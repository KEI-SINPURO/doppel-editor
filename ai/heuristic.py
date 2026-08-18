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
  features/effects.py の detect_highlight_moments()（キーワード出現＋音量ベースの
  盛り上がり検出）を使い、盛り上がり区間に重なる発話セグメントを
  「emphasis: high」（強調テロップ）として扱う。
"""

from typing import Any, Dict, List


def build_heuristic_edit_plan(
    segments: List[Dict[str, Any]],
    highlight_moments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    AIを使わず、キーワード・音量ベースの盛り上がり検出結果だけを使って
    編集プラン（generate_edit_plan と同じ形のJSON）を組み立てる。

    Args:
        segments: Whisperの発話区間 [{"start","end","text"}, ...]
        highlight_moments: features.effects.detect_highlight_moments() の結果
            [{"timestamp", "end", "type", "score", "text"}, ...]

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

    plan_segments = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        plan_segments.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": text,
            "emphasis": "high" if _is_highlighted(seg) else "normal",
        })

    plan_highlights = [
        {
            "start": h.get("timestamp", 0),
            "end": h.get("end", h.get("timestamp", 0) + 0.5),
            "reason": f"キーワード/音量検出（スコア {h.get('score', 0)}）",
        }
        for h in sorted(highlight_moments, key=lambda x: x.get("score", 0), reverse=True)[:5]
    ]

    return {
        "segments": plan_segments,
        "highlight_moments": plan_highlights,
        "notes": "AI未使用：キーワード出現・音量の盛り上がりをルールベースで自動判定しました。",
    }