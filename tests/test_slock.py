"""The slock image: the apage image with a sampler track's solo lockable to a step."""
import shutil

import pytest

import test_apage as A
import test_mainpatch as M
import test_soloknob as K
import test_xfade as X
from test_reclock import NONE
from test_xfade import stock3  # noqa: F401  (a fixture)
from tools import build, build_main, params
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

E = K.SOLO_KNOB
SLOT, ON, OFF = mm.SOLO_SLOT, mm.SOLO_LOCK_ON << 8 | 0x80, mm.SOLO_LOCK_OFF << 8 | 0x80
WORDS = M.PARAMS - (mm.PARAM_SENT - mm.PARAM_WORDS)  # where a trig's locks are written, as the mixer's rig has the block


@pytest.fixture(scope="module")
def main(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=5)


@pytest.fixture(scope="module")
def before(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=4)


def solo_locks(r):
    return {s: r.lock_at(s, SLOT) for s in range(64) if r.lock_at(s, SLOT) != NONE}


# ---- the page
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("track", [0, 4, 7])
def test_knob_e_with_a_step_held_locks_the_steps_solo(main, track):
    r = A.page(main, track)
    r.hold(5)
    assert r.fifth() == ["", "S OFF"]
    assert r.twist(E, 1) == 1
    assert solo_locks(r) == {5: ON} and r.solos == 0 and r.count(5) == 1  # the step's, and the track's own is as it was
    assert r.fifth() == ["", "SOLO"]  # the place says the held step's
    assert not r.rec_locks and r.others == {(track, 5, SLOT)} and not r.locks and not r.changes
    assert r.twist(E, 1) == 1 and solo_locks(r) == {5: ON}
    assert r.twist(E, -1) == 1
    assert solo_locks(r) == {} and r.count(5) == 0 and r.fifth() == ["", "S OFF"]  # as the track does: no lock is left
    r.hold()
    assert r.fifth() == ["", "S OFF"] and r.twist(E, 1) == 1 and r.solos == 1 << track and solo_locks(r) == {}


def test_on_a_soloed_track_a_step_can_be_locked_off(main):
    r = A.page(main, 2, word=1 << 2)
    r.hold(9)
    assert r.fifth() == ["", "SOLO"]
    r.twist(E, -1)
    assert solo_locks(r) == {9: OFF} and r.solos == 1 << 2 and r.fifth() == ["", "S OFF"]
    r.twist(E, 1)
    assert solo_locks(r) == {} and r.fifth() == ["", "SOLO"]


def test_every_held_step_gets_its_own_and_one_with_no_trig_gets_a_trig(main):
    r = A.page(main, 6)
    r.hold(0, 17, 40, trigs=False)
    r.trigs = {17}
    r.twist(E, 2)
    assert solo_locks(r) == {0: ON, 17: ON, 40: ON} and r.trigs == {0, 17, 40} and r.solos == 0


def test_the_two_marks_are_not_recs_and_the_slot_is_no_knob_of_a_digital_machine(main):
    assert {ON >> 8, OFF >> 8}.isdisjoint({0x52, 0x29, 0x00, 0x40, 0x7f, 0xff}) and SLOT != mm.REC_SLOT
    machines = params.machines(main[0], "1.42")  # the twelve machines the audio CPU runs
    assert 44 in machines and not [p for ps in machines.values() for p in ps if p.slot == SLOT]


def test_with_no_step_held_and_on_an_analog_track_it_is_the_apage_images(main, before):
    for track in (3, 9):
        a, b = A.page(main, track), A.page(before, track)
        assert a.show() == b.show()
        for k in range(1, 9):
            assert a.twist(k, 1) == b.twist(k, 1)
        assert a.solos == b.solos and A.xf12(a) == A.xf12(b) and a.show() == b.show() and solo_locks(a) == {}
    r = A.page(main, 9)
    r.hold(4)
    r.twist(E, 1)
    assert solo_locks(r) == {} and r.solos == 1 << 9  # an analog track's solo is the track's alone


