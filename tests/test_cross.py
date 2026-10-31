"""The "cross" image: a loop's end blended into its start, where the fade image dipped.


The dip was the fade image's answer to a click: a forward loop faded out over the 128 frames before its
seam and in over the 64 after, about 4 ms of nothing once a pass.

A blend needs something that leads to the place the next pass begins, and a loop that keeps its length has only
what lies outside it (engine/sampler.h, XFADE):
  - the 256 frames before the start, when there are that many: the pass's last 256 frames go down as those come
    up, and the pass ends on the very frame the next begins after;
  - or else the 256 after the end: the seam is 256 frames later on both sides, the pass running on past its end as
    the frames after the start come up under it;
  - a loop of the whole sample has neither, and keeps the dip.
Played backwards the same the other way round. The blended frames are made of the sample's own, before it is
pitched, and written out ahead, eight a block, so that a block in a seam is no more work than any other.

What is held here, in emulation:
  - the engine is the reference model bit for bit (emu/sampler_ref.py, xfade=True): forward, backwards, mono,
    stereo, each of the two kinds of blend, at five pitches, and with the knobs moving;
  - where there is nothing to blend with, and for a one-shot and a ping-pong, it is the mode image's engine;
  - what a seam is now: a steady level stays where it is, a ramp's jump is spread over the blend, and outside the
    frames around a seam the loop is the frames it was, pass after pass: it is as long as it was;
  - how the blend is written, that a seam reached before it is all there dips as it did, that a pass inside its
    blend is left alone by the knobs;
  - what it writes and where, what it costs a block, and where its code is.

Not held: how it sounds, and time on the unit. The meter in the page's last place is there for the second.
"""
import shutil

import numpy as np
import pytest

import test_pagerec as P
import test_stereo as T
from emu import sampler_ref as ref
from emu.engine import BLOCK
from stereo_rig import Rig
from test_fade import LENGTH, LOOP, POOL, SAMPLE, START
from test_live import SCRIPTS, hold, state
from test_mode import ALONE, as_it_was, model, play, start
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode, params

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ST = 1712
S_XN, S_XUSE = 84, 86                   # in a voice's sampler state: frames of the blend written; 1 may go in, 2 is in
W, NEAR, FAR, N, STEP, REACH = ref.XF_W, ref.XF_NEAR, ref.XF_FAR, ref.XF_N, ref.XF_STEP, ref.XF_REACH
XF, XF_STRIDE, XF_BYTES = 0x44062000, 0x800, 16 + 4 * N     # a voice's: the seam (four longs), then the left's frames and the right's
WRITTEN = N // STEP                     # blocks it takes to write a blend out
FRAMES = 6000
FULL = 20000 * 65536                    # the steady level's sample, as a track's buffer has it
# name: (the pool, the knobs, does a seam blend)
LOOPS = {
    "sound before the start": (ALONE, dict(loop=1, start=30, length=60), True),
    "sound before the start, stereo": (POOL, dict(loop=1, start=30, length=60), True),
    "nothing before the start": (ALONE, dict(loop=1, length=60), True),
    "nothing before the start, stereo": (POOL, dict(loop=1, length=60), True),
    "to the sample's end": (ALONE, dict(loop=1, start=40), True),
    "backwards": (ALONE, dict(loop=1, sample=63, start=10, length=60), True),
    "backwards, stereo": (POOL, dict(loop=1, sample=63, start=10, length=60), True),
    "backwards from the sample's end": (ALONE, dict(loop=1, sample=63, start=30), True),
    "the ramp": (ALONE, dict(loop=1, sample=68, start=20, length=50), True),
    "the whole sample": (POOL, dict(loop=1), False),
    "the whole sample, backwards": (ALONE, dict(loop=1, sample=63), False),
    "once": (ALONE, dict(start=30, length=60), False),
    "ping-pong": (POOL, dict(loop=2, start=30, length=60), False),
    "the short slot": (ALONE, dict(loop=1, sample=70), False),
}
NOTES = [60, 53.3, 67, 36, 79]


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def cross(stock):
    return build_engine.patched_image(stock, cross=True)


