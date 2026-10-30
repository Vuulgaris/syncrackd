"""The wipe image (engine/phone.c, WIPE): the newproj image with the unit emptying the slots the phone names.

On the unit (2026-10-27, the phone app's log) the phone's clear and every write after it went unanswered while NEW
PROJECT's job waited on the phone, its reads served; then the unit stayed on INITIALIZING PROJECT. On request
. Here, with stock's routines
around it played (test_phone's rig):
  - 0x6A while a job waits: the slots to empty, given to the wait as the done frame's are; not while none waits;
  - NEW PROJECT: after the wait each named slot's first sector is written with zeros, the headers read again, then the
    slots loaded; LOAD PROJECT the same before the load, but only on the bank the phone was asked about;
  - the image: the newproj image's but for the phone's runs, the new runs and the SysEx entry.
Emulation only."""
import shutil

import pytest

import test_fltr as F
import test_phone as P
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STORE_WRITE = 0x40111628
SLOTS = (0, 2, 33, 63)
MASK = sum(1 << s for s in SLOTS)


@pytest.fixture(scope="module")
def wipe(official):
    return build_main.patched_image(official.section(3), xfade=77)


def rig(built, project_bank=2, now=0, answer=True):
    """The phone's 0x6A comes while the job waits (the wait's stub puts what wipe_sysex would)."""
    r = F.rig(built, now_project=9, project_bank=project_bank, now=now)
    mc = r.mc
    mc.map(0x4d94f000, 0x1000)                  # the zeros' place: keeptakes.c's SLOT_AT
    r.stub(mm.PROJECT_MAKE, lambda m, p: r.log.append(("make",)))
    r.stub(r.syms["new_slots"], lambda: r.log.append(("slots", mc.r32(r.syms["phone_mask"]), mc.r32(r.syms["phone_mask"] + 4))))
    r.stub(STORE_WRITE, lambda store, sector, n, src: r.log.append(("zero", sector, n, mc.read(src, n) == bytes(n))) or 0)

    def wait(sem):                              # (the rig's own hook on the wait logs it)
        if answer:
            mc.w32(r.syms["phone_mask"], MASK & 0xffffffff)
            mc.w32(r.syms["phone_mask"] + 4, MASK >> 32)
            mc.w32(r.syms["wipe_on"], 1)
    r.stub(P.KERNEL_WAIT, wait)
    mc.w32(r.syms["phone_seen"], 1)
    mc.uc.ctl_flush_tb()
    return r


def zeroed(r):
    return [e[1] for e in r.log if e[0] == "zero" and e[2] == 512 and e[3]]


def test_0x6a_while_a_job_waits_names_the_slots_to_empty_and_ends_the_wait(wipe):
    r = F.rig(wipe)
    r.mc.w32(r.syms["phone_state"], 1)
    data, n = r.frame(0x6a, MASK, 18)
    r.log.clear()
    r.mc.call(r.syms["wipe_sysex"], data, n, 2)
    assert r.log == [("give",)]
    assert r.var("wipe_on") == 1 and r.var("phone_answer") == 1
    assert (r.mc.r32(r.syms["phone_mask"]), r.mc.r32(r.syms["phone_mask"] + 4)) == (MASK & 0xffffffff, MASK >> 32)


def test_0x6a_with_no_wait_is_stocks_and_nothing_is_marked(wipe):
    r = F.rig(wipe)
    data, n = r.frame(0x6a, MASK, 18)
    r.log.clear()
    r.mc.call(r.syms["wipe_sysex"], data, n, 2)
    assert [e[0] for e in r.log] == ["handle"] and r.var("wipe_on") == 0


def test_new_project_zeroes_the_named_slots_headers_reads_the_headers_and_loads_them(wipe):
    r = rig(wipe)
    r.log.clear()
    r.mc.call(r.syms["fresh_make"], 0x1234, 0xffffffff)
    kinds = [e[0] for e in r.log]
    assert kinds == ["make", "write", "commit", "timer", "wait", "cancel"] + ["zero"] * len(SLOTS) + ["scan", "slots"]
    assert zeroed(r) == [8192 + 2048 * s for s in SLOTS]
    assert r.var("wipe_on") == 0


def test_with_no_empty_slots_nothing_is_written(wipe):
    r = rig(wipe, answer=False)
    r.log.clear()
    r.mc.call(r.syms["fresh_make"], 0x1234, 0xffffffff)
    assert "zero" not in [e[0] for e in r.log] and r.log[-1][0] == "slots"


def test_load_project_empties_them_before_the_load_on_the_bank_asked_about(wipe):
    r = rig(wipe, project_bank=0, now=0)
    r.log.clear()
    assert r.mc.call(r.syms["fresh_load"], 0x1234, 5, 0x5678) == 7
    kinds = [e[0] for e in r.log]
    assert kinds == ["write", "commit", "timer", "wait", "cancel"] + ["zero"] * len(SLOTS) + ["scan", "load"]
    assert zeroed(r) == [8192 + 2048 * s for s in SLOTS]


def test_load_project_onto_another_bank_empties_nothing(wipe):
    r = rig(wipe, project_bank=2, now=0)        # the wait on bank 2, the drive put back on 0 before the load
    r.log.clear()
    assert r.mc.call(r.syms["fresh_load"], 0x1234, 5, 0x5678) == 7
    assert "zero" not in [e[0] for e in r.log] and r.log[-1][0] == "load" and r.var("wipe_on") == 0


def test_the_image(official_path, wipe):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=77)[2]
    was = build.build(official_path, log=quiet, xfade=76)[2]
    assert new.section(7) == was.section(7) and new.section(3) == wipe[0]
    spans = [mm.CAVE_PHONE, mm.CAVE_PHONE2, mm.CAVE_PHONE3, mm.CAVE_FRESH, mm.CAVE_NEWPROJ, mm.CAVE_NEWPROJ2, mm.CAVE_WIPE, mm.CAVE_WIPE2]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k) and not pointer(k)]
    assert moved == []
    j = mm.off(mm.SYSEX_IN_JMP + 2)
    assert n[j:j + 4] == wipe[1]["wipe_sysex"].to_bytes(4, "big")
