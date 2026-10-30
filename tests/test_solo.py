"""The "solo" image: the purple pattern mutes as solos (engine/solo.S). OS 1.42 only, main CPU only.

A pattern's word of mutes is left as it is, in the pattern and for the keys that set it. What the two
engines are given of it, at the four places that store their copies, is the tracks its solos silence:
with any of the twelve tracks' bits set, those twelve turned over. Every reader is stock's or ours as
it was.

Emulated here, from the built image:
  - stock's two routines that store a copy, called as stock calls them, for every word there is;
  - the two stores in the engines' own loops, run from stock's instructions before them to the ones after;
  - stock's track test in both loops, with the word as the image stored it;
  - our mixer link and analog mute, with the word put through stock's routine first: the volume the
    mixer is shown and the analog voices' level words;
  - the keys: our answer next to stock's own for the word the solos make, at the routine that colours
    the keys (from its call to the colour it settles on) and at the draw's question.
And that the main program differs from the stops image's only at the declared places, that nothing in
the routines around them branches into one, and that section 7 is the stops image's.

Nothing here says what a unit does: that a key press reaches the sound, what the keys and the screen
show, a pattern change, a project's load, song mode, MIDI. See docs/FINDINGS.md.
"""
import re
import shutil

import pytest
from unicorn.m68k_const import UC_M68K_REG_PC

import test_mainpatch as M
from emu.machine import Machine, boundaries
from test_mutetrig import Loop
from tools import build, build_engine, build_main, deadcode, disasm
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TRACKS, FX = 12, 12
ALL = 0x0fff
MEM = 0x41000000                 # the test's own memory
PATTERN, TABLE, METHOD, NO_SETTINGS, SETTINGS = MEM, MEM + 0x100, MEM + 0x200, MEM + 0x280, MEM + 0x300     # a pattern object, as far as stock asks
MESSAGE, WORD, VIEW, EVENT = MEM + 0x400, MEM + 0x500, MEM + 0x600, MEM + 0x800
STACK, RET = 0x407f0000, 0x40000100
MSG_AT, MSG_END = mm.PATTERN_MUTES_MSG - 8, mm.PATTERN_MUTES_MSG + 6       # moveal %a2@(12),%a0 ; tstl ; beqs ; (the store) ; then on
MIDI_AT, MIDI_END = mm.MIDI_MUTES_MSG - 10, 0x4010e528                     # moveal %a2@(8),%a0 ; tstl ; beqw ; (the store) ; braw
MIDI_TEST, MIDI_DROPPED, MIDI_KEPT, MIDI_OTHER = 0x4010de58, 0x4010de88, 0x4010ded0, 0x4010dee2
MIDI_MUTES, MIDI_SOLOS = 0x444b62b0, 0x444b62b4                            # the MIDI engine's own copies of the global mutes and solos
KEY_SETTLED = mm.KEY_COLOURS + 0x13e                                       # movel %d0,%sp@-: the key's colour is in d0
LIT, LIT_FLAG, DARK = 28, 26, 2                                            # as the routine has them: the bit clear, the same with its flag, the bit set
MARKS = {n: 0x0BAD0000 + n for n in range(1, 15) if n != 8}                # d1..d7, a1..a6
REG = dict({"d%d" % n: n for n in range(8)}, **{"a%d" % n: 8 + n for n in range(8)})


def silenced(word):
    """The rule: the tracks a pattern's solos silence. Bits 12 and up are never touched and never count."""
    return word ^ ALL if word & ALL else word


WORDS = sorted(set(range(0x2000)) | {0x2000, 0x4001, 0x8000, 0xe000, 0xefff, 0xf001, 0xf800, 0xffff})


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, solo=True)


@pytest.fixture(scope="module")
def before(stock3):
    """The stops image's main program."""
    return build_main.patched_image(stock3, stops=True)


