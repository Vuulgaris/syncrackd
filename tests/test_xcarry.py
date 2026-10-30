"""The xcarry image: the xcont image with the crossfade's amount handed over through the page's own method.

On request. Read (stock's turn, 0x4003b870): the change of a
turn is added through the page's method at + 96 to the page's own value for the record, not to the kit's word that
xf_take wrote, so the turning track began from its own old number. XCARRY, xf_carry: before the turn, the track's
value is brought to the pattern's crossfade (the unfiltered largest, xf_live) through the page's + 88, which stock's
own methods carry to the holder, and stock's turn goes on from it.

Held here with the page rig, stock's + 84 and + 88 run as they are, the holder's value and change stood in for.
Not held: the holder itself, and the unit.
"""
import hashlib
import shutil

import pytest

import test_gear as G
import test_xcont as XC
import test_xfix as XF
import test_xknob as XK
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

D, TOP, R_DEC = XK.D, XK.TOP, XK.R_DEC


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=45)


@pytest.fixture(scope="module")
def xcont(official):
    return build_main.patched_image(official.section(3), xfade=44)


def turning(built, track, live, own, filtered=(0,) * 8):
    """The page on `track` with its own crossfade `own` as the page holds it; `live` as in test_xcont."""
    r = XC.lagging(built, track, live, list(filtered))
    r.ui = {R_DEC: (TOP - own) << 8}
    r.changes = []
    r.value = lambda holder, record: r.ui.get(record, r.mode << 8)

    def plain(holder, record, change, t, flag, answer, a, b):
        change -= (change & 0x80000000) << 1
        r.changes.append((record, change))
        r.ui[record] = r.ui.get(record, 0) + change
        return 0
    r.plain = plain
    return r


def test_the_turning_track_is_given_the_holders_amount_before_the_turn(main):
    r = turning(main, 5, {2: 60}, own=0)
    G.twist(r, D, 1)
    assert r.changes == [(R_DEC, -60 << 8)] and r.ui[R_DEC] == (TOP - 60) << 8
    assert len(r.seen_steps) == 1 and XF.live(r, 2) >> 8 == TOP


def test_on_the_xcont_image_the_page_kept_its_own(xcont):
    r = turning(xcont, 5, {2: 60}, own=0)
    G.twist(r, D, 1)
    assert r.changes == [] and r.ui[R_DEC] == TOP << 8            # the turn began from 0: the snap


def test_a_track_that_holds_it_already_is_not_changed(main):
    r = turning(main, 5, {5: 63}, own=63, filtered=(0, 0, 30, 0, 0, 25, 0, 0))
    G.twist(r, D, 1)
    assert r.changes == []


def test_with_a_step_held_nothing_is_handed_over(main):
    r = turning(main, 5, {2: 60}, own=0)
    r.hold(4)
    G.twist(r, D, 1)
    assert r.changes == [] and XF.live(r, 2) >> 8 == TOP - 60


def test_the_image(official_path, main, xcont):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=45, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=44, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("0c1210c5")      # the xcont image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == xcont[0]
    runs = [r for n, r in vars(mm).items() if n.startswith("CAVE") and isinstance(r, tuple) and len(r) == 2]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    diff = [mm.BASE + k for k in range(len(new)) if new[k] != old[k]]
    assert diff and [hex(a) for a in diff if not any(lo <= a < hi for lo, hi in runs) and not moved(mm.off(a))] == []
    print("xcarry image", hashlib.sha256(raw).hexdigest())