@pytest.fixture(scope="module")
def auto(stock):
    return build_engine.patched_image(stock, auto=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def seam_of(e, track=0):
    """What the engine holds of a voice's blend: frames written, where the pass is with it, and the seam it is for."""
    at, x = e.voice(track) + ST, XF + XF_STRIDE * track
    s32 = lambda a: int.from_bytes(e.mc.read(a, 4), "big", signed=True)
    return dict(n=int.from_bytes(e.mc.read(at + S_XN, 2), "big"), use=e.mc.read(at + S_XUSE, 1)[0], wall=s32(x) >> 12, to=s32(x + 4) >> 12)


def region(knobs):
    """The frames a note's knobs make its region of a 6,000 frame sample: [a, b)."""
    a = ref.scale(FRAMES, ref.knob(knobs.get("start", 0)))
    ln = max(ref.knob(knobs.get("length", 127)), ref.LEN_MIN)
    return a, FRAMES if ln >= 127 << 8 else a + ref.scale(FRAMES - a, ln)


# ---- the engine is the model ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("note", NOTES)
@pytest.mark.parametrize("name", list(LOOPS))
def test_the_engine_is_the_reference_model_bit_for_bit(cross, name, note):
    pool, knobs, blends = LOOPS[name]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 420)
    e, left, right = play(cross, pool, script, note=note, **knobs)
    want_l, want_r, p = model(e, pool, script, xfade=True, **knobs)
    assert np.array_equal(left, want_l) and np.array_equal(right, want_r) and np.any(left) and np.any(right) == (pool is POOL)
    got, mine = state(e), seam_of(e)
    assert bool(got["playing"]) == p.playing and (mine["n"], mine["use"]) == (p.xn, p.xuse)
    a, b = region(knobs)
    faded = b - a >= e.player(0, 0)["inc"] >> 2             # (three octaves up these loops are too short to be faded at all)
    assert (mine["n"] == N) == (blends and faded) and (faded or note > 70)
    if p.playing and p.xuse != 2:               # (inside a blend the engine counts its place from the blend's first frame)
        assert (got["frame"], got["a"], got["b"], got["c"], got["span"], got["fade"]) == (p.pos >> 12, p.pa, p.pb, p.pc, p.span, p.fade)
    if blends:
        assert (mine["wall"], mine["to"]) == p.xkey


@pytest.mark.parametrize("n", range(len(SCRIPTS)))
def test_with_the_knobs_moving_too(cross, n):
    """Every script of STRT and LEN the live image is held to, then the knobs at rest for long enough to blend."""
    name = list(SCRIPTS)[n]
    knobs, script = SCRIPTS[name]
    pool, knobs, two = as_it_was(knobs)
    script = list(script) + [script[-1]] * 220
    note = (60, 55, 64.7)[n % 3]
    e, left, right = play(cross, pool, script, note=note, **knobs)
    want_l, want_r, p = model(e, pool, script, xfade=True, **knobs)
    assert np.array_equal(left, want_l) and np.array_equal(right, want_r) and np.any(left) and np.any(right) == two
    assert (seam_of(e)["n"], seam_of(e)["use"], bool(state(e)["playing"])) == (p.xn, p.xuse, p.playing)


def test_the_knobs_walking_all_the_while(cross):
    """A blend begun again and again, gone into whenever the knobs rest for long enough."""
    rng = np.random.default_rng(5)
    script, st, ln = [], 30.0, 60.0
    while len(script) < 900:
        if rng.random() < 0.5:
            st = float(np.clip(st + rng.normal(0, 6), 0, 100))
        else:
            ln = float(np.clip(ln + rng.normal(0, 10), 20, 127))
        script += [(round(st * 256) / 256, round(ln * 256) / 256)] * int(rng.integers(1, 90))
    for pool, knobs in ((POOL, dict(loop=1, start=30, length=60)), (ALONE, dict(loop=1, sample=63, start=30, length=60))):
        e, left, right = play(cross, pool, script, note=62.3, **knobs)
        want_l, want_r, p = model(e, pool, script, xfade=True, **knobs)
        assert np.array_equal(left, want_l) and np.array_equal(right, want_r) and (seam_of(e)["n"], seam_of(e)["use"]) == (p.xn, p.xuse)


