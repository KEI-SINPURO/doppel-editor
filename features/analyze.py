"""
features/analyze.py  ―  動画スタイル分析

過去に投稿した「編集済み動画」を解析して、
  - カットの頻度・平均間隔・リズムパターン（テンポ）
  - テロップの色・位置・出現密度
  - 明るさ・カラートーン（暖色系／寒色系）
を数値として抽出する。ここで得られた値が、STEP2（新しい動画への自動再現）で
そのまま使われる「学習済みスタイル」の中身になる。

【今回追加した点】
  analyze_cut_rhythm()      … カット間隔の「平均」だけでなく「ばらつき」を見て、
                               一定リズム型／緩急型／不規則型のどれかを判定する。
  analyze_editing_patterns()… 編集前(raw)と編集後(edited)の文字起こしを比較し、
                               「その編集者がどう素材を削っているか」というカットの
                               判断基準（残す割合・フィラー語の除去傾向・文の区切りで
                               切る傾向など）を学習する。これがSTEP2で
                               「単なる無音カット」ではなく「その人らしいカット」を
                               再現するための土台になる。

【注意】
  raw/edited比較はタイムコードでの厳密なアライメントは行わず、
  文字起こしテキストの近似マッチング（difflib）で「残された／カットされた」を
  推定する簡易的な手法です。完全に正確ではありませんが、
  「傾向を掴んでAIへのヒントにする」という目的には十分な精度を狙っています。
"""

import cv2
import numpy as np
import tempfile
import os
import difflib
from typing import Optional


# 「えー」「あの」のようなフィラー語（言い淀み）。
# editing_patterns の学習・ヒューリスティック判定の両方で使う基準リスト。
FILLER_WORDS = [
    "えー", "えっと", "えっとー", "あのー", "あの", "まあ", "まぁ",
    "なんか", "そのー", "その", "うーん", "ちょっと待って",
]


