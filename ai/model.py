"""
ai/model.py  ―  Doppel Editor AI エンジン（Claude API版）

【変更点】
  Ollama（ローカルAI）から Anthropic Claude API に切り替えました。
  理由:
    - テック甲子園の応募規約上、Webアプリはローカル環境のトンネリング公開（ngrok等）が禁止されており、
      自分のPCでOllamaを動かす運用は本番デプロイと相性が悪いため
    - 日本語の文脈理解・指示追従性の面でも実用上有利なため

  「AIの強化」は、実際のモデル再学習ではなく、
  ai/learning.py が組み立てる「ユーザー専用の強化テキスト」を
  システムプロンプトに都度注入する方式（プロンプトベースの継続学習）で実現しています。

必要な環境変数（.env）:
  ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
"""

import os
import json
import re
from typing import Optional, Iterator, List, Dict, Any

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# 用途別モデル。文章生成・編集プラン生成は品質重視で Sonnet を既定にする。
DEFAULT_MODEL = "claude-sonnet-5"
FAST_MODEL = "claude-haiku-4-5-20251001"

_client = None


def _get_client():
    """Anthropicクライアントをシングルトンで取得する。APIキーが無ければNone。"""
    global _client
    if not HAS_ANTHROPIC:
        return None
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def is_ai_ready() -> bool:
    """AIが利用可能な状態か（ライブラリ・APIキーとも揃っているか）"""
    return HAS_ANTHROPIC and bool(os.getenv("ANTHROPIC_API_KEY"))


# ============================================================
# システムプロンプトの動的生成
# ============================================================

_BASE_SYSTEM = """あなたは「Doppel AI」――ユーザー自身の動画編集スタイルを学習して育つ、
「もう一人のユーザー自身（編集クローン）」です。
与えられたスタイルデータ（テンポ・テロップ・色調）と、過去の高評価データを、
一般論より常に優先してください。
必ず日本語で、具体的な数値（秒数・px・色コードなど）を含めて回答してください。"""


def build_dynamic_system_prompt(
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    extra: str = "",
) -> str:
    """
    学習済みスタイルデータ・ユーザー強化テキストを組み込んだシステムプロンプトを作る。
    """
    sections = [_BASE_SYSTEM]

    if style_data:
        header = f"【学習済みスタイル「{style_label}」】" if style_label else "【学習済みスタイル】"
        s = [header]
        s.append(f"- テンポ: {style_data.get('tempo', '不明')}（平均カット間隔 {style_data.get('avg_cut_interval', '不明')}秒）")
        s.append(f"- テロップ色: {style_data.get('dominant_color', '不明')} / 位置: {style_data.get('dominant_position', '不明')}")
        s.append(f"- カット数: {style_data.get('total_cuts', '不明')}")
        sections.append("\n".join(s))

    if reinforcement_text:
        sections.append(reinforcement_text)

    if extra:
        sections.append(extra)

    return "\n\n".join(sections)


# ============================================================
# 基本チャット（通常 / ストリーミング）
# ============================================================

_NOT_READY_MSG = (
    "Claude APIが利用できません。.env に ANTHROPIC_API_KEY を設定し、"
    "pip install anthropic を実行してください。"
)


def chat(prompt: str, system_prompt: str, model: str = DEFAULT_MODEL,
         max_tokens: int = 1500, temperature: float = 0.7) -> str:
    client = _get_client()
    if not client:
        return _NOT_READY_MSG
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")
    except Exception as e:
        return f"AI処理中にエラーが発生しました: {e}"


def chat_stream(prompt: str, system_prompt: str, model: str = DEFAULT_MODEL,
                 max_tokens: int = 1500, temperature: float = 0.7) -> Iterator[str]:
    client = _get_client()
    if not client:
        yield _NOT_READY_MSG
        return
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f"AI処理中にエラーが発生しました: {e}"


# ============================================================
# サムネイル提案
# ============================================================

def get_thumbnail_suggestion(
    transcript: str,
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    stream: bool = False,
) -> "str | Iterator[str]":
    """動画内容からサムネイルを3パターン提案する"""
    prompt = f"""以下の動画内容からクリック率の高いサムネイルを3パターン提案してください。

【動画内容】
{transcript[:1500] if transcript else "内容不明"}

各パターンは必ず以下を含めること：
- メインテキスト（大きく表示するコピー、6文字以内推奨）
- サブテキスト（補足説明）
- 推奨カラー配色（ヘックスコードも可）
- 表情・ポーズの指示
- 背景デザインのコンセプト
"""
    system = build_dynamic_system_prompt(style_data, style_label, reinforcement_text)
    return chat_stream(prompt, system) if stream else chat(prompt, system)