@pytest.mark.parametrize("name", [k for k, v in LOOPS.items() if not v[2]])
@pytest.mark.parametrize("note", [60, 55.25])
def test_where_there_is_nothing_to_blend_with_it_is_the_mode_images_engine(cross, auto, name, note):
    """A loop of the whole sample, a one-shot, a ping-pong, a loop too short to be faded: frame for frame."""
    pool, knobs, _ = LOOPS[name]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 300)
    e, left, right = play(cross, pool, script, note=note, **knobs)
    _, was_l, was_r = play(auto, pool, script, note=note, **knobs)
    assert np.array_equal(left, was_l) and np.array_equal(right, was_r) and np.any(left)
    assert seam_of(e)["n"] == 0 and seam_of(e)["use"] == 0


# ---- what a seam is now -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("note", [60, 55.25, 43.5])
@pytest.mark.parametrize("knobs", [dict(start=30, length=60), dict(length=60), dict(sample=61, start=10, length=60)])
def test_a_steady_level_stays_where_it_is(cross, auto, note, knobs):
    """The steady level's sample, looped. The mode image's engine takes it down to nothing and up again at every
    seam; here, once the blend is written, it does not move."""
    knobs = dict(knobs, loop=1, sample=knobs.get("sample", 66) if knobs.get("sample") != 61 else 61)
    script = hold(knobs.get("start", 0), knobs["length"], 500)
    _, was, _ = play(auto, ALONE, script, note=note, **knobs)
    e, left, _ = play(cross, ALONE, script, note=note, **knobs)
    late = slice((WRITTEN + 2) * BLOCK, None)
    level = int(was.max())
    assert abs(level - FULL) < 4 and was[late].min() < level // 100         # the dip, to a 128th
    # (a frame between two of a steady level is a 30,000th under it: the table's rows add up to within that)
    assert left[late].min() > level - level // 20000 and left[late].max() == level and seam_of(e)["n"] == N
    if note == 60:
        assert left[late].min() == level


def test_a_ramps_jump_is_spread_over_the_blend(cross, auto):
    """The ramp, a loop of a quarter of it: the end is 10,700 above the start. A cut there is that jump in one frame;
    the dip took the sound down to nothing over 128 frames and up over 64; the blend takes it from the one level to
    the other in 256 frames, at 36 a frame where the ramp's own slope is 7 and the dip's steepest was 201."""
    knobs = dict(loop=1, sample=68, start=40, length=50)
    a, b = region(knobs)
    jump = (int(POOL[4][b - 1]) - int(POOL[4][a])) * 65536
    script = hold(40, 50, 500)
    _, was, _ = play(auto, ALONE, script, **knobs)
    e, left, _ = play(cross, ALONE, script, **knobs)
    late = slice(b - a + 200, None)             # (the first seam comes before its blend is written, and dips)
    steps, steps_was = np.abs(np.diff(left[late].astype(np.int64))), np.abs(np.diff(was[late].astype(np.int64)))
    slope = 40000 * 65536 // FRAMES
    assert jump > 10000 * 65536 and steps.max() < jump // 200 and steps.max() < slope + jump // W + 3 * 65536
    assert steps_was.max() > 5 * steps.max()                                # the dip's way down, and its own wrap, were the steeper


@pytest.mark.parametrize("knobs, lead", [(dict(loop=1, start=30, length=60), 0), (dict(loop=1, length=60), W),
                                         (dict(loop=1, sample=63, start=10, length=60), 0)])