class Program:
    """The main program in memory, with both copies' pages and room for a pattern, a message and a view."""

    def __init__(self, image):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(MEM, 0x10000)
        mc.map(mm.PATTERN_MUTES & ~0xffff, 0x10000)
        mc.map(mm.MIDI_PATTERN_MUTES & ~0xffff, 0x10000)
        mc.write(mm.BASE, image)
        mc.set_stack(STACK, RET)
        mc.write(METHOD, b"\x20\x3c" + SETTINGS.to_bytes(4, "big") + b"\x4e\x75")       # movel #SETTINGS,%d0 ; rts
        mc.write(NO_SETTINGS, b"\x70\x00\x4e\x75")                                     # moveq #0,%d0 ; rts
        mc.set_exits([RET, MSG_END, MIDI_END, MIDI_DROPPED, MIDI_KEPT, MIDI_OTHER, KEY_SETTLED])

    def copies(self):
        return tuple(int.from_bytes(self.mc.read(a, 2), "big") for a in (mm.PATTERN_MUTES, mm.MIDI_PATTERN_MUTES))

    def marks(self, **more):
        for n, v in list(MARKS.items()) + [(REG[k], v) for k, v in more.items()]:
            self.mc.set_reg(n, v)

    def kept(self, but=()):
        return all(self.mc.reg(n) == v for n, v in MARKS.items() if n not in but)

    def set(self, routine, word, high=0):
        """Stock's routine (word), as its callers call it: a long on the stack. -> both copies after."""
        self.mc.write(mm.PATTERN_MUTES, b"\xa5\x5a")
        self.mc.write(mm.MIDI_PATTERN_MUTES, b"\xa5\x5a")
        self.marks()
        self.mc.call(routine, high << 16 | word)
        assert self.kept() and self.mc.reg(15) == STACK - 4          # d1..d7 and a1..a6 as they were; the caller pops its long
        assert self.mc.reg(8) == STACK - 2                           # a0: the word on the stack, as stock leaves it
        return self.copies()

    def message(self, start, end, at, word, there=True):
        """The store in an engine's loop, from stock's instructions that take the pointer out of the message. -> both copies."""
        mc = self.mc
        mc.write(mm.PATTERN_MUTES, b"\xa5\x5a")
        mc.write(mm.MIDI_PATTERN_MUTES, b"\xa5\x5a")
        mc.write(MESSAGE, bytes(0x40))
        mc.w32(MESSAGE + at, WORD if there else 0)
        mc.write(WORD - 2, b"\x77\x77" + word.to_bytes(2, "big") + b"\x77\x77")
        self.marks(a2=MESSAGE)
        mc.set_reg(0, 0x0BAD00D0)
        mc.set_reg(15, STACK - 0x100)
        mc.uc.emu_start(start, 0)
        assert mc.uc.reg_read(UC_M68K_REG_PC) == end
        assert self.kept(but=(10,)) and mc.reg(10) == MESSAGE and mc.reg(15) == STACK - 0x100
        assert mc.reg(8) == (WORD if there else 0)                   # a0: the pointer, as stock leaves it
        return self.copies()

    def pattern(self, word, data=True):
        """A pattern object whose settings hold this word of mutes, or one with no settings."""
        mc = self.mc
        mc.w32(PATTERN, TABLE)
        mc.w32(TABLE + mm.PATTERN_SETTINGS, METHOD if data else NO_SETTINGS)
        mc.write(SETTINGS, b"\x55" * 16 + word.to_bytes(2, "big") + b"\x55" * 14)
        return PATTERN

    def colour(self, start, d0, track, flag=0):
        """Stock's routine that colours the keys, from `start` to where the key's colour is settled. -> the colour."""
        mc = self.mc
        mc.write(VIEW, bytes(0x100))                                 # + 136: no key is prepared
        self.marks(d2=track, d5=flag, a2=VIEW)
        mc.set_reg(0, d0)
        mc.set_reg(15, STACK - 0x100)
        mc.uc.emu_start(start, 0)
        assert mc.uc.reg_read(UC_M68K_REG_PC) == KEY_SETTLED
        assert self.kept(but=(1, 2, 5, 10)) and (mc.reg(2), mc.reg(5), mc.reg(10)) == (track, flag, VIEW)
        return mc.reg(0)

    def midi_event(self, track, mutes=0, solos=0, source=1):
        """The MIDI engine's loop, its test of an event's track. -> kept."""
        mc = self.mc
        mc.write(EVENT, bytes(0x40))
        mc.w32(EVENT + 4, track)
        mc.w32(EVENT + 40, source)
        mc.w32(MIDI_MUTES, mutes)
        mc.w32(MIDI_SOLOS, solos)
        self.marks(a2=EVENT)
        mc.set_reg(15, STACK - 0x100)
        mc.uc.emu_start(MIDI_TEST, 0)
        pc = mc.uc.reg_read(UC_M68K_REG_PC)
        assert pc in (MIDI_DROPPED, MIDI_KEPT) and mc.reg(2) == track and mc.reg(10) == EVENT
        return pc == MIDI_KEPT


