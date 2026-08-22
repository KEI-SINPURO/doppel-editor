"""
features/export_presets.py  ―  書き出し設定のプリセット

features/generate.py の generate_with_subtitles() が受け取る export_settings 引数
（{"resolution","fps","bitrate","codec","ext"}）にそのまま渡せる形式で用意している。
プラットフォームごとに適した設定を選ぶだけで、書き出しクオリティを調整できる。
"""

from typing import Dict, Optional

# resolution は今回すべて None（自動リフレーム/元動画の解像度をそのまま使う）にしている。
# 強制リサイズは画質劣化や意図しないクロップにつながりやすいため、
# 解像度の変更は「演出オプション」の自動リフレーム機能に任せる設計。
EXPORT_PRESETS: Dict[str, Dict] = {
    "標準（バランス重視）": {
        "resolution": None, "fps": None, "bitrate": "12M", "codec": "libx264", "ext": "mp4",
    },
    "YouTube（高画質）": {
        "resolution": None, "fps": None, "bitrate": "16M", "codec": "libx264", "ext": "mp4",
    },
    "Shorts / Reels / TikTok（縦型・軽量）": {
        "resolution": None, "fps": 30, "bitrate": "8M", "codec": "libx264", "ext": "mp4",
    },
    "X（Twitter）向け軽量": {
        "resolution": None, "fps": 30, "bitrate": "6M", "codec": "libx264", "ext": "mp4",
    },
}


def list_export_preset_names() -> list:
    return list(EXPORT_PRESETS.keys())


def get_export_preset(name: str) -> Optional[Dict]:
    return EXPORT_PRESETS.get(name)