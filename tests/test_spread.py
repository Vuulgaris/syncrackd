"""The spread image (engine/sampler.h, SPREAD): the stsw image with the stretch's look in slices, and smaller."""

import shutil

import numpy as np
import pytest

import test_grain as GR
import test_pagerec as P
import test_slim as S
import test_stretch as X
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_quick import Folded
from tools import build, build_engine, build_main

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def slscrub(official):
    return build_engine.patched_image(official.section(7), slscrub=True)


@pytest.fixture(scope="module")
def grain(official):
    return build_engine.patched_image(official.section(7), grain=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), spread=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def blocks(image, factory, stretched):
    """Eight stereo pitched tracks looping, the first `stretched` of them stretched, trigged together every 90 blocks. ->
    each block's count, past the first few.
    """
    r = Rig(image[0])
    rng = np.random.default_rng(11)
    pool = {k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)}
    pool[3] = GR.bursts(9000)
    r.load_pool(pool)
    S.T.samplers(r, factory, loop=1)
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 4)
        r.set_slot(t, START, 0)
        r.set_slot(t, LENGTH, 127)
        r.set_slot(t, 24, X.sent24(40 + 9 * t) if t < stretched else 0)
        r.set_note(t, 55.25 + (t % 4) * 3.1)
    r.block(0, 0)
    cost = []
    for b in range(500):
        r.block(0xff if b % 90 == 0 else 0, 0)
        cost.append(sum(r.cost.values()))
    return np.array(cost[5:])


@pytest.mark.parametrize("stretched", [1, 8])
def test_the_peak_is_down(slscrub, grain, engine, official, stretched):
    factory = S.factory.__wrapped__(official)
    old, was, now = (blocks(i, factory, stretched) for i in (slscrub, grain, engine))
    p = lambda c: (int(np.percentile(c, 99)), int(c.max()))
    print("%d stretched, the heaviest 1%% and the heaviest: slscrub %d %d, grain %d %d, now %d %d (SWARM's eight 117,348)"
          % (stretched, *p(old), *p(was), *p(now)))
    assert p(now)[0] < p(was)[0] - 3000 and p(now)[1] < p(was)[1] and p(now)[1] < 117348


@pytest.mark.parametrize("speed", [32, 96])
def test_a_low_tone_is_still_steadier_than_before_the_grain_image(slscrub, engine, speed):
    spread = []
    for built in (slscrub, engine):
        n = int(GR.N * 2 ** ((64 - speed) / 32))
        y, _, _ = GR.run(built, GR.low(), speed, n // 32 + 8)
        mid = y[n // 6:n * 5 // 6]
        env = np.array([GR.rms(mid[i:i + 686]) for i in range(0, len(mid) - 686, 343)])
        spread.append(env.std() / env.mean())
    print("70 + 140 Hz at SPD %d: the level's spread %.3f before the grain image, %.3f now" % (speed, *spread))
    assert spread[1] < spread[0] / 2


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
def test_a_note_not_stretched_is_the_grain_images(grain, engine, word):
    a, _, _ = GR.run(grain, GR.bursts(), 64, 400, word=word)
    b, _, _ = GR.run(engine, GR.bursts(), 64, 400, word=word)
    assert np.array_equal(a, b) and a.any()


def test_the_image(official_path, official, engine):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=59, prof=True)
    assert built.section(7) == engine[0]
    assert built.section(3) == build.build(official_path, log=quiet, xfade=58, prof=True)[2].section(3)
    print("spread image", __import__("hashlib").sha256(raw).hexdigest())