@pytest.fixture(scope="module")
def now(main):
    return Program(main[0])


@pytest.fixture(scope="module")
def was(before):
    return Program(before[0])


# ---- the rule ------------------------------------------------------------------------------------------------------------

def test_the_rule():
    assert silenced(0) == 0 and silenced(0x1000) == 0x1000                   # no solo: nothing. The FX track's bit alone is no solo
    assert silenced(0b100) == ALL & ~0b100 and silenced(0b100 | 0x1000) == (ALL & ~0b100) | 0x1000
    assert silenced(ALL) == 0                                                # all twelve soloed: all twelve heard
    for word in WORDS:
        s = silenced(word)
        assert s & ~ALL == word & ~ALL                                       # the FX track's bit, and the three above it, as they were
        assert silenced(s) == word or word & ALL == ALL                      # its own way back, but from all twelve
        assert s & word & ALL == 0                                           # a soloed track is never one of the silenced


# ---- the four places a copy is stored -------------------------------------------------------------------------------------

def test_stocks_two_routines_store_the_tracks_the_solos_silence(now, was):
    for word in WORDS:
        want = silenced(word)
        assert now.set(mm.PATTERN_MUTES_SET, word) == (want, 0xa55a)         # its own copy, and not the other
        assert now.set(mm.MIDI_MUTES_SET, word) == (0xa55a, want)
    for word in (0, 1, 0x0800, 0x0a5a, ALL, 0x1000, 0x1fff, 0xffff):         # the long's upper half is not read, as it was not
        assert now.set(mm.PATTERN_MUTES_SET, word, high=0xffff) == (silenced(word), 0xa55a)
        assert now.set(mm.MIDI_MUTES_SET, word, high=0x8001) == (0xa55a, silenced(word))
        assert was.set(mm.PATTERN_MUTES_SET, word) == (word, 0xa55a)         # the image before: the word itself
        assert was.set(mm.MIDI_MUTES_SET, word) == (0xa55a, word)


def test_the_two_stores_in_the_engines_loops_do_the_same(now, was):
    words = sorted(set(range(0, 0x2000, 37)) | {1, ALL, 0x1000, 0x1001, 0x1fff, 0x8000, 0xffff})
    for word in words:
        want = silenced(word)
        assert now.message(MSG_AT, MSG_END, 12, word) == (want, 0xa55a)
        assert now.message(MIDI_AT, MIDI_END, 8, word) == (0xa55a, want)
    for word in (0, 0b100, ALL, 0x1fff):
        assert was.message(MSG_AT, MSG_END, 12, word) == (word, 0xa55a)
        assert was.message(MIDI_AT, MIDI_END, 8, word) == (0xa55a, word)
        # a message that brings no word stores none
        assert now.message(MSG_AT, MSG_END, 12, word, there=False) == now.message(MIDI_AT, MIDI_END, 8, word, there=False) == (0xa55a, 0xa55a)


# ---- stock's own track tests, with the word as it is stored ---------------------------------------------------------------

@pytest.fixture(scope="module")
def loop(main):
    r = Loop(main[0])
    r.mc.map(mm.MIDI_PATTERN_MUTES & ~0xffff, 0x10000)
    return r


