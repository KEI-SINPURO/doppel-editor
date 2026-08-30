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

【今回のアップデート（精度優先 ― 「本人が編集したみたいだ」と思われる再現度を目指す）】
  - 音量・キーワードから機械的に検出した「盛り上がり候補」(features/effects.py の
    detect_highlight_moments)を、AIが使える場合でも常にヒントとして渡すようにした
    （従来はAI未使用時のフォールバックでのみ使用しており、AIが使える環境では
    テキストの文脈だけでハイライトを推測していた）。
  - 長尺動画（文字起こしセグメント数が多い動画）は自動的に分割してAPI呼び出しを行い、
    出力トークン上限による尻切れ・JSON解析失敗 → 全体がルールベースにフォールバック、
    という「全滅」を防ぐようにした（generate_edit_plan → _generate_edit_plan_chunked）。
  - AIの出力がJSONとしてパースできなかった場合、1回だけ「有効なJSONに直して」と
    頼み直す修復ステップを追加した（_repair_json）。
  - 返ってきたJSONの時刻・必須キーを検証し、範囲外の値やキー欠けを補正する
    防御的な後処理を追加した（_validate_and_repair_plan）。数値の「妥当性」
    （残す割合が学習値と大きくズレていないか等）は機械的に上書きせず、
    Claude自身の判断を尊重する方針。
  - 環境変数 DOPPEL_QUALITY_MODE=max を設定すると、編集プラン生成により高精度な
    上位モデル（QUALITY_MODEL）を使う「最高品質モード」に切り替えられる
    （料金・レイテンシが上がるため既定はオフ。詳細はREADME.md参照）。

【さらなるアップデート（映像そのものも判断材料にする／フィードバック学習の強化）】
  - 環境変数 DOPPEL_VISUAL_MODE=on を設定すると、「動画を再現する」際に
    features/frames.py で抜き出したフレーム画像（ハイライト候補付近など）を
    generate_edit_plan() に一緒に渡し、Claude Vision で実際の映像も見た上で
    ハイライト・強調テロップを判断できるようにした（is_visual_mode_enabled）。
    毎回のAPI呼び出しに画像が増える＝料金が上がるため、既定はオフ。
    長尺動画（自動分割される動画）では、コスト・複雑さを抑えるため画像は使わない。
  - 「スタイルを学習する」タブでは、AIが使えれば常に（DOPPEL_VISUAL_MODEの設定に
    関わらず）編集後動画からテロップが写っているフレームを数枚抜き出し、
    describe_visual_editing_style() でテロップの文体・言い回しの雰囲気を
    言語化して学習するようにした（1スタイルにつき1回だけの軽いコストのため）。
    学習結果は style_data["subtitle_voice"] に保存され、以後の編集プラン生成の
    システムプロンプトに反映される。
  - ai/learning.py の FeedbackLearner を強化し、「良い評価」の例だけでなく
    「改善が必要」だった例も「避けるべき傾向」として強化データに含めるようにした。
    また、現在使っているスタイル名に一致するフィードバックを優先して使うようにした。

【さらなるアップデート（実際の映像編集で「足りていなかった」部分の補完）】
  - highlight_moments に任意の se_mood（"ding"/"impact"/"whoosh"/"pop"/"buzz"/"tada"）を
    付けられるようにした。features/se_presets.py の get_se_bytes_by_mood と組み合わせ、
    「盛り上がりの種類に応じて効果音を自動で使い分ける」機能（render_options_ui の
    「🤖 AIにおまかせ」選択肢）に使われる。以前は動画全体で1種類の効果音しか使えなかった。
  - features/branding.py の mix_bgm() に、発話区間だけBGM音量を追加で下げる
    「自動ダッキング」を追加した（pipeline.py から常時適用）。以前はBGMが動画全体で
    一定音量のままで、セリフに被って聞き取りづらくなることがあった。
  - generate_video_description() を追加。完成動画で実際に使われた発言から、
    YouTube投稿用の概要欄文章とタイムスタンプ付きチャプターを自動生成できるようにした
    （「動画を再現する」タブの「概要欄・チャプターも作る」から利用）。

