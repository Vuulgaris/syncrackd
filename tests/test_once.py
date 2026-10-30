"""The once image: REC's third setting, ONCE (engine/once.S, engine/onceclean.c, engine/recpage.c under ONCE).

On request


What runs here, all from the built image:
- the page: the knob's three settings and their words, on held steps and on the track, with stock's lock routines
  run as they are on a table laid out as they index it (tests/test_reclock.py's rig);
- the sequencer: the stretch of stock's routine that plays a step, from its test of the event to where both of its
  ways go on (0x4008bc18..0x4008bc6e), run as it is with our two places in it, and stock's routine that gathers a
  step's locks under it;
- the main task's side: our wait, with stock's own wait played by the test, and under it stock's routine for a lock
  removed by hand, and the two of stock's that give a track's steps;
- stock's per-block loop that writes the hold flag (tests/test_save.py), for what the audio CPU is sent;
- the audio CPU's engine, which is the feed image's, for the take.

Played by the test, not run: the main task's loop around the wait, and whatever calls the step routine.
"""
import shutil

import numpy as np
import pytest

import test_pagerec as P
from emu.machine import boundaries
from test_fade import MODE
from test_page import HEAP, KEYS, MANAGER, PAGE, STACK, STEPS
from test_reclock import LOCKS, NONE, NOTE, PATTERN_OBJ, REC_KNOB, SRC_KNOB, TABLE, WORDS
from test_recorder import STRIDE
from test_save import IDLE, hold_loop
from test_stops import LAYOUTS, StopsPage
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm
from unicorn import UC_HOOK_CODE

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER, OTHER = 44, 4
SLOT = m.K_REC
ON, OFF, ONCE, SPENT = m.REC_WORD_ON, m.REC_WORD_OFF, mm.ONCE_WORD, mm.ONCE_SPENT
REC, STEREO = m.MODE_REC, m.MODE_STEREO
P_REC = m.PARAM_KNOBS + 2 * SLOT
FRAGMENT = 0x4008bc18                           # tstl %fp: the step routine with an event or none
DATA = TABLE - 15301                            # the pattern's data, as the step routine holds it in a2
X = 0x41234560                                  # the step routine's own argument at sp + 80: only pushed on
MSG = HEAP + 0xe800                             # a message, as stock's wait answers one
NUMBER, STEPS_AT = 0, MANAGER + 13204           # the selected pattern, and where stock's two routines put its tracks' steps
GAIN_KNOB, TAKE_KNOB, DEST_KNOB, BANK_KNOB = 6, 7, 2, 4


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, once=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, feed=True)


@pytest.fixture(scope="module")
def audio(official):
    return build_engine.patched_image(official.section(7), stops=True)


