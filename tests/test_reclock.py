"""The "reclock" image: a step's REC is a lock of its own, not a lock of MODE.

On request
. REC, SRC and the
stereo switch are three bits of the one MODE parameter, and a lock holds a parameter's whole
value: locking REC on a step froze that step's stereo switch and source as they stood.

The unit keeps a lock for each of 71 knob slots of a track, with or without a knob behind the
slot, and plays whatever locks a step has (read in the listing, and run here). Slot 24 has no knob
on a digital track. So a step's REC is a lock there, at one of two marks, and anything else in the
slot leaves the track's own REC, the bit of MODE, to decide.

Three pieces, each emulated on its own:

  the page (engine/recpage.c built with RECLOCK): our routines on a page object of the test's,
    with **the stock routines that read, make and remove a lock by slot run as they are** on a
    lock table laid out the way they index it, and then stock's own routine that gathers a step's
    locks into an event and the one that applies an event's locks, run as they are, to see the
    word arrive where the audio CPU is sent it from. Played by the test, as in tests/test_page.py:
    the holder's methods for MODE, the steps' trigs, the keys object.
  the sound engine (engine/sampler.c built with RECLOCK), inside the real voice loop hook.
  the feed (engine/recfeed.c built with RECLOCK), with the mixer stubbed.

Not emulated: the routine between the two, which builds the block the audio CPU is sent and
smooths every word on the way (its arithmetic does not run here, docs/FINDINGS.md); what slot 24
holds on a track of the unit that has no lock (anything but the two marks leaves REC as it was);
whether a lock on that slot is saved with a pattern; the unit.
"""
import shutil

import numpy as np
import pytest

import test_page
from emu.engine import BLOCK
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm
from test_fade import CASES
from test_live import SCRIPTS, hold as rest, play
from test_page import EVENT, HEAP, KEYS, PAGE, Rig, STEPS
from test_pagerec import ALL, EXT, MONO, REC, STEREO, engine, fed, fed_from, is_take, noise, slot_entry, taken, untouched
from test_pagerec import hold as held_note
from test_recorder import MainRig, STRIDE, frames, junk, make_block

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER, MIDI = 44, 35
SLOT = m.K_REC
ON, OFF = m.REC_WORD_ON, m.REC_WORD_OFF
NONE = 0xFFFF
MODE = 23
P_REC = m.PARAM_KNOBS + 2 * SLOT            # where slot 24 is in a track's 142 bytes
# knob ids on the pages, as a turn names them
SRC_KNOB, REC_KNOB, MODE_KNOB = 1, 3, 6
# the lock table as stock indexes it: 9287 bytes a track at an odd address, as on the unit (the pattern's data + 15301)
TABLE_AT, TABLE = 0x41100000, 0x41100001
PATTERN_OBJ, PATTERN_METHODS, DATA_FN, NOTIFY_FN = HEAP + 0xc000, HEAP + 0xc100, HEAP + 0xc200, HEAP + 0xc210
LOCKS, WORDS = HEAP + 0xd000, HEAP + 0xd400     # an event's locks; the words LOCKS_APPLY writes
FILTER, LOCKED = 0x8000e9b0, 0x4550f1cc         # stock's: the smoothing's state, a long a word; which slots of a track hold a lock
NOTE = 0x401c48cc                               # what stock tells the pattern's listeners of a lock made or removed


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def audio(stock):
    return build_engine.patched_image(stock, reclock=True)


@pytest.fixture(scope="module")
def floor(stock):
    return build_engine.patched_image(stock, floor=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, reclock=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, floor=True)


# ---- the page ------------------------------------------------------------------------------------

