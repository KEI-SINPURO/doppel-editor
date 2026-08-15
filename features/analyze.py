"""
features/analyze.py  ―  動画スタイル分析

過去に投稿した「編集済み動画」を解析して、
  - カットの頻度・平均間隔（テンポ）
  - テロップの色・位置
  - 明るさ・カラートーン（暖色系／寒色系）
を数値として抽出する。ここで得られた値が、STEP2（新しい動画への自動再現）で
そのまま使われる「学習済みスタイル」の中身になる。
"""

import cv2
import numpy as np
import tempfile
import os
from typing import Optional


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

        # カットのリズム分析
        cut_intervals = [cut_points[i + 1] - cut_points[i] for i in range(len(cut_points) - 1)]
        avg_cut_interval = sum(cut_intervals) / len(cut_intervals) if cut_intervals else 0

        # テロップカラー集計
        white_count = sum(1 for r in subtitle_regions if r["color"] == "白")
        yellow_count = sum(1 for r in subtitle_regions if r["color"] == "黄色")
        dominant_color = "white" if white_count >= yellow_count else "yellow"

        # テロップ位置集計
        positions = [r["position"] for r in subtitle_regions]
        dominant_position = max(set(positions), key=positions.count) if positions else "下部"

        return {
            "duration": round(duration, 1),
            "total_cuts": len(cut_points),
            "avg_cut_interval": round(avg_cut_interval, 2),
            "cut_points": cut_points,
            "dominant_color": dominant_color,
            "dominant_position": dominant_position,
            "subtitle_count": len(subtitle_regions),
            "subtitle_regions": subtitle_regions,
            "tempo": classify_tempo(avg_cut_interval),
        }

    except Exception as e:
        print(f"スタイル分析エラー: {e}")
        return None


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