def stored(loop, word):
    loop.mc.call(mm.PATTERN_MUTES_SET, word)
    return int.from_bytes(loop.mc.read(mm.PATTERN_MUTES, 2), "big")


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_midi_tracks_trig_is_dropped_while_another_track_is_soloed(loop, track):
    """Stock's test in the per-block routine's loop, which our images keep for a MIDI track."""
    bit, other = 1 << track, 1 << (track + 5) % TRACKS
    midi = dict(midi=bit)
    assert loop.event(track, pattern=stored(loop, 0), **midi) == (True, 0, 0)                    # no solo
    assert loop.event(track, pattern=stored(loop, bit), **midi) == (True, 0, 0)                  # its own
    assert loop.event(track, pattern=stored(loop, bit | other), **midi) == (True, 0, 0)          # one of two
    assert loop.event(track, pattern=stored(loop, other), **midi) == (False, 0, bit)             # another's: dropped, the UI told by the pattern's
    assert loop.event(track, pattern=stored(loop, ALL & ~bit), **midi) == (False, 0, bit)
    assert loop.event(track, pattern=stored(loop, 0x1000), **midi) == (True, 0, 0)               # the FX track's mute is no solo
    assert loop.event(track, pattern=stored(loop, ALL), **midi) == (True, 0, 0)
    assert loop.event(track, mutes=bit, pattern=stored(loop, bit), **midi) == (False, bit, 0)    # a global mute still mutes a soloed track
    assert loop.event(track, mutes=other, pattern=stored(loop, bit), **midi) == (True, 0, 0)


@pytest.mark.parametrize("track", range(TRACKS))
def test_a_track_that_makes_sound_keeps_its_trigs_whatever_is_soloed(loop, track):
    """As under a mute, from the mute image on: the sound is taken away at the mixer, the trig runs (and a take can be made)."""
    bit, other = 1 << track, 1 << (track + 5) % TRACKS
    for word in (0, bit, other, ALL & ~bit, 0x1fff, 0x1000):
        for mutes in (0, bit):
            assert loop.event(track, mutes=mutes, pattern=stored(loop, word)) == (True, 0, 0)


@pytest.mark.parametrize("track", range(TRACKS))
def test_the_midi_engines_own_test_goes_by_its_copy(now, was, track):
    bit, other = 1 << track, 1 << (track + 7) % TRACKS
    for word in (0, bit, other, bit | other, ALL & ~bit, ALL, 0x1000, 0x1000 | other, 0x0a5a):
        assert now.set(mm.MIDI_MUTES_SET, word)[1] == silenced(word)
        heard = not silenced(word) >> track & 1
        assert now.midi_event(track) is heard
        assert now.midi_event(track, mutes=bit) is False                     # a global mute still mutes
        assert now.midi_event(track, mutes=other) is heard
        assert was.set(mm.MIDI_MUTES_SET, word)[1] == word                   # the image before: the same test, the word a mute
        assert was.midi_event(track) is (not word >> track & 1)


# ---- our mixer link and analog mute: what is silenced ---------------------------------------------------------------------

class Rig(M.Rig):
    """test_mainpatch's rig, with the pattern's word put through stock's routine as it is in the image."""

    def run(self, block, level2, mutes=0, solos=0, pattern=0):
        self.mc.write(mm.PATTERN_MUTES, b"\xa5\x5a")
        self.mc.call(mm.PATTERN_MUTES_SET, pattern)
        self.stored = int.from_bytes(self.mc.read(mm.PATTERN_MUTES, 2), "big")
        return super().run(block, level2, mutes, solos, self.stored)


@pytest.fixture(scope="module")
def rig(main):
    return Rig(*main, entry="mix_amute")


def heard(rig, word, mutes=0):
    """One mixer call. -> (the tracks the mixer is shown at volume 0, the analog voices whose level words are 0)."""
    block, level2 = M.make_block([44, 1, 2, 3, 44, 5, 6, 7, 8, 9, 10, 11], [0] * 12, seed=6)
    assert 0 not in M.vols(block)
    quiet = M.muted_tracks(rig, block, level2, mutes=mutes, pattern=word)
    voices = M.shut_voices(rig, mutes=mutes, pattern=word)
    assert rig.stored == silenced(word)
    return quiet, voices


