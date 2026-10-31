"""The stereo image's second build: the same frames for less work (engine/sampler.c and engine/stub.S built with QUICK).


Pitched, a stereo voice summed sixteen
frames twice a frame, 32 multiplies and 121 instructions a sum, in a loop that asked after the walls and the
fades at every frame: eight of them made the interrupt 1.37 of stock's heaviest.

Here the sums are made in the multiply and accumulate unit, as stock makes its own, a run of frames a call
(hq_run), in Twinshot's update and render. What is held, all of it in emulation:
  - What comes out is what came out. The engine is the reference model bit for bit at seven pitches, with the
    knobs moving, and within reach of a slot's ends; the routine alone is the old arithmetic at every fraction
    of a frame, both ways through a slot, at the stops; and next to the pitch image's engine, eight tracks at
    once with stock machines between them, nothing differs anywhere.
  - It leaves the unit as it found it: the mode word put back, every accumulator at 0 as it was, and every
    form of instruction in it one that stock's own code runs.
  - What it costs: eight pitched stereo tracks are under stock's heaviest interrupt.

Not held here: time. The emulator counts instructions; whether the unit now has the time is the unit's to say.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE

import emu.engine as engine_mod
import test_pagerec as P
import test_pitch as TP
from emu import emac
from emu import sampler_ref as ref
from emu.machine import Machine, boundaries
from stereo_rig import Rig
from test_fade import CASES, DECAY, LENGTH, LOOP, MODE, POOL, SAMPLE, START, TUNE, tail
from test_live import SCRIPTS, hold, model, play, same
from test_stereo import SWARM, pool, samplers, whole
from tools import audiomap as m
from tools import build_engine, params, sinctable
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ST, RVALID = 1712, 50
ROWS = sinctable.rows()
LONGS_BYTES = 33 * 16 * 4
SCRATCH = 0x44070000            # free memory for a test's own note, samples and frames


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def quick(stock):
    return build_engine.patched_image(stock, stereo=True)


@pytest.fixture(scope="module")
def pitch(stock):
    return build_engine.patched_image(stock, pitch=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


class Folded(P.HookEngine):
    """The engine the earlier images' tests are written for, on a one-track image: a stereo note's right channel,
    which waits in free memory, is shown where those images put it, in the next track's buffer."""

    def block(self, trig=0, release=0):
        out = super().block(trig, release)
        if m.u32(self.image, m.ISR_AMP_CALL + 2) == m.STAGE_AMPS:
            return out
        out = out.copy()
        for t in range(7):
            if self.mc.read(self.voice(t) + ST + RVALID, 1)[0]:
                out[t + 1] = np.frombuffer(self.mc.read(m.STASH + 128 * t, 128), dtype=">i4")
        return out


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


# ---- what comes out is what came out --------------------------------------------------------------------

@pytest.mark.parametrize("note", TP.NOTES)
@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_engine_is_the_reference_model_bit_for_bit(quick, case, note):
    """The pitch image's own test, on this engine: whole samples, cut ones, loops, backwards, stereo, the short slot."""
    knobs = CASES[case]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 40)
    e, left, right = play(quick, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=True, **knobs), knobs)


@pytest.mark.parametrize("note", [60, 48, 67, 31.5])
@pytest.mark.parametrize("name", list(SCRIPTS))
def test_with_the_knobs_moving_too(quick, name, note):
    """Every script of STRT and LEN the live image is held to: the frames a run stops for are the model's."""
    knobs, script = SCRIPTS[name]
    e, left, right = play(quick, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=True, **knobs), knobs)


@pytest.mark.parametrize("knobs", [dict(), dict(mode=1), dict(sample=63), dict(sample=63, mode=1), dict(loop=1, mode=1), dict(loop=2),
                                   dict(loop=2, mode=1), dict(start=30, length=60, mode=1)])
@pytest.mark.parametrize("n", [3, 8, 15, 16, 17, 23, 24, 40, 300])
def test_within_reach_of_a_slots_ends_it_is_the_model_too(quick, n, knobs):
    """Slots of a few frames and of many, three octaves down: every place the sixteen are not all in the slot."""
    pool = TP.ends_pool(n)
    blocks = 14 if n < 100 else 90
    e, left, right, _ = TP.low(quick, pool, 24, blocks, **knobs)
    want_l, want_r = TP.low_model(e, pool, blocks, **knobs)
    assert np.array_equal(left, want_l) and (np.any(left) or n < 8)
    if knobs.get("mode") == 1:
        assert np.array_equal(right, want_r) and (np.any(right) or n < 8)


