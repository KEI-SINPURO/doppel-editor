"""
app.py  ―  Doppel Editor メインアプリケーション（v2: スコープ絞り込み版）

【今回のバージョンでやること】
  過去の動画を分析し、その分析結果をもとに「その人らしい動画編集」を
  新しい動画に自動で再現する機能、これだけに絞っています。
  （診断クイズ・AIチャットでのスタイル説明・ミーム提案・YouTuber別知識ベースは削除）

  追加した機能:
    - 編集クローン1体の中に、ジャンル別の複数スタイルを持てる
    - 個人素材（ロゴ・フォント・BGM・効果音）をアップロードして動画生成に使える
    - サムネイル生成は維持
    - ログインにGoogleを追加
"""

import streamlit as st
import sys
import os

st.set_page_config(
    page_title="Doppel Editor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

sys.path.insert(0, os.path.dirname(__file__))

# ── Streamlit Community Cloud の Secrets を環境変数にも反映する ─────────────
# ローカルでは .env がそのまま使われるが、Community Cloud では
# 「Advanced settings > Secrets」に貼り付けたTOMLが st.secrets に入るだけで
# os.environ には自動反映されない。ai/auth.py・ai/model.py は os.getenv() で
# 読む前提になっているため、ここで橋渡しをしておく。
try:
    for _key in st.secrets.keys():
        os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass  # ローカルで secrets.toml が無い場合はここに来るが問題ない

from dotenv import load_dotenv
load_dotenv()

from ui.theme import get_css, THEMES, get_theme as _get_theme
from ui.components import svg, get_genre_icon, ICON_CHOICES, render_section_title, render_alert, run_ai_with_progress

from ai.trainer import (
    init_storage, load_editors, create_editor, delete_editor, get_editor, update_editor,
    add_style, save_style_data, rename_style, delete_style, add_video_to_style, get_style,
    save_asset, delete_asset, load_assets,
    save_feedback, get_editor_summary,
)
from ai.auth import (
    sign_up, sign_in, sign_out, sign_in_with_google, exchange_code_for_session,
    load_editors_remote, save_editor_remote, delete_editor_remote, save_feedback_remote,
)
from ai.model import is_ai_ready, get_thumbnail_suggestion, generate_edit_plan
from ai.heuristic import build_heuristic_edit_plan
from ai.learning import FeedbackLearner

from features.transcribe import transcribe_video, get_plain_text, estimate_time
from features.analyze import analyze_style, analyze_brightness
from features.generate import auto_cut_by_segments, generate_with_subtitles, generate_srt
from features.effects import apply_color_grade, apply_zoom_effect, detect_highlight_moments
from features.branding import overlay_logo, mix_bgm

init_storage()

# ── セッション状態の初期化 ─────────────────────────────────────────────────
DEFAULTS = {
    "page": "auth",
    "selected_editor_id": None,
    "current_theme": "ダーク",
    "user": None,
    "session": None,
    "delete_confirm_id": None,
    "last_thumbnail": "",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def get_theme_name() -> str:
    eid = st.session_state.get("selected_editor_id")
    if eid:
        e = get_editor(eid)
        if e:
            return e.get("theme", "ダーク")
    return st.session_state.get("current_theme", "ダーク")


def inject_css():
    st.markdown(get_css(get_theme_name()), unsafe_allow_html=True)


def _sync_editor(eid: str):
    s = st.session_state.get("session")
    u = st.session_state.get("user")
    if s and u:
        e = get_editor(eid)
        if e:
            save_editor_remote(e, str(u.id), s.access_token)


# ============================================================
# Googleログインのコールバック処理（?code=... を受け取ってセッション交換）
# ============================================================
def handle_oauth_callback():
    params = st.query_params
    code = params.get("code")
    if code:
        result = exchange_code_for_session(code)
        st.query_params.clear()
        if result.get("success"):
            st.session_state["user"] = result["user"]
            st.session_state["session"] = result["session"]
            st.session_state["page"] = "home_main" if load_editors() else "home_initial"
        st.rerun()


# ============================================================
# メインルーティング
# ============================================================
def main():
    handle_oauth_callback()
    inject_css()
    {
        "auth": render_auth,
        "home_initial": render_home_initial,
        "create_editor": render_create_editor,
        "home_main": render_home_main,
        "editor_detail": render_editor_detail,
        "settings_home": render_settings_home,
    }.get(st.session_state["page"], render_auth)()


# ============================================================
# サイドバー
# ============================================================
def render_sidebar():
    with st.sidebar:
        try:
            _sidebar_content()
        except Exception as e:
            st.error(f"サイドバーの読み込みに失敗しました\n\n{str(e)[:150]}")


def _sidebar_content():
    theme_name = get_theme_name()
    t = _get_theme(theme_name)
    current_page = st.session_state.get("page", "")
    editors = load_editors()

    ai_ready = is_ai_ready()
    if ai_ready:
        ai_color, ai_dot, ai_text = t['success'], "●", "Claude AI 動作中"
    else:
        ai_color, ai_dot, ai_text = t['error'], "○", "AI未設定"

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;padding:10px 2px 16px;
        border-bottom:1px solid {t['border']};margin-bottom:14px;">
        <div style="width:38px;height:38px;flex-shrink:0;
            background:linear-gradient(135deg,{t['accent_sub']},{t['accent']});
            border-radius:10px;display:flex;align-items:center;justify-content:center;
            box-shadow:0 4px 12px {t['accent_sub']}55;font-size:20px;">🎬</div>
        <div>
            <div style="font-size:16px;font-weight:700;color:{t['text_primary']};
                letter-spacing:-0.01em;line-height:1.2;">Doppel Editor</div>
            <div style="font-size:10px;color:{t['text_secondary']};margin-top:2px;">編集クローン AI</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size:10px;font-weight:600;color:{t['text_secondary']};
        letter-spacing:0.12em;text-transform:uppercase;margin-bottom:6px;padding:0 2px;">MENU</div>
    """, unsafe_allow_html=True)

    is_home = current_page in ["home_main", "home_initial"]
    if st.button("▶  ホーム" if is_home else "    ホーム", use_container_width=True, key="nav_home",
                 type="primary" if is_home else "secondary"):
        st.session_state["page"] = "home_main" if editors else "home_initial"
        st.rerun()

    is_settings = current_page == "settings_home"
    if st.button("▶  設定" if is_settings else "    設定", use_container_width=True, key="nav_settings",
                 type="primary" if is_settings else "secondary"):
        st.session_state["page"] = "settings_home"
        st.rerun()

    st.markdown(f"<div style='height:1px;background:{t['border']};margin:14px 0;'></div>", unsafe_allow_html=True)

    ai_warn = ""
    if not ai_ready:
        ai_warn = (
            f'<div style="margin-top:8px;padding:7px 9px;background:{t["error"]}15;'
            f'border-radius:6px;font-size:10px;color:{t["error"]};line-height:1.5;">'
            f'.env に ANTHROPIC_API_KEY が未設定です</div>'
        )
    st.markdown(f"""
    <div style="background:{t['bg_card']};border:0.5px solid {t['border']};border-radius:10px;padding:12px 14px;">
        <div style="font-size:10px;font-weight:600;color:{t['text_secondary']};letter-spacing:0.1em;
            text-transform:uppercase;margin-bottom:8px;">AI STATUS</div>
        <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:10px;color:{ai_color};">{ai_dot}</span>
            <span style="font-size:12px;color:{ai_color};font-weight:500;">{ai_text}</span>
        </div>
        {ai_warn}
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div style='height:1px;background:{t['border']};margin:12px 0;'></div>", unsafe_allow_html=True)

    user = st.session_state.get("user")
    if user:
        st.markdown(f"""
        <div style="font-size:11px;color:{t['text_secondary']};margin-bottom:8px;
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{user.email}</div>
        """, unsafe_allow_html=True)
        if st.button("ログアウト", use_container_width=True, key="nav_logout"):
            sign_out()
            for k in ["user", "session", "selected_editor_id"]:
                st.session_state[k] = None
            st.session_state["page"] = "auth"
            st.rerun()
    else:
        if st.button("ログイン / 新規登録", use_container_width=True, key="nav_login"):
            st.session_state["page"] = "auth"
            st.rerun()


# ============================================================
# 認証画面
# ============================================================
def render_auth():
    inject_css()
    t = _get_theme(get_theme_name())

    _, col2, _ = st.columns([1, 1.2, 1])
    with col2:
        st.markdown(f"""
        <div style="text-align:center;padding:48px 0 28px;">
            <div style="width:72px;height:72px;background:linear-gradient(135deg,{t['accent_sub']},{t['accent']});
                border-radius:20px;display:inline-flex;align-items:center;justify-content:center;
                margin-bottom:18px;box-shadow:0 8px 24px {t['accent_sub']}44;font-size:36px;">🎬</div>
            <h1 style="font-size:26px;font-weight:700;color:{t['text_primary']};margin:0 0 6px;
                letter-spacing:-0.02em;">Doppel Editor</h1>
            <p style="font-size:13px;color:{t['text_secondary']};margin:0;">
                あなたの動画から学習し、あなたらしく編集するAI
            </p>
        </div>
        """, unsafe_allow_html=True)

        g = sign_in_with_google()
        if g.get("success"):
            st.link_button("🔵 Googleでログイン", g["url"], use_container_width=True)
        else:
            st.caption("Googleログインは現在利用できません（Supabase側の設定が必要です）")

        st.markdown("<div style='text-align:center;color:#666;font-size:12px;margin:10px 0;'>または</div>",
                     unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["ログイン", "新規登録"])
        with tab1:
            email_l = st.text_input("メールアドレス", placeholder="example@email.com", key="l_email")
            password_l = st.text_input("パスワード", type="password", key="l_pass")
            if st.button("ログイン", use_container_width=True, type="primary", key="login_btn"):
                if email_l and password_l:
                    with st.spinner("ログイン中..."):
                        r = sign_in(email_l, password_l)
                    if r["success"]:
                        st.session_state["user"] = r["user"]
                        st.session_state["session"] = r["session"]
                        _sync_from_remote()
                        st.session_state["page"] = "home_main" if load_editors() else "home_initial"
                        st.rerun()
                    else:
                        st.error("メールアドレスまたはパスワードが違います")
                else:
                    st.warning("全て入力してください")

        with tab2:
            email_s = st.text_input("メールアドレス", placeholder="example@email.com", key="s_email")
            password_s = st.text_input("パスワード", type="password", key="s_pass")
            pass_s2 = st.text_input("パスワード（確認）", type="password", key="s_pass2")
            if st.button("新規登録", use_container_width=True, type="primary", key="signup_btn"):
                if email_s and password_s:
                    if password_s != pass_s2:
                        st.error("パスワードが一致しません")
                    elif len(password_s) < 6:
                        st.error("パスワードは6文字以上にしてください")
                    else:
                        with st.spinner("登録中..."):
                            r = sign_up(email_s, password_s)
                        st.success("登録完了！ログインしてください") if r["success"] else st.error(r["error"])
                else:
                    st.warning("全て入力してください")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("ゲストとして続ける", use_container_width=True, key="guest_btn"):
            st.session_state["page"] = "home_initial"
            st.rerun()


def _sync_from_remote():
    s = st.session_state.get("session")
    u = st.session_state.get("user")
    if s and u:
        remote = load_editors_remote(str(u.id), s.access_token)
        if remote:
            from ai.trainer import save_editors
            save_editors(remote)


# ============================================================
# ホーム（初期）
# ============================================================
def render_home_initial():
    inject_css()
    render_sidebar()
    t = _get_theme(get_theme_name())

    _, main_col, _ = st.columns([1, 5, 1])
    with main_col:
        st.markdown(f"""
        <div style="text-align:center;padding:48px 0 32px;">
            <div style="width:88px;height:88px;background:linear-gradient(135deg,{t['accent_sub']},{t['accent']});
                border-radius:24px;display:inline-flex;align-items:center;justify-content:center;
                margin-bottom:18px;box-shadow:0 12px 32px {t['accent_sub']}55;font-size:44px;">🎬</div>
            <div style="background:{t['accent']}22;border:0.5px solid {t['accent']}44;border-radius:20px;
                padding:5px 16px;font-size:11px;color:{t['accent']};display:inline-block;margin-bottom:18px;
                letter-spacing:0.06em;font-weight:600;">AI 編集クローン</div>
            <h1 style="font-size:28px;font-weight:700;color:{t['text_primary']};line-height:1.4;
                margin:0 0 12px;letter-spacing:-0.02em;">もう一人の自分（編集者）を作る</h1>
            <p style="font-size:14px;color:{t['text_secondary']};line-height:1.9;margin:0 0 28px;">
                過去に編集した動画をAIが分析し<br>新しい動画にも、あなたと同じ編集を自動で再現します
            </p>
        </div>
        """, unsafe_allow_html=True)

        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("編集クローンを作成する →", use_container_width=True, type="primary", key="create_btn"):
                st.session_state["page"] = "create_editor"
                st.rerun()

        st.markdown(f"""
        <div style="background:{t['bg_card']};border:0.5px solid {t['border']};border-radius:14px;
            padding:22px 26px;margin-top:24px;">
            <div style="font-size:14px;font-weight:600;color:{t['accent']};margin-bottom:14px;">📖 使い方</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                {"".join([
                    f'<div style="padding:14px;background:{t["bg_secondary"]};border-radius:10px;">'
                    f'<div style="font-size:11px;color:{t["accent"]};font-weight:600;margin-bottom:5px;">{s}</div>'
                    f'<div style="font-size:13px;color:{t["text_primary"]};font-weight:500;margin-bottom:3px;">{tt}</div>'
                    f'<div style="font-size:11px;color:{t["text_secondary"]};">{d}</div></div>'
                    for s, tt, d in [
                        ("Step 1", "編集クローンを作成", "名前・見た目を設定"),
                        ("Step 2", "スタイルを学習させる", "過去の編集済み動画をアップロード"),
                        ("Step 3", "新しい動画を渡す", "未編集の素材動画をアップロード"),
                        ("Step 4", "自動で再現編集", "テロップ・カット・色調まで自動生成"),
                    ]
                ])}
            </div>
        </div>
        """, unsafe_allow_html=True)


# ============================================================
# 編集クローン作成
# ============================================================
def render_create_editor():
    inject_css()
    render_sidebar()
    t = _get_theme(get_theme_name())

    _, col2, _ = st.columns([1, 3, 1])
    with col2:
        render_section_title("編集クローンの基本設定", get_theme_name())
        editor_name = st.text_input("編集クローンの名前", placeholder="例：ゲーム実況チャンネル用AI")

        st.markdown("**見た目のアイコン**")
        icon_choice = st.selectbox("アイコン", ICON_CHOICES, label_visibility="collapsed") or ICON_CHOICES[0]
        st.markdown(get_genre_icon(icon_choice, 60), unsafe_allow_html=True)

        theme_choice = st.selectbox("カラーテーマ", list(THEMES.keys())) or "ダーク"

        st.markdown("<br>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("← 戻る", use_container_width=True, key="back_create"):
                st.session_state["page"] = "home_initial"
                st.rerun()
        with col_b:
            if st.button("作成する →", use_container_width=True, type="primary", key="do_create"):
                final_name = editor_name if editor_name else "編集クローン"
                editor = create_editor(name=final_name, icon=icon_choice, theme=theme_choice)
                st.session_state["selected_editor_id"] = editor["id"]
                st.session_state["current_theme"] = theme_choice
                _sync_editor(editor["id"])
                st.session_state["page"] = "editor_detail"
                st.rerun()


# ============================================================
# ホーム画面（編集クローン一覧）
# ============================================================
def render_home_main():
    inject_css()
    render_sidebar()
    t = _get_theme(get_theme_name())

    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown(f"""
        <h2 style="font-size:20px;font-weight:600;color:{t['text_primary']};margin:0 0 4px;">あなたの編集クローン</h2>
        <p style="font-size:12px;color:{t['text_secondary']};margin:0 0 16px;">
            選択してスタイルの学習・動画の自動編集を行いましょう
        </p>
        """, unsafe_allow_html=True)
    with col_btn:
        if st.button("＋ 新規作成", use_container_width=True, type="primary", key="new_editor_btn"):
            st.session_state["page"] = "create_editor"
            st.rerun()

    editors = load_editors()

    if not editors:
        st.markdown(f"""
        <div style="text-align:center;padding:80px 20px;border:1px dashed {t['border']};
            border-radius:14px;margin-top:8px;">
            <div style="font-size:40px;margin-bottom:12px;opacity:0.3;">🎬</div>
            <p style="font-size:15px;color:{t['text_primary']};margin-bottom:6px;font-weight:500;">
                まだ編集クローンがいません</p>
            <p style="font-size:13px;color:{t['text_secondary']};">「＋ 新規作成」からクローンを作りましょう</p>
        </div>
        """, unsafe_allow_html=True)
        return

    for i in range(0, len(editors), 2):
        cols = st.columns(2, gap="medium")
        for j, col in enumerate(cols):
            if i + j >= len(editors):
                break
            editor = editors[i + j]
            styles = editor.get("styles", {})
            fb_count = editor.get("feedback_count", 0)
            is_confirm = st.session_state.get("delete_confirm_id") == editor["id"]

            with col:
                if is_confirm:
                    st.markdown(f"""
                    <div style="min-height:200px;background:{t['error']}11;border:1px solid {t['error']}44;
                        border-radius:12px;padding:24px 20px;margin-bottom:6px;display:flex;
                        flex-direction:column;align-items:center;justify-content:center;text-align:center;">
                        <div style="font-size:28px;margin-bottom:12px;">🗑️</div>
                        <div style="font-size:14px;color:{t['error']};font-weight:600;margin-bottom:6px;">
                            「{editor.get('name','')}」を削除しますか？</div>
                        <div style="font-size:12px;color:{t['text_secondary']};">この操作は元に戻せません</div>
                    </div>
                    """, unsafe_allow_html=True)
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("キャンセル", key=f"cancel_{editor['id']}", use_container_width=True):
                            st.session_state["delete_confirm_id"] = None
                            st.rerun()
                    with c2:
                        if st.button("削除する", key=f"confirm_{editor['id']}", use_container_width=True, type="primary"):
                            s = st.session_state.get("session")
                            if s:
                                delete_editor_remote(editor["id"], s.access_token)
                            delete_editor(editor["id"])
                            st.session_state["delete_confirm_id"] = None
                            st.rerun()
                else:
                    genre_icon = get_genre_icon(editor.get("icon", "その他"), 44)
                    style_labels = "・".join(s.get("label", "") for s in styles.values()) or "スタイル未登録"
                    st.markdown(f"""
                    <div style="min-height:200px;background:{t['bg_card']};border:0.5px solid {t['border']};
                        border-radius:12px;padding:18px 18px 14px;margin-bottom:6px;display:flex;
                        flex-direction:column;justify-content:space-between;">
                        <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
                            {genre_icon}
                            <div style="flex:1;min-width:0;">
                                <div style="font-size:16px;font-weight:600;color:{t['text_primary']};
                                    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                                    {editor.get('name','')}</div>
                                <div style="font-size:11px;color:{t['text_secondary']};margin-top:2px;
                                    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{style_labels}</div>
                            </div>
                        </div>
                        <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap;">
                            <span style="background:{t['accent']}22;color:{t['accent']};border-radius:20px;
                                padding:3px 10px;font-size:11px;">🗂 {len(styles)} スタイル</span>
                            <span style="background:{t['accent']}22;color:{t['accent']};border-radius:20px;
                                padding:3px 10px;font-size:11px;">💬 {fb_count} 件</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    c1, c2 = st.columns([5, 1])
                    with c1:
                        if st.button("選択して開く →", key=f"sel_{editor['id']}", use_container_width=True, type="primary"):
                            st.session_state["selected_editor_id"] = editor["id"]
                            st.session_state["current_theme"] = editor.get("theme", "ダーク")
                            st.session_state["page"] = "editor_detail"
                            st.rerun()
                    with c2:
                        if st.button("🗑️", key=f"del_{editor['id']}", use_container_width=True, help="削除"):
                            st.session_state["delete_confirm_id"] = editor["id"]
                            st.rerun()

        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)


# ============================================================
# 編集クローン詳細（タブ構成）
# ============================================================
def render_editor_detail():
    inject_css()
    render_sidebar()
    t = _get_theme(get_theme_name())
    eid = st.session_state.get("selected_editor_id")

    if not eid:
        st.error("編集クローンが選択されていません。")
        if st.button("← ホームに戻る"):
            st.session_state["page"] = "home_main"
            st.rerun()
        return

    editor = get_editor(eid)
    if not editor:
        st.error("編集クローンが見つかりません。")
        if st.button("← ホームに戻る"):
            st.session_state["page"] = "home_main"
            st.rerun()
        return

    col_back, col_h = st.columns([1, 5])
    with col_back:
        if st.button("← 戻る", use_container_width=True, key="back_to_home_btn"):
            st.session_state["page"] = "home_main"
            st.rerun()
    with col_h:
        st.markdown(f"""
        <div style="padding:4px 0 14px;">
            <h2 style="font-size:20px;font-weight:600;color:{t['text_primary']};margin:0;">
                {editor.get('name','')}</h2>
        </div>
        """, unsafe_allow_html=True)

    tabs = st.tabs(["🧠 スタイルを学習する", "🎬 動画を再現する", "🖼️ サムネイル", "🎨 自分の素材", "⚙️ 設定"])

    with tabs[0]:
        render_learn_tab(editor, eid)
    with tabs[1]:
        render_reproduce_tab(editor, eid)
    with tabs[2]:
        render_thumbnail_tab(editor, eid)
    with tabs[3]:
        render_assets_tab(editor, eid)
    with tabs[4]:
        render_editor_settings_tab(editor, eid)


# ── タブ1: スタイルを学習する ────────────────────────────────────────────
def render_learn_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    render_section_title("編集スタイルを学習する", theme_name)
    st.caption("ジャンルごとに複数のスタイルを持てます（例: 「ゲーム1」「ゲーム2」「雑談回」）")

    styles = editor.get("styles", {})
    for sid, s in styles.items():
        sd = s.get("style_data", {})
        with st.expander(f"📁 {s.get('label','無題')}（学習動画 {len(s.get('videos', []))}件）", expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.metric("テンポ", sd.get("tempo", "未分析"))
            c2.metric("テロップ色", sd.get("dominant_color", "未分析"))
            c3.metric("カット数", str(sd.get("total_cuts", "未分析")))

            new_label = st.text_input("名前を変更", value=s.get("label", ""), key=f"rename_{sid}") or s.get("label", "")
            cb1, cb2 = st.columns(2)
            with cb1:
                if st.button("名前を保存", key=f"save_name_{sid}", use_container_width=True):
                    rename_style(eid, sid, new_label)
                    st.rerun()
            with cb2:
                if st.button("🗑️ このスタイルを削除", key=f"del_style_{sid}", use_container_width=True):
                    delete_style(eid, sid)
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**＋ 新しいスタイルを追加**")
    new_style_name = st.text_input("スタイル名", placeholder="例: ゲーム実況（FPS）", key="new_style_name",
                                    label_visibility="collapsed")
    if st.button("スタイルを追加", key="add_style_btn"):
        if new_style_name:
            add_style(eid, new_style_name)
            st.rerun()
        else:
            st.warning("スタイル名を入力してください")

    if not styles:
        return

    st.markdown("<br>", unsafe_allow_html=True)
    render_section_title("動画から学習させる", theme_name)

    target_sid = st.selectbox(
        "学習させるスタイルを選択", list(styles.keys()),
        format_func=lambda k: styles[k].get("label", k), key="learn_target_style",
    )
    if not target_sid:
        return  # スタイルが1件も無い場合はここに来るが、直前の if not styles で弾いているので実際は通らない

    col_raw, col_edit = st.columns(2)
    with col_raw:
        st.caption("① 編集前の素材動画（任意・比較すると精度が上がります）")
        up_raw = st.file_uploader("素材動画", type=["mp4", "mov", "avi", "mkv", "webm"], key="learn_raw")
    with col_edit:
        st.caption("② 編集後の完成動画（必須）")
        up_edit = st.file_uploader("完成動画", type=["mp4", "mov", "avi", "mkv", "webm"], key="learn_edit")

    if up_edit and st.button("この動画からスタイルを学習する", type="primary", use_container_width=True, key="learn_btn"):
        with st.spinner("動画を解析中..."):
            style_data = analyze_style(up_edit.getvalue())
            brightness = analyze_brightness(up_edit.getvalue())
        if style_data:
            save_style_data(eid, target_sid, style_data, brightness)
            add_video_to_style(eid, target_sid, {
                "title": up_edit.name, "with_raw": up_raw.name if up_raw else None,
            })
            _sync_editor(eid)
            st.success("学習が完了しました！「動画を再現する」タブで使えます。")
            st.rerun()
        else:
            st.error("動画の解析に失敗しました。ファイル形式をご確認ください。")


# ── タブ2: 動画を再現する（★ 今回の核となる機能） ──────────────────────
def render_reproduce_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    t = _get_theme(theme_name)
    render_section_title("新しい動画にスタイルを再現する", theme_name)

    styles = editor.get("styles", {})
    if not styles:
        st.info("まだ学習したスタイルがありません。「スタイルを学習する」タブから始めてください。")
        return

    learned = {sid: s for sid, s in styles.items() if s.get("style_data")}
    if not learned:
        st.info("スタイルは登録されていますが、まだ動画から学習されていません。")
        return

    selected_sid = st.selectbox(
        "再現するスタイルを選択", list(learned.keys()),
        format_func=lambda k: learned[k].get("label", k), key="reproduce_style_sel",
    )
    if not selected_sid:
        return  # learned が空でない時点で通常は起こらないが、型を明示するためのガード
    style = learned[selected_sid]
    style_data = style.get("style_data", {})

    c1, c2, c3 = st.columns(3)
    c1.metric("テンポ", style_data.get("tempo", "不明"))
    c2.metric("テロップ色", style_data.get("dominant_color", "不明"))
    c3.metric("カット数", style_data.get("total_cuts", "不明"))

    st.markdown("<br>", unsafe_allow_html=True)
    up = st.file_uploader("新しい素材動画（未編集）をアップロード", type=["mp4", "mov", "avi", "mkv", "webm"],
                           key="reproduce_upload")

    assets = editor.get("assets", {})
    use_logo, bgm_choice = False, None
    with st.expander("自分の素材を使う（任意）", expanded=False):
        if assets.get("logo"):
            use_logo = st.checkbox(f"ロゴを焼き込む（{assets['logo']['filename']}）", key="use_logo")
        else:
            st.caption("ロゴは「自分の素材」タブから追加できます")

        bgm_list = assets.get("bgm", [])
        if bgm_list:
            bgm_labels = ["使わない"] + [b["label"] for b in bgm_list]
            bgm_sel = st.selectbox("BGM", bgm_labels, key="use_bgm")
            if bgm_sel != "使わない":
                bgm_choice = next(b for b in bgm_list if b["label"] == bgm_sel)
        else:
            st.caption("BGMは「自分の素材」タブから追加できます")

        font_asset = assets.get("font")
        use_font = st.checkbox(f"テロップに自分のフォントを使う（{font_asset['filename']}）", key="use_font") \
            if font_asset else False

    if not up:
        return

    if st.button("🎬 このスタイルで自動編集する", type="primary", use_container_width=True, key="run_reproduce"):
        video_bytes = up.getvalue()
        progress = st.progress(0, text="準備中...")

        progress.progress(10, text="音声を文字起こし中...")
        # Streamlit Community Cloud（無料枠・約1GBメモリ）でも安定して動くよう
        # 既定は軽量な "tiny" にしている。Render/VPS等に移行したら "base" に上げると精度が上がる。
        result = transcribe_video(video_bytes, language="ja", model_size="tiny")
        if not result:
            st.error("文字起こしに失敗しました。動画ファイルをご確認ください。")
            return
        segments = result["segments"]

        progress.progress(30, text="AIがあなたのスタイルで編集プランを作成中...")
        learner = FeedbackLearner(eid)
        reinforcement = learner.build_reinforcement_prompt()
        plan = generate_edit_plan(segments, style_data, style.get("label", ""), reinforcement)

        if plan and plan.get("segments"):
            sub_segments = plan["segments"]
            highlight_moments = plan.get("highlight_moments", [])
            ai_used = True
        else:
            # AIキー未設定・エラー時のフォールバック：
            # 外部AIを一切使わず、キーワード出現・音量ベースのルールだけで
            # 強調テロップ・ハイライト箇所を自動判定する（ai/heuristic.py）
            progress.progress(38, text="AI未使用のため、キーワード・音量でルールベース判定中...")
            detected_highlights = detect_highlight_moments(video_bytes, segments)
            heuristic_plan = build_heuristic_edit_plan(segments, detected_highlights)
            sub_segments = heuristic_plan["segments"]
            highlight_moments = heuristic_plan["highlight_moments"]
            ai_used = False

        progress.progress(45, text="学習したテンポで無音をカット中...")
        cut_video = auto_cut_by_segments(video_bytes, segments) or video_bytes

        progress.progress(60, text="学習したテロップスタイルで焼き込み中...")
        base_color = style_data.get("dominant_color", "white")
        emphasis_color = {"white": "yellow", "yellow": "red"}.get(base_color, "yellow")
        styled_segments = []
        for seg in sub_segments:
            is_high = seg.get("emphasis") == "high"
            styled_segments.append({
                **seg,
                "font_color": emphasis_color if is_high else base_color,
                "font_size": 56 if is_high else 40,
                "position": style_data.get("dominant_position", "下部"),
            })

        subtitle_style = {
            "font_color": base_color,
            "font_size": 40,
            "position": style_data.get("dominant_position", "下部"),
            "animation": "フェードイン",
            "stroke": True,
        }
        if use_font and assets.get("font"):
            subtitle_style["font_path"] = assets["font"]["path"]

        output, _ = generate_with_subtitles(cut_video, styled_segments, subtitle_style)
        output = output or cut_video

        progress.progress(78, text="学習した色調に補正中...")
        tone = style.get("brightness_data", {}).get("color_tone", "ニュートラル")
        grade_style = {"暖色系": "warm", "寒色系": "cool"}.get(tone)
        if grade_style:
            output = apply_color_grade(output, grade_style) or output

        if highlight_moments:
            progress.progress(86, text="盛り上がりシーンにズーム演出を追加中...")
            zoom_points = [{"start": h["start"], "end": h["end"]} for h in highlight_moments[:5]]
            output = apply_zoom_effect(output, zoom_points) or output

        if use_logo and assets.get("logo"):
            progress.progress(92, text="ロゴを焼き込み中...")
            output = overlay_logo(output, assets["logo"]["path"]) or output
        if bgm_choice:
            progress.progress(97, text="BGMをミックス中...")
            output = mix_bgm(output, bgm_choice["path"]) or output

        progress.progress(100, text="完成！")
        ai_note = "（Claude AIによる編集プラン適用済み）" if ai_used else "（ルールベース判定で自動編集・外部AI不使用）"
        st.success(f"✅「{style.get('label')}」スタイルで自動編集が完了しました {ai_note}")

        col_before, col_after = st.columns(2)
        with col_before:
            st.caption("Before（素材動画）")
            st.video(video_bytes)
        with col_after:
            st.caption("After（自動編集後）")
            st.video(output)

        base_name = up.name.rsplit(".", 1)[0]
        st.download_button("⬇️ 完成動画をダウンロード", data=output,
                            file_name=f"{base_name}_doppel.mp4", mime="video/mp4",
                            use_container_width=True)

        srt = generate_srt(sub_segments)
        st.download_button("📄 字幕ファイル (.srt) もダウンロード", data=srt.encode("utf-8"),
                            file_name=f"{base_name}.srt", mime="text/plain", use_container_width=True)

        add_video_to_style(eid, selected_sid, {"title": up.name, "type": "reproduced"})

        st.markdown("<br>", unsafe_allow_html=True)
        fb = st.radio("この自動編集の仕上がりはどうでしたか？", ["良い", "改善が必要"], key="reproduce_fb", horizontal=True)
        if st.button("フィードバックを送る", key="reproduce_fb_btn"):
            learner.save(
                query=up.name,
                response=(plan.get("notes", "") if plan else ""),
                rating=1 if fb == "良い" else -1,
                style_label=style.get("label", ""),
            )
            save_feedback(eid, {"type": "reproduce", "content": fb})
            s = st.session_state.get("session")
            u = st.session_state.get("user")
            if s and u:
                save_feedback_remote({"type": "reproduce", "content": fb, "editor_id": eid}, str(u.id), s.access_token)
            st.success("記録しました。次回の自動編集に活かされます。")


# ── タブ3: サムネイル ────────────────────────────────────────────────────
def render_thumbnail_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    t = _get_theme(theme_name)
    render_section_title("サムネイルを作る", theme_name)

    styles = editor.get("styles", {})
    style_label = ""
    style_data = {}
    if styles:
        sid = st.selectbox("参考にするスタイル（任意）", ["指定なし"] + list(styles.keys()),
                            format_func=lambda k: "指定なし" if k == "指定なし" else styles[k].get("label", k),
                            key="thumb_style_sel")
        if sid != "指定なし":
            style_label = styles[sid].get("label", "")
            style_data = styles[sid].get("style_data", {})

    txt = st.text_area("動画の内容を入力", placeholder="例：今回はゲームの隠しステージの攻略を紹介します...",
                        key="th_input", height=100)

    if st.button("サムネイル案を3パターン作成", use_container_width=True, type="primary", key="do_thumb"):
        if not txt:
            st.warning("動画の内容を入力してください")
        else:
            learner = FeedbackLearner(eid)
            stream = get_thumbnail_suggestion(
                txt, style_data, style_label, learner.build_reinforcement_prompt(), stream=True,
            )
            suggestion = run_ai_with_progress(stream, label="サムネイル案を生成中")
            st.session_state["last_thumbnail"] = suggestion

    if st.session_state.get("last_thumbnail"):
        st.markdown(f"""
        <div style="background:{t['bg_card']};border:0.5px solid {t['border']};border-radius:10px;
            padding:16px;margin-top:8px;">
            <div style="font-size:13px;font-weight:600;color:{t['accent']};margin-bottom:8px;">サムネイル提案</div>
            <div style="font-size:13px;color:{t['text_primary']};line-height:1.7;white-space:pre-line;">
                {st.session_state['last_thumbnail']}</div>
        </div>
        """, unsafe_allow_html=True)


# ── タブ4: 自分の素材 ────────────────────────────────────────────────────
def render_assets_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    render_section_title("自分だけの素材（ロゴ・フォント・BGM・効果音）", theme_name)
    st.caption("ここでアップロードした素材は「動画を再現する」タブで自動編集の仕上げに使えます")
    assets = load_assets(eid)

    st.markdown("**🖼️ ロゴ**")
    if assets.get("logo"):
        c1, c2 = st.columns([4, 1])
        c1.write(f"現在: {assets['logo']['filename']}")
        if c2.button("削除", key="del_logo"):
            delete_asset(eid, "logo")
            st.rerun()
    up_logo = st.file_uploader("ロゴ画像（PNG推奨・透過対応）", type=["png", "jpg", "jpeg"], key="up_logo")
    if up_logo and st.button("ロゴを保存", key="save_logo"):
        save_asset(eid, "logo", up_logo.getvalue(), up_logo.name)
        st.rerun()

    st.markdown("<br>**🔤 フォント**", unsafe_allow_html=True)
    if assets.get("font"):
        c1, c2 = st.columns([4, 1])
        c1.write(f"現在: {assets['font']['filename']}")
        if c2.button("削除", key="del_font"):
            delete_asset(eid, "font")
            st.rerun()
    up_font = st.file_uploader("フォントファイル（.ttf / .otf）", type=["ttf", "otf"], key="up_font")
    if up_font and st.button("フォントを保存", key="save_font"):
        save_asset(eid, "font", up_font.getvalue(), up_font.name)
        st.rerun()

    st.markdown("<br>**🎵 BGM**", unsafe_allow_html=True)
    for b in assets.get("bgm", []):
        c1, c2 = st.columns([4, 1])
        c1.write(f"🎵 {b['label']}")
        if c2.button("削除", key=f"del_bgm_{b['id']}"):
            delete_asset(eid, "bgm", b["id"])
            st.rerun()
    up_bgm = st.file_uploader("BGMファイル（mp3 / wav）", type=["mp3", "wav", "m4a"], key="up_bgm")
    bgm_label = st.text_input("BGM名（任意）", key="bgm_label_input")
    if up_bgm and st.button("BGMを追加", key="save_bgm"):
        save_asset(eid, "bgm", up_bgm.getvalue(), up_bgm.name, bgm_label or "")
        st.rerun()

    st.markdown("<br>**🔊 効果音（SE）**", unsafe_allow_html=True)
    for se in assets.get("se", []):
        c1, c2 = st.columns([4, 1])
        c1.write(f"🔊 {se['label']}")
        if c2.button("削除", key=f"del_se_{se['id']}"):
            delete_asset(eid, "se", se["id"])
            st.rerun()
    up_se = st.file_uploader("効果音ファイル（mp3 / wav）", type=["mp3", "wav", "m4a"], key="up_se")
    se_label = st.text_input("SE名（任意）", key="se_label_input")
    if up_se and st.button("SEを追加", key="save_se"):
        save_asset(eid, "se", up_se.getvalue(), up_se.name, se_label or "")
        st.rerun()


# ── タブ5: 設定 ──────────────────────────────────────────────────────────
def render_editor_settings_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    t = _get_theme(theme_name)
    render_section_title("編集クローンの設定", theme_name)

    new_name = st.text_input("名前", value=editor.get("name", ""), key="settings_name")
    new_theme = st.selectbox("カラーテーマ", list(THEMES.keys()),
                              index=list(THEMES.keys()).index(editor.get("theme", "ダーク")))
    if st.button("保存する", use_container_width=True, type="primary", key="save_settings"):
        update_editor(eid, {"name": new_name, "theme": new_theme})
        st.session_state["current_theme"] = new_theme
        _sync_editor(eid)
        st.success("保存しました！")
        st.rerun()

    st.markdown(f"""
    <div style="background:{t['bg_card']};border:0.5px solid {t['border']};border-radius:10px;
        padding:18px;margin:14px 0;font-size:12px;color:{t['text_secondary']};line-height:2.2;">
        クローンID: {editor['id']}<br>
        作成日: {editor['created_at'][:10]}<br>
        スタイル数: {len(editor.get('styles', {}))}<br>
        フィードバック数: {editor.get('feedback_count', 0)}
    </div>
    """, unsafe_allow_html=True)

    if st.checkbox("削除することを確認しました", key="del_confirm"):
        if st.button("この編集クローンを削除する", use_container_width=True, type="primary", key="do_del"):
            s = st.session_state.get("session")
            if s:
                delete_editor_remote(eid, s.access_token)
            delete_editor(eid)
            st.session_state["selected_editor_id"] = None
            st.session_state["page"] = "home_main"
            st.rerun()


# ============================================================
# 設定（全体）
# ============================================================
def render_settings_home():
    inject_css()
    render_sidebar()
    render_section_title("設定", get_theme_name())
    st.caption("編集クローンごとの設定は、各クローンの「⚙️ 設定」タブから変更できます。")

    if st.button("← 戻る", use_container_width=True, key="back_set"):
        st.session_state["page"] = "home_main" if load_editors() else "home_initial"
        st.rerun()


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    main()
else:
    main()