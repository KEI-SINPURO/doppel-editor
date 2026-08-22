"""
ai/trainer.py  ―  データ保存層（ローカルJSON + ファイル保存）

【今回のスコープ変更で構造が変わった点】
  旧: 編集者(editor) = 1つのジャンル・1つのスタイル
  新: 編集者(editor) = 複数の「ジャンル別スタイル」を持てる

    editor
     ├─ styles: { style_id: {label, style_data, brightness_data, videos, ...}, ... }
     └─ assets: { logo, font, bgm:[...], se:[...] }   ← 個人素材（ロゴ/フォント/BGM/SE）

保存先: ~/.doppel_editor/
  editors.json          … 編集者・スタイル一覧のメタデータ
  assets/<editor_id>/   … アップロードされたロゴ・フォント・BGM・SEの実ファイル
  feedback/<editor_id>.json … フィードバック履歴
"""

import json
import os
import shutil
from datetime import datetime
from typing import Optional, TypeVar, List, Dict

_T = TypeVar("_T")

DATA_DIR = os.path.expanduser("~/.doppel_editor")
EDITORS_FILE = os.path.join(DATA_DIR, "editors.json")
ASSET_DIR = os.path.join(DATA_DIR, "assets")
FEEDBACK_DIR = os.path.join(DATA_DIR, "feedback")

_ASSET_KIND_SINGLE = {"logo", "font"}   # 1つだけ保持する素材
_ASSET_KIND_MULTI = {"bgm", "se"}       # 複数保持できる素材


