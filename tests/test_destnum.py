"""The destnum image (engine/recpage.c, DESTNUM): the onedest image with DEST's numbers back.

On request
. Here, on the sampling
page:
  - a STER track's B goes SMPL, then the stereo places SMPL stops at (those with a sample and the lowest free one), and
    the box says each place; a MONO track's the single slots SMPL stops at (the highest free one and those with one);
  - a DEST of the other kind goes back to SMPL when KIND is turned, one of the track's kind stays;
  - nothing of NEXT: the poll holds no place and leaves the number in the box;
  - the image: only the page's runs differ from the onedest image's, and outside them addresses into them; section 7
    the onedest image's.
Emulation only."""
import shutil

import pytest

import test_gear as G
import test_next as N
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

B_, C_ = 2, 3
FRAMES = dict(stereo=(1, 2, 3), mono=(64, 63))


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=74)


def nx_on(r, main):
    return list(r.mc.read(main[1]["next_vars"] + 20, 8))


def walk(r, t, steps):
    """B turned a step at a time: what it says and what the box holds after each."""
    out = []
    for s in steps:
        G.twist(r, B_, s)
        shown = N.says(r)
        assert "DEST" in shown and "NEXT" not in shown
        out.append(("SMPL" if "SMPL" in shown else next(x for x in shown if x.isdigit() and len(x) == 2), N.dest(r, t)))
    return out


def test_a_ster_track_goes_smpl_then_the_stereo_places_smpl_stops_at(main):
    t = 2
    r = N.rig(main, t, N.bank(**FRAMES))
    N.turns(r, 1, 1, 1, 1, 1, -1, -1, -1, -1)
    got = walk(r, t, [1, 1, 1, 1, 1, -1, -1, -1, -1])
    print(got)
    assert got == [("01", 0), ("02", 1), ("03", 2), ("04", 3), ("04", 3), ("03", 2), ("02", 1), ("01", 0), ("SMPL", N.DEST_SMPL)]


def test_a_mono_track_goes_smpl_then_the_single_slots_smpl_stops_at(main):
    t = 5
    r = N.rig(main, t, N.bank(**FRAMES))
    N.turns(r, 1, 1, 1, 1, 1)
    G.twist(r, C_, 1)                                           # KIND MONO
    assert N.word(r, t) & N.KIND
    got = walk(r, t, [1, 1, 1, 1])
    print(got)
    assert got == [("62", 61), ("63", 62), ("64", 63), ("64", 63)]


def test_a_dest_of_the_other_kind_goes_back_to_smpl_at_a_turn_of_kind(main):
    t = 1
    r = N.rig(main, t, N.bank(**FRAMES))
    N.turns(r, 1, 1, 1, -1, 1)
    walk(r, t, [1, 1])                                          # 02, a stereo place
    G.twist(r, C_, 1)                                           # MONO: 02 is not one of its places
    assert N.dest(r, t) == N.DEST_SMPL and "SMPL" in N.says(r)
    G.twist(r, B_, -1)                                          # SMPL already: stays
    G.twist(r, B_, 1)
    assert N.dest(r, t) == 61                                   # the first single slot SMPL stops at
    r.answers[:] = [256]
    G.twist(r, C_, 1)                                           # MONO again: 62 stays
    assert N.dest(r, t) == 61


def test_nothing_of_next_the_poll_leaves_the_number(main):
    t = 0
    r = N.rig(main, t, N.bank(**FRAMES))
    N.turns(r, 1, 1, 1)
    walk(r, t, [1, 1, 1])
    assert nx_on(r, main) == [0] * 8 and N.dest(r, t) == 2
    N.poll(r, main)
    assert N.dest(r, t) == 2 and all(N.dest(r, u) == N.DEST_SMPL for u in range(1, 8))


def test_the_image(official_path, main):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=74)[2]
    was = build.build(official_path, log=quiet, xfade=73)[2]
    assert new.section(7) == was.section(7) and new.section(3) == main[0]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7,
             mm.CAVE_PAGE9, mm.CAVE_NEXT, mm.CAVE_NEXT2, mm.CAVE_NEXT3, mm.CAVE_NEXT4, mm.CAVE_NEXT5, mm.CAVE_KIND]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [k for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k)]
    print("differing: %d bytes, %d outside the page's runs" % (sum(n[k] != o[k] for k in range(len(n))), len(moved)))
    assert all(pointer(k) for k in moved)
