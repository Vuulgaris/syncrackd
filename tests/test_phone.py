"""The phone image: the six image's main CPU with the unit asking the phone at LOAD PROJECT.

The maintainer, 2026-10-15: piece 7 of the phone app, "go", and for what the phone's answer carries "only the changed
slots". engine/phone.c: before stock's load the unit points the drive routines at the project's bank, asks the phone
(a frame of ours through the unit's own SysEx sink), waits on the kernel's wait with a timer's callback as the timeout,
puts the bank back, and calls the load; a frame of the phone's through the SysEx entry's one jump gives the wait and
carries the slots it wrote, which the loader (engine/keeptakes.c, PHONE) loads whether or not the audio CPU holds a take.

Stand-ins for what emulation does not run, as tests/test_hitui.py has them: the kernel's wait and give, the timer
table, the SysEx sink's vtable, the store's reads and the load itself. They prove the routines around them; whether
the MIDI task runs while the job waits, and how long the first timer's count is, only the unit shows.
"""
import hashlib
import shutil

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

RAM = 0x41000000
VT, STORE, SEC = RAM + 0x100, RAM + 0x200, RAM + 0x1000
SINK, SINK_MADE, CLOCK = 0x4449c51c, 0x4449c808, 0xfc07000c
BANK_NOW = 0x40196aba
KERNEL_WAIT, KERNEL_GIVE, TIMER_SET, TIMER_CANCEL = 0x40001792, 0x400018d4, 0x40002de8, 0x40002ea4
RPC_HANDLE, SAMPLE_STORE, STORE_READ, SCAN_ALL = 0x40109d0c, 0x4016f292, 0x401100d4, 0x401115ea
MAGIC = 0x42414e4b


@pytest.fixture(scope="module")
def phone(official):
    return build_main.patched_image(official.section(3), xfade=22)


class Rig:
    def __init__(self, built, project_bank=2, now=0):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(RAM, 0x10000)
        mc.map(0x44400000, 0x100000)
        mc.map(0xfc000000, 0x100000)
        mc.write(mm.BASE, image)
        self.log = []
        mc.w32(BANK_NOW, now)
        mc.w32(SINK, VT)
        mc.w32(SINK_MADE, 1)
        mc.w32(CLOCK, 1000)
        mark = MAGIC.to_bytes(4, "big") + (~MAGIC & 0xffffffff).to_bytes(4, "big") + now.to_bytes(4, "big") + bytes([project_bank if k == 5 else 0xff for k in range(128)])
        self.mark = mark
        self.stub(SAMPLE_STORE, lambda: STORE)
        self.stub(STORE_READ, lambda store, sector, nbytes, where: self.store_read(where))
        self.stub(SCAN_ALL, lambda store: self.log.append(("scan", mc.r32(BANK_NOW))))
        self.stub(KERNEL_WAIT, lambda sem: self.log.append(("wait", mc.r32(BANK_NOW))))
        self.stub(KERNEL_GIVE, lambda sem: self.log.append(("give",)))
        self.stub(TIMER_SET, lambda fn, mask: self.log.append(("timer", fn, mask)))
        self.stub(TIMER_CANCEL, lambda fn: self.log.append(("cancel", fn)))
        self.stub(RPC_HANDLE, lambda data, n, iface: self.log.append(("handle", data, n, iface)) or 0)
        self.stub(self.syms["load_keep"], lambda m, p, g: self.log.append(("load", mc.r32(BANK_NOW), m, p, g)) or 7)
        mc.w32(VT + 12, RAM + 0x300)
        mc.w32(VT + 16, RAM + 0x310)
        self.stub(RAM + 0x300, lambda sink: self.log.append(("commit",)))
        self.stub(RAM + 0x310, lambda sink, data, n: self.log.append(("write", mc.read(data, n))) or 0)
        mc.uc.ctl_flush_tb()
        mc.set_stack(RAM + 0xf000, RAM + 0xfff0)

    def store_read(self, where):
        self.mc.write(where, self.mark)
        return 0

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            uc.reg_write(UC_M68K_REG_D0, (fn(*[mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]) or 0) & 0xffffffff)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def var(self, name):
        return self.mc.r32(self.syms[name])

    def frame(self, ident, mask=0, n=18):
        """The packed message after the header and before the f7, as the unit's SysEx entry hands it on."""
        m = [0, 1, 0, 0, ident] + [((mask & 0xffffffff) >> (7 * k)) & 0x7f for k in range(5)] + [((mask >> 32) >> (7 * k)) & 0x7f for k in range(5)]
        out = []
        for g in range(0, len(m), 7):
            out += [0] + m[g:g + 7]
        data = bytes(out)[:n]
        self.mc.write(RAM + 0x800, data)
        return RAM + 0x800, len(data)


def mask_of(slots):
    return sum(1 << s for s in slots)


def test_a_load_without_a_phone_goes_straight_to_stock_with_nothing_sent_or_waited(phone):
    r = Rig(phone)
    r.mc.w32(SINK_MADE, 0)
    assert r.mc.call(r.syms["phone_load"], 0x1234, 5, 0x5678) == 7
    assert r.log == [("load", 0, 0x1234, 5, 0x5678)]


