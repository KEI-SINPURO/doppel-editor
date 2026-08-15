#!/bin/bash
# ============================================================
# Doppel Editor セットアップスクリプト
# 使い方: bash setup.sh
# ============================================================

set -e

echo ""
echo "========================================"
echo "  Doppel Editor セットアップ開始"
echo "========================================"
echo ""

if [ ! -d "venv" ]; then
  echo "【Step 1】venv を作成しています..."
  python3 -m venv venv
  echo "✅ venv 作成完了"
else
  echo "【Step 1】venv は既に存在します → スキップ"
fi

echo ""
echo "【Step 2】venv を有効化しています..."
source venv/bin/activate
echo "✅ venv 有効化完了 ($(python --version))"

echo ""
echo "【Step 3】pip を最新版に更新しています..."
pip install --upgrade pip --quiet
echo "✅ pip 更新完了"

echo ""
echo "【Step 4】必要なパッケージをインストールしています..."
echo "  （初回は数分かかります。しばらくお待ちください）"
pip install -r requirements.txt --quiet
echo "✅ パッケージインストール完了"

echo ""
echo "【Step 5】.env ファイルを確認しています..."
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  .env ファイルを作成しました（SUPABASE_URL / SUPABASE_KEY / ANTHROPIC_API_KEY を設定してください）"
else
  echo "✅ .env ファイルは存在します"
fi

echo ""
echo "========================================"
echo "  セットアップ完了！"
echo "========================================"
echo ""
echo "次のステップ:"
echo "1. .env に SUPABASE_URL / SUPABASE_KEY / ANTHROPIC_API_KEY を設定する"
echo "2. VS Code 左下の Python バージョンをクリックし「./venv/bin/python」を選ぶ"
echo "3. アプリを起動する:"
echo "   source venv/bin/activate"
echo "   streamlit run app.py"
echo ""