# ============================================================
# 編集アドバイス（テキストでの解説）
# ============================================================

def get_editing_suggestion(
    transcript: str,
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    stream: bool = False,
) -> "str | Iterator[str]":
    """動画の文字起こしと学習済みスタイルから、編集方針を文章で説明する"""
    prompt = f"""以下の動画の文字起こしを見て、あなた（このユーザーの分身）ならどう編集するか説明してください。

【文字起こし】
{transcript[:2000] if transcript else "なし"}

■ カット割りの方針（具体的な秒数を含める）
■ テロップを入れるべき箇所と文言
■ 盛り上がりポイント
■ 色調・雰囲気の方針
"""
    system = build_dynamic_system_prompt(style_data, style_label, reinforcement_text)
    return chat_stream(prompt, system) if stream else chat(prompt, system)


# ============================================================
# ★ 自動再現エンジンの核 ― 編集プラン(JSON)の生成
# ============================================================
#
# STEP2「新しい動画に再現する」で使われる、今回の目玉機能。
# 文字起こしセグメント＋学習済みスタイルをAIに渡し、
# 「どこにどんなテロップを、どのくらいの強調度で入れるか」
# 「どこにズーム等の演出を入れるか」を構造化データ(JSON)として受け取り、
# features/generate.py・features/effects.py にそのまま渡して実際の動画に反映する。
# ============================================================

_EDIT_PLAN_SYSTEM_EXTRA = """
これから渡す「文字起こしセグメント」と「学習済みスタイル」をもとに、
新しい動画をこのユーザーらしく自動編集するための「編集プラン」を
JSONのみで出力してください。前置き・説明文・Markdownのコードフェンスは一切不要です。

出力するJSONの形式:
{
  "segments": [
    {"start": 0.0, "end": 2.3, "text": "テロップとして表示する文言", "emphasis": "normal"}
  ],
  "highlight_moments": [
    {"start": 12.0, "end": 12.6, "reason": "驚きの発言"}
  ],
  "notes": "この動画全体の編集方針を一言で"
}

ルール:
- segments は元の発話内容を大きく損なわない範囲で、テンポよく読める長さに要約してよい
- emphasis は "normal" か "high" のどちらか（highは特に盛り上がる・重要な発言のみ、全体の20%以下に絞る）
- highlight_moments は「ズームなどの演出を入れると良い瞬間」を最大5件、学習済みスタイルのテンポ感に合わせて選ぶ
- 与えられたセグメントの時間範囲外の時刻は使わない
"""


def generate_edit_plan(
    transcript_segments: List[Dict[str, Any]],
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    model: str = DEFAULT_MODEL,
) -> Optional[Dict[str, Any]]:
    """
    文字起こしセグメント＋学習済みスタイルから「このユーザーらしい編集プラン」をJSONで生成する。

    Returns:
        成功時: {"segments": [...], "highlight_moments": [...], "notes": "..."}
        失敗時（AI未設定・パース失敗など）: None
        → 呼び出し側は None の場合、文字起こしそのままを使うフォールバック動作にすること。
    """
    if not is_ai_ready():
        return None

    compact = [
        {"start": round(s.get("start", 0), 2), "end": round(s.get("end", 0), 2),
         "text": s.get("text", "").strip()}
        for s in transcript_segments if s.get("text", "").strip()
    ]
    if not compact:
        return None

    prompt = f"文字起こしセグメント(JSON):\n{json.dumps(compact, ensure_ascii=False)}"
    system = build_dynamic_system_prompt(
        style_data, style_label, reinforcement_text, extra=_EDIT_PLAN_SYSTEM_EXTRA
    )

    raw = chat(prompt, system, model=model, max_tokens=4000, temperature=0.4)
    return _parse_json_safely(raw)


def _parse_json_safely(text: str) -> Optional[Dict[str, Any]]:
    """AIの出力からJSON部分だけを安全に取り出す（前後に説明文が付いても耐えるように）"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None