class OncePage(StopsPage):
    """The page rig on the sampling page, with what the sequencer's side and the main task's side need: the block the
    audio CPU is sent (for a track's machine), the eight tracks' steps objects where stock's own routines look for
    them, and stock's wait."""

    def __init__(self, built, machines=None, **kw):
        self.once_writes, self.waits = [], []
        super().__init__(built, LAYOUTS["a hole in each stack"][0], **kw)
        mc = self.mc
        mc.w32(PAGE + mm.PAGE_INDEX, 1)
        mc.w32(mm.SAVE_STATE, IDLE)
        mc.map(mm.PARAM_SENT & ~0xfff, 0x1000)
        self.sent = {t: SAMPLER if t < 8 else 0 for t in range(12)}
        self.sent.update(machines or {})
        for t, machine in self.sent.items():
            mc.write(mm.PARAM_SENT + STRIDE * t + 62, bytes((machine, 0)))
        self.stub(0x4016eb0a, lambda: 0x41005a00)
        self.stub(0x400c2154, lambda obj: NUMBER if obj == 0x41005a00 else 999)
        for t in range(12):
            steps = STEPS_AT + 1664 * NUMBER + 112 * (t + 1)
            mc.w32(steps + 44, PATTERN_OBJ), mc.w32(steps + 56, t)
        self.stub(mm.MAIN_WAIT, lambda queue: self.waits.append(queue) or MSG)
        mc.set_exits([mc.ret, mm.STEP_JOINED])

    def wrote(self, uc, access, address, size, value, user):
        if mm.ONCE_ARM <= address < mm.ONCE_ARM + mm.ONCE_VARS:
            self.once_writes.append((address - mm.ONCE_ARM, size, value & 0xff))
        else:
            super().wrote(uc, access, address, size, value, user)

    def counted(self, run):
        """-> what `run` answers, and the instructions it took (a routine the test plays is two)."""
        n = [0]
        hook = self.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, address, size, user: n.__setitem__(0, n[0] + 1))
        try:
            return run(), n[0]
        finally:
            self.mc.uc.hook_del(hook)

    @property
    def arm(self):
        return list(self.mc.read(mm.ONCE_ARM, 8))

    @property
    def dirty(self):
        return list(self.mc.read(mm.ONCE_DIRTY, 8))

    def table(self):
        return bytes(self.mc.read(TABLE, 13 * mm.LOCK_TRACK))

    def lay(self, step, word, slot=SLOT, track=None):
        """A lock put there the way stock makes one: its own routine, by (pattern, track, step, slot, value)."""
        self.mc.call(mm.LOCK_TABLE_MAKE, PATTERN_OBJ, self.track if track is None else track, step, slot, word)

    def play(self, step, track=None, event=True):
        """The step is played: stock's routine from its test of the event on. -> the event's locks, [(slot, value)]."""
        mc, track = self.mc, self.track if track is None else track
        sp = STACK[1] - 0x800
        mc.write(LOCKS, b"\x77" * 0x400)
        mc.write(sp - 0x40, b"\x66" * 0x140)
        mc.w32(sp + 80, X)
        regs = {2: 0x22220002, 3: step, 4: track, 5: 0x55550005, 6: 0x66660006, 10: DATA, 11: 0x33330003, 12: 0x44440004,
                13: 0x55550005, 14: LOCKS if event else 0, 15: sp}
        for n, v in regs.items():
            mc.set_reg(n, v)
        self.cost = self.counted(lambda: mc.run(FRAGMENT, mm.STEP_JOINED))[1]
        self.kept = {n: mc.reg(n) for n in regs} == regs and bytes(mc.read(sp, 0x100)) == b"\x66" * 80 + X.to_bytes(4, "big") + b"\x66" * 172
        if not event:
            return None
        raw = bytes(mc.read(LOCKS, 0x400))
        assert raw[:8] == b"\x77" * 8 and raw[12:20] == b"\x77" * 8
        n = int.from_bytes(raw[8:12], "big")
        assert raw[20 + 8 * n:] == b"\x77" * (0x400 - 20 - 8 * n)                 # nothing past the count
        return [(int.from_bytes(raw[20 + 8 * k:][:2], "big"), int.from_bytes(raw[22 + 8 * k:][:2], "big")) for k in range(n)]

    def wait(self):
        """The main task's wait for a message, as its loop calls it. -> what it answers."""
        self.notes.clear()
        got, self.cost = self.counted(lambda: self.mc.call(self.syms["once_loop"], mm.MAIN_QUEUE))
        assert self.waits.pop() == mm.MAIN_QUEUE and not self.waits
        return got


def page(built, **kw):
    return OncePage(built, **kw)


# ---- the knob ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("track", [0, 7])
def test_the_tracks_rec_has_three_settings_and_their_words(main, track):
    r = page(main, track=track, mode=STEREO)
    assert r.rec() == "OFF"
    assert r.twist(REC_KNOB, 1) == 1
    assert r.rec() == "ON" and r.mode == STEREO | REC and r.popped[-1] == ("REC", "ON") and r.arm == [0] * 8
    r.twist(REC_KNOB, 1)                                            # ONCE: the bit of MODE off, the track's byte set
    assert r.rec() == "ONCE" and r.mode == STEREO and r.popped[-1] == ("REC", "ONCE")
    assert r.arm == [int(t == track) for t in range(8)]
    shown = len(r.popped)
    r.twist(REC_KNOB, 1)                                            # the end of the knob
    assert r.rec() == "ONCE" and r.mode == STEREO and len(r.popped) == shown and r.arm[track] == 1
    r.twist(REC_KNOB, -1)
    assert r.rec() == "ON" and r.mode == STEREO | REC and r.popped[-1] == ("REC", "ON") and r.arm == [0] * 8
    r.twist(REC_KNOB, -1)
    assert r.rec() == "OFF" and r.mode == STEREO and r.popped[-1] == ("REC", "OFF")
    assert r.changes == [REC, -REC, REC, -REC] and not r.rec_locks and not r.table_writes and not r.locks and not r.stray


