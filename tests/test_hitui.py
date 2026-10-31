"""The hitui image: the hits image with the filter pages saying what DEL is on a sampler track.


On a sampler track DEL is the hits' threshold and the envelope does not
wait (engine/hits.c), but stock's filter page still named it DEL and drew a delay into FLTR1's picture of the envelope.

Three places of stock's are each a call of ours (engine/hits.c, HITUI): FLTR2's loop takes a knob's name, the base
turn routine takes the pop-up's name, and FLTR1's loop asks DEL's value for its picture. Held here, stock's own
instructions run around each from where it sets its stack up to past the call: on a sampler track DEL's record is
named HITS and its value for the picture is 0; on any other machine, and for any other record, all is stock's; the
stack and every register stock keeps are as stock leaves them. And the image differs from the hits image only there.

Stand-ins, as tests/test_page.py has them: the routine that gives the active track and the one that gives its machine,
the holder's name method and the routine that gives a record's value. Not held, and only the unit can show it: that
the page looks right.
"""
import hashlib
import shutil

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

RAM = 0x41000000
PAGE, METHODS, TRACKS, KIT, HOLDER, HOLDER_METHODS, FLAG = (RAM + k for k in (0x100, 0x400, 0x800, 0x900, 0xa00, 0xb00, 0xc00))
NAME_FN, VALUE_FN, STOCK_NAME = RAM + 0x1000, RAM + 0x1010, RAM + 0x1020
TOP = RAM + 0xf000
KEPT = (2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14)       # d2 to d7, a2 to a6: what a routine is to leave as it found them
NAMES = {0x3f: "DEL", 0x40: "ATK", 0x45: "FENR", 0: None}


@pytest.fixture(scope="module")
def hitui(official):
    return build_main.patched_image(official.section(3), xfade=17)


class Rig:
    def __init__(self, built, machine):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(RAM, 0x10000)
        mc.write(mm.BASE, image)
        self.machine, self.values = machine, {0x3f: 77, 0x40: 50, 0x89: 66, 0x8a: 40}
        mc.w32(PAGE, METHODS)
        mc.w32(PAGE + 116, TRACKS)
        mc.w32(PAGE + 120, KIT)
        mc.w32(HOLDER, HOLDER_METHODS)
        mc.w32(HOLDER_METHODS + 88, NAME_FN)
        self.stub(mm.ACTIVE_TRACK, lambda tracks: 3 if tracks == TRACKS else 99)
        self.stub(mm.MACHINE_OF, lambda kit, track: self.machine if (kit, track) == (KIT, 3) else 99)
        self.stub(NAME_FN, lambda holder, record: STOCK_NAME if holder == HOLDER else 0)
        self.stub(VALUE_FN, lambda page, record, flag: self.values[record] if (page, flag) == (PAGE, FLAG) else 0xbad)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            uc.reg_write(UC_M68K_REG_D0, fn(*[mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]) & 0xffffffff)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def go(self, start, stop, regs):
        """Stock's instructions from start to stop. -> the registers after, and how far the stack moved."""
        mc = self.mc
        for n in range(16):
            mc.set_reg(n, 0x1111 * (n + 1))
        for n, v in regs.items():
            mc.set_reg(n, v)
        mc.set_reg(15, TOP)
        mc.set_stack(TOP, RAM + 0xfff0)
        mc.set_exits([stop, RAM + 0xfff0])
        mc.run(start, stop)
        return {n: mc.reg(n) for n in range(16)}, mc.reg(15) - TOP

    def text(self, at):
        got = self.mc.read(at, 16)
        return got[:got.index(0)].decode()


@pytest.mark.parametrize("machine", [44, 4, 0])
@pytest.mark.parametrize("record", [0x3f, 0x40, 0x45, 600])
def test_fltr2_names_del_hits_on_a_sampler_and_every_other_knob_as_stock(hitui, machine, record):
    r = Rig(hitui, machine)
    regs, moved = r.go(mm.FLTR2_NAME, mm.FLTR2_NAME + 28, {2: record, 10: PAGE})
    assert moved == -4                                          # one long pushed, as stock's
    want = "HITS" if (machine, record) == (44, 0x3f) else NAMES[record if record < 505 else 0] or r.text(r.mc.r32(mm.UI_RECORDS + 0x30))
    assert r.text(r.mc.r32(TOP - 4)) == want
    assert all(regs[n] == (record if n == 2 else PAGE if n == 10 else 0x1111 * (n + 1)) for n in KEPT)


@pytest.mark.parametrize("machine", [44, 4])
@pytest.mark.parametrize("record", [0x3f, 0x40])
def test_the_pop_up_names_del_hits_on_a_sampler(hitui, machine, record):
    r = Rig(hitui, machine)
    r.mc.write(STOCK_NAME, fw.sb("56c190c684dff768"))
    regs, moved = r.go(mm.POPUP_NAME - 0x0e, mm.POPUP_NAME + 6, {0: HOLDER, 2: record, 10: PAGE})
    assert moved == 0
    assert r.text(regs[4]) == ("HITS" if (machine, record) == (44, 0x3f) else "DEL")       # the name the pop-up is given, in d4
    assert regs[8] == METHODS                                   # a0: the page's methods, as stock leaves it
    assert all(regs[n] == {2: record, 4: regs[4], 10: PAGE}.get(n, 0x1111 * (n + 1)) for n in KEPT)


@pytest.mark.parametrize("machine", [44, 4])
@pytest.mark.parametrize("start, atk, dl", [(mm.FLTR1_DEL - 0x14, 0x40, 0x3f), (mm.FLTR1_DEL - 0x28, 0x8a, 0x89)])
def test_fltr1s_picture_has_no_delay_on_a_sampler(hitui, machine, start, atk, dl):
    """From where FLTR1's loop asks ATK's value, on the digital tracks' page and on the analog tracks' (page 11)."""
    r = Rig(hitui, machine)
    regs, moved = r.go(start, mm.FLTR1_DEL + 6, {3: FLAG, 10: PAGE, 11: VALUE_FN})
    assert moved == 0
    assert regs[4] == r.values[atk]                             # d4: ATK's value, stock's
    assert regs[0] == (0 if (machine, dl) == (44, 0x3f) else r.values[dl])     # d0: DEL's, for the picture
    assert all(regs[n] == {3: FLAG, 4: regs[4], 10: PAGE, 11: VALUE_FN}.get(n, 0x1111 * (n + 1)) for n in KEPT)


def test_the_image(official_path, official, hitui):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=17, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=16, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("27af79e2")      # the hits image, as it is
    new, old = built.section(3), was.section(3)
    assert new == hitui[0]
    spans = [mm.CAVE_HITS, (mm.FILTER_ENV_CALL + 2, mm.FILTER_ENV_CALL + 6), (mm.FLTR2_NAME, mm.FLTR2_NAME + 28),
             (mm.FLTR1_DEL, mm.FLTR1_DEL + 6), (mm.POPUP_NAME, mm.POPUP_NAME + 6)]
    assert not [k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
