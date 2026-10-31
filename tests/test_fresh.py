"""The fresh image (engine/phone.c, FRESH): the destnum image with a new project asking the phone as a load does."""
import shutil

import pytest

import test_fltr as F
import test_phone as P
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ASKED = ["scan", "write", "commit", "timer", "wait", "cancel", "scan", "load"]
FRAME = [0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x60, 5, 0, 0, 2, 0xf7]


@pytest.fixture(scope="module")
def fresh(official):
    return build_main.patched_image(official.section(3), xfade=75)


def rig(built, ok=1):
    r = F.rig(built, now_project=9, project_bank=2, now=0)
    r.stub(r.syms["save_keep"], lambda m, p, g: r.log.append(("save", m, p, g)) or ok)
    r.mc.uc.ctl_flush_tb()
    return r


def made(r):
    """Stock's new project saved, through the second save call's target: (manager, project 5, progress)."""
    r.log.clear()
    return r.mc.call(r.syms["fresh_save"], 0x1234, 5, 0x5678)


def test_after_the_hello_a_new_project_is_asked_for_marked_new_and_loaded(fresh):
    r = rig(fresh)
    r.mc.w32(r.syms["phone_seen"], 1)
    assert made(r) == 1
    assert [e[0] for e in r.log] == ["save"] + ASKED
    assert r.log[0] == ("save", 0x1234, 5, 0x5678) and r.log[-1] == ("load", 0, 0x1234, 5, 0x5678)
    new = list(FRAME)
    new[14] = 0x40
    assert r.log[2][1] == bytes(new)
    assert r.var("knows_count") == 1 and r.var("knows_project") == 5 and r.var("knows_bank") == 2
    r.log.clear()
    assert r.mc.call(r.syms["knows_load"], 0x1234, 5, 0x5678) == 7  # LOAD PROJECT after it: no mark
    assert r.log[1][1] == bytes(FRAME) and r.var("knows_count") == 2


def test_with_no_hello_it_is_saved_and_counted_and_nothing_else(fresh):
    r = rig(fresh)
    assert made(r) == 1
    assert r.log == [("save", 0x1234, 5, 0x5678)]
    assert r.var("knows_count") == 1 and r.var("knows_project") == 5 and r.var("knows_bank") == 2
    F.ask(r)  # what 0x64 says now: project 5, bank 2, a load
    assert r.log == [("write", F.reply(5, 2, 1, 1000)), ("commit",)]  # (the start's id: the clock at the count)


def test_a_save_that_failed_is_all(fresh):
    r = rig(fresh, ok=0)
    r.mc.w32(r.syms["phone_seen"], 1)
    assert made(r) == 0
    assert r.log == [("save", 0x1234, 5, 0x5678)] and r.var("knows_count") == 0


def test_the_image(official_path, fresh):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=75)[2]
    was = build.build(official_path, log=quiet, xfade=74)[2]
    assert new.section(7) == was.section(7) and new.section(3) == fresh[0]
    n, o = new.section(3), was.section(3)
    lo, hi = mm.CAVE_FRESH
    call = mm.PROJECT_SAVE_CALLS[1] + 2
    outside = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not (lo <= mm.BASE + k < hi) and not (call <= mm.BASE + k < call + 4)]
    assert outside == []
    assert n[mm.off(call):mm.off(call) + 4] == fresh[1]["fresh_save"].to_bytes(4, "big")
    assert o[mm.off(call):mm.off(call) + 4] == o[mm.off(mm.PROJECT_SAVE_CALLS[0] + 2):mm.off(mm.PROJECT_SAVE_CALLS[0] + 2) + 4]  # save_keep's, as the first
