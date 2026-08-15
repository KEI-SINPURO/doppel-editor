"""
features/transcribe.py  ―  Whisper を使った動画音声文字起こし

STEP2「新しい動画に再現する」の最初のステップとして、
アップロードされた素材動画の音声を文字起こしし、
その結果（発話区間 = segments）を
  - 無音カット（features/generate.py の auto_cut_by_segments）
  - AIによる編集プラン生成（ai/model.py の generate_edit_plan）
の入力として使う。
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

_HAS_STREAMLIT = False
try:
    import streamlit as st  # type: ignore[import]
    _HAS_STREAMLIT = True
except ImportError:
    st = None  # type: ignore[assignment]


if _HAS_STREAMLIT and st is not None:
    @st.cache_resource(show_spinner=False)
    def _load_whisper_model(size: str):
        """Whisper モデルを一度だけ読み込んでキャッシュする（Streamlit環境）"""
        try:
            import whisper as _whisper  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "openai-whisper がインストールされていません。\n"
                "pip install openai-whisper を実行してください。"
            )
        return _whisper.load_model(size)
else:
    def _load_whisper_model(size: str):  # type: ignore[misc]
        try:
            import whisper as _whisper  # type: ignore[import]
        except ImportError:
            raise RuntimeError("openai-whisper がインストールされていません。")
        return _whisper.load_model(size)


def transcribe_video(
    video_bytes: bytes,
    language: str = "ja",
    model_size: str = "base",
) -> Optional[dict]:
    """
    動画の音声を文字起こしする。

    Args:
        video_bytes : 動画ファイルのバイト列
        language    : 音声言語（"ja" = 日本語）
        model_size  : "tiny" / "base"（推奨） / "small" / "medium" / "large"

    Returns:
        {"text": str, "segments": [...]} または None（失敗時）
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=tempfile.gettempdir()) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        model = _load_whisper_model(model_size)
        result = model.transcribe(
            tmp_path, language=language, fp16=False, verbose=False, task="transcribe",
        )
        return result

    except Exception as e:
        print(f"文字起こしエラー: {e}")
        return None

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def get_plain_text(segments: list) -> str:
    """セグメントリストから本文テキストだけを結合して返す"""
    if not segments:
        return ""
    return " ".join(s["text"].strip() for s in segments if s.get("text", "").strip())


def estimate_time(video_bytes: bytes, model_size: str = "base") -> str:
    """文字起こしにかかる推定時間を文字列で返す"""
    size_mb = len(video_bytes) / (1024 * 1024)
    estimated_min = size_mb / 75  # 75MB/分 を仮定
    speed_map = {"tiny": 60, "base": 20, "small": 10, "medium": 5, "large": 2}
    sec = (estimated_min * 60) / speed_map.get(model_size, 20)
    if sec < 60:
        return f"約{max(5, int(sec))}秒"
    return f"約{int(sec / 60)}分"