def test_a_loop_is_as_long_as_it_was_and_only_the_frames_at_a_seam_are_others(cross, auto, knobs, lead):
    """Noise, at its own pitch, eight passes: against the mode image's engine, every frame is the frame it was
    but those of a blend and of the dip it stands in for. With nothing before the start to blend with, the seam is
    256 frames on: the frames that differ are the dip's and the 256 after each wrap."""
    a, b = region(knobs)
    span = b - a
    blocks = 8 * span // BLOCK
    script = hold(knobs.get("start", 0), knobs["length"], blocks)
    _, was, _ = play(auto, ALONE, script, **knobs)
    _, left, _ = play(cross, ALONE, script, **knobs)
    other = np.nonzero(left != was)[0]
    first = int(np.ceil((WRITTEN + 1) * BLOCK / span))                     # the first seam the blend is written for
    seams = [k * span for k in range(first, 9)]
    assert len(other) and all(any(s - max(W, 128) - 8 <= n < s + max(lead, 64) + 8 for s in seams) for n in other)
    for s in seams[:-1]:                                                    # and at every such seam they do differ
        assert np.any((other >= s - 128) & (other < s + lead))
    assert np.array_equal(left[:seams[0] - W - 8], was[:seams[0] - W - 8])


# ---- how the blend is written ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("pool, knobs", [(ALONE, dict(loop=1, start=30, length=60)), (POOL, dict(loop=1, sample=63, start=10, length=60))])
def test_eight_frames_a_block_from_the_block_after_the_note_starts(cross, pool, knobs):
    e = start(cross, pool, **knobs)
    e.mc.write(XF, b"\x5a" * (8 * XF_STRIDE))
    e.block(trig=1)
    assert seam_of(e)["n"] == 0
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=12, xfade=True)
    p.inc = 4096
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127), loop=1)
    e.block()                                                               # the note starts: nothing is written in that block,
    p.block()
    assert seam_of(e)["n"] == 0 and bytes(e.mc.read(XF, XF_BYTES)) == b"\x5a" * XF_BYTES
    wait = 1 if p.fstep else 0                                              # nor in the second block of the fade in a cut start has
    for k in range(1, WRITTEN + 6):
        e.block()
        p.move(knobs.get("start", 0), knobs.get("length", 127))
        p.block()
        got = seam_of(e)
        assert got["n"] == p.xn == min(STEP * max(k - wait, 0), N)
        if not got["n"]:
            continue
        assert (got["wall"], got["to"]) == p.xkey
        raw = bytes(e.mc.read(XF + 16, 4 * N))
        l = np.frombuffer(raw[:2 * N], dtype=">i2")
        assert list(l[:p.xn]) == p.xl[:p.xn] and raw[2 * p.xn:2 * N] == b"\x5a" * (2 * (N - p.xn))
        if pool is POOL:
            r = np.frombuffer(raw[2 * N:], dtype=">i2")
            assert list(r[:p.xn]) == p.xr[:p.xn] and raw[2 * (N + p.xn):] == b"\x5a" * (2 * (N - p.xn))
        else:
            assert raw[2 * N:] == b"\x5a" * (2 * N)                         # a mono sample: no right channel's frames
    assert bytes(e.mc.read(XF + XF_BYTES, 8 * XF_STRIDE - XF_BYTES)) == b"\x5a" * (8 * XF_STRIDE - XF_BYTES)     # and no other voice's


def test_the_blend_is_the_pass_going_down_as_what_leads_to_its_start_comes_up():
    """The model's own frames, read against the sample: 80 of the pass, 256 that go from the one to the other a
    256th a frame, 16 of what the seam leads to."""
    x = [int(v) for v in POOL[0]]
    for knobs, rev in ((dict(start=30, length=60), False), (dict(length=60), False), (dict(sample=63, start=10, length=60), True),
                       (dict(sample=63, start=30), True)):
        p = ref.Player(ALONE, fade=True, live=True, floor=True, hq=12, xfade=True)
        p.note_on(loop=1, **dict(dict(sample=64), **knobs))
        p.block()
        for _ in range(WRITTEN + 2):
            p.move(knobs.get("start", 0), knobs.get("length", 127))
            p.block()
        a, b = region(knobs)
        w, c = p.xkey
        shift = w - (a if rev else b)
        assert p.xn == N and c - (b if rev else a) == shift and shift in ((0, -W) if rev else (0, W))
        first = w - (NEAR if rev else W + FAR)
        for k in range(N):
            i = first + k
            g = min(max(W + NEAR - k if rev else k - FAR, 0), W)
            assert p.xl[k] == x[i] + (((x[i - w + c] - x[i]) * g) >> 8) if 0 < g < W else p.xl[k] == (x[i - w + c] if g else x[i])