def test_a_fast_turn_goes_from_off_to_once_and_back_and_the_bit_of_mode_is_never_set(main):
    r = page(main)
    r.twist(REC_KNOB, 3)
    assert r.rec() == "ONCE" and r.arm[0] == 1 and r.mode == 0 and not r.changes and r.popped == [("REC", "ONCE")]
    r.twist(REC_KNOB, -5)
    assert r.rec() == "OFF" and r.arm == [0] * 8 and not r.changes and r.popped == [("REC", "ONCE"), ("REC", "OFF")]
    r.popups = False
    r.twist(REC_KNOB, 2)
    assert r.arm[0] == 1 and len(r.popped) == 2                    # no pop-up where stock shows none


def test_a_held_steps_rec_has_three_settings_and_only_slot_24_is_locked(main):
    r = page(main, track=3, mode=STEREO)
    r.hold(5)
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {5: ON} and r.rec() == "ON"
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {5: ONCE} and r.rec() == "ONCE" and r.count(5) == 1
    assert r.notes[-1] == (NOTE, SLOT, 3)                          # stock tells the pattern's listeners, as for any lock
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {5: ONCE} and r.count(5) == 1
    # MODE and SRC are not locked by it, the track is as it was, and no byte of the track's ONCE moves
    assert not r.locks and not r.locked and not r.changes and r.mode == STEREO and not r.others and not r.once_writes
    assert r.edited and r.done and not r.stray
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {5: ON} and r.rec() == "ON"
    r.twist(REC_KNOB, -1)                                           # as the track: no lock
    assert not r.rec_locks and r.count(5) == 0 and r.rec() == "OFF"
    r.twist(REC_KNOB, 2)                                            # two at once
    assert r.rec_locks == {5: ONCE}
    r.hold()
    assert r.rec() == "OFF"                                         # with no step held it is the track's


def test_on_a_track_in_record_a_step_can_be_off_as_the_track_or_once(main):
    r = page(main, mode=REC)
    r.hold(12)
    assert r.rec() == "ON"
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {12: OFF} and r.rec() == "OFF"
    r.twist(REC_KNOB, 1)
    assert not r.rec_locks and r.rec() == "ON"
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {12: ONCE} and r.rec() == "ONCE" and r.mode == REC and not r.changes
    r.twist(REC_KNOB, -1)
    assert not r.rec_locks and r.rec() == "ON"


def test_every_held_step_gets_its_own_and_a_step_with_no_trig_gets_one_first(main):
    r = page(main)
    r.hold(2, 3, 40)
    r.trigs = {2, 40}
    r.put(40, ON)                                                   # one of them was locked on already
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {2: ON, 3: ON, 40: ONCE}                 # each one setting up from where it was
    assert r.locked == [("trig", 3, 0)] and r.trigs == {2, 3, 40}
    r.length = 16
    r.hold(4, 20)
    r.twist(REC_KNOB, 2)
    assert r.rec_locks == {2: ON, 3: ON, 4: ONCE, 40: ONCE}        # a step past the pattern's length is no held step


def test_a_held_step_on_a_track_at_once_reads_as_the_track_and_can_be_locked_on_or_off(main):
    r = page(main)
    r.twist(REC_KNOB, 2)
    r.hold(9)
    assert r.rec() == "ONCE" and not r.rec_locks
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {9: ON} and r.rec() == "ON"
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {9: OFF} and r.rec() == "OFF" and r.arm[0] == 1


@pytest.mark.parametrize("word, says", [(SPENT, None), (0x1234, None), (0x52ff, "ON"), (0x2900, "OFF")])
def test_a_slot_that_holds_no_mark_reads_as_the_track(main, word, says):
    for mode, own in ((0, "OFF"), (REC, "ON")):
        r = page(main, mode=mode)
        r.put(7, word)
        r.hold(7)
        assert r.rec() == (says or own)


# ---- what an earlier build saved ------------------------------------------------------------------------------

