"""The "len" and "live" images: LEN, and STRT, act while a note plays (engine/sampler.c built with
LIVE, and LIVE_STRT).

On request

, for a loop, and the same played backwards.

Two builds ran on the unit before this one. LEN was right in both. STRT was not: the first moved
the place played from with the knob ("a tape fluttery noise that moves as fast as i move the
knob"); the second moved the region's two ends under the note ("a more abrupt ripping on smaller
values/loops"), which left a short loop either behind its region, playing straight on, or caught
by it and cut, a step of the knob at a time. Then he offered to leave the start alone.

So here a note is a row of passes. A pass begins at a place and is as long as the knobs have the
region. LEN moves the far end of the pass that is playing, at once. A loop's next pass begins
where the knobs have the start by then; the pass that is playing is left alone. The len image
keeps STRT the note's own and follows LEN only. The live image follows both.

The compiled engines run inside the real voice loop hook and are held bit-identical to the
reference model (emu/sampler_ref.py, Player(pool, fade=True, live=True, strt=...)) while the knobs
are moved under them, block by block, and to the fade image's engine with the knobs at rest.

A knob here is moved the way the unit is read to send it (docs/FINDINGS.md): a step at a time,
each through a filter of 3% a block. Nothing here says how it sounds.
"""
import shutil

import numpy as np
import pytest

from emu import sampler_ref as ref
from emu.engine import BLOCK
from tools import audiomap as m
from tools import build_engine
from test_fade import BUDGET, CASES, DECAY, IN, LENGTH, LOOP, MODE, OUT, POOL, SAMPLE, START, TUNE, jumps, level, start, tail

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

FRAMES = 6000                   # every sample of the pool but the short one
ST = 1712                       # the engine's state in a voice
RAMP = 40000 * 65536            # the ramp sample's height at the output: a loop of it jumps this far, once a pass


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def live(stock):
    return build_engine.patched_image(stock, live=True)


@pytest.fixture(scope="module")
def lenonly(stock):
    return build_engine.patched_image(stock, len_live=True)


@pytest.fixture(scope="module")
def fade(stock):
    return build_engine.patched_image(stock, fade=True)


def play(built, script, track=0, note=60, **knobs):
    """A note, then one block for each (STRT, LEN) of the script, the knobs set before it.
    -> (engine, left, right) from the block the note starts in."""
    e = start(built, track, note, **knobs)
    out = [e.block(trig=1 << track), e.block()]
    for st, ln in script:
        e.set_slot(track, START, st)
        e.set_slot(track, LENGTH, ln)
        out.append(e.block())
    out = np.array(out)
    assert not out[0].any()
    return e, out[1:, track, :].ravel(), out[1:, track + 1, :].ravel()


def model(e, script, track=0, strt=True, floor=False, hq=False, **knobs):
    p = ref.Player(POOL, fade=True, live=True, strt=strt, floor=floor, hq=hq)
    p.inc = e.player(track, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127),
              loop=knobs.get("loop", 0), mode=knobs.get("mode", 0))
    left, right = [], []
    for step in [None] + list(script):
        if step:
            p.move(*step)
        l, r = p.block()
        left += tail(l)
        right += tail(r) if r is not None else [0] * BLOCK
    return np.array(left), np.array(right), p


def state(e, track=0):
    """What the engine holds for a voice."""
    at = e.voice(track) + ST
    word = lambda o: int.from_bytes(e.mc.read(at + o, 2), "big", signed=True)
    return dict(playing=e.mc.r32(at + 20), frame=e.mc.r32(at + 8) >> 12, a=e.mc.r32(at + 36), b=e.mc.r32(at + 40), c=e.mc.r32(at + 44),
                fade=word(60), fstep=word(62), span=e.mc.r32(at + 64), duck=e.mc.read(at + 69, 1)[0])


def frame_of(st):
    return ref.scale(FRAMES, ref.knob(st))


def span_of(st, ln):
    return ref.scale(FRAMES - frame_of(st), ref.knob(ln))


