"""The soloknob image: the purple keys are stock's pattern mutes again, and a solo is on the sampling page's knob E.






What runs here, from the built image: the page's drawing and its knobs (tests/test_once.py's rig), and our mixer link
and analog mute around a stand-in for the mixer (tests/test_mainpatch.py's rig), next to the once image's.
Nothing of stock's is changed by this image that the once image did not change, and seven places it changed are
stock's again: that is tested against the official section.
"""
import shutil

import numpy as np
import pytest

import test_mainpatch as M
import test_once as O
import test_solo as S
from test_reclock import REC_KNOB, SRC_KNOB
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SOLO_KNOB = 5                                   # knob E, as a turn names it
FIFTH = (33, 12)                                # where the fifth place's value goes; its name, at (33, 0), is empty
TRACKS, SAMPLER = 12, 44
ALL = 0x0fff


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, soloknob=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, once=True)


# ---- the knob --------------------------------------------------------------------------------------------------

class Page(O.OncePage):
    def __init__(self, built, word=0, **kw):
        self.solo_writes = []
        super().__init__(built, **kw)
        self.mc.write(mm.SOLO_WORD, word.to_bytes(4, "big"))

    def wrote(self, uc, access, address, size, value, user):
        if mm.SOLO_WORD <= address < mm.SOLO_WORD + 4:
            self.solo_writes.append((address, size))
        else:
            super().wrote(uc, access, address, size, value, user)

    @property
    def solos(self):
        return int.from_bytes(self.mc.read(mm.SOLO_WORD, 4), "big")

    def fifth(self):
        got = self.show()
        return [t[2] for t in got if t[0] == 33 and t[1] in (0, 12)]


@pytest.mark.parametrize("track", [0, 3, 7])
def test_knob_e_is_the_tracks_solo_and_the_place_says_which(main, track):
    r = Page(main, track=track)
    assert r.fifth() == ["", "S OFF"] and r.solos == 0
    assert r.twist(SOLO_KNOB, 1) == 1
    assert r.solos == 1 << track and r.fifth() == ["", "SOLO"]
    r.twist(SOLO_KNOB, 4)                                          # on is on
    assert r.solos == 1 << track
    r.twist(SOLO_KNOB, -1)
    assert r.solos == 0 and r.fifth() == ["", "S OFF"]
    r.twist(SOLO_KNOB, -3)
    assert r.solos == 0
    # nothing of the unit's is touched: no lock, no change of MODE, no pop-up, and the page is drawn again
    assert not r.locks and not r.locked and not r.changes and not r.popped and not r.rec_locks and not r.stray
    assert not r.table_writes and not r.once_writes and r.redrawn


def test_several_tracks_each_its_own_bit(main):
    r = Page(main, track=2, word=0b1000_0001)                      # tracks 1 and 8 are soloed already
    assert r.fifth() == ["", "S OFF"]
    r.twist(SOLO_KNOB, 1)
    assert r.solos == 0b1000_0101 and r.fifth() == ["", "SOLO"]
    r = Page(main, track=7, word=0b1000_0101)
    assert r.fifth() == ["", "SOLO"]
    r.twist(SOLO_KNOB, -1)
    assert r.solos == 0b0000_0101
    r = Page(main, track=0, word=0b0000_0101)
    r.twist(SOLO_KNOB, 0)                                           # a turn of nothing
    assert r.solos == 0b0000_0101 and not r.solo_writes


def scene(built, cls, mode, held, turns):
    r = cls(built, mode=mode)
    r.hold(*held)
    out = []
    for knob, steps in turns:
        r.twist(knob, steps)
        out.append(([t for t in r.show() if t[:2] not in ((33, 0), FIFTH)], r.mode, tuple(r.changes), dict(r.rec_locks), tuple(r.popped),
                    tuple(r.locked), r.gains, r.dest, r.box, r.arm))
    return out


