"""The firstrec image: the handrec image with PLAY recording a ONCE on the first step on the first pass, and only then.

PLAY with a ONCE on the first step records the first pass, and only that pass.

Read before (docs/FINDINGS.md, the recprobe tool and the playrec image): a start queues for each track the record the
step routine's other caller built last (at STOP or a listener's pass), with the step's locks; the step routine itself
first plays the second step. That record carries a ONCE and records, and nothing spent it there, so the sequencer's
play of the step a pass later recorded again; and, on every playrec build, the page's REC at ONCE (the track's own,
which the sequencer uses up at the first step it plays itself: the second pass's first) was armed too, INFERRED from
"the record button switches off right when I start" on the handrec image. The handrec image takes that ONCE at a start.

Now the other caller's step is kept a track (first_keep, 0xff for a step with no locks), a start spends a ONCE on the
step of each sampler track's queued record that has a trig (first_spend, from hand_start), and the sequencer's own play
of that step on the next pass has the main task take the spent lock off (first_late): its event has it, no mark.

Held here, stock's step routine run as it is: each of those; the stay image as it was for the other caller; the main
program differing from the handrec image's only in the once run, the long image's run and the calls into them.

Not held: that the queued record's ONCE records the first pass (it did on the playrec image's second build), and one take in all. For the unit.
"""
import shutil

import pytest

import test_once as O
from test_once import NONE, ON, ONCE, SLOT, SPENT
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def main(official):
    assert official.version == "1.42"
    return build_main.patched_image(official.section(3), xfade=82)


def rig(main, track):
    r = O.page(main, track=track)
    for lo in (mm.SEQ_STATE & ~0xfff, mm.SEQ_PLACES & ~0xfff, mm.PATTERN_DATA & ~0xfff):
        try:
            r.mc.map(lo, 0x1000)
        except Exception:
            pass
    for t in range(13):
        r.mc.write(mm.SEQ_PLACES + 80 * t, bytes(80))
    r.mc.w32(mm.PATTERN_DATA, O.DATA)
    return r


def play(r, step, place, track=None):
    """The step routine from its test of the event on, `place` its fifth argument (0 from the sequencer).
    -> the event's locks, [(slot, value)]."""
    mc, track = r.mc, r.track if track is None else track
    sp = O.STACK[1] - 0x800
    mc.write(O.LOCKS, b"\x77" * 0x400)
    mc.write(sp - 0x40, b"\x66" * 0x140)
    mc.w32(sp + 76, place)
    regs = {2: 0x22220002, 3: step, 4: track, 5: 0x55550005, 6: 0x66660006, 10: O.DATA, 11: 0x33330003, 12: 0x44440004,
            13: 0x55550005, 14: O.LOCKS, 15: sp}
    for n, v in regs.items():
        mc.set_reg(n, v)
    mc.run(O.FRAGMENT, mm.STEP_JOINED)
    assert {n: mc.reg(n) for n in regs} == regs
    assert bytes(mc.read(sp, 0x100)) == b"\x66" * 76 + place.to_bytes(4, "big") + b"\x66" * 176
    raw = bytes(mc.read(O.LOCKS, 0x400))
    n = int.from_bytes(raw[8:12], "big")
    return [(int.from_bytes(raw[20 + 8 * k:][:2], "big"), int.from_bytes(raw[22 + 8 * k:][:2], "big")) for k in range(n)]


def place(t):
    return mm.SEQ_PLACES + 80 * t


def start(r, queued):
    """A start: its store of the state through hand_start, with a trig in the records of the tracks in `queued`."""
    for t in queued:
        r.mc.w32(place(t) + 4, 1)
    regs = {0: 1, 1: 0x11110001, 2: 0x22220002, 9: 0x99990009, 10: 0xaaaa000a}
    for n, v in regs.items():
        r.mc.set_reg(n, v)
    r.mc.call(r.syms["hand_start"])
    assert r.mc.r32(mm.SEQ_STATE) == 1 and {n: r.mc.reg(n) for n in regs} == regs


def v(r, name):
    return list(r.mc.read(r.syms[name], 8))


