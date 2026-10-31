"""The cut image: the prewas image with the always-on per-block costs that change nothing heard taken out.


Three of ours run every block
whatever the pattern:
  - the allright image's audio CPU: both right-channel transfers every block and 1 KB more into the window. It did
    not help, so section 7 is the nodiv image's again: the transfers for stereo samples only.
  - the profile: a second frame, an rte and twenty stores a block with PROF off. engine/prof.S, CUT: the interrupt's
    hook goes to prof_gate (in the copies' run), which goes on to the record only with prof_on set.
  - the profile's laps (engine/rightdma.c, LAP) and the mixer split (engine/mixlink.c, MIXSPLIT), tools: left out,
    stock's mixer called straight. A PROF take still gives the interrupt's whole and its stretches.

Held here: section 7 is the nodiv image's; the gate with the profile off leaves the stack and every register as
stock's first two instructions do and touches no record, and with it on goes to the profile; the mixer is shown what
the prewas image shows it; nothing else changed.
Not held: the lag.
"""
import hashlib
import shutil

import pytest
from unicorn.m68k_const import UC_M68K_REG_A7

import test_fast as F
import test_nodiv as N
from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STOCK = 0x400a38d6                  # the per-block routine's third instruction


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=41)


@pytest.fixture(scope="module")
def prewas(official):
    return build_main.patched_image(official.section(3), xfade=40)


def entry(image, start, stops, prof_on=None, at=None):
    """Run the interrupt's start from `start` with known registers. -> (pc, registers, the stack's bytes, record)."""
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x41000000, 0x10000)
    mc.write(mm.BASE, image)
    if prof_on is not None:
        mc.w32(at, prof_on)
    for n in range(15):
        mc.set_reg(n, 0x11110000 + 0x111 * n)
    sp = 0x41008000
    mc.uc.reg_write(UC_M68K_REG_A7, sp)
    mc.write(sp - 256, bytes(range(256)))
    mc.set_exits(stops)
    mc.uc.emu_start(start, 0)
    from unicorn.m68k_const import UC_M68K_REG_PC
    return (mc.uc.reg_read(UC_M68K_REG_PC), [mc.reg(n) for n in range(16)], bytes(mc.read(sp - 256, 512)),
            bytes(mc.read(mm.CAVE_PROF[0], mm.PROF_RECORD)))


def test_the_hook_goes_to_the_gate(main):
    image, syms = main
    o = mm.off(mm.BLOCK_IRQ)
    assert image[o:o + 6] == b"\x4e\xf9" + syms["prof_gate"].to_bytes(4, "big")
    assert mm.CAVE_PRE[0] <= syms["prof_gate"] < mm.CAVE_PRE[1]


def test_with_the_profile_off_the_gate_is_stocks_first_two_instructions(main, official):
    image, syms = main
    got = entry(image, syms["prof_gate"], [STOCK, syms["prof_irq"]], 0, syms["prof_on"])
    want = entry(official.section(3), mm.BLOCK_IRQ, [STOCK])
    assert got[0] == want[0] == STOCK
    assert got[1:3] == want[1:3]
    assert got[3] == image[mm.off(mm.CAVE_PROF[0]):mm.off(mm.CAVE_PROF[0]) + mm.PROF_RECORD]      # the record not touched


def test_with_the_profile_on_the_gate_goes_to_the_profile_as_it_came(main):
    image, syms = main
    pc, regs, stack, _ = entry(image, syms["prof_gate"], [STOCK, syms["prof_irq"]], 1, syms["prof_on"])
    assert pc == syms["prof_irq"]
    assert regs[:15] == [0x11110000 + 0x111 * n for n in range(15)] and regs[15] == 0x41008000
    assert stack == bytes(range(256)) + stack[256:]


@pytest.fixture(scope="module")
def rigs(main, prewas):
    return F.rig(main), F.rig(prewas)


@pytest.mark.parametrize("case", range(len(N.CASES)))
def test_the_mixer_is_shown_what_the_prewas_image_shows_it(rigs, case):
    cut, old = rigs
    got, _ = F.scene(cut, seed=6, **N.CASES[case])
    want, _ = F.scene(old, seed=6, **N.CASES[case])
    assert got == want and got[0] == 0x8000DBD0


def test_the_image(official_path, official, main, prewas):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=41, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=40, prof=True)
    nodiv_raw, _, nodiv, _, _ = build.build(official_path, log=quiet, xfade=38, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("dafee1e7")      # the prewas image, as it is
    assert hashlib.sha256(nodiv_raw).hexdigest().startswith("13474a00")    # the nodiv image, as it is
    assert built.section(7) == nodiv.section(7) != was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == prewas[0]
    for lo, hi in (mm.CAVE_SPLIT, mm.CAVE_LAP):                            # the split's and the laps' runs are stock's again
        assert new[mm.off(lo):mm.off(hi)] == official.section(3)[mm.off(lo):mm.off(hi)]
    spans = [mm.CAVE_LINK2, mm.CAVE_SPLIT, mm.CAVE_LAP, mm.CAVE_DMA, mm.CAVE_DMA2, mm.CAVE_COPY, mm.CAVE_PRE, mm.CAVE_PROF,
             mm.CAVE_FAST, mm.CAVE_SRR, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_AMUTE, mm.CAVE_ALOCK]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
             and not moved(k)]
    assert stray == []
    print("cut image", hashlib.sha256(raw).hexdigest())
