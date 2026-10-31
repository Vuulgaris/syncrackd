"""The letgo image (engine/sampler.h, LETGO): the tune image with two things on the audio CPU."""
import shutil

import numpy as np
import pytest

import test_norm as N
import test_pack as PK
import test_pagerec as P
import test_slim as S
from emu.engine import BLOCK
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_multi import recorder, taken, write
from test_quick import Folded
from tools import build, build_engine
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

QUIET = 1 << 11
FLOOR = 21474  # -100 dB of full scale, 2^31


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


@pytest.fixture(scope="module")
def trap(official):
    return build_engine.patched_image(official.section(7), trap=True)


@pytest.fixture(scope="module")
def letgo(official):
    return build_engine.patched_image(official.section(7), letgo=True)


# The right channel let go

def scene(image, factory, seed, blocks=330):
    """Eight stereo one-shots of 1,200 frames, the four stages' knobs anywhere, trigged together every 110 blocks; track
    0's sample all left. -> a block's (the left after the last stage, the right as the main CPU takes it, the count,
    the mask).
    """
    r = Rig(image)
    rng = np.random.default_rng(seed)
    pool = {k: rng.integers(-20000, 20000, 1200).astype(np.int16) for k in range(8)}
    pool[1] = np.zeros(1200, np.int16)
    r.load_pool(pool)
    S.T.samplers(r, factory, loop=0)
    r.stage_knobs(rng)
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 4)
        r.set_slot(t, START, 0)
        r.set_slot(t, LENGTH, 127)
        r.set_note(t, 57 + t)
    r.block(0, 0)
    out = []
    for b in range(blocks):
        _, _, left = r.block(0xff if b % 110 == 1 else 0, 0)
        mask = r.mask()
        right = np.array([r.right(t) if mask >> t & 1 else left[t] for t in range(8)])
        out.append((left.copy(), right, sum(r.cost.values()), mask))
    return out


@pytest.fixture(scope="module")
def scenes(trap, letgo, official):
    factory = S.factory.__wrapped__(official)
    return {seed: (scene(trap[0], factory, seed), scene(letgo[0], factory, seed)) for seed in (5, 6)}


@pytest.mark.parametrize("seed", [5, 6])
def test_the_left_is_the_trap_images_and_the_right_within_minus_100_db(scenes, seed):
    was, now = scenes[seed]
    worst = max(int(np.abs(a[1].astype(np.int64) - b[1]).max()) for a, b in zip(was, now))
    loud = max(int(np.abs(a[1]).max()) for a in was)
    print("seed %d: the right's largest difference %d, its loudest %d" % (seed, worst, loud))
    assert all(np.array_equal(a[0], b[0]) for a, b in zip(was, now))
    assert worst <= FLOOR and loud > 1 << 27


@pytest.mark.parametrize("seed", [5, 6])
def test_a_silent_stereo_track_leaves_the_mask_and_comes_back_with_its_next_note(scenes, seed):
    was, now = scenes[seed]
    assert all(a[3] == 0xff for a in was[5:])  # the trap image: every track, ever after
    masks = [b[3] for b in now]
    print("seed %d, the mask by block: %s" % (seed, " ".join("%d:%02x" % (b, masks[b]) for b in range(0, 110, 10))))
    assert masks[3] == 0xff and not masks[100] & 1 and bin(masks[100]).count("1") <= 3 and masks[113] == 0xff


@pytest.mark.parametrize("seed", [5, 6])
def test_each_track_let_go_costs_less(scenes, seed):
    was, now = scenes[seed]
    rows = [(a[2] - b[2], 8 - bin(b[3]).count("1"), b[3]) for a, b in zip(was[60:109], now[60:109])]
    playing = max(b[2] - a[2] for a, b in zip(was[3:20], now[3:20]))
    print("seed %d: saved a block, by tracks let go: %s; playing, at most %d more" % (seed, sorted(set(rows))[-6:], playing))
    assert all(saved >= 2000 * gone + (14000 if not mask else 0) for saved, gone, mask in rows) and playing <= 200