def ramp(a, b, n):
    return [a + (b - a) * (k + 1) / n for k in range(n)]


def hold(st, ln, n):
    return [(st, ln)] * n


def turned(at, steps, every, blocks):
    """A knob as the unit is read to send it: `steps` clicks of one unit, one every `every` blocks, each smoothed in."""
    target, y, out = float(at), float(at), []
    for n in range(blocks):
        if n and n % every == 0 and abs(target - at) < abs(steps):
            target += 1 if steps > 0 else -1
        y += 0.03 * (target - y)
        out.append(round(y * 256) / 256)
    return out


def walk(seed, n, st=20.0, ln=100.0, jump=0.06):
    """The two knobs wandering: small steps mostly, a leap now and then, a rest now and then."""
    rng = np.random.default_rng(seed)
    out, rest = [], 0
    for _ in range(n):
        if rest:
            rest -= 1
        elif rng.random() < 0.1:
            rest = int(rng.integers(2, 12))
        else:
            if rng.random() < jump:
                st = float(rng.uniform(0, 110))
            else:
                st = float(np.clip(st + rng.normal(0, 1.5), 0, 120))
            if rng.random() < jump:
                ln = float(rng.uniform(2, 127))
            elif rng.random() < 0.5:
                ln = float(np.clip(ln + rng.normal(0, 3), 1, 127))
        out.append((round(st * 256) / 256, round(ln * 256) / 256))
    return out


# ---- the engines are the model, with the knobs moving under them -----------------------------------

SCRIPTS = {
    "STRT up, slowly": (dict(loop=1, sample=68, start=10), list(zip(ramp(10, 40, 60), [127] * 60)) + hold(40, 127, 200)),
    "STRT down, slowly": (dict(loop=1, sample=68, start=60), list(zip(ramp(60, 5, 80), [127] * 80)) + hold(5, 127, 200)),
    "STRT in one leap": (dict(loop=1, sample=68, start=10), hold(10, 127, 6) + hold(70, 127, 200)),
    "STRT leaping every block": (dict(loop=1, sample=64, start=5), list(zip(ramp(5, 110, 12), [127] * 12)) + hold(110, 127, 200)),
    "a short loop, STRT turned up": (dict(loop=1, sample=68, start=10, length=8), list(zip(turned(10, 40, 12, 600), [8] * 600))),
    "a short loop, STRT turned down": (dict(loop=1, sample=68, start=70, length=8), list(zip(turned(70, -40, 12, 600), [8] * 600))),
    "a loop with fades, STRT turned up": (dict(loop=1, sample=68, start=10, length=40), list(zip(turned(10, 40, 12, 600), [40] * 600))),
    "a loop with fades, STRT turned down": (dict(loop=1, sample=68, start=70, length=60), list(zip(turned(70, -40, 12, 600), [60] * 600))),
    "LEN down past the place played from": (dict(loop=1, sample=68, start=10), list(zip([10] * 60, ramp(127, 15, 60))) + hold(10, 15, 60)),
    "LEN down to a buzz and back": (dict(loop=1, sample=68, start=10), list(zip([10] * 300, turned(127, -125, 2, 300))) + list(zip([10] * 300, turned(2, 60, 3, 300)))),
    "LEN up": (dict(loop=1, sample=68, start=10, length=20), list(zip([10] * 40, ramp(20, 127, 40))) + hold(10, 127, 60)),
    "a one-shot, STRT turned": (dict(sample=64, start=10), list(zip(ramp(10, 50, 50), [127] * 50)) + hold(50, 127, 30)),
    "a one-shot, LEN pulled in behind it": (dict(sample=64), hold(0, 127, 60) + hold(0, 20, 20)),
    "a one-shot, LEN turned ahead of it": (dict(sample=64, length=100), list(zip([0] * 50, ramp(100, 60, 50))) + hold(0, 60, 60)),
    "backwards, LEN turned": (dict(loop=1, sample=59, length=100), list(zip([0] * 60, ramp(100, 50, 60))) + hold(0, 50, 200)),
    "backwards, STRT turned": (dict(loop=1, sample=59, length=100), list(zip(ramp(0, 60, 60), [100] * 60)) + hold(60, 100, 60)),
    "backwards, a short loop, LEN turned": (dict(loop=1, sample=59, start=30, length=10), list(zip([30] * 500, turned(10, 30, 10, 500)))),
    "backwards, both": (dict(loop=1, sample=63, start=10, length=90), walk(11, 150)),
    "ping-pong": (dict(loop=2, sample=68, start=20, length=60), walk(12, 200)),
    "ping-pong, leaps": (dict(loop=2, sample=68, start=20, length=60), walk(19, 200, jump=0.4)),
    "ping-pong, backwards": (dict(loop=2, sample=59, start=20, length=60), walk(21, 200, jump=0.3)),
    "ping-pong, short, STRT turned": (dict(loop=2, sample=68, start=10, length=8), list(zip(turned(10, 40, 12, 600), [8] * 600))),
    "stereo": (dict(loop=1, mode=1, start=5, length=90), walk(13, 150)),
    "stereo, backwards": (dict(loop=1, mode=1, sample=63, start=5, length=90), walk(14, 150)),
    "a walk, looped": (dict(loop=1, sample=64, start=20, length=100), walk(15, 250)),
    "a walk, once": (dict(sample=64, start=20, length=100), walk(16, 120, jump=0.02)),
    "a walk of leaps": (dict(loop=1, sample=68, start=20, length=100), walk(17, 200, jump=0.5)),
    "the short slot": (dict(loop=1, sample=70), walk(18, 150)),
    "LEN down to nothing": (dict(loop=1, sample=64), list(zip([0] * 80, ramp(127, 0, 80))) + hold(0, 0, 20) + hold(0, 60, 20)),
}


