"""Phase 2: every address in tools/audiomap.py, checked against the pinned section 7."""
import pytest

from tools import audiomap as m


@pytest.fixture(scope="module")
def img(official):
    return official.section(7)


def op32(img, insn_addr):
    """32-bit operand of an instruction with a 2-byte opcode."""
    return m.u32(img, insn_addr + 2)


def test_image_and_entry(img):
    assert len(img) == m.SIZE
    assert m.u32(img, m.BASE) == m.ENTRY
    assert op32(img, 0x4000107a) == m.STACK_TOP  # movea.l #,sp at entry


def test_boot_copies_and_bss(img):
    assert op32(img, 0x400004be) == m.SRAM_LO_SRC[0]
    assert op32(img, 0x400004c4) == m.SRAM
    assert op32(img, 0x400004d0) == m.SRAM_LO_SRC[1]
    assert op32(img, 0x400004de) == m.SRAM_HI  # zero fill up to here
    assert op32(img, 0x400004e6) == m.SRAM_HI_SRC[0]
    assert op32(img, 0x400004ec) == m.SRAM_HI
    assert op32(img, 0x400004f8) == m.SRAM_HI_SRC[1] == m.IMAGE_END
    assert op32(img, 0x40000506) == m.SRAM_END
    assert op32(img, 0x4000051a) == m.BSS[0]
    assert op32(img, 0x40000520) == m.BSS[1]


def test_voice_loop_operands(img):
    assert op32(img, 0x4000433c) == 0xA0  # MACSR during the loop
    assert op32(img, 0x400044d2) == 0x20  # MACSR after
    assert op32(img, 0x400043aa) == m.VOICES
    assert op32(img, 0x400043be) == m.VOICE_SIZE
    assert op32(img, 0x400043c4) == m.PARAM_STRIDE
    assert op32(img, 0x400043b0) == m.UPDATE_TABLE
    assert op32(img, 0x40004406) == m.TYPE_TO_ENGINE
    assert op32(img, 0x400044aa) == m.RENDER_TABLE
    assert op32(img, 0x40004474) + 4 * op32(img, 0x4000448c) == m.PMOD
    # the audio interrupt calls it with these buffers
    assert op32(img, 0x40000a28) == m.PARAM_BUF
    assert op32(img, 0x40000a2e) == m.OUT_BUF
    assert op32(img, 0x40000a34) == m.VOICE_LOOP
    assert m.OUT_BUF == m.VOICES + m.N_VOICES * m.VOICE_SIZE
    assert m.PARAM_BUF == m.OUT_BUF + m.N_VOICES * m.OUT_STRIDE


def test_engine_tables(img):
    table = img[m.off(m.TYPE_TO_ENGINE):m.off(m.TYPE_TO_ENGINE) + 46]
    want = [0] * 46
    for engine, mtype in enumerate(m.TYPE_OF_ENGINE):
        want[mtype] = engine
    assert list(table) == want
    upd = [m.u32(img, m.UPDATE_TABLE + 4 * i) for i in range(m.N_ENGINES)]
    ren = [m.u32(img, m.RENDER_TABLE + 4 * i) for i in range(m.N_ENGINES)]
    assert m.RENDER_TABLE + 4 * m.N_ENGINES == m.UPDATE_TABLE
    assert m.UPDATE_TABLE + 4 * m.N_ENGINES == m.TYPE_TO_ENGINE
    assert (upd[6], ren[6]) == (0x40008074, 0x4000847a)  # SD VINTAGE, as in the notes
    assert (upd[11], ren[11]) == (m.TWIN_UPDATE, m.TWIN_RENDER)
    code = range(m.BASE, m.CODE_END)
    assert all(a in code and a % 2 == 0 for a in upd + ren)
    assert len(set(upd)) == len(set(ren)) == m.N_ENGINES


def test_voice_init(img):
    assert op32(img, 0x40000fd8) == m.VOICES + 0x56c
    assert op32(img, 0x40000fe0) == m.NOISE_SEED
    assert op32(img, 0x40000fe6) == m.VOICE_RESET
    assert op32(img, 0x40000ff4) == m.VOICE_TMP
    assert op32(img, 0x4000100e) == 0x30 * m.N_VOICES


def test_twinshot_and_pool(img):
    assert op32(img, 0x400097f6) == m.SAMPLE_PITCH
    assert op32(img, 0x40009a92) == m.SAMPLE_PLAY
    assert op32(img, 0x40009aa0) == m.TWIN_BUF_A
    assert op32(img, 0x40009aac) == m.TWIN_BUF_B
    assert op32(img, 0x40009ac4) == m.TWIN_FILTER
    assert op32(img, 0x40009acc) == m.ENVELOPE
    assert op32(img, 0x40009b04) == m.TWIN_MIX
    assert op32(img, 0x40009972) == m.SLOT_LEN
    assert op32(img, 0x4000997e) == m.SLOT_PTR
    assert op32(img, 0x40009986) == m.SLOT_MAX_FRAMES
    # pool load, clear, and the walk that builds the slot table
    assert op32(img, 0x40000cdc) == m.POOL
    assert op32(img, 0x40000ce2) == m.POOL_SIZE
    assert op32(img, 0x40000d7e) == m.POOL_SIZE
    assert op32(img, 0x40000d84) == m.POOL
    assert op32(img, 0x40000d12) == m.POOL
    assert op32(img, 0x40000d58) == m.POOL + 4  # first frame follows a u32 length
    assert op32(img, 0x40000d30) == m.SLOT_LEN
    assert op32(img, 0x40000d2a) == m.SLOT_PTR
    assert op32(img, 0x40000d6c) == 8 * m.SLOTS
    assert m.POOL + m.POOL_SIZE == m.SLOT_LEN - 4
    # the chunk copy in init: memcpy(POOL + (index << 11), 0x800, 0x800)
    assert op32(img, 0x40000fba) == m.POOL
    assert op32(img, 0x40000fae) >> 16 == op32(img, 0x40000fb2) >> 16 == m.POOL_CHUNK  # pea (xxx).W
    # the SPI reader has no caller: its address appears nowhere as a 32-bit value
    assert img.find(m.POOL_LOAD.to_bytes(4, "big")) < 0
    assert m.SLOT_LEN + 8 * m.SLOTS <= m.BSS[1]


def test_free_sdram_is_unreferenced(img):
    """No 32-bit operand in the code area points into the free region."""
    lo, hi = m.FREE_SDRAM
    import re
    import shutil
    if not shutil.which("m68k-elf-objdump"):
        pytest.skip("no objdump")
    import os
    import tempfile
    from tools import disasm
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(img)
    try:
        lst = disasm.disasm(f.name, m.BASE, m.BASE, m.CODE_END)
    finally:
        os.unlink(f.name)
    hits = set()
    for line in lst.splitlines():
        p = line.split("\t")
        if len(p) < 3 or ".short" in p[2]:
            continue
        for x in re.findall(r"0x([0-9a-f]{8})\b", p[2]):
            hits.add(int(x, 16))
        for x in re.findall(r"#(-?\d+)\b", p[2]):
            hits.add(int(x) & 0xFFFFFFFF)
    assert m.STACK_TOP in hits and m.BSS[1] in hits
    # 0x46666666 is a Q31 gain (0.55) fed to the MAC at 0x40007422, not an address
    assert {v for v in hits if lo < v < hi} == {0x46666666}
    assert hi - lo == 66782848