# The normalizer

def norm_engine(built, places):
    e = recorder(built, places, 0)
    for t in places:
        e.set_slot(t, 24, 0x52 + 7 / 256)
    return e


def back_to_back(built):
    """Two mono takes in single slots side by side, the second begun as the first ends. -> the first's slot, frames, its
    take as it was, and what is in its slot after.
    """
    e = norm_engine(built, {4: 40, 5: 39})
    k, n, (left, _) = N.take(e, built, 4, N.sine(24, 2000, 11))
    k2, _, _ = N.take(e, built, 5, N.sine(10, 2000, 12), count=200)
    N.settle(e, built, n // N.STEP + 4)
    assert k2 == k - 1
    return k, n, left, taken(e, k, n)


def test_a_mono_take_beside_one_being_scaled_stopped_it_on_the_trap_image(trap):
    k, n, left, got = back_to_back(trap)
    assert not np.array_equal(got, N.scaled(left, N.loudest(left)))
    assert not np.array_equal(got, left)  # part done


def test_now_it_is_scaled_whole(letgo):
    k, n, left, got = back_to_back(letgo)
    assert np.array_equal(got, N.scaled(left, N.loudest(left))) and N.loudest(got) > N.TOP * 0.99


def slot63(built):
    e = norm_engine(built, {4: 64})
    e.mc.write(PK.buf(0), bytes.fromhex(fw.sx("9f7cc770a4cd8734")))
    e.mc.write(N.KEPT + 4 * 62, (1).to_bytes(4, "big"))
    k, n, (left, _) = N.take(e, built, 4, N.sine(8, 900, 13))
    N.settle(e, built, n // N.STEP + 3)
    assert k == 63 and np.array_equal(taken(e, k, n), N.scaled(left, N.loudest(left)))
    return e.mc.r32(PK.buf(0)), e.mc.r32(N.KEPT + 4 * 62)


def test_a_mono_take_in_slot_63_wrote_slot_0s_first_long_on_the_trap_image(trap):
    assert slot63(trap)[0] == 0


def test_now_slot_0_and_the_neighbours_mark_are_left(letgo):
    assert slot63(letgo) == (0x12345678, 1)


def cut_short(built):
    """A stereo take on track 3 cut short by the track's next trig, into another place. -> the first's slot, frames, both
    sides as taken, and both after.
    """
    e = norm_engine(built, {3: 7})
    a = N.sine(14, 700, 14)
    N.tick(e, built, 1 << 3)
    for b, x in enumerate(a):
        write(e, 100 + b, {3: x})
        N.tick(e, built)
    k = e.mc.read(e.voice(3) + N.ST + PK.S_RK, 1)[0]
    n = P.slot_entry(e, k)[0]
    was = taken(e, k, n).copy(), taken(e, k + 1, n).copy()
    e.set_slot(3, SAMPLE, PK.knob_of(11))
    N.take(e, built, 3, N.sine(6, 700, 15), count=200)
    N.settle(e, built, n // N.STEP + 4)
    assert e.mc.read(e.voice(3) + N.ST + PK.S_RK, 1)[0] != k
    return was, (taken(e, k, n), taken(e, k + 1, n))


def test_a_take_cut_short_by_the_next_was_never_scaled_on_the_trap_image(trap):
    was, now = cut_short(trap)
    assert np.array_equal(was[0], now[0]) and np.array_equal(was[1], now[1])


def test_now_it_is_scaled(letgo):
    was, now = cut_short(letgo)
    peak = N.loudest(*was)
    assert np.array_equal(now[0], N.scaled(was[0], peak)) and np.array_equal(now[1], N.scaled(was[1], peak))


# The image

def test_the_image(official_path, official, letgo):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=69)[2]
    was = build.build(official_path, log=quiet, xfade=68)[2]
    assert new.section(3) == was.section(3) and new.section(7) != was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert new.container.by_id(sid).stored == official.container.by_id(sid).stored
