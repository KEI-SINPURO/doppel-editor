"""
ai/auth.py  ―  認証層（Supabase）

【今回追加した点】
  Googleログイン（OAuth）を追加しました。
  Supabase側で Google プロバイダーを有効化しておく必要があります
  （README.md の「Googleログインの設定」を参照してください）。

  Streamlitはブラウザリダイレクトの受け皿を自前で持たないため、
  以下の2ステップに分けて実装しています。
    1. sign_in_with_google() でOAuthの認可URLを発行し、リンクを開いてもらう
    2. Googleログイン後、Supabaseが `?code=...` を付けて元のURLにリダイレクトしてくるので、
       app.py 側で st.query_params から code を受け取り、
       exchange_code_for_session() でセッションに交換する
"""

import os
import json
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
APP_PUBLIC_URL = os.getenv("APP_PUBLIC_URL", "")


def get_client() -> Client:
    """Supabaseクライアントを作成する。

    .env に SUPABASE_URL / SUPABASE_KEY が設定されていないと
    create_client(None, None) が呼ばれて分かりにくいエラーで落ちるため、
    ここで明確なエラーメッセージを出す。
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            ".env ファイルに SUPABASE_URL と SUPABASE_KEY を設定してください。"
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================
# メール認証
# ============================================================

def sign_up(email: str, password: str) -> dict:
    """新規登録"""
    try:
        client = get_client()
        response = client.auth.sign_up({"email": email, "password": password})
        if response.user:
            client.table("profiles").insert({
                "id": str(response.user.id),
                "email": email,
            }).execute()
            return {"success": True, "user": response.user}
        return {"success": False, "error": "登録に失敗しました"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def sign_in(email: str, password: str) -> dict:
    """ログイン"""
    try:
        client = get_client()
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        if response.user:
            return {"success": True, "user": response.user, "session": response.session}
        return {"success": False, "error": "ログインに失敗しました"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def sign_out() -> dict:
    """ログアウト"""
    try:
        client = get_client()
        client.auth.sign_out()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_user(access_token: str) -> dict:
    """ユーザー情報を取得"""
    try:
        client = get_client()
        response = client.auth.get_user(access_token)
        if response is not None and response.user:
            return {"success": True, "user": response.user}
        return {"success": False, "error": "ユーザーが見つかりません"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Googleログイン（OAuth）
# ============================================================

def sign_in_with_google() -> dict:
    """
    Google OAuthの認可URLを発行する。
    戻り値の url を `st.link_button` 等でユーザーに開いてもらい、
    Google側の認証後、APP_PUBLIC_URL に ?code=... 付きでリダイレクトされてくる。
    """
    try:
        client = get_client()
        res = client.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": APP_PUBLIC_URL} if APP_PUBLIC_URL else {},
        })
        return {"success": True, "url": res.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


def exchange_code_for_session(code: str) -> dict:
    """GoogleログインのリダイレクトURLから受け取った code をセッションに交換する"""
    try:
        client = get_client()
        res = client.auth.exchange_code_for_session({"auth_code": code})
        if res.session and res.user:
            return {"success": True, "user": res.user, "session": res.session}
        return {"success": False, "error": "セッション交換に失敗しました"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 編集者データのクラウド同期
# ============================================================

def load_editors_remote(user_id: str, access_token: str) -> list:
    """Supabaseから編集者一覧を取得"""
    try:
        client = get_client()
        client.postgrest.auth(access_token)
        response = client.table("editors").select("*").eq("user_id", user_id).execute()
        return response.data or []
    except Exception as e:
        print(f"編集者取得エラー: {e}")
        return []


def save_editor_remote(editor: dict, user_id: str, access_token: str) -> bool:
    """Supabaseに編集者を保存"""
    try:
        client = get_client()
        client.postgrest.auth(access_token)
        editor_data = {**editor, "user_id": user_id}
        client.table("editors").upsert(editor_data).execute()
        return True
    except Exception as e:
        print(f"編集者保存エラー: {e}")
        return False


def delete_editor_remote(editor_id: str, access_token: str) -> bool:
    """Supabaseから編集者を削除"""
    try:
        client = get_client()
        client.postgrest.auth(access_token)
        client.table("editors").delete().eq("id", editor_id).execute()
        return True
    except Exception as e:
        print(f"編集者削除エラー: {e}")
        return False


def save_feedback_remote(feedback: dict, user_id: str, access_token: str) -> bool:
    """Supabaseにフィードバックを保存"""
    try:
        client = get_client()
        client.postgrest.auth(access_token)
        client.table("feedbacks").insert({
            "editor_id": feedback.get("editor_id"),
            "user_id": user_id,
            "content": feedback,
        }).execute()
        return True
    except Exception as e:
        print(f"フィードバック保存エラー: {e}")
        return False
