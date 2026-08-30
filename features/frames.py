"""
features/frames.py  ―  動画からのフレーム画像抽出（Claude Visionへの視覚情報提供用）

【何のためにあるか】
  これまでの ai/model.py の generate_edit_plan() は、Whisperの文字起こしテキストと
  数値化されたスタイルデータだけを判断材料にしており、「実際の映像がどう映っているか」
  （表情・場面転換・テロップの実際の見た目など）は一切見ていなかった。
  本モジュールは、動画から数枚のフレームを抜き出してClaude API（Vision対応）に
  渡せる形式に変換する、AIを一切使わない純粋なcv2ベースの画像処理ユーティリティ。

  使いどころ:
    - pipeline.py: 「動画を再現する」際、ハイライト候補の時刻付近のフレームを
      generate_edit_plan() に渡し、盛り上がり判定の精度を上げる（DOPPEL_VISUAL_MODE=on 時のみ）
    - app.py（学習タブ）: 編集後動画からテロップが検出された時刻のフレームを
      ai/model.py の describe_visual_editing_style() に渡し、テロップの文体・雰囲気を学習する
      （こちらは学習1回あたりのコストなので既定で常時実行）

【コストに関する注意】
  画像はAPIのトークン消費が大きいため、
    - 抽出枚数には必ず上限を設ける（多くの用途で4〜6枚程度を推奨）
    - resize_width で解像度を落としてからJPEGエンコードする
  という2点を必ず守るように設計している。
"""

import base64
import os
import tempfile
from typing import Dict, List, Optional

import cv2


def _resize_for_vision(frame, target_width: int = 512):
    """横幅が target_width を超える場合のみ縮小する（小さい動画はそのまま）"""
    h, w = frame.shape[:2]
    if w <= target_width:
        return frame
    scale = target_width / w
    return cv2.resize(frame, (target_width, max(1, int(h * scale))))


def _encode_jpeg_base64(frame, quality: int = 80) -> Optional[str]:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def extract_frames_at_timestamps(
    video_bytes: bytes,
    timestamps: List[float],
    max_frames: int = 6,
    resize_width: int = 512,
) -> List[Dict[str, str]]:
    """
    指定した時刻（秒）に最も近いフレームを抽出し、Claude APIにそのまま渡せる
    画像ブロック形式（[{"media_type": "image/jpeg", "data": "<base64>"}, ...]）で返す。

    Args:
        video_bytes  : 対象動画のバイト列
        timestamps   : 抽出したい時刻のリスト（秒）。多すぎる場合は時系列順に間引かれる
        max_frames   : 抽出する最大枚数（コスト・処理時間を抑えるための上限）
        resize_width : リサイズ後の横幅（px）。小さいほどAPIコストが下がる

    Returns:
        画像ブロックのリスト（読み込めたフレームのみ。全滅した場合は空リスト。例外は投げない）
    """
    if not timestamps:
        return []

    tmp_path = None
    results: List[Dict[str, str]] = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frame_count / fps if fps else 0

        sorted_ts = sorted({round(t, 2) for t in timestamps if t is not None and t >= 0})
        if not sorted_ts:
            cap.release()
            return []
        if len(sorted_ts) > max_frames:
            step = len(sorted_ts) / max_frames
            sorted_ts = [sorted_ts[min(int(i * step), len(sorted_ts) - 1)] for i in range(max_frames)]

        for t in sorted_ts:
            target_t = min(max(t, 0.0), max(duration - 0.05, 0.0)) if duration else t
            frame_idx = max(0, int(target_t * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            frame = _resize_for_vision(frame, resize_width)
            b64 = _encode_jpeg_base64(frame)
            if b64:
                results.append({"media_type": "image/jpeg", "data": b64})

        cap.release()
        return results

    except Exception as e:
        print(f"フレーム抽出エラー: {e}")
        return results
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def extract_evenly_spaced_frames(
    video_bytes: bytes,
    count: int = 6,
    resize_width: int = 512,
) -> List[Dict[str, str]]:
    """
    時刻の指定が無い場合の汎用サンプリング。動画全体からほぼ均等な間隔でフレームを抽出する
    （例：ハイライト候補が1件も無かった動画の、全体の雰囲気をざっくり把握したい場合）。
    """
    tmp_path = None
    duration = 0.0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frame_count / fps if fps else 0
        cap.release()
    except Exception as e:
        print(f"動画情報取得エラー: {e}")
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    if duration <= 0 or count <= 0:
        return []
    timestamps = [duration * (i + 0.5) / count for i in range(count)]
    return extract_frames_at_timestamps(video_bytes, timestamps, max_frames=count, resize_width=resize_width)