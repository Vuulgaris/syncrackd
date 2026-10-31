"""The stay image: the gear image with a ONCE, a step's or the track's, used up only where the sequencer plays a step."""
import hashlib
import shutil

import pytest

import test_once as O
from test_once import MSG, NONE, ON, ONCE, SLOT, SPENT
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

PLACE = 0x444e1234  # a place for the event, as the routine that brings a track up to date hands one
MODE = mm.MODE_SLOT


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=10)


def play(r, step, place, track=None):
    """The step routine from its test of the event on, as one of its two callers has it: `place` is its fifth argument, 0
    from the sequencer. -> the event's locks, [(slot, value)].
    """
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
    assert raw[20 + 8 * n:] == b"\x77" * (0x400 - 20 - 8 * n)
    return [(int.from_bytes(raw[20 + 8 * k:][:2], "big"), int.from_bytes(raw[22 + 8 * k:][:2], "big")) for k in range(n)]


@pytest.mark.parametrize("track, step", [(2, 0), (0, 0), (7, 0), (5, 9)])
def test_a_once_stays_where_a_step_is_only_brought_up_to_date_and_goes_where_the_sequencer_plays_it(main, track, step):
    r = O.page(main, track=track)
    r.lay(step, ONCE)
    was = r.table()
    for _ in range(3):  # a change to the track, and another: the lock is as it was made
        assert play(r, step, PLACE) == [(SLOT, ONCE)]  # (the event has it: stock's gathering is not touched)
        assert r.table() == was and r.dirty == r.arm == [0] * 8
        assert r.wait() == MSG and r.lock_at(step) == ONCE
    assert play(r, step, 0) == [(SLOT, ONCE)]  # the sequencer: played as a step locked on, and spent
    assert r.lock_at(step) == SPENT and r.dirty == [int(t == track) for t in range(8)]
    assert r.wait() == MSG and r.lock_at(step) == NONE and r.dirty == [0] * 8


def test_a_step_locked_on_or_off_is_as_it_was_either_way(main):
    r = O.page(main, track=3)
    r.lay(0, ON), r.lay(4, O.OFF)
    was = r.table()
    for place in (PLACE, 0):
        assert play(r, 0, place) == [(SLOT, ON)] and play(r, 4, place) == [(SLOT, O.OFF)]
        assert r.table() == was and r.dirty == r.arm == [0] * 8


def test_a_tracks_own_once_waits_for_the_sequencer(main):
    track = 4
    r = O.page(main, track=track)
    r.lay(6, 0x4000, slot=20)  # a step with a lock of its own, and step 2 with none
    r.mc.write(mm.ONCE_ARM + track, b"\x01")
    armed = [int(t == track) for t in range(8)]
    for _ in range(2):
        assert play(r, 2, PLACE) == [] and r.arm == armed  # brought up to date: nothing added, the track still waits
        assert play(r, 6, PLACE) == [(20, 0x4000)] and r.arm == armed
    assert play(r, 6, 0) == [(20, 0x4000), (SLOT, ON)] and r.arm == [0] * 8  # the sequencer: this step records, once
    assert play(r, 2, 0) == [] and play(r, 6, 0) == [(20, 0x4000)]
    r.mc.write(mm.ONCE_ARM + track, b"\x01")
    assert play(r, 2, 0) == [(SLOT, ON)] and r.arm == [0] * 8  # and a step with no locks the same


def test_old_locks_of_mode_go_at_the_next_message_with_no_once_spent(main):
    """The srr image's eight bytes, set by the per-block routine when it makes a track's word from MODE."""
    track = 1
    r = O.page(main, track=track)
    r.lay(3, 0x1f00, slot=MODE), r.lay(40, 0x0300, slot=MODE), r.lay(3, ON), r.lay(3, 0x4000, slot=20)
    r.lay(3, 0x1f00, slot=MODE, track=6)
    assert r.wait() == MSG and r.lock_at(3, MODE) == 0x1f00  # nothing says so yet: nothing is done
    r.mc.write(mm.SRR_DIRTY + track, b"\x01")
    assert r.dirty == [0] * 8  # no ONCE was spent
    assert r.wait() == MSG
    assert r.lock_at(3, MODE) == NONE and r.lock_at(40, MODE) == NONE  # the track's locks of MODE: gone
    assert r.lock_at(3) == ON and r.lock_at(3, 20) == 0x4000 and r.lock_at(3, MODE, track=6) == 0x1f00
    assert bytes(r.mc.read(mm.SRR_DIRTY, 8)) == bytes(8)
    r.lay(8, 0x2000, slot=MODE)  # a lock of the reduction made after: it stays
    assert r.wait() == MSG and r.lock_at(8, MODE) == 0x2000


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=10)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=9)
    assert hashlib.sha256(was_raw).hexdigest().startswith("5ef3a04c")
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and len(new) == len(old)
    spans = [mm.CAVE_ONCE, mm.CAVE_STAY, (mm.STEP_LOCKS_PUSH, mm.STEP_LOCKS_PUSH + 6), (mm.STEP_NO_LOCKS, mm.STEP_NO_LOCKS + 4),
             (mm.MAIN_LOOP_WAIT, mm.MAIN_LOOP_WAIT + 6)]
    assert not [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert mm.CAVE_STAY[0] <= syms["once_clean"] < mm.CAVE_STAY[1] and mm.CAVE_ONCE[0] < syms["once_loop"] < mm.CAVE_ONCE[1]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
