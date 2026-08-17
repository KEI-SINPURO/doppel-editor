"""
features/branding.py  ―  個人素材（ロゴ・BGM・効果音）の適用

「自分だけの素材」機能：
  - ロゴ … 動画の隅に半透明で焼き込む
  - フォント … generate.py 側で TextClip の font パスとして利用（このファイルでは扱わない）
  - BGM … 元の音声の下にループしてミックスする
  - SE  … 指定タイミング（AIが選んだハイライト等）に効果音を重ねる
"""

import tempfile
import os
from typing import Optional, List

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, AudioFileClip,
        CompositeVideoClip, CompositeAudioClip, afx,
    )
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


def mix_bgm(video_bytes: bytes, bgm_path: str, bgm_volume_db: float = -12.0) -> Optional[bytes]:
    """自分のBGMファイルを、元の音声の下にループしてミックスする"""
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
    """指定した複数タイミングに効果音を重ねる（AIが選んだハイライト瞬間など）"""
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