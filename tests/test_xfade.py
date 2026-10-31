"""The xfade image: a crossfade on the sampling page's knob G, where MODE was.





What runs here, from the built image: the page's drawing and its knobs (tests/test_soloknob.py's rig), our mixer link
and analog mute around a stand-in for the mixer (tests/test_mainpatch.py's rig) next to the soloknob image's, the
mixer's own gain routine as it is, stock's loop that writes the hold flag with engine/recword.S in it (as
tests/test_save.py runs it), the feed (tests/test_feed.py's rig) and the audio CPU's engine for what a take is.
The routine that makes an analog voice's level words is read in the listing and not run.
"""
import shutil

import numpy as np
import pytest

import test_feed as F
import test_mainpatch as M
import test_once as O
import test_soloknob as K
from emu.machine import Machine
from test_meter import ALL, REC, STEREO, src
from test_pack import knob_of, takes
from test_recorder import frames, junk, make_block
from test_reclock import REC_KNOB, SRC_KNOB
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

XF_KNOB = 7                                     # knob G, as a turn names it
THIRD = (85, 12)                                # where the lower row's third value goes; its name, at (85, 0), is empty
TOP = mm.XFADE_TOP
TRACKS, SAMPLER = 12, 44
STRIDE, P_VOL, P_TYPE, P_MODE = M.STRIDE, M.P_VOL, M.P_TYPE, M.P_MODE
MACHINES = [SAMPLER] * 8 + [8, 9, 10, 11]
NONE = (0,) * 8


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, soloknob=True)


@pytest.fixture(scope="module")
def audio(official):
    return build_engine.patched_image(official.section(7), stops=True)


# ---- the knob --------------------------------------------------------------------------------------------------

class Page(K.Page):
    def __init__(self, built, xf=None, **kw):
        self.xf_writes = []
        super().__init__(built, **kw)
        if xf is not None:
            self.mc.write(mm.XFADES, bytes(xf))

    def wrote(self, uc, access, address, size, value, user):
        if mm.XFADES <= address < mm.XFADES + 8:
            self.xf_writes.append((address - mm.XFADES, size))
        else:
            super().wrote(uc, access, address, size, value, user)

    @property
    def xf(self):
        return list(self.mc.read(mm.XFADES, 8))

    def third(self):
        return [t[2] for t in self.show() if t[0] == THIRD[0] and t[1] in (0, THIRD[1])]


@pytest.mark.parametrize("track", [0, 3, 7])
def test_knob_g_is_the_tracks_crossfade_and_the_place_says_how_far(main, track):
    r = Page(main, track=track)
    assert r.third() == ["", "XF0"] and r.xf == [0] * 8
    for steps, want in ((1, 1), (8, 9), (1, 10), (89, 99), (1, 100), (26, 126), (1, 127), (1, 127), (40, 127), (-1, 126), (0, 126),
                        (-62, 64), (-63, 1), (-1, 0), (-1, 0), (-90, 0), (300, 127), (-300, 0)):
        assert r.twist(XF_KNOB, steps) == 1
        assert r.xf == [want if t == track else 0 for t in range(8)] and r.third() == ["", "XF%d" % want]
    # a byte of its own, and nothing of the unit's is touched: no lock, no change of MODE, no pop-up; the page is drawn again
    assert r.xf_writes and all(w == (track, 1) for w in r.xf_writes)
    assert not r.locks and not r.locked and not r.changes and not r.popped and not r.rec_locks and not r.stray
    assert not r.table_writes and not r.once_writes and not r.solo_writes and r.redrawn


def test_each_track_has_its_own(main):
    r = Page(main, track=2, xf=[5, 0, 0, 0, 0, 0, 0, 99])
    assert r.third() == ["", "XF0"]
    r.twist(XF_KNOB, 3)
    assert r.xf == [5, 0, 3, 0, 0, 0, 0, 99] and r.third() == ["", "XF3"]
    r = Page(main, track=7, xf=[5, 0, 3, 0, 0, 0, 0, 99])
    assert r.third() == ["", "XF99"]
    r.twist(XF_KNOB, -99)
    assert r.xf == [5, 0, 3, 0, 0, 0, 0, 0]


