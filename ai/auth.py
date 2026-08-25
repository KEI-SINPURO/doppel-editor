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
import base64
import hashlib
import secrets
import tempfile
from urllib.parse import urlencode
from typing import Optional
import httpx
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

def _pkce_verifier_path() -> str:
    """code_verifierを一時保存するファイルパス（同一プロセス内でタブをまたいで共有するため）"""
    return os.path.join(tempfile.gettempdir(), "doppel_oauth_verifier.txt")


def _generate_pkce_pair():
    """PKCE用のcode_verifier / code_challengeを自前で生成する"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def sign_in_with_google() -> dict:
    """
    Google OAuthの認可URLを発行する。
    ライブラリ側のPKCE状態管理（タブをまたぐと消えてしまう）を使わず、
    code_verifierを自分たちで生成・一時保存し、認可URLも直接組み立てる。
    """
    try:
        verifier, challenge = _generate_pkce_pair()
        with open(_pkce_verifier_path(), "w") as f:
            f.write(verifier)

        params = {
            "provider": "google",
            "redirect_to": APP_PUBLIC_URL,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
            "apikey": SUPABASE_KEY,
        }
        url = f"{SUPABASE_URL}/auth/v1/authorize?{urlencode(params)}"
        return {"success": True, "url": url}
    except Exception as e:
        return {"success": False, "error": str(e)}


def exchange_code_for_session(code: str) -> dict:
    """GoogleログインのリダイレクトURLから受け取った code をセッションに交換する"""
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return {"success": False, "error": "SUPABASE_URL/SUPABASE_KEYが設定されていません"}
        verifier_path = _pkce_verifier_path()
        if not os.path.exists(verifier_path):
            return {"success": False, "error": "code_verifierが見つかりません。もう一度ログインをやり直してください。"}
        with open(verifier_path, "r") as f:
            verifier = f.read().strip()
        os.remove(verifier_path)

        resp = httpx.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "pkce"},
            headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
            json={"auth_code": code, "code_verifier": verifier},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"{resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            return {"success": False, "error": "トークンの取得に失敗しました"}

        client = get_client()
        session_res = client.auth.set_session(access_token, refresh_token)
        if session_res.session and session_res.user:
            return {"success": True, "user": session_res.user, "session": session_res.session}
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