def same(e, left, right, want_l, want_r, p, knobs):
    assert np.array_equal(left, want_l)
    assert np.any(left)
    if knobs.get("mode") == 1:
        assert np.array_equal(right, want_r) and np.any(right)
    got = state(e)
    assert bool(got["playing"]) == p.playing
    if p.playing:
        assert (got["frame"], got["a"], got["b"], got["c"], got["span"], got["fade"], got["duck"]) == \
               (p.pos >> 12, p.pa, p.pb, p.pc, p.span, p.fade, int(p.duck))


@pytest.mark.parametrize("note", [60, 67, 48, 79])
@pytest.mark.parametrize("name", list(SCRIPTS))
def test_the_live_engine_is_the_reference_model_bit_for_bit(live, name, note):
    knobs, script = SCRIPTS[name]
    e, left, right = play(live, script, note=note, **knobs)
    same(e, left, right, *model(e, script, **knobs), knobs)


@pytest.mark.parametrize("note", [60, 72])
@pytest.mark.parametrize("name", list(SCRIPTS))
def test_the_len_engine_is_the_reference_model_bit_for_bit(lenonly, name, note):
    knobs, script = SCRIPTS[name]
    e, left, right = play(lenonly, script, note=note, **knobs)
    same(e, left, right, *model(e, script, strt=False, **knobs), knobs)


@pytest.mark.parametrize("note", [60, 72, 48])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_with_the_knobs_at_rest_both_are_the_fade_images_engine(live, lenonly, fade, case, note):
    knobs = CASES[case]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 44)
    _, b, br = play(fade, script, note=note, **knobs)
    for built in (live, lenonly):
        _, a, ar = play(built, script, note=note, **knobs)
        assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


