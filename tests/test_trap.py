"""The trap image (engine/sampler.h, TRAP): the spread image with a stretched note for less."""

import hashlib
import shutil

import numpy as np
import pytest

import test_grain as GR
import test_pagerec as P
import test_slim as S
import test_spread as SP
import test_stretch as X
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def spread(official):
    return build_engine.patched_image(official.section(7), spread=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), trap=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


@pytest.mark.parametrize("stretched", [1, 8])
def test_the_peak_is_down(spread, engine, official, stretched):
    factory = S.factory.__wrapped__(official)
    was, now = (SP.blocks(i, factory, stretched) for i in (spread, engine))
    p = lambda c: (int(np.percentile(c, 99)), int(c.max()), int(np.median(c)))
    print("%d stretched, the heaviest 1%%, the heaviest, the middle: spread %d %d %d, now %d %d %d (SWARM's eight 117,348)"
          % (stretched, *p(was), *p(now)))
    assert p(now)[0] < p(was)[0] - (8000 if stretched == 8 else 500) and p(now)[1] < p(was)[1]


@pytest.mark.parametrize("speed", [32, 96])
def test_a_low_tone_is_no_less_steady(spread, engine, speed):
    out = []
    for built in (spread, engine):
        n = int(GR.N * 2 ** ((64 - speed) / 32))
        y, _, _ = GR.run(built, GR.low(), speed, n // 32 + 8)
        mid = y[n // 6:n * 5 // 6]
        env = np.array([GR.rms(mid[i:i + 686]) for i in range(0, len(mid) - 686, 343)])
        out.append(env.std() / env.mean())
    print("70 + 140 Hz at SPD %d: the level's spread %.3f on the spread image, %.3f now" % (speed, *out))
    assert out[1] < max(out[0] * 1.2, 0.01)


def test_bursts_still_come_once_and_on_time(engine):
    y, place, _ = GR.run(engine, GR.bursts(), 32, (2 * GR.N) // 32 + 40, settle=600)
    a = GR.attacks(y, place)
    print("  ".join("early %.2f at %+d" % (pre, at) for pre, _, at in a))
    assert all(pre < 0.05 and -32 <= at <= 96 for pre, _, at in a)


def test_at_its_own_speed_and_pitch_it_is_still_the_note(engine):
    for x in (X.tone(), GR.bursts()):
        plain, _, _ = GR.run(engine, x, 64, (3 * GR.N) // 32, word=0, settle=600)
        stretched, _, _ = GR.run(engine, x, 64, (3 * GR.N) // 32, settle=600)
        a, b = plain[128:GR.N - 2000], stretched[128:GR.N - 2000]
        err = np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(a ** 2))
        print("own speed: error %.5f of the note's level" % err)
        assert err < 0.01


@pytest.mark.parametrize("word", [0, 0x80 / 256], ids=["CHRO", "SLCE"])
def test_a_note_not_stretched_is_the_spread_images(spread, engine, word):
    a, _, _ = GR.run(spread, GR.bursts(), 64, 400, word=word)
    b, _, _ = GR.run(engine, GR.bursts(), 64, 400, word=word)
    assert np.array_equal(a, b) and a.any()


def test_the_image(official_path, official, engine, spread):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=65, prof=True)
    was = build.build(official_path, log=quiet, xfade=64, prof=True)[2]
    assert built.section(3) == was.section(3)  # the mirror image's main CPU
    a7, b7, n7 = built.section(7), spread[0], len(official.section(7))
    assert a7 == engine[0] and len(a7) == len(b7)
    runs = [r for n, v in vars(m).items() if n.endswith("CAVES") for r in v.values() if r[1] <= m.BASE + n7]
    table = [t + 4 * m.ALLOY_ENGINE for t in (m.UPDATE_TABLE, m.RENDER_TABLE)]
    stray = [hex(m.BASE + k) for k in range(n7) if a7[k] != b7[k]
             and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs + [(t, t + 4) for t in table])]
    assert stray == []  # our runs (CY ALLOY's among them) and engine 2's entries
    lo, hi = m.TRAP_CAVES["al"]
    assert a7[m.off(lo):m.off(hi)] != b7[m.off(lo):m.off(hi)]
    syms = engine[1]  # a track on CY ALLOY is handed SWARM's stand-ins
    assert [m.u32(a7, t) for t in table] == [syms["swarm_update"], syms["swarm_render"]]
    print("trap image", hashlib.sha256(raw).hexdigest())
