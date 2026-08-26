THEMES = {
    "ダーク": {
        "bg_primary":    "#08080f",
        "bg_secondary":  "#0b0b14",
        "bg_card":       "#0f0f1a",
        "accent":        "#7f77dd",
        "accent_sub":    "#534ab7",
        "text_primary":  "#e0e0f0",
        "text_secondary":"#6a6a82",
        "button_bg":     "#13131e",
        "button_hover":  "#1e1e32",
        "border":        "#1e1e2e",
        "success":       "#00e676",
        "warning":       "#ffb300",
        "error":         "#ff1744",
        "sidebar_bg":    "#0d0d22",
    },
    "ネオン": {
        "bg_primary":    "#050510",
        "bg_secondary":  "#0d0d1f",
        "bg_card":       "#12122a",
        "accent":        "#00ff88",
        "accent_sub":    "#ff00ff",
        "text_primary":  "#ffffff",
        "text_secondary":"#aaaacc",
        "button_bg":     "#1a1a3a",
        "button_hover":  "#2a2a4a",
        "border":        "#00ff8833",
        "success":       "#00ff88",
        "warning":       "#ffaa00",
        "error":         "#ff0055",
        "sidebar_bg":    "#10103a",
    },
    "ライト": {
        "bg_primary":    "#f0f0f5",
        "bg_secondary":  "#ffffff",
        "bg_card":       "#e8e8f0",
        "accent":        "#534ab7",
        "accent_sub":    "#7f77dd",
        "text_primary":  "#111111",
        "text_secondary":"#555566",
        "button_bg":     "#e0e0ea",
        "button_hover":  "#d0d0e0",
        "border":        "#c8c8d8",
        "success":       "#2e7d32",
        "warning":       "#e65100",
        "error":         "#c62828",
        "sidebar_bg":    "#ececf5",
    },
    "サンセット": {
        "bg_primary":    "#0a0a1a",
        "bg_secondary":  "#12122a",
        "bg_card":       "#1a1a35",
        "accent":        "#ff6b35",
        "accent_sub":    "#ff3fa4",
        "text_primary":  "#ffffff",
        "text_secondary":"#ffaaaa",
        "button_bg":     "#1f1f3f",
        "button_hover":  "#2f2f4f",
        "border":        "#ff6b3533",
        "success":       "#00e676",
        "warning":       "#ff6b35",
        "error":         "#ff1744",
        "sidebar_bg":    "#161640",
    },
    "フォレスト": {
        "bg_primary":    "#0a120a",
        "bg_secondary":  "#0f1f0f",
        "bg_card":       "#152415",
        "accent":        "#c8a951",
        "accent_sub":    "#4caf50",
        "text_primary":  "#e8f5e9",
        "text_secondary":"#a5d6a7",
        "button_bg":     "#1b2e1b",
        "button_hover":  "#243e24",
        "border":        "#c8a95133",
        "success":       "#4caf50",
        "warning":       "#c8a951",
        "error":         "#ef5350",
        "sidebar_bg":    "#122012",
    },
    "オーシャン": {
        "bg_primary":    "#020b18",
        "bg_secondary":  "#041525",
        "bg_card":       "#071e33",
        "accent":        "#00b4d8",
        "accent_sub":    "#48cae4",
        "text_primary":  "#e0f4ff",
        "text_secondary":"#90caf9",
        "button_bg":     "#0a2440",
        "button_hover":  "#0d2e50",
        "border":        "#00b4d833",
        "success":       "#00e5ff",
        "warning":       "#ffb300",
        "error":         "#ff1744",
        "sidebar_bg":    "#061c34",
    },
}


def get_theme(theme_name: str) -> dict:
    return THEMES.get(theme_name, THEMES["ダーク"])