@pytest.mark.parametrize("mode", [0, 1])
def test_the_loudest_sample_there_can_be_is_held_as_it_was(quick, mode):
    """Full scale, switching every few frames: the sum passes what 31 bits hold, both ways, and is held there."""
    rng = np.random.default_rng(3)
    square = np.repeat(rng.choice([-32768, 32767], 800), rng.integers(1, 5, 800))[:2000].astype(np.int16)
    other = np.repeat(rng.choice([-32768, 32767], 800), rng.integers(1, 5, 800))[:2000].astype(np.int16)
    pool = {0: square, 1: other}
    e = P.engine(quick, pool=pool)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)
    for slot, v in ((TUNE, 64), (SAMPLE, 64), (START, 0), (LENGTH, 127), (LOOP, 0), (MODE, mode), (DECAY, 127)):
        e.set_slot(0, slot, v)
    e.set_note(0, 49.3)
    out = np.array([e.block(trig=1 if b == 0 else 0) for b in range(100)])[1:]
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=True)
    p.inc = e.player(0, 0)["inc"]
    p.note_on(sample=64, mode=mode)
    raw_l, raw_r = [], []
    for _ in range(99):
        l, r = p.block()
        raw_l += list(l)
        raw_r += list(r) if r is not None else []
    assert np.array_equal(out[:, 0, :].ravel(), np.array(tail(raw_l)))
    assert max(raw_l) == 2 * ref.HQ_TOP and min(raw_l) == -2 * ref.HQ_TOP - 2
    if mode:
        assert np.array_equal(out[:, 1, :].ravel(), np.array(tail(raw_r)))
        assert max(raw_r) == 2 * ref.HQ_TOP and min(raw_r) == -2 * ref.HQ_TOP - 2
    assert e.mc.emac.overflows == 0                                 # and no accumulator ever passed its 48 bits


SWARM_TYPE, OTHERS = 38, (36, 37, 4)       # stock machines for the tracks that are not ours: SY SWARM, and SY TOY, SY BITS or a drum


def many(built, descs, seed, blocks=70):
    """Eight tracks for a while. 0 and 4 stereo samplers (1 and 5 left silent: the earlier images put a right channel
    there), two more mono samplers, two stock machines; samples, pitches, notes and knobs moving.
    -> what each block left in the eight buffers, the right channels folded in."""
    rng = np.random.default_rng(seed)
    e = P.engine(built, pool=POOL)
    stockers = {(2, 7)[seed % 2]: SWARM_TYPE, (6, 3)[seed % 2]: OTHERS[seed % 3]}
    mono = [t for t in (2, 3, 6, 7) if t not in stockers]
    for t in range(8):
        e.set_slot(t, SAMPLE, 64 + 63)
    for t, mtype in stockers.items():
        e.set_defaults(t, mtype, descs)
        e.set_note(t, 48 + 5 * t)
    for t in (0, 4):
        e.set_slot(t, MODE, 1)
    out = []
    for b in range(blocks):
        trig = 0
        if b % 9 == 1:
            for t in [0, 4] + mono:
                if rng.random() < 0.25:
                    continue
                pick = [64, 65, 66, 63, 62] if t in (0, 4) else [64, 65, 68, 70, 63, 60, 57]
                for slot, v in ((SAMPLE, int(rng.choice(pick))), (START, int(rng.integers(0, 90))), (LENGTH, int(rng.integers(3, 128))),
                                (LOOP, int(rng.integers(0, 3))), (TUNE, int(rng.integers(40, 90)))):
                    e.set_slot(t, slot, v)
                e.set_note(t, float(rng.choice([60, 48, 36, 24, 67, 72.5, 84, 55.25, 59, 61])))
                trig |= 1 << t
            trig |= sum(1 << t for t in stockers)
        elif rng.random() < 0.4:
            t = int(rng.choice([0, 4] + mono))
            e.set_slot(t, START if rng.random() < 0.5 else LENGTH, int(rng.integers(3, 120)))
        out.append(e.block(trig=trig))
    return np.array(out), e


