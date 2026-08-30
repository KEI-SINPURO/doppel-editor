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

【今回のアップデート（精度優先の再現度アップ）】
  以前の analyze_editing_patterns() は、raw側の各発言を「edited側の文字起こし全体
  （1本の長い文字列）」に対して緩く一致するかどうかだけで keep/cut を判定しており、
  ①どの発言がedited側のどこに対応するか（順序・位置）、②発言まるごとではなく
  冒頭・末尾の一部（フィラー語）だけがトリムされているケース、を学習できなかった。

  そこで、次の2段構えに変更した：
    Tier 2（従来と同じ・堅牢な判定）: keep/cut 自体の判定は、引き続き
      「edited側の文字起こし全体に対する緩い一致」で行う。これはWhisperの
      セグメント分割がraw/edited間で必ずしも一致しない（同じ発言でも区切られ方が
      違う）ことに強いため、判定の主軸として維持する。
    Tier 1（新規・補助的な学習）: raw側の各セグメントを、edited側の「個別セグメント」
      に貪欲法で対応付ける（_align_segments_pairwise）。この対応付けから、
        - position_bias  : 動画内の位置（冒頭/中盤/終盤）ごとの残す割合の違い
        - trim_stats     : 単語(トークン)レベルのタイムスタンプ（features/transcribe.py で
                           word_timestamps=True にして取得）が使える場合、「セグメントは
                           残しつつ、冒頭・末尾のフィラー語だけをわずかに削る」傾向を検出
      を追加で学習する。これらは ai/model.py のプロンプトに渡され、Claudeが
      「本当に不要な発言だけをカットし、フィラー語混じりというだけの理由で
      発言ごと消さない」よう、より繊細な判断をするための材料になる。

  なお、これらは「対応付けができた場合の補助的な統計」であり、対応付けに失敗しても
  （Noneや0件になっても）Tier 2 のkeep/cut判定自体には影響しない＝安全側に倒れる設計。

【注意】
  raw/edited比較はタイムコードでの厳密なアライメントは行わず、
  文字起こしテキストの近似マッチング（difflib）で「残された／カットされた」を
  推定する簡易的な手法です。完全に正確ではありませんが、
  「傾向を掴んでAIへのヒントにする」という目的には十分な精度を狙っています。
  特にWhisperの日本語の単語区切りは、英語のような分かち書きと違い、
  1トークンが1文字～数文字程度になることが多いため、trim_statsの
  「トークン数」はあくまで目安（大きいほど多く削られている）として扱ってください。
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


# ============================================================
# raw/edited比較 ― 内部ヘルパー（Tier 1: 補助的なセグメント対応付け）
# ============================================================

def _align_segments_pairwise(raw_segments: list, edited_texts: list, min_ratio: float = 0.5) -> list:
    """
    raw_segments の各要素を、最も文面が似ているedited_texts側のインデックスに
    貪欲法で対応付ける（1つのedited側セグメントは1回しか使わない）。

    keep/cut 自体の判定には使わない（そちらは引き続き _is_kept 相当の、
    edited側全文に対する緩い一致で行う）。この対応付けは、並び順や動画内の
    位置に関する「補助的な学習」（_compute_position_bias, _compute_trim_stats）
    にのみ使用する。Whisperのセグメント分割がraw/edited間で食い違っていると
    対応付けに失敗しやすいが、失敗時はNoneを返すだけで安全側に倒れる。

    Returns:
        raw_segments と同じ長さのリスト。各要素は対応するedited側のインデックス、
        対応が見つからなければ None。
    """
    used_idx = set()
    result = []
    for rseg in raw_segments:
        rtext = (rseg.get("text") or "").strip()
        if not rtext:
            result.append(None)
            continue
        best_idx, best_ratio = None, 0.0
        for ei, etext in enumerate(edited_texts):
            if ei in used_idx or not etext:
                continue
            ratio = difflib.SequenceMatcher(None, rtext, etext).ratio()
            if ratio > best_ratio:
                best_ratio, best_idx = ratio, ei
        if best_idx is not None and best_ratio >= min_ratio:
            result.append(best_idx)
            used_idx.add(best_idx)
        else:
            result.append(None)
    return result


def _compute_position_bias(raw_segments: list, kept_flags: list) -> dict:
    """
    動画のタイムライン上の位置（冒頭20%／中盤60%／終盤20%）ごとに、
    どれだけ残されたか（keep_ratio相当）を分けて集計する。
    「冒頭の雑談・挨拶は削るが、終盤の締めは基本残す」といった、
    位置に応じたカットの癖を学習するために使う。

    Returns:
        {"冒頭": float|None, "中盤": float|None, "終盤": float|None}
        （該当区間に発言が無ければNone）
    """
    if not raw_segments:
        return {}
    total_start = raw_segments[0].get("start", 0)
    total_end = raw_segments[-1].get("end", total_start)
    total_duration = max(total_end - total_start, 0.01)

    buckets = {"冒頭": (0.0, 0.2), "中盤": (0.2, 0.8), "終盤": (0.8, 1.001)}
    result = {}
    for label, (lo, hi) in buckets.items():
        idxs = [
            i for i, s in enumerate(raw_segments)
            if lo <= (s.get("start", 0) - total_start) / total_duration < hi
        ]
        if not idxs:
            result[label] = None
            continue
        kept = sum(1 for i in idxs if kept_flags[i])
        result[label] = round(kept / len(idxs), 2)
    return result