def test_a_seam_reached_before_the_blend_is_all_written_dips_as_it_did(cross, auto):
    """A loop of 23 ms: its first seam comes at block 35 and the blend is written at block 45. That seam is the
    mode image's, frame for frame; the next is blended."""
    knobs = dict(loop=1, sample=66, start=30, length=30)
    a, b = region(knobs)
    span = b - a
    assert 1024 < span < (WRITTEN - 4) * BLOCK
    script = hold(30, 30, 200)
    _, was, _ = play(auto, ALONE, script, **knobs)
    e, left, _ = play(cross, ALONE, script, **knobs)
    level = int(was.max())
    assert np.array_equal(left[:span + 64], was[:span + 64]) and was[:span + 64].min() < level // 100
    assert left[2 * span - 200:].min() == level and was[2 * span - 200:].min() < level // 100


def test_a_pass_inside_its_blend_is_left_alone_by_the_knobs(cross):
    """STRT and LEN turned while a pass is in its blend: nothing of the note moves until it has wrapped, then
    they are taken as a block that follows any other."""
    knobs = dict(loop=1, start=30, length=60)
    e = start(cross, POOL, **knobs)
    e.block(trig=1)
    blocks = 0
    while seam_of(e)["use"] != 2:
        e.block()
        blocks += 1
        assert blocks < 200
    held, seam = state(e), seam_of(e)
    e.set_slot(0, START, 50)
    e.set_slot(0, LENGTH, 70)
    inside = 0
    while seam_of(e)["use"] == 2:
        assert (state(e)["a"], state(e)["b"], state(e)["c"], state(e)["span"]) == (held["a"], held["b"], held["c"], held["span"])
        e.block()
        inside += 1
    assert 1 < inside <= REACH // BLOCK + 2
    now = state(e)                                                          # wrapped, to where the blend led; and the block after takes the knobs
    assert now["a"] == seam["to"] == held["c"] and now["frame"] < seam["to"] + BLOCK
    e.block()
    a, b = region(dict(start=50, length=70))
    assert state(e)["c"] == a and state(e)["span"] == b - a and seam_of(e)["n"] == STEP


def test_a_seam_that_moves_begins_its_blend_again(cross):
    knobs = dict(loop=1, start=30, length=60)
    e = start(cross, ALONE, **knobs)
    e.block(trig=1)
    for _ in range(WRITTEN + 2):
        e.block()
    was = seam_of(e)
    assert was["n"] == N
    e.block()
    assert seam_of(e) == was                                                # at rest: nothing more is written
    e.set_slot(0, START, 31)
    e.block()
    got = seam_of(e)
    assert got["n"] == STEP and got["to"] != was["to"]
    for k in range(1, 40):                                                  # LEN moving every block: begun again every block
        e.set_slot(0, LENGTH, 60 + k / 4)
        e.block()
        assert seam_of(e)["n"] == STEP and seam_of(e)["use"] == 0
    e.set_slot(0, LENGTH, 127)                                              # and a loop too short to be faded has none
    e.set_slot(0, START, 126.5)
    e.block()
    assert seam_of(e)["n"] == 0


def test_a_new_note_begins_with_no_blend(cross):
    e = start(cross, ALONE, loop=1, start=30, length=60)
    e.block(trig=1)
    while seam_of(e)["use"] != 2:
        e.block()
    e.block(trig=1)
    e.block()
    got = seam_of(e)
    assert got["n"] == 0 and got["use"] == 0 and state(e)["frame"] < region(dict(start=30, length=60))[0] + 2 * BLOCK


