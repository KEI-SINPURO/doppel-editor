"""
features/effects.py  ―  動画エフェクト

STEP2「新しい動画に再現する」で、学習済みスタイルをもとに実際に適用するエフェクト群。

  apply_color_grade()       … 色調補正
  apply_zoom_effect()       … ハイライト部分のズームイン/アウト演出
  apply_speed_ramp()        … ハイライト部分のスロー/早送り演出（NEW）
  auto_reframe()            … 顔検出ベースの自動リフレーム（横→縦型 等）（NEW）
  detect_highlight_moments()… 盛り上がりシーンの自動検出（キーワード＋音量ベース）

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
    from moviepy.editor import VideoFileClip, concatenate_videoclips, vfx
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


def apply_speed_ramp(video_bytes: bytes, speed_points: list, factor: float = 0.6) -> Optional[bytes]:
    """
    指定した時間帯だけ再生速度を変える（主にハイライト部分のスローモーション演出に使用）。
    factor < 1.0 でスロー、factor > 1.0 で早送り。

    Args:
        video_bytes : 対象動画
        speed_points: [{"start": float, "end": float}, ...]（動画の現在のタイムライン基準の時刻）
        factor      : 適用する速度倍率（0.6なら6割の速さ＝ゆるやかなスロー）

    【注意】moviepyの speedx は音声もそのまま速度変換するため、
    スロー再生にすると音声のピッチも下がります（早送りだとピッチが上がります）。
    音声のピッチを保ったまま速度だけ変えるタイムストレッチ処理は今回未対応です。
    気になる場合は、ハイライト演出を「ズームのみ」にしてください。
    """
    if not HAS_MOVIEPY or not speed_points:
        return None

    tmp_path = None
    output_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        video = VideoFileClip(tmp_path)

        # 区間の重なりを統合しておく（ハイライトが隣接・重複していても二重適用しないため）
        raw_ranges = sorted(
            (max(0.0, p.get("start", 0)), min(video.duration, p.get("end", 0)))
            for p in speed_points
        )
        merged: list[tuple[float, float]] = []
        for s, e in raw_ranges:
            if e <= s:
                continue
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        if not merged:
            video.close()
            return video_bytes

        clips = []
        cursor = 0.0
        for s, e in merged:
            if s > cursor:
                clips.append(video.subclip(cursor, s))
            # speedx は moviepy 1.0.3 に実在するが、型スタブ(moviepy.video.fx.all)に
            # 未収録のため、Pylanceの reportAttributeAccessIssue が誤検知として出る
            clips.append(video.subclip(s, e).fx(vfx.speedx, factor))  # type: ignore[attr-defined]
            cursor = e
        if cursor < video.duration:
            clips.append(video.subclip(cursor, video.duration))

        final = concatenate_videoclips(clips, method="compose")
        output_path = tmp_path.replace(".mp4", "_speedramp.mp4")
        final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(output_path, "rb") as f:
            result = f.read()
        video.close()
        final.close()
        return result

    except Exception as e:
        print(f"速度変化エラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


_FACE_CASCADE = None
_FACE_CASCADE_LOAD_FAILED = False


def _get_face_cascade():
    """
    顔検出用のHaar Cascadeを読み込む（シングルトン）。
    opencv-python にファイルが同梱されているため、追加インストール・ダウンロードは不要。
    読み込みに失敗した場合は None を返し、呼び出し側は中央クロップにフォールバックする。
    """
    global _FACE_CASCADE, _FACE_CASCADE_LOAD_FAILED
    if _FACE_CASCADE is not None:
        return _FACE_CASCADE
    if _FACE_CASCADE_LOAD_FAILED:
        return None
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"  # type: ignore[attr-defined]
        # CascadeClassifier も同様に、opencv-pythonの型スタブに未収録の場合があるための誤検知
        cascade = cv2.CascadeClassifier(cascade_path)  # type: ignore[attr-defined]
        if cascade.empty():
            raise RuntimeError("cascade empty")
        _FACE_CASCADE = cascade
        return _FACE_CASCADE
    except Exception as e:
        print(f"顔検出モデルの読み込みに失敗（中央クロップにフォールバックします）: {e}")
        _FACE_CASCADE_LOAD_FAILED = True
        return None


def auto_reframe(video_bytes: bytes, target_ratio: str = "9:16", smoothing: float = 0.25) -> Optional[bytes]:
    """
    横動画をShorts/Reels/TikTok等の縦型・スクエア比率に自動リフレームする。

    OpenCVの顔検出（Haar Cascade。opencv-python同梱・追加インストール不要）を使い、
    映っている人物を検出できたフレームではそちらにクロップ窓を寄せ、
    検出できないフレーム（横顔・後ろ姿・ゲーム画面など）では直前の位置を維持する。
    急に飛ばないよう、指数移動平均でクロップ位置をなめらかに追従させる。

    Args:
        video_bytes : 元動画（横向きを想定）
        target_ratio: "9:16"（Shorts/Reels/TikTok）/ "4:5"（Instagramフィード）/ "1:1"（正方形）
        smoothing   : 顔位置への追従の強さ(0~1)。大きいほど素早く追従するが、揺れやすくなる。

    Returns:
        リフレーム後の動画バイト列（失敗時はNone）

    【注意】顔検出ベースの簡易実装のため、複数人が映るシーンやゲーム実況・アニメ調の
    映像では狙い通りに追従しない場合があります。顔が一度も検出できない場合は、
    中央を基準にしたクロップにフォールバックします。
    """
    if not HAS_MOVIEPY:
        return None

    try:
        target_w, target_h = (float(x) for x in target_ratio.split(":"))
    except Exception:
        target_w, target_h = 9.0, 16.0

    tmp_path = output_path = final_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not orig_w or not orig_h:
            cap.release()
            return None

        orig_ratio = orig_w / orig_h
        target_ratio_value = target_w / target_h

        if abs(orig_ratio - target_ratio_value) < 0.02:
            # すでにほぼ目的の比率なら何もしない
            cap.release()
            return video_bytes

        face_cascade = _get_face_cascade()
        detect_interval = max(int(fps // 3), 1)  # 1秒に約3回だけ検出（軽量化）

        if target_ratio_value < orig_ratio:
            # 横方向をクロップ（横動画→縦動画の典型パターン）
            crop_w = max(2, int(orig_h * target_ratio_value))
            crop_h = orig_h
            track_horizontal = True
        else:
            # 縦方向をクロップ
            crop_w = orig_w
            crop_h = max(2, int(orig_w / target_ratio_value))
            track_horizontal = False

        output_path = tmp_path.replace(".mp4", "_reframe_noaudio.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
        out = cv2.VideoWriter(output_path, fourcc, fps, (crop_w, crop_h))

        smoothed_center = (orig_w / 2) if track_horizontal else (orig_h / 2)
        frame_idx = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if face_cascade is not None and frame_idx % detect_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
                if len(faces) > 0:
                    # 一番大きく映っている顔を採用する（メイン被写体とみなす）
                    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                    target_center = (fx + fw / 2) if track_horizontal else (fy + fh / 2)
                    smoothed_center = smoothed_center * (1 - smoothing) + target_center * smoothing

            if track_horizontal:
                x1 = int(max(0, min(orig_w - crop_w, smoothed_center - crop_w / 2)))
                cropped = frame[:, x1:x1 + crop_w]
            else:
                y1 = int(max(0, min(orig_h - crop_h, smoothed_center - crop_h / 2)))
                cropped = frame[y1:y1 + crop_h, :]

            if cropped.shape[1] != crop_w or cropped.shape[0] != crop_h:
                cropped = cv2.resize(cropped, (crop_w, crop_h))

            out.write(cropped)
            frame_idx += 1

        cap.release()
        out.release()

        if not HAS_MOVIEPY:
            with open(output_path, "rb") as f:
                return f.read()

        final_path = tmp_path.replace(".mp4", "_reframe.mp4")
        original = VideoFileClip(tmp_path)
        reframed_clip = VideoFileClip(output_path)
        if original.audio:
            reframed_clip = reframed_clip.set_audio(original.audio)

        reframed_clip.write_videofile(final_path, codec="libx264", audio_codec="aac", logger=None, threads=4)

        with open(final_path, "rb") as f:
            result = f.read()

        original.close()
        reframed_clip.close()
        return result

    except Exception as e:
        print(f"自動リフレームエラー: {e}")
        return None

    finally:
        for p in [tmp_path, output_path, final_path]:
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