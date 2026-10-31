"""The handrec image: with the sequencer stopped, a track whose own REC is at ONCE records a note played by hand, for
the TRIG page's LEN, and REC reads OFF after.




the TRIG page's.

Main CPU. recword.S makes slot 24 of the block the audio CPU is sent every block: a step's lock's mark, or what
hand_rec (engine/once.S, in the long image's run) says. Stopped, a track at ONCE gets REC's mark, so the note it is
waiting for records. The block whose trig mask (stock's a5 at that call) has the track takes the ONCE (REC reads OFF),
sets the track's hold bit and what is left of the take: stock's length of the track's TRIG page LEN (the byte at the
pattern's data + 1177 a track + 961, its table from + 4, as the step routine reads them), in the tempo's units. Each
block takes the tempo off it; at nothing the mark goes, the feed stops and the take with it. The feed puts the hold
bits in the high byte of the window's word at 0x802 (engine/recfeed.c). A start (hand_start) clears all of it.

Audio CPU. rec_all ignores a release on a track whose hold bit is set (engine/stub.S HANDREC).

Held here: all of that, recword.S with the once run and the long image's run beside it, and rec_all in the audio CPU's
emulation; a step's own lock still decides; the images differ from the evict image's only where they declare.

Not held: that a note played by hand is in stock's trig mask (a5) as a sequencer's is, that the TRIG page's LEN is the
byte read (a step's LEN falls back to it in the step routine, read in the listing), the length by ear. For the unit.
"""
import shutil

import numpy as np
import pytest

import test_pack as PK
import test_pagerec as P
from emu.engine import BLOCK, RET
from emu.machine import Machine
from test_mode import ST
from test_multi import LANE, recorder
from test_quick import Folded
from test_srr import OFF, ON, Word, signed
from tools import audiomap as m
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

PLAYING, STOPPED = 1, 2
TEMPO = 120 * 120                       # 120 BPM: a step is 2,700,000 of the tempo's units, 187.5 blocks
DATA = 0x7e000000                       # the pattern's data, in the rig


@pytest.fixture(scope="module")
def built(official_path):
    _, _, b, _, syms = build.build(official_path, log=lambda s: None, xfade=81)
    return b, syms


@pytest.fixture(scope="module")
def main(built):
    return built[0].section(3), built[1]


class Hand(Word):
    """recword.S with the once run and the long image's run beside it, the sequencer's state, the tempo, the pattern's
    data and stock's table of lengths."""

    def __init__(self, image, syms):
        super().__init__(image, syms)
        mc = self.mc
        for lo, hi in (mm.CAVE_ONCE, mm.CAVE_LONG):
            mc.map(lo & ~0xfff, 0x1000)
            mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        for a in (mm.SEQ_STATE, mm.TEMPO, mm.PATTERN_DATA):
            try:
                mc.map(a & ~0xfff, 0x1000)
            except Exception:
                pass
        t = mm.LEN_TABLE & ~0xfff
        mc.map(t, 0x1000)
        mc.write(t, image[mm.off(t):mm.off(t) + 0x1000])     # data: stock's table
        mc.map(DATA, 0x4000)
        mc.w32(mm.PATTERN_DATA, DATA)
        mc.w32(mm.TEMPO, TEMPO)
        self.table = [mc.r32(mm.LEN_TABLE + 4 + 4 * k) for k in range(128)]

    def setup(self, state, armed, lens=None):
        self.mc.w32(mm.SEQ_STATE, state)
        self.mc.write(mm.ONCE_ARM, bytes(int(k in armed) for k in range(8)))
        self.mc.write(mm.HAND_HOLD, bytes(36))
        for t, n in (lens or {}).items():
            self.mc.write(DATA + 1177 * t + mm.TRIG_LEN_OWN, bytes((n,)))

    def mark(self, t, own=signed(3, 0), hit=False, lock=None):
        """A block: the track's slot 24 as sent (its high byte), with the track's note in the trig mask or not."""
        self.mc.set_reg(13, (1 << t) if hit else 0)
        return self.run(t, own, lock=lock)["sent"] >> 8

    @property
    def armed(self):
        return list(self.mc.read(mm.ONCE_ARM, 8))

    @property
    def hold(self):
        return self.mc.r32(mm.HAND_HOLD)

    def left(self, t):
        return self.mc.r32(mm.HAND_LEFT + 4 * t)


@pytest.fixture(scope="module")
def hand(main):
    return Hand(*main)


def test_the_table_is_stocks_lengths_a_step_at_the_trig_pages_default(hand):
    assert hand.table[14] == 2_700_000 and hand.table[0] < hand.table[1] < hand.table[126]


