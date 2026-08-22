"""
ai/model.py  ―  Doppel Editor AI エンジン（Claude API版）

【方針】
  無料枠にこだわらず、日本語の品質・指示追従性を優先してClaude APIを使用します。
  新規アカウントには少額の無料トライアルクレジット（目安$5・期限14日、要電話番号認証）が
  付与されますが、それを使い切ると少額の課金（1回の生成が数円程度）が必要になります。

  「AIの強化」は、実際のモデル再学習ではなく、
  ai/learning.py が組み立てる「ユーザー専用の強化テキスト」と、
  features/analyze.py が学習した「カットの癖（editing_patterns/rhythm）」を
  システムプロンプトに都度注入する方式（プロンプトベースの継続学習）で実現しています。

必要な環境変数（.env）:
  ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
  （取得方法: https://console.anthropic.com）
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
与えられたスタイルデータ（テンポ・テロップ・色調・カットの癖）と、過去の高評価データを、
一般論より常に優先してください。
必ず日本語で、具体的な数値（秒数・px・色コードなど）を含めて回答してください。"""


def build_dynamic_system_prompt(
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    extra: str = "",
) -> str:
    """学習済みスタイルデータ・ユーザー強化テキストを組み込んだシステムプロンプトを作る。"""
    sections = [_BASE_SYSTEM]

    if style_data:
        header = f"【学習済みスタイル「{style_label}」】" if style_label else "【学習済みスタイル】"
        s = [header]
        s.append(f"- テンポ: {style_data.get('tempo', '不明')}（平均カット間隔 {style_data.get('avg_cut_interval', '不明')}秒）")
        s.append(f"- テロップ色: {style_data.get('dominant_color', '不明')} / 位置: {style_data.get('dominant_position', '不明')}")
        s.append(f"- カット数: {style_data.get('total_cuts', '不明')}")
        if style_data.get("subtitle_density"):
            s.append(f"- テロップの出現頻度: 1分あたり約{style_data.get('subtitle_density')}回")
        sections.append("\n".join(s))

        rhythm = style_data.get("rhythm")
        if rhythm and rhythm.get("rhythm_pattern") and rhythm.get("rhythm_pattern") != "不明":
            r = ["【カットのリズムパターン（分析結果）】"]
            r.append(f"- パターン: {rhythm.get('rhythm_pattern')}")
            r.append(
                f"- 平均カット間隔: {rhythm.get('avg_interval')}秒"
                f"（ばらつき ±{rhythm.get('std_interval')}秒、"
                f"最短{rhythm.get('min_interval')}秒〜最長{rhythm.get('max_interval')}秒）"
            )
            sections.append("\n".join(r))

        patterns = style_data.get("editing_patterns")
        if patterns:
            p = ["【学習した「カットの癖」（過去のraw素材と完成動画の比較から学習）】"]
            p.append(f"- 素材のうち残す割合の目安: 約{int(patterns.get('keep_ratio', 1) * 100)}%")
            p.append(f"- フィラー語（えー、あの、など）の除去傾向: 該当発言のうち約{int(patterns.get('filler_removal_rate', 0) * 100)}%を削る")
            p.append(f"- カットは文の区切り（句読点）で行われる傾向: 約{int(patterns.get('boundary_tendency', 0) * 100)}%")
            if patterns.get("avg_cut_duration"):
                p.append(f"- カットされる発言1つあたりの平均長さ: 約{patterns.get('avg_cut_duration')}秒")
            if patterns.get("typical_cut_examples"):
                examples = "／".join(patterns["typical_cut_examples"])
                p.append(f"- 実際に過去カットされていた発言の例: {examples}")
            p.append("この傾向を踏まえて、新しい動画でも同じ基準で「残す／削る」を判断してください。")
            sections.append("\n".join(p))

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

_EDIT_PLAN_SYSTEM_EXTRA = """
これから渡す「文字起こしセグメント」と「学習済みスタイル（カットの癖を含む）」をもとに、
新しい動画をこのユーザーらしく自動編集するための「編集プラン」を
JSONのみで出力してください。前置き・説明文・Markdownのコードフェンスは一切不要です。

出力するJSONの形式:
{
  "segments": [
    {"start": 0.0, "end": 2.3, "text": "テロップとして表示する文言", "emphasis": "normal", "keep": true}
  ],
  "highlight_moments": [
    {"start": 12.0, "end": 12.6, "reason": "驚きの発言"}
  ],
  "notes": "この動画全体の編集方針を一言で"
}

ルール:
- segments は元の発話内容を大きく損なわない範囲で、テンポよく読める長さに要約してよい
- emphasis は "normal" か "high" のどちらか（highは特に盛り上がる・重要な発言のみ、全体の20%以下に絞る）
- keep は、このセグメントを最終的な動画に残すかどうか（true/false）。
  基本は true。学習した「カットの癖」（フィラー語の除去傾向・残す割合・カットされていた
  発言の実例）を踏まえ、言い淀み・明らかな脱線・不要な繰り返しなど、
  過去の傾向から見て編集者が削っていたであろう発言だけを false にしてよい。
  false の割合は、学習した「残す割合」を大きく下回らない範囲に収めること（乱用しない）。
- highlight_moments は「ズームなどの演出を入れると良い瞬間」を最大5件、学習済みスタイルの
  テンポ感・リズムパターンに合わせて選ぶ
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
    各セグメントには "keep"（残すか削るか）も含まれ、学習した「カットの癖」を反映する。

    Returns:
        成功時: {"segments": [...], "highlight_moments": [...], "notes": "..."}
        失敗時（AI未設定・パース失敗など）: None
        → 呼び出し側は None の場合、ai/heuristic.py のルールベース版にフォールバックすること。
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