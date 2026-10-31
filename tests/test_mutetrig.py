"""The "mute" image: a muted track's trigs still fire (engine/mutetrig.c). OS 1.42 only.

Stock drops an event the sequencer made for a muted track, in the event loop of the routine
that runs every block. Our images already silence a muted track at the mixer and at the analog
voices' level words, so on this image that test is skipped for every track that makes sound,
and kept for a MIDI track.

Emulated here: the stock event loop itself, from where it takes up an event for a track to
where it has decided to keep it or drop it, as it is in the image, with our routine called from
inside it. It is run for every track against every mix of event, mute, solo, pattern mute and
MIDI track, next to the same code of the image before (the bank image's main program), which is
what says what "not muted" and "stock's mute" are. The UI's own routine for "is this a MIDI
track" is run on the same kit. And the recorder's feed with the mixer link under it, for a
track that is muted and in record.

Nothing here says what a unit does with it: that every event the sequencer makes for a muted
track comes through this one test, what the trig keys show for a muted track, that a note
started under a mute is silent from its first frame. See docs/FINDINGS.md.
"""
import itertools
import shutil

import numpy as np
import pytest
from unicorn.m68k_const import UC_M68K_REG_PC

from emu.machine import Machine
from tools import audiomap as m
from tools import build_main, disasm
from tools import mainmap as mm
from test_recorder import BLOCK, MainRig, RND, STRIDE, frames, junk, make_block, ring_at, rnd_of, to16
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

P_VOL = 124
KIT = 0x41000000                 # a kit
EVENT = 0x41010000               # an event
KIT_OBJECT = 0x41020000          # the UI's object for a kit, for its own "is a MIDI track"
FRAME = 0x407e0000               # the per-block routine's frame: fp
STACK = 0x407f0000
OWNERS = 0x43bdd34c              # 28 bytes a track, read by the check after the mute tests
HELD = 0x43bdf43e                # a word, a bit a track: a note-on is dropped while it is set
MASK, UI_GLOBAL, UI_PATTERN = -56, -74, -70     # in the frame: the mute mask, and the muted trigs the UI is told of
TRACKS = 12
NOTE_ON, SEQUENCER, HAS_NOTE = 1, 1, 0x80


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, bank=True)


@pytest.fixture(scope="module")
def built(stock3):
    return build_main.patched_image(stock3, mute=True)


