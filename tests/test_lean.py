"""The stereo image's third build: the same sound for less of a block (LEAN), and the sum of twelve (TWELVE).

The unit, through the time image, 2026-10-11: eight stereo samples at their own pitch read 72 hundredths of a
block, the same pitched 99 and "peaks ovewr a 100 at times", seven SY SWARMs and a sampler 81. So the second
build's eight pitched stereo tracks, which matched stock's heaviest interrupt by count, are past it in time.

LEAN changes no frame:
  - a voice's level and gain went through two of stock's routines a channel. They are one pass for both
    channels here (voice_out), held to those two routines themselves, bit for bit, on whatever a voice holds;
  - the right channels' copies move more longs a turn (longs, send, swap), held to what they have to move.
The engine as a whole is still held to the reference model and to the pitch image's engine by tests/test_quick.py
and to stock's stages by tests/test_stereo.py: all of that runs on this build.

TWELVE is another sound, a little: a frame between two is summed from twelve frames, not sixteen. It is held to
the same model with the table of twelve, and what it gives up is measured. It is built as its own file beside
the other (the time12 image) for a person to hear and to read: nothing is decided here.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_pagerec as P
import test_pitch as TP
from emu import sampler_ref as ref
from emu.engine import BLOCK
from test_fade import CASES, DECAY, LENGTH, LOOP, MODE, SAMPLE, START, TUNE, tail
from test_live import SCRIPTS, hold, model, play, same
from test_quick import Folded
from test_stereo import SWARM, whole
from tools import audiomap as m
from tools import build_engine, params, sinctable

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STOCK_AMP, STOCK_MIX = 0x400045a0, 0x400049f4
SCRATCH_L, SCRATCH_R = 0x80008c60, 0x80008d84
OUT, RIGHT, LAYERS = 0x44070000, 0x44070100, 0x44070200          # free memory for a test's two buffers and stock's two indexes
V = dict(gain=8, gain2=12, cur=24, cur2=28, trig=52, start=56, target=976, level=980, attack=1000)
FULL = 0x80000000                                                 # a level: all of it. And "no attack"


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def lean(stock):
    return build_engine.patched_image(stock, stereo=True)


@pytest.fixture(scope="module")
def twelve(stock):
    return build_engine.patched_image(stock, stereo=True, twelve=True)


@pytest.fixture(scope="module")
def pitch(stock):
    return build_engine.patched_image(stock, pitch=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


# ---- a voice's level and gain: one pass, stock's two routines to the bit -------------------------------------

class Voice:
    """A voice's memory and Twinshot's two scratch buffers, set by the test; stock's two routines and ours run on them."""

    def __init__(self, built):
        self.e = P.engine(built)
        self.mc, self.syms = self.e.mc, built[1]
        self.at = self.e.voice(3)
        self.mc.write(LAYERS, (0).to_bytes(4, "big") + (1).to_bytes(4, "big"))

    def set(self, fields, left, right):
        mc = self.mc
        for k, v in fields.items():
            mc.w32(self.at + V[k], v)
        mc.write(SCRATCH_L, np.asarray(left).astype(">i4").tobytes())
        mc.write(SCRATCH_R, np.asarray(right).astype(">i4").tobytes())
        mc.write(OUT, b"\x55" * 128)
        mc.write(RIGHT, b"\x55" * 128)
        mc.emac.macsr = 0xa0

    def got(self):
        mc = self.mc
        buf = lambda at: np.frombuffer(mc.read(at, 128), dtype=">i4").astype(np.int64)
        return buf(OUT), buf(RIGHT), {k: mc.r32(self.at + o) for k, o in V.items()}, list(mc.emac.acc), mc.emac.macsr & 0xf0

    def stock(self, fields, left, right, stereo):
        """As the sampler called them up to the second build: a channel at a time, the right from where the left began."""
        self.set(fields, left, right)
        mc, v = self.mc, self.at
        level, cur = mc.r32(v + V["level"]), mc.r32(v + V["cur"])
        mc.call(STOCK_AMP, SCRATCH_L, v)
        mc.call(STOCK_MIX, SCRATCH_L, SCRATCH_L, OUT, LAYERS, v)
        if stereo:
            mc.w32(v + V["level"], level)
            mc.w32(v + V["cur"], cur)
            mc.call(STOCK_AMP, SCRATCH_R, v)
            mc.call(STOCK_MIX, SCRATCH_R, SCRATCH_R, RIGHT, LAYERS, v)
        return self.got()

    def ours(self, fields, left, right, stereo):
        self.set(fields, left, right)
        self.mc.call(self.syms["voice_out"], self.at, OUT, RIGHT if stereo else 0)
        return self.got()


