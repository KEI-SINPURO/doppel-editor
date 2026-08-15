"""
features/generate.py  ―  動画生成（テロップ焼き込み・無音カット・字幕出力）

STEP2「新しい動画に再現する」のコア処理:
  1. auto_cut_by_segments() … 学習したテンポに合わせて無音区間をカット
  2. generate_with_subtitles() … 学習したテロップの見た目（色・サイズ・位置・フォント）で焼き込み
  3. generate_srt() … 字幕ファイル(.srt)の書き出し（編集ソフトへの取り込み用）
"""

import tempfile
import os
import pathlib
import shutil
from typing import Optional

try:
    from moviepy.editor import (
        VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips,
    )
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False

import numpy as np


# ============================================================
# ① 無音カット（学習したテンポの再現）
# ============================================================

def auto_cut_by_segments(
    video_bytes: bytes,
    segments: list,
    padding: float = 0.15,
    min_gap: float = 0.5,
) -> Optional[bytes]:
    """
    Whisperの発話区間(segments)をもとに、区間と区間の間の無音（min_gap秒以上）を自動でカットする。
    「学習したテンポで話していない部分を詰める」ことで、テンポの良い動画に仕上げる基本処理。

    Args:
        video_bytes: 元動画
        segments   : [{"start": float, "end": float, "text": str}, ...]（発話区間 = 残す部分）
        padding    : 各発話区間の前後に残す余白（秒）。呼吸や間を不自然に切らないため
        min_gap    : これ以上の無音はカット対象とする閾値（秒）

    Returns:
        カット後の動画バイト列（失敗時はNone）
    """
    if not HAS_MOVIEPY or not segments:
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        video = VideoFileClip(tmp_path)

        # 発話区間をパディングしつつ、近い区間同士は統合する
        ranges = sorted(
            (max(0.0, s["start"] - padding), min(video.duration, s["end"] + padding))
            for s in segments if s.get("text", "").strip()
        )
        merged: list[tuple[float, float]] = []
        for start, end in ranges:
            if merged and start - merged[-1][1] < min_gap:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        if not merged:
            return video_bytes

        clips = [video.subclip(s, e) for s, e in merged if e > s]
        if not clips:
            return video_bytes

        final = concatenate_videoclips(clips, method="compose")
        output_path = tmp_path.replace(".mp4", "_autocut.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"自動カットエラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


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

                tc_kwargs = dict(
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
