"""
ai パッケージ
=============
Doppel Editor のAI・データ管理まわり。

  trainer.py  … 編集者(クローン)・ジャンル別スタイル・個人素材・フィードバックの保存
  model.py    … Claude API 呼び出し（編集アドバイス／サムネ提案／自動再現プラン生成）
  learning.py … フィードバックを蓄積し、Claude APIへの強化テキストを組み立てる
  auth.py     … Supabase認証（メール／Google）とデータのクラウド同期
"""

__version__ = "2.0.0"