必要な環境変数（.env）:
  ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
  （取得方法: https://console.anthropic.com）
  DOPPEL_QUALITY_MODE=max   （任意。編集プラン生成に上位モデルを使いたい場合のみ設定）
  DOPPEL_VISUAL_MODE=on     （任意。動画再現時にフレーム画像も判断材料にしたい場合のみ設定）
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

# 編集プラン生成専用の「最高品質モード」で使う上位モデル。
# Opus系はSonnetよりも複雑な文脈判断に強い一方、料金・レイテンシは上がる
# （最新の料金は https://docs.claude.com 等の公式ドキュメントを確認してください）。
# 既定は "balanced"（DEFAULT_MODEL=Sonnet）。.env に DOPPEL_QUALITY_MODE=max と
# 書くと、編集プラン生成だけがこちらに切り替わる。
QUALITY_MODEL = "claude-opus-4-8"
_QUALITY_MODE = os.getenv("DOPPEL_QUALITY_MODE", "balanced").strip().lower()

# 「動画を再現する」際に、文字起こしテキストだけでなくフレーム画像も判断材料にするか。
# 毎回のAPI呼び出しに画像が乗る＝料金が増えるため、既定はオフ。"on"で有効化する。
_VISUAL_MODE = os.getenv("DOPPEL_VISUAL_MODE", "off").strip().lower()

_client = None


def is_visual_mode_enabled() -> bool:
    """編集プラン生成にフレーム画像を使う「映像参照モード」が有効かどうかを返す"""
    return _VISUAL_MODE in ("on", "true", "1")


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


def get_quality_mode() -> str:
    """現在のAI品質モード（"max" または "balanced"）を返す（サイドバー表示用）"""
    return "max" if _QUALITY_MODE == "max" else "balanced"


def _edit_plan_model() -> str:
    """編集プラン生成に使うモデルを決める（品質モードが"max"ならQUALITY_MODEL）"""
    return QUALITY_MODEL if _QUALITY_MODE == "max" else DEFAULT_MODEL


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

            # NEW: 動画内の位置（冒頭/中盤/終盤）による残す割合の違い
            pos = patterns.get("position_bias") or {}
            pos_parts = [f"{label} 約{int(ratio * 100)}%" for label, ratio in pos.items() if ratio is not None]
            if pos_parts:
                p.append(f"- 動画内の位置による残す割合の違い: {' / '.join(pos_parts)}")

            # NEW: フィラー語のトリム傾向（システム側で自動処理される部分）
            trim = patterns.get("trim_stats")
            if trim and trim.get("sample_size", 0) >= 2:
                p.append(
                    f"- フィラー語のトリム傾向: 残した発言でも、冒頭平均{trim.get('avg_trim_start_tokens', 0)}語・"
                    f"末尾平均{trim.get('avg_trim_end_tokens', 0)}語ぶんは自動的に削られていた"
                    "（このシステムでは自動トリム処理が別途行われるため、keepの判断材料にはしてよいが、"
                    "テロップ文言自体をその分削る必要はない）"
                )

            p.append("この傾向を踏まえて、新しい動画でも同じ基準で「残す／削る」を判断してください。")
            sections.append("\n".join(p))

        # NEW: 過去の動画のフレームから学習した、テロップの文体・言い回しの雰囲気
        # （ai/model.py の describe_visual_editing_style が生成し、
        #   app.py の学習タブで style_data["subtitle_voice"] に保存されたもの）
        subtitle_voice = style_data.get("subtitle_voice")
        if subtitle_voice:
            sections.append(
                "【学習したテロップの文体・雰囲気（過去の動画のフレームから分析）】\n"
                f"{subtitle_voice}\n"
                "テロップ文言（segments の text）を書く際は、この文体・トーンに合わせてください。"
            )

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


def _build_image_content_blocks(images: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """
    features/frames.py が返す [{"media_type": "image/jpeg", "data": "<base64>"}, ...] を、
    Anthropic APIのメッセージcontentに埋め込める画像ブロック形式に変換する。
    """
    blocks = []
    for img in images or []:
        data = img.get("data")
        if not data:
            continue
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.get("media_type", "image/jpeg"),
                "data": data,
            },
        })
    return blocks