def scene(built, mode, locks, held, turns):
    r = page(built, mode=mode)
    for step, word in locks.items():
        r.lay(step, word)
    r.hold(*held)
    out = [r.show()]
    for knob, steps in turns:
        r.twist(knob, steps)
        out.append((r.show(), r.mode, tuple(r.changes), dict(r.rec_locks), tuple(r.popped), tuple(r.locked), r.gains, r.dest, r.box))
    return out


@pytest.mark.parametrize("mode", [0, REC, STEREO | REC, 5 << 2])
@pytest.mark.parametrize("held", [(), (5,), (5, 9)])
def test_a_project_the_feed_image_saved_reads_and_turns_the_same(main, before, mode, held):
    """A step locked on or off, a track on or off: what the page shows, and every turn that stays between OFF and ON
    and every turn of the other knobs, is the feed image's."""
    locks = {5: ON, 9: OFF, 20: ON}
    turns = [(SRC_KNOB, 2), (DEST_KNOB, 3), (BANK_KNOB, 1), (GAIN_KNOB, 5), (TAKE_KNOB, 1), (TAKE_KNOB, -1), (REC_KNOB, -1), (REC_KNOB, -1)]
    assert scene(main, mode, locks, held, turns) == scene(before, mode, locks, held, turns)
    if not held:
        up = [(REC_KNOB, -1), (REC_KNOB, 1)]                        # the track's, off and to on: a turn to the right from ON is new
        assert scene(main, mode & ~REC, locks, held, up) == scene(before, mode & ~REC, locks, held, up)


# ---- the sequencer: a step is played ---------------------------------------------------------------------------

def locked(r, step, word):
    """A step locked by the page, at ON or ONCE, the keys let go after."""
    r.hold(step)
    r.twist(REC_KNOB, {ON: 1, ONCE: 2}[word])
    r.hold()
    assert r.rec_locks[step] == word


@pytest.mark.parametrize("track", [0, 5, 7])
def test_a_step_locked_once_is_played_as_one_locked_on_and_is_spent(main, track):
    on, once = page(main, track=track), page(main, track=track)
    locked(on, 9, ON), locked(once, 9, ONCE)
    was, made = once.table(), len(on.table_writes)
    assert on.play(9) == [(SLOT, ON)] and once.play(9) == [(SLOT, ONCE)] and on.kept and once.kept
    # what stock's routine that applies an event's locks leaves for both: the mark of a step locked on, in slot 24's word
    for r, word in ((on, ON), (once, ONCE)):
        r.mc.write(WORDS, bytes(0x800))
        r.mc.call(mm.LOCKS_APPLY, track, LOCKS, WORDS)
        got = bytes(r.mc.read(WORDS + STRIDE * track + P_REC, 2))
        assert got == word.to_bytes(2, "big") and got[0] == m.REC_LOCK_ON
    # the step locked on: nothing of the pattern moved. The one locked once: its word, to one that is no mark
    assert len(on.table_writes) == made and on.rec_locks == {9: ON} and on.dirty == on.arm == [0] * 8
    now = once.table()
    at = once.at(9) - TABLE
    assert now[at:at + 2] == SPENT.to_bytes(2, "big") and now[:at] == was[:at] and now[at + 2:] == was[at + 2:]
    assert once.count(9) == 1 and once.dirty == [int(t == track) for t in range(8)] and once.arm == [0] * 8
    assert SPENT >> 8 not in (m.REC_LOCK_ON, m.REC_LOCK_OFF)
    # the second pass, should the main task not have come by yet: the same step says nothing
    assert once.play(9) == [(SLOT, SPENT)] and on.play(9) == [(SLOT, ON)]
    assert once.table() == now and on.rec_locks == {9: ON}