@pytest.mark.parametrize("seed", range(6))
def test_next_to_the_pitch_images_engine_nothing_differs(quick, pitch, descs, seed):
    """Not the model: the engine this one replaces, the whole voice loop, eight tracks at once. A stereo track's two
    channels, the mono ones, and the stock machines between them, whose own sums use the same accumulators."""
    a, ea = many(pitch, descs, seed)
    b, eb = many(quick, descs, seed)
    assert np.array_equal(a, b)
    assert all(a[:, t].any() for t in (0, 1, 2, 3, 4, 5, 6, 7))
    assert ea.mc.emac.overflows == eb.mc.emac.overflows == 0


# ---- the routine alone ----------------------------------------------------------------------------------

def old_sum(x16, f):
    """What the pitch image's routine makes of sixteen frames and a fraction (engine/stub.S, hq_mid)."""
    r0, r1 = ROWS[f >> 7], ROWS[(f >> 7) + 1]
    d0 = sum(int(v) * c for v, c in zip(x16, r0))
    d1 = sum(int(v) * c for v, c in zip(x16, r1))
    d = d0 + ((d1 - d0) >> 7) * (f & 127)
    return 2 * min(max(d, -0x40000000), 0x3fffffff)


def old_frame(x, pad, pos):
    """A frame of one channel as engine/sampler.c picked it before: x the slot, pad its 45 words around the two ends."""
    i, f, n = pos >> 12, pos & 0xfff, len(x)
    if not f:
        return int(x[i]) * 65536
    if i >= 7 and i + 9 <= n:
        return old_sum(x[i - 7:i + 9], f)
    w = i if i < 7 else 22 + 8 + i - n
    return old_sum(pad[w:w + 16], f)


def pads_of(x):
    n = len(x)
    return [int(x[min(max(j, 0), n - 1)]) for j in list(range(-7, 15)) + list(range(n - 15, n + 8))]


class Alone:
    """hq_run by itself: a note's state, two channels and their ends written out, in free memory."""
    NOTE, LEFT, RIGHT, PAD, OUT_L, OUT_R = SCRATCH, SCRATCH + 0x1000, SCRATCH + 0x5000, SCRATCH + 0x100, SCRATCH + 0x400, SCRATCH + 0x600

    def __init__(self, built, left, right, native=True):
        image, self.syms = built
        real = engine_mod.Machine
        if not native:
            engine_mod.Machine = lambda: real(use_native=False)
        try:
            self.e = P.engine(built)
        finally:
            engine_mod.Machine = real
        self.e.block()                                              # the table is made
        self.mc, self.left, self.right = self.e.mc, left, right
        self.mc.write(self.LEFT, np.asarray(left, dtype=">i2").tobytes())
        self.mc.write(self.RIGHT, np.asarray(right, dtype=">i2").tobytes())
        self.pads = pads_of(left), pads_of(right)
        self.mc.write(self.PAD, np.asarray(self.pads[0] + self.pads[1], dtype=">i2").tobytes())

    def run(self, pos, inc, direction, n, end, lo, span, stereo=True, macsr=0xa0):
        mc = self.mc
        mc.write(self.NOTE, bytes(88))
        for off, v in ((0, self.LEFT), (4, self.RIGHT), (8, pos), (12, len(self.left)), (24, inc), (72, self.PAD)):
            mc.w32(self.NOTE + off, v)
        mc.write(self.NOTE + 28, bytes([direction & 0xff]))
        mc.write(self.OUT_L, b"\x55" * 128)
        mc.write(self.OUT_R, b"\x55" * 128)
        mc.emac.macsr = macsr
        got = mc.call(self.syms["hq_run"], self.NOTE, self.OUT_L, self.OUT_R if stereo else 0, n, end, lo & 0xffffffff, span & 0xffffffff)
        frames = lambda at: np.frombuffer(mc.read(at, 128), dtype=">i4").astype(np.int64)
        return got, emac.s32(mc.r32(self.NOTE + 8)), frames(self.OUT_L), frames(self.OUT_R)

    def want(self, pos, step, count, stereo=True):
        l = [old_frame(self.left, self.pads[0], pos + k * step) for k in range(count)]
        r = [old_frame(self.right, self.pads[1], pos + k * step) for k in range(count)] if stereo else []
        return l, r


