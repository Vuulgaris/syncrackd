"""The gear image: the srr image with the sampling page's knobs, and SMPL, turning as stock's own knobs do.

On request
. Until here every tick of a turn moved a knob of ours
a whole step. Now a turn goes through stock's three knob routines, as a stock page of whole numbers sends one
(0x40049730): the steps (times a coarse number while the knob is pushed in), whether it is pushed in, and the change
by a feel, counted in the page object's + 148; and the knob moves by the change's whole part, towards nought.

Held here: which routine a turn of each knob goes through, with what, and that the knob moves by what comes back and
by nothing else; that the crossfade's knob is as it was; SMPL's stops by the sample picker's feel; REC and SRC read
and written as the track's own word in the kit (the srr image's page, not run in emulation until here); and that the
main program differs from the srr image's only in the page's runs, the audio CPU's not at all.

Not held: what the change routine gives back for a turn. It is stock's, and its feels are built at a start by code
that does not run here: it is played by the test. How a knob feels is for the unit.
"""
import hashlib
import shutil

import pytest

import test_apage as A
import test_stops as S
from test_gain import GAIN_KNOB
from test_pack import DEST_KNOB
from test_page import EVENT, PAGE
from test_reclock import REC_KNOB, SRC_KNOB
from test_soloknob import SOLO_KNOB
from test_xfade import XF_KNOB
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

KIT = 0x7f000000
STATE = PAGE + mm.SYN_SIZE              # ours, after the page object: a mark, then a DEST a track
SIG = mm.SRR_SIG


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=9)


def geared(r, answers=None):
    """Stock's change routine played: -> the list its calls go into. Each call takes the next answer, or 0. And a
    kit where stock keeps its address, every track's word on slot 24 not signed yet."""
    for base in (mm.KIT_POINTER & ~0xfff, KIT):
        try:
            r.mc.map(base, 0x1000)
        except Exception:
            pass
    r.mc.write(KIT, bytes(0x1000))
    r.mc.w32(mm.KIT_POINTER, KIT)
    calls, left = [], list(answers or [])

    def change(obj, knob, steps, feel, pushed):
        calls.append((obj, knob, steps - (1 << 32) if steps >> 31 else steps, feel, pushed))
        return left.pop(0) if left else 0

    r.stub(mm.KNOB_CHANGE, change)
    r.mc.uc.ctl_flush_tb()
    r.answers = left
    return calls


def twist(r, knob, steps, pushed=False):
    if "pushed" in r.twist.__code__.co_varnames:                # a rig that writes the event's byte itself
        return r.twist(knob, steps, pushed=pushed)
    r.mc.write(EVENT + 20, bytes([pushed]))
    return r.twist(knob, steps)


def own(r, track):
    return int.from_bytes(r.mc.read(KIT + mm.KIT_TRACK * track + mm.KIT_WORDS + 2 * mm.REC_SLOT, 2), "big")


@pytest.mark.parametrize("knob", [SRC_KNOB, DEST_KNOB, REC_KNOB, 4, SOLO_KNOB, GAIN_KNOB])
def test_a_turn_of_the_pages_knobs_goes_through_stocks_change_by_the_plain_feel(main, knob):
    r = A.page(main, 2)
    calls = geared(r)
    feel = mm.FEEL_PICKER if knob in (SRC_KNOB, REC_KNOB) else mm.FEEL_PLAIN      # the second build: SRC and REC by the picker's
    assert twist(r, knob, 5) == 1 and twist(r, knob, -3) == 1
    assert calls == [(PAGE + mm.TURN_STATE, knob - 1, 5, feel, 0), (PAGE + mm.TURN_STATE, knob - 1, -3, feel, 0)]
    del calls[:]
    assert twist(r, knob, 5, pushed=True) == 1 and twist(r, knob, -1, pushed=True) == 1      # pushed in: four times the steps
    assert calls == [(PAGE + mm.TURN_STATE, knob - 1, 20, feel, 1), (PAGE + mm.TURN_STATE, knob - 1, -4, feel, 1)]


def test_a_knob_moves_by_the_changes_whole_part_and_by_nothing_else(main):
    """DEST and the gain: numbers. Ticks that stock's routine is still counting move nothing."""
    track = 3
    r = A.page(main, track)
    geared(r, [0, 255, 256, 3 * 256 + 200, -255, -2 * 256 - 1, 0, 100 * 256])
    seen = []
    for steps in (1, 1, 1, 9, -1, -9, -40, 1):
        twist(r, DEST_KNOB, steps)
        seen.append(r.mc.read(STATE + 4 + track, 1)[0])
    assert seen == [0, 0, 1, 4, 4, 2, 2, 64]                    # and it stops at the last place
    geared(r, [256, 0, 5 * 256, -256, 40 * 256])
    gains = []
    for steps in (1, 30, 1, -1, 1):
        twist(r, GAIN_KNOB, steps)
        gains.append(r.mc.read(mm.REC_GAINS + track, 1)[0])
    assert gains == [1, 1, 6, 5, 24]