class LockRig(Rig):
    """The page rig with a lock table of its own, so stock's lock routines run on it as they are."""

    def __init__(self, built, machines, track=0, **kw):
        self.table_writes, self.notes = [], []
        super().__init__(built, machines, track=track, **kw)
        mc = self.mc
        mc.map(TABLE_AT, 0x20000)
        mc.map(FILTER & ~0xFFF, 0x2000)
        mc.map(LOCKED & ~0xFFF, 0x1000)
        mc.write(TABLE, ((b"\xff\xff" * 71 + bytes(2)) * 64 + bytes(71)) * 13)     # no lock anywhere
        mc.w32(STEPS + 44, PATTERN_OBJ)                     # the steps object: its pattern, and which track it is
        mc.w32(STEPS + 56, track)
        mc.w32(PATTERN_OBJ, PATTERN_METHODS)
        mc.w32(PATTERN_METHODS + 40, DATA_FN)
        mc.w32(PATTERN_METHODS + 16, NOTIFY_FN)
        self.stub(DATA_FN, lambda obj: TABLE if obj == PATTERN_OBJ else 0)
        self.stub(NOTIFY_FN, lambda obj, note: self.noted(obj, note))
        mc.uc.ctl_flush_tb()

    def noted(self, obj, note):
        assert obj == PATTERN_OBJ
        self.notes.append((self.mc.r32(note), self.mc.r32(note + 4), self.mc.r32(note + 8)) if note else None)
        return 0

    def wrote(self, uc, access, address, size, value, user):
        if TABLE <= address < TABLE + 13 * mm.LOCK_TRACK:
            self.table_writes.append(address)
        elif not (FILTER <= address < FILTER + 0x1000 or LOCKED <= address < LOCKED + 0x100 or HEAP + 0xd000 <= address < HEAP + 0xe000):
            super().wrote(uc, access, address, size, value, user)

    def at(self, step, slot=SLOT, track=None):
        return TABLE + mm.LOCK_TRACK * (self.track if track is None else track) + mm.LOCK_STEP * step + 2 * slot

    def lock_at(self, step, slot=SLOT, track=None):
        """The word stock's table holds for a slot of a step: 0xffff is no lock."""
        return int.from_bytes(self.mc.read(self.at(step, slot, track), 2), "big")

    def put(self, step, word, slot=SLOT):
        self.mc.write(self.at(step, slot), word.to_bytes(2, "big"))

    def count(self, step):
        """How many locks stock counts on the step: the row's last word."""
        return self.lock_at(step, 71)

    @property
    def rec_locks(self):
        return {s: self.lock_at(s) for s in range(64) if self.lock_at(s) != NONE}

    @property
    def others(self):
        """Every lock in the table that is not the active track's slot 24."""
        raw = bytes(self.mc.read(TABLE, 13 * mm.LOCK_TRACK))
        return {(t, s, k) for t in range(13) for s in range(64) for k in range(71)
                if (t, k) != (self.track, SLOT) and raw[mm.LOCK_TRACK * t + mm.LOCK_STEP * s + 2 * k:][:2] != b"\xff\xff"}

    def places(self):
        return [t[2] for t in self.show()]

    def rec(self):
        """What the page reads for REC."""
        got = self.places()
        return got[got.index("REC") + 1]


def page_rig(main, track=0, **kw):
    r = LockRig(main, {track: SAMPLER}, track=track, index=1, **kw)
    r.mc.w32(0x40196aba, 0), r.mc.w32(0x40196abe, 0)        # the bank numbers the page also draws
    return r


@pytest.mark.parametrize("track", [0, 7])
@pytest.mark.parametrize("mode", [MONO, STEREO, EXT, EXT | STEREO])
def test_rec_with_a_step_held_makes_a_lock_on_slot_24_and_none_of_mode(main, track, mode):
    r = page_rig(main, track=track, mode=mode)
    r.hold(5)
    assert r.twist(REC_KNOB, 1) == 1
    assert r.rec_locks == {5: ON} and not r.others          # the step's REC, in stock's own table, for this track only
    assert not r.locks and not r.locked and not r.changes and r.mode == mode    # no lock of MODE, and the track is as it was
    assert r.count(5) == 1                                  # stock counts it among the step's locks
    assert r.notes[0] == (NOTE, SLOT, track)                # and tells the pattern's listeners, as for any lock
    assert r.edited and r.done and not r.stray              # the keys object is told, so letting go does not take the trig