def loud(n, seed):
    rng = np.random.default_rng(seed)
    x = rng.integers(-32768, 32768, n)
    x[n // 3:n // 2] = np.repeat(rng.choice([-32768, 32767], n), rng.integers(1, 4, n))[:n // 2 - n // 3]
    return x.astype(np.int16)


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("stereo", [True, False])
def test_the_routine_is_the_old_arithmetic_at_every_fraction_of_a_frame(quick, stereo, native):
    """Every fraction there is, 4096 of them, on frames of noise and of full scale switching: frame for frame what
    the pitch image's routine made, on both models of the unit this bench has."""
    left, right = loud(600, 1), loud(600, 2)
    a = Alone(quick, left, right, native)
    held = 0
    for start in range(0, 4096, 32):
        pos, inc = (40 + start % 500) << 12 | start, 4097               # the fraction moves on one a frame
        got, at, l, r = a.run(pos, inc, 1, 0, 32, 0, 0x7fffffff, stereo)
        wl, wr = a.want(pos, inc, 32, stereo)
        assert got == 32 and at == pos + 32 * inc
        assert list(l) == wl and (not stereo or list(r) == wr)
        assert stereo or set(r) == {0x55555555}                         # one channel: the other's frames are not touched
        held += sum(abs(v) >= 0x7ffffffe for v in wl + wr)
    assert held > 20 and a.mc.emac.overflows == 0


@pytest.mark.parametrize("n", [3, 15, 16, 17, 24, 200])
@pytest.mark.parametrize("stereo", [True, False])
def test_and_wherever_in_a_slot_the_frame_is(quick, n, stereo):
    """Both ways through slots of a few frames and of many, a step that lands on frames of the sample and between
    them: in the slot, and from what a note's start writes out of its ends."""
    a = Alone(quick, loud(max(n, 6), n)[:n], loud(max(n, 6), n + 50)[:n])
    last = (n - 1) << 12
    for inc in (1, 517, 2048, 4096, 5000, 9000):
        for direction, pos in ((1, 0), (-1, last)):
            step = inc * direction
            count = min(32, last // inc + 1)
            got, at, l, r = a.run(pos, inc, direction, 0, count, 0, 0x7fffffff, stereo)
            wl, wr = a.want(pos, step, count, stereo)
            assert got == count and at == pos + count * step
            assert list(l[:count]) == wl and set(l[count:]) <= {0x55555555}
            assert not stereo or (list(r[:count]) == wr and set(r[count:]) <= {0x55555555})


def test_a_run_stops_at_the_frame_that_is_not_in_its_stretch(quick):
    """From frame n of a block to the first whose place is before lo or span past it; one frame wherever it is, when asked."""
    a = Alone(quick, loud(300, 4), loud(300, 5))
    pos, inc = (50 << 12) + 77, 3000
    got, at, l, r = a.run(pos, inc, 1, 5, 32, 0, pos + 10 * inc - 1)              # ten frames' places are under the end
    wl, wr = a.want(pos, inc, 10)
    assert got == 15 and at == pos + 10 * inc
    assert list(l[5:15]) == wl and list(r[5:15]) == wr and set(l[:5]) | set(l[15:]) | set(r[:5]) | set(r[15:]) == {0x55555555}
    got, at, l, r = a.run(pos, inc, -1, 0, 32, pos - 3 * inc, 0x7fffffff)         # backwards: down to lo and no further
    assert got == 4 and at == pos - 4 * inc and list(l[:4]) == a.want(pos, -inc, 4)[0]
    got, at, l, r = a.run(pos, inc, 1, 9, 32, pos + 1, 100)                       # not in the stretch at all: nothing is made
    assert got == 9 and at == pos and set(l) | set(r) == {0x55555555}
    got, at, l, r = a.run(pos, inc, 1, 9, 10, -0x80000000, 0xffffffff)            # one frame, wherever
    assert got == 10 and at == pos + inc and (l[9], r[9]) == (a.want(pos, inc, 1)[0][0], a.want(pos, inc, 1)[1][0])
    assert set(l[:9]) | set(l[10:]) == {0x55555555}


# ---- it leaves the unit as it found it ------------------------------------------------------------------

@pytest.mark.parametrize("macsr", [0xa0, 0x20, 0xa6, 0])
def test_the_mode_word_is_put_back_and_the_accumulators_left_at_nothing(quick, macsr):
    a = Alone(quick, loud(300, 6), loud(300, 7))
    regs = [0x1000 * k + 0x123 for k in range(2, 8)] + [0x44070800 + 4 * k for k in range(2, 7)]      # d2-d7, a2-a6
    for k, v in zip(list(range(2, 8)) + list(range(10, 15)), regs):
        a.mc.set_reg(k, v)
    wrote = []
    h = a.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, at, s, v, u: wrote.append((at, s)))
    a.mc.uc.ctl_flush_tb()
    got, at, l, r = a.run((60 << 12) + 5, 2500, 1, 0, 32, 0, 0x7fffffff, macsr=macsr)
    a.mc.uc.hook_del(h)
    assert got == 32 and a.mc.emac.macsr == macsr and a.mc.emac.acc == [0, 0, 0, 0]
    assert [a.mc.reg(k) for k in list(range(2, 8)) + list(range(10, 15))] == regs
    ok = [(a.OUT_L, a.OUT_L + 128), (a.OUT_R, a.OUT_R + 128), (a.NOTE + 8, a.NOTE + 12), (m.STACK_TOP - 0x200, m.STACK_TOP)]
    assert wrote and all(any(lo <= w and w + s <= hi for lo, hi in ok) for w, s in wrote)       # the frames, the place, its own stack


def test_in_the_voice_loop_it_finds_the_unit_as_it_leaves_it(quick, factory):
    """The real interrupt, eight tracks, stock's heaviest machine on two of them: at every call the mode word is the
    voice loop's and the four accumulators hold nothing, which is how the routine leaves them."""
    image, syms = quick
    r = Rig(image)
    r.load_pool(pool())
    samplers(r, factory, loop=1, mode=1)
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 3)
        r.set_note(t, (55.25, 60, 43, 67)[t % 4])
    for t in (2, 6):
        r.set_machine(t, 38)
    seen = []
    ends = [a for a, _, text in boundaries(image[m.off(syms["hq_out"]):m.off(syms["hq_out"]) + 40], syms["hq_out"]) if text.startswith("rts")][:1]
    hook = lambda uc, address, size, user: seen.append((address, r.mc.emac.macsr & 0xf0, tuple(r.mc.emac.acc)))
    for at in [syms["hq_run"]] + ends:
        r.mc.uc.hook_add(UC_HOOK_CODE, hook, None, begin=at, end=at)
    r.mc.uc.ctl_flush_tb()
    r.block(0, 0)
    r.block(0xff, 0)
    for _ in range(12):
        r.block(0, 0)
    calls = [s for s in seen if s[0] == syms["hq_run"]]
    assert len(calls) > 60 and len(seen) == 2 * len(calls)
    assert {s[1:] for s in seen} == {(0xa0, (0, 0, 0, 0))}
    assert r.mc.emac.overflows == 0


