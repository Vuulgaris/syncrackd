"""The mixtime image, a tool: the ring image with the profile splitting its mixer stretch into stock's mixer and our links."""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build, build_main, prof_read
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TIMER, MIXER, REC = 0xfc07000c, 0x4008f242, mm.CAVE_PROF[0]


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=33)


def test_mix_timed_reads_the_timer_around_stocks_mixer_and_hands_its_answer_back(main):
    image, syms = main
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x41000000, 0x10000)
    mc.map(0xfc000000, 0x100000)
    mc.write(mm.BASE, image)
    mc.write(MIXER, b"\x4e\x75")
    seen = []

    def mixer(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        seen.append(([mc.r32(sp + 4 + 4 * k) for k in range(3)], mc.r32(REC + 36)))
        mc.w32(TIMER, 222)
        uc.reg_write(UC_M68K_REG_D0, 0x55)
    mc.uc.hook_add(UC_HOOK_CODE, mixer, begin=MIXER, end=MIXER)
    mc.set_stack(0x41008000, 0x41009000)
    mc.w32(TIMER, 111)
    assert mc.call(syms["mix_timed"], 0x1111, 0x2222, 0x3333) == 0x55
    assert seen == [([0x1111, 0x2222, 0x3333], 111)]
    assert mc.r32(REC + 36) == 111 and mc.r32(REC + 56) == 222


def test_the_link_calls_stocks_mixer_through_it(main, official):
    image, syms = main
    run = image[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])]
    assert run.count(b"\x4e\xb9" + syms["mix_timed"].to_bytes(4, "big")) == 1 and fw.sb("358fa4370da856261746") not in run
    assert mm.CAVE_SPLIT[0] <= syms["mix_timed"] < mm.CAVE_SPLIT[1]


def rows(order):
    """Records whose timer readings come in the given order of names, one count apart, 20 blocks in a row."""
    r = {n: np.zeros(20, dtype=np.uint32) for n in prof_read.LONGS}
    for k, n in enumerate(order):
        r[n] = np.arange(20, dtype=np.uint32) * 88000 + 100 * k
    r["count"] = np.arange(20, dtype=np.uint32)
    r["rows"] = 20
    return r


def test_prof_read_knows_the_layout_by_where_the_readings_lie():
    new = rows(["entry", "s1", "s2", "s3", "s4", "mix_in", "s0", "s5", "mix_out", "fed", "exit"])
    old = rows(["entry", "s0", "s1", "s2", "s3", "s4", "mix_in", "mix_out", "fed", "exit"])
    assert prof_read.split(new) and not prof_read.laps(new)
    assert prof_read.laps(old) and not prof_read.split(old)
    _, parts, _, _ = prof_read.times(new)
    assert [int(parts[k][0]) for k in ("  our links before stock's mixer", "  stock's mixer", "  our links after it")] == [100, 100, 100]


def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=33, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=32, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("e0bf856c")  # the ring image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE, mm.CAVE_SPLIT]
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)] == []
    print("mixtime image", hashlib.sha256(raw).hexdigest())