def test_stocks_own_routines_read_it_back_and_play_it(main):
    """The lock is read by stock's routine for a slot; the routine that gathers a step's locks for an event finds it;
    and the one that applies an event's locks puts it in slot 24's word of the track, and in the smoothing's state."""
    track = 3
    r = page_rig(main, track=track)
    r.hold(9)
    r.twist(REC_KNOB, 1)
    mc = r.mc
    assert mc.call(mm.LOCK_READ, STEPS, 9, SLOT) & 0xFFFF == ON
    assert mc.call(mm.LOCK_READ, STEPS, 8, SLOT) == 0xFFFFFFFF and mc.call(mm.LOCK_READ, STEPS, 9, MODE) == 0xFFFFFFFF
    mc.write(LOCKS, bytes(0x400))
    mc.call(mm.STEP_LOCKS, LOCKS, TABLE + mm.LOCK_TRACK * track, 0, 9, 9, 0)
    assert mc.r32(LOCKS + 8) == 1 and bytes(mc.read(LOCKS + 20, 4)) == SLOT.to_bytes(2, "big") + ON.to_bytes(2, "big")
    mc.write(WORDS, bytes(0x800))
    mc.call(mm.LOCKS_APPLY, track, LOCKS, WORDS)
    place = STRIDE * track + P_REC                          # where the block the audio CPU is sent has slot 24 of the track
    words = bytes(mc.read(WORDS, 0x800))
    assert words[place:place + 2] == ON.to_bytes(2, "big") and words.count(0) == 0x800 - 2
    assert mc.r32(FILTER + 2 * place) == ON << 16           # at once, not smoothed toward
    assert mc.r32(LOCKED + 12 * track) == 1 << SLOT         # and marked to be put back at the track's next event
    assert P_REC == 0x4c                                    # the word the audio CPU's voice loop copies into the hold flag


def test_the_step_is_given_no_lock_when_it_is_to_do_what_the_track_does(main):
    r = page_rig(main, mode=MONO)
    r.hold(5)
    r.twist(REC_KNOB, -1)                                   # the track's REC is off, and so is this
    assert not r.rec_locks and not r.table_writes and not r.locked
    r = page_rig(main, mode=REC)
    r.hold(5)
    r.twist(REC_KNOB, 1)
    assert not r.rec_locks and not r.table_writes and not r.locked


def test_turning_it_back_takes_the_lock_away(main):
    r = page_rig(main)
    r.hold(5)
    r.twist(REC_KNOB, 1)
    r.twist(REC_KNOB, 3)                                    # again: the same lock
    assert r.rec_locks == {5: ON} and r.count(5) == 1
    r.twist(REC_KNOB, -1)
    assert not r.rec_locks and r.count(5) == 0 and not r.others
    assert r.notes[-1] is None or r.notes[-2] == (NOTE, SLOT, 0)    # stock told the listeners of the removal too
    assert not r.locks and not r.changes and not r.stray


def test_on_a_track_in_record_a_step_can_be_locked_off(main):
    r = page_rig(main, mode=REC | STEREO)
    r.hold(12)
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {12: OFF} and r.mode == REC | STEREO and not r.locks
    r.twist(REC_KNOB, 1)
    assert not r.rec_locks


def test_every_held_step_gets_its_own_and_a_step_with_no_trig_gets_one_first(main):
    r = page_rig(main)
    r.hold(2, 3, 40)
    r.trigs = {2, 40}                                       # step 3 is held with no trig on it
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {2: ON, 3: ON, 40: ON}
    assert r.locked == [("trig", 3, 0)] and r.trigs == {2, 3, 40}   # as stock does before it makes a lock
    assert [r.count(s) for s in (2, 3, 40)] == [1, 1, 1]
    r.hold(3)
    r.twist(REC_KNOB, -1)
    assert r.rec_locks == {2: ON, 40: ON}


def test_steps_past_the_patterns_length_are_not_held_steps(main):
    r = page_rig(main)
    r.length = 16
    r.hold(4, 20)
    r.twist(REC_KNOB, 1)
    assert r.rec_locks == {4: ON}


def test_with_no_step_held_rec_is_the_tracks_as_before(main):
    r = page_rig(main, mode=STEREO)
    r.twist(REC_KNOB, 1)
    assert r.mode == STEREO | REC and r.changes == [REC] and not r.rec_locks and not r.table_writes
    assert r.popped == [("REC", "ON")]
    r.twist(REC_KNOB, -1)
    assert r.mode == STEREO and r.popped[-1] == ("REC", "OFF")