def shape(i):
    """What kind of instruction of the multiply and accumulate unit this is, registers and numbers apart: for a
    product, the kinds of register multiplied, and for one that fetches, how the place is named, the kind of
    register fetched into, and whether that is one of the two multiplied."""
    side = lambda reg: "a" if reg >= 8 else "d"
    if i.kind == "mac":
        fetch = (i.mem[0], side(i.rw), i.rw in (i.rx, i.ry)) if i.mem else ()
        return ("mac", i.sub, "".join(sorted(side(i.rx) + side(i.ry)))) + fetch
    return (i.kind, i.clear) + ((i.src[0],) if i.src else ())


def test_every_form_of_instruction_in_it_is_one_stock_runs(stock, quick):
    """The bench's model of that unit was made for stock's code and checked on it: nothing here asks more of it.
    Signed fractions and longs only, a product with or without a fetch, by register or by a place past one, into
    a data or an address register; the mode word saved, set to stock's and put back."""
    image, syms = quick
    def forms(mc, spans):                                           # the instructions of that unit, as the bench takes them over
        return {shape(i) for at, i in mc.emac_sites.items() if any(lo <= at < hi for lo, hi in spans)}
    theirs = forms(Rig(stock).mc, [(m.BASE, m.CODE_END)])
    lo, hi = m.QUICK_CAVES["k"]
    ours = forms(Rig(image).mc, [(lo, hi), (syms["hq_one"], m.CAVES["y"][1])])
    assert len(ours) >= 9 and set(ours) <= set(theirs), sorted(set(ours) - set(theirs))
    assert {("mac", False, "ad", 5, "a", True), ("mac", False, "dd", 3, "d", True), ("store", True), ("to_macsr", False, "imm")} <= set(ours)
    # stock sets this mode itself around its voices and puts back what it found around a routine, as hq_run does
    assert stock[m.off(0x40001916):m.off(0x4000191c)] == bytes.fromhex(fw.sx("e49bfb15e468ef342fd3")) == image[m.off(lo) + 16:m.off(lo) + 22]