# ---- what it writes, and what it costs ----------------------------------------------------------------------------------

def test_it_writes_a_voices_blend_and_nothing_else_that_the_mode_image_does_not(cross, auto):
    """Two looping tracks and six idle ones, 200 blocks: every write the engine makes outside the voices' own state
    is a write the mode image's engine makes, or lies in the two voices' blends."""
    from unicorn import UC_HOOK_MEM_WRITE

    def writes(built):
        e = P.engine(built, pool=POOL)
        for t in range(m.N_VOICES):
            e.set_slot(t, SAMPLE, 64 + 63)
        for t, note in ((2, 57.5), (5, 60)):
            for slot, v in ((SAMPLE, 64), (START, 30), (LENGTH, 60), (LOOP, 1)):
                e.set_slot(t, slot, v)
            e.set_note(t, note)
        seen = set()
        e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, user: seen.update(range(address, address + size)))
        for b in range(200):
            e.block(trig=0x24 if b == 0 else 0)
        return {a for a in seen if not m.STACK_TOP - 0x10000 <= a < m.STACK_TOP}
    mine, was = writes(cross), writes(auto)
    more = mine - was
    blends = set().union(*(range(XF + XF_STRIDE * t, XF + XF_STRIDE * t + XF_BYTES) for t in (2, 5)))
    state_bytes = set().union(*(range(m.VOICES + m.VOICE_SIZE * t + ST + S_XN, m.VOICES + m.VOICE_SIZE * t + ST + 88) for t in range(8)))
    assert more and more <= blends | state_bytes and blends <= mine
    assert XF + 8 * XF_STRIDE <= m.KEPT and m.HQ_LONGS + 33 * 64 <= XF