@pytest.mark.parametrize("mode", [0, O.REC, O.STEREO | 5 << 2])
@pytest.mark.parametrize("held", [(), (5, 9)])
def test_the_rest_of_the_page_is_the_once_images(main, before, mode, held):
    turns = [(SRC_KNOB, 2), (O.DEST_KNOB, 3), (O.BANK_KNOB, 1), (O.GAIN_KNOB, 5), (O.TAKE_KNOB, 1), (O.TAKE_KNOB, -1),
             (REC_KNOB, 1), (REC_KNOB, 1), (REC_KNOB, -1), (REC_KNOB, -2), (REC_KNOB, 3)]
    assert scene(main, Page, mode, held, turns) == scene(before, O.OncePage, mode, held, turns)


def test_on_the_once_image_the_place_is_empty_and_the_knob_turns_nothing(before):
    r = Page(before, word=0x55)
    assert r.fifth() == [] and r.twist(SOLO_KNOB, 1) == 1 and r.solos == 0x55 and not r.solo_writes


# ---- what is silenced: our mixer link and analog mute ---------------------------------------------------------------

class Rig(M.Rig):
    """test_mainpatch's rig with the knob's long beside stock's words."""

    def run(self, block, level2, mutes=0, solos=0, pattern=0, knob=0):
        self.mc.write(mm.SOLO_WORD, knob.to_bytes(4, "big"))
        out = super().run(block, level2, mutes, solos, pattern)
        self.left = int.from_bytes(self.mc.read(mm.SOLO_WORD, 4), "big")
        return out


@pytest.fixture(scope="module")
def rig(main):
    return Rig(*main, entry="mix_amute")


@pytest.fixture(scope="module")
def old(before):
    return Rig(*before, entry="mix_amute")


MACHINES = [SAMPLER] * 8 + [8, 9, 10, 11]


def heard(rig, machines=MACHINES, **state):
    """One mixer call. -> (the tracks the mixer is shown at volume 0, the analog voices whose two level words are 0).
    Nothing else of the block the mixer is given, of the level words or of the control block moves: the FX track's
    part of each among them."""
    block, level2 = M.make_block(machines, [0] * 12, seed=6)
    assert 0 not in M.vols(block)
    quiet = M.muted_tracks(rig, block, level2, **state)
    was = np.random.default_rng(12).integers(1, 256, M.CONTROL_BYTES, dtype=np.uint8).tobytes()
    rig.mc.write(mm.CONTROL, was)
    ret, after, level2_after = rig.run(block, level2, **state)
    assert ret == 0x8000DBD0 and after == block and level2_after == level2
    got = rig.mc.read(mm.CONTROL, M.CONTROL_BYTES)
    assert rig.seen["control"] == got                              # done before the mixer runs
    voices = [v for v in range(4) if got[2 * v:2 * v + 2] == b"\0\0"]
    want = bytearray(was)
    for v in voices:
        want[2 * v:2 * v + 2] = want[10 + 2 * v:12 + 2 * v] = b"\0\0"
    assert got == bytes(want)
    return quiet, voices


def test_with_no_solo_it_is_the_mutes_as_on_the_once_image(rig, old):
    rng = np.random.default_rng(3)
    assert heard(rig) == ([], []) and rig.left == 0
    for _ in range(24):
        mutes, pattern = int(rng.integers(0, 0x2000)), int(rng.integers(0, 0x2000))
        want = [t for t in range(TRACKS) if (mutes | pattern) >> t & 1]
        assert heard(rig, mutes=mutes, pattern=pattern) == heard(old, mutes=mutes, pattern=pattern) == (want, [t - 8 for t in want if t >= 8])


@pytest.mark.parametrize("track", range(8))
def test_one_solo_silences_the_other_eleven(rig, track):
    others = [t for t in range(TRACKS) if t != track]
    assert heard(rig, knob=1 << track) == (others, [0, 1, 2, 3]) and rig.left == 1 << track
    # a soloed track is heard when it is green-muted, and when it is purple-muted; a mute on a silenced track changes nothing
    assert heard(rig, knob=1 << track, mutes=1 << track) == (others, [0, 1, 2, 3])
    assert heard(rig, knob=1 << track, pattern=1 << track) == (others, [0, 1, 2, 3])
    assert heard(rig, knob=1 << track, mutes=ALL, pattern=ALL) == (others, [0, 1, 2, 3])
    # the FX track's bit in either word of mutes is nothing to it
    assert heard(rig, knob=1 << track, mutes=0x1000, pattern=0x1000) == (others, [0, 1, 2, 3])