# ---- the table -------------------------------------------------------------------------------------------

def longs_of(e):
    raw = e.mc.read(m.HQ_LONGS, LONGS_BYTES)
    return [[int.from_bytes(raw[64 * r + 4 * k:64 * r + 4 * k + 4], "big", signed=True) for k in range(16)] for r in range(33)]


WANT = [[c << 15 for c in row] for row in ROWS]


def test_the_table_is_33_rows_of_longs_made_at_every_start(quick):
    """A number of the table shifted up 15, in a long. Made on the first interrupt after a start, and after stock's
    reset of the first voice, from the rows in the image: nothing in that memory is believed."""
    e = P.engine(quick)
    assert e.mc.r32(m.HQ_MADE) == 0
    e.mc.write(m.HQ_LONGS - 16, b"\xa5" * (LONGS_BYTES + 32))
    e.block()
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic() and longs_of(e) == WANT
    assert e.mc.read(m.HQ_LONGS - 16, 16) == e.mc.read(m.HQ_LONGS + LONGS_BYTES, 16) == b"\xa5" * 16
    for trig in (0xff, 0, 0):                                       # each voice's first note resets it, the first voice too: made again
        e.block(trig=trig)
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic() and longs_of(e) == WANT
    wrote = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: wrote.append(a), begin=m.HQ_MARK, end=m.HQ_LONGS + LONGS_BYTES + 64)
    e.mc.uc.ctl_flush_tb()
    for b in range(4):
        e.block(trig=0 if b else 1)
    pads = range(m.HQ_PADS, m.HQ_PADS + 8 * m.HQ_PAD_BYTES)
    assert all(a in pads for a in wrote)                            # made: left alone. And the rows of words are not written at all
    e.mc.write(m.HQ_LONGS + 200, fw.sb("9f7cc770a4cd8734"))
    e.mc.call(m.VOICE_RESET, e.voice(0))
    assert e.mc.r32(m.HQ_MADE) == 0
    del wrote[:]
    e.block()
    assert longs_of(e) == WANT and sorted(set(wrote)) == list(range(m.HQ_LONGS, m.HQ_LONGS + LONGS_BYTES, 4))


def test_a_sum_is_under_32_bits_at_every_step(quick):
    """Why an accumulator read back is the sum itself, wherever the unit holds one to: a row's numbers add up to
    under two in size, so sixteen full-scale frames times them, in any order and stopped anywhere, stay inside
    32 bits, where neither the 48 the unit sums in nor the 40 it may hold to is met."""
    assert max(sum(abs(c) for c in row) for row in ROWS) == 63807 and 63807 * 32768 < 2 ** 31
    assert all(abs(c << 15) < 2 ** 31 for row in ROWS for c in row)
    # a frame at the top of a long times a number shifted up 15 has nothing under the 40 bits the unit keeps
    assert all(((x << 16) * (c << 15)) % (1 << 23) == 0 for x in (-32768, -1, 1, 32767) for c in (ROWS[5][7], ROWS[16][3], -6318))
    a = Alone(quick, np.full(64, -32768, dtype=np.int16), np.full(64, 32767, dtype=np.int16))
    got, at, l, r = a.run((20 << 12) + 2048, 0, 1, 0, 4, 0, 0x7fffffff)
    assert set(l[:4]) == {-32768 * 32767 * 2} and set(r[:4]) == {32767 * 32767 * 2} and a.mc.emac.overflows == 0


