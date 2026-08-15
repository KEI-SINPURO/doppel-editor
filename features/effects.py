"""
features/effects.py  ―  動画エフェクト

STEP2「新しい動画に再現する」で、学習済みスタイルをもとに実際に適用するエフェクト群。
今回のスコープ（分析→再現のみ）で使わない機能（揺れ・フラッシュ・絵文字オーバーレイ等）は
コードを読みやすくするため削除しています。必要になったら features/branding.py と
同じ要領で追加してください。
"""

import tempfile
import os
from typing import Optional

import cv2
import numpy as np

try:
    from moviepy.editor import VideoFileClip
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False


def apply_color_grade(video_bytes: bytes, style: str = "normal") -> Optional[bytes]:
    """
    学習した色調（暖色系／寒色系など）に合わせてカラーグレーディングを適用する。
    style: "vivid" / "cinema" / "warm" / "cool" / "retro" / "normal"
    """
    tmp_path = None
    output_path = None
    final_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        output_path = tmp_path.replace(".mp4", "_graded_noaudio.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            out.write(_apply_grade_to_frame(frame, style))

        cap.release()
        out.release()

        if not HAS_MOVIEPY:
            with open(output_path, "rb") as f:
                return f.read()

        final_path = tmp_path.replace(".mp4", "_graded.mp4")
        original = VideoFileClip(tmp_path)
        graded_clip = VideoFileClip(output_path)

        if original.audio:
            graded_clip = graded_clip.set_audio(original.audio)

        graded_clip.write_videofile(
            final_path, codec="libx264", audio_codec="aac", logger=None, threads=4,
        )

        with open(final_path, "rb") as f:
            result = f.read()

        original.close()
        graded_clip.close()
        return result

    except Exception as e:
        print(f"カラーグレーディングエラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path, final_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _apply_grade_to_frame(frame, style: str) -> np.ndarray:
    """フレームにカラーグレードを適用"""
    if style == "vivid":
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.3, 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.1, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    elif style == "cinema":
        result = frame.astype(np.float32)
        result[:, :, 0] = np.clip(result[:, :, 0] * 1.1, 0, 255)
        result[:, :, 2] = np.clip(result[:, :, 2] * 0.88, 0, 255)
        result = np.clip(result * 0.93 + 8, 0, 255)
        return result.astype(np.uint8)
    elif style == "warm":
        result = frame.astype(np.float32)
        result[:, :, 2] = np.clip(result[:, :, 2] * 1.15, 0, 255)
        result[:, :, 0] = np.clip(result[:, :, 0] * 0.92, 0, 255)
        return result.astype(np.uint8)
    elif style == "cool":
        result = frame.astype(np.float32)
        result[:, :, 0] = np.clip(result[:, :, 0] * 1.15, 0, 255)
        result[:, :, 2] = np.clip(result[:, :, 2] * 0.92, 0, 255)
        return result.astype(np.uint8)
    elif style == "retro":
        result = frame.astype(np.float32)
        result[:, :, 1] = np.clip(result[:, :, 1] * 0.88, 0, 255)
        result = np.clip(result * 0.88 + 18, 0, 255)
        return result.astype(np.uint8)
    else:
        return frame


def apply_zoom_effect(video_bytes: bytes, zoom_points: list) -> Optional[bytes]:
    """指定した時間帯にズームイン→ズームアウトの演出を入れる"""
    if not HAS_MOVIEPY:
        return None

    tmp_path = None
    output_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)

        def zoom_effect(get_frame, t):
            frame = get_frame(t)
            for zp in zoom_points:
                if zp["start"] <= t <= zp["end"]:
                    progress = (t - zp["start"]) / max(zp["end"] - zp["start"], 0.01)
                    zoom_factor = 1.0 + 0.15 * np.sin(progress * np.pi)
                    h, w = frame.shape[:2]
                    new_h = int(h / zoom_factor)
                    new_w = int(w / zoom_factor)
                    y1 = (h - new_h) // 2
                    x1 = (w - new_w) // 2
                    cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
                    return cv2.resize(cropped, (w, h))
            return frame

        final = video.fl(zoom_effect)
        output_path = tmp_path.replace(".mp4", "_zoom.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()

        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"ズームエフェクトエラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def detect_highlight_moments(video_bytes: bytes, segments: list) -> list:
    """
    盛り上がりシーンを自動検出する（キーワード＋音量ベース）。
    AIによる編集プラン（ai/model.py の generate_edit_plan）が使えない場合の
    フォールバックとしても利用する。
    """
    highlights = []

    highlight_keywords = [
        "すごい", "やばい", "えー", "マジ", "最高", "嘘",
        "笑", "ウケる", "びっくり", "信じられない", "待って",
        "え？", "本当に", "絶対", "神", "天才", "最悪",
        "やった", "勝った", "負けた", "終わった", "きた",
    ]

    for segment in segments:
        text = segment.get("text", "")
        score = sum(1 for kw in highlight_keywords if kw in text)
        if "！" in text or "!?" in text:
            score += 1
        if len(text) < 10 and score > 0:
            score += 1
        if score > 0:
            highlights.append({
                "timestamp": segment["start"], "end": segment["end"],
                "type": "keyword", "score": score, "text": text,
            })

    try:
        tmp_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        if HAS_MOVIEPY:
            from moviepy.editor import VideoFileClip as _VFC
            video = _VFC(tmp_path)
            if video.audio:
                audio_array = video.audio.to_soundarray()
                chunk_samples = int(video.audio.fps * 0.5)
                for i in range(0, len(audio_array) - chunk_samples, chunk_samples):
                    chunk = audio_array[i:i + chunk_samples]
                    volume = float(np.mean(np.abs(chunk)))
                    if volume > 0.15:
                        timestamp = i / video.audio.fps
                        highlights.append({
                            "timestamp": round(timestamp, 1), "end": round(timestamp + 0.5, 1),
                            "type": "loud", "score": round(volume * 10, 2), "text": "",
                        })
            video.close()

        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    except Exception as e:
        print(f"音量検出エラー: {e}")

    highlights.sort(key=lambda x: x["score"], reverse=True)
    return highlights[:10]
