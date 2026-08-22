"""
features/media_library.py  ―  「定番素材」プリセットのカタログ管理

【BGMについて】
  著作権・利用規約の関係で、このリポジトリには実際の音源ファイルを同梱していません。
  代わりに、以下の仕組みだけを用意しています：

    assets/bgm_presets/manifest.json … プリセットの一覧（label, mood, filename）
    assets/bgm_presets/<filename>     … 実際の音源ファイル（.mp3 / .wav 等）

  manifest.json に登録されていても、実ファイルが assets/bgm_presets/ に
  存在しなければ一覧には出てこない（developerがまだ音源を配置していない状態を
  安全に扱うため）。

  音源を追加する場合は、ライセンスに従って利用できる音源を配置してください。
  日本のクリエイターに広く使われている無料・商用利用可の音源サイト例:
    - DOVA-SYNDROME (https://dova-s.jp/)
    - 魔王魂 (https://maou.audio/)
    - 甘茶の音楽工房 (https://amachamusic.chagasi.com/)
    - YouTube オーディオ ライブラリ
  いずれも利用規約・クレジット表記ルールを必ず確認のうえ使用してください。

【SEについて】
  features/se_presets.py で完全にプログラム生成（著作権フリー）しているため、
  こちらは追加ファイル不要ですぐに使えます。
"""

import json
import os
from typing import Dict, List

BGM_PRESET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "bgm_presets")
BGM_MANIFEST = os.path.join(BGM_PRESET_DIR, "manifest.json")


def list_bgm_presets() -> List[Dict]:
    """
    登録済みのBGMプリセット一覧を返す。
    manifest.jsonに書かれていても、実ファイルが存在しないエントリは除外する。

    Returns:
        [{"label": str, "mood": str, "path": str}, ...]（音源が1つも無ければ空リスト）
    """
    if not os.path.exists(BGM_MANIFEST):
        return []
    try:
        with open(BGM_MANIFEST, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        print(f"BGMプリセットのmanifest読み込みエラー: {e}")
        return []

    result = []
    for e in entries:
        filename = e.get("filename", "")
        path = os.path.join(BGM_PRESET_DIR, filename)
        if filename and os.path.exists(path):
            result.append({
                "label": e.get("label", filename),
                "mood": e.get("mood", ""),
                "path": path,
            })
    return result