def init_storage():
    """ストレージの初期化（初回起動時に呼ぶ）"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ASSET_DIR, exist_ok=True)
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    if not os.path.exists(EDITORS_FILE):
        _write_json(EDITORS_FILE, [])


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path: str, default: _T) -> _T:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]


# ============================================================
# 編集者（クローン）本体
# ============================================================

def load_editors() -> List[Dict]:
    init_storage()
    return _read_json(EDITORS_FILE, [])


def save_editors(editors: list):
    init_storage()
    _write_json(EDITORS_FILE, editors)


def create_editor(name: str, icon: str, theme: str) -> Dict:
    """新しい編集クローンを作成する（ジャンル別スタイルは後から追加していく）"""
    editors = load_editors()
    editor = {
        "id": _new_id(),
        "name": name,
        "icon": icon,
        "theme": theme,
        "styles": {},   # style_id -> {label, style_data, brightness_data, videos, created_at, updated_at}
        "assets": {"logo": None, "font": None, "bgm": [], "se": []},
        "feedback_count": 0,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    editors.append(editor)
    save_editors(editors)
    return editor


def get_editor(editor_id: Optional[str]) -> Optional[Dict]:
    if not editor_id:
        return None
    for e in load_editors():
        if e["id"] == editor_id:
            return e
    return None


def update_editor(editor_id: str, updates: dict) -> Optional[Dict]:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id:
            editors[i].update(updates)
            editors[i]["updated_at"] = datetime.now().isoformat()
            save_editors(editors)
            return editors[i]
    return None


def delete_editor(editor_id: str) -> bool:
    editors = load_editors()
    editors = [e for e in editors if e["id"] != editor_id]
    save_editors(editors)

    fb_file = os.path.join(FEEDBACK_DIR, f"{editor_id}.json")
    if os.path.exists(fb_file):
        try:
            os.unlink(fb_file)
        except Exception:
            pass

    asset_dir = os.path.join(ASSET_DIR, editor_id)
    if os.path.isdir(asset_dir):
        try:
            shutil.rmtree(asset_dir)
        except Exception:
            pass

    training_dir = os.path.join(DATA_DIR, "training", editor_id)
    if os.path.isdir(training_dir):
        try:
            shutil.rmtree(training_dir)
        except Exception:
            pass
    return True


# ============================================================
# ジャンル別スタイル
# ============================================================

def add_style(editor_id: str, label: str) -> Optional[str]:
    """編集者に新しい「ジャンル別スタイル」の枠を作成し、style_idを返す"""
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id:
            style_id = _new_id()
            editors[i].setdefault("styles", {})[style_id] = {
                "label": label,
                "style_data": {},
                "brightness_data": {},
                "videos": [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            editors[i]["updated_at"] = datetime.now().isoformat()
            save_editors(editors)
            return style_id
    return None


def save_style_data(editor_id: str, style_id: str, style_data: dict,
                     brightness_data: Optional[dict] = None) -> bool:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id and style_id in e.get("styles", {}):
            editors[i]["styles"][style_id]["style_data"] = style_data
            if brightness_data:
                editors[i]["styles"][style_id]["brightness_data"] = brightness_data
            editors[i]["styles"][style_id]["updated_at"] = datetime.now().isoformat()
            editors[i]["updated_at"] = datetime.now().isoformat()
            save_editors(editors)
            return True
    return False


def rename_style(editor_id: str, style_id: str, new_label: str) -> bool:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id and style_id in e.get("styles", {}):
            editors[i]["styles"][style_id]["label"] = new_label
            save_editors(editors)
            return True
    return False


def delete_style(editor_id: str, style_id: str) -> bool:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id and style_id in e.get("styles", {}):
            del editors[i]["styles"][style_id]
            save_editors(editors)
            return True
    return False


def add_video_to_style(editor_id: str, style_id: str, video_info: dict) -> bool:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id and style_id in e.get("styles", {}):
            entry = {"id": _new_id(), "added_at": datetime.now().isoformat(), **video_info}
            editors[i]["styles"][style_id].setdefault("videos", []).append(entry)
            editors[i]["updated_at"] = datetime.now().isoformat()
            save_editors(editors)
            return True
    return False


def get_style(editor_id: str, style_id: str) -> Optional[Dict]:
    editor = get_editor(editor_id)
    if not editor:
        return None
    return editor.get("styles", {}).get(style_id)


# ============================================================
# 個人素材（ロゴ・フォント・BGM・効果音）
# ============================================================

def save_asset(editor_id: str, kind: str, file_bytes: bytes, filename: str,
                label: str = "") -> Optional[Dict]:
    """
    個人素材を保存する。
    kind: "logo" | "font" | "bgm" | "se"
    logo / font は1個だけ保持（新しくアップロードすると差し替え）。
    bgm / se は複数保持できる。
    """
    if kind not in _ASSET_KIND_SINGLE | _ASSET_KIND_MULTI:
        return None

    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] != editor_id:
            continue

        asset_dir = os.path.join(ASSET_DIR, editor_id, kind)
        os.makedirs(asset_dir, exist_ok=True)
        asset_id = _new_id()
        ext = os.path.splitext(filename)[1]
        saved_path = os.path.join(asset_dir, f"{asset_id}{ext}")
        with open(saved_path, "wb") as f:
            f.write(file_bytes)

        entry = {
            "id": asset_id,
            "filename": filename,
            "path": saved_path,
            "label": label or filename,
            "added_at": datetime.now().isoformat(),
        }

        editors[i].setdefault("assets", {"logo": None, "font": None, "bgm": [], "se": []})

        if kind in _ASSET_KIND_SINGLE:
            old = editors[i]["assets"].get(kind)
            if old and old.get("path") and os.path.exists(old["path"]):
                try:
                    os.unlink(old["path"])
                except Exception:
                    pass
            editors[i]["assets"][kind] = entry
        else:
            editors[i]["assets"].setdefault(kind, []).append(entry)

        editors[i]["updated_at"] = datetime.now().isoformat()
        save_editors(editors)
        return entry
    return None


def delete_asset(editor_id: str, kind: str, asset_id: Optional[str] = None) -> bool:
    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] != editor_id:
            continue
        assets = editors[i].setdefault("assets", {"logo": None, "font": None, "bgm": [], "se": []})

        if kind in _ASSET_KIND_SINGLE:
            old = assets.get(kind)
            if old and old.get("path") and os.path.exists(old["path"]):
                try:
                    os.unlink(old["path"])
                except Exception:
                    pass
            assets[kind] = None
        else:
            items = assets.get(kind, [])
            keep = []
            for item in items:
                if item.get("id") == asset_id:
                    if item.get("path") and os.path.exists(item["path"]):
                        try:
                            os.unlink(item["path"])
                        except Exception:
                            pass
                else:
                    keep.append(item)
            assets[kind] = keep

        save_editors(editors)
        return True
    return False


def load_assets(editor_id: str) -> Dict:
    editor = get_editor(editor_id)
    if not editor:
        return {"logo": None, "font": None, "bgm": [], "se": []}
    return editor.get("assets", {"logo": None, "font": None, "bgm": [], "se": []})


# ============================================================
# フィードバック
# ============================================================

def save_feedback(editor_id: str, feedback: dict):
    init_storage()
    fb_file = os.path.join(FEEDBACK_DIR, f"{editor_id}.json")
    feedbacks = _read_json(fb_file, [])
    feedbacks.append({"timestamp": datetime.now().isoformat(), "feedback": feedback})
    _write_json(fb_file, feedbacks)

    editors = load_editors()
    for i, e in enumerate(editors):
        if e["id"] == editor_id:
            editors[i]["feedback_count"] = len(feedbacks)
            editors[i]["updated_at"] = datetime.now().isoformat()
            save_editors(editors)
            break


def load_feedback(editor_id: str) -> list:
    fb_file = os.path.join(FEEDBACK_DIR, f"{editor_id}.json")
    return _read_json(fb_file, [])


def get_editor_summary(editor_id: str) -> str:
    """AIへの参考情報として渡す、編集者のサマリー文字列"""
    editor = get_editor(editor_id)
    if not editor:
        return ""
    lines = [f"編集者名: {editor['name']}", f"フィードバック数: {editor.get('feedback_count', 0)}"]
    for style in editor.get("styles", {}).values():
        s = style.get("style_data", {})
        patterns = s.get("editing_patterns", {})
        pattern_str = (
            f" / 残す割合={int(patterns.get('keep_ratio', 1) * 100)}%"
            f" / フィラー除去率={int(patterns.get('filler_removal_rate', 0) * 100)}%"
        ) if patterns else ""
        lines.append(
            f"- スタイル「{style.get('label', '')}」: "
            f"テンポ={s.get('tempo', '未分析')} / "
            f"テロップ色={s.get('dominant_color', '未分析')} / "
            f"カット数={s.get('total_cuts', '未分析')}{pattern_str}"
        )
    return "\n".join(lines)