@pytest.mark.parametrize("knob", [0b0000_0101, 0b1000_0001, 0b0111_1110, 0xff, 0b0001_1000])
@pytest.mark.parametrize("mutes, pattern", [(0, 0), (0x0a5a, 0x0005), (0x1fff, 0x1fff)])
def test_several_solos_whatever_is_muted(rig, knob, mutes, pattern):
    quiet = [t for t in range(TRACKS) if not knob >> t & 1]        # exactly the tracks not soloed, the analog four among them
    assert heard(rig, knob=knob, mutes=mutes, pattern=pattern) == (quiet, [0, 1, 2, 3]) and rig.left == knob


def test_stocks_own_solo_word_is_not_followed_any_more(rig, old):
    assert heard(old, solos=0b0100) == ([t for t in range(TRACKS) if t != 2], [0, 1, 2, 3])     # the once image: stock's rule
    assert heard(rig, solos=0b0100) == ([], [])
    assert heard(rig, solos=0b0100, mutes=0b0010_0000_0001) == ([0, 9], [1])
    assert heard(rig, solos=0b0100, knob=0b1000) == ([t for t in range(TRACKS) if t != 3], [0, 1, 2, 3])


def test_a_track_that_is_no_sampler_any_more_has_no_solo(rig):
    """Its page is gone and with it the knob: the bit is cleared where the mixer link looks, a block later for the analog
    voices, which are looked at first."""
    machines = [SAMPLER, 3, SAMPLER] + [SAMPLER] * 5 + [8, 9, 10, 11]
    block, level2 = M.make_block(machines, [0] * 12, seed=6)
    assert M.muted_tracks(rig, block, level2, knob=0b0010) == [] and rig.left == 0
    assert heard(rig, machines) == ([], [])
    assert M.muted_tracks(rig, block, level2, knob=0b0110) == [t for t in range(TRACKS) if t != 2] and rig.left == 0b0100
    # bits past the eight digital tracks are never set by the page; one found there is dropped
    assert M.muted_tracks(rig, block, level2, knob=0x0300) == [] and rig.left == 0


def test_the_long_is_read_and_only_written_when_a_bit_has_to_go(rig):
    writes = []
    block, level2 = M.make_block(MACHINES, [0] * 12, seed=6)
    from unicorn import UC_HOOK_MEM_WRITE
    hook = rig.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, user: writes.append(address),
                              begin=mm.SOLO_WORD, end=mm.SOLO_WORD + 3)
    try:
        rig.mc.write(mm.SOLO_WORD, (0b101).to_bytes(4, "big"))
        rig.mc.call(rig.entry, 0x11111111, 0x22222222, M.PARAMS)
        assert not writes
    finally:
        rig.mc.uc.hook_del(hook)


# ---- the purple keys are stock's again -------------------------------------------------------------------------------

def test_the_solo_images_seven_places_hold_stocks_bytes(main, before, stock3):
    image, syms = main
    old, was = before
    places = [(a, n) for a, n in S.SITES.values()] + [(a, 4) for a in S.OPERANDS]
    assert len(places) == 7
    for a, n in places:
        assert image[mm.off(a):mm.off(a) + n] == stock3[mm.off(a):mm.off(a) + n] != old[mm.off(a):mm.off(a) + n], hex(a)
    # the two routines that store the copies of the pattern's word, whole, and the readers of both copies
    for a, n in ((mm.PATTERN_MUTES_SET, 12), (mm.MIDI_MUTES_SET, 12), (mm.PATTERN_MUTED, 0x3a), (mm.KEY_COLOURS, 0x180), (mm.MUTE_TEST, 6),
                 (0x400a3d6a, 6), (0x400a4250, 6), (0x4010de7e, 6), (0x4010deb2, 6)):
        assert image[mm.off(a):mm.off(a) + n] == stock3[mm.off(a):mm.off(a) + n]
    # none of the solo image's routines is in the image, and the run its code was in is stock's but for our long at its start
    assert not [n for n in syms if n.startswith("solo_")] and [n for n in was if n.startswith("solo_")]
    lo, hi = mm.CAVE_SOLO
    assert image[mm.off(lo):mm.off(lo) + 4] == bytes(4) and mm.SOLO_WORD == lo
    assert image[mm.off(lo) + 4:mm.off(hi)] == stock3[mm.off(lo) + 4:mm.off(hi)] != old[mm.off(lo) + 4:mm.off(hi)]


