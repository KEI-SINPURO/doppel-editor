"""
features/generate.py  ―  動画生成（テロップ焼き込み・無音カット・トランジション・字幕出力）

STEP2「新しい動画に再現する」のコア処理:
  0. concatenate_source_clips() … 複数の素材動画を1本に結合する（イントロ＋本編＋アウトロ 等）
  1. auto_cut_by_segments() / auto_cut_by_style()
       … 学習したテンポに合わせて無音区間をカット。トランジション（クロスフェード等）にも対応
  1b. auto_cut_with_mapping() / auto_cut_by_style_with_mapping()
       … カット処理と同時に「元動画の時刻→カット後動画の時刻」の変換関数を返す。
         カットで前方の時間が詰まった分、テロップ・ハイライト等の時刻がズレるのを防ぐために使う
  1c. filter_segments_by_keep_flags()
       … AI/ヒューリスティックが「不要」と判定した発言区間を、元のセグメント列から安全に除外する
  2. generate_with_subtitles() … 学習したテロップの見た目（色・サイズ・位置・フォント）で焼き込み
  3. generate_srt() … 字幕ファイル(.srt)の書き出し（編集ソフトへの取り込み用）
"""

import tempfile
import os
import pathlib
import shutil
from typing import Optional, Any, Dict, Callable, List, Tuple

try:
    from moviepy.editor import (
        VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, vfx,
    )
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False

import numpy as np


# ============================================================
# ⓪ 複数素材の結合（メイン素材＋イントロ／アウトロ 等）
# ============================================================