def test_with_no_solo_nothing_is_silenced(rig):
    assert heard(rig, 0) == ([], [])
    assert heard(rig, 0x1000) == ([], [])                                    # the FX track's mute alone


@pytest.mark.parametrize("track", range(TRACKS))
def test_one_solo_silences_the_other_eleven(rig, track):
    others = [t for t in range(TRACKS) if t != track]
    analog = [v for v in range(4) if v + 8 != track]                         # tracks 9..12: their level words, left and right
    assert heard(rig, 1 << track) == (others, analog)
    assert heard(rig, 1 << track | 0x1000) == (others, analog)               # with the FX track muted too
    assert heard(rig, 1 << track, mutes=1 << track) == (list(range(TRACKS)), [0, 1, 2, 3])       # a global mute beats the solo
    assert heard(rig, 1 << track, mutes=1 << others[0]) == (others, analog)  # and one on a silenced track changes nothing


@pytest.mark.parametrize("word, mutes", [(0b0000_0000_0101, 0), (0b1010_0000_0000, 0), (0b0001_1000_0001, 0), (0x0a5a, 0), (ALL, 0),
                                         (0b0011_0000_0011, 0b0001_0000_0001), (0x0555, 0x0aaa), (0x1001, 0x1000), (ALL, 0b0100_0000_0100)])
def test_several_solos_and_global_mutes_mixed_in(rig, word, mutes):
    quiet = [t for t in range(TRACKS) if (silenced(word) | mutes) >> t & 1]
    assert quiet == [t for t in range(TRACKS) if not word >> t & 1 or mutes >> t & 1]            # exactly the tracks not soloed, and the muted
    assert heard(rig, word, mutes) == (quiet, [t - 8 for t in quiet if t >= 8])


# ---- the keys ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("word", [0, 1, 0b100, 0x0800, 0x0a5a, ALL, ALL & ~1, 0x1000, 0x1004, 0x1fff, 0xe000, 0xf0f0, 0xffff])
def test_a_key_is_dark_for_a_track_a_solo_silences(now, was, word, main):
    """Our answer next to stock's own routine, asked of a pattern that holds what the solos silence. Thirteen tracks:
    for the FX track's number the answer is its own bit, as it was."""
    syms = main[1]
    for track in range(TRACKS + 1):
        want = silenced(word) >> track & 1
        assert now.mc.call(mm.PATTERN_MUTED, now.pattern(word), track) & 0xff == word >> track & 1       # stock's routine is in the image as it was
        stock_says = now.mc.call(mm.PATTERN_MUTED, now.pattern(silenced(word)), track) & 0xff
        now.marks()
        assert now.mc.call(syms["solo_key"], now.pattern(word), track) == want == stock_says
        assert now.kept(but=(1,)) and now.mc.reg(15) == STACK - 8             # d1 and a0 alone, as stock's routine uses them
        assert now.mc.call(mm.SCREEN_PATTERN_JUMP, now.pattern(word), track) == want                     # the draw's question, by its jump
        assert was.mc.call(mm.SCREEN_PATTERN_JUMP, was.pattern(word), track) & 0xff == word >> track & 1
    for track in range(TRACKS):
        heard = not silenced(word) >> track & 1
        # the routine that colours the keys, from its call for a pattern and from a song row's word, to the colour
        assert now.colour(mm.KEY_PATTERN_CALL - 4, now.pattern(word), track) == (LIT if heard else DARK)
        assert now.colour(mm.KEY_ROW_BIT - 2, 0x5a5a0000 | word, track) == (LIT if heard else DARK)
        assert now.colour(mm.KEY_ROW_BIT - 2, word, track, flag=1) == (LIT_FLAG if heard else DARK)
        # and stock's, the image before, given what the solos silence: the same key
        assert was.colour(mm.KEY_PATTERN_CALL - 4, was.pattern(silenced(word)), track) == (LIT if heard else DARK)
        assert was.colour(mm.KEY_ROW_BIT - 2, silenced(word), track) == (LIT if heard else DARK)
        assert was.colour(mm.KEY_PATTERN_CALL - 4, was.pattern(word), track) == (DARK if word >> track & 1 else LIT)      # what it was: a mute