def chat_with_images(prompt: str, system_prompt: str, images: Optional[List[Dict[str, str]]] = None,
                      model: str = DEFAULT_MODEL, max_tokens: int = 1500, temperature: float = 0.7) -> str:
    """
    chat() の画像対応版。features/frames.py で抽出したフレーム画像を渡すと、
    Claude Visionが実際の映像も見た上で応答する。images が空/Noneならテキストのみと同じ挙動。
    """
    client = _get_client()
    if not client:
        return _NOT_READY_MSG
    content: List[Dict[str, Any]] = _build_image_content_blocks(images)
    content.append({"type": "text", "text": prompt})
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            # ★ content は実行時には {"type": "image"/"text", ...} 形式の辞書リストのままで
            #   問題なく動作する（Anthropic APIは素のJSON構造を受け付ける）。だが型スタブ上は
            #   TextBlockParam | ImageBlockParam 等の厳密なTypedDictユニオンを要求しており、
            #   Dict[str, Any]で組み立てているためPylanceが誤検知する。
            #   ai/auth.py の exchange_code_for_session と同じ理由の誤検知のため無視する。
            messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
        )
        return "".join(block.text for block in resp.content if block.type == "text")
    except Exception as e:
        return f"AI処理中にエラーが発生しました: {e}"


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
# テロップの文体・雰囲気の分析（学習タブ専用・Claude Vision使用）
# ============================================================

_VISUAL_STYLE_SYSTEM = """あなたは動画編集の専門家です。渡された数枚のフレーム画像は、
ある人物が過去に編集した動画から、テロップが映っているタイミングを中心にサンプリングしたものです。
画面に焼き込まれたテロップの「言葉遣い・語尾・絵文字や記号の使い方・強調の仕方・トーン」を中心に、
その編集者ならではの文体を日本語で簡潔に（3〜5行程度）言語化してください。
テロップが読み取れない・写っていない画像は無視して構いません。
画像から実際に読み取れる範囲の事実だけを述べ、憶測で断定しないでください。
テロップが1枚も読み取れなかった場合は、素直に「テロップの文体は読み取れませんでした」とだけ答えてください。"""


def describe_visual_editing_style(
    frames_b64: Optional[List[Dict[str, str]]],
    model: str = DEFAULT_MODEL,
) -> Optional[str]:
    """
    学習時にサンプリングしたフレーム画像（features/frames.py の
    extract_frames_at_timestamps 等の出力）から、テロップの文体・言い回しの雰囲気を
    Claude Visionで言語化する。

    AI未使用・画像が渡されなかった場合はNoneを返す（呼び出し側は何もせずスキップする＝
    安全側にフォールバックする）。1スタイルの学習につき1回だけ呼ばれる想定のため、
    generate_edit_plan のような分割・修復処理は行わず、シンプルな単発呼び出しにしている。

    Returns:
        文体の説明文（string）。失敗時・未使用時は None。
    """
    if not is_ai_ready() or not frames_b64:
        return None
    prompt = "これらのフレーム画像から、テロップの言葉遣い・文体・雰囲気を分析してください。"
    result = chat_with_images(
        prompt, _VISUAL_STYLE_SYSTEM, images=frames_b64, model=model, max_tokens=500, temperature=0.3,
    )
    if not result or result == _NOT_READY_MSG or result.startswith("AI処理中にエラーが発生しました"):
        return None
    return result.strip()


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
    {"start": 12.0, "end": 12.6, "reason": "驚きの発言", "se_mood": "impact"}
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
  なお、発言の冒頭・末尾にフィラー語（「えー」「あの」等）が付いているだけで、
  それ以外の内容に価値がある発言は、丸ごと false にする必要はない
  （その部分だけをシステム側が自動的に細かくトリムするため）。
- highlight_moments は「ズームなどの演出を入れると良い瞬間」を最大5件、学習済みスタイルの
  テンポ感・リズムパターンに合わせて選ぶ。音量・キーワードから機械的に検出した候補が
  別途渡された場合は、参考にしつつ、文脈的に妥当なものだけを採用してよい（丸写し不要）。