# ---- the mixer link and the analog mute
# ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    r = X.Rig(*main, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    return r


def marks(rig, words):
    """What the playing steps left in slot 17 of the eight digital tracks, where a trig's locks are written."""
    for t in range(8):
        rig.mc.write(WORDS + 142 * t + 28 + 2 * SLOT, words.get(t, 0x0000).to_bytes(2, "big"))


@pytest.mark.parametrize("track", [0, 3, 7])
def test_a_step_locked_on_solos_its_track_while_its_mark_is_there(rig, track):
    marks(rig, {track: ON})
    quiet, voices = K.heard(rig, knob=0)
    assert quiet == [t for t in range(12) if t != track] and voices == [0, 1, 2, 3]
    assert rig.left == 0 and rig.mc.r32(mm.SOLO_NOW) == 1 << track  # the knobs' long is not written: the next trig ends it
    marks(rig, {})
    assert K.heard(rig, knob=0) == ([], [])


def test_a_step_locked_off_takes_its_track_out_of_the_solos(rig):
    marks(rig, {2: OFF})
    quiet, voices = K.heard(rig, knob=1 << 2 | 1 << 5)
    assert quiet == [t for t in range(12) if t != 5] and rig.left == 1 << 2 | 1 << 5
    quiet, voices = K.heard(rig, knob=1 << 2)  # the only solo, locked off: no solo, the mutes count again
    assert quiet == [] and voices == []
    marks(rig, {})


@pytest.mark.parametrize("word", [0x0000, 0x4000, 0x7f00, 0xffff, 0x5280, 0x2980, ON ^ 0x0100, OFF ^ 0x0100, 0x0035])
def test_anything_else_in_the_slot_leaves_the_tracks_own_solo_to_decide(rig, word):
    marks(rig, {t: word for t in range(8)})
    assert K.heard(rig, knob=0) == ([], [])
    quiet, _ = K.heard(rig, knob=1 << 6)
    assert quiet == [t for t in range(12) if t != 6]
    marks(rig, {})


def test_the_mark_counts_through_its_whole_low_byte_and_only_on_a_sampler(rig):
    for low in (0x00, 0x80, 0xff):
        marks(rig, {1: ON & 0xff00 | low})
        assert K.heard(rig, knob=0)[0] == [t for t in range(12) if t != 1]
    machines = list(K.MACHINES)
    machines[1] = 4  # another machine: the slot's word is nothing of ours
    assert K.heard(rig, machines=machines, knob=0) == ([], [])
    marks(rig, {})


def test_with_no_mark_it_is_the_apage_images_mixer(rig, before):
    old = X.Rig(*before, entry="mix_amute")
    marks(rig, {})
    for knob in (0, 0x21, 0x800, 0x104):
        assert K.heard(rig, knob=knob) == K.heard(old, knob=knob)
    for xf in ([0] * 12, [40] + [0] * 11, [0] * 9 + [99, 0, 0]):
        assert X.mixed(rig, xf=xf) == X.mixed(old, xf=xf)


# ---- the image
# ------------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, stock3, main):  # noqa: F811
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=5)[2]
    was = build.build(official_path, log=quiet, xfade=4)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    assert new[mm.off(mm.SOLO_NOW):mm.off(mm.SOLO_NOW) + 4] == bytes(4) and mm.SOLO_NOW + 4 <= mm.CAVE_SOLO[1]
    assert not stock3.count(mm.SOLO_NOW.to_bytes(4, "big"))
    lo, hi = mm.CAVE_PAGE8
    assert old[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)] != new[mm.off(lo):mm.off(hi)]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8, mm.CAVE, mm.CAVE_AMUTE,
             mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED, (mm.SOLO_NOW, mm.SOLO_NOW + 4), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100), (mm.SYN_SIDE, mm.SYN_SIDE + 0x40)]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]  # operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
