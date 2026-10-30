"""The eucl image: the soloend image with SOLO and REC only on the TRIG page's first page.

On request
. The TRIG object shows two
pages, 1 (or 2) and 3, the euclidean one (records 457 to 464, tools/uitable.pages); the trig image's three methods
did not ask which was showing. On page 3 they are stock's now, on every track.
"""
import shutil

import pytest

import test_gear as G
import test_trig as T
from test_page import LIST, PAGE
from tools import build, build_main, uitable
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=49)


def trig(main, track, showing):
    r = T.trig(main, track)
    r.mc.w32(LIST, 1)
    r.mc.w32(LIST + 4, 3)
    r.mc.w32(PAGE + mm.PAGE_LIST_END, LIST + 8)
    r.mc.w32(PAGE + mm.PAGE_INDEX, showing)
    return r


def test_page_3_is_the_euclidean_one(official):
    assert sorted(uitable.pages(official.section(3))[3]["knobs"]) == list(range(457, 465))


@pytest.mark.parametrize("track", [0, 5, 7])
def test_on_the_euclidean_page_every_knob_is_stocks(main, track):
    r = trig(main, track, 1)
    assert [r.ask(k) for k in range(8)] == [600 + k for k in range(8)]
    r.show()
    assert r.texts == [] and r.trig_stock[-1] == ("draw", PAGE)          # no SOLO, no REC, no switch drawn
    for k in range(1, 9):
        assert G.twist(r, k, 1) == 0x66
    assert [t for t in r.trig_stock if t[0] == "turn"] == [("turn", k) for k in range(1, 9)]
    assert int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") == 0


@pytest.mark.parametrize("track", [0, 5, 7])
def test_on_the_first_page_e_and_f_are_still_solo_and_rec(main, track):
    r = trig(main, track, 0)
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 0, 0, 606, 607]
    G.twist(r, T.E, 1)
    assert int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") == 1 << track


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=49)[2]
    was = build.build(official_path, log=quiet, xfade=48)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    spans = [mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3, mm.CAVE_TRIG4]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]   # operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