def test_the_main_task_takes_the_spent_lock_off_with_stocks_routine_and_the_trig_plays_on(main):
    r = page(main, track=2)
    locked(r, 9, ONCE), locked(r, 30, ON)
    r.lay(9, 0x4000, slot=20)                                      # another lock on the same step, and a lock of another track
    r.lay(9, ONCE, track=4)
    assert r.wait() == MSG and not r.notes and not r.once_writes    # nothing to do: stock's wait and its answer
    idle = r.cost
    r.play(9)
    writes, trigs = len(r.table_writes), set(r.trigs)
    assert r.wait() == MSG                                          # the message is stock's, whatever was done after it came
    assert r.rec_locks == {30: ON} and r.lock_at(9) == NONE and r.count(9) == 1 and r.lock_at(9, 20) == 0x4000
    assert r.lock_at(9, track=4) == ONCE and r.dirty == [0] * 8
    assert (NOTE, SLOT, 2) in r.notes                               # stock's routine told the pattern's listeners, as by hand
    assert len(r.table_writes) > writes and r.trigs == trigs and not r.stray
    assert r.play(9) == [(20, 0x4000)] and r.kept                   # the next pass: the step plays, with what else it holds
    assert r.wait() == MSG and r.cost == idle and idle <= 12
    r.hold(9)
    assert r.rec() == "OFF"                                         # and the page reads the track's for it


def test_a_step_locked_on_records_every_pass_and_nothing_is_taken_off(main):
    r = page(main, track=6)
    locked(r, 4, ON)
    was = r.table()
    for _ in range(3):
        assert r.play(4) == [(SLOT, ON)]
        assert r.wait() == MSG
    assert r.table() == was and r.dirty == r.arm == [0] * 8 and not r.notes


def test_two_spent_on_a_track_and_one_on_another_all_go_at_the_next_message(main):
    r = page(main, track=1)
    locked(r, 3, ONCE), locked(r, 50, ONCE)
    r.lay(7, ONCE, track=6)
    r.play(3), r.play(50), r.play(7, track=6)
    assert r.dirty == [0, 1, 0, 0, 0, 0, 1, 0]
    r.wait()
    assert not r.rec_locks and r.lock_at(7, track=6) == NONE and r.dirty == [0] * 8


def test_a_spent_lock_in_a_pattern_that_is_no_longer_selected_is_left_and_a_turn_of_rec_takes_it_off(main):
    r = page(main)
    locked(r, 3, ONCE)
    r.play(3)
    r.stub(0x400c2154, lambda obj: 1)                              # another pattern is selected: its steps objects are not these
    r.mc.uc.ctl_flush_tb()
    for t in range(12):
        r.mc.w32(STEPS_AT + 1664 + 112 * (t + 1) + 44, 0)         # no pattern data behind them: stock's routines answer "none"
    r.wait()
    assert r.rec_locks == {3: SPENT} and r.dirty == [0] * 8
    r.hold(3)
    r.twist(REC_KNOB, -1)
    assert not r.rec_locks and r.count(3) == 0


# ---- the track's own ONCE --------------------------------------------------------------------------------------

def armed(built, track=0, **kw):
    r = page(built, track=track, **kw)
    r.twist(REC_KNOB, 2)
    assert r.arm[track] == 1 and r.mode & REC == 0
    return r


@pytest.mark.parametrize("track", [0, 7])
def test_the_next_step_played_records_as_a_step_locked_on_and_the_track_is_off_after(main, track):
    r = armed(main, track=track)
    was = r.table()
    assert r.play(11) == [(SLOT, ON)] and r.kept                   # a step with no locks: one, (slot 24, on)
    assert r.arm == [0] * 8 and r.rec() == "OFF" and r.table() == was and r.dirty == [0] * 8
    assert r.play(12) == [] and r.play(11) == []                    # and no other
    assert r.wait() == MSG and not r.notes and r.table() == was


def test_a_step_with_locks_of_its_own_gets_it_after_them(main):
    r = armed(main, track=3)
    r.lay(11, 0x4000, slot=20), r.lay(11, 0x0100, slot=70)
    assert r.play(11) == [(20, 0x4000), (70, 0x0100), (SLOT, ON)] and r.kept and r.arm == [0] * 8
    assert r.play(11) == [(20, 0x4000), (70, 0x0100)]


def test_a_step_locked_off_leaves_it_for_the_next_and_one_locked_on_or_once_uses_it_up(main):
    r = armed(main)
    r.lay(4, OFF)
    assert r.play(4) == [(SLOT, OFF)] and r.arm[0] == 1
    assert r.play(5) == [(SLOT, ON)] and r.arm[0] == 0
    for word in (ON, ONCE):
        r = armed(main)
        r.lay(4, word)
        assert r.play(4) == [(SLOT, word)] and r.arm == [0] * 8    # a take is made by the step's own lock: one take
        assert r.play(5) == []


