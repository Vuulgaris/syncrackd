"""the eight image (engine/sampler.h, EIGHT): the slim image with a pitched frame summed from eight frames, not twelve (six was "too much filtering").

Against the slim image's engine: at a sample's own pitch the sound is the same to
the bit; pitched, the engine's frames are the table of eight's own sum (tools/sinctable.py, interp), two channels and one;
what it costs; and what it gives up, by the table alone, against the table of twelve. Emulation only."""

import shutil

import numpy as np
import pytest

import test_pagerec as P
from test_quick import Folded
from test_slim import CYCLE, render
from tools import build_engine, params, sinctable

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def slim(stock):
    return build_engine.patched_image(stock, slim=True)


@pytest.fixture(scope="module")
def eight(stock):
    return build_engine.patched_image(stock, eight=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def test_the_table_is_eight_frames_wide_and_adds_up_to_one():
    for row in sinctable.rows8():
        assert len(row) == 16 and not any(row[:4] + row[12:]) and sum(row) == sinctable.ONE


@pytest.mark.parametrize("kw", [dict(), dict(mono=True), dict(back=True, loop=2)])
def test_at_its_own_pitch_the_sound_is_the_slim_images(slim, eight, factory, kw):
    _, was, _, _ = render(slim[0], factory, 60, 2 * CYCLE, own=True, start=30, length=40, **kw)
    _, now, _, _ = render(eight[0], factory, 60, 2 * CYCLE, own=True, start=30, length=40, **kw)
    assert np.array_equal(was, now)


@pytest.mark.parametrize("kw", [dict(), dict(mono=True)])
def test_pitched_it_is_another_sound_near_the_slim_images(slim, eight, factory, kw):
    """Noise pitched: not the same, and within what twelve against six makes of noise (most of it the top octave)."""
    _, was, _, _ = render(slim[0], factory, 55.25, CYCLE, start=30, length=40, **kw)
    _, now, _, _ = render(eight[0], factory, 55.25, CYCLE, start=30, length=40, **kw)
    d = (now - was).astype(float)
    ratio = np.sqrt((d ** 2).mean() / (was.astype(float) ** 2).mean())
    print("%s: the difference %.1f dB under the sound" % (kw, -20 * np.log10(ratio)))
    assert 0 < ratio < 0.3


def test_what_it_gives_up_by_the_table():
    """A sine pitched up a fifth and down a fifth, each table: what is left besides it, in dB under it."""
    out = []
    for f0 in (1000, 5000, 10000, 15000):
        for ratio in (1.5, 2 ** (-7 / 12)):
            n = 1 << 11
            x = np.round(20000 * np.sin(2 * np.pi * f0 / 48000 * np.arange(n + 64))).astype(np.int64)
            res = []
            for table in (sinctable.rows12(), sinctable.rows8()):
                pos = np.arange(n // 2) * ratio + 16
                y = np.array([sinctable.interp(x, int(p), int((p % 1) * 4096), table) for p in pos], float) / sinctable.ONE
                want = 20000 * np.sin(2 * np.pi * f0 / 48000 * pos)
                res.append(20 * np.log10(np.sqrt(((y - want * (np.dot(y, want) / np.dot(want, want))) ** 2).mean()) / 14142 + 1e-12))
            out.append((f0, round(ratio, 3), round(res[0], 1), round(res[1], 1)))
    print("sine, ratio, twelve, eight (dB of what is not the sine):", out)


def test_what_it_costs(slim, eight, factory):
    for name, kw in (("stereo", {}), ("mono", dict(mono=True))):
        was, *_ = render(slim[0], factory, 55.25, 2 * CYCLE, start=30, length=40, **kw)
        now, *_ = render(eight[0], factory, 55.25, 2 * CYCLE, start=30, length=40, **kw)
        b, less = CYCLE, was - now
        print("%s: steady %d, the heaviest %d -> %d, least saved %d" % (name, int(np.median(less[b + 60:b + 80])), was[b:].max(), now[b:].max(), less[b:].min()))
        assert now[b:].max() < was[b:].max() and less[b:].min() > 0
