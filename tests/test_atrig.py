"""The atrig image: the norm image with an analog track's SOLO on its TRIG page and LFO.T on its FLTR2."""
import shutil

import pytest

import test_apage as A
import test_fltr as FL
import test_gear as G
import test_trig as T
from test_page import LIST, PAGE
from tools import build, build_main, uitable
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

LFO_T = 28


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=51)


@pytest.fixture(scope="module")
def before(official):
    return build_main.patched_image(official.section(3), xfade=50)


def trig(built, track, pages, showing=0):
    r = T.trig(built, track)
    for i, n in enumerate(pages):
        r.mc.w32(LIST + 4 * i, n)
    r.mc.w32(PAGE + mm.PAGE_LIST_END, LIST + 4 * len(pages))
    r.mc.w32(PAGE + mm.PAGE_INDEX, showing)
    return r


def solo(r):
    return int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big")


def test_the_analog_pages_are_as_read(official):
    pages = uitable.pages(official.section(3))
    assert pages[1]["knobs"][:6] == [20, 22, 23, 33, LFO_T, 27] and pages[8]["knobs"][6] == 0


@pytest.mark.parametrize("track", [8, 9, 11])
def test_on_an_analog_trig_page_e_is_solo_and_the_rest_are_stocks(main, track):
    r = trig(main, track, (1, 3))
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 0, 605, 606, 607]
    for k in (1, 2, 3, 4, 6, 7, 8):
        assert G.twist(r, k, 1) == 0x66
    assert [t for t in r.trig_stock if t[0] == "turn"] == [("turn", k) for k in (1, 2, 3, 4, 6, 7, 8)]
    assert solo(r) == 0
    G.geared(r, [256, -256])
    G.twist(r, T.E, 1)
    assert solo(r) == 1 << track
    G.twist(r, T.E, -1)
    assert solo(r) == 0


@pytest.mark.parametrize("held", [(), (0,), (3, 9)])
@pytest.mark.parametrize("answers", [(256,), (256, -256), (-256,)])
def test_with_steps_held_it_locks_as_the_second_syn_page_did(main, before, held, answers):
    assert T.scene(trig(main, 9, (1, 3)), T.E, held, answers)[:2] == T.scene(A.page(before, 9, index=1), T.E, held, answers)[:2]


@pytest.mark.parametrize("track", [9, 2])
def test_the_euclidean_page_is_stocks(main, track):
    r = trig(main, track, (1 if track >= 8 else 2, 3), showing=1)
    assert [r.ask(k) for k in range(8)] == [600 + k for k in range(8)]


def test_a_samplers_trig_page_is_as_it_was(main):
    r = trig(main, 4, (2, 3))
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 0, 0, 606, 607]


def test_the_second_syn_page_has_no_solo_now(main, before):
    new, old = A.page(main, 10, index=1), A.page(before, 10, index=1)
    G.geared(new, [256])
    G.geared(old, [256])
    new.twist(T.E, 1)
    old.twist(T.E, 1)
    assert solo(new) == 0 and solo(old) == 1 << 10


@pytest.mark.parametrize("track", [8, 10, 11])
def test_an_analog_fltr2s_g_is_lfo_t(main, track):
    r = FL.fltr(main, track)
    r.mc.w32(FL.NUMBERS, 7)
    r.mc.w32(FL.NUMBERS + 4, 8)
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 604, 605, LFO_T, 607]
    r.mc.w32(PAGE + mm.PAGE_INDEX, 0)
    assert [r.ask(k) for k in range(8)] == [600 + k for k in range(8)]


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=51)[2]
    was = build.build(official_path, log=quiet, xfade=50)[2]
    assert new.section(3) == main[0] != was.section(3) and new.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert new.container.by_id(sid).stored == official.container.by_id(sid).stored