def test_a_spent_lock_on_the_step_does_not_stand_in_its_way(main):
    r = armed(main)
    r.lay(4, SPENT)
    assert r.play(4) == [(SLOT, SPENT), (SLOT, ON)]                 # stock applies them in order: the last one stands
    r.mc.write(WORDS, bytes(0x800))
    r.mc.call(mm.LOCKS_APPLY, 0, LOCKS, WORDS)
    assert bytes(r.mc.read(WORDS + P_REC, 2)) == ON.to_bytes(2, "big")


def test_an_event_that_is_full_is_left_as_it_is(main):
    r = armed(main)
    for slot in range(71):
        if slot != SLOT:
            r.lay(4, 0x0100 + slot, slot=slot)
    assert len(r.play(4)) == 71 and r.arm == [0] * 8               # 70 of its own and ours: all an event has room for
    r = armed(main)
    for slot in range(71):
        r.lay(4, SPENT if slot == SLOT else 0x0100 + slot, slot=slot)
    assert len(r.play(4)) == 71 and r.arm[0] == 1                  # 71 of its own: nothing is added, and it waits


def test_only_the_armed_track_and_a_turn_back_disarms(main):
    r = armed(main, track=2)
    assert r.play(4, track=1) == [] and r.play(4, track=3) == [] and r.arm[2] == 1
    r.twist(REC_KNOB, -2)
    assert r.arm == [0] * 8 and r.play(4) == []


# ---- what is not a sampler's -----------------------------------------------------------------------------------

@pytest.mark.parametrize("track, machine", [(3, OTHER), (5, 35), (8, 0), (11, 0), (12, 0)])
def test_a_track_that_is_no_sampler_is_played_as_stock_plays_it(main, track, machine):
    r = page(main, machines={track: machine} if track < 12 else None)
    r.lay(9, ONCE, track=track)                                    # there the slot is a knob, or the hold flag
    r.mc.write(mm.ONCE_ARM, b"\x01" * 8)
    was = r.table()
    assert r.play(9, track=track) == [(SLOT, ONCE)] and r.play(10, track=track) == [] and r.kept
    assert r.table() == was and r.arm == [1] * 8 and r.dirty == [0] * 8


def test_with_no_event_nothing_is_done(main):
    r = armed(main)
    r.lay(9, ONCE)
    was = r.table()
    assert r.play(9, event=False) is None and r.kept and r.table() == was and r.arm[0] == 1


def test_with_nothing_at_once_the_step_routine_leaves_what_the_feed_images_leaves(main, before):
    rng = np.random.default_rng(7)
    new, old, there = page(main), page(before), {}
    for _ in range(40):
        track, step = int(rng.integers(0, 13)), int(rng.integers(0, 64))
        locks = {int(s): int(rng.choice([ON, OFF, SPENT, 0x0100 * int(rng.integers(0, 128))])) for s in rng.choice(71, int(rng.integers(0, 6)), replace=False)}
        for r in (new, old):
            for slot, word in locks.items():
                r.lay(step, word, slot=slot, track=track)
        there.setdefault((track, step), {}).update(locks)
        got, want = new.play(step, track=track), old.play(step, track=track)
        assert got == want == sorted(there[track, step].items()) and new.kept and old.kept and new.table() == old.table()
        assert new.cost - old.cost <= (40 if got else 18)           # ours, a step: with locks the six pushes, the track's test, the row
    assert new.arm == new.dirty == [0] * 8


# ---- what the audio CPU is sent, and the take ------------------------------------------------------------------

def test_the_per_block_loop_sends_once_as_the_mark_it_holds_and_spent_as_nothing(main):
    """Stock's loop that writes the hold flag over slot 24, with engine/recword.S in it, run as it is."""
    tracks = [(SAMPLER, ONCE, 0, 0), (SAMPLER, SPENT, 0, 0), (SAMPLER, SPENT, 1, 0), (OTHER, ONCE, 0, 0),
              (SAMPLER, ON, 0, 0), (SAMPLER, OFF, 1, 0), (SAMPLER, 0, 0, 0), (SAMPLER, ONCE, 7, 0x7f00)]
    sent, _ = hold_loop(main[0], tracks)
    got = [int.from_bytes(sent[STRIDE * t + P_REC:][:2], "big") for t in range(8)]
    assert got == [ONCE, 0, 1, 0, ON, OFF, 0, ONCE]


