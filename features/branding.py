"""
features/branding.py  ―  個人素材（ロゴ・BGM・効果音・ナレーション）の適用

「自分だけの素材」機能：
  - ロゴ … 動画の隅に半透明で焼き込む
  - フォント … generate.py 側で TextClip の font パスとして利用（このファイルでは扱わない）
  - BGM … 元の音声の下にループしてミックスする（NEW: 発話区間の自動ダッキングに対応）
  - SE  … 指定タイミング（AIが選んだハイライト等）に効果音を重ねる
          （NEW: insert_multiple_se で、場面ごとに異なる種類の効果音を使い分けられる）
  - ナレーション（NEW） … ボイスオーバー音声を重ね、その区間だけ元の音声をダッキングする

【今回のアップデート（実際の編集で「足りていなかった」部分を補う）】
  プロの編集者が当たり前に行っているが、これまで未実装だった2点を追加した：
    1. BGMの自動ダッキング ― セリフ中はBGMを下げ、間奏部分では聞かせる。
       これまでは mix_bgm() が動画全体で一定音量のままBGMを重ねていた。
    2. 効果音（SE）の場面ごとの使い分け ― 「驚き」「達成」「失敗」等、瞬間のトーンに
       合わせて異なる効果音を鳴らす。これまでは insert_se() が1種類の効果音を
       全ハイライト箇所に一律で使っていた（insert_multiple_se() で複数種類に対応）。
"""

import tempfile
import os
from typing import List, Optional, Tuple

import numpy as np

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, AudioFileClip,
        CompositeVideoClip, CompositeAudioClip, concatenate_audioclips, afx,
    )
    from moviepy.audio.AudioClip import AudioArrayClip
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False


