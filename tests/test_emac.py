"""EMAC model and decoder. Values follow the ColdFire reference manual, chapter 6."""
import pytest

from emu import emac
from emu.emac import FI, OMC, Emac

ONE = 0x7FFFFFFF
MINUS_ONE = 0x80000000
HALF = 0x40000000


def frac():
    e = Emac()
    e.macsr = OMC | FI          # 0xA0, as in the voice loop
    return e


def test_fractional_products():
    e = frac()
    e.mac(0, HALF, HALF)
    assert e.store(0, clear=True) == 0x20000000            # 0.5 * 0.5
    e.mac(0, MINUS_ONE, HALF)
    assert e.store(0, clear=True) == 0xC0000000            # -1 * 0.5
    e.mac(0, MINUS_ONE, 0x80AD0000)                        # the case Unicorn gets wrong:
    v = e.store(0, clear=True)                             # -1 * -0.9947 must be +0.9947
    assert v == 0x7F530000


def test_minus_one_squared_saturates_on_store_only():
    e = frac()
    e.mac(0, MINUS_ONE, MINUS_ONE)
    assert e.acc[0] == 1 << 39                             # exactly +1.0, held in the extension
    assert e.store(0) == ONE                               # OMC: saturated read
    e.mac(0, MINUS_ONE, HALF)                              # +1.0 - 0.5 is back in range
    assert e.store(0, clear=True) == HALF
    assert e.acc[0] == 0 and e.overflows == 0


def test_no_saturation_without_omc():
    e = Emac()
    e.macsr = FI                                           # 0x20, as after the voice loop
    e.mac(0, MINUS_ONE, MINUS_ONE)
    assert e.store(0) == 0x80000000                        # ACC[39:8], wrapped


def test_low_byte_keeps_precision():
    e = frac()
    x = 0x00001000                                         # products below one Q31 lsb
    for _ in range(256):
        e.mac(0, x, x)
    # each product is 2**24 >> 23 = 2 units of 2**-39; 256 of them reach 2 lsb of Q31
    assert e.acc[0] == 512 and e.store(0) == 2


def test_truncation_is_floor():
    e = frac()
    e.mac(0, 0xFFFFFFFF, 0x00000001)                       # -2**-31 * 2**-31, tiny negative
    assert e.acc[0] == -1 and e.store(0) == 0xFFFFFFFF


def test_msac_and_load():
    e = frac()
    e.load(1, 0x12345678)
    assert e.acc[1] == 0x12345678 << 8
    e.mac(1, HALF, HALF, sub=True)
    assert e.store(1) == 0x12345678 - 0x20000000 & 0xFFFFFFFF
    assert e.store(1, clear=True) and e.acc[1] == 0
    e.load(2, 0x80000000)
    assert e.acc[2] == -(1 << 39) and e.store(2) == 0x80000000


def test_unmodelled_modes_raise():
    e = Emac()                                             # integer mode
    with pytest.raises(NotImplementedError):
        e.mac(0, 1, 1)
    e.macsr = FI | emac.RT
    with pytest.raises(NotImplementedError):
        e.store(0)


@pytest.mark.parametrize("raw,want", [
    ("a4010800", "macl %d1,%d2,%acc0"),
    ("a6020900", "msacl %d2,%d3,%acc0"),
    ("a29c1806", "macl %d6,%d1,%a4@+,%d1,%acc0"),
    ("a2aa19040004", "msacl %d4,%d1,%a2@(4),%d1,%acc0"),
    ("a1c2", "movclrl %acc0,%d2"),
    ("a93c000000a0", "movel #160,%macsr"),
])
def test_decode_known_encodings(raw, want):
    b = bytes.fromhex(raw)
    i = emac.decode(b)
    assert emac.text(i) == want and i.size == len(b)


def test_mov3q_is_not_emac():
    assert emac.decode(bytes.fromhex("a144")) is None


def test_decoder_agrees_with_objdump_on_all_of_section_7(official):
    """Every EMAC instruction in the real code: our decode renders to objdump's text."""
    import shutil
    if not shutil.which("m68k-elf-objdump"):
        pytest.skip("no objdump")
    from emu.machine import boundaries
    from tools import audiomap as m
    code = official.section(7)[4:m.off(m.CODE_END)]
    n = 0
    for addr, raw, txt in boundaries(code, m.BASE + 4):
        i = emac.decode(raw) if raw[0] >> 4 == 0xA else None
        if i is None:
            continue
        assert i.size == len(raw), hex(addr)
        assert emac.text(i) == txt.replace("\t", " ").strip(), hex(addr)
        n += 1
    assert n == 839
