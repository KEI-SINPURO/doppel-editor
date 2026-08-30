"""
ai/heuristic.py  ―  AI(Claude/Gemini)を一切使わない、ルールベースの編集プラン生成

【なぜこれがあるか】
  Claude/Gemini等の外部AI APIキーが無い・使えない状態でも、
  「動画分析→再現」機能そのものは最後まで動作するようにするための、
  完全にPythonのロジックだけで完結する代替エンジン。

  外部通信もAPIキーも一切不要で、無料・オフラインで動く。
  ai/model.py の generate_edit_plan() が使えない場合、
  app.py はこちらにフォールバックする。

【判定方法】
  - features/effects.py の detect_highlight_moments()（キーワード出現＋音量ベースの
    盛り上がり検出）を使い、盛り上がり区間に重なる発話セグメントを
    「emphasis: high」（強調テロップ）として扱う。
  - style_data（features/analyze.py の analyze_editing_patterns() が学習した
    「カットの癖」）が渡されていれば、その「フィラー語の除去傾向」を反映して
    "keep": false（動画から削る）を判定する。AI未使用時でも、
    学習した傾向をできるだけ再現するのが狙い。

【今回の変更点】
  従来は filler_removal_rate（フィラー語混じりの発言のうち、どれだけ削られていたか）
  という「動画全体で1つの数値」だけを見て判定していた。
  features/analyze.py の analyze_editing_patterns() が新たに学習した
  position_bias（動画内の位置＝冒頭/中盤/終盤ごとの残す割合）が使える場合は、
  「filler_removal_rate自体はそれほど高くなくても、冒頭の挨拶・雑談部分では
  フィラー語混じりの相槌はほぼ削られていた」といった、位置に応じたより繊細な
  判定ができるようにした（AI未使用時でも精度を底上げする狙い）。
  なお、その発言の中身（テロップ本文）に含まれる細かいフィラー語の「部分トリム」は
  pipeline.py 側で features/generate.py の trim_filler_word_edges() が担当するため、
  ここでは引き続き「発言まるごと残すか消すか」の判定のみを行う。
"""

from typing import Any, Dict, List, Optional

# features/analyze.py の FILLER_WORDS と同じ考え方のリスト。
# heuristic.py は「外部ライブラリ・APIキー一切不要」という設計方針を保つため、
# features側の定数をimportせず、ここで小さく複製している。
_FILLER_WORDS = [
    "えー", "えっと", "えっとー", "あのー", "あの", "まあ", "まぁ",
    "なんか", "そのー", "その", "うーん", "ちょっと待って",
]


def _position_label(t: float, total_start: float, total_duration: float) -> str:
    """発言時刻が、動画内の冒頭(0~20%)／中盤(20~80%)／終盤(80~100%)のどこに位置するかを返す"""
    if total_duration <= 0:
        return "中盤"
    frac = (t - total_start) / total_duration
    if frac < 0.2:
        return "冒頭"
    elif frac < 0.8:
        return "中盤"
    return "終盤"


def build_heuristic_edit_plan(
    segments: List[Dict[str, Any]],
    highlight_moments: List[Dict[str, Any]],
    style_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    AIを使わず、キーワード・音量ベースの盛り上がり検出結果と、
    学習済みの「カットの癖」（あれば）だけを使って編集プラン
    （generate_edit_plan と同じ形のJSON、"keep" 付き）を組み立てる。

    Args:
        segments: Whisperの発話区間 [{"start","end","text"}, ...]
        highlight_moments: features.effects.detect_highlight_moments() の結果
            [{"timestamp", "end", "type", "score", "text"}, ...]
        style_data: 学習済みスタイル（editor["styles"][sid]["style_data"]）。
            "editing_patterns"."filler_removal_rate"・"position_bias" があれば、
            フィラー語だけの短い相槌を削るかどうかの判定に使う。

    Returns:
        {"segments": [...], "highlight_moments": [...], "notes": "..."}
        （ai/model.py の generate_edit_plan() と互換の形式）
    """
    highlight_ranges = [
        (h.get("timestamp", 0), h.get("end", h.get("timestamp", 0) + 0.5))
        for h in highlight_moments
    ]

    def _is_highlighted(seg: Dict[str, Any]) -> bool:
        s, e = seg.get("start", 0), seg.get("end", 0)
        return any(s < hr_end and e > hr_start for hr_start, hr_end in highlight_ranges)

    # 学習済みの「フィラー語除去傾向」があれば反映する。
    # データが無ければ0.3をデフォルトにして、明らかなフィラーのみ控えめに除去する。
    patterns = (style_data or {}).get("editing_patterns", {}) or {}
    filler_removal_rate = patterns.get("filler_removal_rate", 0.3)
    position_bias = patterns.get("position_bias") or {}

    total_start = segments[0].get("start", 0) if segments else 0.0
    total_end = segments[-1].get("end", total_start) if segments else total_start
    total_duration = max(total_end - total_start, 0.01)

    def _is_filler_only(text: str) -> bool:
        stripped = text.strip()
        return len(stripped) <= 6 and any(fw in stripped for fw in _FILLER_WORDS)

    used_position_bias = False
    plan_segments = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        keep = True
        if _is_filler_only(text):
            if filler_removal_rate >= 0.4:
                keep = False
            else:
                # filler_removal_rate単体では判定が微妙でも、この発言の「位置」
                # （冒頭/終盤）が元々あまり残されていない傾向であれば、フィラーのみの
                # 相槌はそこに合わせて削る（例：冒頭の雑談は基本カットする編集者、など）
                pos_label = _position_label(seg.get("start", 0), total_start, total_duration)
                pos_keep_ratio = position_bias.get(pos_label)
                if pos_keep_ratio is not None and pos_keep_ratio < 0.5:
                    keep = False
                    used_position_bias = True
        plan_segments.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": text,
            "emphasis": "high" if _is_highlighted(seg) else "normal",
            "keep": keep,
        })

    plan_highlights = [
        {
            "start": h.get("timestamp", 0),
            "end": h.get("end", h.get("timestamp", 0) + 0.5),
            "reason": f"キーワード/音量検出（スコア {h.get('score', 0)}）",
        }
        for h in sorted(highlight_moments, key=lambda x: x.get("score", 0), reverse=True)[:5]
    ]

    notes = "AI未使用：キーワード出現・音量の盛り上がり、および学習したカットの癖をルールベースで自動判定しました。"
    if used_position_bias:
        notes += "（動画内の位置ごとの残す傾向も加味しています）"

    return {
        "segments": plan_segments,
        "highlight_moments": plan_highlights,
        "notes": notes,
    }