"""
features/se_presets.py  ―  「定番」効果音（SE）のプリセット

【なぜファイルを同梱せずコードで生成しているか】
  ネット上の効果音素材はほとんどが著作権・利用規約付きで、
  このリポジトリに無断で同梱するわけにはいかない。
  そこで、numpyで波形を直接合成することで「著作権フリーな最低限のSE」を
  その場で作れるようにした。プロの効果音ライブラリのようなクオリティではないが、
  「ピコン」「シュッ」等の定番の役割を果たす簡易的な音は十分作れる。

  個性的な・こだわりのある効果音は、引き続き「自分の素材」タブから
  自分でアップロードして使う（本物の効果音ファイルを使いたい場合はそちら）。

使い方:
    from features.se_presets import list_se_preset_names, get_se_preset_bytes
    names = list_se_preset_names()              # ["ピコン（通知音）", ...]
    wav_bytes = get_se_preset_bytes(names[0])    # WAVファイルのバイト列
"""

import io
import wave
from typing import Callable, Dict, List, Optional

import numpy as np

SAMPLE_RATE = 44100


def _note(freq: float, duration: float, sr: int = SAMPLE_RATE,
          attack: float = 0.005, release: float = 0.08, amplitude: float = 0.5) -> np.ndarray:
    """単一のサイン波トーンを、アタック/リリースのエンベロープ付きで生成する"""
    n = max(1, int(sr * duration))
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * freq * t)

    env = np.ones(n)
    a = min(n, max(1, int(attack * sr)))
    r = min(n, max(1, int(release * sr)))
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)

    return tone * env * amplitude


def _to_wav_bytes(samples: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    """numpy配列(-1.0~1.0)をモノラルWAVファイルのバイト列に変換する"""
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def generate_ding() -> bytes:
    """ピコン（通知音） ― 2音の上昇チャイム"""
    sr = SAMPLE_RATE
    d1 = _note(880, 0.12, sr, attack=0.005, release=0.08, amplitude=0.5)
    d2 = _note(1320, 0.18, sr, attack=0.005, release=0.14, amplitude=0.5)
    gap = np.zeros(int(sr * 0.02))
    samples = np.concatenate([d1, gap, d2])
    return _to_wav_bytes(samples)


def generate_impact() -> bytes:
    """ドン（強調音） ― 低音の衝撃音"""
    sr = SAMPLE_RATE
    n = int(sr * 0.25)
    t = np.arange(n) / sr
    low = np.sin(2 * np.pi * 90 * t)
    noise = np.random.uniform(-1, 1, n)
    env = np.exp(-np.linspace(0, 12, n))
    samples = (low * 0.6 + noise * 0.15) * env
    return _to_wav_bytes(samples)


def generate_whoosh() -> bytes:
    """シュッ（トランジション音） ― 山なりのノイズスイープ"""
    sr = SAMPLE_RATE
    dur = 0.35
    n = int(sr * dur)
    noise = np.random.uniform(-1, 1, n)
    sweep_freq = np.linspace(2000, 200, n)
    modulator = np.sin(2 * np.pi * np.cumsum(sweep_freq) / sr)
    env = np.sin(np.linspace(0, np.pi, n))  # 山なりのエンベロープ
    samples = noise * 0.3 * env + modulator * 0.15 * env
    return _to_wav_bytes(samples)


def generate_pop() -> bytes:
    """ポン（ポップ音） ― 短いクリック音"""
    sr = SAMPLE_RATE
    n = int(sr * 0.06)
    noise = np.random.uniform(-1, 1, n)
    env = np.exp(-np.linspace(0, 25, n))
    samples = noise * env * 0.6
    return _to_wav_bytes(samples)


def generate_buzz() -> bytes:
    """ブー（ブザー音） ― 矩形波の警告音"""
    sr = SAMPLE_RATE
    dur = 0.35
    n = int(sr * dur)
    t = np.arange(n) / sr
    tone = np.sign(np.sin(2 * np.pi * 140 * t))
    env = np.ones(n)
    r = int(sr * 0.08)
    env[-r:] = np.linspace(1, 0, r)
    samples = tone * env * 0.35
    return _to_wav_bytes(samples)


def generate_tada() -> bytes:
    """ジャジャン（決定音） ― 3音の上昇アルペジオ"""
    sr = SAMPLE_RATE
    notes = [523.25, 659.25, 783.99]  # C5 - E5 - G5
    parts = [_note(f, 0.12, sr, attack=0.005, release=0.06, amplitude=0.45) for f in notes]
    return _to_wav_bytes(np.concatenate(parts))


SE_PRESETS: Dict[str, Callable[[], bytes]] = {
    "ピコン（通知音）": generate_ding,
    "ドン（強調音）": generate_impact,
    "シュッ（トランジション音）": generate_whoosh,
    "ポン（ポップ音）": generate_pop,
    "ブー（ブザー音）": generate_buzz,
    "ジャジャン（決定音）": generate_tada,
}


def list_se_preset_names() -> List[str]:
    """利用可能な組み込みSEプリセット名の一覧"""
    return list(SE_PRESETS.keys())


def get_se_preset_bytes(name: str) -> Optional[bytes]:
    """プリセット名からWAVバイト列を生成して返す（存在しない名前ならNone）"""
    fn = SE_PRESETS.get(name)
    return fn() if fn else None