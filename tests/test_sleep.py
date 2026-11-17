"""The sleep image (engine/sampler.h, SLEEP): the handrec image's audio CPU with stock's voices resting when silent."""

import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_stereo as T
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from tools import audiomap as m
from tools import build, build_engine, params

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER, SWARM = 44, 38
KIT = [2, 0, 38, 5, 44, 44, 6, 7]  # stock machines beside two samplers; type 6 dies away in a third of a second
FLOOR = 1 << 11  # LETGO_QUIET
SKIP, OK = m.SLEEP_STATE + 8, m.SLEEP_STATE + 24
TIMER = m.TIMER1_COUNT
LOOP_RTS = 0x400044e0  # the voice loop's rts: before the keep box's step
KEEP = 0xc10


@pytest.fixture(scope="module")
def was(official):
    return build_engine.patched_image(official.section(7), handrec=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), sleep=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


def rig(image, factory, descs, machines=(SAMPLER,) * 8, pool=None):
    """Eight tracks at factory settings: stock machines, and samplers on stereo pitched loops."""
    r = Rig(image[0])
    rng = np.random.default_rng(11)
    r.load_pool(pool or {k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
    T.samplers(r, factory, loop=1)
    for t, mt in enumerate(machines):
        if mt != SAMPLER:
            r.set_machine(t, mt)
            for p in descs[mt]:
                r.set_slot(t, p.slot, p.default)
            r.set_note(t, 48 + 5 * t)
            continue
        r.set_slot(t, SAMPLE, 64 + t % 4)
        r.set_slot(t, START, 0)
        r.set_slot(t, LENGTH, 127)
        r.set_slot(t, 24, 0)
        r.set_note(t, 55.25 + (t % 4) * 3.1)
    r.block(0, 0)
    return r


def run(r, blocks, trigs=()):
    """-> (the left of every block, blocks x 8 x 32; the instructions of each; the voices not run in each)"""
    out, cost, skip = [], [], []
    for b in range(blocks):
        out.append(np.asarray(r.block(0xff if b in trigs else 0, 0)[2]))
        cost.append(sum(r.cost.values()))
        skip.append(r.mc.r32(SKIP))
    return np.stack(out), np.array(cost), np.array(skip)


def test_after_a_start_with_nothing_trigged_it_is_under_half(was, engine, factory, descs):
    a = run(rig(was, factory, descs, KIT), 120)[1]
    _, b, skip = run(rig(engine, factory, descs, KIT), 120)
    print("nothing trigged since the start: %d an interrupt, now %d (SWARM's eight %d)" % (a[-64:].mean(), b[-64:].mean(), T.SWARM))
    assert a[-64:].mean() > 88000 and b[-64:].mean() < 0.5 * a[-64:].mean()
    assert all(bin(s).count("1") >= 7 for s in skip[40:])  # every voice rests but the one looked at


@pytest.fixture(scope="module")
def kit(was, engine, factory, descs):
    """The kit trigged at blocks 0 and 800 on both images."""
    return [run(rig(im, factory, descs, KIT), 1000, trigs=(0, 800)) for im in (was, engine)]


def test_a_voice_that_sounds_is_as_it_was_to_the_bit(kit):
    (a, ca, _), (b, cb, skip) = kit
    for t in (1, 2, 3, 4, 5, 7):
        assert np.array_equal(a[:, t], b[:, t]) and a[:, t].any()
        assert not (skip[1:] >> t & 1).any()
    assert np.array_equal(a[:300], b[:300]) and not (skip[1:300] & ~1).any()  # track 1's machine makes no sound as it is set: it rests
    more = cb - ca
    print("the two passes: %d more at the most in the first 30 blocks (silent voices looked at whole), %d on a block with seven sounding"
          % (more[1:30].max(), more[100:300].max()))
    assert 0 < more[1:30].max() < 1300 and more[100:300].max() < 900


def test_a_quiet_stock_voice_rests_and_its_trig_wakes_it(kit):
    (a, ca, _), (b, cb, skip) = kit
    rest = skip >> 6 & 1
    first = int(np.argmax(rest))
    print("type 6 rests from block %d; an interrupt then %d, was %d" % (first, cb[first + 40:790].mean(), ca[first + 40:790].mean()))
    assert 300 < first < 700 and rest[first:800].mean() > 0.9
    quiet = np.abs(b[first:800, 6][rest[first:800] == 1]).max()  # not run: what the stages make of nothing (the filter's
    print("its buffer while it rests: %d at the most, was %d (the floor %d)" % (quiet, np.abs(a[first:800, 6]).max(), FLOOR))
    assert quiet < FLOOR  # tail and its own least numbers, as on stock), under the floor
    assert np.abs(a[first - 32:800, 6]).max() < FLOOR  # as it was, from 32 blocks before
    assert ca[first + 40:790].mean() - cb[first + 40:790].mean() > 6000
    assert not rest[800:900].any()  # the trig's own block on
    rms = [np.sqrt((x[800:900, 6].astype(np.float64) ** 2).mean()) for x in (a, b)]
    assert abs(rms[1] / rms[0] - 1) < 0.03 and rms[0] > 1e6  # the note again, the engine's phase its own


def test_a_samplers_voice_is_never_rested(was, engine, factory, descs):
    rng = np.random.default_rng(3)
    x = rng.integers(-30000, 30000, 9000).astype(np.int16)
    x[2000:7000] = 0  # five thousand frames of nothing in the middle
    pool = {k: x for k in range(8)}
    a, _, _ = run(rig(was, factory, descs, pool=pool), 400, trigs=(0,))
    b, _, skip = run(rig(engine, factory, descs, pool=pool), 400, trigs=(0,))
    assert np.array_equal(a, b) and np.abs(a[:60]).max() > 100 * FLOOR and np.abs(a[:, 0]).max(axis=1)[60:300].min() < np.abs(a[:60, 0]).max() // 1000 and np.abs(a[300:]).max() > 100 * FLOOR
    assert not skip[2:].any()


def test_a_sound_that_comes_back_with_no_trig_is_heard(engine, factory, descs):
    """SWARM held and sounding, said by hand to have been silent: it is looked at within 16 blocks, heard, and run again.
    """
    r = rig(engine, factory, descs, [SWARM] * 8)
    out, skip = [], []
    for b in range(160):
        if b == 100:
            r.mc.write(m.SLEEP_STATE + 2, b"\xff")
        out.append(np.abs(np.asarray(r.block(0x04 if b == 0 else 0, 0)[2])[2]).max())
        skip.append(r.mc.r32(SKIP) >> 2 & 1)
    rested = sum(skip[100:])
    print("a sounding voice said to be silent: not run for %d blocks, then run again" % rested)
    assert min(out[50:100]) > 100 * FLOOR and not any(skip[1:100])
    assert 0 < rested <= 15 and skip[100] == 1 and not any(skip[100 + rested:])
    assert min(out[100 + rested:]) > 100 * FLOOR  # (while not run, the filter rings on by itself)


class Timed(Rig):
    """A Rig whose timer reads `late` from the voice loop's end on, and nothing before it."""
    def __init__(self, image):
        super().__init__(image)
        self.late = 0
        for a in (LOOP_RTS, m.ISR_AMP_CALL):
            self.mc.uc.hook_add(UC_HOOK_CODE, self._late, None, begin=a, end=a)
        self.mc.uc.ctl_flush_tb()

    def _late(self, uc, address, size, user):
        self.mc.w32(TIMER, self.late)

    def block(self, trig=0, release=0, feed=None):
        self.mc.w32(TIMER, 0)
        return super().block(trig, release, feed)


def ask(r, n, slot=0x8000 | 20):
    """A request of the keep box. -> is it answered by the block's end."""
    r.mc.write(KEEP, n.to_bytes(2, "big") + slot.to_bytes(2, "big") + (0).to_bytes(4, "big"))
    r.block(0, 0)
    return r.mc.r32(KEEP + 8) == n


def gone_over(r):
    return [r.mc.r32(0x44070000 + 512 * k + 12) for k in range(8)]


def test_the_save_copy_and_the_scan_wait_for_a_light_block(engine, factory, descs, monkeypatch):
    monkeypatch.setattr("test_sleep.Rig", Timed)
    rng = np.random.default_rng(5)
    r = rig(engine, factory, descs, pool={k: rng.integers(-30000, 30000, 60000).astype(np.int16) for k in range(8)})
    for b in range(20):  # the timer still, as on every other test: all light
        before = gone_over(r)
        assert ask(r, b + 1) and r.mc.r32(OK) == 1 and gone_over(r) != before
    r.late = 50000  # blocks longer than they have been
    before = gone_over(r)
    assert not ask(r, 21) and r.mc.r32(OK) == 0 and gone_over(r) == before
    waited = 1
    while not ask(r, 21):  # the same request till it is answered: the mean comes up
        waited += 1
        assert waited < 70
    print("a block of 50,000 after blocks of nothing: the keep box answers after %d blocks" % waited)
    assert waited > 30 and r.mc.r32(OK) == 1
    r.late = 80000  # heavier again: left
    assert not ask(r, 22) and r.mc.r32(OK) == 0
    r.late = 40000  # a lighter one: taken at once
    before = gone_over(r)
    assert ask(r, 22) and r.mc.r32(OK) == 1 and gone_over(r) != before


def test_the_image(official_path, official, was, engine):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=84, prof=True)[2]
    old = build.build(official_path, log=quiet, xfade=83, prof=True)[2]
    assert new.section(3) == old.section(3) and new.section(7) == engine[0] and old.section(7) == was[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert new.container.by_id(sid).stored == official.container.by_id(sid).stored
    a, b = was[0], engine[0]
    far = len(official.section(7)) - m.FAR
    caves = {}
    for more in (m.CAVES, m.REC_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.PITCH_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES, m.TIMED_CAVES,
                 m.CROSS_CAVES, m.SRR_CAVES, m.HITS_CAVES, m.SCAN_CAVES, m.TRAP_CAVES, m.BACK_CAVES, m.GRAIN_CAVES):
        caves.update(more)
    told = [(lo + far, hi + far) if lo >= m.FAR else (m.off(lo), m.off(hi)) for lo, hi in caves.values()]  # our own runs: the
    # new code in e, f, g, k, m and w, and a call's address where a routine of ours moved
    told += [(m.off(a0), m.off(a0) + n) for a0, n in ((m.SLEEP_GATE, 6), (m.ISR_VOICE_LOOP_CALL + 2, 4), (m.ISR_AMP_CALL + 2, 4))]
    assert len(a) == len(b)
    other = [k for k in range(len(a)) if a[k] != b[k]]
    assert other and all(any(lo <= k < hi for lo, hi in told) for k in other)