def _compute_trim_stats(raw_segments: list, edited_segments: list, kept_flags: list, alignment: list) -> Optional[dict]:
    """
    「残された」と判定されたセグメントについて、raw側とedited側それぞれの
    単語(トークン)レベルタイムスタンプ（features/transcribe.py で
    word_timestamps=True にして取得。無ければこの関数は何もしない）を比較し、
    冒頭・末尾でどれだけの単語数が削られているか（＝フィラー語トリムの目安）を集計する。

    Returns:
        {"avg_trim_start_tokens": float, "avg_trim_end_tokens": float, "sample_size": int}
        比較可能なペアが1件も無ければ None（＝この統計は使わない、で安全に無視される）。
    """
    samples_start, samples_end = [], []
    for ri, ei in enumerate(alignment):
        if ei is None or not kept_flags[ri] or ei >= len(edited_segments):
            continue
        rwords = raw_segments[ri].get("words") or []
        ewords = edited_segments[ei].get("words") or []
        if not rwords or not ewords:
            continue
        rtok = [(w.get("word") or "").strip() for w in rwords]
        etok = [(w.get("word") or "").strip() for w in ewords]
        matcher = difflib.SequenceMatcher(None, rtok, etok)
        match = matcher.find_longest_match(0, len(rtok), 0, len(etok))
        if match.size == 0:
            continue
        samples_start.append(match.a)
        samples_end.append(len(rtok) - (match.a + match.size))

    if not samples_start:
        return None

    return {
        "avg_trim_start_tokens": round(sum(samples_start) / len(samples_start), 1),
        "avg_trim_end_tokens": round(sum(samples_end) / len(samples_end), 1),
        "sample_size": len(samples_start),
    }


def analyze_editing_patterns(raw_segments: list, edited_segments: list) -> dict:
    """
    編集前(raw)素材と編集後(edited)動画、それぞれの文字起こしセグメントを比較し、
    「編集者がどういう基準で発言をカットしているか」の癖を学習する。

    アプローチ（完全一致のタイムライン整列は行わず、テキストベースの近似）:
      raw の各発言セグメントについて、その内容が edited 側の文字起こし全体の
      中にどれだけ含まれているかを difflib で調べ、「残された」か「カットされた」かを判定する
      （この主判定はTier 2。詳細はモジュールdocstring参照）。
      加えて、個別セグメント同士の対応付け（Tier 1）から、位置別の残す割合や
      フィラー語のトリム傾向も補助的に学習する。

    Args:
        raw_segments   : 編集前素材のWhisperセグメント [{"start","end","text",("words")}, ...]
        edited_segments: 編集後完成動画のWhisperセグメント（同上）

    Returns:
        {
          "keep_ratio": float,             # 素材のうち時間ベースで残された割合(0~1)
          "cut_count": int,                # カットされたセグメント数
          "avg_cut_duration": float,       # カットされた発言1つあたりの平均秒数
          "filler_removal_rate": float,    # フィラー語を含む発言のうち、カットされた割合
          "boundary_tendency": float,      # カットが句読点（文の区切り）で終わる発言だった割合
          "typical_cut_examples": [str],   # 実際にカットされた発言の例（最大5件・各40文字まで）
          "reordering_rate": float,        # NEW: 発言の並び替え傾向の目安(0~1・UI表示用の参考情報)
          "position_bias": dict,           # NEW: 冒頭/中盤/終盤ごとの残す割合
          "trim_stats": dict|None,         # NEW: フィラー語のトリム傾向（word-levelデータが無ければNone）
        }
        raw_segments が空の場合は {} を返す。
    """
    if not raw_segments:
        return {}

    edited_text_joined = "".join(s.get("text", "").strip() for s in edited_segments) if edited_segments else ""
    edited_texts = [s.get("text", "").strip() for s in edited_segments] if edited_segments else []

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

    # ---- Tier 1: 補助的なセグメント対応付け（並び替え・位置・トリムの学習） ----
    alignment = _align_segments_pairwise(raw_segments, edited_texts)

    matched_edited_indices = [ei for ei in alignment if ei is not None]
    reordering_rate = 0.0
    if len(matched_edited_indices) >= 2:
        inversions = sum(
            1 for a in range(len(matched_edited_indices) - 1)
            if matched_edited_indices[a] > matched_edited_indices[a + 1]
        )
        reordering_rate = round(inversions / (len(matched_edited_indices) - 1), 2)

    position_bias = _compute_position_bias(raw_segments, kept_flags)
    trim_stats = _compute_trim_stats(raw_segments, edited_segments, kept_flags, alignment)

    return {
        "keep_ratio": round(max(0.0, min(1.0, keep_ratio)), 2),
        "cut_count": len(cut_segments),
        "avg_cut_duration": round(cut_duration / len(cut_segments), 2) if cut_segments else 0,
        "filler_removal_rate": round(filler_removal_rate, 2),
        "boundary_tendency": round(boundary_tendency, 2),
        "typical_cut_examples": typical_cut_examples,
        "reordering_rate": reordering_rate,
        "position_bias": position_bias,
        "trim_stats": trim_stats,
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