def test_the_scripts_do_reach_every_way_through():
    seen = set()
    for name, (knobs, script) in SCRIPTS.items():
        p = ref.Player(POOL, fade=True, live=True)
        p.note_on(**{k: knobs.get(k, d) for k, d in (("sample", 64), ("start", 0), ("length", 127), ("loop", 0), ("mode", 0))})
        fresh = []
        plain = p._pass
        p._pass = lambda: (fresh.append((p.mode, p.dir == p.dir0)), plain())[1]
        p.block()
        for step in script:
            was = (p.duck, p.playing, p.pa, p.pb, p.dir, p.pos, p.pc)
            del fresh[:]
            p.move(*step)
            if p.pc != was[6] and (p.pa, p.pb, p.pos) == (was[2], was[3], was[5]):
                seen.add("the next pass moved, the playing one did not")
            if p.duck and not was[0]:
                seen.add("down")
            if was[0] and not p.duck and p.playing:
                seen.add("up")
            if fresh and not was[0] and p.pos != was[5]:
                seen.add("a short loop's next pass at once")
            if was[1] and not p.playing:
                seen.add("ended by the far end")
            if p.dir != was[4] and p.pos == was[5]:
                seen.add("a ping-pong turned where it was")
            del fresh[:]
            moved = p.pc != (p.pa if p.dir0 > 0 else p.pb)
            p.block()
            if any(mode == 2 for mode, _ in fresh):
                seen.add("a ping-pong took the new start when it was back")
            if any(mode == 1 for mode, _ in fresh) and moved:
                seen.add("a loop took the new start when it came round")
    assert seen == {"the next pass moved, the playing one did not", "down", "up", "a short loop's next pass at once",
                    "ended by the far end", "a ping-pong turned where it was", "a ping-pong took the new start when it was back",
                    "a loop took the new start when it came round"}


# ---- what went wrong on the unit, and does not here ------------------------------------------------

def seams(x):
    """Where a loop of the ramp turns: a jump far above the ramp's own slope. Frames from the note's start, the
    fade a note cut into at its start comes in with left out."""
    at = np.flatnonzero(jumps(x) > RAMP / FRAMES * 20) + 1
    return at[at > IN + 1]


def passes(x):
    """Frames from one turn to the next."""
    return np.diff(seams(x))


@pytest.mark.parametrize("steps", [40, -40])
def test_a_short_loop_keeps_looping_while_strt_is_turned(live, steps):
    """The second build's rip. A loop of 7 ms, STRT turned 40 steps at 8 a second. The region slides off under the
    note 1,900 frames; the second build played straight on after it one way and cut the note again and again the
    other. Here every pass is a pass long, the level never moves, and each pass begins where the knob had come to."""
    at = 10 if steps > 0 else 70
    script = list(zip(turned(at, steps, 12, 700), [8] * 700))
    spans = (span_of(at, 8), span_of(at + steps, 8))
    assert max(spans) < 1024 // 2                                       # too short for fades at its seam: a tone
    e, a, _ = play(live, script, sample=68, loop=1, start=at, length=8)             # the ramp: a seam shows as a jump
    lengths = passes(a)
    assert len(lengths) > 40
    assert lengths.max() <= max(spans) + 1 and lengths.min() >= min(spans) - 1      # every pass the length the knobs had it
    _, steady, _ = play(live, script, sample=66, loop=1, start=at, length=8)        # the steady level: a cut shows as a dip
    assert np.all(level(steady[IN:]) == 1.0)
    got = state(e)
    assert abs(script[-1][0] - (at + steps)) < 0.05                                 # the knob has all but come to rest
    assert got["c"] == frame_of(script[-1][0]) and got["a"] == got["c"]             # and the loop is where the knob is


def test_the_second_builds_rip_is_what_the_model_says_it_was():
    """Not the engine: the arithmetic of the build that ran on the unit, kept here so that what was heard has a
    number. The region's two ends moved under the note. Turned up, the note was left behind and played straight on."""
    a0, moved = frame_of(10), frame_of(50)
    span = span_of(10, 8)
    behind = moved - a0                                                 # the start has gone this far past the note
    assert behind > 5 * span                                            # five passes' worth of sample played through, not looped


