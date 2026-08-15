"""
features パッケージ
===================
動画処理まわりの実装（Doppel Editorの「実際に編集する」部分）。

  analyze.py   … 動画を分析してカット数・テンポ・テロップ色・色調を取得
  transcribe.py… Whisperで音声を文字起こし
  generate.py  … 無音カット・テロップ焼き込み・字幕(.srt)出力
  effects.py   … カラーグレーディング・ズーム・盛り上がり検出
  branding.py  … 個人素材（ロゴ・BGM・効果音）の適用
"""

__version__ = "2.0.0"