def get_css(theme_name: str) -> str:
    t = get_theme(theme_name)
    return f"""
    <style>
        .stApp {{ background-color: {t['bg_primary']} !important; }}
        .main .block-container {{ padding: 1.5rem 2rem 3rem !important; max-width: 100% !important; }}
        .stApp, .stApp p, .stApp span, .stApp div,
        .stApp label, .stApp li, .stApp td, .stApp th {{ color: {t['text_primary']} !important; }}
        h1, h2, h3, h4, h5, h6 {{ color: {t['text_primary']} !important; font-weight: 500 !important; }}

        section[data-testid="stSidebar"] {{
            background-color: {t['sidebar_bg']} !important;
            border-right: 2px solid {t['accent']}44 !important;
            min-width: 250px !important; max-width: 290px !important;
            box-shadow: 4px 0 20px rgba(0,0,0,0.4) !important;
        }}
        section[data-testid="stSidebar"] > div {{
            background-color: {t['sidebar_bg']} !important; padding: 1.2rem 0.9rem !important;
        }}
        section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] div, section[data-testid="stSidebar"] label {{
            color: {t['text_primary']} !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {{
            background-color: rgba(255,255,255,0.04) !important;
            border: 0.5px solid {t['border']} !important;
            color: {t['text_primary']} !important; text-align: left !important;
            padding: 10px 14px !important; font-size: 13px !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {{
            background-color: {t['accent']}18 !important; border-color: {t['accent']}66 !important;
            color: {t['accent']} !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] {{
            background: linear-gradient(135deg, {t['accent_sub']}44, {t['accent']}33) !important;
            border-color: {t['accent']}66 !important; color: {t['accent']} !important;
        }}

        [data-testid="stSidebarCollapsedControl"] {{
            position: fixed !important; top: 50% !important; left: 0px !important;
            transform: translateY(-50%) !important; z-index: 999999 !important;
            display: flex !important; visibility: visible !important; opacity: 1 !important;
            background: linear-gradient(135deg, {t['accent_sub']}, {t['accent']}) !important;
            border: none !important; border-radius: 0 16px 16px 0 !important;
            width: 36px !important; height: 72px !important;
            align-items: center !important; justify-content: center !important;
            cursor: pointer !important; box-shadow: 4px 0 20px {t['accent_sub']}88 !important;
            transition: width 0.2s ease, box-shadow 0.2s ease !important;
        }}
        [data-testid="stSidebarCollapsedControl"]:hover {{
            width: 44px !important; box-shadow: 6px 0 28px {t['accent']}aa !important;
        }}
        [data-testid="stSidebarCollapsedControl"] button {{
            background: transparent !important; border: none !important;
            width: 100% !important; height: 100% !important; padding: 0 !important;
            display: flex !important; align-items: center !important; justify-content: center !important;
        }}
        [data-testid="stSidebarCollapsedControl"] svg {{
            stroke: #ffffff !important; fill: none !important; width: 20px !important; height: 20px !important;
        }}
        [data-testid="stSidebarCollapseButton"] button {{
            color: {t['text_secondary']} !important; background: transparent !important; border: none !important;
        }}
        [data-testid="stSidebarCollapseButton"] button:hover {{
            color: {t['accent']} !important; background: {t['button_hover']} !important;
        }}

        .stButton > button, div[data-testid="stButton"] > button {{
            background-color: {t['button_bg']} !important; color: {t['text_primary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
            padding: 10px 18px !important; font-size: 13px !important; font-weight: 400 !important;
            transition: background-color 0.2s, border-color 0.2s, color 0.2s !important;
            width: 100% !important;
        }}
        .stButton > button:hover, div[data-testid="stButton"] > button:hover {{
            background-color: {t['button_hover']} !important; border-color: {t['accent']}88 !important;
            color: {t['accent']} !important;
        }}
        .stButton > button p, div[data-testid="stButton"] > button p {{
            color: inherit !important; font-size: 13px !important;
        }}
        div[data-testid="stLinkButton"] a {{
            background-color: {t['button_bg']} !important; color: {t['text_primary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
            padding: 10px 18px !important; font-size: 13px !important; font-weight: 400 !important;
            display: flex !important; align-items: center !important; justify-content: center !important;
            width: 100% !important; text-decoration: none !important;
            transition: background-color 0.2s, border-color 0.2s, color 0.2s !important;
        }}
        div[data-testid="stLinkButton"] a:hover {{
            background-color: {t['button_hover']} !important; border-color: {t['accent']}88 !important;
            color: {t['accent']} !important;
        }}
        div[data-testid="stLinkButton"] a p {{
            color: inherit !important; font-size: 13px !important; margin: 0 !important;
        }}
        div[data-testid="stButton"] button[kind="primary"],
        button[data-testid="baseButton-primary"], .stButton button[kind="primary"] {{
            background: linear-gradient(135deg, {t['accent_sub']}, {t['accent']}) !important;
            color: #ffffff !important; border: none !important; font-weight: 600 !important;
            font-size: 14px !important; letter-spacing: 0.02em !important;
            box-shadow: 0 2px 8px {t['accent_sub']}44 !important;
        }}
        div[data-testid="stButton"] button[kind="primary"]:hover,
        button[data-testid="baseButton-primary"]:hover {{
            opacity: 0.88 !important; color: #ffffff !important;
            box-shadow: 0 4px 16px {t['accent_sub']}66 !important;
        }}
        div[data-testid="stButton"] button[kind="primary"] p,
        button[data-testid="baseButton-primary"] p {{ color: #ffffff !important; font-size: 14px !important; }}

        .stTextInput > div > div > input {{
            background-color: {t['bg_card']} !important; color: {t['text_primary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
            font-size: 14px !important; padding: 10px 14px !important;
        }}
        .stTextInput > div > div > input::placeholder {{ color: {t['text_secondary']} !important; }}
        .stTextInput > div > div > input:focus {{
            border-color: {t['accent']} !important; box-shadow: 0 0 0 2px {t['accent']}22 !important;
        }}
        .stTextInput label, .stTextInput label p {{
            color: {t['text_primary']} !important; font-size: 13px !important; font-weight: 500 !important;
        }}

        .stSelectbox > div > div {{
            background-color: {t['bg_card']} !important; color: {t['text_primary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
        }}
        .stSelectbox label, .stSelectbox label p {{ color: {t['text_primary']} !important; font-size: 13px !important; }}
        [data-baseweb="popover"] {{ background-color: {t['bg_card']} !important; border: 0.5px solid {t['border']} !important; }}
        [role="option"] {{ background-color: {t['bg_card']} !important; color: {t['text_primary']} !important; }}
        [role="option"]:hover {{ background-color: {t['button_hover']} !important; }}

        .stTabs [data-baseweb="tab-list"] {{
            background-color: transparent !important; border-bottom: 1px solid {t['border']} !important; gap: 0 !important;
        }}
        .stTabs [data-baseweb="tab"] {{
            background-color: transparent !important; color: {t['text_secondary']} !important;
            border: none !important; padding: 10px 20px !important; font-size: 13px !important;
        }}
        .stTabs [data-baseweb="tab"] p {{ color: inherit !important; font-size: 13px !important; }}
        .stTabs [aria-selected="true"] {{
            color: {t['accent']} !important; border-bottom: 2px solid {t['accent']} !important;
            background-color: {t['accent']}0d !important;
        }}
        .stTabs [aria-selected="true"] p {{ color: {t['accent']} !important; }}
        .stTabs [data-baseweb="tab-panel"] {{ background-color: transparent !important; padding: 16px 0 !important; }}

        .stProgress > div > div > div {{
            background: linear-gradient(90deg, {t['accent_sub']}, {t['accent']}) !important; border-radius: 4px !important;
        }}
        .stProgress > div > div {{ background-color: {t['border']} !important; border-radius: 4px !important; }}

        [data-testid="metric-container"] {{
            background-color: {t['bg_card']} !important; border: 0.5px solid {t['border']} !important;
            border-radius: 12px !important; padding: 16px !important;
        }}
        [data-testid="metric-container"] label, [data-testid="metric-container"] label p {{
            color: {t['text_secondary']} !important; font-size: 11px !important;
        }}
        [data-testid="metric-container"] [data-testid="stMetricValue"],
        [data-testid="metric-container"] [data-testid="stMetricValue"] div {{
            color: {t['accent']} !important; font-size: 22px !important; font-weight: 500 !important;
        }}

        [data-testid="stAlert"] {{ border-radius: 8px !important; }}
        [data-testid="stAlert"] p {{ color: {t['text_primary']} !important; font-size: 13px !important; }}

        [data-testid="stFileUploader"] {{
            background-color: {t['bg_card']} !important; border: 1.5px dashed {t['accent']}44 !important;
            border-radius: 12px !important; padding: 8px !important; transition: border-color 0.2s !important;
        }}
        [data-testid="stFileUploader"]:hover {{ border-color: {t['accent']}88 !important; }}
        [data-testid="stFileUploader"] p, [data-testid="stFileUploader"] span {{ color: {t['text_primary']} !important; }}
        [data-testid="stFileUploaderDropzoneInstructions"] span,
        [data-testid="stFileUploaderDropzoneInstructions"] small {{ color: {t['text_secondary']} !important; }}

        [data-testid="stFileUploaderFile"] {{
            background-color: {t['bg_secondary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
        }}
        [data-testid="stFileUploaderFileName"] {{
            color: {t['text_primary']} !important; font-size: 13px !important;
        }}
        [data-testid="stFileUploaderFile"] small,
        [data-testid="stFileUploaderFile"] span {{
            color: {t['text_secondary']} !important;
        }}
        [data-testid="stFileUploaderDeleteBtn"] button {{
            color: {t['text_secondary']} !important; background: transparent !important;
        }}
        [data-testid="stFileUploaderDeleteBtn"] button:hover {{
            color: {t['error']} !important;
        }}

        .stRadio label p {{ color: {t['text_primary']} !important; font-size: 14px !important; }}
        .stMultiSelect > div > div {{
            background-color: {t['bg_card']} !important; border: 0.5px solid {t['border']} !important; border-radius: 8px !important;
        }}
        .stMultiSelect label p {{ color: {t['text_primary']} !important; font-size: 13px !important; }}
        .stSlider label p, .stSlider p {{ color: {t['text_primary']} !important; font-size: 13px !important; }}
        .stCaption, .stCaption p {{ color: {t['text_secondary']} !important; font-size: 12px !important; }}
        [data-testid="stForm"] {{ background-color: transparent !important; border: none !important; }}
        .stCheckbox label p {{ color: {t['text_primary']} !important; font-size: 14px !important; }}
        .stTextArea textarea {{
            background-color: {t['bg_card']} !important; color: {t['text_primary']} !important;
            border: 0.5px solid {t['border']} !important; border-radius: 8px !important; font-size: 14px !important;
        }}

        header[data-testid="stHeader"] {{
            background-color: {t['bg_primary']} !important; border-bottom: 0.5px solid {t['border']} !important;
        }}
        #MainMenu {{display: none !important;}}
        footer {{display: none !important;}}
        [data-testid="stToolbar"] {{display: none !important;}}
        [data-testid="stDecoration"] {{display: none !important;}}
        header button[title="Deploy"] {{display: none !important;}}

        ::-webkit-scrollbar {{width: 5px; height: 5px;}}
        ::-webkit-scrollbar-track {{background: {t['bg_secondary']};}}
        ::-webkit-scrollbar-thumb {{ background: {t['border']}; border-radius: 3px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: {t['accent']}66; }}
    </style>
    """