def test_the_solo_is_switched_by_a_change_that_is_a_whole_step(main):
    for track in (1, 9):                                        # a sampler's page, and an analog track's
        r = A.page(main, track)
        calls = geared(r, [0, 200, 256, 0, -100, -256])
        got = []
        for steps in (1, 3, 1, -1, -1, -1):
            twist(r, SOLO_KNOB, steps)
            got.append(int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") >> track & 1)
        assert got == [0, 0, 1, 1, 1, 0] and len(calls) == 6 and all(c[1] == SOLO_KNOB - 1 and c[3] == mm.FEEL_PLAIN for c in calls)


@pytest.mark.parametrize("track", [2, 10])
def test_the_crossfades_knob_is_as_it_was(main, track):
    r = A.page(main, track)
    calls = geared(r, [7 * 256])
    for steps, want in ((1, 1), (8, 9), (-2, 7), (300, 127), (-1, 126)):
        assert twist(r, XF_KNOB, steps) == 1 and A.xf12(r)[track] == want
    assert not calls and r.answers == [7 * 256]                 # a tick a step, and stock's routine is not asked


def test_rec_and_src_are_the_tracks_own_word_in_the_kit(main):
    """The srr image's page: REC and SRC read and written where the sound engine's side reads the kit."""
    track = 5
    r = A.page(main, track)
    geared(r, [256, 3 * 256, 0, -256, 40 * 256, -256])
    assert own(r, track) == 0                                   # not signed: the page reads REC off and the main mix
    texts = [t[2] for t in r.show()]
    assert "OFF" in texts and "MAIN" in texts
    twist(r, REC_KNOB, 1)
    assert own(r, track) == SIG | 1 and "ON" in [t[2] for t in r.show()]
    twist(r, SRC_KNOB, 9)
    assert own(r, track) == SIG | 3 << 8 | 1                    # the fourth source, REC kept
    twist(r, SRC_KNOB, 1)                                       # ticks still being counted: nothing
    assert own(r, track) == SIG | 3 << 8 | 1
    twist(r, REC_KNOB, -1)
    assert own(r, track) == SIG | 3 << 8
    twist(r, SRC_KNOB, 99)
    assert own(r, track) == SIG | 15 << 8                       # and it stops at the last source
    twist(r, SRC_KNOB, -1)
    assert own(r, track) == SIG | 14 << 8
    assert all(own(r, t) == 0 for t in range(8) if t != track)


def test_smpl_stops_by_the_sample_pickers_feel(main):
    frames = S.LAYOUTS["the two stacks touching"][0]
    numbers = S.stops_of(frames)
    r = S.StopsPage(main, frames, smpl=S.knob_of(3))
    calls = geared(r, [0, 256, 2 * 256, -256, 255, -3 * 256])
    value = S.knob_of(3)
    for steps, moved in ((1, 0), (1, 1), (1, 2), (-1, -1), (5, 0), (-1, -3)):
        value = S.travelled(numbers, value, moved) if moved else value
        assert r.turn_smpl(steps) == value
    assert [c[:2] + c[3:] for c in calls] == [(PAGE + mm.TURN_STATE, S.SMPL_KNOB - 1, mm.FEEL_PICKER, 0)] * 6
    assert [c[2] for c in calls] == [1, 1, 1, -1, 5, -1]
    del calls[:]
    r.turn_smpl(1, pushed=True)                                 # pushed in: eight times the steps, as stock's picker
    assert calls == [(PAGE + mm.TURN_STATE, S.SMPL_KNOB - 1, 8, mm.FEEL_PICKER, 1)]


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=9)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=8)
    assert hashlib.sha256(was_raw).hexdigest().startswith("69f0fd04")      # the srr image's second build, as it is
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and len(new) == len(old)
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10]
    stray = [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 24, [hex(a) for a in stray[:24]]       # operands that name a routine of the page's that moved
    assert built.section(7) == was.section(7)                   # the audio CPU's program is the srr image's
    for name in ("KNOB_STEPS", "KNOB_PUSHED", "KNOB_CHANGE"):   # stock's three routines are stock's
        at = mm.off(getattr(mm, name))
        assert new[at:at + 32] == official.section(3)[at:at + 32]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
