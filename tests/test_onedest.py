"""The onedest image (engine/recpage.c, ONEDEST): the gainup image with DEST only SMPL.

On request
. Here, on the sampling page:
  - B reads DEST SMPL whatever it is turned to, and every track's take goes to its SMPL place (the box says DEST_SMPL);
  - a NEXT left from before (the page's own numbers are not cleared by a start) is dropped by a turn of B, and the poll
    holds no place for it;
  - C is still the track's KIND;
  - the image: only the page's runs differ from the gainup image's, and outside them addresses into them; section 7
    the gainup image's.
Emulation only."""
import shutil

import pytest

import test_gear as G
import test_next as N
import test_srr as R
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

B_, C_ = 2, 3


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=73)


def nx_on(r, main):
    return list(r.mc.read(main[1]["next_vars"] + 20, 8))


def test_b_reads_smpl_and_every_take_goes_to_smpl(main):
    t = 2
    r = N.rig(main, t)
    N.turns(r, 1, 1, 1, -1)
    for steps in (1, 1, 1, -1):
        G.twist(r, B_, steps)
        assert "SMPL" in N.says(r) and "NEXT" not in N.says(r) and "DEST" in N.says(r)
        assert all(N.dest(r, u) == N.DEST_SMPL for u in range(8)) and nx_on(r, main) == [0] * 8
    N.poll(r, main)
    assert all(N.dest(r, u) == N.DEST_SMPL for u in range(8))


def test_a_next_left_from_before_goes_at_a_turn_of_b(main):
    t = 2
    r = N.rig(main, t, N.bank(stereo=(1, 2)))
    N.turns(r, 1, 1)
    G.twist(r, B_, 1)                                           # the page's numbers made
    r.mc.write(G.STATE + 4 + 5, b"\x01")                        # track 6 on NEXT, as a build before left it
    N.on(r, main, 5)
    N.poll(r, main)
    assert N.dest(r, 5) == 2                                    # held a place, as on the gainup image
    G.twist(r, B_, 1)
    assert nx_on(r, main) == [0] * 8 and r.mc.read(G.STATE + 4, 8) == bytes(8)
    N.poll(r, main)
    assert all(N.dest(r, u) == N.DEST_SMPL for u in range(8))


def test_c_is_still_the_tracks_kind(main):
    t = 4
    r = N.rig(main, t)
    N.turns(r, 1, -1)
    G.twist(r, C_, 1)
    assert N.word(r, t) == R.signed(4, 0) | N.KIND and "MONO" in N.says(r)
    G.twist(r, C_, -1)
    assert N.word(r, t) == R.signed(4, 0) and "STER" in N.says(r)


def test_the_image(official_path, main):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=73)[2]
    was = build.build(official_path, log=quiet, xfade=72)[2]
    assert new.section(7) == was.section(7) and new.section(3) == main[0]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7,
             mm.CAVE_PAGE9, mm.CAVE_NEXT, mm.CAVE_NEXT2, mm.CAVE_NEXT3, mm.CAVE_NEXT4, mm.CAVE_NEXT5]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [k for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k)]
    print("differing: %d bytes, %d outside the page's runs" % (sum(n[k] != o[k] for k in range(len(n))), len(moved)))
    assert all(pointer(k) for k in moved)
