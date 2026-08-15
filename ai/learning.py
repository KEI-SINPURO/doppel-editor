"""
ai/learning.py  ―  フィードバック学習（プロンプトベースの継続学習）

【方式について】
  旧バージョンは Ollama の `ollama create` で Modelfile を書き換え、
  実際にモデルを再学習していました。
  これはローカルにOllamaサーバーを常設する必要があり、
  テック甲子園の応募規約（Webアプリは公開URLでのデプロイが必須／
  ローカル環境のトンネリング公開は不可）と相性が悪いため、今回は不採用にしました。

  代わりに、ユーザーの「良い評価だった提案例」「好みプロファイル」を蓄積し、
  Claude API 呼び出しのたびにシステムプロンプトへ注入する方式にしています。
  モデルの重みは変えていませんが、使うたびに文脈として「そのユーザー専用の
  参考データ」が渡るため、実質的に「使うほど自分に近づく」体験を実現できます。

保存先: ~/.doppel_editor/training/<editor_id>/
  examples.json … フィードバック履歴
  profile.json  … 評価数などの集計プロファイル
"""

import json
import os
from datetime import datetime
from typing import Dict, List

_BASE_DIR = os.path.expanduser("~/.doppel_editor/training")
_MAX_EXAMPLES_IN_PROMPT = 3


def _dir(editor_id: str) -> str:
    return os.path.join(_BASE_DIR, editor_id)


def _examples_file(editor_id: str) -> str:
    return os.path.join(_dir(editor_id), "examples.json")


def _profile_file(editor_id: str) -> str:
    return os.path.join(_dir(editor_id), "profile.json")


def _read_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class FeedbackLearner:
    """編集者（クローン）1体単位でフィードバックを蓄積・要約するクラス"""

    def __init__(self, editor_id: str):
        self.editor_id = editor_id
        os.makedirs(_dir(editor_id), exist_ok=True)

    def save(self, query: str, response: str, rating: int, style_label: str = "") -> bool:
        """
        Args:
            query      : 何についての提案・編集だったか（動画名など）
            response   : AIの提案文 or 編集メモ
            rating     : +1（良い） / -1（改善が必要）
            style_label: どのジャンル別スタイルを使ったか
        """
        try:
            examples = _read_json(self._examples_path(), [])
            examples.append({
                "timestamp": datetime.now().isoformat(),
                "query_summary": (query or "")[:120],
                "response": (response or "")[:1500],
                "rating": rating,
                "style_label": style_label,
            })
            _write_json(self._examples_path(), examples)
            self._update_profile(rating, style_label)
            return True
        except Exception as e:
            print(f"フィードバック保存エラー: {e}")
            return False

    def _examples_path(self) -> str:
        return _examples_file(self.editor_id)

    def _profile_path(self) -> str:
        return _profile_file(self.editor_id)

    def _update_profile(self, rating: int, style_label: str):
        profile = _read_json(self._profile_path(), {
            "total_ratings": 0, "good_ratings": 0, "bad_ratings": 0, "style_scores": {},
        })
        profile["total_ratings"] = profile.get("total_ratings", 0) + 1
        if rating == 1:
            profile["good_ratings"] = profile.get("good_ratings", 0) + 1
        else:
            profile["bad_ratings"] = profile.get("bad_ratings", 0) + 1
        if style_label:
            scores = profile.get("style_scores", {})
            scores[style_label] = scores.get(style_label, 0) + rating
            profile["style_scores"] = scores
        _write_json(self._profile_path(), profile)

    def build_reinforcement_prompt(self) -> str:
        """
        Claude API のシステムプロンプトに注入する「このユーザー専用の強化テキスト」を組み立てる。
        過去の高評価の提案例を few-shot として渡すことで、疑似的なファインチューニング効果を狙う。
        データがまだ少ない場合は空文字列を返す（＝一般的な提案にフォールバックする）。
        """
        examples = _read_json(self._examples_path(), [])
        profile = _read_json(self._profile_path(), {})

        good = [e for e in examples if e.get("rating") == 1]
        good_sorted = sorted(good, key=lambda x: x["timestamp"], reverse=True)
        top = good_sorted[:_MAX_EXAMPLES_IN_PROMPT]

        if not top and profile.get("total_ratings", 0) < 1:
            return ""

        lines = ["【このユーザー専用の強化データ（過去の評価から学習した傾向）】"]
        if profile.get("total_ratings", 0) >= 3:
            lines.append(
                f"評価実績: 全{profile.get('total_ratings', 0)}件中、"
                f"良い評価 {profile.get('good_ratings', 0)}件 / 改善要求 {profile.get('bad_ratings', 0)}件"
            )
        for ex in top:
            lines.append(f"- 過去に高評価だった提案・編集の例: 「{ex['response'][:200]}」")
        if top:
            lines.append("この傾向を最優先で反映し、一貫性のある提案・編集をしてください。")
        return "\n".join(lines)

    def get_stats(self) -> Dict:
        examples = _read_json(self._examples_path(), [])
        profile = _read_json(self._profile_path(), {})
        return {
            "total_feedback": len(examples),
            "good_ratings": sum(1 for e in examples if e.get("rating") == 1),
            "bad_ratings": sum(1 for e in examples if e.get("rating") == -1),
            "total_ratings": profile.get("total_ratings", 0),
        }