def test_a_pattern_with_no_settings_has_every_key_lit_as_stocks_routine_has_it(now, main):
    for track in range(TRACKS + 1):
        assert now.mc.call(mm.PATTERN_MUTED, now.pattern(0x0a5a, data=False), track) & 0xff == 0
        assert now.mc.call(main[1]["solo_key"], now.pattern(0x0a5a, data=False), track) == 0
    for track in range(TRACKS):
        assert now.colour(mm.KEY_PATTERN_CALL - 4, now.pattern(0x0a5a, data=False), track) == LIT


def test_a_key_press_still_reads_the_patterns_own_bit(stock3, main):
    """The two places a press turns a bit over (a track key, the FX key) call stock's routine as they did."""
    image = main[0]
    for at in (0x40037336, 0x4003ceaa):
        assert image[mm.off(at):mm.off(at) + 6] == stock3[mm.off(at):mm.off(at) + 6] == b"\x4e\xb9" + mm.PATTERN_MUTED.to_bytes(4, "big")
    lo, hi = mm.off(mm.PATTERN_MUTED), mm.off(mm.PATTERN_MUTED) + 58
    assert image[lo:hi] == stock3[lo:hi] and stock3[hi - 2:hi] == b"\x4e\x75"


# ---- the program -------------------------------------------------------------------------------------------------------------

SITES = {"solo_set": (mm.PATTERN_MUTES_SET, 6), "solo_set_midi": (mm.MIDI_MUTES_SET, 6), "solo_msg": (mm.PATTERN_MUTES_MSG, 6),
         "solo_msg_midi": (mm.MIDI_MUTES_MSG, 6), "solo_key_row": (mm.KEY_ROW_BIT, 6)}
OPERANDS = (mm.KEY_PATTERN_CALL + 2, mm.SCREEN_PATTERN_JUMP + 2)             # both: the long after the opcode, to solo_key


def test_the_main_program_is_the_stops_images_but_for_seven_places_and_the_run(main, before, stock3, official):
    (image, syms), (old, old_syms) = main, before
    spans = [mm.CAVE_SOLO] + [(a, a + n) for a, n in SITES.values()] + [(a, a + 4) for a in OPERANDS]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != old[k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff), [hex(d) for d in diff if not any(a <= d < b for a, b in spans)][:8]
    assert all(syms[s] == v for s, v in old_syms.items()) and set(syms) - set(old_syms) == set(SITES) | {"solo_key", "solo_word"}
    for name, (at, n) in SITES.items():
        op = b"\x4e\xf9" if name.startswith("solo_set") else b"\x4e\xb9"     # the two routines: a jump. The rest: a call
        assert image[mm.off(at):mm.off(at) + n] == op + syms[name].to_bytes(4, "big")
    for at in OPERANDS:
        assert mm.u32(image, at) == syms["solo_key"] and mm.u32(old, at) == mm.PATTERN_MUTED
        assert image[mm.off(at) - 2:mm.off(at)] == old[mm.off(at) - 2:mm.off(at)]
    # the run: nothing reaches it, it begins after a return and ends on one, and no other run of ours is there
    lo, hi = mm.CAVE_SOLO
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert (lo, hi) in deadcode.usable(runs, 64) and hi - lo == 166
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" == stock3[mm.off(hi) - 2:mm.off(hi)]
    ours = [v for k, v in vars(mm).items() if k.startswith("CAVE") and isinstance(v, tuple) and v != mm.CAVE_SOLO]
    assert not any(lo < b and a < hi for a, b in ours) and all(lo <= syms[s] < hi for s in set(syms) - set(old_syms))
    # 94 bytes of it are ours, the rest is nothing: 72 bytes left
    code = image[mm.off(lo):mm.off(hi)]
    assert len(code.rstrip(b"\x4e\x71")) == 94 and code[94:] == b"\x4e\x71" * 36
    # the readers of both copies are stock's and ours as they were
    for at in (mm.MUTE_TEST, 0x400a3d6a, 0x400a4250, 0x4010de7e, 0x4010deb2):
        assert image[mm.off(at):mm.off(at) + 6] == stock3[mm.off(at):mm.off(at) + 6]
    for lo, hi in (mm.CAVE, mm.CAVE_AMUTE):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]


