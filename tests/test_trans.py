"""The trans image: the spread image with FLTR2's DEL drawn as a plain knob named TRANS on a sampler track.



and still DEL: that argument means no picture, and the name is the descriptor's, drawn by
the + 180 itself (engine/hits.c, TRANS). This build keeps stock's way, marks a sampler track's DEL, draws the plain
knob's graphic in the delay's place when marked, and names it TRANS at the + 180's call of the descriptor's name.
TRANSIENT in the pop-up. Held here, stock's instructions run around each place. Only the unit can show: the knob drawn,
TRANSIENT fitting the pop-up.
"""
import hashlib
import shutil

import pytest
from unicorn.m68k_const import UC_M68K_REG_PC

from tests.test_hitui import HOLDER, KEPT, METHODS, PAGE, STOCK_NAME, TOP, Rig
from tools import build, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

OWN, NEXT = 0x400424c2, 0x400424c8          # the record's own picture, the test of FENR
PLAIN, DELAY_ON = 0x400701b4, mm.DEL_GFX + 8    # a plain knob's graphic; the delay's, past what ours replaces


@pytest.fixture(scope="module")
def trans(official):
    return build_main.patched_image(official.section(3), xfade=60)


def run(r, start, exits, regs, pushed=()):
    mc = r.mc
    for n in range(16):
        mc.set_reg(n, 0x1111 * (n + 1))
    for n, v in regs.items():
        mc.set_reg(n, v)
    sp = TOP - 4 * len(pushed)
    for k, v in enumerate(pushed):
        mc.w32(sp + 4 * k, v)
    mc.set_reg(15, sp)
    mc.set_stack(TOP, TOP + 0x10)
    mc.set_exits(list(exits) + [TOP + 0x10])
    mc.uc.emu_start(start, 0)
    return mc.uc.reg_read(UC_M68K_REG_PC), {n: mc.reg(n) for n in range(16)}


@pytest.mark.parametrize("machine", [44, 4, 0])
@pytest.mark.parametrize("record", [0x3f, 0x40, 0x45])
def test_del_keeps_its_own_picture_and_is_marked_on_a_sampler(trans, machine, record):
    r = Rig(trans, machine)
    mark = r.syms["trans_mark"]
    r.mc.write(mark, b"\x12\x34")
    pc, regs = run(r, mm.FLTR2_DEL, (OWN, NEXT), {2: record, 10: PAGE})
    assert pc == (OWN if record == 0x3f else NEXT) and regs[15] == TOP
    assert r.mc.read(mark, 2) == (b"\x12\x34" if record != 0x3f else b"\x00\xff" if machine == 44 else b"\x00\x00")
    assert all(regs[n] == {2: record, 10: PAGE}.get(n, 0x1111 * (n + 1)) for n in KEPT)


@pytest.mark.parametrize("marked", [True, False])
def test_the_delay_graphic_is_a_plain_knob_once_when_marked(trans, marked):
    r = Rig(trans, 44)
    mark = r.syms["trans_mark"]
    r.mc.write(mark, b"\x00\xff" if marked else b"\x00\x00")
    args = (0x1234, 0x7f00, 0x5000, 24, 34)
    pc, regs = run(r, mm.DEL_GFX, (PLAIN, DELAY_ON), {}, (0xdead0000,) + args)
    assert r.mc.read(mark, 2) == b"\x00\x00"
    if marked:
        assert pc == PLAIN and regs[15] == TOP - 24                 # the call as it came: the return, then the five
        assert all(regs[n] == 0x1111 * (n + 1) for n in KEPT)
    else:
        assert pc == DELAY_ON and regs[15] == TOP - 24 - 12           # stock's frame, d2 to d4 kept in it
        assert [r.mc.r32(regs[15] + 4 * k) for k in range(3)] == [0x3333, 0x4444, 0x5555]


@pytest.mark.parametrize("machine", [44, 4])
@pytest.mark.parametrize("record", [0x3f, 0x40])
def test_the_name_under_the_knob(trans, machine, record):
    r = Rig(trans, machine)
    pc, regs = run(r, mm.KNOB_LABEL, (mm.KNOB_LABEL + 6,), {13: PAGE}, (HOLDER, record))
    assert pc == mm.KNOB_LABEL + 6 and regs[15] == TOP - 8
    assert r.text(regs[0]) == ("TRANS" if (machine, record) == (44, 0x3f) else "DEL" if record == 0x3f else "ATK")
    assert all(regs[n] == {13: PAGE}.get(n, 0x1111 * (n + 1)) for n in KEPT)


@pytest.mark.parametrize("machine", [44, 4])
def test_the_names(trans, machine):
    r = Rig(trans, machine)
    regs, moved = r.go(mm.FLTR2_NAME, mm.FLTR2_NAME + 28, {2: 0x3f, 10: PAGE})
    assert moved == -4 and r.text(r.mc.r32(TOP - 4)) == ("TRANS" if machine == 44 else "DEL")       # a greyed knob's
    r.mc.write(STOCK_NAME, fw.sb("56c190c684dff768"))
    regs, moved = r.go(mm.POPUP_NAME - 0x0e, mm.POPUP_NAME + 6, {0: HOLDER, 2: 0x3f, 10: PAGE})
    assert moved == 0 and regs[8] == METHODS
    assert r.text(regs[4]) == ("TRANSIENT" if machine == 44 else "DEL")


def test_the_image(official_path, official, trans):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=60, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=59, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("05d83e5b")      # the spread image, as it is
    print("trans image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == trans[0]
    spans = [mm.CAVE_HITS, mm.CAVE_TRANS, (mm.FLTR2_DEL, mm.FLTR2_DEL + 6), (mm.DEL_GFX, mm.DEL_GFX + 8),
             (mm.KNOB_LABEL + 2, mm.KNOB_LABEL + 6)]
    assert not [k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