class Loop:
    """The event loop's code for one event of a track, from the image, with memory of the test's."""

    def __init__(self, image):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x41000000, 0x30000)
        mc.map(0x80000000, 0x10000)
        mc.map(mm.PATTERN_MUTES & ~0xffff, 0x10000)
        mc.write(mm.BASE, image)
        mc.write(KIT_OBJECT, (KIT_OBJECT + 0x100).to_bytes(4, "big"))                       # its method table
        mc.w32(KIT_OBJECT + 0x100 + 52, KIT_OBJECT + 0x200)                                 # + 52: where the kit is
        mc.write(KIT_OBJECT + 0x200, b"\x20\x3c" + KIT.to_bytes(4, "big") + b"\x4e\x75")    # movel #KIT,%d0 ; rts
        mc.set_stack(STACK, 0x40000100)
        mc.set_exits([mm.TRIG_KEPT, mm.TRIG_NEXT, 0x40000100])

    def event(self, track, kind=NOTE_ON, source=SEQUENCER, flags=HAS_NOTE, mutes=0, pattern=0, midi=0, held=0, kit=KIT, owner=None):
        """One event through the loop. -> (kept, the UI's muted trigs by the global mutes, by the pattern's)."""
        mc = self.mc
        mc.write(EVENT, bytes(0x60))
        for at, v in ((4, kind), (8, track), (12, source), (16, 0x1234), (36, flags)):
            mc.w32(EVENT + at, v)
        mc.write(KIT, bytes(0x2000))
        mc.write(KIT + mm.KIT_MIDI, midi.to_bytes(2, "big"))
        mc.w32(mm.KIT_NOW, kit)
        mc.write(mm.PATTERN_MUTES, pattern.to_bytes(2, "big"))
        mc.write(HELD, held.to_bytes(2, "big"))
        mc.write(OWNERS, bytes(28 * 13))
        if owner is not None:
            mc.w32(OWNERS + 28 * track, owner[0])
            mc.w32(OWNERS + 28 * track + 4, owner[1])
        mc.write(FRAME - 0x100, bytes(0x100))
        mc.w32(FRAME + MASK, mutes)
        for n, v in ((0, kind), (1, source), (2, track), (3, 0x33333333), (4, 0x44444444), (5, 0x55555555), (6, 0x66666666),
                     (7, 0x77777777), (8, 0x0BAD00A0), (9, 0x0BAD00A1), (10, EVENT), (11, 0x0BAD00A3), (12, 0x0BAD00A4),
                     (13, 0x0BAD00A5), (14, FRAME), (15, STACK - 0x400)):
            mc.set_reg(n, v)
        mc.uc.emu_start(mm.TRIG_EVENT, 0)
        pc = mc.uc.reg_read(UC_M68K_REG_PC)
        assert pc in (mm.TRIG_KEPT, mm.TRIG_NEXT)
        assert mc.reg(15) == STACK - 0x400                                 # the stack is where it was
        assert (mc.reg(2), mc.reg(10), mc.reg(14)) == (track, EVENT, FRAME)
        assert (mc.reg(3), mc.reg(5), mc.reg(6)) == (0x33333333, 0x55555555, 0x66666666)
        word = lambda at: int.from_bytes(mc.read(FRAME + at, 2), "big")
        return pc == mm.TRIG_KEPT, word(UI_GLOBAL), word(UI_PATTERN)

    def is_midi(self, track):
        """Stock's own answer, as the UI asks it of a kit object."""
        return self.mc.call(mm.TRACK_IS_MIDI, KIT_OBJECT, track) & 0xff


@pytest.fixture(scope="module")
def loops(before, built):
    return Loop(before[0]), Loop(built[0])


# ---- what it is for --------------------------------------------------------------------------------

@pytest.mark.parametrize("track", range(TRACKS))
def test_a_muted_tracks_trig_is_kept(loops, track):
    was, now = loops
    bit = 1 << track
    for mutes, pattern in ((bit, 0), (0, bit), (bit, bit), (0x1fff, 0x1fff)):
        assert was.event(track, mutes=mutes, pattern=pattern)[0] is False     # the image before drops it
        assert now.event(track, mutes=mutes, pattern=pattern) == (True, 0, 0)  # this one runs it, and tells the UI of no muted trig


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_solo_elsewhere_does_not_stop_a_trig_either(loops, track):
    """With a solo the mask the loop is handed is everything but the solo tracks."""
    was, now = loops
    others = ~(1 << ((track + 5) % TRACKS)) & 0xFFFFFFFF
    assert was.event(track, mutes=others)[0] is False
    assert now.event(track, mutes=others)[0] is True


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_muted_midi_tracks_trig_is_dropped_as_it_was(loops, track):
    was, now = loops
    bit = 1 << track
    for mutes, pattern in ((bit, 0), (0, bit), (bit, bit)):
        want = (False, bit if mutes else 0, bit if pattern else 0)             # dropped, and the UI told by which mute
        assert was.event(track, mutes=mutes, pattern=pattern, midi=bit) == want
        assert now.event(track, mutes=mutes, pattern=pattern, midi=bit) == want
    assert now.event(track, midi=bit) == (True, 0, 0)                          # and plays when it is not muted


def test_every_kind_of_event_is_let_through_not_only_a_note_on(loops):
    """A note's end, and whatever else the sequencer sends a track, was dropped under a mute too."""
    was, now = loops
    for kind, flags in itertools.product((0, 1, 2, 3, 7), (0, 0x80, 0x81, 0x8000, 0x20080)):
        assert was.event(4, kind=kind, flags=flags, mutes=1 << 4)[0] is False
        assert now.event(4, kind=kind, flags=flags, mutes=1 << 4)[0] is True


