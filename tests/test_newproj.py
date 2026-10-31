"""The newproj image (engine/phone.c, NEWPROJ): the fresh image with NEW PROJECT asking the phone, and every ask saying the
project it leaves.


NEW PROJECT is stock's Project Init job (0x40059f9e), which calls the project maker (0x4001d16a) with -1 and
neither saves nor loads; the fresh image hooked only an empty slot's load. Here, with stock's routines around it played
(test_phone's rig):
  - NEW PROJECT after the phone's hello: the maker, then an ask of project 0x3fff marked new (the bank byte + 128),
    saying the project left, a wait, and the slots the phone names; counted as a load of no project;
  - NEW PROJECT with no hello: the maker, counted, nothing asked;
  - an empty slot's new project: the maker (the project left read first), then after its save the ask, marked new,
    saying that project left;
  - LOAD PROJECT: the ask says the project it leaves, 7f 7f for one never saved;
  - the image: the fresh image's but for the phone's runs, the bank code's, the new runs and the three calls.
Emulation only."""
import shutil

import pytest

import test_fltr as F
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ASKED = ["scan", "write", "commit", "timer", "wait", "cancel", "scan", "load"]


def frame(project, bank, left, new=False):
    lo, hi = (0x7f, 0x7f) if left is None else (left & 0x7f, left >> 7)
    return bytes([0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x60, project & 0x7f, project >> 7, 0x40 if new else 0, bank, lo, hi, 0xf7])


@pytest.fixture(scope="module")
def newproj(official):
    return build_main.patched_image(official.section(3), xfade=76)


def rig(built, now_project=9, ok=1):
    r = F.rig(built, now_project=now_project, project_bank=2, now=0)
    r.stub(mm.PROJECT_MAKE, lambda m, p: r.log.append(("make", m, p if p < 0x80000000 else p - (1 << 32))))
    r.stub(r.syms["new_slots"], lambda: r.log.append(("slots",)))
    r.stub(r.syms["save_keep"], lambda m, p, g: r.log.append(("save", m, p, g)) or ok)
    r.mc.uc.ctl_flush_tb()
    return r


def call(r, name, *args):
    r.log.clear()
    return r.mc.call(r.syms[name], *[a & 0xffffffff for a in args])


def test_new_project_after_the_hello_asks_marked_new_with_the_project_left_and_loads_the_named_slots(newproj):
    r = rig(newproj)
    r.mc.w32(r.syms["phone_seen"], 1)
    call(r, "fresh_make", 0x1234, -1)
    assert [e[0] for e in r.log] == ["make", "write", "commit", "timer", "wait", "cancel", "slots"]
    assert r.log[0] == ("make", 0x1234, -1)
    assert r.log[1][1] == frame(0x3fff, 0, 9, new=True)
    assert r.var("knows_count") == 1 and r.var("knows_project") == 0x3fff
    assert r.mc.read(r.syms["phone_frame"] + 14, 1) == b"\x00"          # the mark gone after


def test_new_project_with_no_hello_is_made_and_counted_only(newproj):
    r = rig(newproj)
    call(r, "fresh_make", 0x1234, -1)
    assert r.log == [("make", 0x1234, -1)]
    assert r.var("knows_count") == 1 and r.var("knows_project") == 0x3fff


def test_an_empty_slots_new_project_asks_after_its_save_with_the_project_left(newproj):
    r = rig(newproj)
    r.mc.w32(r.syms["phone_seen"], 1)
    call(r, "fresh_make", 0x1234, 5)
    assert r.log == [("make", 0x1234, 5)] and r.var("knows_count") == 0     # nothing asked yet: the save comes first
    r.log.clear()
    assert r.mc.call(r.syms["fresh_save"], 0x1234, 5, 0x5678) == 1
    assert [e[0] for e in r.log] == ["save"] + ASKED
    assert r.log[2][1] == frame(5, 2, 9, new=True)
    assert r.var("knows_count") == 1 and r.var("knows_project") == 5


@pytest.mark.parametrize("now,left", [(9, 9), (130, 130), (-1, None)])
def test_load_project_says_the_project_it_leaves(newproj, now, left):
    r = rig(newproj, now_project=now)
    r.mc.w32(r.syms["phone_seen"], 1)
    assert call(r, "fresh_load", 0x1234, 5, 0x5678) == 7
    assert [e[0] for e in r.log] == ASKED and r.log[1][1] == frame(5, 2, left)


def test_the_image(official_path, newproj):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=76)[2]
    was = build.build(official_path, log=quiet, xfade=75)[2]
    assert new.section(7) == was.section(7) and new.section(3) == newproj[0]
    spans = [mm.CAVE_PHONE, mm.CAVE_PHONE2, mm.CAVE_PHONE3, mm.CAVE_FRESH, mm.CAVE_NEWPROJ, mm.CAVE_NEWPROJ2, mm.CAVE_BANK]
    calls = [(a + 2, a + 6) for a in mm.PROJECT_MAKE_CALLS + (mm.PROJECT_LOAD_CALL,)]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k)
             and not any(lo <= mm.BASE + k < hi for lo, hi in calls) and not pointer(k)]
    assert moved == []
    for a in mm.PROJECT_MAKE_CALLS:
        assert n[mm.off(a + 2):mm.off(a + 6)] == newproj[1]["fresh_make"].to_bytes(4, "big")
    assert n[mm.off(mm.PROJECT_LOAD_CALL + 2):mm.off(mm.PROJECT_LOAD_CALL + 6)] == newproj[1]["fresh_load"].to_bytes(4, "big")
