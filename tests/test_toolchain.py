"""Phase 0: the toolchain works. No firmware needed."""
import shutil
import subprocess

import pytest

CC = shutil.which("m68k-elf-gcc") or shutil.which("m68k-linux-gnu-gcc")
OBJDUMP = shutil.which("m68k-elf-objdump") or shutil.which("m68k-linux-gnu-objdump")

MCPU = "-mcpu=54418"

C_SRC = """
int mac_dot(const short *a, const short *b, int n)
{
    int acc = 0;
    while (n--)
        acc += *a++ * *b++;
    return acc;
}
"""

# EMAC and ColdFire-only instructions the stock engine uses. The audio CPU is MCF5441x class (ISA C + EMAC), see
# docs/FINDINGS.md.
ASM_SRC = """
    .text
    .globl emac_probe
emac_probe:
    move.l  #0xa0,%d0
    move.l  %d0,%macsr
    clr.l   %d0
    move.l  %d0,%acc0
    mac.l   %d1,%d2,%acc0
    move.l  %acc0,%d0
    mvs.w   %d1,%d2
    mvz.b   %d1,%d2
    ff1.l   %d0
    sats.l  %d0
    rts
"""


def _build(tmp_path, name, src, lang):
    out = tmp_path / (name + ".o")
    subprocess.run(
        [CC, MCPU, "-O2", "-x", lang, "-c", "-", "-o", str(out)],
        input=src.encode(), check=True,
    )
    return subprocess.run(
        [OBJDUMP, "-d", str(out)], check=True, capture_output=True, text=True
    ).stdout


@pytest.mark.skipif(not CC, reason="no ColdFire cross-compiler")
def test_compile_c_for_coldfire(tmp_path):
    dis = _build(tmp_path, "c", C_SRC, "c")
    assert "<mac_dot>:" in dis and "rts" in dis


@pytest.mark.skipif(not CC, reason="no ColdFire cross-compiler")
def test_assemble_emac(tmp_path):
    dis = _build(tmp_path, "s", ASM_SRC, "assembler")
    for mnemonic in ("macl", "mvsw", "mvzb", "ff1", "satsl"):
        assert mnemonic in dis, mnemonic


def test_unicorn_runs_m68k():
    from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
    from unicorn.m68k_const import UC_M68K_REG_D0

    base = 0x40000400
    code = bytes.fromhex("702a" "5280")  # moveq #42,d0 ; addq.l #1,d0
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(base & ~0xFFF, 0x1000)
    uc.mem_write(base, code)
    uc.emu_start(base, base + len(code))
    assert uc.reg_read(UC_M68K_REG_D0) == 43


def test_capstone_and_numpy_import():
    import capstone  # noqa: F401
    import numpy  # noqa: F401