def scene(built, cls, mode, held, turns):
    r = cls(built, mode=mode)
    r.hold(*held)
    out = []
    for knob, steps in turns:
        r.twist(knob, steps)
        out.append(([t for t in r.show() if t[:2] not in ((THIRD[0], 0), THIRD)], r.mode, tuple(r.changes), dict(r.rec_locks), tuple(r.popped),
                    tuple(r.locked), r.gains, r.dest, r.box, r.arm, r.solos))
    return out


@pytest.mark.parametrize("mode", [0, O.REC, O.STEREO | 5 << 2, O.REC | O.STEREO | 9 << 2])
@pytest.mark.parametrize("held", [(), (5, 9)])
def test_the_rest_of_the_page_is_the_soloknob_images(main, before, mode, held):
    """A project the soloknob image saved, a track on MONO or on STEREO: every other place and every other knob, the
    peak in the last box among them, turn for turn. MODE as it is saved is not written by a drawing."""
    turns = [(SRC_KNOB, 2), (O.DEST_KNOB, 3), (O.BANK_KNOB, 1), (O.GAIN_KNOB, 5), (K.SOLO_KNOB, 1), (K.SOLO_KNOB, -1),
             (REC_KNOB, 1), (REC_KNOB, 1), (REC_KNOB, -1), (REC_KNOB, -2), (REC_KNOB, 3)]
    assert scene(main, Page, mode, held, turns) == scene(before, K.Page, mode, held, turns)


@pytest.mark.parametrize("mode", [0, O.STEREO, O.REC | 5 << 2])
def test_mode_has_no_knob_here_and_on_the_soloknob_image_the_bytes_are_not_written(main, before, mode):
    r = Page(main, mode=mode)
    for steps in (1, -1, 4, -9):
        r.twist(XF_KNOB, steps)
        assert r.mode == mode and not r.changes and not r.locked
    old = Page(before, mode=mode)
    assert old.third() == ["", "STER" if mode & O.STEREO else "MONO"]
    old.twist(XF_KNOB, -1 if mode & O.STEREO else 1)
    assert old.mode == mode ^ O.STEREO and not old.xf_writes


# ---- what is turned down: our mixer link and analog mute ------------------------------------------------------------

LEVELS = (0, 1, 2, 3, 5, 6, 7, 8)               # the control block's words that are an analog voice's: left of 1..4, right of 1..4


class Rig(K.Rig):
    """test_soloknob's rig with the eight crossfades beside the solos' long."""

    def run(self, block, level2, xf=None, **state):
        if xf is not None:
            self.mc.write(mm.XFADES, bytes(xf))
        out = super().run(block, level2, **state)
        self.xf_left = list(self.mc.read(mm.XFADES, 8))
        return out


@pytest.fixture(scope="module")
def rig(main):
    return Rig(*main, entry="mix_amute")


@pytest.fixture(scope="module")
def old(before):
    return Rig(*before, entry="mix_amute")


def mixed(rig, machines=MACHINES, seed=6, **state):
    """One mixer call. -> (the twelve volume words the mixer is shown, the analog voices' eight level words as they are
    sent, the twelve as the block has them, the eight as stock made them). Everything is put back, and nothing else of
    the block the mixer is given, of the level words or of the control block moves: the FX track's part of each and the
    external input's level words among them."""
    block, level2 = M.make_block(machines, [0] * 12, seed=seed)
    assert 0 not in M.vols(block)
    was = np.random.default_rng(seed + 6).integers(1, 256, M.CONTROL_BYTES, dtype=np.uint8).tobytes()
    rig.mc.write(mm.CONTROL, was)
    ret, after, level2_after = rig.run(block, level2, **state)
    assert ret == 0x8000DBD0 and after == block and level2_after == level2
    seen = bytearray(rig.seen["params"])
    shown = M.vols(seen)
    for t in range(TRACKS):
        seen[STRIDE * t + P_VOL:STRIDE * t + P_VOL + 2] = block[STRIDE * t + P_VOL:][:2]
    assert bytes(seen) == block and rig.seen["level2"] == level2
    got = bytes(rig.mc.read(mm.CONTROL, M.CONTROL_BYTES))
    assert rig.seen["control"] == got                              # done before the mixer runs
    words = lambda b: [int.from_bytes(b[2 * k:2 * k + 2], "big") for k in range(10)]
    assert got[20:] == was[20:] and words(got)[4] == words(was)[4] and words(got)[9] == words(was)[9]
    return shown, [words(got)[k] for k in LEVELS], M.vols(block), [words(was)[k] for k in LEVELS]