@pytest.mark.parametrize("t, length", [(0, 14), (5, 30), (7, 0)])
def test_stopped_at_once_the_mark_waits_and_a_note_holds_its_take_for_the_trig_pages_len(hand, t, length):
    hand.setup(STOPPED, {t}, {t: length})
    for _ in range(3):                                          # waiting for its note
        assert hand.mark(t) == ON and hand.armed == [int(k == t) for k in range(8)] and hand.hold == 0
    assert hand.mark(t, hit=True) == ON                         # its note: the ONCE taken, the take held
    assert hand.armed == [0] * 8 and hand.hold == 1 << t and hand.left(t) == hand.table[length]
    blocks = 1
    while hand.mark(t) == ON:
        blocks += 1
        assert hand.hold == 1 << t
    assert blocks == -(-hand.table[length] // TEMPO)            # as many blocks as the length takes at the tempo
    assert hand.hold == 0 and hand.left(t) == 0 and hand.armed == [0] * 8
    assert hand.mark(t, hit=True) == OFF                        # a note after: plays, records nothing


def test_another_tracks_once_and_note_are_its_own(hand):
    hand.setup(STOPPED, {2}, {2: 14})
    assert hand.mark(4) == OFF and hand.mark(4, hit=True) == OFF
    assert hand.mark(2, hit=True) == ON and hand.hold == 1 << 2


def test_playing_the_once_waits_for_the_sequencer_as_before(hand):
    hand.setup(PLAYING, {3}, {3: 14})
    assert hand.mark(3, hit=True) == OFF and hand.armed[3] == 1 and hand.hold == 0
    assert hand.mark(3, signed(3, 1)) == ON                     # REC on is on


def test_a_steps_own_lock_still_decides(hand):
    hand.setup(STOPPED, {2}, {2: 14})
    assert hand.mark(2, lock=0x2980) == OFF
    assert hand.mark(2, lock=0x52c0) == ON
    hand.setup(STOPPED, set())
    assert hand.run(2, signed(0, 0))["changed"] == [[76, 77], [], []]   # slot 24 of the block, nothing else


def test_a_start_takes_every_tracks_once_and_lets_a_held_take_go(main):
    image, syms = main
    mc = Machine()
    for lo, hi in (mm.CAVE_ONCE, mm.CAVE_LONG):
        mc.map(lo & ~0xfff, 0x1000)
        mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
    mc.map(mm.SEQ_STATE & ~0xfff, 0x1000)
    mc.map(0x8000f000, 0x1000)
    mc.set_stack(0x8000ff00, RET)
    mc.write(mm.ONCE_ARM, bytes((1, 0, 1, 1, 0, 0, 0, 1)) + b"\x01" * 8)
    mc.write(mm.HAND_HOLD, b"\xff" * 36)
    regs = {0: 1, 1: 0x11111111, 2: 0x22222222, 9: 0x99999999}
    for n, v in regs.items():
        mc.set_reg(n, v)
    mc.call(syms["hand_start"])
    assert mc.r32(mm.SEQ_STATE) == 1 and bytes(mc.read(mm.ONCE_ARM, 16)) == bytes(8) + b"\x01" * 8   # the spent bytes kept
    assert bytes(mc.read(mm.HAND_HOLD, 36)) == bytes(36)
    assert {n: mc.reg(n) for n in regs} == regs


@pytest.fixture
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def feed(e, count, track, hold, x):
    e.mc.write(LANE + 4 * BLOCK * track, np.asarray(x).astype(">i2").tobytes())
    e.mc.write(m.MAILBOX, (count & 0xffff).to_bytes(2, "big") + ((1 << track) | hold << 8).to_bytes(2, "big"))


@pytest.mark.parametrize("held", [True, False])
def test_a_held_takes_release_ends_nothing_and_an_unheld_ones_ends_it(built, folded, held):
    track, place = 3, 6
    e = recorder((built[0].section(7), built[1]), {track: place}, 0)
    e.set_slot(track, 24, 0x52 + 7 / 256)                       # REC's mark, as recword.S sends it
    hold = (1 << track) if held else 0
    x = np.random.default_rng(5).integers(-9000, 9000, (4, BLOCK, 2)).astype(np.int16)
    at = e.voice(track) + ST
    e.block(1 << track, 0)                                      # the note
    feed(e, 99, track, hold, x[0])
    e.block(0, 0)                                               # its take starts, and takes from the next block on
    assert e.mc.read(at + PK.S_REC, 1)[0] == 1 and e.mc.r32(at + PK.S_RPOS) == 0
    feed(e, 100, track, hold, x[1])
    e.block(0, 1 << track)                                      # a block taken, and the key let go
    assert e.mc.read(at + PK.S_REC, 1)[0] == int(held) and e.mc.r32(at + PK.S_RPOS) == BLOCK
    for c in (101, 102):
        feed(e, c, track, hold, x[c - 99])
        e.block(0, 0)
    assert e.mc.r32(at + PK.S_RPOS) == (3 if held else 1) * BLOCK


def test_the_image(official_path, built):
    quiet = lambda s: None
    new = built[0]
    was = build.build(official_path, log=quiet, xfade=79)[2]
    n, o = new.section(3), was.section(3)
    spans = [mm.CAVE_ONCE, mm.CAVE_SRR, mm.CAVE_LONG, (mm.STEP_LOCKS_PUSH, mm.STEP_LOCKS_PUSH + 6),
             (mm.STEP_NO_LOCKS, mm.STEP_NO_LOCKS + 4), (mm.MAIN_LOOP_WAIT, mm.MAIN_LOOP_WAIT + 6)] + [(a, a + 6) for a in mm.SEQ_STARTS]
    moved = [mm.BASE + k for k in range(len(n)) if n[k] != o[k] and not any(lo <= mm.BASE + k < hi for lo, hi in spans)]
    feed_runs = [(lo, hi) for lo, hi in (getattr(mm, c) for c in dir(mm) if c.startswith("CAVE_")) if isinstance(lo, int)]
    assert all(any(lo <= a < hi for lo, hi in feed_runs) for a in moved), [hex(a) for a in moved][:8]   # the feed's run, its one write
    for a in mm.SEQ_STARTS:
        k = mm.off(a)
        assert o[k:k + 6] == b"\x23\xc0" + mm.SEQ_STATE.to_bytes(4, "big")
        assert n[k:k + 6] == b"\x4e\xb9" + built[1]["hand_start"].to_bytes(4, "big")
    s7n, s7o = new.section(7), was.section(7)
    lo, hi = m.PITCH_CAVES["r"]                                 # rec_all's run
    assert len(s7n) == len(s7o)
    assert [hex(m.BASE + k) for k in range(len(s7n)) if s7n[k] != s7o[k] and not lo <= m.BASE + k < hi] == []