# ---- against the image before, case by case --------------------------------------------------------

CASES = [dict(kind=kind, source=source, flags=flags, held=held, owner=owner)
         for kind in (1, 0, 2)
         for source in (1, 0, 2, 0xFFFFFFFF)
         for flags in (0, 0x80, 0x40080)
         for held in (0, 0x1fff)
         for owner in (None, (0x1234, 1), (0x9999, 1))]
MUTES = [(0, 0), (0x1fff, 0), (0, 0x1fff), (0x1fff, 0x1fff), (0x0aaa, 0x0555), (0xFFFFFFFF, 0xFFFF)]


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_track_that_makes_sound_is_treated_as_the_image_before_treats_an_unmuted_one(loops, track):
    was, now = loops
    seen = set()
    for case in CASES:
        unmuted = was.event(track, **case)
        for mutes, pattern in MUTES:
            assert now.event(track, mutes=mutes, pattern=pattern, **case) == unmuted
            seen.add((was.event(track, mutes=mutes, pattern=pattern, **case)[0], unmuted[0]))
    assert seen == {(True, True), (False, False), (False, True)}      # the cases do hold events a mute alone dropped


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_midi_track_is_treated_exactly_as_before(loops, track):
    was, now = loops
    dropped = 0
    for case in CASES:
        for mutes, pattern in MUTES:
            for midi in (1 << track, 0x0fff):
                got = now.event(track, mutes=mutes, pattern=pattern, midi=midi, **case)
                assert got == was.event(track, mutes=mutes, pattern=pattern, midi=midi, **case)
                dropped += not got[0]
    assert dropped


def test_only_the_tracks_own_bit_of_the_kit_counts(loops):
    was, now = loops
    for track in range(TRACKS):
        others = 0x0fff & ~(1 << track)
        assert now.event(track, mutes=0x1fff, midi=others)[0] is True
        assert now.event(track, mutes=0x1fff, midi=1 << track)[0] is False


def test_with_no_kit_yet_it_is_stock(loops):
    """Before the first kit is brought, the word the routine would read is not there to read."""
    was, now = loops
    for track in (0, 7, 11):
        for mutes in (0, 1 << track):
            assert now.event(track, mutes=mutes, kit=0) == was.event(track, mutes=mutes, kit=0)
    assert now.event(3, mutes=1 << 3, kit=0)[0] is False


def test_the_kits_word_is_the_one_the_ui_calls_a_midi_track(loops):
    """Stock's routine behind "a track's machine", run on a kit object over the same kit."""
    was, now = loops
    for midi in (0, 1, 0x0800, 0x0a5a, 0x0fff):
        for track in range(TRACKS):
            now.event(track, mutes=0x1fff, midi=midi)
            stock_says = now.is_midi(track)
            assert stock_says == (midi >> track) & 1
            assert now.event(track, mutes=0x1fff, midi=midi)[0] is (not stock_says)


# ---- the FX track, and the rest of the program ------------------------------------------------------

def test_the_fx_tracks_own_test_is_left_alone(stock3, built):
    image, _ = built
    at = 0x400a3d5e                                    # moveq #1,%d7 ; cmpl %d1,%d7 ; bnes ; tstl %fp@(-44) ; bnes ; movew PATTERN_MUTES,%d1
    code = bytes.fromhex(fw.sx("d2a3052ef6e9ec4bad7208fb540f64782b18f99eb15f"))
    assert stock3[mm.off(at):mm.off(at) + len(code)] == code == image[mm.off(at):mm.off(at) + len(code)]