def test_the_page_shows_the_held_steps_rec_and_the_tracks_otherwise(main):
    r = page_rig(main, mode=MONO)
    assert r.rec() == "OFF"
    r.hold(5)
    r.twist(REC_KNOB, 1)
    assert r.rec() == "ON"                                  # the held step's
    r.hold()
    assert r.rec() == "OFF"                                 # the track's
    r.hold(6)
    assert r.rec() == "OFF"                                 # a step with no lock: the track's
    r.mode = REC
    assert r.rec() == "ON"
    r.put(6, OFF)
    assert r.rec() == "OFF"
    r.put(6, 0x1234)                                        # not one of the two marks: the track's
    assert r.rec() == "ON"
    assert not r.stray


def test_src_is_the_tracks_alone_now(main):
    r = page_rig(main, mode=REC)
    r.hold(5)
    assert r.twist(SRC_KNOB, 1) == 1
    assert r.mode == REC | EXT and r.changes == [EXT] and not r.locks and not r.rec_locks
    assert r.places()[:2] == ["SRC", "EXT"]


def test_mode_on_the_first_page_can_still_be_locked_and_it_is_all_that_is(main):
    r = LockRig(main, {0: SAMPLER}, index=0, mode=REC)
    r.hold(7)
    r.twist(MODE_KNOB, 1)
    assert r.locks == {7: REC | STEREO} and r.mode == REC and not r.rec_locks and not r.table_writes


@pytest.mark.parametrize("knob, bit", [(REC_KNOB, REC), (SRC_KNOB, EXT)])
def test_a_turn_of_the_tracks_rec_or_src_goes_into_every_lock_of_mode(main, knob, bit):
    """A lock of MODE is a lock of the stereo switch: its other two bits are kept the track's."""
    r = page_rig(main, mode=MONO)
    r.locks = {3: STEREO, 9: MONO, 63: STEREO}
    r.trigs = {3, 9, 63}
    r.twist(knob, 1)
    assert r.mode == bit and r.locks == {3: STEREO | bit, 9: bit, 63: STEREO | bit}
    assert sorted(r.locked) == [("move", 3, bit), ("move", 9, bit), ("move", 63, bit)]
    r.twist(knob, -1)
    assert r.mode == 0 and r.locks == {3: STEREO, 9: MONO, 63: STEREO}
    assert not r.rec_locks and not r.table_writes


def test_a_lock_of_mode_made_by_the_build_before_stops_being_a_lock_of_rec(main):
    """What is on the unit now: a step whose REC was locked has a lock of MODE with the record bit in it. One turn of
    the track's REC and back, and it is a lock of the stereo switch as it stood, saying what the track says."""
    r = page_rig(main, mode=MONO)
    r.locks, r.trigs = {4: REC, 8: REC | EXT | STEREO}, {4, 8}
    r.twist(REC_KNOB, 1)
    r.twist(REC_KNOB, -1)
    assert r.mode == MONO and r.locks == {4: MONO, 8: STEREO}


def test_the_stereo_switch_of_the_track_is_not_written_into_locks(main):
    r = LockRig(main, {0: SAMPLER}, index=0, mode=MONO)
    r.locks, r.trigs = {3: MONO, 9: STEREO | REC}, {3, 9}
    r.twist(MODE_KNOB, 1)
    assert r.mode == STEREO and r.locks == {3: MONO, 9: STEREO | REC} and not r.locked


@pytest.mark.parametrize("machine", [0, 7, 36, 38])
def test_a_track_that_is_no_sampler_any_more_loses_its_rec_locks(main, machine):
    """On another digital machine slot 24 is the envelope's hold flag: a REC lock left behind would hold its notes."""
    r = LockRig(main, {2: machine}, track=2, index=0)
    for step, word in ((1, ON), (40, OFF), (63, ON), (7, 0x1000)):
        r.put(step, word)
    r.put(1, 0x3300, slot=20)                               # a lock of something else on the same step
    r.table_writes = []
    r.show()
    assert r.rec_locks == {7: 0x1000}                       # ours are gone; a value that is not ours is not touched
    assert r.lock_at(1, 20) == 0x3300 and not r.stray
    r.table_writes = []
    r.show()
    assert not r.table_writes                               # and nothing more is done once they are