def test_the_pattern_word_goes_to_the_engines_as_it_is(main):
    """Stock's routine that stores the per-block routine's copy, run from the image: the word, not the tracks its solos silence."""
    mc = Rig(*main, entry="mix_amute").mc
    for word in (0, 1, 0x0005, 0x0a5a, 0x1000, 0x1fff):
        mc.write(mm.PATTERN_MUTES, b"\xa5\x5a")
        mc.call(mm.PATTERN_MUTES_SET, word)
        assert int.from_bytes(mc.read(mm.PATTERN_MUTES, 2), "big") == word


# ---- the image ---------------------------------------------------------------------------------------------------

RUNS = [mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_SOLO, mm.CAVE_PAGE]
MOVED = (mm.TRIG_MUTE + 2, mm.HOLD_WRITE + 2, mm.MIX_CALL + 2)      # the operands of three calls into the runs that were built again
POINTERS = O.POINTERS


def test_the_main_program_is_the_once_images_but_for_its_declared_places(main, before, stock3):
    image, syms = main
    old, was = before
    diff = [k for k in range(len(stock3)) if image[k] != old[k]]
    spans = (RUNS + [(a, a + n) for a, n in S.SITES.values()] + [(a, a + 4) for a in S.OPERANDS] + [(a, a + 4) for a in MOVED]
             + [(a, a + 4) for a in POINTERS] + [mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_REC, mm.CAVE_METER,
                                                 mm.CAVE_FEED])
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff), [hex(mm.BASE + k) for k in diff if not any(mm.off(s) <= k < mm.off(e) for s, e in spans)][:6]
    for s, e in RUNS:
        assert image[mm.off(s):mm.off(e)] != old[mm.off(s):mm.off(e)], hex(s)
    # the once image's own run and its three places, the keep code, the banks, the text and the right channel's: as they were
    for lo, hi in (mm.CAVE_ONCE, mm.CAVE_KEEP, mm.CAVE_BANK, mm.CAVE_RIGHT, mm.CAVE_HALVES, mm.CAVE_TEXT):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]
    for a, n in O.SITES:
        assert image[mm.off(a):mm.off(a) + n] == old[mm.off(a):mm.off(a) + n]
    # in the runs that hold other routines too, only operands that name a routine that moved differ: a few bytes each
    for lo, hi in (mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED):
        assert sum(image[k] != old[k] for k in range(mm.off(lo), mm.off(hi))) <= 16, hex(lo)
    # the routine in front of stock's trig test, and the one that puts REC's mark in the block: the once image's bytes
    for name, n in (("mute_trig", 34), ("rec_word", 40)):
        assert image[mm.off(syms[name]):mm.off(syms[name]) + n] == old[mm.off(was[name]):mm.off(was[name]) + n]


def test_every_pointer_names_the_routine_it_named(main, before):
    image, syms = main
    old, was = before
    for a in POINTERS + MOVED:
        names = [n for n, v in was.items() if v == int.from_bytes(old[mm.off(a):mm.off(a) + 4], "big")]
        assert names and int.from_bytes(image[mm.off(a):mm.off(a) + 4], "big") in [syms[n] for n in names], hex(a)


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, soloknob=True)
    was = build.build(official_path, log=quiet, once=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the once image's byte for byte, which is the stops image's
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
