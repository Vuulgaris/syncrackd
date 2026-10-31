"""The grain image (engine/sampler.h, GRAIN): the slscrub image with a stretch that holds together."""

import shutil

import numpy as np
import pytest

import test_hits as H
import test_pagerec as P
import test_slim as S
import test_stretch as X
from stereo_rig import Rig
from test_fade import LENGTH, LOOP, SAMPLE, START
from test_quick import ST, Folded
from tools import build_engine, build_main
from tools import audiomap as m

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

N = 24000
HITS = (1200, 6000, 10800, 15600, 20400)


@pytest.fixture(scope="module")
def before(official):
    return build_engine.patched_image(official.section(7), slscrub=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), grain=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def low(n=N):
    t = np.arange(n)
    y = 9000 * np.sin(2 * np.pi * 70 * t / 48000) + 4500 * np.sin(2 * np.pi * 140 * t / 48000 + 1)
    return np.round(y * np.minimum(1, np.minimum(t, n - t) / 1000)).astype(np.int16)


def bursts(n=N):
    y = np.zeros(n)
    for h in HITS:
        t = np.arange(n - h)
        y[h:] += 20000 * np.sin(2 * np.pi * 900 * t / 48000) * np.exp(-t / 400.0)
    return np.round(y).astype(np.int16)


def run(built, x, speed, blocks, word=None, settle=0):
    """Track 0 on x once, stretched at `speed`; `settle` blocks of the scan first, so it has gone over the slot. -> its
    output, and its place at each block's end.
    """
    e = P.engine(built, pool={0: x, 1: x})
    for slot, v in {SAMPLE: H.PK.knob_of(0), P.MODE: 0, P.TUNE: 64, LENGTH: 127, START: 0, LOOP: 0,
                    24: X.sent24(speed) if word is None else word}.items():
        e.set_slot(0, slot, v)
    e.set_note(0, 60)
    for _ in range(settle):  # the scan's blocks: the harness runs the voices only
        e.mc.call(built[1]["hits_block"])
    st = e.voice(0) + ST
    out, place = [], []
    for b in range(blocks):
        out.append(e.block(1 if b == 0 else 0, 0)[0])
        place.append(e.mc.r32(st + 8) / 4096)
    return np.concatenate(out).astype(np.int64), np.array(place), e


def rms(y):
    return np.sqrt(np.mean(np.asarray(y, float) ** 2)) + 1e-9


@pytest.mark.parametrize("speed", [32, 96])
def test_a_low_tone_stays_steady(before, engine, speed):
    ripple = []
    for built in (before, engine):
        n = int(N * 2 ** ((64 - speed) / 32))  # how long the note is, stretched
        y, place, _ = run(built, low(), speed, n // 32 + 8)
        mid = y[n // 6:n * 5 // 6]
        env = np.array([rms(mid[i:i + 686]) for i in range(0, len(mid) - 686, 343)])  # 686: 70 Hz's period
        ripple.append(env.std() / env.mean())
    print("70 + 140 Hz at SPD %d: the level's spread %.3f before, %.3f now" % (speed, *ripple))
    assert ripple[1] < 0.04 and ripple[1] < ripple[0] / 3


def attacks(y, place):
    """Each burst as heard: (what came before its time against what follows, the most its level rises again after its
    peak, frames from its time to its peak).
    """
    out = []
    for h in HITS:
        b = int(np.argmax(place >= h))  # the block its place reaches it in
        t = 32 * b + int(32 * (h - place[b - 1]) / (place[b] - place[b - 1]))
        env = np.array([rms(y[i:i + 64]) for i in range(t - 32, t + 3000, 32)])
        p = int(np.argmax(env[:12]))
        rise = max(env[i] / env[p:i].min() for i in range(p + 1, len(env)))
        out.append((rms(y[t - 480:t - 48]) / rms(y[t:t + 480]), rise, 32 * p - 32))
    return out


def test_bursts_stretched_half_come_once_and_on_time(before, engine):
    x = bursts()
    _, _, e = run(engine, x, 32, 1, settle=600)
    h = e.mc.read(0x44070000, 20)
    assert int.from_bytes(h[12:16], "big") == N and h[19] == len(HITS)  # the scan's list: through the slot, five
    for built, fixed in ((before, False), (engine, True)):
        y, place, _ = run(built, x, 32, (2 * N) // 32 + 40, settle=600)
        a = attacks(y, place)
        print(("before" if not fixed else "now   ") + ": " + "  ".join("early %.2f again x%.2f at %+d" % v for v in a))
        if fixed:
            assert all(pre < 0.05 and rise < 1.25 and -32 <= at <= 96 for pre, rise, at in a)
        else:
            assert max(pre for pre, _, _ in a) > 0.2 or max(rise for _, rise, _ in a) > 1.5  # the fault, as it was


def test_at_its_own_speed_and_pitch_it_is_still_the_note(engine):
    for x in (X.tone(), bursts()):
        plain, _, _ = run(engine, x, 64, (3 * N) // 32, word=0, settle=600)
        stretched, _, _ = run(engine, x, 64, (3 * N) // 32, settle=600)
        a, b = plain[128:N - 2000], stretched[128:N - 2000]
        err = np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(a ** 2))
        print("own speed: error %.5f of the note's level" % err)
        assert err < 0.01


def test_what_eight_stretched_stereo_voices_cost(before, engine, official):
    factory = S.factory.__wrapped__(official)
    worst = []
    for image in (before, engine):
        r = Rig(image[0])
        rng = np.random.default_rng(11)
        pool = {k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)}
        pool[3] = bursts(9000)
        r.load_pool(pool)
        S.T.samplers(r, factory, loop=1)
        for t in range(8):
            r.set_slot(t, SAMPLE, 64 + t % 4)
            r.set_slot(t, START, 0)
            r.set_slot(t, LENGTH, 127)
            r.set_slot(t, 24, X.sent24(40 + 9 * t))
            r.set_note(t, 55.25 + (t % 4) * 3.1)
        r.block(0, 0)
        cost = []
        for b in range(500):
            r.block(0xff if b % 90 == 0 else 0, 0)
            cost.append(sum(r.cost.values()))
        worst.append(max(cost))
    print("eight stretched stereo voices, the heaviest block: before %d, now %d (SWARM's eight 117,348)" % tuple(worst))
    assert worst[1] < 117348


@pytest.mark.parametrize("word", [0, 0x80 / 256], ids=["CHRO", "SLCE"])
def test_a_note_not_stretched_is_the_slscrub_images(before, engine, word):
    x = bursts()
    a, _, _ = run(before, x, 64, 400, word=word)
    b, _, _ = run(engine, x, 64, 400, word=word)
    assert np.array_equal(a, b) and a.any()


def test_section_7_fits_and_the_main_cpu_is_the_lock_images(engine, official):
    assert official.section(7).__len__() + m.FAR_BYTES_GRAIN + 5 <= 393216
    assert build_main.patched_image(official.section(3), xfade=57)[0] == build_main.patched_image(official.section(3), xfade=54)[0]