def costs(image, factory, note, blocks, trig_every=None, **knobs):
    """Eight stereo tracks trigged together: -> instructions of each interrupt after the one the first trig is in."""
    r = Rig(image)
    rng = np.random.default_rng(11)
    r.load_pool({k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
    T.samplers(r, factory, loop=knobs.get("loop", 1))
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 3)
        r.set_slot(t, START, knobs.get("start", 0))
        r.set_slot(t, LENGTH, knobs.get("length", 127))
        r.set_note(t, note)
    r.block(0, 0)
    out = []
    for b in range(blocks):
        r.block(0xff if b == 0 or (trig_every and b % trig_every == 0) else 0, 0)
        out.append(sum(r.cost.values()))
    return out[1:]


CYCLE = 90


def cycle(image, factory, **knobs):
    """Eight pitched stereo loops trigged together every 90 blocks, the third time round: -> instructions of the
    block the notes start in, and of the two after."""
    c = costs(image, factory, 55.25, 2 * CYCLE + 8, trig_every=CYCLE, **knobs)[2 * CYCLE - 1:]
    return c[1], c[2], c[3]


def test_what_it_costs_an_interrupt(cross, auto, factory):
    """Instructions, of 117,348 for stock's heaviest; eight pitched stereo loops trigged together. The mode image's
    engine first, for what a block was. A loop cut out of a sample: a block its blend's frames are written in is
    2,100 over a steady one, for 44 blocks; a steady block is 600 over what it was (is the seam where it was, may
    the pass go in); and a block in a seam, which was 9,400 over for the dip, is 3,800 over."""
    was = costs(auto[0], factory, 55.25, 150, start=30, length=40)
    now = costs(cross[0], factory, 55.25, 150, start=30, length=40)
    steady_was, steady = int(np.median(was[60:])), int(np.median(now[WRITTEN + 8:]))
    writing = int(np.median(now[5:WRITTEN]))
    assert abs(steady_was - 102750) < 300 and 8500 < max(was[60:]) - steady_was < 10300     # the dip's blocks stood out
    assert 450 < steady - steady_was < 750
    assert 1900 < writing - steady < 2400                                                  # eight frames of two channels, eight tracks
    assert 3300 < max(now[WRITTEN + 8:]) - steady < 4300 and max(now[WRITTEN + 8:]) - steady < (max(was[60:]) - steady_was) // 2
    # a loop of the whole sample, which has nothing to blend with: 500 a block more, and nothing written
    was, now = costs(auto[0], factory, 55.25, 60), costs(cross[0], factory, 55.25, 60)
    assert all(0 < b - a < 700 for a, b in zip(was[2:], now[2:]))


def test_the_heaviest_blocks_are_what_they_were(cross, auto, factory):
    """The block eight notes start in, which is the most an interrupt comes to, and the blocks of the fade in after a
    cut start: 300 and 500 more. Nothing of a blend is written in a block a fade is on in. From a sample's own start
    there is no fade, and the blend's first frames are written the block after the notes start: 2,800 more there,
    in a block that was a steady one."""
    was, now = cycle(auto[0], factory, start=30, length=40), cycle(cross[0], factory, start=30, length=40)
    assert 0 < now[0] - was[0] < 500 and 0 < now[1] - was[1] < 700 and max(now) == now[0] < 0.975 * T.SWARM
    assert 2500 < now[2] - was[2] < 3100                                    # the fade in is over: the seam is worked out, and eight frames
    was, now = cycle(auto[0], factory, length=40), cycle(cross[0], factory, length=40)
    assert 0 < now[0] - was[0] < 500 and 2500 < now[1] - was[1] < 3100 and max(now) == now[0] < 0.925 * T.SWARM


def test_a_note_that_does_not_loop_costs_what_it_did(cross, auto, factory):
    was = costs(auto[0], factory, 55.25, 40, loop=0)
    got = costs(cross[0], factory, 55.25, 40, loop=0)
    assert all(0 <= b - a < 420 for a, b in zip(was, got))                             # two calls and three tests a voice a block


# ---- where it is ------------------------------------------------------------------------------------------------------

def test_section_7_is_the_mode_images_but_for_our_code(stock, cross, auto):
    image, syms = cross
    runs = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES, **m.ONE_CAVES, **m.QUICK_CAVES)
    runs.update(m.LEAN_CAVES, **{k: v for k, v in m.TIMED_CAVES.items() if k != "m"}, **m.CROSS_CAVES)
    spans = list(runs.values()) + [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE,
                                                         m.ISR_VOICE_LOOP_CALL + 2, m.ISR_AMP_CALL + 2)]
    diff = [m.BASE + k for k in range(len(image)) if image[k] != auto[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    lo, hi = m.CROSS_CAVES["o"]
    assert (lo, hi) == m.SPARE_RUNS[1] and hi - lo == 108 and lo <= syms["into"] < hi
    assert auto[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)] and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
    mine = {n.split(".")[0]: a for n, a in syms.items()}                    # (the compiler gives a routine it has specialised a longer name)
    for name in ("bake", "xstep", "xset", "seam", "outside", "into"):
        assert any(a <= mine[name] < b for a, b in runs.values()) and name not in auto[1]


def test_the_last_small_run_is_reached_by_nothing(stock, auto, descs, factory):
    """The third of the four runs of unreferenced functions the map lists as spare (the time image's routine has
    two, and the fourth is named four times in stock): nothing of stock's or of the mode image's names it or
    branches there, and it is never run or read while every machine plays."""
    run = m.CROSS_CAVES["o"]
    T.reached_by_nothing(stock, [run])
    T.reached_by_nothing(auto[0], [run])
    unreached = {(lo, hi): named for lo, hi, named, clean in deadcode.survey(stock, m.BASE, m.CODE_END, m.BASE + 4) if clean}
    assert unreached[run] == 0
    seen, _ = T.never_run(auto[0], [run], descs, factory)
    assert not seen


def test_the_image(official_path, official, cross):
    """The mode image's main program, and this sound engine."""
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, cross=True)
    main = build_main.patched_image(official.section(3), auto=True)
    assert sorted(regions) == [3, 7] and built.section(7) == cross[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    assert syms["bake"] == cross[1]["bake"]
