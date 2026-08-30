"""
pipeline.py  ―  「動画を再現する」の一連の処理を、UI(app.py)から独立した関数として切り出したもの

【なぜ切り出したか】
  今まで app.py の render_reproduce_tab() 内にベタ書きされていた
  「文字起こし→AI編集プラン作成→カット→テロップ→エフェクト→音素材→書き出し」を
  ここに抽出した。これにより、以下の2つの新機能から同じロジックを再利用できる：

    - プレビュー・修正機能：本番レンダリング前にAIの編集プラン（テロップ文言・
      残す/削る・強調）を確認し、手直ししてから最終書き出しに進める
    - バッチ処理：複数の動画に同じスタイル・同じ設定を連続して適用する

処理は2段階に分かれる:
  1. build_edit_plan()    … 文字起こし → AI/ヒューリスティックの編集プラン作成（軽い処理）
  2. render_final_video() … 確認・修正済みのプランをもとに実際の動画を書き出す（重い処理）

【今回のアップデート（精度優先）】
  - 音量・キーワードの盛り上がり検出（features/effects.py）は、AIが使える場合でも
    常に計算し、ai/model.py の generate_edit_plan() へ「参考ヒント」として渡すようにした
    （以前はAI未使用時のフォールバックでのみ計算していた）。
  - AIが highlight_moments を1件も返さなかった場合の保険として、検出結果から
    変換したものを使うようにした（_highlights_from_detected）。
  - render_final_video() で、キープされたセグメントに対して
    features/generate.py の trim_filler_word_edges() を追加適用し、
    冒頭・末尾のフィラー語だけを自動的に切り詰めるようにした。
  - build_edit_plan() が Whisper の精度設定（model_size / beam_size）を
    そのまま受け渡せるようにした（省略時は features/transcribe.py の既定値を使用）。
  - 環境変数 DOPPEL_VISUAL_MODE=on の場合、features/frames.py でハイライト候補付近の
    フレーム画像を抜き出し、ai/model.py の generate_edit_plan() に渡すようにした
    （Claudeが実際の映像も見た上でハイライト・強調を判断できるようにするため）。
    既定はオフ（毎回のAPI呼び出しに画像が乗る＝料金が増えるため）。
"""

from typing import Optional, Dict, Any, Callable, List

from ai.model import generate_edit_plan, is_visual_mode_enabled
from ai.heuristic import build_heuristic_edit_plan

from features.transcribe import transcribe_video
from features.frames import extract_frames_at_timestamps
from features.effects import (
    detect_highlight_moments, apply_color_grade, apply_zoom_effect,
    apply_speed_ramp, auto_reframe,
)
from features.generate import (
    auto_cut_by_style_with_mapping, decide_transition_from_style,
    filter_segments_by_keep_flags, trim_filler_word_edges, generate_with_subtitles, generate_srt,
)
from features.branding import overlay_logo, mix_bgm, insert_se, add_narration
from features.audio_quality import normalize_audio_loudness, apply_noise_gate

# 映像参照モード時、ハイライト候補が1件も無かった場合に均等サンプリングするフレーム数
_VISUAL_FALLBACK_FRAME_COUNT = 6
_VISUAL_MAX_FRAMES = 6


