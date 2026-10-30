"""Render every stock digital machine through the real voice loop.

    python -m emu.render firmware/path/to/Syntakt_OS1.42.syx

Writes 32-bit mono WAVs to build/renders/ (made from Elektron code: never
commit them) and prints level, pitch, decay and instruction counts.
"""
import os
import sys

import numpy as np

from tools import audiomap as m
from tools import fw, params

from .engine import BLOCK, RATE, Engine, write_wav

OUT = os.path.join("build", "renders")


def test_pool():
    """Slot 0: 1 kHz sine, 0.5 s. Slot 1: 250 Hz sine, 0.5 s. Half scale."""
    t = np.arange(RATE // 2) / RATE
    return {0: np.round(16384 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16),
            1: np.round(16384 * np.sin(2 * np.pi * 250 * t)).astype(np.int16)}


def pitch(x):
    """Strongest spectral peak in Hz, parabolic interpolation."""
    x = x.astype(float)
    if not x.any():
        return 0.0
    s = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    k = int(s[1:-1].argmax()) + 1
    a, b, c = np.log(s[k - 1:k + 2] + 1e-30)
    return (k + 0.5 * (a - c) / (a - 2 * b + c)) * RATE / len(x)


def decay_ms(x, db=-60):
    """Time after which block peaks stay below db relative to the overall peak."""
    peaks = np.abs(x.astype(float)).reshape(-1, BLOCK).max(axis=1)
    if peaks.max() == 0:
        return 0.0
    live = np.nonzero(peaks > peaks.max() * 10 ** (db / 20))[0]
    return (live[-1] + 1) * BLOCK * 1000 / RATE


def budget(image, descs, mtype, blocks=300, pool=None):
    """Instructions per voice-loop block with this machine on all 8 tracks, all trigged."""
    e = Engine(image)
    if pool:
        e.load_pool(pool)
    for t in range(m.N_VOICES):
        e.set_defaults(t, mtype, descs)
        e.set_note(t, 60)
    counts = []
    for b in range(blocks):
        before = e.mc.insns
        e.block(0xFF if b == 0 else 0)
        counts.append(e.mc.insns - before)
    return max(counts), sum(counts) / len(counts), e.mc.emac.overflows


def render_one(image, descs, mtype, seconds=1.0, note=60, pool=None):
    e = Engine(image)
    if pool:
        e.load_pool(pool)
    for t in range(m.N_VOICES):
        e.set_defaults(t, mtype, descs)
        e.set_note(t, note)
    return e.render(int(seconds * RATE / BLOCK), trig=0x01)[0]


def main(path):
    img = fw.load(path)
    image, descs = img.section(7), params.machines(img.section(3), img.version)
    os.makedirs(OUT, exist_ok=True)
    pool = test_pool()
    print("%-11s %4s  %9s  %9s  %8s  %10s %10s %9s" % (
        "machine", "type", "peak dBFS", "peak Hz", "-60dB ms", "max insn/b", "mean", "per voice"))
    rows = []
    for engine, mtype in enumerate(m.TYPE_OF_ENGINE):
        name = m.ENGINES[engine]
        x = render_one(image, descs, mtype, pool=pool if mtype == 44 else None)
        write_wav(os.path.join(OUT, name.replace(" ", "_") + ".wav"), x)
        mx, mean, ovf = budget(image, descs, mtype, pool=pool if mtype == 44 else None)
        peak = np.abs(x.astype(float)).max()
        db = 20 * np.log10(peak / 2 ** 31) if peak else float("-inf")
        rows.append((name, mx))
        print("%-11s %4d  %9.1f  %9.1f  %8.0f  %10d %10.0f %9.0f%s" % (
            name, mtype, db, pitch(x), decay_ms(x), mx, mean, mx / m.N_VOICES,
            "  EMAC OVERFLOWS %d" % ovf if ovf else ""))
    name, mx = max(rows, key=lambda r: r[1])
    print("\nheaviest: %s, %d instructions per block for 8 voices, %d per voice" % (
        name, mx, mx // m.N_VOICES))


if __name__ == "__main__":
    main(sys.argv[1])