def concatenate_source_clips(clips_bytes: List[bytes]) -> Optional[bytes]:
    """
    複数の素材動画（バイト列のリスト）を、渡された順番で1本につなぎ合わせる。
    「メイン素材＋イントロ＋アウトロ」のように、複数のソースを1つの動画として
    STEP2の再現編集（文字起こし→カット→テロップ焼き込み…）にかけたい場合の前処理。

    Args:
        clips_bytes: 結合したい順番に並んだ動画バイト列のリスト

    Returns:
        結合後の動画バイト列（1本だけならそのまま返す。失敗時はNone）
    """
    if not HAS_MOVIEPY or not clips_bytes:
        return None
    if len(clips_bytes) == 1:
        return clips_bytes[0]

    tmp_paths: List[str] = []
    output_path = None
    try:
        clips = []
        for b in clips_bytes:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                tmp.write(b)
                tmp_paths.append(tmp.name)
            clips.append(VideoFileClip(tmp_paths[-1]))

        final = concatenate_videoclips(clips, method="compose")
        output_path = tmp_paths[0].replace(".mp4", "_merged_source.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        for c in clips:
            c.close()
        final.close()
        return result

    except Exception as e:
        print(f"素材結合エラー: {e}")
        return None
    finally:
        for p in tmp_paths + [output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


# ============================================================
# ① 無音カット・トランジション（学習したテンポ・リズムの再現）
# ============================================================

def _compute_merged_ranges(segments: list, duration: float, padding: float, min_gap: float) -> List[Tuple[float, float]]:
    """発話区間をパディング・統合し、「元動画のタイムライン上で残す区間」のリストを作る。"""
    ranges = sorted(
        (max(0.0, s.get("start", 0) - padding), min(duration, s.get("end", 0) + padding))
        for s in segments if s.get("text", "").strip()
    )
    merged: List[Tuple[float, float]] = []
    for start, end in ranges:
        if merged and start - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _cut_video_core(
    video_bytes: bytes,
    segments: list,
    padding: float,
    min_gap: float,
    transition: str = "cut",
    transition_duration: float = 0.3,
):
    """
    実際のカット処理の中核。動画を一度だけ開き、
    (残す区間の計算 → 切り出し → トランジションを付けて結合) までを1パスで行う。

    transition:
        "cut"        … 何もしない（通常のハードカット）
        "crossfade"  … 前後のカットを重ねて溶暗・溶明でつなぐ（ディゾルブ）
        "fade_black" … 各カットの前後を一瞬黒に落としてからつなぐ

    Returns:
        (カット後の動画バイト列 or None, 元動画上で残した区間のリスト[(start,end),...])
    """
    if not HAS_MOVIEPY or not segments:
        return None, []

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        video = VideoFileClip(tmp_path)

        merged = _compute_merged_ranges(segments, video.duration, padding, min_gap)
        if not merged:
            video.close()
            return video_bytes, []

        clips = [video.subclip(s, min(e, video.duration)) for s, e in merged if e > s]
        if not clips:
            video.close()
            return video_bytes, []

        if transition == "crossfade" and len(clips) > 1:
            td = min(transition_duration, min(c.duration for c in clips) / 2)
            prepared = [clips[0]] + [c.crossfadein(td) for c in clips[1:]]
            # padding は moviepy 1.0.3では float を渡せるが、型スタブ上は int 宣言のため
            # Pylanceが誤検知する（intに丸めると短いクリップでクロスフェードが効かなくなるため
            # あえてfloatのまま渡している）
            final = concatenate_videoclips(prepared, method="compose", padding=-td)  # type: ignore[arg-type]
        elif transition == "fade_black" and len(clips) > 1:
            td = min(transition_duration, min(c.duration for c in clips) / 2)
            prepared = []
            for i, c in enumerate(clips):
                cc = c
                # fadein / fadeout も moviepy 1.0.3 に実在するが型スタブ未収録のため誤検知になる
                if i > 0:
                    cc = cc.fx(vfx.fadein, td)  # type: ignore[attr-defined]
                if i < len(clips) - 1:
                    cc = cc.fx(vfx.fadeout, td)  # type: ignore[attr-defined]
                prepared.append(cc)
            final = concatenate_videoclips(prepared, method="compose")
        else:
            final = concatenate_videoclips(clips, method="compose")

        output_path = tmp_path.replace(".mp4", "_autocut.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result, merged

    except Exception as e:
        print(f"自動カットエラー: {e}")
        return None, []
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def build_time_mapping(merged_ranges: List[Tuple[float, float]], transition_overlap: float = 0.0) -> Callable[[float], float]:
    """
    merged_ranges（元動画タイムライン上で残した区間、開始時刻順）から、
    「元動画の時刻 → カット後動画の時刻」への変換関数を作る。
    テロップ・ハイライト・ズーム演出などの時刻を、カットで詰まった後のタイムラインに
    正しく合わせ込むために使う（カットで前方の時間が詰まった分、後ろの時刻はズレるため）。

    Args:
        merged_ranges     : _compute_merged_ranges() が返す、残した区間のリスト
        transition_overlap: クロスフェード等で前後のカットが重なる場合の概算の重なり秒数
                             （_cut_video_core の transition_duration とだいたい合わせる。
                             クリップが短くクランプされた場合は厳密には一致しない近似値）
    """
    offsets = []
    cumulative = 0.0
    for i, (s, e) in enumerate(merged_ranges):
        if i > 0:
            cumulative = max(0.0, cumulative - transition_overlap)
        offsets.append((s, e, cumulative))
        cumulative += max(0.0, e - s)

    def _map(t: float) -> float:
        prev_cum_end = 0.0
        for s, e, cum in offsets:
            if t < s:
                return prev_cum_end
            if s <= t <= e:
                return cum + (t - s)
            prev_cum_end = cum + (e - s)
        return prev_cum_end

    return _map


def auto_cut_by_segments(
    video_bytes: bytes,
    segments: list,
    padding: float = 0.15,
    min_gap: float = 0.5,
    transition: str = "cut",
) -> Optional[bytes]:
    """
    Whisperの発話区間(segments)をもとに、区間と区間の間の無音（min_gap秒以上）を自動でカットする。
    「学習したテンポで話していない部分を詰める」ことで、テンポの良い動画に仕上げる基本処理。

    Args:
        video_bytes: 元動画
        segments   : [{"start": float, "end": float, "text": str}, ...]（発話区間 = 残す部分）
        padding    : 各発話区間の前後に残す余白（秒）。呼吸や間を不自然に切らないため
        min_gap    : これ以上の無音はカット対象とする閾値（秒）
        transition : "cut" / "crossfade" / "fade_black"（NEW）

    Returns:
        カット後の動画バイト列（失敗時はNone）
    """
    result, _ = _cut_video_core(video_bytes, segments, padding, min_gap, transition=transition)
    return result


def auto_cut_with_mapping(
    video_bytes: bytes,
    segments: list,
    padding: float = 0.15,
    min_gap: float = 0.5,
    transition: str = "cut",
):
    """
    auto_cut_by_segments と同じ処理を行い、あわせて時刻変換関数
    （元動画の時刻 → カット後動画の時刻）も返す。

    Returns:
        (カット後の動画バイト列 or None, 時刻変換関数 or None)
    """
    result, merged = _cut_video_core(video_bytes, segments, padding, min_gap, transition=transition)
    if result is None:
        return None, None
    if not merged:
        # カットが実質発生しなかった（元動画そのまま） → 変換不要
        return result, (lambda t: t)
    overlap = 0.3 if transition == "crossfade" and len(merged) > 1 else 0.0
    return result, build_time_mapping(merged, transition_overlap=overlap)


def filter_segments_by_keep_flags(original_segments: list, plan_segments: list) -> list:
    """
    元のWhisperセグメント(original_segments。音声全体を隙間なくカバーする)のうち、
    AI/ヒューリスティックが "keep": false と判定した区間に大きく重なるものだけを除外する。

    plan_segments（ai/model.py の generate_edit_plan や ai/heuristic.py の
    build_heuristic_edit_plan が返す区間）は、テンポよく読める長さに要約されていて
    original_segments と1:1で対応しない場合がある。そのため直接 plan_segments の
    時刻でカットするのではなく、「keep=false の時間帯と50%以上重なる元セグメントだけを
    落とす」という保守的な方法にして、意図しない大量カットを防いでいる。

    Args:
        original_segments: Whisperの全発話区間（カット処理のベースにする側）
        plan_segments     : "keep" フィールドを含む区間リスト

    Returns:
        original_segments のうち、明確に不要と判定された区間を除いたリスト。
        全部除外されてしまった場合は安全側に倒して original_segments をそのまま返す。
    """
    drop_ranges = [
        (s.get("start", 0), s.get("end", 0))
        for s in plan_segments if not s.get("keep", True)
    ]
    if not drop_ranges:
        return original_segments

    kept = []
    for seg in original_segments:
        s, e = seg.get("start", 0), seg.get("end", 0)
        seg_duration = max(e - s, 0.01)
        dropped = False
        for ds, de in drop_ranges:
            overlap = min(e, de) - max(s, ds)
            if overlap > 0 and overlap / seg_duration > 0.5:
                dropped = True
                break
        if not dropped:
            kept.append(seg)

    return kept or original_segments


def _decide_cut_params(style_data: Optional[dict]) -> Tuple[float, float]:
    """学習した「カットのリズム」からpadding/min_gapを決める。"""
    style_data = style_data or {}
    rhythm = style_data.get("rhythm", {}) or {}
    avg_interval = rhythm.get("avg_interval")

    if avg_interval and avg_interval < 3:
        return 0.10, 0.35
    elif avg_interval and avg_interval > 8:
        return 0.20, 0.7
    return 0.15, 0.5


def decide_transition_from_style(style_data: Optional[dict]) -> str:
    """
    学習した「カットのリズムパターン」から、それらしいトランジションを自動で決める。
    「学習したリズムにおまかせ」オプション用。
      一定リズム型 → カット（メリハリを保つ）
      緩急型       → クロスフェード（滑らかな緩急）
      不規則型     → 暗転（場面の切り替わりを強調）
    """
    rhythm_pattern = (style_data or {}).get("rhythm", {}).get("rhythm_pattern", "") or ""
    if "一定リズム" in rhythm_pattern:
        return "cut"
    if "緩急" in rhythm_pattern:
        return "crossfade"
    if "不規則" in rhythm_pattern:
        return "fade_black"
    return "cut"


def auto_cut_by_style(
    video_bytes: bytes,
    segments: list,
    style_data: Optional[dict] = None,
    transition: str = "cut",
) -> Optional[bytes]:
    """
    学習した「カットのリズム」(style_data["rhythm"])を padding・min_gap に反映したうえで
    auto_cut_by_segments を呼ぶラッパー。学習データが無い場合は従来通りのデフォルト値で動作する。
    """
    padding, min_gap = _decide_cut_params(style_data)
    return auto_cut_by_segments(video_bytes, segments, padding=padding, min_gap=min_gap, transition=transition)


def auto_cut_by_style_with_mapping(
    video_bytes: bytes,
    segments: list,
    style_data: Optional[dict] = None,
    transition: str = "cut",
):
    """auto_cut_by_style と同じロジックで、時刻変換関数もあわせて返す版。"""
    padding, min_gap = _decide_cut_params(style_data)
    return auto_cut_with_mapping(video_bytes, segments, padding=padding, min_gap=min_gap, transition=transition)


# ============================================================
# ② テロップ焼き込み（学習したスタイルの再現）
# ============================================================

def generate_with_subtitles(
    video_bytes: bytes,
    segments: list,
    style: dict,
    export_settings: Optional[dict] = None,
) -> tuple[Optional[bytes], Optional[str]]:
    """
    動画にテロップを焼き込んで書き出す。

    Args:
        video_bytes: 元動画のバイト列
        segments:
            [{"start": float, "end": float, "text": str,
              "font_color": str(任意/セグメント別上書き),
              "font_size": int(任意), "position": str(任意)}, ...]
        style:
            {"font_color": str, "font_size": int, "position": str,
             "stroke": bool, "animation": str, "font_path": str(任意・自分のフォントファイル)}
        export_settings:
            {"resolution":(w,h)|None, "fps":int|None, "bitrate":str, "codec":str, "ext":str,
             "save_path":str|None, "save_method":str}

    Returns:
        (動画バイト列, ローカル保存パス or None)。失敗時は (None, None)
    """
    if not HAS_MOVIEPY:
        print("moviepy がインストールされていません: pip install moviepy")
        return None, None

    export_settings = export_settings or {}
    target_res = export_settings.get("resolution")
    target_fps = export_settings.get("fps")
    bitrate = export_settings.get("bitrate", "12M")
    codec = export_settings.get("codec", "libx264")
    ext = export_settings.get("ext", "mp4")
    save_path = export_settings.get("save_path")
    save_method = export_settings.get("save_method", "ブラウザでダウンロード")

    font_color = style.get("font_color", "white")
    font_size = int(style.get("font_size", 40))
    position_key = style.get("position", "下部")
    use_stroke = style.get("stroke", True)
    animation = style.get("animation", "なし")
    font_path = style.get("font_path")  # 個人素材（自分のフォント）。Noneならデフォルトフォント

    pos_map = {"下部": ("center", "bottom"), "中央": ("center", "center"), "上部": ("center", "top")}
    pos = pos_map.get(position_key, ("center", "bottom"))
    stroke_color = "black" if use_stroke else None
    stroke_width = 2 if use_stroke else 0

    tmp_path = None
    output_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)

        if target_res:
            video = video.resize(target_res)  # type: ignore[attr-defined]

        clips = [video]

        for segment in segments:
            start = float(segment.get("start", 0))
            end = float(segment.get("end", 0))
            text = str(segment.get("text", "")).strip()

            if not text or end <= start or start >= video.duration:
                continue
            end = min(end, video.duration)
            duration = end - start

            try:
                seg_color = segment.get("font_color", font_color)
                seg_size = int(segment.get("font_size", font_size))
                seg_pos_key = segment.get("position", position_key)
                seg_pos = pos_map.get(seg_pos_key, pos)

                # ★ 値の型が混在する(int/str/tuple/None)辞書なので、Dict[str, Any]と明示する。
                #   これが無いと **tc_kwargs で展開した際に、各キーワード引数の型が
                #   「あり得る全ての値の型の合体」とみなされてしまい、誤検知の原因になる。
                tc_kwargs: Dict[str, Any] = dict(
                    fontsize=seg_size, color=seg_color,
                    stroke_color=stroke_color, stroke_width=stroke_width,
                    method="caption", size=(video.w - 80, None), align="center",
                )
                if font_path and os.path.exists(font_path):
                    tc_kwargs["font"] = font_path

                txt_clip = TextClip(text, **tc_kwargs)
                txt_clip = _apply_animation(txt_clip, animation, duration)
                txt_clip = txt_clip.set_position(seg_pos).set_start(start).set_end(end)
                clips.append(txt_clip)

            except Exception as e:
                print(f"テロップ生成スキップ [{text[:20]}]: {e}")
                continue

        final = CompositeVideoClip(clips)
        output_path = tmp_path.replace(".mp4", f"_output.{ext}")
        write_fps = target_fps if target_fps else video.fps

        final.write_videofile(
            output_path, fps=write_fps, codec=codec, audio_codec="aac",
            ffmpeg_params=["-b:v", bitrate], logger=None, threads=4,
        )

        video.close()
        final.close()

        with open(output_path, "rb") as f:
            result_bytes = f.read()

        local_saved = None
        if save_path and save_method == "フォルダに直接保存":
            try:
                dest_dir = pathlib.Path(os.path.expanduser(save_path))
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / f"doppel_output.{ext}"
                shutil.copy2(output_path, dest_file)
                local_saved = str(dest_file)
            except Exception as e:
                print(f"ローカル保存エラー: {e}")

        return result_bytes, local_saved

    except Exception as e:
        print(f"テロップ生成エラー: {e}")
        return None, None

    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _apply_animation(clip, animation: str, duration: float):
    """テロップクリップにアニメーションを適用する"""
    fade = min(0.3, duration * 0.2)
    if animation == "フェードイン":
        return clip.crossfadein(fade)
    elif animation == "フェードアウト":
        return clip.crossfadeout(fade)
    elif animation == "フェードイン・アウト":
        return clip.crossfadein(fade).crossfadeout(fade)
    elif animation == "バウンス":
        def bounce_pos(t):
            progress = t / max(duration, 0.01)
            bounce = abs(np.sin(progress * np.pi * 2)) * max(0, 1 - progress * 3) * 15
            return ("center", int(bounce))
        return clip.set_position(bounce_pos)
    return clip


# ============================================================
# ③ SRT 字幕ファイル生成
# ============================================================

def generate_srt(segments: list) -> str:
    """Whisper/編集プランのセグメントから SRT 字幕ファイルを生成する"""

    def _fmt(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h = ms // 3_600_000; ms %= 3_600_000
        m = ms // 60_000; ms %= 60_000
        s = ms // 1_000; ms %= 1_000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    counter = 1
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = max(float(seg.get("end", start + 1.0)), start + 0.1)
        lines += [str(counter), f"{_fmt(start)} --> {_fmt(end)}", text, ""]
        counter += 1

    return "\n".join(lines)