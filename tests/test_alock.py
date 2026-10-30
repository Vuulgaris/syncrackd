"""The alock image: the slock image with an analog track's solo lockable to a step too.

On request,
and on 2026-10-13: "Start on the aog solo work".

An analog track's lock is on knob slot 26, the last of the ten words that are a track's machine (17 to 26): no analog
machine has a knob on it (theirs are 17 to 24, and 25 on one). The same two marks as a sampler track's on slot 17,
counted only on a track that holds an analog machine.

NOT SHOWN, and emulation cannot: that nothing of an analog voice reads that word. Only the unit can.
"""
import shutil

import pytest

import test_apage as A
import test_slock as L
import test_soloknob as K
import test_xfade as X
from test_reclock import NONE
from test_xfade import stock3  # noqa: F401  (a fixture)
from tools import build, build_main, params
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

E, ON, OFF, WORDS = L.E, L.ON, L.OFF, L.WORDS
SLOT = mm.SOLO_SLOT_ANALOG
ANALOG = [8, 9, 10, 11]


@pytest.fixture(scope="module")
def main(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=6)


@pytest.fixture(scope="module")
def before(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=5)


def locks(r, slot):
    return {s: r.lock_at(s, slot) for s in range(64) if r.lock_at(s, slot) != NONE}


def test_no_analog_machine_has_a_knob_on_the_slot(stock3):  # noqa: F811
    """Every record of the main program by its machine: the analog machines are 8 to 33 and 39 to 43, and none names
    slot 26. Stock copies a machine as ten words, 17 to 26 (0x400a9c2e), so it is a machine's word and no page's."""
    by = {}
    for p in params.load(stock3, "1.42"):
        by.setdefault(p.type, set()).add(p.slot)
    analog = [t for t in by if 8 <= t <= 33 or 39 <= t <= 43]
    assert len(analog) == 31 and all(by[t] <= set(range(17, 26)) for t in analog) and not any(SLOT in by[t] for t in analog)
    assert {t for t in analog if 25 in by[t]} == {28}
    assert stock3[mm.off(0x400a9c2e):mm.off(0x400a9c2e) + 6] == bytes.fromhex(fw.sx("681a9606f6d97820a3a9")) and \
        stock3[mm.off(0x400a9c64):mm.off(0x400a9c64) + 6] == bytes.fromhex(fw.sx("4055ca62b1f8c686267a"))


@pytest.mark.parametrize("track", ANALOG)
def test_knob_e_with_a_step_held_locks_the_steps_solo_on_an_analog_track(main, track):
    r = A.page(main, track)
    r.hold(12)
    assert r.fifth() == ["", "S OFF"]
    assert r.twist(E, 1) == 1
    assert locks(r, SLOT) == {12: ON} and r.solos == 0 and r.count(12) == 1 and r.fifth() == ["", "SOLO"]
    assert locks(r, mm.SOLO_SLOT) == {} and not r.rec_locks and r.others == {(track, 12, SLOT)}
    assert r.twist(E, -1) == 1 and locks(r, SLOT) == {} and r.count(12) == 0 and r.fifth() == ["", "S OFF"]
    r.hold()
    assert r.twist(E, 1) == 1 and r.solos == 1 << track and locks(r, SLOT) == {}    # no step held: the track's own, as before
    r.hold(3)
    assert r.fifth() == ["", "SOLO"]
    r.twist(E, -1)
    assert locks(r, SLOT) == {3: OFF} and r.solos == 1 << track and r.fifth() == ["", "S OFF"]


def test_a_track_that_holds_the_midi_machine_gets_no_lock(main):
    r = A.page(main, 10, machine=35)
    r.hold(2)
    r.twist(E, 1)
    assert locks(r, SLOT) == {} and r.solos == 1 << 10              # the slot may be a knob there: the track's own is turned


def test_a_samplers_is_on_slot_17_as_it_was(main, before):
    a, b = A.page(main, 4), A.page(before, 4)
    for r in (a, b):
        r.hold(7)
        r.twist(E, 1)
    assert locks(a, mm.SOLO_SLOT) == locks(b, mm.SOLO_SLOT) == {7: ON} and locks(a, SLOT) == {} and a.show() == b.show()