def test_the_main_program_differs_from_the_bank_images_in_one_call_and_the_routine(before, built):
    (was, _), (image, syms) = before, built
    changed = [mm.BASE + i for i in range(len(was)) if was[i] != image[i]]
    site = range(mm.TRIG_MUTE, mm.TRIG_MUTE + 6)
    routine = range(syms["mute_trig"], syms["mute_trig"] + 34)
    assert all(a in site or a in routine for a in changed) and set(site) <= set(changed)
    assert mm.CAVE_REC[0] <= routine[0] and routine[-1] < mm.CAVE_REC[1]            # in the feed's run, after the feed
    assert syms["mix_rec"] == mm.CAVE_REC[0] and routine[0] >= syms["mix_rec"] + 166
    assert was[mm.off(routine[0]):mm.off(routine[-1]) + 1] == b"\x4e\x71" * 17       # where the bank image has nothing
    assert image[mm.off(mm.TRIG_MUTE):mm.off(mm.TRIG_MUTE) + 6] == b"\x4e\xb9" + syms["mute_trig"].to_bytes(4, "big")


def test_the_routine_is_what_the_source_says(built, tmp_path):
    image, syms = built
    path = tmp_path / "main.bin"
    path.write_bytes(image)
    text = disasm.disasm(str(path), mm.BASE, syms["mute_trig"], syms["mute_trig"] + 34)
    ops = [line.split("\t")[-1].strip() for line in text.strip().splitlines()]
    assert ops == ["movel 0x800030b8,%d1", "beqs %#x" % (syms["mute_trig"] + 26), "moveal %d1,%a0", "mvsw %a0@(5456),%d1",
                   "btst %d2,%d1", "bnes %#x" % (syms["mute_trig"] + 26), "addql #4,%sp", "jmp %#x" % mm.TRIG_UNMUTED,
                   "movel %fp@(-56),%d1", "asrl %d2,%d1", "rts"]


def test_nothing_else_in_the_program_goes_into_the_six_bytes(stock3):
    """The call takes the place of two instructions: no branch and no address may point between them."""
    lo, hi = mm.TRIG_MUTE, mm.TRIG_MUTE + 6
    for a in range(lo + 1, hi):
        assert a.to_bytes(4, "big") not in stock3
    routine = stock3[mm.off(0x400a38ce):mm.off(0x400a5700)]
    for at in range(0, len(routine) - 4, 2):
        op = routine[at]
        if op >> 4 != 6:                                   # a branch, short or word
            continue
        disp = routine[at + 1]
        target = None
        if disp == 0:
            target = 0x400a38ce + at + 2 + int.from_bytes(routine[at + 2:at + 4], "big", signed=True)
        elif disp != 0xff:
            target = 0x400a38ce + at + 2 + (disp - 256 if disp > 127 else disp)
        assert target is None or not lo < target < hi


# ---- a take on a muted track ----------------------------------------------------------------------

@pytest.mark.parametrize("mode, left", [(2, 0), (6, 18)])
def test_the_feed_runs_for_a_track_that_is_muted_and_in_record(built, mode, left):
    """The recorder's feed looks at MODE and not at the mutes: with the trig let through, a take is made unheard."""
    image, syms = built
    rig = MainRig(image, syms)
    block = make_block([44 if t == 3 else 4 for t in range(12)], [mode if t == 3 else 0 for t in range(12)])
    rig.mc.w32(mm.MUTES, 1 << 3)
    frame = frames()
    start = junk(6)
    _, window = rig.run(block, frame, start)
    want = bytearray(start)
    want[m.MAILBOX:m.MAILBOX + 2] = (7).to_bytes(2, "big")                                 # one block went to the audio CPU
    pair, rnd = to16(frame[:, left:left + 2], rnd_of(start))
    want[ring_at(7):ring_at(7) + 4 * BLOCK] = pair.astype(">i2").tobytes()
    want[RND:RND + 4] = rnd.to_bytes(4, "big")
    assert window == bytes(want)
    seen = rig.seen["params"]
    assert seen[STRIDE * 3 + P_VOL:STRIDE * 3 + P_VOL + 2] == b"\0\0"                      # and the mixer is shown none of the track
    assert seen[STRIDE * 2 + P_VOL:STRIDE * 2 + P_VOL + 2] == block[STRIDE * 2 + P_VOL:STRIDE * 2 + P_VOL + 2]