@pytest.mark.parametrize("track, machine", [(2, MIDI), (8, 20), (11, 30), (12, 0xFFFFFFFF), (2, SAMPLER)])
def test_a_midi_track_an_analog_track_and_a_sampler_keep_what_is_in_the_slot(main, track, machine):
    """On a MIDI machine and on the analog tracks slot 24 is a knob with locks of its own."""
    r = LockRig(main, {track: machine}, track=track, index=0)
    r.put(1, ON), r.put(40, OFF)
    r.table_writes = []
    r.show()
    assert r.rec_locks == {1: ON, 40: OFF} and not r.table_writes


def test_the_rest_of_the_page_is_as_it_was(main):
    r = page_rig(main, mode=0)
    assert r.places()[:6] == ["SRC", "MAIN", "DEST", "SMPL", "REC", "OFF"]
    r.twist(REC_KNOB, 1), r.twist(SRC_KNOB, 1), r.twist(2, 4)
    assert r.mode == REC | EXT and r.dest == 4
    for knob in range(5, 9):
        assert r.twist(knob, 3) == 1
    assert r.mode == REC | EXT and not r.rec_locks and not r.table_writes


# ---- the sound engine ------------------------------------------------------------------------------

def word(e, track, value):
    """Slot 24 of a track, as a 16-bit word."""
    e.set_slot(track, SLOT, value / 256)


@pytest.mark.parametrize("mode", [MONO, STEREO, EXT, EXT | STEREO])
def test_a_step_locked_on_starts_a_take_though_the_tracks_rec_is_off(audio, mode):
    e = engine(audio)
    e.set_slot(5, MODE, mode)
    word(e, 5, ON)
    data = held_note(e, track=5, n=20)
    assert is_take(taken(e, 10), data, 0, 20) and is_take(taken(e, 11), data, 1, 20)
    assert untouched(e, but=(10, 11))


def test_a_step_locked_off_plays_though_the_tracks_rec_is_on(audio):
    rng = np.random.default_rng(3)
    pool = {k: rng.integers(-20000, 20000, 3000).astype(np.int16) for k in range(16)}
    e = engine(audio, pool=pool)
    e.set_slot(4, MODE, REC)
    word(e, 4, OFF)
    data = noise(14, 4)
    out = np.concatenate([fed(e, data[b], trig=0b10000 if b == 0 else 0, release=0b10000 if b == 10 else 0) for b in range(14)], axis=1)
    assert np.any(out[4])                                   # it plays the sample SMPL is on
    assert all(slot_entry(e, k)[1] != m.REC_BASE + m.REC_STRIDE * k for k in range(m.SLOTS))    # and nothing is taped over


@pytest.mark.parametrize("value", [0, 0x0100, 0x7f00, 0x5180, 0x51ff, 0x5300, 0x2880, 0x2a00, 0x8000, 0xffff])
def test_anything_else_in_the_slot_leaves_the_tracks_own_rec(audio, value):
    """Whatever a track of the unit has there with no lock: with these, REC is the bit of MODE, both ways."""
    e = engine(audio)
    e.set_slot(3, MODE, REC)
    word(e, 3, value)
    data = held_note(e, track=3, n=8)
    assert is_take(taken(e, 6), data, 0, 8) and untouched(e, but=(6, 7))
    e = engine(audio)
    word(e, 3, value)
    held_note(e, track=3, n=8)
    assert untouched(e)


@pytest.mark.parametrize("value, on", [(0x5200, True), (0x5280, True), (0x52ff, True), (0x2900, False), (0x2980, False), (0x29ff, False)])
def test_the_mark_is_the_high_byte_so_the_smoothing_cannot_miss_it(audio, value, on):
    """The lock is written with 0x80 under the mark: half a number either way is still the mark."""
    e = engine(audio)
    e.set_slot(3, MODE, MONO if on else REC)
    word(e, 3, value)
    held_note(e, track=3, n=8)
    assert untouched(e) != on


