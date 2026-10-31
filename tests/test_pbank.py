"""The pbank image (engine/pbank.c, PBANK): the next image with BANK off the sampling page and in the PROJECT menu.


one entry that moves to the next bank each time it is chosen, and the bank
still loads only with a project. Here, the main CPU only:
  - the PROJECT menu, built by stock's own constructors at the start, has a fourth entry under MANAGE PROJECTS, drawn
    by stock's own list: SAMPLE BANK and the loaded bank, A>B with another chosen;
  - choosing it, through stock's own call of an entry's action, moves BANK_WANT on, after C to A, and marks the menu
    to be drawn again; nothing is loaded;
  - knob D of the sampling page shows and turns nothing;
  - section 7 the spread image's.
Emulation only: the list's keys and its redraw on the unit are not run."""

import hashlib
import re
import shutil
import struct

import numpy as np
import pytest

import test_gear as G
import test_next as N
import test_stretch as X
from emu import screen as S
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

BANK_NOW, BANK_WANT = 0x40196aba, 0x40196abe
ITEM_CLASS = 0x402410f8                 # an entry of a list: its name's call at + 24, its action's data at + 28
ITEM_ACTION = 0x400fa638                # (entry): stock's call of an entry's action, as the list makes it (0x400ff5b6)
D_ = 3


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=62)


@pytest.fixture(scope="module")
def stock(official):
    return S.Screen(official.section(3))


@pytest.fixture
def scr(main):
    return S.Screen(main[0])


def menu(s):
    lo = mm.MAIN_HEAP[0]
    heap = bytes(s.mc.read(lo, 0x400000))
    found = [lo + m.start() for m in re.finditer(re.escape(struct.pack(">I", mm.PROJECT_MENU_CLASS)), heap)]
    assert len(found) == 1
    return found[0]


def entries(s, call):
    lo = mm.MAIN_HEAP[0]
    heap = bytes(s.mc.read(lo, 0x400000))
    return [lo + m.start() for m in re.finditer(re.escape(struct.pack(">I", ITEM_CLASS)), heap)
            if s.mc.r32(lo + m.start() + 24) == call]


def banks(s, now, want):
    s.mc.w32(BANK_NOW, now)
    s.mc.w32(BANK_WANT, want)


def test_the_project_menu_has_a_fourth_entry_drawn_by_stock(main, scr, stock):
    was, now = stock.draw(menu(stock) + 56), scr.draw(menu(scr) + 56)
    rows = [y for y in range(64) if (was[y] != now[y]).any()]
    assert rows and min(rows) >= 40                     # the three entries and the title as they were; under them, ours
    assert len(entries(scr, main[1]["bank_name"])) == 1
    banks(scr, 0, 0)
    a = scr.draw(menu(scr) + 56)
    banks(scr, 0, 1)
    ab = scr.draw(menu(scr) + 56)
    banks(scr, 2, 2)
    c = scr.draw(menu(scr) + 56)
    assert (a[40:] != ab[40:]).any() and (a[40:] != c[40:]).any() and (a[:40] == ab[:40]).all()


@pytest.mark.parametrize("now, want, then", [(0, 0, [1, 2, 0, 1]), (1, 0xffffffff, [2, 0, 1]), (2, 2, [0, 1, 2]),
                                             (0xffffffff, 0xffffffff, [1, 2, 0])])
def test_choosing_it_moves_to_the_next_bank_and_loads_nothing(main, scr, now, want, then):
    item, = entries(scr, main[1]["bank_name"])
    page = menu(scr) + 56
    banks(scr, now, want)
    for b in then:
        scr.mc.write(page + 20, b"\0")
        scr.run(ITEM_ACTION, item)
        assert scr.mc.r32(BANK_WANT) == b and scr.mc.r32(BANK_NOW) == now
        assert scr.mc.read(page + 20, 1) == b"\x01"     # the menu marked to be drawn again


def test_the_text(main, scr):
    t = main[1]["w_sbank"]
    for now, want, says in ((0, 0, b"SAMPLE BANK A"), (0, 1, b"SAMPLE BANK A>B"), (1, 0xffffffff, b"SAMPLE BANK B"),
                            (2, 0, b"SAMPLE BANK C>A"), (7, 7, b"SAMPLE BANK A")):
        banks(scr, now, want)
        scr.run(main[1]["bank_text"])
        assert bytes(scr.mc.read(t, 16)).split(b"\0")[0] == says


def test_knob_d_of_the_sampling_page_is_nothing(main):
    r = N.rig(main, 2)
    r.mc.w32(BANK_NOW, 0)
    r.mc.w32(BANK_WANT, 0)
    N.turns(r, 1, 1)
    assert "BANK" not in N.says(r)
    G.twist(r, D_, 1)
    assert r.mc.r32(BANK_WANT) == 0 and "BANK" not in N.says(r)
    assert not r.locks and not r.locked


def test_the_sampling_page_draws_d_empty(scr):
    dots = scr.draw(scr.page(*S.PAGES["sampling"]))
    assert not dots[16:27, 106:117].any()            # inside stock's dotted box: no name, no value


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=62, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=61, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("8da5c8f4")      # the next image, as it is
    print("pbank image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE4, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE9, mm.CAVE_TRIG3, mm.CAVE_STSW, mm.CAVE_STSW2,
             mm.CAVE_ONCE, mm.CAVE_SRR, mm.CAVE_LOCK, mm.CAVE_NEXT, mm.CAVE_NEXT2, mm.CAVE_NEXT3, mm.CAVE_NEXT4, mm.CAVE_NEXT5,
             mm.CAVE_PBANK, (mm.PROJECT_MENU_END, mm.PROJECT_MENU_END + 6)]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