def test_strt_on_a_long_loop_changes_no_frame_until_the_loop_comes_round(live):
    """The first build's flutter. The whole sample is the loop, so its end is the sample's end and does not move."""
    for turn in (ramp(20, 40, 30), ramp(40, 2, 30), [70.0] * 30, turned(20, 30, 4, 200),
                 [float(x) for x in np.random.default_rng(3).uniform(0, 110, 30)]):
        script = hold(20, 127, 3) + list(zip(turn, [127] * len(turn))) + hold(turn[-1], 127, 250)
        _, moved, _ = play(live, script, sample=68, loop=1, start=20)
        _, still, _ = play(live, hold(20, 127, len(script)), sample=68, loop=1, start=20)
        seam = FRAMES - frame_of(20)                                    # frames from the note's start to the sample's end
        d = np.flatnonzero(moved != still)
        assert len(d) and d[0] >= seam - 1 and d[0] <= seam + IN + BLOCK


def test_after_the_loop_comes_round_it_is_the_new_loop(live):
    e, moved, _ = play(live, hold(20, 127, 5) + hold(60, 127, 600), sample=68, loop=1, start=20)
    got = state(e)
    assert (got["a"], got["b"]) == (frame_of(60), FRAMES) and got["a"] <= got["frame"] < got["b"]
    span = FRAMES - frame_of(60)
    late = moved[FRAMES:]                                               # past the first turn, wherever the note was
    assert len(late) >= 3 * span
    assert np.array_equal(late[:span * 2], late[span:span * 3])        # it repeats every pass of the new region


def test_a_one_shot_is_not_touched_by_its_start(live):
    """A one-shot is one pass, begun where it began. With LEN at all of it, it runs to the sample's end whatever STRT does."""
    for turn in (ramp(10, 100, 40), ramp(60, 0, 40), [5.0] * 40):
        script = list(zip(turn, [127] * 40)) + hold(turn[-1], 127, 200)
        _, moved, _ = play(live, script, sample=64, start=10)
        _, still, _ = play(live, hold(10, 127, len(script)), sample=64, start=10)
        assert np.array_equal(moved, still) and np.any(moved)


# ---- the len image: STRT is the note's own ---------------------------------------------------------

@pytest.mark.parametrize("knobs", [dict(loop=1, sample=68, start=20, length=127), dict(loop=1, sample=68, start=20, length=8),
                                   dict(loop=1, sample=59, start=20, length=60), dict(loop=2, sample=68, start=20, length=30),
                                   dict(sample=64, start=20, length=80), dict(loop=1, mode=1, start=20, length=50)])
def test_on_the_len_image_strt_does_nothing_to_a_note_that_is_playing(lenonly, knobs):
    """Turned any way at all, for as long as the note lasts: the frames of the knob left alone."""
    n = 400
    for turn in (turned(20, 60, 5, n), turned(20, -20, 5, n), [float(x) for x in np.random.default_rng(8).uniform(0, 120, n)]):
        _, moved, mr = play(lenonly, list(zip(turn, [knobs["length"]] * n)), **knobs)
        _, still, sr = play(lenonly, hold(20, knobs["length"], n), **knobs)
        assert np.array_equal(moved, still) and np.array_equal(mr, sr) and np.any(moved)


def test_on_the_len_image_the_next_note_takes_strt_as_it_is(lenonly):
    e = start(lenonly, sample=68, start=20, loop=1)
    e.block(trig=1)
    e.block()
    e.set_slot(0, START, 70)
    for _ in range(5):
        e.block()
    assert state(e)["a"] == frame_of(20)                    # this note: where it was
    e.block(trig=1)
    e.block()
    assert state(e)["a"] == frame_of(70)                    # the next: where the knob is


@pytest.mark.parametrize("name", ["LEN down past the place played from", "LEN down to a buzz and back", "LEN up",
                                  "a one-shot, LEN pulled in behind it", "backwards, LEN turned", "LEN down to nothing"])