def test_the_take_ends_when_the_lock_is_put_back(audio):
    """A lock holds to the track's next event; then the slot is what it was, and the take is over."""
    e = engine(audio)
    word(e, 1, ON)
    data = noise(12, 6)
    for b in range(6):
        fed(e, data[b], trig=2 if b == 0 else 0)
    word(e, 1, 0)
    for b in range(6, 12):
        fed(e, data[b])
    got = taken(e, 2)
    assert 4 * BLOCK <= len(got) <= 7 * BLOCK
    whole = data[:, :, 0].ravel()
    assert any(np.array_equal(got, whole[a:a + len(got)]) for a in range(0, 3 * BLOCK, BLOCK))


def test_a_take_the_track_started_ends_at_a_step_locked_off(audio):
    e = engine(audio)
    e.set_slot(1, MODE, REC)
    data = noise(12, 6)
    for b in range(6):
        fed(e, data[b], trig=2 if b == 0 else 0)
    word(e, 1, OFF)
    for b in range(6, 12):
        fed(e, data[b])
    assert 4 * BLOCK <= len(taken(e, 2)) <= 7 * BLOCK


@pytest.mark.parametrize("value", [0, 0x7f00, 0x0100])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_playing_is_the_floor_images_engine_whatever_else_the_slot_holds(audio, floor, case, value):
    """The voice loop copies the slot into the voice's hold flag; ours clears it, as before."""
    knobs = CASES[case]
    script = rest(knobs.get("start", 0), knobs.get("length", 127), 30)

    def run(built, value):
        from test_fade import start
        e = start(built, **knobs)
        word(e, 0, value)
        out = np.array([e.block(trig=1)] + [e.block() for _ in script])
        return out[1:, 0, :].ravel(), out[1:, 1, :].ravel()
    a, ar = run(audio, value)
    b, br = run(floor, 0)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