@pytest.mark.parametrize("track, step", [(0, 0), (3, 0), (7, 0), (5, 9)])
def test_a_start_spends_the_once_its_queued_record_plays_and_the_next_pass_has_it_taken_off(main, track, step):
    r = rig(main, track)
    r.lay(step, ONCE)
    for _ in range(3):                                          # STOP's pass and a listener's: nothing spent, as on the stay image
        assert play(r, step, place(track)) == [(SLOT, ONCE)]
        assert r.lock_at(step) == ONCE and r.dirty == [0] * 8
    assert v(r, "first_kept")[track] == step
    start(r, [track])
    assert r.lock_at(step) == SPENT and r.dirty == [0] * 8
    assert v(r, "first_step")[track] == step and v(r, "first_late_v") == [int(t == track) for t in range(8)]
    assert play(r, step + 1, 0) == [] and r.dirty == [0] * 8    # the sequencer's next step: still waiting
    assert play(r, step, 0) == [(SLOT, SPENT)]                  # the step again, a pass on: no mark, and taken off
    assert r.dirty == [int(t == track) for t in range(8)] and v(r, "first_late_v") == [0] * 8


def test_a_start_spends_nothing_where_no_trig_is_queued_or_the_step_is_on_off_or_has_no_locks(main):
    r = rig(main, 2)
    r.lay(0, ONCE)
    play(r, 0, place(2))
    start(r, [])                                                # no trig queued for it
    assert r.lock_at(0) == ONCE and v(r, "first_late_v") == [0] * 8
    for word in (ON, O.OFF):
        r.lay(4, word)
        play(r, 4, place(2))
        start(r, [2])
        assert r.lock_at(0) == ONCE and r.lock_at(4) == word and v(r, "first_late_v") == [0] * 8
    play(r, 6, place(2))                                        # a step with no locks
    assert v(r, "first_kept")[2] == 0xff
    start(r, [2])
    assert r.lock_at(0) == ONCE and v(r, "first_late_v") == [0] * 8


def test_a_track_that_holds_no_sampler_is_left_alone(main):
    r = rig(main, 1)
    r.lay(0, ONCE)
    play(r, 0, place(1))
    r.mc.write(mm.PARAM_SENT + 142 * 1 + 62, bytes((10, 0)))  # another machine
    start(r, [1])
    assert r.lock_at(0) == ONCE and v(r, "first_late_v") == [0] * 8


def test_a_start_still_takes_the_pages_once_and_a_held_take(main):
    r = rig(main, 4)
    r.mc.write(mm.ONCE_ARM, b"\x01" * 8)
    r.mc.write(mm.HAND_HOLD, b"\xff" * 36)
    start(r, [])
    assert v(r, "once_vars") == [0] * 8 and bytes(r.mc.read(mm.HAND_HOLD, 36)) == bytes(36)


def test_the_sequencers_own_play_spends_as_before(main):
    r = rig(main, 4)
    r.lay(5, ONCE)
    assert play(r, 5, 0) == [(SLOT, ONCE)] and r.lock_at(5) == SPENT and r.dirty == [int(t == 4) for t in range(8)]


def test_the_image(official_path, main):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=82)[2]
    was = build.build(official_path, log=quiet, xfade=81)[2]
    assert new.section(7) == was.section(7) and new.section(3) == main[0]
    n, o = new.section(3), was.section(3)
    spans = [mm.CAVE_ONCE, mm.CAVE_LONG, (mm.STEP_LOCKS_PUSH, mm.STEP_LOCKS_PUSH + 6), (mm.STEP_NO_LOCKS, mm.STEP_NO_LOCKS + 4),
             (mm.MAIN_LOOP_WAIT, mm.MAIN_LOOP_WAIT + 6)] + [(a, a + 6) for a in mm.SEQ_STARTS]
    assert [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not any(lo <= mm.BASE + k < hi for lo, hi in spans)] == []
    assert main[1]["hand_rec"] == mm.HAND_REC and main[1]["hand_hold"] == mm.HAND_HOLD