def others(xf, t):
    """What a track is turned down by: the largest of the other tracks' numbers."""
    return max(x for k, x in enumerate(xf) if k != t)


def law(vols, levels, xf, silent=()):
    """The rule, by itself: a volume word times (127 - x) / 127, a level word times the square of that, both rounded
    down; a track a mute or a solo silences is 0."""
    down = [others(xf, t) for t in range(TRACKS)]
    return ([0 if t in silent else v * (TOP - down[t]) // TOP for t, v in enumerate(vols)],
            [0 if 8 + k % 4 in silent else w * (TOP - down[8 + k % 4]) ** 2 // TOP ** 2 for k, w in enumerate(levels)])


def test_at_0_the_mixer_is_shown_what_the_soloknob_image_shows(rig, old):
    """Bit for bit: every word the mixer is given, the level words and the control block, whatever is muted or soloed."""
    rng = np.random.default_rng(3)
    shown, levels, vols, was = mixed(rig, xf=NONE)
    assert (shown, levels) == (vols, was) and rig.xf_left == [0] * 8
    for k in range(24):
        state = dict(mutes=int(rng.integers(0, 0x2000)), pattern=int(rng.integers(0, 0x2000)), knob=int(rng.integers(0, 0x100)) if k % 3 == 0 else 0)
        a = mixed(rig, seed=k, xf=NONE, **state)
        seen = dict(rig.seen)
        assert a == mixed(old, seed=k, **state) and seen == old.seen


@pytest.mark.parametrize("track", range(8))
def test_at_the_top_exactly_the_other_eleven_are_silent(rig, track):
    xf = [TOP if t == track else 0 for t in range(8)]
    shown, levels, vols, was = mixed(rig, xf=xf)
    assert shown == [vols[t] if t == track else 0 for t in range(TRACKS)] and levels == [0] * 8
    assert rig.xf_left == xf and rig.left == 0


@pytest.mark.parametrize("x", [1, 2, 32, 63, 64, 65, 100, 126])
@pytest.mark.parametrize("track", [0, 5, 7])
def test_in_between_the_others_follow_the_law_and_the_track_is_untouched(rig, track, x):
    xf = [x if t == track else 0 for t in range(8)]
    shown, levels, vols, was = mixed(rig, seed=x + track, xf=xf)
    assert (shown, levels) == law(vols, was, xf) and shown[track] == vols[track]
    assert all(0 < shown[t] < vols[t] for t in range(TRACKS) if t != track and vols[t] > TOP)
    assert all(a <= b for a, b in zip(levels, was)) and levels != was


@pytest.mark.parametrize("xf", [(64, 0, 0, 100, 0, 0, 0, 0), (100, 0, 0, 64, 0, 0, 0, 0), (50, 50, 0, 0, 0, 0, 0, 0), (1, 2, 3, 4, 5, 6, 7, 8),
                                (127, 0, 0, 0, 0, 0, 0, 127), (127, 127, 127, 127, 127, 127, 127, 127), (0, 0, 9, 0, 0, 127, 0, 0),
                                (0, 0, 0, 0, 0, 0, 77, 76), (90, 90, 90, 0, 0, 0, 0, 0)])
def test_several_tracks_up_each_goes_down_by_the_largest_of_the_others(rig, xf):
    shown, levels, vols, was = mixed(rig, seed=sum(xf), xf=xf)
    assert (shown, levels) == law(vols, was, xf) and rig.xf_left == list(xf)
    assert [others(xf, t) for t in range(8, TRACKS)] == [max(xf)] * 4       # an analog track has none of its own
    if xf == (64, 0, 0, 100, 0, 0, 0, 0):                           # track 1 by track 4's 100, track 4 by track 1's 64, the rest by 100
        assert shown[0] == vols[0] * 27 // 127 and shown[3] == vols[3] * 63 // 127 and shown[5] == vols[5] * 27 // 127
    if xf == (127, 0, 0, 0, 0, 0, 0, 127):                          # two at the top: everything is silent
        assert shown == [0] * TRACKS


@pytest.mark.parametrize("xf", [(80, 0, 0, 0, 0, 0, 0, 0), (0, 0, 127, 0, 0, 0, 0, 0), (30, 0, 0, 0, 0, 60, 0, 0)])
def test_a_mute_or_a_solo_silences_whatever_the_crossfade_says(rig, xf):
    for state in (dict(mutes=0b0010_0000_0101), dict(pattern=0b1000_0010_0001), dict(mutes=0x0a5a, pattern=0x0005), dict(mutes=0x1fff, pattern=0x1fff)):
        silent = [t for t in range(TRACKS) if (state.get("mutes", 0) | state.get("pattern", 0)) >> t & 1]
        shown, levels, vols, was = mixed(rig, xf=xf, **state)
        assert (shown, levels) == law(vols, was, xf, silent)
    for solo in (0b0000_0001, 0b0010_0000, 0b0000_1010, 0b0100_0100):
        silent = [t for t in range(TRACKS) if not solo >> t & 1]
        for state in (dict(), dict(mutes=solo), dict(pattern=0x1fff)):         # a soloed track is heard whatever is muted
            shown, levels, vols, was = mixed(rig, xf=xf, knob=solo, **state)
            assert (shown, levels) == law(vols, was, xf, silent) and rig.left == solo
    # a soloed track is not turned down by its own solo nor by its own crossfade: it is turned down by another track's
    shown, levels, vols, was = mixed(rig, xf=(0, 0, 90, 0, 0, 0, 0, 0), knob=0b0100)
    assert shown == [vols[2] if t == 2 else 0 for t in range(TRACKS)]
    shown, levels, vols, was = mixed(rig, xf=(0, 0, 90, 0, 0, 0, 0, 0), knob=0b0001)
    assert shown == [vols[0] * 37 // 127 if t == 0 else 0 for t in range(TRACKS)]


def test_a_track_that_is_no_sampler_any_more_has_no_crossfade(rig):
    """Its page is gone and with it the knob: the number is made 0 where the mixer link looks, a block later for the
    analog voices, which are looked at first."""
    machines = [SAMPLER, 3, SAMPLER] + [SAMPLER] * 5 + [8, 9, 10, 11]
    shown, levels, vols, was = mixed(rig, machines, xf=(0, 99, 0, 0, 0, 0, 0, 0))
    assert shown == vols and rig.xf_left == [0] * 8
    assert levels == law(vols, was, (0, 99, 0, 0, 0, 0, 0, 0))[1]              # this block the analog four went by it
    shown, levels, vols, was = mixed(rig, machines)                            # and the next they do not
    assert (shown, levels) == (vols, was)
    xf = (0, 99, 40, 0, 0, 0, 0, 0)
    shown, levels, vols, was = mixed(rig, machines, xf=xf)
    assert shown == law(vols, was, (0, 0, 40, 0, 0, 0, 0, 0))[0] and rig.xf_left == [0, 0, 40, 0, 0, 0, 0, 0]


def test_the_bytes_are_read_and_only_written_when_one_has_to_go(rig):
    from unicorn import UC_HOOK_MEM_WRITE
    writes = []
    block, level2 = M.make_block(MACHINES, [0] * 12, seed=6)
    hook = rig.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, user: writes.append(address),
                              begin=mm.SOLO_WORD, end=mm.XFADES + 7)
    try:
        for xf in (NONE, (0, 0, 0, 70, 0, 0, 0, 0), (127,) * 8):
            rig.run(block, level2, xf=xf)
            assert not writes
        rig.run(M.make_block([SAMPLER, 3] + MACHINES[2:], [0] * 12, seed=6)[0], level2, xf=(0, 5, 0, 0, 0, 0, 0, 0))
        assert writes == [mm.XFADES + 1]
    finally:
        rig.mc.uc.hook_del(hook)


def gain(rig, vol, level=127 << 8, level2=127 << 8, curve=0):
    rig.mc.emac.macsr = 0x20                                       # signed fractional, as the mixer runs
    g = rig.mc.call(mm.MIX_GAIN, level, level2, vol, curve)
    return (1 << 32) - g if g >> 31 else g                         # the mixer's gain is a negative fraction: its size


DB = {16: -2.3, 32: -5.0, 48: -8.1, 64: -12.0, 80: -17.2, 96: -24.4, 112: -37.1}      # how far down the others are, by the mixer's own gain


def test_the_law_through_the_mixers_own_gain_routine(rig):
    """A volume word times (127 - x) / 127 is the track's own VOL knob turned down in that proportion, and the mixer's
    gain goes by the square of the volume: it falls all the way, 12 dB down at the middle, and is nothing at the top."""
    for vol in (127 << 8, 100 << 8, 64 << 8):
        full = gain(rig, vol)
        gains = [gain(rig, vol * (TOP - x) // TOP) for x in range(TOP + 1)]
        bad = [(x, a, b) for x, (a, b) in enumerate(zip(gains, gains[1:])) if a < b]
        assert gains[0] == full and gains[TOP] == 0 and not bad, (vol >> 8, bad[:4])
        for x, db in DB.items():
            assert abs(20 * np.log10(gains[x] / full) - db) < 0.3, (x, 20 * np.log10(gains[x] / full))
            assert abs(gains[x] / full - ((TOP - x) / TOP) ** 2) < 0.002          # the square, as the analog voices' words are made


COST = {"none up": 88, "one up": 425, "all eight up": 484}        # instructions a block more than the soloknob image's two routines


@pytest.mark.parametrize("case, xf", [("none up", NONE), ("one up", (0, 0, 0, 64, 0, 0, 0, 0)), ("all eight up", (10, 20, 30, 40, 50, 60, 70, 80))])
def test_what_a_block_costs_more_on_the_main_cpu(rig, old, case, xf):
    """The per-block routine is an interrupt above the UI. Counted through the analog mute and the mixer link, the mixer
    a stand-in; engine/recword.S adds one instruction a sampler track on top, eight at most."""
    block, level2 = M.make_block(MACHINES, [0] * 12, seed=6)
    counts = []
    for r, kw in ((old, {}), (rig, dict(xf=xf))):
        was = r.mc.insns
        r.run(block, level2, **kw)
        counts.append(r.mc.insns - was)
    assert counts[1] - counts[0] == COST[case], counts


# ---- a take at a stereo place is stereo -------------------------------------------------------------------------------

def sent_after(image, block, locks=None):
    """Stock's loop that writes the hold flag (0x400a4c3e to 0x400a4c7a) run as it is, engine/recword.S in it, over a
    block of parameters as it is about to be sent. -> the block that is sent, the mixer's and the feed's and the audio
    CPU's."""
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x80000000, 0x10000)
    mc.write(mm.BASE, image)
    mc.set_stack(0x407ff000, 0x40000100)
    mc.set_exits([0x40000100, mm.HOLD_END])
    b = bytearray(block)
    for t in range(8):
        b[STRIDE * t + 128:STRIDE * t + 130] = b[STRIDE * t + 110:STRIDE * t + 112] = bytes(2)      # stock's flag: 0
    mc.write(mm.MACHINE_BYTES, bytes(block[STRIDE * t + P_TYPE] for t in range(8)))
    mc.write(mm.PARAM_WORDS, locks or bytes(STRIDE * 8))
    mc.write(mm.PARAM_SENT, bytes(b))
    mc.set_reg(10, mm.PARAM_SENT)                                   # a2: the block, as the mixer call is handed it
    mc.set_reg(15, 0x407ff000)
    mc.run(mm.HOLD_LOOP, mm.HOLD_END)
    return bytes(mc.read(mm.PARAM_SENT, len(b))), bytes(b)


@pytest.mark.parametrize("own", [0, STEREO, REC, REC | STEREO, REC | src(5), REC | STEREO | src(9)])
def test_mode_is_sent_as_stereo_on_a_sampler_track_and_left_on_any_other(main, before, own):
    machines = [SAMPLER, SAMPLER, 4, SAMPLER, 17, SAMPLER, SAMPLER, SAMPLER] + [8, 9, 10, 11]
    block = make_block(machines, [own] * 12, seed=own + 1)
    new, was = sent_after(main[0], block)
    old, _ = sent_after(before[0], block)
    for t in range(8):
        assert new[STRIDE * t + P_MODE] == (own | STEREO if machines[t] == SAMPLER else own) and old[STRIDE * t + P_MODE] == own
    # nothing else of the block is other than the soloknob image sends
    assert [k for k in range(len(new)) if new[k] != old[k]] == ([] if own & STEREO else [STRIDE * t + P_MODE for t in range(8) if machines[t] == SAMPLER])
    # a step's REC goes through as it did
    locks = bytearray(STRIDE * 8)
    locks[O.P_REC:O.P_REC + 2] = O.ON.to_bytes(2, "big")
    locks[STRIDE * 3 + O.P_REC:STRIDE * 3 + O.P_REC + 2] = O.ONCE.to_bytes(2, "big")
    new, _ = sent_after(main[0], block, bytes(locks))
    old, _ = sent_after(before[0], block, bytes(locks))
    assert [new[STRIDE * t + O.P_REC:][:2] for t in range(8)] == [old[STRIDE * t + O.P_REC:][:2] for t in range(8)]
    assert int.from_bytes(new[O.P_REC:][:2], "big") == O.ON and int.from_bytes(new[STRIDE * 3 + O.P_REC:][:2], "big") == O.ONCE


def mode_sent(image, own, track=4):
    block = make_block(ALL, [own] * 12, seed=3)
    return sent_after(image, block)[0][STRIDE * track + P_MODE]


@pytest.mark.parametrize("own", [REC, REC | STEREO, REC | src(7)])
@pytest.mark.parametrize("place", [3, 31])
def test_a_take_at_a_stereo_place_is_stereo_with_modes_bit_either_way(main, before, audio, place, own):
    """MODE as this image sends it, into the audio CPU's engine: both slots filled, as long as each other, the take a
    track on STEREO makes block for block. As the soloknob image sends a track on MONO: two frames in the second."""
    k = 2 * place
    now, _ = takes(audio, place, mode_sent(main[0], own))
    assert now == takes(audio, place, own | STEREO)[0]
    first, second = now[-1][0][k], now[-1][0][k + 1]
    assert first[0] == second[0] >= 64
    was = takes(audio, place, mode_sent(before[0], own))[0][-1][0]
    assert was[k] == first and was[k + 1][0] == (first[0] if own & STEREO else 2)


@pytest.mark.parametrize("own", [REC, REC | STEREO])
@pytest.mark.parametrize("place", [40, 63])
def test_a_take_at_a_single_slot_is_mono_as_it_was(main, before, audio, place, own):
    assert knob_of(place) == 64 + place
    now, _ = takes(audio, place, mode_sent(main[0], own))
    assert now == takes(audio, place, mode_sent(before[0], own))[0] == takes(audio, place, own)[0]
    table = now[-1][0]
    assert table[place][0] % 2 == 1 and table[place][0] > 32            # one slot, an odd length: a mono sample


@pytest.mark.parametrize("own, n, db", [(REC, 0, 0), (REC | src(1), 1, 12), (REC | src(14), 14, 0), (REC | STEREO | src(15), 15, 24)])
def test_the_feed_writes_a_stereo_take_whatever_modes_bit_says(main, before, own, n, db):
    """The block as the loop leaves it, into the feed: the two sides of the source, each its own. On the soloknob image
    a track on MONO is fed half of the one and half of the other on both."""
    for image, stereo in ((main, True), (before, bool(own & STEREO))):
        r = F.Feed(*image)
        r.reset(gains=[db] * 8)
        window, frame = junk(0x0105), frames(seed=30 + n)
        sent = sent_after(image[0], F.block_of(2, own))[0]
        ret, after = r.run(sent, frame, window)
        assert after == F.spec(window, frame, n, db, stereo)


# ---- the image ---------------------------------------------------------------------------------------------------

RUNS = [mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_PAGE, mm.CAVE_PAGE4, (mm.XFADES, mm.XFADES + 8)]
MOVED = K.MOVED
POINTERS = O.POINTERS


def test_the_main_program_is_the_soloknob_images_but_for_its_declared_places(main, before, stock3):
    image, syms = main
    old, was = before
    diff = [k for k in range(len(stock3)) if image[k] != old[k]]
    spans = (RUNS + [(a, a + 4) for a in MOVED] + [(a, a + 4) for a in POINTERS]
             + [mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_METER, mm.CAVE_FEED, mm.CAVE_ONCE])
    stray = [hex(mm.BASE + k) for k in diff if not any(mm.off(s) <= k < mm.off(e) for s, e in spans)]
    assert diff and not stray, stray[:6]
    for s, e in RUNS:
        assert image[mm.off(s):mm.off(e)] != old[mm.off(s):mm.off(e)], hex(s)
    # the eight bytes: 0 in the image, after the solos' long, in a run nothing reaches; the rest of that run is stock's
    lo, hi = mm.CAVE_SOLO
    assert mm.XFADES == mm.SOLO_WORD + 4 == lo + 4 and image[mm.off(lo):mm.off(lo) + 12] == bytes(12)
    assert image[mm.off(lo) + 12:mm.off(hi)] == stock3[mm.off(lo) + 12:mm.off(hi)] == old[mm.off(lo) + 12:mm.off(hi)]
    assert old[mm.off(lo) + 4:mm.off(lo) + 12] == stock3[mm.off(lo) + 4:mm.off(lo) + 12]
    assert not any(image.count((mm.XFADES + k).to_bytes(4, "big")) > (k % 4 == 0) * 6 for k in range(8))
    # the keep code, the banks, the text, the right channel's and the once image's three places: as they were
    for lo, hi in (mm.CAVE_KEEP, mm.CAVE_BANK, mm.CAVE_RIGHT, mm.CAVE_HALVES, mm.CAVE_TEXT):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]
    for a, n in O.SITES:
        assert image[mm.off(a):mm.off(a) + n] == old[mm.off(a):mm.off(a) + n]
    # in the runs that hold other routines only, nothing but operands that name a routine that moved: a few bytes each
    for lo, hi in (mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_METER, mm.CAVE_FEED, mm.CAVE_ONCE):
        assert sum(image[k] != old[k] for k in range(mm.off(lo), mm.off(hi))) <= 24, hex(lo)
    # the routine in front of stock's trig test: the soloknob image's bytes. The one that puts REC's mark in the block: six more
    assert image[mm.off(syms["mute_trig"]):mm.off(syms["mute_trig"]) + 34] == old[mm.off(was["mute_trig"]):mm.off(was["mute_trig"]) + 34]
    new, had = image[mm.off(syms["rec_word"]):][:46], old[mm.off(was["rec_word"]):][:40]
    assert new[:15] == had[:15] and new[15] == had[15] + 6 and new[16:22] == bytes.fromhex("08e80000004a") and new[22:46] == had[16:40]


def test_every_pointer_names_the_routine_it_named(main, before):
    image, syms = main
    old, was = before
    for a in POINTERS + MOVED:
        names = [n for n, v in was.items() if v == int.from_bytes(old[mm.off(a):mm.off(a) + 4], "big")]
        assert names and int.from_bytes(image[mm.off(a):mm.off(a) + 4], "big") in [syms[n] for n in names], hex(a)


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, xfade=True)
    was = build.build(official_path, log=quiet, soloknob=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the soloknob image's byte for byte, which is the stops image's
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