def test_the_load_asks_the_phone_waits_and_loads_with_the_bank_put_back(phone):
    r = Rig(phone, project_bank=2, now=0)
    assert r.mc.call(r.syms["phone_load"], 0x1234, 5, 0x5678) == 7
    kinds = [e[0] for e in r.log]
    assert kinds == ["scan", "write", "commit", "timer", "wait", "cancel", "scan", "load"]
    assert r.log[0] == ("scan", 2)                  # the drive routines are pointed at the project's bank while the phone works
    assert r.log[4] == ("wait", 2)
    assert r.log[6] == ("scan", 0)                  # and back before stock's load
    assert r.log[7] == ("load", 0, 0x1234, 5, 0x5678)
    assert r.log[3] == ("timer", r.syms["tick"] if "tick" in r.syms else r.log[3][1], 0x20)
    data = r.log[1][1]
    assert data == bytes([0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x60, 5, 0, 0, 2, 0xf7])


def test_a_project_on_the_loaded_bank_switches_nothing(phone):
    r = Rig(phone, project_bank=1, now=1)
    r.mc.call(r.syms["phone_load"], 1, 5, 0)
    assert [e[0] for e in r.log] == ["write", "commit", "timer", "wait", "cancel", "load"]


def test_a_project_the_mark_does_not_know_is_on_bank_0(phone):
    r = Rig(phone, project_bank=2, now=1)
    r.mc.call(r.syms["phone_load"], 1, 6, 0)           # project 6's byte is 0xff
    assert r.log[1][1][15] == 0 and r.log[0] == ("scan", 0)


def test_the_phones_done_gives_the_wait_with_the_slots_it_wrote_and_is_not_handed_on(phone):
    r = Rig(phone)
    slots = (0, 5, 31, 32, 63)
    r.mc.w32(r.syms["phone_state"], 1)
    data, n = r.frame(0x61, mask_of(slots))
    r.mc.call(r.syms["phone_sysex"], data, n, 2)
    assert r.log == [("give",)]
    assert r.var("phone_mask") == mask_of(slots) & 0xffffffff
    assert r.mc.r32(r.syms["phone_mask"] + 4) == mask_of(slots) >> 32
    assert r.var("phone_answer") == 1


def test_working_frames_renew_the_wait_and_lengthen_it(phone):
    r = Rig(phone)
    r.mc.w32(r.syms["phone_state"], 1)
    r.mc.w32(CLOCK, 777)
    data, n = r.frame(0x62, 0, 8)
    r.mc.call(r.syms["phone_sysex"], data, n, 2)
    assert r.log == [] and r.var("phone_start") == 777 and r.var("phone_limit") == 528000000


def test_our_ids_are_taken_and_not_acted_on_when_nothing_waits(phone):
    r = Rig(phone)
    data, n = r.frame(0x61, mask_of([3]))
    r.mc.call(r.syms["phone_sysex"], data, n, 2)
    assert r.log == [] and r.var("phone_mask") == 0


def test_every_other_frame_goes_on_to_stock_as_it_came(phone):
    r = Rig(phone)
    r.mc.w32(r.syms["phone_state"], 1)
    data, n = r.frame(0x53, 0, 12)
    r.mc.call(r.syms["phone_sysex"], data, n, 4)
    assert r.log == [("handle", data, n, 4)]


def test_the_timeout_gives_only_after_its_limit(phone):
    r = Rig(phone)
    r.mc.w32(r.syms["phone_start"], 1000)
    r.mc.w32(r.syms["phone_limit"], 264000000)
    r.mc.w32(CLOCK, 1000 + 264000000 - 1)
    r.mc.call(r.syms["tick"])
    assert r.log == []
    r.mc.w32(CLOCK, 1000 + 264000000)
    r.mc.call(r.syms["tick"])
    assert r.log == [("give",)]


def test_the_mask_is_at_the_place_the_loader_reads_it(phone):
    assert phone[1]["phone_mask"] == 0x40126f08 == mm.CAVE_PHONE[0]


def test_the_image(official_path, official, phone):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=22, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=20, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("d7bd3348")      # the six image, as it is
    new, old = built.section(3), was.section(3)
    assert new == phone[0]
    spans = [mm.CAVE_PHONE, mm.CAVE_PHONE2, (mm.SYSEX_IN_JMP + 2, mm.SYSEX_IN_JMP + 6),
             (mm.PROJECT_LOAD_CALL + 2, mm.PROJECT_LOAD_CALL + 6), mm.CAVE_KEEP, mm.CAVE_BANK]

    def in_caves(v):
        return any(a <= v < b for a, b in (mm.CAVE_KEEP, mm.CAVE_BANK))

    def pointer_into_ours(k):
        # the code of the keep and bank runs is longer with PHONE, so a place that names one of its routines names it
        # at another address: a long that held an address in those runs and still does
        return any(in_caves(int.from_bytes(old[w:w + 4], "big")) and in_caves(int.from_bytes(new[w:w + 4], "big"))
                   for w in range(max(0, k - 3), k + 1))

    assert not [k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
                and not pointer_into_ours(k)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