def test_len_is_the_same_on_both_images(live, lenonly, name):
    """Where STRT is not moved, the two engines put out the same frames."""
    knobs, script = SCRIPTS[name]
    _, a, _ = play(live, script, **knobs)
    _, b, _ = play(lenonly, script, **knobs)
    assert np.array_equal(a, b) and np.any(a)


# ---- LEN: as the first two builds had it, which passed on the unit ---------------------------------

@pytest.fixture(params=["live", "len"])
def either(request, live, lenonly):
    return live if request.param == "live" else lenonly


def test_len_turned_moves_a_loops_end_at_once(either):
    """With the note still inside the new region, the loop from then on is the loop a note started with that LEN makes."""
    _, moved, _ = play(either, hold(10, 100, 4) + hold(10, 50, 200), sample=68, loop=1, start=10, length=100)
    _, there, _ = play(either, hold(10, 50, 204), sample=68, loop=1, start=10, length=50)
    assert np.array_equal(moved, there)                     # four blocks in, both are well inside the shorter region
    _, longer, _ = play(either, hold(10, 100, 204), sample=68, loop=1, start=10, length=100)
    assert not np.array_equal(moved, longer)


def test_len_pulled_in_behind_a_loop_brings_it_back_to_its_start_without_a_click(either):
    e, a, _ = play(either, hold(0, 127, 100) + hold(0, 30, 200), sample=66, loop=1)     # the steady level: the gain is all there is to see
    la = level(a)
    at = 101 * BLOCK                                        # the block the knob is seen in
    assert np.all(la[IN:at] == 1.0)
    down = la[at:at + OUT + BLOCK]
    assert down[0] == 1.0 and down.min() == 0.0 and np.all(np.diff(down[:OUT + 1]) < 0)
    back = np.flatnonzero(la[at:] == 1.0)
    assert back[back > OUT][0] <= OUT + BLOCK + IN          # down, then up
    got = state(e)
    assert got["playing"] and got["b"] == frame_of(30) and got["frame"] < got["b"]
    _, ramped, _ = play(either, hold(0, 127, 100) + hold(0, 30, 200), sample=68, loop=1)    # the ramp: a jump would show
    assert jumps(ramped[at:at + OUT + 3 * BLOCK]).max() < RAMP / 20


def test_len_pulled_in_behind_a_one_shot_ends_it_without_a_click(either):
    e, a, _ = play(either, hold(0, 127, 100) + hold(0, 30, 30), sample=66)
    la = level(a)
    at = 101 * BLOCK
    assert np.all(la[:at + 1] == 1.0) and np.all(np.diff(la[at:at + OUT + 1]) < 0)
    assert not la[at + OUT:].any() and not state(e)["playing"]


def test_len_down_to_a_buzz_and_back_never_stops_the_loop(either):
    """What he does with it. The loop goes on through every length, and comes back up as long as the knob says."""
    knobs, script = SCRIPTS["LEN down to a buzz and back"]
    e, a, _ = play(either, script, **knobs)
    got = state(e)
    assert script[-1][1] > 61 and min(ln for _, ln in script) < 2.1
    assert got["playing"] and (got["b"] - got["a"], got["span"]) == (span_of(10, script[-1][1]),) * 2
    assert np.any(a[-8 * BLOCK:])


def test_a_knob_put_back_while_the_sound_is_going_down_lets_it_up_where_it_was(either):
    """Down first, then look again: if the far end is ahead of the note once more, the note is not sent back."""
    e, a, _ = play(either, hold(0, 127, 100) + hold(0, 30, 1) + hold(0, 127, 20), sample=68, loop=1)
    _, still, _ = play(either, hold(0, 127, 121), sample=68, loop=1)
    at = 101 * BLOCK
    assert np.array_equal(a[:at], still[:at])
    after = at + OUT + IN
    assert np.array_equal(a[after:], still[after:])         # the same place, the same frames, after the dip