- highlight_moments の各要素には、任意で se_mood を付けてよい（「効果音をAIにおまかせ」機能で
  使われる）。その瞬間のトーンに最も近いものを1つだけ選ぶこと:
    "ding"   … 嬉しい発見・ポジティブな驚き
    "impact" … 強い衝撃・シリアスな驚き
    "whoosh" … 場面転換・テンポの良い切り替え
    "pop"    … 軽いリアクション・ちょっとしたツッコミ
    "buzz"   … 残念・失敗・警告
    "tada"   … 達成・成功・締めくくり
  迷う場合、効果音が不要と判断する場合は省略してよい（省略時は付けない方がよい）。
- 与えられたセグメントの時間範囲外の時刻は使わない
- segments の順序は、渡された文字起こしセグメントの時系列順のまま出力すること
  （このシステムは発言の並び替え再現には対応していないため、順序を入れ替えないこと）
"""

# 出力の尻切れ（＝JSON解析失敗→全体がルールベースにフォールバック）を防ぐため、
# 以前の4000から引き上げた。長尺動画は _CHUNK_TRIGGER を超えたら自動分割されるため、
# 1回の呼び出しがこの上限に収まりやすくなっている。
_EDIT_PLAN_MAX_TOKENS = 8000

# 1回のAPI呼び出しに渡すセグメント数の上限。これを超える動画は自動的に分割処理する。
_CHUNK_SIZE = 70
_CHUNK_TRIGGER = 90

# ハイライト瞬間に付与できる se_mood の許可リスト（features/se_presets.py と対応）
_ALLOWED_SE_MOODS = {"ding", "impact", "whoosh", "pop", "buzz", "tada"}


def _format_highlight_hints(hints: Optional[List[Dict[str, Any]]]) -> str:
    """
    features/effects.py の detect_highlight_moments()（音量・キーワードから機械的に
    検出した盛り上がり候補）を、Claudeへの参考情報として整形する。
    あくまで「機械的な候補」であり、採用するかどうかの最終判断はAI（文脈判断）に委ねる。
    """
    if not hints:
        return ""
    lines = [
        "【音量・キーワードから機械的に検出した「盛り上がり候補」（参考情報。必ずしも正しくない）】",
        "文脈的に的外れなら無視して構いません。逆にここに無くても、文脈上盛り上がっていると"
        "判断すれば highlight_moments に追加して構いません。",
    ]
    for h in hints[:15]:
        ts = h.get("timestamp", h.get("start", 0))
        te = h.get("end", ts + 0.5)
        kind = h.get("type", "")
        text = (h.get("text") or "")[:30]
        lines.append(f"- {ts:.1f}s〜{te:.1f}s（{kind}検出・スコア{h.get('score', 0)}）: {text}")
    return "\n".join(lines)


def generate_edit_plan(
    transcript_segments: List[Dict[str, Any]],
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    model: Optional[str] = None,
    highlight_hints: Optional[List[Dict[str, Any]]] = None,
    frame_images: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    文字起こしセグメント＋学習済みスタイルから「このユーザーらしい編集プラン」をJSONで生成する。
    各セグメントには "keep"（残すか削るか）も含まれ、学習した「カットの癖」を反映する。

    Args:
        transcript_segments: Whisperの発話区間 [{"start","end","text",...}, ...]
        style_data / style_label / reinforcement_text: 従来通り
        model           : 使用モデル。省略時は品質モード（DOPPEL_QUALITY_MODE）に応じて自動選択
        highlight_hints : features/effects.py の detect_highlight_moments() の結果。
                          渡すとAIへの参考情報として組み込まれ、盛り上がり判定の精度が上がる
        frame_images    : features/frames.py で抽出したフレーム画像（DOPPEL_VISUAL_MODE=on時のみ
                          呼び出し側が渡す想定）。渡すとClaude Visionが実際の映像も見た上で判断する。
                          ★ 長尺動画（自動分割される動画）ではコスト・複雑さを抑えるため無視される
                          （_generate_edit_plan_chunked には渡さない設計）。

    Returns:
        成功時: {"segments": [...], "highlight_moments": [...], "notes": "..."}
        失敗時（AI未設定・パース失敗など）: None
        → 呼び出し側は None の場合、ai/heuristic.py のルールベース版にフォールバックすること。

    長尺動画（セグメント数が _CHUNK_TRIGGER を超える）は自動的に複数回のAPI呼び出しに
    分割される（_generate_edit_plan_chunked）。1回の呼び出しに収まる動画は
    従来通り1回で生成する（_generate_edit_plan_single）。
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

    resolved_model = model or _edit_plan_model()
    system = build_dynamic_system_prompt(
        style_data, style_label, reinforcement_text, extra=_EDIT_PLAN_SYSTEM_EXTRA
    )

    try:
        if len(compact) <= _CHUNK_TRIGGER:
            return _generate_edit_plan_single(compact, system, resolved_model, highlight_hints, frame_images)
        return _generate_edit_plan_chunked(compact, system, resolved_model, highlight_hints)
    except Exception as e:
        print(f"編集プラン生成エラー: {e}")
        return None


def _generate_edit_plan_single(
    compact: List[Dict[str, Any]],
    system: str,
    model: str,
    highlight_hints: Optional[List[Dict[str, Any]]],
    frame_images: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """1回のAPI呼び出しで完結する（短め〜中程度の動画向け）編集プラン生成"""
    hint_block = _format_highlight_hints(highlight_hints)
    prompt = f"文字起こしセグメント(JSON):\n{json.dumps(compact, ensure_ascii=False)}"
    if hint_block:
        prompt += f"\n\n{hint_block}"
    if frame_images:
        prompt += (
            "\n\n【添付画像について】この動画から抜き出したフレーム画像も渡しています。"
            "実際の映像の様子（表情・場面・テロップの有無等）も判断材料にしてください。"
        )

    if frame_images:
        raw = chat_with_images(
            prompt, system, images=frame_images, model=model,
            max_tokens=_EDIT_PLAN_MAX_TOKENS, temperature=0.4,
        )
    else:
        raw = chat(prompt, system, model=model, max_tokens=_EDIT_PLAN_MAX_TOKENS, temperature=0.4)

    plan = _parse_json_safely(raw)
    if plan is None:
        repaired = _repair_json(raw, system, model)
        plan = _parse_json_safely(repaired) if repaired else None
    if plan is None:
        return None
    return _validate_and_repair_plan(plan, compact)


def _generate_edit_plan_chunked(
    compact: List[Dict[str, Any]],
    system: str,
    model: str,
    highlight_hints: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    長尺動画向け：セグメントを _CHUNK_SIZE ごとに分割し、それぞれ個別にAPI呼び出しして
    結果を結合する。1チャンクだけ解析に失敗しても動画全体をヒューリスティックに
    投げ出さず、そのチャンクだけ「原文のまま残す」で処理を継続する。
    """
    chunks = [compact[i:i + _CHUNK_SIZE] for i in range(0, len(compact), _CHUNK_SIZE)]
    num_chunks = len(chunks)
    max_highlights_total = min(5 * num_chunks, 20)
    per_chunk_highlight_cap = max(2, -(-max_highlights_total // num_chunks))  # 切り上げ除算

    all_segments: List[Dict[str, Any]] = []
    all_highlights: List[Dict[str, Any]] = []
    notes_list: List[str] = []
    prev_note = ""

    for idx, chunk in enumerate(chunks):
        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]
        chunk_hints = [
            h for h in (highlight_hints or [])
            if chunk_start <= h.get("timestamp", h.get("start", 0)) <= chunk_end
        ]
        hint_block = _format_highlight_hints(chunk_hints)

        prompt_parts = [f"【長尺動画のため {idx + 1}/{num_chunks} パートに分割して処理中】"]
        if prev_note:
            prompt_parts.append(f"（直前のパートまでの編集方針: {prev_note}）")
        prompt_parts.append(f"このパートで返す highlight_moments は最大{per_chunk_highlight_cap}件にしてください。")
        prompt_parts.append(f"文字起こしセグメント(JSON):\n{json.dumps(chunk, ensure_ascii=False)}")
        if hint_block:
            prompt_parts.append(hint_block)
        prompt = "\n\n".join(prompt_parts)

        raw = chat(prompt, system, model=model, max_tokens=_EDIT_PLAN_MAX_TOKENS, temperature=0.4)
        plan = _parse_json_safely(raw)
        if plan is None:
            repaired = _repair_json(raw, system, model)
            plan = _parse_json_safely(repaired) if repaired else None
        if plan is None:
            # このパートだけ解析失敗 → 動画全体をヒューリスティックに投げ出さず、
            # このパートだけ「原文のまま残す・強調なし」で処理を継続する
            plan = {
                "segments": [
                    {"start": s["start"], "end": s["end"], "text": s["text"], "emphasis": "normal", "keep": True}
                    for s in chunk
                ],
                "highlight_moments": [],
                "notes": "（このパートはAI応答の解析に失敗したため、原文のまま保持しました）",
            }

        plan = _validate_and_repair_plan(plan, chunk)
        all_segments.extend(plan.get("segments", []))
        all_highlights.extend(plan.get("highlight_moments", []))
        note = plan.get("notes", "")
        if note:
            notes_list.append(note)
            prev_note = note

    all_highlights.sort(key=lambda h: h.get("start", 0))
    if len(all_highlights) > max_highlights_total:
        all_highlights = all_highlights[:max_highlights_total]

    combined_notes = f"（{num_chunks}パートに分割して編集方針を統合）"
    if notes_list:
        combined_notes += " " + " / ".join(notes_list[:3])

    return {
        "segments": all_segments,
        "highlight_moments": all_highlights,
        "notes": combined_notes,
    }


def _repair_json(broken_text: str, system: str, model: str) -> Optional[str]:
    """
    generate_edit_plan の出力がJSONとしてパースできなかった場合に、1回だけ
    「有効なJSONに直して返して」とAIに頼み直す（軽微な壊れ方の大半はこれで直る）。
    """
    if not broken_text:
        return None
    fix_prompt = (
        "以下はJSONとして出力されるはずでしたが、そのままではパースに失敗しました。"
        "内容（テロップ文言・秒数・判定）はできる限りそのまま保った上で、"
        "有効なJSONのみを出力し直してください。前置き・説明文・Markdownのコードフェンスは一切不要です。\n\n"
        "---\n" + broken_text[:8000]
    )
    try:
        return chat(fix_prompt, system, model=model, max_tokens=_EDIT_PLAN_MAX_TOKENS, temperature=0.0)
    except Exception as e:
        print(f"JSON修復エラー: {e}")
        return None


def _validate_and_repair_plan(plan: Dict[str, Any], reference_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claudeが返したJSONの構造・値を検証し、軽微な問題は補正する防御的な後処理。
      - segments/highlight_moments の各要素で欠けているキーはデフォルト値で補う
      - start/end が reference_segments の時間範囲から外れていればクリップする
      - start >= end のような不正な区間は落とす
    「残す割合が学習値と大きくズレていないか」といった意味的な妥当性は、
    ここで機械的に上書きするとかえって判断の質を落としかねないため、あえて行わない
    （Claude自身の文脈判断を尊重する）。

    Args:
        plan               : パース済みJSON（dict）
        reference_segments : この呼び出しで渡した元セグメント（時間範囲の基準にする）

    Returns:
        補正後のplan（同じdictを変更して返す）
    """
    if not isinstance(plan, dict):
        return {"segments": [], "highlight_moments": [], "notes": ""}
    if not reference_segments:
        return plan

    lo = min(s.get("start", 0) for s in reference_segments)
    hi = max(s.get("end", lo) for s in reference_segments)

    def _clip(value, default: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, v))

    fixed_segments = []
    for s in plan.get("segments", []) or []:
        if not isinstance(s, dict):
            continue
        start = _clip(s.get("start", lo), lo)
        end = _clip(s.get("end", start), start)
        if end <= start:
            continue
        fixed_segments.append({
            "start": start,
            "end": end,
            "text": str(s.get("text", "") or ""),
            "emphasis": s.get("emphasis") if s.get("emphasis") in ("normal", "high") else "normal",
            "keep": bool(s.get("keep", True)),
        })

    fixed_highlights = []
    for h in plan.get("highlight_moments", []) or []:
        if not isinstance(h, dict):
            continue
        start = _clip(h.get("start", lo), lo)
        end = _clip(h.get("end", start + 0.5), start + 0.5)
        if end <= start:
            continue
        entry = {
            "start": start,
            "end": end,
            "reason": str(h.get("reason", "") or ""),
        }
        se_mood = h.get("se_mood")
        if se_mood in _ALLOWED_SE_MOODS:
            entry["se_mood"] = se_mood
        fixed_highlights.append(entry)

    plan["segments"] = fixed_segments
    plan["highlight_moments"] = fixed_highlights
    plan["notes"] = str(plan.get("notes", "") or "")
    return plan


def _parse_json_safely(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """AIの出力からJSON部分だけを安全に取り出す（前後に説明文・コードフェンスが付いても耐えるように）"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


# ============================================================
# ★ 概要欄・チャプターの自動生成（NEW ― 「動画編集で足りていない部分」の補完）
# ============================================================
# プロの編集者・投稿者の仕事には、カット編集そのものだけでなく
# 「YouTube投稿用の概要欄・チャプター作成」も含まれることが多い。
# 完成動画で実際に使われた発言（カット後のタイムライン基準）から、
# それらしい概要文とタイムスタンプ付きチャプターを自動生成する。

_DESCRIPTION_SYSTEM_EXTRA = """
渡す「実際に完成動画で使われた発言」（カット後のタイムライン上の開始時刻付き）をもとに、
YouTube投稿用の概要欄とチャプターを日本語でJSONのみで出力してください。
前置き・説明文・Markdownのコードフェンスは一切不要です。

出力するJSONの形式:
{
  "description": "視聴者向けの動画概要文（2〜4文程度。任意でハッシュタグを2〜4個末尾に添えてよい）",
  "chapters": [
    {"time": "0:00", "title": "オープニング"},
    {"time": "1:23", "title": "○○について"}
  ]
}

ルール:
- chapters は必ず "0:00" から始めること（YouTubeがチャプターとして認識するための必須要件）
- チャプターは3〜8個程度、動画の展開・話題の転換に応じて自然な区切りで設定する
- time は "分:秒"（1時間を超える場合のみ "時:分:秒"）形式の文字列にする
- 学習したテロップの文体（渡されていれば）があれば、descriptionの文体もそれに寄せてよい
- 発言内容から明らかに読み取れないことは書かない（誇張・憶測を避ける）
"""


def generate_video_description(
    kept_segments: List[Dict[str, Any]],
    style_data: Optional[dict] = None,
    style_label: str = "",
    reinforcement_text: str = "",
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    完成動画（カット後のタイムライン基準）で実際に使われた発言から、
    YouTube投稿用の概要欄文章とチャプター（タイムスタンプ付き見出し）を生成する。

    Args:
        kept_segments: 実際に使われた発言 [{"start","end","text",...}, ...]。
                       pipeline.render_final_video() の戻り値の "sub_segments" を
                       そのまま渡す想定（カット・時刻補正後のタイムライン基準のため）。
        style_data / style_label / reinforcement_text: 従来通り

    Returns:
        {"description": str, "chapters": [{"time": str, "title": str}, ...]}
        AI未使用・発言が無い・生成に失敗した場合は None。
    """
    if not is_ai_ready() or not kept_segments:
        return None

    compact = [
        {"start": round(s.get("start", 0), 1), "text": (s.get("text") or "").strip()}
        for s in kept_segments if (s.get("text") or "").strip()
    ]
    if not compact:
        return None

    resolved_model = model or DEFAULT_MODEL
    system = build_dynamic_system_prompt(
        style_data, style_label, reinforcement_text, extra=_DESCRIPTION_SYSTEM_EXTRA
    )
    prompt = f"実際に使われた発言(JSON。startはカット後タイムライン基準の秒数):\n{json.dumps(compact, ensure_ascii=False)}"

    raw = chat(prompt, system, model=resolved_model, max_tokens=1200, temperature=0.5)
    result = _parse_json_safely(raw)
    if not result or not isinstance(result.get("chapters"), list):
        return None

    chapters = [c for c in result.get("chapters", []) if isinstance(c, dict) and c.get("title")]
    if not chapters:
        return None
    if chapters[0].get("time") != "0:00":
        chapters = [{"time": "0:00", "title": "オープニング"}] + chapters

    return {
        "description": str(result.get("description", "") or ""),
        "chapters": chapters[:12],
    }