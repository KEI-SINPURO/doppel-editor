"""
features/audio_quality.py  ―  音質仕上げ（音量正規化・簡易ノイズゲート）

新しい外部ライブラリは追加せず、moviepy/numpyだけで実装した簡易版です。
本格的なノイズ除去（RNNoise・spectral gating等）ではなく、
無音に近い区間の残留ノイズ（ファン音・環境音など）を抑える程度の効果である点に
注意してください。常時大きく鳴っているノイズの除去には限界があります。
"""

import tempfile
import os
from typing import Optional

import numpy as np

try:
    from moviepy.editor import VideoFileClip
    from moviepy.audio.AudioClip import AudioArrayClip
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False


def normalize_audio_loudness(video_bytes: bytes, target_rms_db: float = -20.0) -> Optional[bytes]:
    """
    動画全体の音声レベルを、ざっくり目標ラウドネス(RMS基準)に合わせて一括ゲイン調整する。
    セグメントごとの発話音量差を細かく均すものではなく、動画全体の音量を
    「小さすぎる／大きすぎる」状態から適正な範囲に近づけるためのシンプルな正規化。

    Args:
        video_bytes  : 対象動画
        target_rms_db: 目標とするRMS音量（dBFS相当）。-20dB前後が一般的な目安。

    Returns:
        正規化後の動画バイト列（音声が無い、または失敗した場合はNone）
    """
    if not HAS_MOVIEPY:
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        if not video.audio:
            video.close()
            return video_bytes

        arr = video.audio.to_soundarray(fps=44100)
        rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)) + 1e-9)
        current_db = 20 * np.log10(rms)
        gain_db = target_rms_db - current_db
        # 無音に近い区間などで過剰増幅しないよう、ゲイン変化量に安全域を設ける
        gain_db = max(-12.0, min(12.0, gain_db))
        gain_factor = 10 ** (gain_db / 20)

        new_audio = video.audio.volumex(gain_factor)  # type: ignore[attr-defined]
        final = video.set_audio(new_audio)

        output_path = tmp_path.replace(".mp4", "_normalized.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"音量正規化エラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def apply_noise_gate(
    video_bytes: bytes,
    threshold_db: float = -45.0,
    reduction_db: float = -18.0,
    window_sec: float = 0.05,
) -> Optional[bytes]:
    """
    簡易ノイズゲート。音声を短い時間窓(window_sec)ごとのRMS音量で見て、
    threshold_db を下回る（＝無音に近い）区間だけ、さらに reduction_db 分下げる。
    発話中の音声はthresholdを上回るためほぼ影響を受けず、無音区間に乗っている
    残留ノイズだけを目立たなくする狙い。

    Args:
        video_bytes  : 対象動画
        threshold_db : この音量を下回る区間を「無音に近い」とみなす閾値
        reduction_db : 無音区間をさらに下げる量（負の値）
        window_sec   : ゲート判定に使う時間窓の長さ（秒）

    Returns:
        処理後の動画バイト列（音声が無い、または失敗した場合はNone）
    """
    if not HAS_MOVIEPY:
        return None

    tmp_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)
        if not video.audio:
            video.close()
            return video_bytes

        fps = int(video.audio.fps or 44100)
        arr = video.audio.to_soundarray(fps=fps)
        if arr.ndim == 1:
            arr = arr[:, np.newaxis]

        n_samples = arr.shape[0]
        window = max(1, int(window_sec * fps))
        threshold_amp = 10 ** (threshold_db / 20)
        reduction_factor = 10 ** (reduction_db / 20)

        gated = arr.copy()
        for start in range(0, n_samples, window):
            end = min(start + window, n_samples)
            chunk = arr[start:end]
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)) + 1e-9)
            if rms < threshold_amp:
                gated[start:end] = chunk * reduction_factor

        gated_audio = AudioArrayClip(gated, fps=fps)
        final = video.set_audio(gated_audio)

        output_path = tmp_path.replace(".mp4", "_gated.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"ノイズゲートエラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass