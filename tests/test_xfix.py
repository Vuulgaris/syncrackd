"""The xfix image: the nofx image with the crossfade's hand-over taking the others' live crossfade away too."""
import hashlib
import shutil

import pytest

import test_gear as G
import test_xknob as XK
import test_xshare as XS
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

D, TOP = XK.D, XK.TOP
LIVE = mm.PARAM_WORDS


def live(r, t):
    return int.from_bytes(r.mc.read(LIVE + 142 * t + 28 + 2 * XK.DEC, 2), "big")


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=43)


@pytest.fixture(scope="module")
def nofx(official):
    return build_main.patched_image(official.section(3), xfade=42)


def first(built, track, holder=2, x=60):
    r = XS.first(built, track, holder=holder, x=x)
    try:
        r.mc.read(LIVE, 2)
    except Exception:
        r.mc.map(LIVE & ~0xfff, 0x1000)  # eight tracks of 142 bytes end before 0x80003000
    for t in range(8):
        r.mc.write(LIVE + 142 * t + 28 + 2 * XK.DEC, ((TOP - (x if t == holder else 0)) << 8).to_bytes(2, "big"))
    return r


def test_a_turn_on_another_track_takes_the_holders_live_crossfade_away(main):
    r = first(main, 5)
    G.twist(r, D, 3)
    assert [XK.kit_dec(r, t) >> 8 for t in range(8)] == [TOP - 60 if t == 5 else TOP for t in range(8)]
    assert [live(r, t) >> 8 for t in range(8)] == [TOP for t in range(8)]  # the turning track's own is stock's to write


def test_on_the_nofx_image_the_live_word_was_left(nofx):
    r = first(nofx, 5)
    G.twist(r, D, 3)
    assert live(r, 2) >> 8 == TOP - 60  # the stuck number


def test_with_a_step_held_nothing_is_taken(main):
    r = first(main, 5)
    r.hold(4)
    G.twist(r, D, 2)
    assert live(r, 2) >> 8 == TOP - 60 and XK.kit_dec(r, 2) >> 8 == TOP - 60


def test_a_track_that_is_no_sampler_is_left(main):
    r = first(main, 5)
    r.machines = {t: (44 if t != 2 else 3) for t in range(8)}
    G.twist(r, D, 3)
    assert live(r, 2) >> 8 == TOP - 60


def test_the_image(official_path, main, nofx):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=43, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=42, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("890730a6")  # the nofx image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == nofx[0]
    diff = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k]]
    runs = [r for n, r in vars(mm).items() if n.startswith("CAVE") and isinstance(r, tuple) and len(r) == 2]
    stray = [a for a in diff if not any(lo <= int(a, 16) < hi for lo, hi in runs)]
    assert diff and stray == []
    print("xfix image", hashlib.sha256(raw).hexdigest())