def test_backwards_len_is_how_long_a_pass_is_too(either):
    """Played backwards a pass begins at the region's top and LEN is how far down it goes from there. Turned down,
    the pass that is playing ends that much sooner, and the next begins at the new top."""
    top, new = span_of(0, 100), span_of(0, 40)
    e = start(either, sample=59, loop=1, length=100)
    e.block(trig=1)
    blocks = 0
    for _ in range(5):
        e.block()
        blocks += 1
    assert state(e)["b"] == top
    e.set_slot(0, LENGTH, 40)
    while state(e)["b"] == top:                             # until the pass that was playing is over
        e.block()
        blocks += 1
        assert blocks < 400
    assert abs(blocks * BLOCK - new) <= BLOCK               # the new length from where it began, not the old one
    assert new + 5 * BLOCK < top - 5 * BLOCK
    got = state(e)
    assert (got["a"], got["b"]) == (0, new) and got["frame"] < new      # and the next pass is the new region


# ---- ping-pong -------------------------------------------------------------------------------------

def test_a_ping_pong_caught_by_its_far_end_turns_where_it_is(either):
    """No dip and no jump: a turn is a turn. The ramp would show a jump as a step many times its slope."""
    slope = RAMP / FRAMES
    script = hold(20, 100, 60) + hold(20, 30, 200)                         # the far end comes in behind it on the way out
    e, a, _ = play(either, script, sample=68, loop=2, start=20, length=100)
    assert jumps(a[IN:]).max() < slope * 1.05 and np.all(level(np.abs(a[IN:])) <= 1.0)
    got = state(e)
    assert got["playing"] and got["duck"] == 0 and got["fade"] == m.FADE_ONE


def test_a_ping_pong_takes_a_new_start_when_it_is_back_where_its_pass_began(live):
    script = hold(20, 60, 30) + hold(50, 60, 500)
    e, a, _ = play(live, script, sample=66, loop=2, start=20, length=60)       # the steady level
    got = state(e)
    assert got["playing"] and (got["a"], got["c"]) == (frame_of(50),) * 2 and got["b"] == frame_of(50) + span_of(50, 60)
    la = level(a)
    assert la[IN:].min() == 0.0 and la[-1] == 1.0                              # through a fade out and a fade in, once
    dips = np.flatnonzero(np.diff((la[IN:] < 1.0).astype(int)) == 1)
    assert len(dips) == 1


# ---- the rest --------------------------------------------------------------------------------------

def test_the_slot_is_never_read_past(live, lenonly):
    """The model reads its samples from lists and says so when a frame is outside the slot; the engines are that model."""
    for seed in range(40, 52):
        knobs = dict(loop=int(seed % 3), sample=(64, 63, 68, 59)[seed % 4], start=20, length=100)
        script = walk(seed, 160, jump=0.3)
        for built, strt in ((live, True), (lenonly, False)):
            e, left, _ = play(built, script, note=(60, 72, 84)[seed % 3], **knobs)
            want, _, p = model(e, script, strt=strt, **knobs)
            assert np.array_equal(left, want)
            got = state(e)
            if got["playing"]:
                assert 0 <= got["a"] < got["b"] <= FRAMES and 0 <= got["frame"] < FRAMES


def test_a_new_note_takes_the_knobs_as_they_are(either):
    """What a move left behind (a fade out, a move waiting for nothing) does not reach the next note."""
    e = start(either, sample=66, loop=1)
    e.block(trig=1)
    for _ in range(100):
        e.block()
    e.set_slot(0, LENGTH, 30)                               # the far end comes in behind the note: the fade out begins
    e.block()
    assert state(e)["duck"] == 1
    e.set_slot(0, LENGTH, 127)
    e.block(trig=1)
    first = level(e.block()[0])
    assert np.all(first == 1.0)                             # from the sample's start, at full level, at once
    got = state(e)
    assert (got["duck"], got["a"], got["b"], got["fade"]) == (0, 0, FRAMES, m.FADE_ONE)