def take(audio, mode, word, own=0):
    """A note held on track 4 with `word` in slot 24. -> every slot's entry, the two takes, the feed."""
    e = P.engine(audio)
    P.box(e)
    fresh = [P.slot_entry(e, k) for k in range(m.SLOTS)]
    e.set_slot(4, MODE, mode | own)
    e.set_slot(4, SLOT, word / 256)
    data = P.hold(e, track=4, n=12)
    entries = [P.slot_entry(e, k) for k in range(m.SLOTS)]
    if entries == fresh:
        return entries, None, data, True
    return entries, [bytes(P.taken(e, k).tobytes()) for k in (8, 9) if entries[k] != fresh[k]], data, False


@pytest.mark.parametrize("mode", [0, STEREO, 5 << 2, STEREO | 9 << 2])
def test_the_take_of_a_step_locked_once_is_the_take_of_a_step_locked_on(audio, mode):
    on, once = take(audio, mode, ON), take(audio, mode, ONCE)
    assert on[0] == once[0] and on[1] == once[1] and not on[3] and len(once[1]) == 2    # a mono take leaves one frame in the second slot
    assert len(once[1][0]) >= 2 * 8 * 32                            # eight blocks or more of the feed, in the first slot


@pytest.mark.parametrize("word", [SPENT, 0, 1])
def test_on_the_second_pass_nothing_is_taken_and_the_tracks_own_rec_decides(audio, word):
    assert take(audio, STEREO, word)[3]                             # REC off on the track: the step plays
    assert not take(audio, STEREO, word, own=REC)[3]                # REC on: it records, as a step with no lock does


def test_the_whole_way_from_the_knob_to_the_take_and_the_second_pass(main, audio):
    """The page's lock, stock's gathering and applying, the per-block loop, the engine: ONCE against ON, pass by pass."""
    out = {}
    for word in (ON, ONCE):
        r = page(main, track=4)
        locked(r, 9, word)
        passes = []
        for _ in range(2):
            r.play(9)
            r.wait()
            r.mc.write(WORDS, bytes(0x800))
            r.mc.call(mm.LOCKS_APPLY, 4, LOCKS, WORDS)
            applied = int.from_bytes(r.mc.read(WORDS + STRIDE * 4 + P_REC, 2), "big")
            sent, _ = hold_loop(main[0], [(SAMPLER, applied if t == 4 else 0, 0, 0) for t in range(8)])
            passes.append(take(audio, STEREO, int.from_bytes(sent[STRIDE * 4 + P_REC:][:2], "big")))
        out[word] = passes
        assert r.rec_locks == ({9: ON} if word == ON else {})
    assert out[ONCE][0][:2] == out[ON][0][:2] and not out[ONCE][0][3]      # the first pass: the same take
    assert out[ONCE][1][3] and out[ON][1][:2] == out[ON][0][:2]            # the second: none, where ON takes again


# ---- the image -------------------------------------------------------------------------------------------------

RUNS = [mm.CAVE_ONCE, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE6]
SITES = [(mm.STEP_LOCKS_PUSH, 6), (mm.STEP_NO_LOCKS, 4), (mm.MAIN_LOOP_WAIT + 2, 4)]