def analyze_style(video_bytes: bytes) -> Optional[dict]:
    """編集済み動画からスタイルを分析する"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps else 0

        subtitle_regions = []
        cut_points = []
        frame_count = 0
        prev_frame = None
        sample_interval = max(int(fps), 1)

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # カット検出
            if prev_frame is not None:
                diff = cv2.absdiff(frame, prev_frame)
                diff_score = np.mean(diff)
                if diff_score > 30:
                    cut_points.append(frame_count / fps)

            # テロップ検出（1秒ごと）
            if frame_count % sample_interval == 0:
                height, width = frame.shape[:2]
                bottom_region = frame[int(height * 0.7):, :]
                hsv = cv2.cvtColor(bottom_region, cv2.COLOR_BGR2HSV)

                white_mask = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 30, 255]))
                yellow_mask = cv2.inRange(hsv, np.array([20, 100, 100]), np.array([40, 255, 255]))

                white_ratio = np.sum(white_mask > 0) / (bottom_region.shape[0] * bottom_region.shape[1])
                yellow_ratio = np.sum(yellow_mask > 0) / (bottom_region.shape[0] * bottom_region.shape[1])

                if white_ratio > 0.01 or yellow_ratio > 0.01:
                    dominant_color = "白" if white_ratio > yellow_ratio else "黄色"
                    subtitle_regions.append({
                        "timestamp": round(frame_count / fps, 1),
                        "color": dominant_color,
                        "position": detect_subtitle_position(frame),
                    })

            prev_frame = frame.copy()
            frame_count += 1

        cap.release()
        os.unlink(tmp_path)

        # カットのリズム分析（平均だけでなく、ばらつき・パターンも見る）
        rhythm = analyze_cut_rhythm(cut_points, duration)

        # テロップカラー集計
        white_count = sum(1 for r in subtitle_regions if r["color"] == "白")
        yellow_count = sum(1 for r in subtitle_regions if r["color"] == "黄色")
        dominant_color = "white" if white_count >= yellow_count else "yellow"

        # テロップ位置集計
        positions = [r["position"] for r in subtitle_regions]
        dominant_position = max(set(positions), key=positions.count) if positions else "下部"

        # テロップの出現密度（1分あたり何回テロップが検出されたか）
        subtitle_density = round(len(subtitle_regions) / duration * 60, 1) if duration else 0

        return {
            "duration": round(duration, 1),
            "total_cuts": len(cut_points),
            "avg_cut_interval": rhythm["avg_interval"],
            "cut_points": cut_points,
            "dominant_color": dominant_color,
            "dominant_position": dominant_position,
            "subtitle_count": len(subtitle_regions),
            "subtitle_regions": subtitle_regions,
            "subtitle_density": subtitle_density,
            "tempo": classify_tempo(rhythm["avg_interval"]),
            "rhythm": rhythm,
        }

    except Exception as e:
        print(f"スタイル分析エラー: {e}")
        return None


def analyze_cut_rhythm(cut_points: list, duration: float) -> dict:
    """
    カット間隔の「平均」だけでなく「ばらつき（標準偏差）」を見て、
    その編集者のカットのリズムパターンを分類する。

    - 一定リズム型: メトロノームのように、ほぼ均等な間隔で刻む
    - 緩急型      : 場面に応じてテンポを意図的に変える
    - 不規則型    : カットのタイミングが大きくばらつく

    このパターンは ai/model.py のプロンプトに渡され、
    Claudeが編集プランを組み立てる際の「テンポ感」の参考になる。
    """
    intervals = [cut_points[i + 1] - cut_points[i] for i in range(len(cut_points) - 1)]
    if not intervals:
        return {
            "avg_interval": 0, "std_interval": 0, "min_interval": 0,
            "max_interval": 0, "cuts_per_minute": 0, "rhythm_pattern": "不明",
        }

    avg = sum(intervals) / len(intervals)
    variance = sum((x - avg) ** 2 for x in intervals) / len(intervals)
    std = variance ** 0.5
    cuts_per_minute = (len(cut_points) / duration * 60) if duration else 0

    coefficient_of_variation = (std / avg) if avg else 0
    if coefficient_of_variation < 0.3:
        pattern = "一定リズム型（ほぼ均等な間隔でカットする）"
    elif coefficient_of_variation < 0.7:
        pattern = "緩急型（場面に応じてテンポを変える）"
    else:
        pattern = "不規則型（カットのタイミングが大きく変化する）"

    return {
        "avg_interval": round(avg, 2),
        "std_interval": round(std, 2),
        "min_interval": round(min(intervals), 2),
        "max_interval": round(max(intervals), 2),
        "cuts_per_minute": round(cuts_per_minute, 1),
        "rhythm_pattern": pattern,
    }


def analyze_editing_patterns(raw_segments: list, edited_segments: list) -> dict:
    """
    編集前(raw)素材と編集後(edited)動画、それぞれの文字起こしセグメントを比較し、
    「編集者がどういう基準で発言をカットしているか」の癖を学習する。

    アプローチ（完全一致のタイムライン整列は行わず、テキストベースの近似）:
      raw の各発言セグメントについて、その内容が edited 側の文字起こし全体の
      中にどれだけ含まれているかを difflib で調べ、「残された」か「カットされた」かを判定する。

    Args:
        raw_segments   : 編集前素材のWhisperセグメント [{"start","end","text"}, ...]
        edited_segments: 編集後完成動画のWhisperセグメント（同上）

    Returns:
        {
          "keep_ratio": float,             # 素材のうち時間ベースで残された割合(0~1)
          "cut_count": int,                # カットされたセグメント数
          "avg_cut_duration": float,       # カットされた発言1つあたりの平均秒数
          "filler_removal_rate": float,    # フィラー語を含む発言のうち、カットされた割合
          "boundary_tendency": float,      # カットが句読点（文の区切り）で終わる発言だった割合
          "typical_cut_examples": [str],   # 実際にカットされた発言の例（最大5件・各40文字まで）
        }
        raw_segments が空の場合は {} を返す。
    """
    if not raw_segments:
        return {}

    edited_text_joined = "".join(s.get("text", "").strip() for s in edited_segments) if edited_segments else ""

    def _is_kept(text: str) -> bool:
        if not text:
            return True  # 空発言は判定対象外（カット扱いしない）
        matcher = difflib.SequenceMatcher(None, text, edited_text_joined)
        match = matcher.find_longest_match(0, len(text), 0, len(edited_text_joined))
        # 発言の6割以上がedited側に連続して見つかれば「残された」とみなす
        return match.size >= max(2, int(len(text) * 0.6))

    kept_flags = [_is_kept(s.get("text", "").strip()) for s in raw_segments]

    total_raw_duration = sum(max(0, s.get("end", 0) - s.get("start", 0)) for s in raw_segments)
    cut_segments = [
        s for s, kept in zip(raw_segments, kept_flags)
        if not kept and s.get("text", "").strip()
    ]

    cut_duration = sum(max(0, s.get("end", 0) - s.get("start", 0)) for s in cut_segments)
    keep_ratio = 1 - (cut_duration / total_raw_duration) if total_raw_duration else 1.0

    filler_total = sum(
        1 for s in raw_segments if any(fw in s.get("text", "") for fw in FILLER_WORDS)
    )
    filler_cut = sum(
        1 for s in cut_segments if any(fw in s.get("text", "") for fw in FILLER_WORDS)
    )
    filler_removal_rate = (filler_cut / filler_total) if filler_total else 0.0

    boundary_hits = sum(
        1 for s in cut_segments if s.get("text", "").strip().endswith(("。", "！", "？", "!", "?"))
    )
    boundary_tendency = (boundary_hits / len(cut_segments)) if cut_segments else 0.0

    typical_cut_examples = [s.get("text", "").strip()[:40] for s in cut_segments[:5]]

    return {
        "keep_ratio": round(max(0.0, min(1.0, keep_ratio)), 2),
        "cut_count": len(cut_segments),
        "avg_cut_duration": round(cut_duration / len(cut_segments), 2) if cut_segments else 0,
        "filler_removal_rate": round(filler_removal_rate, 2),
        "boundary_tendency": round(boundary_tendency, 2),
        "typical_cut_examples": typical_cut_examples,
    }


def detect_subtitle_position(frame) -> str:
    """テロップの位置を検出する"""
    height = frame.shape[0]

    top_region = frame[:int(height * 0.3), :]
    mid_region = frame[int(height * 0.3):int(height * 0.7), :]
    bottom_region = frame[int(height * 0.7):, :]

    def count_bright(region):
        hsv_r = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv_r, np.array([0, 0, 200]), np.array([180, 30, 255]))
        return np.sum(mask > 0)

    top_score = count_bright(top_region)
    mid_score = count_bright(mid_region)
    bottom_score = count_bright(bottom_region)

    if bottom_score >= mid_score and bottom_score >= top_score:
        return "下部"
    elif mid_score >= top_score:
        return "中央"
    else:
        return "上部"


def classify_tempo(avg_cut_interval: float) -> str:
    """カット間隔からテンポを分類する"""
    if avg_cut_interval == 0:
        return "不明"
    elif avg_cut_interval < 2:
        return "超高速"
    elif avg_cut_interval < 4:
        return "速め"
    elif avg_cut_interval < 8:
        return "普通"
    elif avg_cut_interval < 15:
        return "ゆっくり"
    else:
        return "超ゆっくり"


def analyze_brightness(video_bytes: bytes) -> dict:
    """動画の明るさ・カラートーンを分析する"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        sample_interval = max(int(fps * 2), 1)
        frame_count = 0
        brightness_values = []
        color_temps = []

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % sample_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness_values.append(np.mean(gray))
                b, g, r = cv2.split(frame)
                color_temps.append({"r": float(np.mean(r)), "g": float(np.mean(g)), "b": float(np.mean(b))})
            frame_count += 1

        cap.release()
        os.unlink(tmp_path)

        avg_brightness = sum(brightness_values) / len(brightness_values) if brightness_values else 0
        avg_r = sum(c["r"] for c in color_temps) / len(color_temps) if color_temps else 0
        avg_g = sum(c["g"] for c in color_temps) / len(color_temps) if color_temps else 0
        avg_b = sum(c["b"] for c in color_temps) / len(color_temps) if color_temps else 0

        if avg_r > avg_b:
            color_tone = "暖色系"
        elif avg_b > avg_r:
            color_tone = "寒色系"
        else:
            color_tone = "ニュートラル"

        return {
            "avg_brightness": round(avg_brightness, 1),
            "brightness_level": classify_brightness(avg_brightness),
            "color_tone": color_tone,
            "avg_rgb": {"r": round(avg_r), "g": round(avg_g), "b": round(avg_b)},
        }

    except Exception as e:
        print(f"明るさ分析エラー: {e}")
        return {}


def classify_brightness(brightness: float) -> str:
    """明るさを分類する"""
    if brightness > 180:
        return "明るい"
    elif brightness > 120:
        return "普通"
    elif brightness > 60:
        return "暗め"
    else:
        return "かなり暗い"