def agree(v, fields, left, right, stereo):
    a, b = v.stock(fields, left, right, stereo), v.ours(fields, left, right, stereo)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]), fields
    assert a[2] == b[2] and a[3] == b[3] == [0, 0, 0, 0] and a[4] == b[4] == 0xa0, fields
    assert stereo or set(b[1]) == {0x55555555}
    return b


def frames(rng, loud=False):
    x = rng.integers(-(1 << 31), 1 << 31, 32)
    if loud:
        x[rng.integers(0, 32, 6)] = rng.choice([-(1 << 31), (1 << 31) - 1, 0], 6)
    return x


@pytest.mark.parametrize("stereo", [True, False])
def test_a_steady_level_and_gain_are_stocks_to_the_bit(lean, stereo):
    """A note that is holding: the level at all of it or part, the gain a sample's or a take's or anything."""
    v, rng = Voice(lean), np.random.default_rng(1)
    for level in (FULL, 0xc0000000, 0xe1234567, 0, 0x90000001):
        for gain in (0x7fffffff, 0x40000000, 0, 0x12345678):
            f = dict(gain=gain, cur=gain, gain2=0, cur2=0, trig=0, start=0, target=level, level=level, attack=0x7000)
            out, right, *_ = agree(v, f, frames(rng, True), frames(rng, True), stereo)
            assert (level and gain) == 0 or out.any()


@pytest.mark.parametrize("seed", range(40))
def test_any_ramp_of_either_is_stocks_to_the_bit(lean, seed):
    """Where the level and the gain are, where they are going, a trig in the block, a note starting in it with an
    attack or without: whatever a voice holds, both channels come out as stock's two routines make them, the voice
    is left as they leave it, and the accumulators as they leave them."""
    rng = np.random.default_rng(seed)
    v = Voice(lean)
    for n in range(12):
        f = dict(gain=int(rng.integers(0, 1 << 32)), cur=int(rng.integers(0, 1 << 32)), gain2=0, cur2=0,
                 trig=int(rng.integers(0, 2)), start=int(rng.integers(0, 2)),
                 target=int(rng.choice([FULL, 0, int(rng.integers(0, 1 << 32))])), level=int(rng.integers(0, 1 << 32)),
                 attack=int(rng.choice([FULL, 0x1000, int(rng.integers(0, 1 << 32))])))
        if n % 3 == 0:                                              # as the sampler has them: a gain that is where it is going
            f["cur"] = f["gain"] = int(rng.choice([0x7fffffff, 0x40000000]))
        agree(v, f, frames(rng, n % 2 == 0), frames(rng, n % 4 == 0), stereo=bool(n % 5))


@pytest.mark.parametrize("stereo", [True, False])
def test_with_twinshots_second_layer_not_at_nothing_stocks_own_two_are_called(lean, stereo):
    """The sampler keeps that layer's gain at 0, and where it has got to at 0 from a note's start. Before a
    voice's first note it may hold what another machine left: then nothing is assumed."""
    v, rng = Voice(lean), np.random.default_rng(9)
    seen = []
    v.mc.uc.hook_add(1 << 2, lambda uc, a, s, u: seen.append(a), None, STOCK_MIX, STOCK_MIX)       # UC_HOOK_CODE
    v.mc.uc.ctl_flush_tb()
    for gain2, cur2 in ((0, 0x1234), (0x40000000, 0), (0x7fffffff, 0x10000000)):
        f = dict(gain=0x7fffffff, cur=0x20000000, gain2=gain2, cur2=cur2, trig=0, start=1, target=0xa0000000, level=0xf0000000, attack=FULL)
        del seen[:]
        v.ours(f, frames(rng), frames(rng), stereo)
        assert len(seen) == (2 if stereo else 1)
        agree(v, f, frames(rng), frames(rng), stereo)
    del seen[:]
    v.ours(dict(gain2=0, cur2=0), frames(rng), frames(rng), stereo)
    assert not seen


