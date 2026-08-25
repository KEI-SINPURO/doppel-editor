import time
import streamlit as st
from ui.theme import get_theme

# ========== SVGアイコンライブラリ ==========
def svg(name: str, size: int = 20, color: str = "#9990e8") -> str:
    s = str(size)
    icons = {
        "film": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="4" width="20" height="16" rx="2" stroke="{color}" stroke-width="1.5"/>
            <path d="M7 4V20M17 4V20M2 9H7M17 9H22M2 15H7M17 15H22" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "editors": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <circle cx="9" cy="7" r="3" stroke="{color}" stroke-width="1.5"/>
            <path d="M3 20C3 17 5.7 15 9 15" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
            <circle cx="17" cy="9" r="2.5" stroke="{color}" stroke-width="1.5"/>
            <path d="M13 20C13 17.8 14.8 16 17 16C19.2 16 21 17.8 21 20" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "settings": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="3" stroke="{color}" stroke-width="1.5"/>
            <path d="M12 2V4M12 20V22M4.22 4.22L5.64 5.64M18.36 18.36L19.78 19.78M2 12H4M20 12H22M4.22 19.78L5.64 18.36M18.36 5.64L19.78 4.22" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "logout": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M16 17L21 12L16 7" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M21 12H9" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M9 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H9" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "login": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M8 7L3 12L8 17" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M3 12H15" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M15 3H19C20.1 3 21 3.9 21 5V19C21 20.1 20.1 21 19 21H15" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "plus": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="9" stroke="{color}" stroke-width="1.5"/>
            <path d="M12 8V16M8 12H16" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "robot": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="8" width="16" height="12" rx="2" stroke="{color}" stroke-width="1.5"/>
            <path d="M9 12H9.01M15 12H15.01" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
            <path d="M9 16H15" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M12 8V5" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
            <circle cx="12" cy="4" r="1.5" stroke="{color}" stroke-width="1.5"/>
            <path d="M4 13H2M22 13H20" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "trash": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M3 6H21M8 6V4H16V6M19 6L18 20H6L5 6" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M10 11V17M14 11V17" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "back": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M9 6L3 12L9 18" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>""",
        "upload": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M12 15V3M8 7L12 3L16 7" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M4 17H20V19C20 20.1 19.1 21 18 21H6C4.9 21 4 20.1 4 19V17Z" stroke="{color}" stroke-width="1.5"/>
        </svg>""",
        "music": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M9 18V6L21 3V15" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="6" cy="18" r="3" stroke="{color}" stroke-width="1.5"/>
            <circle cx="18" cy="15" r="3" stroke="{color}" stroke-width="1.5"/>
        </svg>""",
        "person": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="7" r="4" stroke="{color}" stroke-width="1.5"/>
            <path d="M4 21C4 17.7 7.6 15 12 15C16.4 15 20 17.7 20 21" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "ai": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M12 2C8.7 2 6 4.7 6 8C6 10.4 7.4 12.5 9.4 13.6L9 21H15L14.6 13.6C16.6 12.5 18 10.4 18 8C18 4.7 15.3 2 12 2Z" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M9 8H10M14 8H15" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
            <path d="M10 11C10.5 11.5 13.5 11.5 14 11" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "video": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="4" width="20" height="16" rx="2" stroke="{color}" stroke-width="1.5"/>
            <path d="M10 9L16 12L10 15V9Z" fill="{color}" stroke="{color}" stroke-width="1" stroke-linejoin="round"/>
        </svg>""",
        "thumbnail": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="4" width="20" height="16" rx="2" stroke="{color}" stroke-width="1.5"/>
            <circle cx="8" cy="9" r="2" stroke="{color}" stroke-width="1.2"/>
            <path d="M2 16L7 11L11 15L15 10L22 16" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>""",
        "wand": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M15 3L21 9L9 21L3 15L15 3Z" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M18 12L20 10M14 8L16 6M3 3L5 5M19 19L21 21M3 21L5 19" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
        </svg>""",
        "layers": f"""<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L21 7L12 12L3 7L12 2Z" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M3 12L12 17L21 12" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M3 17L12 22L21 17" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>""",
    }
    return icons.get(name, icons["person"])