# ---- this block's solos --------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    r = X.Rig(*main, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    return r


def marks(rig, words, types=(8, 9, 10, 11)):
    """What the playing steps left: slot 17 of a digital track, slot 26 of an analog one. And the analog tracks' machines."""
    for t in range(12):
        slot = mm.SOLO_SLOT if t < 8 else SLOT
        rig.mc.write(WORDS + 142 * t + 28 + 2 * slot, words.get(t, 0).to_bytes(2, "big"))
    rig.mc.write(mm.MACHINE_BYTES + 8, bytes(types))


@pytest.mark.parametrize("track", ANALOG)
def test_a_step_locked_on_solos_its_analog_track(rig, track):
    marks(rig, {track: ON})
    quiet, voices = K.heard(rig, knob=0)
    assert quiet == [t for t in range(12) if t != track] and voices == [v for v in range(4) if 8 + v != track]
    assert rig.left == 0 and rig.mc.r32(mm.SOLO_NOW) == 1 << track
    marks(rig, {track: OFF})
    quiet, voices = K.heard(rig, knob=1 << track | 1 << 1)          # locked off on a soloed track: out of the solos
    assert quiet == [t for t in range(12) if t != 1] and voices == [0, 1, 2, 3] and rig.left == 1 << track | 1 << 1
    marks(rig, {})


@pytest.mark.parametrize("word", [0x0000, 0x4000, 0x7f00, 0xffff, 0x5280, ON ^ 0x0100, 0x0035])
def test_anything_else_in_the_slot_and_any_machine_that_is_not_analog_leave_the_tracks_own(rig, word):
    marks(rig, {t: word for t in ANALOG})
    assert K.heard(rig, knob=0) == ([], [])
    marks(rig, {9: ON}, types=(8, 35, 10, 11))                      # the MIDI machine on the track
    assert K.heard(rig, knob=0) == ([], [])
    marks(rig, {9: ON}, types=(8, 44, 10, 50))
    assert K.heard(rig, knob=0) == ([], [])
    marks(rig, {})


def test_slot_26_of_a_digital_track_and_slot_17_of_an_analog_one_are_not_looked_at(rig):
    marks(rig, {})
    for t in range(8):
        rig.mc.write(WORDS + 142 * t + 28 + 2 * SLOT, ON.to_bytes(2, "big"))         # a sampler's own knob is there
    for t in ANALOG:
        rig.mc.write(WORDS + 142 * t + 28 + 2 * mm.SOLO_SLOT, ON.to_bytes(2, "big"))   # an analog machine's first knob
    assert K.heard(rig, knob=0) == ([], [])
    for t in range(12):
        rig.mc.write(WORDS + 142 * t + 28, bytes(114))


def test_with_no_analog_mark_it_is_the_slock_images_mixer(rig, before):
    old = X.Rig(*before, entry="mix_amute")
    old.mc.map(0x7fffd000, 0x3000)
    for words in ({}, {3: ON}, {0: OFF, 6: ON}):
        marks(rig, words)
        L.marks(old, words)
        for knob in (0, 0x41, 0x900):
            assert K.heard(rig, knob=knob) == K.heard(old, knob=knob)
    marks(rig, {})
    L.marks(old, {})
    for xf in ([0] * 12, [0] * 9 + [99, 0, 0]):
        assert X.mixed(rig, xf=xf) == X.mixed(old, xf=xf)


def test_the_image(official_path, official, stock3, main):  # noqa: F811
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=6)[2]
    was = build.build(official_path, log=quiet, xfade=5)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    lo, hi = mm.CAVE_ALOCK
    assert old[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)] != new[mm.off(lo):mm.off(hi)]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8, mm.CAVE, mm.CAVE_AMUTE,
             mm.CAVE_ALOCK, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED, (mm.SYN_CLASS, mm.SYN_CLASS + 0x100), (mm.SYN_SIDE, mm.SYN_SIDE + 0x40)]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]       # operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
