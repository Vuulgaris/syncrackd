"""The evtime tool: the fast image with the profile cutting the events and knobs stretch in five, the mixer not timed.

On request (25.1
hundredths of a block without the unit's USB audio streaming, 28.5 with; "it still lags when i try to do usb audio
over able ton"). engine/evlap.S: four of stock's calls in the stretch go to stubs that read the profile's timer into
the record's places for the stopped code's stack pointer, PC, last stack long and task, and jump on to the routine.
tools/prof_read.py reads the five parts and how often each call was made.

Held here by running the stubs with the routine played; not held: the counts on the unit.
"""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_A0

from emu.machine import Machine
from tools import build, build_main, prof_read
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TIMER, REC = 0xfc07000c, mm.CAVE_PROF[0]
AT = (16, 12, 56, 60)


def evtime(stock3):
    build_main.EVLAP = True
    try:
        return build_main.patched_image(stock3, xfade=34)
    finally:
        build_main.EVLAP = False


@pytest.fixture(scope="module")
def main(official):
    return evtime(official.section(3))


@pytest.fixture(scope="module")
def fast(official):
    return build_main.patched_image(official.section(3), xfade=34)


@pytest.mark.parametrize("k", range(4))
def test_a_lap_reads_the_timer_and_the_routine_finds_everything_as_its_caller_left_it(main, k):
    image, syms = main
    site, target = mm.EV_LAPS[k]
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x41000000, 0x10000)
    mc.map(0xfc000000, 0x100000)
    mc.write(mm.BASE, image)
    mc.write(target, b"\x4e\x75")
    seen = []

    def routine(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        seen.append((sp, [mc.r32(sp + 4 * j) for j in range(1, 4)], uc.reg_read(UC_M68K_REG_D0), uc.reg_read(UC_M68K_REG_D1),
                     uc.reg_read(UC_M68K_REG_A0)))
    mc.uc.hook_add(UC_HOOK_CODE, routine, begin=target, end=target)
    for at in AT:
        mc.w32(REC + at, 0x5555)
    mc.w32(TIMER, 0x12345)
    sp = 0x41008000
    for j, v in enumerate((0xa1, 0xa2, 0xa3)):
        mc.w32(sp + 4 + 4 * j, v)
    mc.w32(sp, 0x41009000)                      # where the routine returns to
    mc.write(0x41009000, b"\x4e\x75")
    mc.uc.reg_write(UC_M68K_REG_A7, sp)
    mc.uc.reg_write(UC_M68K_REG_D0, 0xdeadbeef)
    mc.uc.reg_write(UC_M68K_REG_D1, 0x1111)
    mc.uc.reg_write(UC_M68K_REG_A0, 0x2222)
    assert image[mm.off(site):mm.off(site) + 6] == b"\x4e\xb9" + syms["ev_lap%d" % (k + 1)].to_bytes(4, "big")
    mc.uc.emu_start(syms["ev_lap%d" % (k + 1)], 0x41009000, count=20)
    assert seen == [(sp, [0xa1, 0xa2, 0xa3], 0xdeadbeef, 0x1111, 0x2222)]
    assert [mc.r32(REC + at) for at in AT] == [0x12345 if j == k else 0x5555 for j in range(4)]


def rows(order, n=20):
    r = {name: np.full(n, 0x40001234, dtype=np.uint32) for name in prof_read.LONGS}
    for k, name in enumerate(order):
        r[name] = np.arange(n, dtype=np.uint32) * 88000 + 100 * k
    r["count"] = np.arange(n, dtype=np.uint32)
    r["rows"] = n
    return r


def test_prof_read_cuts_the_stretch_in_five_and_takes_a_lap_not_reached_as_the_one_before():
    r = rows(["entry", "s0", "sp", "pc", "s5", "task", "s1", "s2", "s3", "s4", "mix_in", "mix_out", "fed", "exit"])
    assert prof_read.laps(r) and prof_read.evlap(r) and not prof_read.split(r)
    _, parts, _, _ = prof_read.times(r)
    assert [int(parts["    " + nm][0]) for nm in prof_read.EV_NAMES] == [100] * 5
    r["s5"][:] = 0x405fcc8c                     # the third call not made: what the interrupt's start left
    _, parts, _, _ = prof_read.times(r)
    assert [int(parts["    " + nm][0]) for nm in prof_read.EV_NAMES] == [100, 100, 0, 200, 100]
    assert prof_read.ev_hits(r) == [100.0, 100.0, 0.0, 100.0]
    old = rows(["entry", "s0", "s1", "s2", "s3", "s4", "mix_in", "mix_out", "fed", "exit"])
    assert not prof_read.evlap(old)


def test_the_image(official_path, main, fast):
    quiet = lambda s: None
    build_main.EVLAP = True
    try:
        raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=34, prof=True)
    finally:
        build_main.EVLAP = False
    new, old = built.section(3), fast[0]
    assert new == main[0]
    spans = [mm.CAVE_EVLAP, mm.CAVE, mm.CAVE_SPLIT, mm.CAVE_AMUTE, mm.CAVE_ALOCK, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_PROF, mm.CAVE_FAST] + \
            [(s + 2, s + 6) for s, _ in mm.EV_LAPS]
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)] == []
    assert new[mm.off(mm.CAVE_SPLIT[0]):mm.off(mm.CAVE_SPLIT[1])] == built.section(3)[mm.off(mm.CAVE_SPLIT[0]):mm.off(mm.CAVE_SPLIT[1])]
    print("evtime image", hashlib.sha256(raw).hexdigest())