@pytest.mark.parametrize("name", ["a walk, looped", "stereo", "ping-pong", "LEN down to a buzz and back"])
def test_with_the_knobs_moving_it_is_the_floor_images_engine(audio, floor, name):
    knobs, script = SCRIPTS[name]
    _, a, ar = play(audio, script, **knobs)
    _, b, br = play(floor, script, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


def test_what_it_costs_on_the_audio_cpu(audio, floor):
    """Instructions in a block of the whole voice loop over the floor image's, all eight tracks samplers."""
    def count(built, starting):
        e = engine(built, pool={k: np.zeros(4000, dtype=np.int16) for k in range(8)})
        e.block(trig=0xFF)
        e.block()
        n0 = e.mc.insns
        e.block(trig=0xFF if starting else 0)
        if starting:
            n0 = e.mc.insns
            e.block()
        return e.mc.insns - n0
    assert (count(audio, False) - count(floor, False), count(audio, True) - count(floor, True)) == COST


COST = (112, 208)           # eight voices: 14 instructions a voice a block for the test, 12 more where a note starts


# ---- the feed --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return MainRig(*main)


def block(modes, locks=None):
    """The mixer's parameters: a MODE a track, and slot 24 of each: nothing there, or what `locks` says."""
    b = bytearray(make_block(ALL, modes))
    for t in range(12):
        b[STRIDE * t + P_REC:STRIDE * t + P_REC + 2] = dict(locks or {}).get(t, 0).to_bytes(2, "big")
    return bytes(b)


@pytest.mark.parametrize("mode, left", [(MONO, mm.F_MAIN_L), (STEREO, mm.F_MAIN_L), (EXT, mm.F_EXT_L), (EXT | STEREO, mm.F_EXT_L)])
@pytest.mark.parametrize("track", [0, 7])
def test_the_feed_runs_for_a_step_locked_on_from_the_tracks_source(rig, track, mode, left):
    frame = frames()
    window = junk(0x0105)
    ret, after = rig.run(block([0] * track + [mode] + [0] * (11 - track), {track: ON}), frame, window)
    assert ret == 0x8000DBD0 and after == fed_from(window, frame, left)


def test_nothing_is_fed_for_a_step_locked_off(rig):
    window = junk(0x0105)
    _, after = rig.run(block([REC] + [0] * 11, {0: OFF}), frames(), window)
    assert after == window


@pytest.mark.parametrize("value", [0, 0x0100, 0x7f00, 0x5180, 0x5300, 0x2880, 0x2a00, 0xffff])
def test_anything_else_in_the_slot_leaves_the_feed_to_the_tracks_rec(rig, value):
    frame = frames()
    window = junk(0x0105)
    _, after = rig.run(block([0, 0, REC | EXT] + [0] * 9, {t: value for t in range(12)}), frame, window)
    assert after == fed_from(window, frame, mm.F_EXT_L)
    _, after = rig.run(block([EXT | STEREO] * 12, {t: value for t in range(12)}), frame, window)
    assert after == window


def test_the_first_track_in_record_by_either_way_picks_the_source(rig):
    frame = frames()
    window = junk(0x0105)
    _, after = rig.run(block([0, REC, EXT, 0, REC] + [0] * 7, {1: OFF, 2: ON}), frame, window)
    assert after == fed_from(window, frame, mm.F_EXT_L)     # track 2 is locked off, track 3 on: its source is the external input
    _, after = rig.run(block([0, REC, EXT, 0, REC] + [0] * 7, {1: OFF, 2: OFF}), frame, window)
    assert after == fed_from(window, frame, mm.F_MAIN_L)    # then track 5, by its own REC


def test_a_mark_on_a_track_that_is_no_sampler_feeds_nothing(rig):
    window = junk(0x0105)
    machines = [0] * 8 + [8, 9, 10, 11]
    b = bytearray(make_block(machines, [0] * 12))
    for t in range(12):
        b[STRIDE * t + P_REC:STRIDE * t + P_REC + 2] = ON.to_bytes(2, "big")
    _, after = rig.run(bytes(b), frames(), window)
    assert after == window


# ---- the image -------------------------------------------------------------------------------------

def test_the_image_is_the_floor_image_but_for_our_code_and_the_pointers_to_it(official_path, official, stock, stock3, audio, floor, main, before):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, floor=True)[2]
    raw, _, built, regions, syms = build.build(official_path, log=quiet, reclock=True)
    assert sorted(regions) == [3, 7] and built.section(7) == audio[0] and built.section(3) == main[0]
    assert was.section(7) == floor[0] and was.section(3) == before[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    # the audio CPU: our runs of code, and the three pointers into them
    spans = list(m.CAVES.values()) + list(m.REC_CAVES.values()) + list(m.FADE_CAVES.values()) + list(m.LIVE_CAVES.values())
    spans += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    diff = [k for k in range(len(stock)) if floor[0][k] != audio[0][k]]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in spans) for k in diff)
    lo, hi = m.REC_CAVES["z"]
    assert lo <= audio[1]["rec_on"] < hi
    # the main CPU: the page's two runs and the feed's, and the pointers to routines that moved in them
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_REC, mm.CAVE_AMUTE]
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(x, x + 4) for x in (mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_BUILD + 6, mm.MIX_CALL + 2, mm.TRIG_MUTE + 2)]
    diff = [k for k in range(len(stock3)) if before[0][k] != main[0][k]]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    for name in ("rec_steps", "sync", "strays"):
        sym = next(a for n, a in main[1].items() if n.startswith(name))
        assert any(lo <= sym < hi for lo, hi in (mm.CAVE_PAGE, mm.CAVE_PAGE2))


def test_the_stock_lock_routines_are_as_they_were(stock3, main):
    """What the page now calls by address, and what plays a lock: none of it is ours and none of it changed."""
    for lo, hi in ((mm.LOCK_READ, mm.LOCK_READ + 0x2c), (mm.LOCK_MAKE, mm.LOCK_DROP + 0x42), (mm.LOCK_TABLE_READ, mm.LOCK_TABLE_READ + 0x74),
                   (mm.LOCK_TABLE_DROP, mm.LOCK_TABLE_MAKE + 0xbc), (mm.STEP_LOCKS, mm.STEP_LOCKS + 0x52), (mm.LOCKS_APPLY, mm.LOCKS_APPLY + 0x9e),
                   (mm.STEP_A, mm.STEP_B + 0x5c), (mm.STEP_TRIG, mm.STEP_TRIG + 0x60)):
        assert main[0][mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    # no knob of a digital track is on slot 24: the descriptors of the machines the audio CPU runs
    from tools import params
    assert not [p for ps in params.machines(main[0], "1.42").values() for p in ps if p.slot == SLOT]