def test_it_writes_the_two_buffers_and_the_voices_own_two_places(lean):
    v, rng = Voice(lean), np.random.default_rng(4)
    v.set(dict(gain=0x7fffffff, cur=0x60000000, gain2=0, cur2=0, trig=0, start=0, target=0x90000000, level=0xc0000000, attack=0), frames(rng), frames(rng))
    regs = [0x1000 * k + 0x77 for k in range(2, 8)] + [0x44070800 + 4 * k for k in range(2, 7)]
    for k, value in zip(list(range(2, 8)) + list(range(10, 15)), regs):
        v.mc.set_reg(k, value)
    wrote = []
    h = v.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, at, s, val, u: wrote.append((at, s)))
    v.mc.uc.ctl_flush_tb()
    v.mc.call(v.syms["voice_out"], v.at, OUT, RIGHT)
    v.mc.uc.hook_del(h)
    ok = [(OUT, OUT + 128), (RIGHT, RIGHT + 128), (v.at + V["level"], v.at + V["level"] + 4), (v.at + V["cur"], v.at + V["cur"] + 4),
          (m.STACK_TOP - 0x200, m.STACK_TOP)]
    assert wrote and all(any(a <= w and w + s <= b for a, b in ok) for w, s in wrote)
    assert [v.mc.reg(k) for k in list(range(2, 8)) + list(range(10, 15))] == regs


# ---- the three that move longs ---------------------------------------------------------------------------------

def test_longs_moves_n_longs_and_no_more(lean):
    e = P.engine(lean)
    mc, rng = e.mc, np.random.default_rng(2)
    for n in list(range(1, 14)) + [24, 40, 41, 43]:
        src = bytes(rng.integers(0, 256, 4 * n + 8, dtype=np.uint8))
        mc.write(OUT, src)
        mc.write(RIGHT, b"\xee" * (4 * n + 8))
        mc.call(lean[1]["longs"], RIGHT, OUT, n)
        assert mc.read(RIGHT, 4 * n + 8) == src[:4 * n] + b"\xee" * 8 and mc.read(OUT, 4 * n + 8) == src