def get_genre_icon(icon_key: str, size: int = 44) -> str:
    """
    編集クローンの「見た目のアイコン」。ジャンル名だった旧仕様から独立し、
    単なる見た目バリエーションの選択として使う（中身のジャンル分けはスタイル単位で行う）。
    """
    is_ = str(max(20, int(size * 0.48)))

    ICONS = {
        "ゲーム": {"grad": ("#1a0d40", "#3a1d80"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="gc1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#c8b4ff"/><stop offset="100%" stop-color="#9080ff"/></linearGradient></defs><path d="M4 12C4 9.8 5.8 8 8 8H24C26.2 8 28 9.8 28 12V18C28 22 24 26 20 26H12C8 26 4 22 4 18V12Z" fill="url(#gc1)" fill-opacity="0.3" stroke="url(#gc1)" stroke-width="1.5"/><rect x="8" y="15" width="6" height="2" rx="1" fill="url(#gc1)"/><rect x="10" y="13" width="2" height="6" rx="1" fill="url(#gc1)"/><circle cx="22" cy="14" r="1.5" fill="#ff6b9d"/><circle cx="25" cy="17" r="1.5" fill="#69e0a5"/></svg>"""},
        "Vlog": {"grad": ("#0d2a1a", "#1a5c3a"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="vl1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#69e0a5"/><stop offset="100%" stop-color="#00c870"/></linearGradient></defs><rect x="2" y="8" width="18" height="14" rx="3" fill="url(#vl1)" fill-opacity="0.25" stroke="url(#vl1)" stroke-width="1.5"/><circle cx="11" cy="15" r="4" fill="url(#vl1)" fill-opacity="0.15" stroke="url(#vl1)" stroke-width="1.2"/><path d="M20 12L30 9V21L20 18V12Z" fill="url(#vl1)" fill-opacity="0.7" stroke="url(#vl1)" stroke-width="1.2" stroke-linejoin="round"/><circle cx="26" cy="8" r="2.5" fill="#ff4d4d"/></svg>"""},
        "料理": {"grad": ("#2a1008", "#5c2a10"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="ck1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ffb06b"/><stop offset="100%" stop-color="#e86a2a"/></linearGradient></defs><path d="M6 14H26V22C26 24.2 24.2 26 22 26H10C7.8 26 6 24.2 6 22V14Z" fill="url(#ck1)" fill-opacity="0.3" stroke="url(#ck1)" stroke-width="1.5"/><rect x="4" y="12" width="24" height="3" rx="1.5" fill="url(#ck1)" fill-opacity="0.5"/><path d="M11 9C11 7 13 7 13 5" stroke="url(#ck1)" stroke-width="1.5" stroke-linecap="round"/></svg>"""},
        "音楽": {"grad": ("#1a0a30", "#3a1060"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="ms1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#d080ff"/><stop offset="100%" stop-color="#8030e0"/></linearGradient></defs><rect x="10" y="6" width="2.5" height="16" rx="1.25" fill="url(#ms1)"/><rect x="20" y="4" width="2.5" height="16" rx="1.25" fill="url(#ms1)"/><path d="M10 8L22.5 6V9L10 11V8Z" fill="url(#ms1)"/><ellipse cx="10" cy="23" rx="4" ry="3" fill="url(#ms1)"/><ellipse cx="21" cy="21" rx="4" ry="3" fill="url(#ms1)" fill-opacity="0.9"/></svg>"""},
        "旅行": {"grad": ("#0a1a2e", "#0a3060"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="tr1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#60b4ff"/><stop offset="100%" stop-color="#2070d0"/></linearGradient></defs><circle cx="16" cy="18" r="11" fill="url(#tr1)" fill-opacity="0.2" stroke="url(#tr1)" stroke-width="1.5"/><path d="M8 8L24 6L22 10L14 11L8 8Z" fill="white" fill-opacity="0.9"/></svg>"""},
        "エンタメ": {"grad": ("#2a1808", "#5c3010"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="en1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ffd060"/><stop offset="100%" stop-color="#ff7020"/></linearGradient></defs><path d="M16 2L19.5 12H30L21.5 18L24.5 28L16 22L7.5 28L10.5 18L2 12H12.5L16 2Z" fill="url(#en1)" fill-opacity="0.9"/></svg>"""},
        "その他": {"grad": ("#1a1040", "#3a2880"), "svg": f"""<svg width="{is_}" height="{is_}" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="ot1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#b0a0ff"/><stop offset="100%" stop-color="#7060d0"/></linearGradient></defs><circle cx="16" cy="9" r="5" fill="url(#ot1)" fill-opacity="0.8"/><path d="M6 28C6 22 10.5 18 16 18C21.5 18 26 22 26 28" stroke="url(#ot1)" stroke-width="2" stroke-linecap="round"/></svg>"""},
    }

    info = ICONS.get(icon_key, ICONS["その他"])
    grad_from, grad_to = info["grad"]
    return f"""<div style="
        width:{size}px;height:{size}px;border-radius:14px;
        background:linear-gradient(135deg,{grad_from},{grad_to});
        border:1px solid {grad_to}44;display:inline-flex;
        align-items:center;justify-content:center;flex-shrink:0;
        box-shadow:0 4px 12px {grad_to}44;overflow:hidden;
    ">{info['svg']}</div>"""


ICON_CHOICES = ["ゲーム", "Vlog", "料理", "音楽", "旅行", "エンタメ", "その他"]


# ========== UIコンポーネント ==========

def render_section_title(title: str, theme_name: str):
    t = get_theme(theme_name)
    st.markdown(f"""
    <div style="font-size:11px;color:{t['text_secondary']};font-weight:500;
        letter-spacing:0.08em;text-transform:uppercase;margin:16px 0 10px;
        padding-bottom:6px;border-bottom:0.5px solid {t['border']};">{title}</div>
    """, unsafe_allow_html=True)


def render_alert(message: str, alert_type: str, theme_name: str):
    t = get_theme(theme_name)
    colors = {"success": t['success'], "warning": t['warning'], "error": t['error'], "info": t['accent']}
    icons_map = {"success": "plus", "warning": "trash", "error": "trash", "info": "robot"}
    color = colors.get(alert_type, t['accent'])
    icon_html = svg(icons_map.get(alert_type, "robot"), 16, color)
    st.markdown(f"""
    <div style="background:{color}22;border:0.5px solid {color}44;border-radius:8px;
        padding:10px 14px;margin:8px 0;display:flex;align-items:center;gap:8px;
        color:{color};font-size:13px;">{icon_html} {message}</div>
    """, unsafe_allow_html=True)


def run_ai_with_progress(stream, label: str = "AIが処理中") -> str:
    """
    Claude API のストリーミング応答（Iterator[str]）を受け取りながら、
    経過時間と進捗バーをリアルタイム表示し、完成したテキストを返す。
    """
    ss = st.session_state
    avg_seconds = ss.get("ai_avg_seconds", 15.0)
    avg_chars = ss.get("ai_avg_chars", 500)

    bar = st.progress(0.0, text=f"{label}…　準備中")
    start = time.time()
    full_text = ""

    for chunk in stream:
        full_text += chunk
        elapsed = time.time() - start
        char_pct = len(full_text) / max(avg_chars, 1)
        time_pct = elapsed / max(avg_seconds, 1)
        pct = min(max(char_pct, time_pct), 0.95)
        remaining = max(avg_seconds - elapsed, 1)
        bar.progress(pct, text=f"{label}…　{int(pct * 100)}%　経過 {elapsed:.0f}秒 ／ 残り目安 約{remaining:.0f}秒")

    elapsed_total = time.time() - start
    bar.progress(1.0, text=f"✅ 完了！（{elapsed_total:.0f}秒）")

    if full_text:
        ss["ai_avg_seconds"] = round(avg_seconds * 0.7 + elapsed_total * 0.3, 1)
        ss["ai_avg_chars"] = round(avg_chars * 0.7 + len(full_text) * 0.3, 1)

    return full_text

def progress_time_text(label: str, pct: int, elapsed: float, avg_seconds: float) -> str:
    if elapsed < avg_seconds:
        remaining = avg_seconds - elapsed
        return f"{label}…　{pct}%　経過 {elapsed:.0f}秒 ／ 残り目安 約{remaining:.0f}秒"
    return f"{label}…　{pct}%　経過 {elapsed:.0f}秒 ／ 想定（約{avg_seconds:.0f}秒）を超えています。完了までそのままお待ちください"