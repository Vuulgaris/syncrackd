"""The axf image (engine/recpage.c, AXF): the ask image with the analog tracks' second SYN page drawn clean.



Since the slice image `load_place` puts the peak in G's place, and `xfade_place`, which only the analog tracks' page still
calls, drew it there and the crossfade over it. Here, by stock's own page drawn in emulation (emu/screen.py):
  - on the ask image G is the crossfade and the peak at once, exactly what this image puts in G and in H;
  - a sampler track's sampling page as the ask image's;
  - the image: only the page's two runs differ from the ask image's, and outside them the addresses of routines in
    them that moved; section 7 the ask image's.
Emulation only."""
import shutil

import numpy as np
import pytest

from emu import screen as S
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ROWS = slice(40, 57)                    # the lower row of places
G, H = slice(75, 98), slice(101, 124)   # a place's text and box, 26 dots apart; the page's mark at the right edge left out


@pytest.fixture(scope="module")
def axf(official):
    return build_main.patched_image(official.section(3), xfade=71)


@pytest.fixture(scope="module")
def ask(official):
    return build_main.patched_image(official.section(3), xfade=70)


def analog_page(image):
    s = S.Screen(image[0], 8)
    s.mc.write(0x4001ff74, bytes([0x70, 8, 0x4e, 0x75]))       # the active track: 8, the first analog one
    s.mc.uc.ctl_flush_tb()
    return s.draw(s.page(*S.PAGES["sampling"]))


def test_on_the_ask_image_g_was_the_crossfade_and_the_peak_at_once(ask, axf):
    was, now = analog_page(ask), analog_page(axf)
    assert np.array_equal(was[ROWS, G], now[ROWS, G] | now[ROWS, H])
    assert now[ROWS, H].sum() > was[ROWS, H].sum() and now[ROWS, G].sum() < was[ROWS, G].sum()
    assert np.array_equal(was[:ROWS.start], now[:ROWS.start])   # the rest of the page as it was


def test_a_sampler_tracks_sampling_page_is_the_ask_images(ask, axf):
    pages = [S.Screen(i[0], 44) for i in (ask, axf)]
    was, now = (s.draw(s.page(*S.PAGES["sampling"])) for s in pages)
    assert np.array_equal(was, now)


def test_the_image(official_path, ask, axf):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=71)[2]
    was = build.build(official_path, log=quiet, xfade=70)[2]
    assert new.section(7) == was.section(7) and new.section(3) == axf[0] and was.section(3) == ask[0]
    spans = [mm.CAVE_PAGE4, mm.CAVE_PAGE7]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [k for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k)]
    print("outside the two runs: %d bytes, each an address into them" % len(moved))
    assert all(pointer(k) for k in moved)       # the routines after peak_h and after xfade_place moved, and their callers' addresses with them