def test_swap_exchanges_n_longs_with_the_copy_of_their_shape(lean):
    """Stock's memory of the two filters and its copy in free memory, 0xc4048000 on: the three stretches the right
    channels' pass exchanges, and any other length."""
    e = P.engine(lean)
    mc, rng = e.mc, np.random.default_rng(3)
    shadow = lambda a: a + m.R_SHADOW & 0xffffffff
    regs = [0x2000 * k + 0x33 for k in range(2, 8)] + [0x44070900 + 4 * k for k in range(2, 7)]
    for a, n in list(m.FILTER_STATE and [(lo, (hi - lo) // 4) for lo, hi in m.FILTER_STATE]) + [(0x80008740, k) for k in (1, 5, 6, 7, 11, 12, 13)]:
        mine, theirs = (bytes(rng.integers(0, 256, 4 * n + 8, dtype=np.uint8)) for _ in range(2))
        mc.write(a, mine)
        mc.write(shadow(a), theirs)
        for k, value in zip(list(range(2, 8)) + list(range(10, 15)), regs):
            mc.set_reg(k, value)
        mc.call(lean[1]["swap"], a, n)
        assert mc.read(a, 4 * n + 8) == theirs[:4 * n] + mine[4 * n:] and mc.read(shadow(a), 4 * n + 8) == mine[:4 * n] + theirs[4 * n:]
        assert [mc.reg(k) for k in list(range(2, 8)) + list(range(10, 15))] == regs
    assert sorted((hi - lo) // 4 for lo, hi in m.FILTER_STATE) == [16, 20, 112]


@pytest.mark.parametrize("mask", [0, 1, 0x80, 0x10, 0xff, 0xa5, 0x5a, 0x7e])
def test_send_puts_the_masks_tracks_in_their_halves_of_the_window_and_touches_nothing_else(lean, mask):
    e = P.engine(lean)
    mc, rng = e.mc, np.random.default_rng(mask)
    waiting = rng.integers(-(1 << 31), 1 << 31, (8, 32))
    mc.write(m.STASH, waiting.astype(">i4").tobytes())
    mc.write(0, b"\xee" * 0x1000)
    wrote = []
    h = mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, at, s, val, u: wrote.append((at, s)))
    mc.uc.ctl_flush_tb()
    mc.call(lean[1]["send"], mask)
    mc.uc.hook_del(h)
    want = bytearray(b"\xee" * 0x1000)
    for t in range(8):
        if mask >> t & 1:
            for half in (0, 1):
                at = m.rw_half(2 * t + half)
                want[at:at + 64] = waiting[t][16 * half:16 * half + 16].astype(">i4").tobytes()
    assert mc.read(0, 0x1000) == bytes(want)
    assert all(s == 4 and w < 0x1000 for w, s in wrote if w < m.STACK_TOP - 0x400) and len([w for w, s in wrote if w < 0x1000]) == 32 * bin(mask).count("1")


# ---- a fade, and a note's start: the blocks that stood out ----------------------------------------------------
#
# 
# The bench has it: a block is not always what a steady one is. The block a note starts in wrote
# out the frames around its slot's ends a word at a time with a question for each, and every frame of a fade
# was made alone, at more than twice the work of a frame in a run. Eight tracks trigged on one step do both
# together, and the meter's P holds the most of ten seconds.

def test_a_run_under_a_fade_is_the_frames_one_at_a_time(lean):
    """fade_run against the two routines it is a run of, faded and fade_move, which the engine still has for the
    frame at a wall: any gain, a fade in to its end and past it, a fade out to nothing and on, one channel or two."""
    e = P.engine(lean)
    mc, syms, rng = e.mc, lean[1], np.random.default_rng(6)
    note = OUT + 0x400
    for trial in range(60):
        g, step = int(rng.integers(0, 4097)), int(rng.choice([64, -32, 64, -32, 7, -500, 0]))
        n, end = int(rng.integers(0, 20)), int(rng.integers(20, 33))
        stereo = bool(trial % 3)
        left, right = frames(rng, True), frames(rng, True)
        mc.write(note, bytes(88))
        mc.write(note + 60, g.to_bytes(2, "big") + (step & 0xffff).to_bytes(2, "big"))
        mc.write(OUT, np.asarray(left).astype(">i4").tobytes())
        mc.write(RIGHT, np.asarray(right).astype(">i4").tobytes())
        mc.call(syms["fade_run"], note, OUT, RIGHT if stereo else 0, n, end)
        got_l = np.frombuffer(mc.read(OUT, 128), dtype=">i4").astype(np.int64)
        got_r = np.frombuffer(mc.read(RIGHT, 128), dtype=">i4").astype(np.int64)
        got_state = mc.read(note + 60, 4)
        # the same frames one at a time, by the engine's own two routines
        want_l, want_r = [int(v) for v in left], [int(v) for v in right]
        mc.write(note + 60, g.to_bytes(2, "big") + (step & 0xffff).to_bytes(2, "big"))
        for k in range(n, end):
            now = int.from_bytes(mc.read(note + 60, 2), "big", signed=True)
            for buf in (want_l, want_r) if stereo else (want_l,):
                v = mc.call(syms["faded"], (buf[k] >> 4) & 0xffffffff, now)
                buf[k] = ((v - (1 << 32) if v & 0x80000000 else v) << 4 + 32) >> 32 if False else (((v << 4) & 0xffffffff) ^ 0x80000000) - 0x80000000
            if int.from_bytes(mc.read(note + 62, 2), "big", signed=True):
                mc.call(syms["fade_move"], note)
            else:                                                   # (a step of 0 is not a fade: play does not ask for a run of it)
                pass
        assert list(got_l) == want_l and list(got_r) == want_r, (trial, g, step, n, end)
        if step:
            assert got_state == mc.read(note + 60, 4)


@pytest.mark.parametrize("n", [1, 2, 3, 7, 8, 14, 15, 16, 17, 22, 23, 44, 45, 46, 300])
@pytest.mark.parametrize("voice", [0, 5])
def test_a_notes_start_writes_out_the_frames_around_its_slots_ends_as_it_did(lean, n, voice):
    """The same 45 words a side as the pitch image's routine (tests/test_pitch.py), for a slot of any length:
    frames -7 to 14, then n - 15 to n + 7, the end frame standing in for what is past it."""
    rng = np.random.default_rng(n)
    left, right = rng.integers(-30000, 30000, n).astype(np.int16), rng.integers(-30000, 30000, n).astype(np.int16)
    e = P.engine(lean)
    mc = e.mc
    at = m.HQ_PADS + m.HQ_PAD_BYTES * voice
    st = e.voice(voice) + 1712
    want = lambda x: [int(x[min(max(j, 0), n - 1)]) for j in list(range(-7, 15)) + list(range(n - 15, n + 8))]
    a, b = OUT + 0x1000, OUT + 0x2000                           # the two slots, with room for the longest
    for stereo in (True, False):
        mc.write(a, left.astype(">i2").tobytes())
        mc.write(b, right.astype(">i2").tobytes())
        mc.write(st, bytes(88))
        mc.w32(st, a), mc.w32(st + 4, b if stereo else 0), mc.w32(st + 12, n)
        mc.write(m.HQ_PADS, b"\xa5" * (8 * m.HQ_PAD_BYTES))
        mc.call(lean[1]["hq_pads"], st)
        sides = 2 if stereo else 1
        got = np.frombuffer(mc.read(at, 2 * m.HQ_PAD_SIDE * sides), ">i2").reshape(sides, m.HQ_PAD_SIDE)
        assert list(got[0]) == want(left) and (not stereo or list(got[1]) == want(right))
        assert mc.r32(st + 72) == at
        rest = mc.read(m.HQ_PADS, 8 * m.HQ_PAD_BYTES)
        assert rest[:at - m.HQ_PADS] == b"\xa5" * (at - m.HQ_PADS) and set(rest[at - m.HQ_PADS + 2 * m.HQ_PAD_SIDE * sides:]) == {0xa5}


def blocks_of(image, factory, note, **knobs):
    """Eight stereo tracks trigged together every twelve blocks, once the first notes are past: -> instructions of a
    steady block, of the block the trig is in, of the one the notes start in, and of the one after."""
    from stereo_rig import Rig
    r = Rig(image)
    rng = np.random.default_rng(11)
    r.load_pool({k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
    from test_stereo import samplers
    samplers(r, factory, loop=knobs.get("loop", 0), mode=1)
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 3)
        r.set_slot(t, START, knobs.get("start", 0))
        r.set_slot(t, LENGTH, knobs.get("length", 127))
        r.set_note(t, note)
    r.block(0, 0)
    costs = []
    for b in range(28):
        r.block(0xff if b % 12 == 0 else 0, 0)
        costs.append(sum(r.cost.values()))
    return costs[22], costs[24], costs[25], costs[26]


def test_the_blocks_that_stood_out_stand_out_less(lean, twelve, factory):
    """Instructions. With the first step of this build a note's first block was 14,800 over a steady one for eight
    stereo tracks, and with a cut start, where a fade in begins, 21,000 and then 6,300 more: it is 5,300, and 11,300
    and then 6,300. (The very first note of a voice after a start is 8,900 more again, once: stock resets the voice
    and the table is made.)"""
    steady, trig, start, after = blocks_of(lean[0], factory, 55.25)
    assert abs(steady - 108720) < 100 and 3000 < trig - steady < 3700 and 4800 < start - steady < 5800 and abs(after - steady) < 100
    steady, trig, start, after = blocks_of(lean[0], factory, 55.25, start=20, length=60)
    assert 10500 < start - steady < 12000 and 5800 < after - steady < 6800
    steady, trig, start, after = blocks_of(twelve[0], factory, 55.25)
    assert abs(steady - 102570) < 100 and 4800 < start - steady < 5800
    steady, trig, start, after = blocks_of(lean[0], factory, 60)
    assert abs(steady - 76650) < 100 and 5500 < start - steady < 6600


# ---- what it costs, and where it is ---------------------------------------------------------------------------

COST = dict(own=76674, one=58263, four=79907, eight=108774, mono=66423, mono_own=42309)
COST12 = dict(own=76674, eight=102615, mono=61815)


def test_what_the_third_build_takes_off_an_interrupt(lean, twelve, factory):
    """Instructions, eight sampler tracks looping. The second build: 84,579 at their own pitch in stereo, 116,679
    pitched, which the unit's meter read as 72 and 99 hundredths of a block. 7,905 fewer either way here, and
    6,144 fewer again pitched with the sum of twelve. What that is in time is the unit's to say."""
    image = lean[0]
    got = dict(own=whole(image, factory, 8, 60)[3], one=whole(image, factory, 1, 55.25)[3], four=whole(image, factory, 4, 55.25)[3],
               eight=whole(image, factory, 8, 55.25)[3], mono=whole(image, factory, 8, 55.25, mode=0)[3],
               mono_own=whole(image, factory, 8, 60, mode=0)[3])
    assert all(abs(got[k] - COST[k]) <= 40 for k in COST), got
    assert 116679 - got["eight"] > 7800 and 84579 - got["own"] > 7800 and got["eight"] < 0.93 * SWARM
    image = twelve[0]
    got12 = dict(own=whole(image, factory, 8, 60)[3], eight=whole(image, factory, 8, 55.25)[3], mono=whole(image, factory, 8, 55.25, mode=0)[3])
    assert all(abs(got12[k] - COST12[k]) <= 40 for k in COST12), got12
    assert got12["own"] == got["own"] and got["eight"] - got12["eight"] > 6000 and got12["eight"] < 0.88 * SWARM
    assert got["mono"] - got12["mono"] > 4500


def test_where_it_is(stock, lean, twelve, pitch):
    """Twinshot's other run, its player and filter, holds the pass of the level and the gain: both of Twinshot's
    runs are used now. The three that move longs are in the room the sums left and in the right channels' own."""
    image, syms = lean
    lo, hi = m.LEAN_CAVES["m"]
    assert (lo, hi) == m.TWIN_ROOM["player and filter"] and pitch[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
    assert lo == syms["voice_out"] and image[m.off(lo):m.off(hi)] != stock[m.off(lo):m.off(hi)]
    assert m.QUICK_CAVES["k"][0] <= syms["longs"] < m.QUICK_CAVES["k"][1]
    assert m.ONE_CAVES["b"][0] <= syms["send"] < m.ONE_CAVES["b"][1] and m.CAVES["x"][0] <= syms["swap"] < m.CAVES["x"][1]
    assert lo < syms["fade_run"] < hi and m.PITCH_CAVES["s"][0] == syms["hq_pads"]         # the run under a fade; a note's start
    # stock's two routines are still there and still called, from the one place that may need them
    ours = list(dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES, **m.ONE_CAVES, **m.QUICK_CAVES, **m.LEAN_CAVES).values())
    for a in (STOCK_AMP, STOCK_MIX):
        calls = [m.BASE + o for o in range(0, m.off(m.CODE_END) - 5, 2) if image[o:o + 6] == b"\x4e\xb9" + a.to_bytes(4, "big")]
        mine = [c for c in calls if any(x <= c < y for x, y in ours)]
        assert len(mine) == 1 and lo <= mine[0] < hi
    assert image[m.off(STOCK_AMP):m.off(STOCK_AMP) + 0x68] == stock[m.off(STOCK_AMP):m.off(STOCK_AMP) + 0x68]
    assert image[m.off(STOCK_MIX):m.off(STOCK_MIX) + 0x76] == stock[m.off(STOCK_MIX):m.off(STOCK_MIX) + 0x76]
    # the sum of twelve is the same program with a shorter sum and another table: every difference is in our own
    # runs, and nothing outside the run of the sums has moved
    other, osyms = twelve
    diff = [m.BASE + k for k in range(len(image)) if image[k] != other[k]]
    assert diff and all(any(x <= d < y for x, y in ours) for d in diff)
    klo, khi = m.QUICK_CAVES["k"]
    assert {n for n in syms if syms[n] != osyms[n]} <= {n for n in syms if klo <= syms[n] < khi} and set(syms) == set(osyms)
    assert any(klo <= d < khi for d in diff) and any(m.REC_CAVES["z"][0] <= d < m.REC_CAVES["z"][1] for d in diff)


# ---- the sum of twelve ------------------------------------------------------------------------------------------

ROWS12 = sinctable.rows12()


def test_the_table_of_twelve_is_a_sinc_of_twelve_in_the_shape_of_the_one_of_sixteen():
    assert len(ROWS12) == 33 and all(len(r) == 16 and r[:2] == r[-2:] == [0, 0] and sum(r) == sinctable.ONE for r in ROWS12)
    assert ROWS12[0] == [0] * 7 + [sinctable.ONE] + [0] * 8 and ROWS12[32] == [0] * 8 + [sinctable.ONE] + [0] * 7
    assert all(ROWS12[32 - r] == ROWS12[r][::-1] for r in range(16))
    assert max(sum(abs(c) for c in r) for r in ROWS12) * 32768 < 2 ** 31            # a sum of them is under 32 bits at every step, as with sixteen
    assert sinctable.magic(True) != sinctable.magic() and sinctable.stored(True) == ROWS12[:17]


@pytest.mark.parametrize("note", [48, 36, 67, 72.5, 55.25])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_engine_of_twelve_is_the_model_with_that_table(twelve, case, note):
    knobs = CASES[case]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 40)
    e, left, right = play(twelve, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=12, **knobs), knobs)


@pytest.mark.parametrize("name", ["a walk, looped", "stereo, backwards", "ping-pong, leaps", "the short slot", "a short loop, STRT turned up"])
def test_and_with_the_knobs_moving(twelve, name):
    knobs, script = SCRIPTS[name]
    e, left, right = play(twelve, script, note=43, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=12, **knobs), knobs)


@pytest.mark.parametrize("knobs", [dict(), dict(mode=1), dict(sample=63, mode=1), dict(loop=2, mode=1)])
@pytest.mark.parametrize("n", [3, 15, 16, 17, 40, 300])
def test_and_within_reach_of_a_slots_ends(twelve, n, knobs):
    pool = TP.ends_pool(n)
    blocks = 14 if n < 100 else 90
    e, left, right, _ = TP.low(twelve, pool, 24, blocks, **knobs)
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=12)
    p.inc = e.player(0, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), loop=knobs.get("loop", 0), mode=knobs.get("mode", 0))
    want_l, want_r = [], []
    for b in range(blocks):
        if b:
            p.move(0, 127)
        l, r = p.block()
        want_l += tail(l)
        want_r += tail(r) if r is not None else [0] * BLOCK
    assert np.array_equal(left, np.array(want_l)) and (np.any(left) or n < 8)
    if knobs.get("mode") == 1:
        assert np.array_equal(right, np.array(want_r))