def overlay_logo(
    video_bytes: bytes,
    logo_path: str,
    position: str = "bottom-right",
    opacity: float = 0.85,
    scale: float = 0.12,
) -> Optional[bytes]:
    """動画の隅にロゴ画像を焼き込む"""
    if not HAS_MOVIEPY or not logo_path or not os.path.exists(logo_path):
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        logo_w = max(1, int(video.w * scale))
        logo = (
            ImageClip(logo_path)
            .set_duration(video.duration)
            .resize(width=logo_w)
            .set_opacity(opacity)
        )

        margin = int(video.w * 0.02)
        pos_map = {
            "bottom-right": (video.w - logo.w - margin, video.h - logo.h - margin),
            "bottom-left": (margin, video.h - logo.h - margin),
            "top-right": (video.w - logo.w - margin, margin),
            "top-left": (margin, margin),
        }
        logo = logo.set_position(pos_map.get(position, pos_map["bottom-right"]))

        final = CompositeVideoClip([video, logo])
        output_path = tmp_path.replace(".mp4", "_logo.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"ロゴ焼き込みエラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _apply_speech_ducking(bgm_clip, speech_segments: list, duck_extra_db: float, ramp_sec: float):
    """
    BGMクリップに対して、発話区間だけ音量をさらに下げる「自動ダッキング」を適用する。

    features/audio_quality.py の apply_noise_gate と同じ、
    to_soundarray()で丸ごと配列化 → ゲイン処理 → AudioArrayClipで戻す、という
    このリポジトリで実績のある実装パターンに揃えている（動作の信頼性を優先）。

    Args:
        bgm_clip      : 既にvolumex等で基準音量を適用済みのBGM AudioClip
        speech_segments: [{"start","end"}, ...]（発話区間。カット後タイムライン基準）
        duck_extra_db : 発話区間でさらに下げる量（負の値。例: -6.0）
        ramp_sec      : 発話の開始・終了前後で滑らかに音量を変化させる時間（秒）
    """
    fps = int(bgm_clip.fps or 44100)
    arr = bgm_clip.to_soundarray(fps=fps)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    n_samples = arr.shape[0]

    duck_factor = 10 ** (duck_extra_db / 20)
    ramp_samples = max(1, int(ramp_sec * fps))

    gain = np.ones(n_samples, dtype=np.float64)
    for seg in speech_segments:
        s, e = seg.get("start", 0), seg.get("end", 0)
        if e <= s:
            continue
        s_idx = max(0, min(n_samples, int(s * fps)))
        e_idx = max(0, min(n_samples, int(e * fps)))
        if s_idx >= e_idx:
            continue

        gain[s_idx:e_idx] = np.minimum(gain[s_idx:e_idx], duck_factor)

        ramp_start = max(0, s_idx - ramp_samples)
        if ramp_start < s_idx:
            fade_in = np.linspace(1.0, duck_factor, s_idx - ramp_start)
            gain[ramp_start:s_idx] = np.minimum(gain[ramp_start:s_idx], fade_in)

        ramp_end = min(n_samples, e_idx + ramp_samples)
        if e_idx < ramp_end:
            fade_out = np.linspace(duck_factor, 1.0, ramp_end - e_idx)
            gain[e_idx:ramp_end] = np.minimum(gain[e_idx:ramp_end], fade_out)

    gated = arr * gain[:, np.newaxis]
    return AudioArrayClip(gated, fps=fps)


def mix_bgm(
    video_bytes: bytes,
    bgm_path: str,
    bgm_volume_db: float = -12.0,
    speech_segments: Optional[list] = None,
    duck_extra_db: float = -6.0,
    duck_ramp_sec: float = 0.3,
) -> Optional[bytes]:
    """
    自分のBGMファイルを、元の音声の下にループしてミックスする。

    Args:
        video_bytes    : 対象動画
        bgm_path       : BGMファイルのパス
        bgm_volume_db  : BGMの基準音量（dB）
        speech_segments: 【NEW】渡すと、この区間だけBGM音量をさらに duck_extra_db 下げる
                         「自動ダッキング」を行う（プロの編集の基本テクニック）。
                         省略時は従来通り、動画全体で一定音量のままミックスする。
        duck_extra_db  : 発話区間でさらに下げる量（負の値。既定-6dB）
        duck_ramp_sec  : ダッキングの立ち上がり・立ち下がりを滑らかにする時間（秒）
    """
    if not HAS_MOVIEPY or not bgm_path or not os.path.exists(bgm_path):
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        bgm = AudioFileClip(bgm_path)

        volume_factor = 10 ** (bgm_volume_db / 20)  # dB → 倍率
        # audio_loop / volumex は moviepy 1.0.3 に実在するが、型スタブに未収録のため誤検知になる
        bgm_looped = afx.audio_loop(bgm, duration=video.duration).volumex(volume_factor)  # type: ignore[attr-defined]

        if speech_segments:
            try:
                bgm_looped = _apply_speech_ducking(bgm_looped, speech_segments, duck_extra_db, duck_ramp_sec)
            except Exception as e:
                # ダッキング処理自体が失敗しても、BGMミックス自体は（一定音量で）続行する
                print(f"BGMダッキング処理エラー（一定音量でのミックスに切り替えます）: {e}")

        new_audio = CompositeAudioClip([video.audio, bgm_looped]) if video.audio else bgm_looped
        final = video.set_audio(new_audio)

        output_path = tmp_path.replace(".mp4", "_bgm.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        bgm.close()
        final.close()
        return result

    except Exception as e:
        print(f"BGMミックスエラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def insert_se(
    video_bytes: bytes,
    se_path: str,
    timestamps: List[float],
    se_volume_db: float = 0.0,
) -> Optional[bytes]:
    """指定した複数タイミングに、同じ1種類の効果音を重ねる（AIが選んだハイライト瞬間など）"""
    if not HAS_MOVIEPY or not se_path or not os.path.exists(se_path) or not timestamps:
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        volume_factor = 10 ** (se_volume_db / 20)

        se_clips = [
            AudioFileClip(se_path).volumex(volume_factor).set_start(t)  # type: ignore[attr-defined]
            for t in timestamps if 0 <= t < video.duration
        ]
        if not se_clips:
            return video_bytes

        tracks = ([video.audio] if video.audio else []) + se_clips
        final = video.set_audio(CompositeAudioClip(tracks))

        output_path = tmp_path.replace(".mp4", "_se.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"効果音挿入エラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def insert_multiple_se(
    video_bytes: bytes,
    timed_se: List[Tuple[float, Optional[bytes]]],
    se_volume_db: float = 0.0,
) -> Optional[bytes]:
    """
    【NEW】insert_se() の「場面ごとに異なる効果音」対応版。
    (タイムスタンプ, 効果音のWAVバイト列) のペアのリストを受け取り、それぞれのタイミングに
    それぞれ異なる効果音を重ねる。「AIにおまかせ」でSEを場面のトーンに応じて使い分ける機能
    （features/se_presets.py の get_se_bytes_by_mood と ai/model.py の se_mood）で使用する。

    Args:
        video_bytes  : 対象動画
        timed_se     : [(タイムスタンプ(秒), 効果音のWAVバイト列 または None), ...]。
                       get_se_bytes_by_mood() は未知のmoodに対してNoneを返しうるため、
                       Noneを許容する型にしている（該当ペアは下記ループで安全にスキップされる）
        se_volume_db : 効果音全体の音量調整（dB）

    Returns:
        処理後の動画バイト列。有効な組み合わせが1件も無ければ元のvideo_bytesをそのまま返す。
        失敗時はNone。
    """
    if not HAS_MOVIEPY or not timed_se:
        return None

    tmp_path = output_path = None
    se_tmp_paths: List[str] = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        volume_factor = 10 ** (se_volume_db / 20)

        se_clips = []
        for t, se_bytes in timed_se:
            if se_bytes is None or not (0 <= t < video.duration):
                continue
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as sf:
                sf.write(se_bytes)
                se_tmp_paths.append(sf.name)
            se_clips.append(AudioFileClip(se_tmp_paths[-1]).volumex(volume_factor).set_start(t))  # type: ignore[attr-defined]

        if not se_clips:
            video.close()
            return video_bytes

        tracks = ([video.audio] if video.audio else []) + se_clips
        final = video.set_audio(CompositeAudioClip(tracks))

        output_path = tmp_path.replace(".mp4", "_multise.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"複数効果音挿入エラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path] + se_tmp_paths:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def add_narration(
    video_bytes: bytes,
    narration_path: str,
    start_at: float = 0.0,
    duck_db: float = -15.0,
) -> Optional[bytes]:
    """
    ナレーション（ボイスオーバー）音声を動画に重ねる。
    ナレーションが再生されている区間だけ、元の動画の音声を duck_db だけ下げる
    （ダッキング）ことで、ナレーションを聞き取りやすくする。

    Args:
        video_bytes    : 対象動画
        narration_path : ナレーション音声ファイルのパス（mp3/wav等）
        start_at        : ナレーションを開始する動画上の時刻（秒）。基本は動画冒頭(0.0)
        duck_db         : ナレーション再生中、元の音声を何dB下げるか（負の値。例: -15.0）

    Returns:
        合成後の動画バイト列（失敗時はNone）
    """
    if not HAS_MOVIEPY or not narration_path or not os.path.exists(narration_path):
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        narration = AudioFileClip(narration_path)

        start_at = max(0.0, min(start_at, video.duration))
        narration_len = min(narration.duration, video.duration - start_at)
        if narration_len <= 0:
            video.close()
            narration.close()
            return video_bytes

        narration_clip = narration.subclip(0, narration_len).set_start(start_at)

        if video.audio:
            duck_factor = 10 ** (duck_db / 20)
            segments = []
            if start_at > 0:
                segments.append(video.audio.subclip(0, start_at))
            segments.append(video.audio.subclip(start_at, start_at + narration_len).volumex(duck_factor))  # type: ignore[attr-defined]
            if start_at + narration_len < video.duration:
                segments.append(video.audio.subclip(start_at + narration_len, video.duration))
            ducked_original = concatenate_audioclips(segments)
            combined_audio = CompositeAudioClip([ducked_original, narration_clip])
        else:
            combined_audio = narration_clip

        final = video.set_audio(combined_audio)
        output_path = tmp_path.replace(".mp4", "_narration.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        narration.close()
        final.close()
        return result

    except Exception as e:
        print(f"ナレーション合成エラー: {e}")
        return None
    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass