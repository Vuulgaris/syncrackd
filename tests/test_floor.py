"""The "floor" image: LEN stops at 3.




So 3.

Two places. The knob: LEN's descriptor on the main CPU gets a least value of 3, so the knob stops
there. The engine (engine/sampler.c built with FLOOR): LEN is taken as no less than 3 where a note
starts and where the knob is followed while it plays, for what does not pass the knob's range: an
LFO, a lock, a pattern saved before.

The compiled engine runs inside the real voice loop hook and is held bit-identical to the reference
model (emu/sampler_ref.py, Player(..., floor=True)), and to the live image's engine wherever LEN is
at the floor or over. A loop at the floor is 3/127 of what the sample has left after STRT, so on a
short sample, or with STRT far in, it is still short.
"""
import shutil

import numpy as np
import pytest

from emu import sampler_ref as ref
from tools import audiomap as m
from tools import build, build_engine, build_main, params
from tools import mainmap as mm
from test_fade import CASES
from test_live import FRAMES, SCRIPTS, hold, model, play, ramp, same, span_of, state

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

FLOOR = m.LEN_MIN


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def live(stock):
    return build_engine.patched_image(stock, live=True)


@pytest.fixture(scope="module")
def floor(stock):
    return build_engine.patched_image(stock, floor=True)


@pytest.mark.parametrize("note", [60, 72])
@pytest.mark.parametrize("name", list(SCRIPTS))
def test_the_engine_is_the_reference_model_bit_for_bit(floor, name, note):
    """Every script of the live image's, several of which take LEN under the floor and to nothing."""
    knobs, script = SCRIPTS[name]
    e, left, right = play(floor, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, **knobs), knobs)


@pytest.mark.parametrize("knobs", [dict(loop=1, sample=68, start=10), dict(sample=64), dict(loop=1, sample=59, start=30),
                                   dict(loop=2, sample=68, start=20), dict(loop=1, mode=1, start=5)])
@pytest.mark.parametrize("length", [0, 0.5, 1, 2, 2.996])
def test_a_note_started_with_len_under_the_floor_is_the_note_at_the_floor(floor, knobs, length):
    script = hold(knobs.get("start", 0), length, 40)
    _, a, ar = play(floor, script, length=length, **knobs)
    _, b, br = play(floor, hold(knobs.get("start", 0), FLOOR, 40), length=FLOOR, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


def test_on_the_live_image_those_notes_were_shorter_or_not_there(live):
    """What the floor is for: at 1 the loop was a few frames, at 0 nothing played."""
    e, a, _ = play(live, hold(10, 1, 20), loop=1, sample=68, start=10, length=1)
    assert state(e)["span"] == span_of(10, 1) < span_of(10, FLOOR)
    _, a, _ = play(live, hold(10, 0, 20), loop=1, sample=68, start=10, length=0)
    assert not a.any()


def test_len_turned_all_the_way_down_while_a_loop_plays_leaves_a_loop_at_the_floor(floor):
    knobs = dict(loop=1, sample=68, start=10)
    script = list(zip([10] * 200, ramp(127, 0, 200))) + hold(10, 0, 200)
    e, a, _ = play(floor, script, **knobs)
    got = state(e)
    assert got["playing"] and got["span"] == got["b"] - got["a"] == span_of(10, FLOOR)
    assert np.any(a[-64 * 32:])


def test_the_floor_is_a_share_of_what_the_sample_has_left(floor):
    """3/127 of the frames from STRT to the sample's end: 140 of this pool's 6000 from the start, fewer with STRT further in."""
    assert span_of(0, FLOOR) == ref.scale(FRAMES, FLOOR << 8) == 140
    for st in (0, 40, 100):
        e, _, _ = play(floor, hold(st, 0, 4), loop=1, sample=68, start=st, length=0)
        assert state(e)["span"] == span_of(st, FLOOR)
    assert span_of(100, FLOOR) < span_of(40, FLOOR) < span_of(0, FLOOR)


@pytest.mark.parametrize("note", [60, 48])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_with_len_at_the_floor_or_over_it_is_the_live_images_engine(floor, live, case, note):
    knobs = CASES[case]
    assert knobs.get("length", 127) >= FLOOR
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 44)
    _, a, ar = play(floor, script, note=note, **knobs)
    _, b, br = play(live, script, note=note, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


@pytest.mark.parametrize("name", ["LEN down past the place played from", "LEN up", "backwards, LEN turned", "a walk, looped", "stereo", "ping-pong"])
def test_with_len_moving_at_the_floor_or_over_it_is_the_live_images_engine(floor, live, name):
    knobs, script = SCRIPTS[name]
    assert min(ln for _, ln in script) >= FLOOR
    _, a, ar = play(floor, script, **knobs)
    _, b, br = play(live, script, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


# ---- the knob, and the image -----------------------------------------------------------------------

def test_lens_knob_stops_at_the_floor_and_no_other_descriptor_moves(official):
    stock3 = official.section(3)
    was = params.machines(build_main.patched_image(stock3, mute=True)[0], "1.42")
    now = params.machines(build_main.patched_image(stock3, floor=True)[0], "1.42")
    length = next(p for p in now[44] if p.short == "LEN")
    assert (length.slot, length.min, length.max, length.default) == (21, FLOOR, 127, 127)
    assert [p for t in now for p in now[t] if p not in was[t]] == [length]
    assert next(p for p in was[44] if p.short == "LEN").min == 0


def test_the_image_is_the_live_image_but_for_that_number_and_our_code(official_path, official, stock, live, floor):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, live=True)[2]
    raw, _, built, regions, syms = build.build(official_path, log=quiet, floor=True)
    assert sorted(regions) == [3, 7] and built.section(7) == floor[0] and was.section(7) == live[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    at = mm.off(mm.SAMP_RECORDS + 0x34 * 3 + 8)                         # LEN's record, its least value
    diff = [k for k in range(len(was.section(3))) if was.section(3)[k] != built.section(3)[k]]
    assert diff == [at + 2] and built.section(3)[at:at + 4] == (FLOOR << 8).to_bytes(4, "big")
    spans = list(m.CAVES.values()) + list(m.REC_CAVES.values()) + list(m.FADE_CAVES.values()) + list(m.LIVE_CAVES.values())
    # and the three pointers to it, which move with the code
    spans += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    diff = [k for k in range(len(stock)) if live[0][k] != floor[0][k]]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in spans) for k in diff)