def test_at_its_own_pitch_twelve_and_sixteen_are_the_same_sound(lean, twelve):
    """No frame falls between two: nothing is summed."""
    for knobs in (dict(), dict(mode=1, loop=1, start=5, length=45), dict(sample=63)):
        script = hold(knobs.get("start", 0), knobs.get("length", 127), 30)
        _, a, ar = play(lean, script, **knobs)
        _, b, br = play(twelve, script, **knobs)
        assert np.array_equal(a, b) and np.array_equal(ar, br) and a.any()


@pytest.mark.parametrize("hz, sixteen, least", [(1000, 85, 85), (3000, 80, 78), (6000, 80, 76), (10000, 75, 72), (14000, 72, 66)])
def test_what_twelve_gives_up(lean, twelve, hz, sixteen, least):
    """A tone two octaves down, the engine's own output, everything else against the tone in dB. Sixteen frames:
    the pitch image's figures. Twelve: within about 8 dB of them, and 40 and more over the line between two
    frames that the pitch image replaced (33 dB at 6 kHz, 16 at 14)."""
    pool = TP.tone_pool(hz)
    with16 = TP.clean(*TP.played(lean, pool, 36, 620), hz=hz)
    with12 = TP.clean(*TP.played(twelve, pool, 36, 620), hz=hz)
    assert with16 >= sixteen and least <= with12 <= with16 + 1
