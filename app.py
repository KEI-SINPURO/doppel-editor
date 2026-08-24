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
    - 編集前(raw)素材と編集後(edited)動画を比較して「カットの癖」を学習し、
      再現時のカット判断（学習した基準で残す／削る）に反映
    - トランジション／ハイライトのスローモーション／顔検出ベースの自動リフレーム
    - カットで詰まった分のタイムラインのズレを補正するテロップ・ハイライトの時刻変換
    - 複数の素材動画を結合してから再現編集できる（イントロ＋本編＋アウトロ 等）
    - ナレーション（ボイスオーバー）音声の追加とダッキング
    - ハイライトへの効果音（SE）自動配置（組み込みプリセット／自分の素材）
    - BGMプリセットの仕組み（assets/bgm_presets/ 参照）
    - 【NEW】本番レンダリング前に、AIの編集プラン（テロップ文言・残す/削る・強調）を
      確認・修正できるプレビュー画面（pipeline.py に処理を分離）
    - 【NEW】音量正規化・簡易ノイズゲート・プラットフォーム別の書き出し設定プリセット
    - 【NEW】複数の動画をまとめて自動編集するバッチ処理タブ（ZIP一括ダウンロード）

  処理の実体（文字起こし→編集プラン作成→動画書き出し）は pipeline.py に切り出してあり、
  「動画を再現する」タブとバッチ処理タブの両方から共通で使っている。
