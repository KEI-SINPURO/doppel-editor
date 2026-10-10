"""
features/transcribe.py  ―  Whisper を使った動画音声文字起こし

STEP2「新しい動画に再現する」の最初のステップとして、
アップロードされた素材動画の音声を文字起こしし、
その結果（発話区間 = segments）を
  - 無音カット（features/generate.py の auto_cut_by_segments）
  - AIによる編集プラン生成（ai/model.py の generate_edit_plan）
の入力として使う。

【今回の変更点（精度優先チューニング → 安定性優先に再調整）】
  当初は「多少重くなっても精度がほしい」という方針で既定値を "tiny" から "medium"
  （+ビームサーチ）まで引き上げていたが、実際にStreamlit Community Cloudの無料枠に
  デプロイしたところ、メモリ不足によるアプリ強制終了（OOM Kill。Python側の例外処理では
  防げない）が繰り返し発生したため、既定値を安全側の "small"・貪欲デコードに戻した。

  無料枠でも落ちにくい既定値にしつつ、環境変数で精度を引き上げられるようにしている：
    - DEFAULT_MODEL_SIZE : 既定 "small"（環境変数 WHISPER_MODEL_SIZE で上書き可。
                            メモリに余裕のある環境なら "medium"/"large-v3" 等に上げられる）
    - DEFAULT_BEAM_SIZE  : 既定 None（貪欲デコード。環境変数 WHISPER_BEAM_SIZE で
                            例えば "5" 等を指定するとビームサーチに切り替えられる）
    - word_timestamps=True は常時有効化し、単語（トークン）単位のタイムスタンプを取得。
      features/analyze.py の「フィラー語トリム傾向」の学習や、
      features/generate.py の trim_filler_word_edges()（発言の中身は残したまま、
      冒頭・末尾のフィラー語だけをわずかに削る処理）の入力として使う
      （word_timestamps自体のメモリ・処理時間への影響は比較的小さい）。

  ★ 重要な注意（README.md も参照）：
    "medium" 以上のモデルは、Streamlit Community Cloudの無料枠（メモリ約1GB）では
    メモリ不足でアプリが落ちる可能性が高い。精度を上げたい場合は、まず
    Render.com・VPS等メモリに余裕のある環境への移行を検討したうえで、
    環境変数 WHISPER_MODEL_SIZE を medium/large-v3 等に設定してください。
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


# ============================================================
# 精度優先の既定設定（環境変数で上書き可能）
# ============================================================

def _read_beam_size(raw: str) -> Optional[int]:
    raw = (raw or "").strip()
    if not raw or raw == "0":
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


DEFAULT_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "small")
DEFAULT_BEAM_SIZE: Optional[int] = _read_beam_size(os.getenv("WHISPER_BEAM_SIZE", ""))


def get_transcribe_quality_label() -> str:
    """現在のWhisper設定を、サイドバー等に表示する短い文字列にして返す"""
    beam_note = f"・ビームサーチ(width={DEFAULT_BEAM_SIZE})" if DEFAULT_BEAM_SIZE else "・高速デコード"
    return f"{DEFAULT_MODEL_SIZE}{beam_note}"


if _HAS_STREAMLIT and st is not None:
    @st.cache_resource(show_spinner=False)
    def _load_whisper_model(size: str):  # pyright: ignore[reportRedeclaration]
        # ★ if/elseの両方でこの関数名を定義しているため、Pylanceは
        #   「同じ名前を二重宣言している」と警告する。実際にはstreamlitの有無で
        #   片方だけが有効になる設計なので問題ない。
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
    model_size: Optional[str] = None,
    beam_size: Optional[int] = None,
) -> Optional[dict]:
    """
    動画の音声を文字起こしする。

    Args:
        video_bytes : 動画ファイルのバイト列
        language    : 音声言語（"ja" = 日本語）
        model_size  : "tiny" / "base" / "small" / "medium" / "large-v3" 等。
                      省略した場合は DEFAULT_MODEL_SIZE（環境変数 WHISPER_MODEL_SIZE、既定"small"）を使う。
        beam_size   : ビームサーチの幅。大きいほど精度が上がる一方、処理時間も伸びる。
                      省略した場合は DEFAULT_BEAM_SIZE（環境変数 WHISPER_BEAM_SIZE、既定None＝貪欲デコード）を使う。
                      Noneを明示的に渡すと、その呼び出しだけ高速な貪欲デコードにできる。

    Returns:
        {"text": str, "segments": [...]} または None（失敗時）。
        word_timestamps=True で呼んでいるため、各segmentには
        "words": [{"word","start","end","probability"}, ...] が含まれる
        （features/analyze.py・features/generate.py の精密なトリム処理の入力になる）。
    """
    resolved_model_size = model_size if model_size is not None else DEFAULT_MODEL_SIZE
    resolved_beam_size = beam_size if beam_size is not None else DEFAULT_BEAM_SIZE

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=tempfile.gettempdir()) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        model = _load_whisper_model(resolved_model_size)
        result = model.transcribe(
            tmp_path,
            language=language,
            fp16=False,
            verbose=False,
            task="transcribe",
            word_timestamps=True,
            beam_size=resolved_beam_size,
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


def estimate_time(video_bytes: bytes, model_size: Optional[str] = None, beam_size: Optional[int] = None) -> str:
    """文字起こしにかかる推定時間を文字列で返す（あくまで目安）"""
    resolved_model_size = model_size if model_size is not None else DEFAULT_MODEL_SIZE
    resolved_beam_size = beam_size if beam_size is not None else DEFAULT_BEAM_SIZE

    size_mb = len(video_bytes) / (1024 * 1024)
    estimated_min = size_mb / 75  # 75MB/分 を仮定
    speed_map = {"tiny": 60, "base": 20, "small": 10, "medium": 5, "large": 2, "large-v3": 2, "large-v2": 2}
    base_speed = speed_map.get(resolved_model_size, 5)
    # ビームサーチは幅にほぼ比例して遅くなる目安（大雑把な近似値）
    beam_factor = max(1, resolved_beam_size or 1) / 1.0 if resolved_beam_size else 1.0
    sec = (estimated_min * 60) / base_speed * (1 + 0.15 * (beam_factor - 1))
    if sec < 60:
        return f"約{max(5, int(sec))}秒"
    return f"約{int(sec / 60)}分"