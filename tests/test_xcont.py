"""The xcont image: the xfix image with the crossfade's hand-over taking its amount from the unfiltered words.

On request
. A turn of D with no step held gives the turning track the pattern's
crossfade before each tick (engine/recpage.c, xf_take); that amount was the analog mute's largest, made from the
filtered block (about 60 ms behind). With the old holder's word cleared at once (xfix), the two crossed in the filter
and the largest dipped, each tick began again from the dip, down to 0. XCONT, xf_live: the largest of the sampler tracks'
words the block is filtered from (0x800021b0, which the clear and stock's store set at once) and the analog tracks' own.

Held here with the xshare image's rig, the filtered numbers made to lag as on the unit. Not held: stock's filter.
"""
import hashlib
import shutil

import pytest

import test_gear as G
import test_xfix as XF
import test_xknob as XK
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

D, TOP = XK.D, XK.TOP


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=44)


@pytest.fixture(scope="module")
def xfix(official):
    return build_main.patched_image(official.section(3), xfade=43)


def lagging(built, track, live, filtered, analog=(0, 0, 0, 0)):
    """The first page on `track`; `live` {track: crossfade} in the words at 0x800021b0 (and the kit), the analog mute's
    twelve numbers `filtered` (eight) and `analog`, as a filter behind them leaves them."""
    r = XF.first(built, track, holder=None, x=0)
    for t in range(8):
        x = live.get(t, 0)
        r.mc.write(XF.LIVE + 142 * t + 28 + 2 * XK.DEC, ((TOP - x) << 8).to_bytes(2, "big"))
        r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * XK.DEC, ((TOP - x) << 8).to_bytes(2, "big"))
        r.mc.write(mm.PARAM_SENT + 142 * t + 62, bytes([44]))
    r.mc.write(mm.XFADES, bytes(list(filtered) + list(analog)))
    return r


@pytest.mark.parametrize("built,want", [("main", 60), ("xfix", 20)])
def test_the_first_tick_takes_the_holders_amount_not_the_filters_dip(main, xfix, built, want):
    r = lagging(main if built == "main" else xfix, 5, {2: 60}, [0, 0, 20, 0, 0, 0, 0, 0])
    G.twist(r, D, 1)
    assert XK.kit_dec(r, 5) >> 8 == TOP - want                  # on the xfix image: the dip, the snap
    assert XF.live(r, 2) >> 8 == TOP                            # and the old holder cleared


@pytest.mark.parametrize("built,want", [("main", 63), ("xfix", 30)])
def test_the_next_ticks_go_on_from_the_turning_tracks_own(main, xfix, built, want):
    r = lagging(main if built == "main" else xfix, 5, {5: 63}, [0, 0, 30, 0, 0, 25, 0, 0])
    G.twist(r, D, 1)
    assert XK.kit_dec(r, 5) >> 8 == TOP - want


def test_an_analog_holders_amount_is_still_carried(main):
    r = lagging(main, 1, {}, [0] * 8, analog=(0, 50, 0, 0))
    G.twist(r, D, 1)
    assert XK.kit_dec(r, 1) >> 8 == TOP - 50 and list(r.mc.read(mm.XFADES + 8, 4)) == [0, 0, 0, 0]


def test_a_track_that_is_no_sampler_is_not_counted(main):
    r = lagging(main, 5, {2: 90}, [0] * 8)
    r.mc.write(mm.PARAM_SENT + 142 * 2 + 62, bytes([3]))
    G.twist(r, D, 1)
    assert XK.kit_dec(r, 5) >> 8 == TOP


def test_the_image(official_path, main, xfix):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=44, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=43, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("b3c276e4")      # the xfix image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == xfix[0]
    runs = [r for n, r in vars(mm).items() if n.startswith("CAVE") and isinstance(r, tuple) and len(r) == 2]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))      # a method's pointer to ours that moved
    diff = [mm.BASE + k for k in range(len(new)) if new[k] != old[k]]
    assert diff and [hex(a) for a in diff if not any(lo <= a < hi for lo, hi in runs) and not moved(mm.off(a))] == []
    print("xcont image", hashlib.sha256(raw).hexdigest())
