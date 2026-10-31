"""The gainup image (engine/recpage.c, GAINUP): the axf image with the sampling page's places moved."""
import shutil

import numpy as np
import pytest

import test_gear as G
import test_srr as R
import test_stretch as X
from emu import screen as S
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

D, E, F, GK = 4, 5, 6, 7  # knob ids, a knob's place plus 1
TOP, LOW = slice(10, 37), slice(37, 64)  # a row's box, value and name: the lower row 27 dots under the upper


def at(dots, row, k):
    """A place's dots: its box, value and name, 26 dots a place; the page's mark at the right edge left out."""
    return dots[row, 23 + 26 * k:46 + 26 * k]


@pytest.fixture(scope="module")
def axf(official):
    return build_main.patched_image(official.section(3), xfade=71)


@pytest.fixture(scope="module")
def gainup(official):
    return build_main.patched_image(official.section(3), xfade=72)


def sampling(image):
    s = S.Screen(image[0], 44)
    return s.draw(s.page(*S.PAGES["sampling"]))


def test_the_places_moved(axf, gainup):
    was, now = sampling(axf), sampling(gainup)
    assert np.array_equal(at(now, TOP, 3), at(was, LOW, 1))  # D: the gain, F's on the axf image
    assert np.array_equal(at(now, LOW, 0), at(was, LOW, 2))  # E: the peak, G's
    assert np.array_equal(at(now, LOW, 2), at(was, LOW, 0))  # G: STRC, E's
    assert np.array_equal(at(now, LOW, 1), at(was, TOP, 3))  # F: an empty box, as D was
    for row, k in [(TOP, 0), (TOP, 1), (TOP, 2), (LOW, 3)]:
        assert np.array_equal(at(now, row, k), at(was, row, k))
    assert at(was, LOW, 1).sum() > at(now, LOW, 1).sum() and at(now, TOP, 3).sum() > at(was, TOP, 3).sum()


def test_d_turns_the_gain_e_the_profile_g_the_stretch_and_f_nothing(gainup):
    t = 3
    r = X.keyed(gainup, t)
    calls = G.geared(r, [256, 256, 256, 256])  # (a kit afresh: the word after it)
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    prof = gainup[1]["prof_on"]
    gain = lambda: r.mc.read(mm.REC_GAINS + t, 1)[0]
    G.twist(r, D, 1)
    assert gain() == 1 and calls[-1][1] == 3 and calls[-1][3] == mm.FEEL_PLAIN  # by the plain feel, as F was
    n = len(calls)
    G.twist(r, E, 1)
    assert r.mc.r32(prof) == 1 and len(calls) == n  # not geared, as G was
    G.twist(r, E, -1)
    assert r.mc.r32(prof) == 0
    G.twist(r, GK, 1)
    assert G.own(r, t) == R.signed(4, 0) | 8  # stretched
    before = (gain(), G.own(r, t), r.mc.r32(prof))
    G.twist(r, F, 1)
    assert (gain(), G.own(r, t), r.mc.r32(prof)) == before


def test_the_image(official_path, axf, gainup):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=72)[2]
    was = build.build(official_path, log=quiet, xfade=71)[2]
    assert new.section(7) == was.section(7) and new.section(3) == gainup[0] and was.section(3) == axf[0]
    n, o = new.section(3), was.section(3)
    moved = [(hex(mm.BASE + k), o[k], n[k]) for k in range(len(n)) if n[k] != o[k]]
    print(moved)
    assert len(moved) == 8  # the place numbers, and the turn's two branches' offsets swapped
    assert sorted((a, b) for _, a, b in moved if a < 8) == [(4, 6), (5, 3), (6, 4), (6, 4)]