def test_the_routines_are_what_the_source_says(main, tmp_path):
    image, syms = main
    path = tmp_path / "main.bin"
    path.write_bytes(image)
    at = syms["solo_set"]
    text = disasm.disasm(str(path), mm.BASE, at, at + 94)
    ops = [line.split("\t")[-1].strip() for line in text.strip().splitlines()]
    word, key, tail, end = syms["solo_word"], syms["solo_key"], syms["solo_key"] + 32, syms["solo_key"] + 38
    assert (syms["solo_msg"], syms["solo_set_midi"], syms["solo_msg_midi"], word, key, syms["solo_key_row"]) == (at + 4, at + 16, at + 20, at + 32, at + 48, at + 88)
    assert ops == ["lea %sp@(6),%a0", "mvzw %a0@,%d0", "bsrs %#x" % word, "movew %%d0,%#x" % mm.PATTERN_MUTES, "rts",
                   "lea %sp@(6),%a0", "mvzw %a0@,%d0", "bsrs %#x" % word, "movew %%d0,%#x" % mm.MIDI_PATTERN_MUTES, "rts",
                   "lsll #4,%d0", "tstw %d0", "beqs %#x" % (word + 12), "eoril #65520,%d0", "lsrl #4,%d0", "rts",
                   "moveal %sp@(4),%a0", "movel %a0,%sp@-", "moveal %a0@,%a0", "moveal %a0@(40),%a0", "jsr %a0@", "addql #4,%sp",
                   "tstl %d0", "beqs %#x" % end, "moveal %d0,%a0", "mvzw %a0@(16),%d0", "bsrs %#x" % word, "movel %sp@(8),%d1",
                   "lsrl %d1,%d0", "moveq #1,%d1", "andl %d1,%d0", "rts",
                   "bsrs %#x" % word, "movel %d2,%d1", "bras %#x" % tail]


ROUTINES = [(0x400a30a6, 0x400a30ca), (0x4010d4a8, 0x4010d4d0),             # the two routines and their neighbours
            (0x400a38ce, 0x400a4e30), (0x4010dbf8, 0x4010e932),             # the per-block routine and the MIDI engine's loop
            (mm.SCREEN_MUTED, mm.SCREEN_PATTERN_JUMP + 6), (mm.KEY_COLOURS, 0x40037852)]


def test_nothing_else_in_the_program_goes_into_a_changed_place(stock3):
    """No address in the program, and no branch of the routines around them, points inside one. The two routines' own
    first addresses are the ones their callers name."""
    inside = [a for at, n in list(SITES.values()) + [(mm.KEY_PATTERN_CALL, 6), (mm.SCREEN_PATTERN_JUMP, 6)] for a in range(at + 1, at + n)]
    inside += list(range(mm.PATTERN_MUTES_SET + 6, mm.PATTERN_MUTES_SET + 12)) + list(range(mm.MIDI_MUTES_SET + 6, mm.MIDI_MUTES_SET + 12))
    for a in inside:
        assert a.to_bytes(4, "big") not in stock3, hex(a)
    seen = 0
    for lo, hi in ROUTINES:
        for at, raw, text in boundaries(stock3[mm.off(lo):mm.off(hi)], lo):
            for target in re.findall(r"0x(4[0-9a-f]{7})\b", text):
                seen += 1
                assert int(target, 16) not in inside, hex(at)
    assert seen > 500                                                        # the listing does name its branches' targets
    assert stock3.count(mm.PATTERN_MUTES_SET.to_bytes(4, "big")) == 3 == stock3.count(mm.MIDI_MUTES_SET.to_bytes(4, "big"))


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, solo=True)
    was = build.build(official_path, log=quiet, stops=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the stops image's byte for byte
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