def test_a_recording_track_is_left_alone(either):
    """REC is a bit of MODE: a take plays nothing, and the knobs move nothing in it."""
    e = start(either, sample=64, mode=2)
    e.block(trig=1)
    for st in (10, 60, 0, 127):
        e.set_slot(0, START, st)
        e.set_slot(0, LENGTH, 127 - st)
        assert not e.block()[0].any()
    assert not state(e)["playing"]


def test_other_tracks_are_not_moved(either):
    e = start(either, sample=64, loop=1)
    for slot, v in ((TUNE, 64), (SAMPLE, 68), (START, 0), (LENGTH, 127), (LOOP, 1), (MODE, 0), (DECAY, 127)):
        e.set_slot(3, slot, v)
    e.set_note(3, 60)
    out = [e.block(trig=0b1001)]
    for k in range(60):
        e.set_slot(0, START, k)
        e.set_slot(0, LENGTH, 127 - k)
        out.append(e.block())
    there = np.array(out)[1:, 3, :].ravel()
    _, alone, _ = play(either, hold(0, 127, 60), track=3, sample=68, loop=1)
    assert np.array_equal(there, alone[:len(there)]) and np.any(there)


def test_cost_on_the_audio_cpu(live, lenonly, fade):
    """Instructions in a block of the whole voice loop, one stereo voice playing, over the fade image's engine."""
    def count(built, script, **knobs):
        e = start(built, **knobs)
        e.block(trig=1)
        e.block()
        worst = 0
        for st, ln in script:
            e.set_slot(0, START, st)
            e.set_slot(0, LENGTH, ln)
            n0 = e.mc.insns
            e.block()
            worst = max(worst, e.mc.insns - n0)
        return worst
    still = hold(10, 127, 6)
    turning = list(zip(ramp(10, 40, 40), ramp(127, 60, 40)))
    base = count(fade, still, sample=64, start=10, mode=1)
    got = tuple(count(built, script, sample=64, start=10, mode=1) - base for built in (live, lenonly) for script in (still, turning))
    assert got == COST and base + max(got) < 8 * BUDGET              # all eight voices of the loop


COST = (80, 179, 82, 183)     # live and len, each with the knobs at rest (the region worked out and found the same) and with both turning


def test_the_code_is_in_two_more_runs_and_the_images_differ_there_only(official_path, official, stock, live, lenonly, fade):
    from tools import build
    quiet = lambda s: None
    muted = build.build(official_path, log=quiet, mute=True)[2]
    assert muted.section(7) == fade[0]                                  # the mute image's sound engine is the fade image's
    for flag, engine in (("live", live), ("len_live", lenonly)):
        raw, _, built, regions, syms = build.build(official_path, log=quiet, **{flag: True})
        assert sorted(regions) == [3, 7] and built.section(7) == engine[0]
        for sid in official.ids:
            if sid not in (3, 7):
                assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        assert built.section(3) == muted.section(3)                     # the main CPU's program is the mute image's
        for name, cave in (("live", "v"), ("pass", "u"), ("walls", "u")):
            lo, hi = m.LIVE_CAVES[cave]
            assert lo <= engine[1][name] < hi
        lo, hi = m.FADE_CAVES["w"]
        region = next(a for n, a in engine[1].items() if n.startswith("region"))
        assert lo <= region < hi and lo <= engine[1]["enter"] < hi
        spans = list(m.CAVES.values()) + list(m.REC_CAVES.values()) + list(m.FADE_CAVES.values()) + list(m.LIVE_CAVES.values())
        assert not any(a < d and c < b for k, (a, b) in enumerate(spans) for c, d in spans[k + 1:])
        spans += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
        diff = [k for k in range(len(stock)) if stock[k] != built.section(7)[k]]
        assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in spans) for k in diff)
    for lo, hi in m.LIVE_CAVES.values():
        assert fade[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
        assert stock[m.off(lo) - 2:m.off(lo)] == b"\x4e\x75" and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
    assert m.LIVE_CAVES["u"][1] == m.TWIN_MIX                           # right up to a routine the engine calls
    assert live[0] != lenonly[0]