def _highlights_from_detected(detected_highlights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    features/effects.py の detect_highlight_moments()の出力（"timestamp"キー）を、
    レンダリング側が期待する {"start","end","reason"} 形式に変換する。
    AIが highlight_moments を1件も返さなかった場合の保険として使う。
    """
    return [
        {
            "start": h.get("timestamp", 0),
            "end": h.get("end", h.get("timestamp", 0) + 0.5),
            "reason": f"キーワード/音量検出（スコア {h.get('score', 0)}）",
        }
        for h in sorted(detected_highlights, key=lambda x: x.get("score", 0), reverse=True)[:5]
    ]


def build_edit_plan(
    video_bytes: bytes,
    style_data: Optional[dict],
    style_label: str = "",
    reinforcement_text: str = "",
    model_size: Optional[str] = None,
    beam_size: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    文字起こし → 編集プラン作成までを行う（動画の書き出しはまだ行わない・軽い処理）。

    Args:
        video_bytes : 対象動画
        style_data / style_label / reinforcement_text: 従来通り
        model_size  : Whisperのモデルサイズ。省略時は features/transcribe.py の既定
                      （環境変数 WHISPER_MODEL_SIZE。既定 "medium"）を使う
        beam_size   : Whisperのビームサーチ幅。省略時は features/transcribe.py の既定
                      （環境変数 WHISPER_BEAM_SIZE。既定 5）を使う

    Returns:
        {
          "segments": [...],          # Whisperの生セグメント（音声全体をカバー。カットの基準に使う）
          "plan_segments": [...],     # text/keep/emphasis付きの編集プラン（テロップ・残す/削るの元）
          "highlight_moments": [...], # ズーム/スロー/SEの対象になる盛り上がり区間
          "notes": str,                # AI/ヒューリスティックが付けた編集方針の一言
          "ai_used": bool,
        }
        文字起こし自体に失敗した場合は None。
    """
    result = transcribe_video(video_bytes, language="ja", model_size=model_size, beam_size=beam_size)
    if not result:
        return None
    segments = result["segments"]

    # 音量・キーワードの盛り上がり検出は、AIの判断材料としても・フォールバックとしても
    # 使うため、AIが使えるかどうかに関わらず常に計算しておく。
    detected_highlights = detect_highlight_moments(video_bytes, segments)

    # 映像参照モード（DOPPEL_VISUAL_MODE=on）が有効なら、ハイライト候補付近の
    # フレーム画像も抜き出してAIに渡す（毎回コストが増えるため既定はオフ）。
    frame_images = None
    if is_visual_mode_enabled():
        candidate_ts = [h.get("timestamp", 0) for h in detected_highlights[:_VISUAL_MAX_FRAMES]]
        if not candidate_ts and segments:
            # ハイライト候補が無い場合は、動画全体からほぼ均等にサンプリングする
            total_end = segments[-1].get("end", 0)
            if total_end > 0:
                candidate_ts = [
                    total_end * (i + 0.5) / _VISUAL_FALLBACK_FRAME_COUNT
                    for i in range(_VISUAL_FALLBACK_FRAME_COUNT)
                ]
        if candidate_ts:
            frame_images = extract_frames_at_timestamps(video_bytes, candidate_ts, max_frames=_VISUAL_MAX_FRAMES)

    plan = generate_edit_plan(
        segments, style_data, style_label, reinforcement_text,
        highlight_hints=detected_highlights, frame_images=frame_images,
    )
    if plan and plan.get("segments"):
        plan_segments = plan["segments"]
        highlight_moments = plan.get("highlight_moments") or _highlights_from_detected(detected_highlights)
        notes = plan.get("notes", "")
        ai_used = True
    else:
        # AIキー未設定・エラー時のフォールバック（ai/heuristic.py）
        heuristic_plan = build_heuristic_edit_plan(segments, detected_highlights, style_data)
        plan_segments = heuristic_plan["segments"]
        highlight_moments = heuristic_plan["highlight_moments"]
        notes = heuristic_plan.get("notes", "")
        ai_used = False

    return {
        "segments": segments,
        "plan_segments": plan_segments,
        "highlight_moments": highlight_moments,
        "notes": notes,
        "ai_used": ai_used,
    }


def derive_highlights_from_plan(plan_segments: List[Dict[str, Any]], max_highlights: int = 5) -> List[Dict[str, Any]]:
    """
    ユーザーが確認・修正した plan_segments の「強調」フラグ(emphasis=="high")から、
    ハイライト区間（ズーム/スロー/SEの対象）を作り直す。
    プレビュー画面でユーザーが強調テロップを追加/解除した場合に、
    ハイライト演出もその意思に追従させるために使う。
    """
    highlights = [
        {"start": s.get("start", 0), "end": s.get("end", 0), "reason": "テロップの強調指定より"}
        for s in plan_segments if s.get("emphasis") == "high"
    ]
    return highlights[:max_highlights]


def render_final_video(
    video_bytes: bytes,
    edit_plan: Dict[str, Any],
    style: dict,
    render_options: Dict[str, Any],
    # ※ 戻り値は無視するため Any にしている。呼び出し側が
    #   st.progress().progress(...) のように何かを返す関数を渡しても型エラーにならないように、
    #   あえて None 固定にしていない。
    progress_cb: Optional[Callable[[int, str], Any]] = None,
) -> Dict[str, Any]:
    """
    確認・修正済みの編集プランをもとに、実際の動画を書き出す（重い処理）。

    Args:
        video_bytes   : 元の素材動画（複数結合済みならその結合後バイト列）
        edit_plan     : build_edit_plan() の戻り値。plan_segments/highlight_moments は
                         呼び出し側で編集済みでもよい（この関数はコピーを取ってから使うので、
                         渡された edit_plan 自体は書き換えない）
        style         : editor["styles"][style_id]（style_data・brightness_data・labelを含む）
        render_options: {
            "transition": "cut"|"crossfade"|"fade_black"|"auto",
            "highlight_fx": "none"|"zoom"|"slowmo"|"zoom_slowmo",
            "reframe_ratio": "9:16"|"1:1"|"4:5"|None,
            "use_logo": bool, "logo_path": str|None,
            "use_font": bool, "font_path": str|None,
            "bgm_path": str|None,
            "se_path": str|None,
            "narration_path": str|None, "narration_duck_db": float,
            "normalize_audio": bool, "noise_gate": bool,
            "export_preset": dict|None,  # features/export_presets.py の値をそのまま渡せる
        }
        progress_cb   : progress(pct: int, text: str) を呼ぶコールバック（省略可）

    Returns:
        {
          "output": bytes|None,        # 完成動画（失敗時はNone）
          "srt": str,                   # 字幕ファイルの中身
          "sub_segments": list,         # 実際に使われたテロップセグメント（カット後タイムライン基準）
          "highlight_moments": list,    # 実際に使われたハイライト区間（同上）
          "ai_used": bool,
        }
    """
    def _progress(pct: int, text: str):
        if progress_cb:
            progress_cb(pct, text)

    style_data = style.get("style_data", {})
    segments = edit_plan["segments"]
    # 呼び出し元のデータを書き換えないよう、必ずコピーしてから加工する
    sub_segments = [dict(s) for s in edit_plan["plan_segments"]]
    highlight_moments = [dict(h) for h in edit_plan.get("highlight_moments", [])]
    ai_used = edit_plan.get("ai_used", False)

    transition_choice = render_options.get("transition", "cut")
    transition = decide_transition_from_style(style_data) if transition_choice == "auto" else transition_choice

    kept_sub_segments = [s for s in sub_segments if s.get("keep", True)]
    if kept_sub_segments:
        sub_segments = kept_sub_segments

    _progress(8, "学習したテンポ・カットの癖でカット・トランジションを適用中...")
    cut_source_segments = filter_segments_by_keep_flags(segments, sub_segments)
    # 残すと判定された発言でも、冒頭・末尾のフィラー語（「えー」「あの」等）だけは
    # さらに自動でトリムする（word-level timestampsが無いセグメントはそのまま通過する）
    cut_source_segments = trim_filler_word_edges(cut_source_segments)
    cut_video, time_map = auto_cut_by_style_with_mapping(
        video_bytes, cut_source_segments, style_data, transition=transition,
    )
    cut_video = cut_video or video_bytes
    if time_map is None:
        time_map = lambda t: t  # noqa: E731

    # テロップ・ハイライトの時刻を、カットで詰まった後の新しいタイムラインに合わせ直す
    for seg in sub_segments:
        seg["start"] = time_map(seg.get("start", 0))
        seg["end"] = time_map(seg.get("end", 0))
    for h in highlight_moments:
        h["start"] = time_map(h.get("start", 0))
        h["end"] = time_map(h.get("end", 0))

    reframe_ratio = render_options.get("reframe_ratio")
    if reframe_ratio:
        _progress(18, "画面比率を自動リフレーム中...")
        cut_video = auto_reframe(cut_video, reframe_ratio) or cut_video

    _progress(28, "学習したテロップスタイルで焼き込み中...")
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
    if render_options.get("use_font") and render_options.get("font_path"):
        subtitle_style["font_path"] = render_options["font_path"]

    export_settings = render_options.get("export_preset")
    output, _ = generate_with_subtitles(cut_video, styled_segments, subtitle_style, export_settings)
    output = output or cut_video

    _progress(42, "学習した色調に補正中...")
    tone = style.get("brightness_data", {}).get("color_tone", "ニュートラル")
    grade_style = {"暖色系": "warm", "寒色系": "cool"}.get(tone)
    if grade_style:
        output = apply_color_grade(output, grade_style) or output

    se_path = render_options.get("se_path")
    if se_path and highlight_moments:
        _progress(52, "ハイライトシーンに効果音を配置中...")
        se_timestamps = [h["start"] for h in highlight_moments[:5]]
        output = insert_se(output, se_path, se_timestamps) or output

    highlight_fx = render_options.get("highlight_fx", "none")
    if highlight_moments and highlight_fx != "none":
        fx_points = [{"start": h["start"], "end": h["end"]} for h in highlight_moments[:5]]
        if highlight_fx in ("zoom", "zoom_slowmo"):
            _progress(60, "盛り上がりシーンにズーム演出を追加中...")
            output = apply_zoom_effect(output, fx_points) or output
        if highlight_fx in ("slowmo", "zoom_slowmo"):
            _progress(67, "盛り上がりシーンをスローモーションで強調中...")
            output = apply_speed_ramp(output, fx_points, factor=0.6) or output

    if render_options.get("use_logo") and render_options.get("logo_path"):
        _progress(74, "ロゴを焼き込み中...")
        output = overlay_logo(output, render_options["logo_path"]) or output

    if render_options.get("bgm_path"):
        _progress(80, "BGMをミックス中...")
        output = mix_bgm(output, render_options["bgm_path"]) or output

    if render_options.get("narration_path"):
        _progress(85, "ナレーションを合成中...")
        output = add_narration(
            output, render_options["narration_path"],
            duck_db=-abs(render_options.get("narration_duck_db", 15)),
        ) or output

    if render_options.get("normalize_audio"):
        _progress(90, "音量を正規化中...")
        output = normalize_audio_loudness(output) or output

    if render_options.get("noise_gate"):
        _progress(95, "ノイズゲートを適用中...")
        output = apply_noise_gate(output) or output

    _progress(100, "完成！")

    srt = generate_srt(sub_segments)
    return {
        "output": output,
        "srt": srt,
        "sub_segments": sub_segments,
        "highlight_moments": highlight_moments,
        "ai_used": ai_used,
    }