"""

import streamlit as st
import sys
import os
import tempfile
import zipfile
import io
from typing import Dict, Optional, Tuple

st.set_page_config(
    page_title="Doppel Editor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="locked",
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

import pandas as pd

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
from ai.model import is_ai_ready, get_thumbnail_suggestion
from ai.learning import FeedbackLearner

from features.transcribe import transcribe_video, get_plain_text, estimate_time
from features.analyze import analyze_style, analyze_brightness, analyze_editing_patterns
from features.generate import concatenate_source_clips
from features.se_presets import list_se_preset_names, get_se_preset_bytes
from features.media_library import list_bgm_presets
from features.export_presets import list_export_preset_names, get_export_preset

from pipeline import build_edit_plan, render_final_video, derive_highlights_from_plan

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
# 演出オプションUI・レンダリング設定の組み立て（再現タブ・バッチタブ共通）
# ============================================================
def render_options_ui(assets: dict, key_prefix: str):
    """
    「自分の素材を使う」「演出オプション」「追加の音素材」「音質仕上げ・書き出し設定」の
    UIをまとめて描画し、pipeline.render_final_video() にそのまま渡せる render_options を返す。
    「動画を再現する」タブとバッチ処理タブの両方から呼べるよう、key_prefixでウィジェットキーを分離する。

    Returns:
        (render_options: dict, labels: dict)
        render_options の "se_source" と "narration_file" は、まだファイル化されていない
        （SEプリセット名 or アップロードされたファイルオブジェクトのまま）。
        実際に書き出す直前に _materialize_render_options() で一時ファイルに変換する。
    """
    bgm_presets = list_bgm_presets()
    # ★ {"使わない": None} だけで初期化すると、Pyrightはこの辞書の値の型を
    #   "None" 単体だと推論してしまい、後続の str 代入がエラーになる。
    #   Optional[str] と明示することで、None/str どちらの代入も正しく型チェックできるようにする。
    bgm_label_to_path: Dict[str, Optional[str]] = {"使わない": None}
    for p in bgm_presets:
        bgm_label_to_path[f"🎼 プリセット: {p['label']}"] = p["path"]
    for b in assets.get("bgm", []):
        bgm_label_to_path[f"📁 自分の素材: {b['label']}"] = b["path"]

    # 同様に、値の型を Optional[Tuple[str, str]] と明示しておく
    se_label_to_source: Dict[str, Optional[Tuple[str, str]]] = {"なし": None}
    for name in list_se_preset_names():
        se_label_to_source[f"🎛️ プリセット: {name}"] = ("preset", name)
    for se in assets.get("se", []):
        se_label_to_source[f"📁 自分の素材: {se['label']}"] = ("asset", se["path"])

    transition_options = {
        "カット（トランジションなし）": "cut",
        "クロスフェード（ディゾルブ）": "crossfade",
        "暗転（黒に落としてつなぐ）": "fade_black",
        "学習したリズムにおまかせ": "auto",
    }
    highlight_fx_options = {
        "ズーム": "zoom", "なし": "none",
        "スローモーション": "slowmo", "ズーム＋スローモーション": "zoom_slowmo",
    }
    reframe_options = {
        "変更しない（元の比率のまま）": None,
        "縦型 9:16（Shorts / Reels / TikTok）": "9:16",
        "スクエア 1:1（Instagramフィード）": "1:1",
        "縦長 4:5（Instagramフィード）": "4:5",
    }
    export_preset_names = list_export_preset_names()

    use_logo = False
    use_font = False
    with st.expander("自分の素材を使う（任意）", expanded=False):
        if assets.get("logo"):
            use_logo = st.checkbox(f"ロゴを焼き込む（{assets['logo']['filename']}）", key=f"{key_prefix}_use_logo")
        else:
            st.caption("ロゴは「自分の素材」タブから追加できます")
        font_asset = assets.get("font")
        if font_asset:
            use_font = st.checkbox(
                f"テロップに自分のフォントを使う（{font_asset['filename']}）", key=f"{key_prefix}_use_font",
            )

    with st.expander("演出オプション（任意）", expanded=False):
        # ★ st.selectbox() は型上 str | None を返す（Pylanceの型スタブ上、選択肢が空の場合等を
        #   考慮しているため）。index=0 を渡しているので実際にNoneになることは無いが、
        #   後続で辞書のキーとして使うため、既存コードの慣習（icon_choice等）に合わせて
        #   "or 先頭の選択肢" で確実に str 型に倒しておく。
        transition_keys = list(transition_options.keys())
        transition_choice_label = st.selectbox(
            "カットのつなぎ方（トランジション）", transition_keys,
            index=0, key=f"{key_prefix}_transition",
        ) or transition_keys[0]
        transition_choice = transition_options[transition_choice_label]

        highlight_fx_keys = list(highlight_fx_options.keys())
        highlight_fx_choice_label = st.selectbox(
            "ハイライト演出", highlight_fx_keys, index=0, key=f"{key_prefix}_highlight_fx",
        ) or highlight_fx_keys[0]
        highlight_fx = highlight_fx_options[highlight_fx_choice_label]
        if highlight_fx in ("slowmo", "zoom_slowmo"):
            st.caption("※ スローモーションは音声のピッチも下がります（音程補正は未対応）")

        reframe_keys = list(reframe_options.keys())
        reframe_choice_label = st.selectbox(
            "画面比率（自動リフレーム）", reframe_keys, index=0, key=f"{key_prefix}_reframe",
        ) or reframe_keys[0]
        reframe_ratio = reframe_options[reframe_choice_label]
        if reframe_ratio:
            st.caption("※ 顔検出でメインの被写体を追従してクロップします（うまく検出できない場合は中央クロップ）")

    with st.expander("追加の音素材（任意）", expanded=False):
        st.caption("🎙️ ナレーション（ボイスオーバー） ― 動画冒頭から重ね、その間だけ元の音声を下げます")
        up_narration = st.file_uploader(
            "ナレーション音声", type=["mp3", "wav", "m4a"], key=f"{key_prefix}_narration",
        )
        narration_duck_db = st.slider(
            "ナレーション再生中、元の音量をどれだけ下げるか（dB）", 0, 30, 15, key=f"{key_prefix}_duck",
        )

        st.caption("🔊 ハイライト効果音 ― 盛り上がりシーンに自動で配置します")
        if len(se_label_to_source) == 1:
            st.caption("（自分のSEを追加するには「自分の素材」タブから登録してください）")
        se_keys = list(se_label_to_source.keys())
        se_choice_label = st.selectbox("効果音", se_keys, index=0, key=f"{key_prefix}_se") or se_keys[0]
        se_source = se_label_to_source[se_choice_label]

        st.caption("🎼 BGM ― プリセット、または自分の素材から選べます")
        if len(bgm_label_to_path) == 1:
            st.caption("プリセットBGMは未登録です（assets/bgm_presets/ 参照）。「自分の素材」タブからも追加できます。")
        bgm_keys = list(bgm_label_to_path.keys())
        bgm_choice_label = st.selectbox("BGM", bgm_keys, index=0, key=f"{key_prefix}_bgm") or bgm_keys[0]
        bgm_path_choice = bgm_label_to_path[bgm_choice_label]

    with st.expander("音質仕上げ・書き出し設定（任意）", expanded=False):
        normalize_audio = st.checkbox(
            "音量を正規化する（動画全体の音量を適正なレベルに合わせる）", key=f"{key_prefix}_normalize",
        )
        noise_gate = st.checkbox(
            "簡易ノイズゲートをかける（無音区間の残留ノイズを抑える）", key=f"{key_prefix}_noisegate",
        )
        st.caption("※ どちらも簡易的な処理です。環境音そのものを消すような本格的なノイズ除去はできません。")
        export_preset_label = st.selectbox(
            "書き出し設定", export_preset_names, index=0, key=f"{key_prefix}_export",
        ) or export_preset_names[0]

    render_options = {
        "transition": transition_choice,
        "highlight_fx": highlight_fx,
        "reframe_ratio": reframe_ratio,
        "use_logo": use_logo,
        "logo_path": (assets.get("logo") or {}).get("path") if use_logo else None,
        "use_font": use_font,
        "font_path": (assets.get("font") or {}).get("path") if use_font else None,
        "bgm_path": bgm_path_choice,
        "se_source": se_source,          # ("preset", name) | ("asset", path) | None
        "narration_file": up_narration,  # UploadedFile | None
        "narration_duck_db": narration_duck_db,
        "normalize_audio": normalize_audio,
        "noise_gate": noise_gate,
        "export_preset": get_export_preset(export_preset_label),
    }
    labels = {
        "transition": transition_choice_label if transition_choice != "cut" else None,
        "highlight_fx": highlight_fx_choice_label if highlight_fx != "none" else None,
        "reframe": reframe_choice_label if reframe_ratio else None,
        "se": se_choice_label if se_source else None,
        "bgm": bgm_choice_label if bgm_path_choice else None,
        "narration": "ナレーション追加" if up_narration else None,
        "normalize_audio": "音量正規化" if normalize_audio else None,
        "noise_gate": "ノイズゲート" if noise_gate else None,
        "export_preset": export_preset_label,
    }
    return render_options, labels


def _make_progress_cb(bar):
    """
    st.progress() が返すバー(DeltaGenerator)を、pipeline.render_final_video() が
    期待する Callable[[int, str], None] 形式のコールバックに変換する。

    ループ内でそのまま `lambda p, txt: bar.progress(...)` を作ると、
    ①bar.progress()の戻り値(DeltaGenerator)が型不一致になる、
    ②forループ変数の遅延束縛でバーの参照がズレる、という2つの問題があるため、
    ファクトリ関数として明示的に切り出している。
    """
    def _cb(p: int, txt: str) -> None:
        bar.progress(p, text=txt)
    return _cb


def _materialize_render_options(render_options: dict):
    """
    render_options_ui() が返した dict のうち、まだファイル化されていないもの
    （SEプリセット名・アップロードされたナレーションファイル）を一時ファイルに書き出し、
    pipeline.render_final_video() にそのまま渡せる形（se_path/narration_path）に変換する。

    Returns:
        (materialized_options: dict, temp_paths_to_cleanup: list[str])
        呼び出し側は render_final_video() の呼び出し後、必ず temp_paths_to_cleanup を削除すること。
    """
    materialized = dict(render_options)
    temp_paths = []

    se_source = render_options.get("se_source")
    se_path = None
    if se_source:
        kind, value = se_source
        if kind == "preset":
            se_bytes = get_se_preset_bytes(value)
            if se_bytes:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as sf:
                    sf.write(se_bytes)
                    se_path = sf.name
                temp_paths.append(se_path)
        else:
            se_path = value
    materialized["se_path"] = se_path
    materialized.pop("se_source", None)

    narration_file = render_options.get("narration_file")
    narration_path = None
    if narration_file:
        suffix = os.path.splitext(narration_file.name)[1] or ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as nf:
            nf.write(narration_file.getvalue())
            narration_path = nf.name
        temp_paths.append(narration_path)
    materialized["narration_path"] = narration_path
    materialized.pop("narration_file", None)

    return materialized, temp_paths


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
            st.code(g["url"])  # ← この1行を追加（デバッグ用）
            st.link_button("🔵 Googleでログイン", g["url"], use_container_width=True)
        else:
            st.caption(f"Googleログインは現在利用できません: {g.get('error')}")

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

    tabs = st.tabs([
        "🧠 スタイルを学習する", "🎬 動画を再現する", "📦 バッチ処理",
        "🖼️ サムネイル", "🎨 自分の素材", "⚙️ 設定",
    ])

    with tabs[0]:
        render_learn_tab(editor, eid)
    with tabs[1]:
        render_reproduce_tab(editor, eid)
    with tabs[2]:
        render_batch_tab(editor, eid)
    with tabs[3]:
        render_thumbnail_tab(editor, eid)
    with tabs[4]:
        render_assets_tab(editor, eid)
    with tabs[5]:
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

            rhythm = sd.get("rhythm")
            if rhythm and rhythm.get("rhythm_pattern") and rhythm.get("rhythm_pattern") != "不明":
                st.caption(f"⏱️ リズム傾向：{rhythm.get('rhythm_pattern')}")

            patterns = sd.get("editing_patterns")
            if patterns:
                st.caption(
                    f"🎯 学習した編集の癖：素材の約{int(patterns.get('keep_ratio', 1) * 100)}%を残す／"
                    f"フィラー語除去率 約{int(patterns.get('filler_removal_rate', 0) * 100)}%／"
                    f"カットは文の区切りで行われる傾向 約{int(patterns.get('boundary_tendency', 0) * 100)}%"
                )
            else:
                st.caption("💡 「編集前の素材動画」も一緒にアップロードすると、カットの癖まで学習できます")

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
        st.caption("① 編集前の素材動画（任意・比較すると「カットの癖」まで学習できます）")
        up_raw = st.file_uploader("素材動画", type=["mp4", "mov", "avi", "mkv", "webm"], key="learn_raw")
    with col_edit:
        st.caption("② 編集後の完成動画（必須）")
        up_edit = st.file_uploader("完成動画", type=["mp4", "mov", "avi", "mkv", "webm"], key="learn_edit")

    if up_edit and st.button("この動画からスタイルを学習する", type="primary", use_container_width=True, key="learn_btn"):
        with st.spinner("動画を解析中..."):
            style_data = analyze_style(up_edit.getvalue())
            brightness = analyze_brightness(up_edit.getvalue())

            editing_patterns = None
            if up_raw and style_data:
                st.caption("編集前素材と比較して「カットの癖」も学習しています…（少し時間がかかります）")
                # 同じ動画をもう一度アップロードしなくて済むよう、raw/edited 双方をここで
                # 一度だけ文字起こしし、「どこが残されて、どこが削られたか」を比較する。
                raw_result = transcribe_video(up_raw.getvalue(), language="ja", model_size="tiny")
                edited_result = transcribe_video(up_edit.getvalue(), language="ja", model_size="tiny")
                if raw_result and edited_result:
                    editing_patterns = analyze_editing_patterns(
                        raw_result["segments"], edited_result["segments"],
                    )
                    if editing_patterns:
                        style_data["editing_patterns"] = editing_patterns

        if style_data:
            save_style_data(eid, target_sid, style_data, brightness)
            add_video_to_style(eid, target_sid, {
                "title": up_edit.name, "with_raw": up_raw.name if up_raw else None,
            })
            _sync_editor(eid)
            msg = "学習が完了しました！「動画を再現する」タブで使えます。"
            if editing_patterns:
                msg += (
                    f"（素材の約{int(editing_patterns.get('keep_ratio', 1) * 100)}%を残す傾向、"
                    f"フィラー語除去率 約{int(editing_patterns.get('filler_removal_rate', 0) * 100)}% を学習しました）"
                )
            st.success(msg)
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
        return
    style = learned[selected_sid]
    style_data = style.get("style_data", {})

    c1, c2, c3 = st.columns(3)
    c1.metric("テンポ", style_data.get("tempo", "不明"))
    c2.metric("テロップ色", style_data.get("dominant_color", "不明"))
    c3.metric("カット数", style_data.get("total_cuts", "不明"))

    st.markdown("<br>", unsafe_allow_html=True)
    ups = st.file_uploader(
        "新しい素材動画（未編集）をアップロード（複数選択で1本に結合できます）",
        type=["mp4", "mov", "avi", "mkv", "webm"], key="reproduce_upload", accept_multiple_files=True,
    )
    if not ups:
        return

    if len(ups) > 1:
        st.caption(f"📎 {len(ups)}個の素材が選択されました。つなげる順番を指定してください。")
        order_map = {}
        order_cols = st.columns(min(len(ups), 4))
        for idx, f in enumerate(ups):
            with order_cols[idx % len(order_cols)]:
                order_map[idx] = st.number_input(
                    f"順番：{f.name[:18]}", min_value=1, max_value=len(ups), value=idx + 1,
                    key=f"order_{idx}_{f.name}",
                )
        ordered_files = [f for _, f in sorted(zip((order_map[i] for i in range(len(ups))), ups), key=lambda p: p[0])]
        combined_label = f"{ordered_files[0].name}ほか{len(ordered_files)}本を結合"
    else:
        ordered_files = ups
        combined_label = ups[0].name

    assets = editor.get("assets", {})
    render_options, labels = render_options_ui(assets, key_prefix="rep")

    # ── ① 編集プランの作成 ──────────────────────────────
    render_section_title("編集プランを作成する", theme_name)
    plan_key = f"edit_plan__{eid}__{selected_sid}"
    video_key = f"edit_plan_video__{eid}__{selected_sid}"
    label_key = f"edit_plan_label__{eid}__{selected_sid}"

    col_plan, col_reset = st.columns([3, 1])
    with col_plan:
        make_plan_clicked = st.button(
            "🧠 編集プランを作成する（文字起こし・AI判断）", type="primary",
            use_container_width=True, key="make_plan_btn",
        )
    with col_reset:
        if st.session_state.get(plan_key) is not None:
            if st.button("↺ 作り直す", use_container_width=True, key="reset_plan_btn"):
                st.session_state[plan_key] = None
                st.session_state[video_key] = None
                st.rerun()

    if make_plan_clicked:
        with st.spinner("素材を準備・文字起こし中..."):
            if len(ordered_files) > 1:
                video_bytes = concatenate_source_clips([f.getvalue() for f in ordered_files])
            else:
                video_bytes = ordered_files[0].getvalue()
            if not video_bytes:
                st.error("素材の結合に失敗しました。ファイル形式をご確認ください。")
                return
            learner = FeedbackLearner(eid)
            reinforcement = learner.build_reinforcement_prompt()
            plan = build_edit_plan(video_bytes, style_data, style.get("label", ""), reinforcement)
        if not plan:
            st.error("文字起こしに失敗しました。動画ファイルをご確認ください。")
            return
        st.session_state[plan_key] = plan
        st.session_state[video_key] = video_bytes
        st.session_state[label_key] = combined_label
        st.rerun()

    plan = st.session_state.get(plan_key)
    video_bytes = st.session_state.get(video_key)
    if not plan or video_bytes is None:
        st.info("👆 「編集プランを作成する」を押すと、AIが判断したテロップ内容・残す/削るを"
                "ここで確認・修正してから最終レンダリングに進めます。")
        return

    ai_note = "Claude AIによる編集プラン" if plan["ai_used"] else "ルールベース判定（AI未使用）"
    st.success(f"編集プランができました（{ai_note}）。内容を確認・修正してから最終レンダリングしてください。")
    if plan.get("notes"):
        st.caption(f"📝 {plan['notes']}")

    # ── ② プランの確認・修正 ────────────────────────────
    render_section_title("編集プランを確認・修正する", theme_name)
    plan_segments = plan["plan_segments"]
    df = pd.DataFrame([
        {
            "開始(秒)": round(s.get("start", 0), 1),
            "終了(秒)": round(s.get("end", 0), 1),
            "テロップ文言": s.get("text", ""),
            "残す": bool(s.get("keep", True)),
            "強調": s.get("emphasis") == "high",
        }
        for s in plan_segments
    ])
    edited_df = st.data_editor(
        df, key="plan_editor", use_container_width=True, num_rows="fixed", hide_index=True,
        column_config={
            "開始(秒)": st.column_config.NumberColumn(disabled=True),
            "終了(秒)": st.column_config.NumberColumn(disabled=True),
            "テロップ文言": st.column_config.TextColumn(width="large"),
            "残す": st.column_config.CheckboxColumn(help="オフにするとその発言はカットされます"),
            "強調": st.column_config.CheckboxColumn(help="オンにすると強調テロップ＋ハイライト演出の対象になります"),
        },
    )
    st.caption(f"合計 {len(plan_segments)} 発言 ／ 残す: {int(edited_df['残す'].sum())} ／ "
               f"強調: {int(edited_df['強調'].sum())}")

    # ── ③ 最終レンダリング ──────────────────────────────
    if st.button("✅ この内容で最終レンダリングする", type="primary", use_container_width=True, key="render_final_btn"):
        updated_plan_segments = []
        for i, row in edited_df.iterrows():
            original = plan_segments[i]
            updated_plan_segments.append({
                **original,
                "text": row["テロップ文言"],
                "keep": bool(row["残す"]),
                "emphasis": "high" if bool(row["強調"]) else "normal",
            })
        working_plan = {
            **plan,
            "plan_segments": updated_plan_segments,
            "highlight_moments": derive_highlights_from_plan(updated_plan_segments),
        }

        materialized_options, temp_paths = _materialize_render_options(render_options)
        progress = st.progress(0, text="準備中...")
        try:
            result = render_final_video(
                video_bytes, working_plan, style, materialized_options,
                progress_cb=_make_progress_cb(progress),
            )
        finally:
            for p in temp_paths:
                if p and os.path.exists(p):
                    os.unlink(p)

        output = result.get("output")
        if not output:
            st.error("最終レンダリングに失敗しました。")
            return

        ai_note2 = "（Claude AIによる編集プラン適用済み）" if result["ai_used"] else "（ルールベース判定で自動編集・外部AI不使用）"
        st.success(f"✅「{style.get('label')}」スタイルで自動編集が完了しました {ai_note2}")

        applied_notes = [v for v in labels.values() if v]
        if len(ordered_files) > 1:
            applied_notes.insert(0, f"素材結合: {len(ordered_files)}本")
        if applied_notes:
            st.caption("🎛️ " + " ／ ".join(applied_notes))

        col_before, col_after = st.columns(2)
        with col_before:
            st.caption("Before（素材動画）")
            st.video(video_bytes)
        with col_after:
            st.caption("After（自動編集後）")
            st.video(output)

        combined_label_final = st.session_state.get(label_key, "output")
        base_name = combined_label_final.rsplit(".", 1)[0] if "." in combined_label_final else combined_label_final
        st.download_button("⬇️ 完成動画をダウンロード", data=output,
                            file_name=f"{base_name}_doppel.mp4", mime="video/mp4", use_container_width=True)
        st.download_button("📄 字幕ファイル (.srt) もダウンロード", data=result["srt"].encode("utf-8"),
                            file_name=f"{base_name}.srt", mime="text/plain", use_container_width=True)

        add_video_to_style(eid, selected_sid, {"title": combined_label_final, "type": "reproduced"})

        st.markdown("<br>", unsafe_allow_html=True)
        fb = st.radio("この自動編集の仕上がりはどうでしたか？", ["良い", "改善が必要"], key="reproduce_fb", horizontal=True)
        if st.button("フィードバックを送る", key="reproduce_fb_btn"):
            learner = FeedbackLearner(eid)
            learner.save(
                query=combined_label_final,
                response=plan.get("notes", ""),
                rating=1 if fb == "良い" else -1,
                style_label=style.get("label", ""),
            )
            save_feedback(eid, {"type": "reproduce", "content": fb})
            s = st.session_state.get("session")
            u = st.session_state.get("user")
            if s and u:
                save_feedback_remote({"type": "reproduce", "content": fb, "editor_id": eid}, str(u.id), s.access_token)
            st.success("記録しました。次回の自動編集に活かされます。")


# ── タブ3: バッチ処理（複数動画をまとめて自動編集） ─────────────────────
def render_batch_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    render_section_title("複数の動画をまとめて自動編集する", theme_name)
    st.caption("同じスタイル・同じ設定で、複数の動画を順番に自動編集します。"
               "1本ずつの確認・修正はできないため、まずは「動画を再現する」タブで設定を試してから使うのがおすすめです。")

    styles = editor.get("styles", {})
    learned = {sid: s for sid, s in styles.items() if s.get("style_data")}
    if not learned:
        st.info("まだ学習済みのスタイルがありません。")
        return

    selected_sid = st.selectbox(
        "使用するスタイル", list(learned.keys()),
        format_func=lambda k: learned[k].get("label", k), key="batch_style_sel",
    )
    if not selected_sid:
        return
    style = learned[selected_sid]
    style_data = style.get("style_data", {})

    batch_files = st.file_uploader(
        "処理したい動画をまとめて選択（各ファイルが個別に自動編集されます）",
        type=["mp4", "mov", "avi", "mkv", "webm"], accept_multiple_files=True, key="batch_upload",
    )
    if not batch_files:
        return
    st.caption(f"📦 {len(batch_files)}本の動画が選択されています。")

    assets = editor.get("assets", {})
    render_options, labels = render_options_ui(assets, key_prefix="batch")

    st.warning("⏱️ 動画1本あたり数分かかる処理を、選んだ本数ぶん繰り返します。処理中はページを閉じないでください。")

    if st.button(f"📦 {len(batch_files)}本をまとめて自動編集する", type="primary",
                 use_container_width=True, key="run_batch_btn"):
        learner = FeedbackLearner(eid)
        reinforcement = learner.build_reinforcement_prompt()
        results = []
        overall = st.progress(0, text="バッチ処理を開始します...")

        for i, f in enumerate(batch_files):
            st.markdown(f"**{i + 1}/{len(batch_files)}：{f.name}**")
            sub_progress = st.progress(0, text="準備中...")
            video_bytes = f.getvalue()

            plan = build_edit_plan(video_bytes, style_data, style.get("label", ""), reinforcement)
            if not plan:
                st.warning(f"⚠️ {f.name}: 文字起こしに失敗したためスキップしました")
                overall.progress(int((i + 1) / len(batch_files) * 100), text=f"{i + 1}/{len(batch_files)} 処理済み")
                continue

            materialized_options, temp_paths = _materialize_render_options(render_options)
            try:
                result = render_final_video(
                    video_bytes, plan, style, materialized_options,
                    progress_cb=_make_progress_cb(sub_progress),
                )
            finally:
                for p in temp_paths:
                    if p and os.path.exists(p):
                        os.unlink(p)

            if result.get("output"):
                results.append({"name": f.name, "output": result["output"], "srt": result["srt"]})
            else:
                st.warning(f"⚠️ {f.name}: 書き出しに失敗しました")

            overall.progress(int((i + 1) / len(batch_files) * 100), text=f"{i + 1}/{len(batch_files)} 処理済み")

        if results:
            st.success(f"✅ {len(results)}/{len(batch_files)}本の自動編集が完了しました")
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for r in results:
                    base = r["name"].rsplit(".", 1)[0] if "." in r["name"] else r["name"]
                    zf.writestr(f"{base}_doppel.mp4", r["output"])
                    zf.writestr(f"{base}.srt", r["srt"])
            st.download_button("⬇️ すべてまとめてダウンロード（ZIP）", data=zip_buf.getvalue(),
                                file_name="doppel_batch_output.zip", mime="application/zip",
                                use_container_width=True)
            for r in results:
                with st.expander(f"🎬 {r['name']}", expanded=False):
                    st.video(r["output"])
        else:
            st.error("すべての動画で処理に失敗しました。")


# ── タブ4: サムネイル ────────────────────────────────────────────────────
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


# ── タブ5: 自分の素材 ────────────────────────────────────────────────────
def render_assets_tab(editor: dict, eid: str):
    theme_name = get_theme_name()
    render_section_title("自分だけの素材（ロゴ・フォント・BGM・効果音）", theme_name)
    st.caption("ここでアップロードした素材は「動画を再現する」タブで自動編集の仕上げに使えます。"
               "BGM・効果音は、アプリ内蔵のプリセットと合わせて選べます。")
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

    st.markdown("<br>**🎵 BGM**（アプリ内蔵のプリセットBGMは「動画を再現する」タブで別途選べます）", unsafe_allow_html=True)
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

    st.markdown("<br>**🔊 効果音（SE）**（合成生成のプリセットSEは「動画を再現する」タブで別途選べます）", unsafe_allow_html=True)
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


# ── タブ6: 設定 ──────────────────────────────────────────────────────────
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