def test_the_main_program_is_the_feed_images_but_for_its_declared_places(main, before, stock3):
    image, syms = main
    old, was = before
    diff = [k for k in range(len(stock3)) if image[k] != old[k]]
    spans = RUNS + [(a, a + n) for a, n in SITES] + [(a, a + 4) for a in POINTERS]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    for s, e in RUNS + [(a, a + n) for a, n in SITES]:
        assert image[mm.off(s):mm.off(e)] != old[mm.off(s):mm.off(e)], hex(s)
    # the three places were stock's on the feed image, and so was the run, which nothing reaches
    for s, e in [mm.CAVE_ONCE] + [(a, a + n) for a, n in SITES]:
        assert old[mm.off(s):mm.off(e)] == stock3[mm.off(s):mm.off(e)]
    lo, hi = mm.CAVE_ONCE
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    # the three places as they are now: a call, a short call, a call
    at = mm.off(mm.STEP_LOCKS_PUSH)
    assert image[at:at + 6] == b"\x4e\xb9" + syms["once_seq"].to_bytes(4, "big") and image[at + 6:at + 12] == stock3[at + 6:at + 12]
    at = mm.off(mm.STEP_NO_LOCKS)
    assert image[at:at + 2] == b"\x61\x00" and mm.STEP_NO_LOCKS + 2 + int.from_bytes(image[at + 2:at + 4], "big", signed=True) == syms["once_none"]
    at = mm.off(mm.MAIN_LOOP_WAIT)
    assert image[at:at + 6] == b"\x4e\xb9" + syms["once_loop"].to_bytes(4, "big")
    # the sixteen bytes are 0 in the image, so 0 at every start, and where the header says
    assert image[mm.off(lo):mm.off(lo) + 16] == bytes(16) and syms["once_vars"] == lo == mm.ONCE_ARM == 0x40088820
    assert all(lo <= syms[n] < hi for n in ("once_seq", "once_none", "once_loop", "once_clean"))
    # every other run of ours is the feed image's, and so are stock's routines this leans on
    for lo, hi in (mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED, mm.CAVE_KEEP, mm.CAVE_BANK, mm.CAVE_PAGE4, mm.CAVE_PAGE5,
                   mm.CAVE_SOLO, mm.CAVE_RIGHT, mm.CAVE_HALVES, mm.CAVE_TEXT):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]
    lo, hi = mm.CAVE_PAGE6                                          # the page's sixth run: the feed image's but for one operand
    assert sum(image[k] != old[k] for k in range(mm.off(lo), mm.off(hi))) <= 4
    for a, n in ((mm.STEP_LOCKS, 0x52), (mm.LOCK_DROP, 0x42), (mm.LOCK_TABLE_DROP, 0xd0), (mm.NOW_PATTERN, 0x36), (mm.STEPS_OF, 0x22),
                 (mm.MAIN_WAIT, 0x40), (mm.HOLD_LOOP, mm.HOLD_END - mm.HOLD_LOOP)):
        assert image[mm.off(a):mm.off(a) + n] == old[mm.off(a):mm.off(a) + n]


# the page's routines that moved, and the places that name them
POINTERS = (mm.SYN_CLASS + mm.PAGE_DRAW_METHOD, mm.SYN_CLASS + mm.PAGE_TURN_METHOD, mm.SYN_CLASS + mm.PAGE_KNOB_METHOD,
            mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_BUILD + 6)


def test_every_pointer_names_the_routine_it_named(main, before):
    image, syms = main
    old, was = before
    for a in POINTERS:
        names = [n for n, v in was.items() if v == int.from_bytes(old[mm.off(a):mm.off(a) + 4], "big")]
        assert names and int.from_bytes(image[mm.off(a):mm.off(a) + 4], "big") in [syms[n] for n in names], hex(a)


def test_no_branch_goes_into_a_changed_place(stock3):
    """Every short and word branch of the routine around the two places, by its own bytes: none lands inside one."""
    lo, hi = mm.STEP_PLAY, 0x4008c128
    code = stock3[mm.off(lo):mm.off(hi)]
    inside = set(range(mm.STEP_LOCKS_PUSH + 2, mm.STEP_LOCKS_PUSH + 6)) | set(range(mm.STEP_NO_LOCKS + 2, mm.STEP_NO_LOCKS + 4))
    landed = set()
    for a, raw, _ in boundaries(code, lo):
        op = int.from_bytes(raw[:2], "big")
        if op >> 12 == 6:                                           # a branch
            d = op & 0xff
            if d == 0:
                landed.add(a + 2 + int.from_bytes(code[a - lo + 2:a - lo + 4], "big", signed=True))
            elif d != 0xff:
                landed.add(a + 2 + (d - 256 if d > 127 else d))
    assert mm.STEP_NO_LOCKS in landed and mm.STEP_JOINED in landed and not landed & inside
    assert mm.STEP_LOCKS_PUSH not in landed and mm.STEP_LOCKS_PUSH + 6 not in landed


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, once=True)
    was = build.build(official_path, log=quiet, feed=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the feed image's byte for byte, which is the stops image's
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