def test_the_tables_memory_is_no_one_elses(stock, quick):
    """Past the eight voices' frames around their slots' ends, under the takes' marks and buffers."""
    end = m.HQ_LONGS + LONGS_BYTES
    assert m.HQ_PADS + 8 * m.HQ_PAD_BYTES == m.HQ_LONGS and end <= SCRATCH < m.KEPT < m.REC_BASE
    ours = [m.QUICK_CAVES["k"], m.CAVES["y"], m.PITCH_CAVES["t"]]
    for image in (stock, quick[0]):
        named = [o for o in range(0, len(image) - 3, 2) if m.HQ_LONGS <= int.from_bytes(image[o:o + 4], "big") < end]
        assert all(any(m.off(lo) <= o < m.off(hi) for lo, hi in ours) for o in named) and (named or image is stock)
    assert len([o for o in range(0, len(quick[0]) - 3, 2) if int.from_bytes(quick[0][o:o + 4], "big") == m.HQ_TABLE]) == 0     # the rows of words: gone


# ---- what it costs ---------------------------------------------------------------------------------------

COST = dict(own=76674, one=58263, four=79907, eight=108774, mono=66423, mono_own=42309)     # the third build's: tests/test_lean.py


def test_eight_pitched_stereo_tracks_are_under_stocks_heaviest_interrupt(quick, pitch, factory):
    """Instructions an interrupt, eight sampler tracks looping. The first build's eight pitched stereo tracks were
    160,319, 1.37 of SY SWARM on all eight; they are under it now, and everything else is less than it was too."""
    image, _ = quick
    got = dict(own=whole(image, factory, 8, 60)[3], one=whole(image, factory, 1, 55.25)[3], four=whole(image, factory, 4, 55.25)[3],
               eight=whole(image, factory, 8, 55.25)[3], mono=whole(image, factory, 8, 55.25, mode=0)[3],
               mono_own=whole(image, factory, 8, 60, mode=0)[3])
    assert all(abs(got[k] - COST[k]) <= 40 for k in COST), got
    assert got["eight"] < SWARM and got["own"] < 0.73 * SWARM
    for note in (36, 48, 67):                                       # the same at any pitch between frames
        assert abs(whole(image, factory, 8, note)[3] - got["eight"]) < 150
    was = whole(pitch[0], factory, 8, 55.25, mode=0, earlier=True)[3], whole(pitch[0], factory, 8, 60, mode=0, earlier=True)[3]
    assert was[0] - got["mono"] > 19000 and was[1] - got["mono_own"] > 8500


@pytest.mark.parametrize("note", [36, 24, 12])
@pytest.mark.parametrize("mode", [0, 1])
def test_a_low_notes_blocks_within_reach_of_an_end_cost_what_the_rest_do(quick, note, mode):
    """Far below its pitch a note is within reach of its slot's end for blocks. Those frames are made by the same run."""
    pool = TP.ends_pool(4000)
    e, left, right, counts = TP.low(quick, pool, note, 40, warm=True, mode=mode)
    assert max(counts[1:]) - min(counts[1:]) < 220 and left.any()


# ---- the room --------------------------------------------------------------------------------------------

def test_it_is_in_twinshots_update_and_render_and_what_it_replaces_is_gone(stock, quick, pitch):
    """Stock Twinshot's two routines, which no table of ours points at and nothing else reaches (tests/test_stereo.py
    holds that of the image without them): 830 bytes, the first use of that room. The two-channel sum and the
    routine's ends are there; the one-channel sum is in the room the old routine left in the sampler's second run."""
    image, syms = quick
    lo, hi = m.QUICK_CAVES["k"]
    assert (lo, hi) == m.TWIN_ROOM["update and render"] == (m.TWIN_UPDATE, 0x40009b1a) and hi - lo == 830
    assert pitch[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)] and image[m.off(lo):m.off(hi)] != stock[m.off(lo):m.off(hi)]
    assert all(lo <= syms[n] < hi for n in ("hq_run", "hq_two", "hq_out", "hq_hold"))
    ylo, yhi = m.CAVES["y"]
    assert all(ylo <= syms[n] < yhi for n in ("hq_one", "sampler_hook")) and "hq_mid" not in syms and "hq_mid" in pitch[1]
    assert m.u32(image, m.UPDATE_TABLE + 4 * m.TWIN_ENGINE) == syms["sampler_update"] and m.u32(image, m.RENDER_TABLE + 4 * m.TWIN_ENGINE) == syms["sampler_render"]
    other = m.TWIN_ROOM["player and filter"]                        # Twinshot's other run: the third build's (tests/test_lean.py)
    assert pitch[0][m.off(other[0]):m.off(other[1])] == stock[m.off(other[0]):m.off(other[1])]
