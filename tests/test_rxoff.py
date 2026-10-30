"""The rxoff image: the fast image with stock's receive of the host's USB audio not run while the unit sends its own.

On request. Measured on the maintainer's unit
(the evtime tool, samples/EVON3.wav and EVOFF3.wav): the per-block routine's call of stock's receive, 0x400041cc, is
0.9 hundredths of a block with no USB audio and 3.9 with it. engine/rxgate.S: the call goes to rx_gate, which while
0x405d40e4 (what stock's send tests first) is not 0 clears the 32 frames of USB audio in with stock's own clear and
returns, and otherwise goes to stock's routine as it was.

Held here by running the gate with stock's clear run as it is and stock's receive played; not held: the USB controller,
the time saved on the unit, that the packets left in the receive's list are taken up again after a capture.
"""
import hashlib
import shutil

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SENDING, RECEIVE, USB_IN, CLEAR = 0x405d40e4, 0x400041cc, 0x45512000, 0x40115b68


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=35)


@pytest.fixture(scope="module")
def fast(official):
    return build_main.patched_image(official.section(3), xfade=34)


def gate(built, sending):
    image, syms = built
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x41000000, 0x10000)
    mc.map(0x45500000, 0x20000)
    mc.write(mm.BASE, image)
    mc.write(RECEIVE, b"\x4e\x75")
    seen = []

    def receive(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        seen.append((sp, mc.r32(sp + 4), mc.r32(sp + 8)))
    mc.uc.hook_add(UC_HOOK_CODE, receive, begin=RECEIVE, end=RECEIVE)
    mc.w32(SENDING, sending)
    mc.write(USB_IN - 16, bytes(range(1, 256)) + bytes(range(1, 256)) + bytes(10))
    mc.set_stack(0x41008000, 0x41009000)
    mc.call(syms["rx_gate"], USB_IN, 32)
    return mc, seen


def test_with_no_capture_stocks_receive_is_called_with_the_stack_as_it_came(main):
    mc, seen = gate(main, 0)
    assert len(seen) == 1 and seen[0][1:] == (USB_IN, 32)
    assert mc.read(USB_IN, 256) == (bytes(range(1, 256)) + bytes(range(1, 256)))[16:16 + 256]


def test_while_the_unit_sends_its_usb_audio_the_receive_is_not_run_and_usb_in_is_silence(main):
    mc, seen = gate(main, 1)
    junk = bytes(range(1, 256)) + bytes(range(1, 256))
    assert seen == []
    assert mc.read(USB_IN, 256) == bytes(256)                       # 32 frames, two longs each
    assert mc.read(USB_IN - 16, 16) == junk[:16] and mc.read(USB_IN + 256, 16) == junk[272:288]   # and nothing round it


def test_the_call_goes_to_the_gate_with_its_two_arguments(main):
    image, syms = main
    o = mm.off(mm.RX_CALL)
    assert image[o - 10:o] == bytes.fromhex(fw.sx("db8a08dd3b00d569e8de924628e2"))
    assert image[o:o + 6] == b"\x4e\xb9" + syms["rx_gate"].to_bytes(4, "big")
    assert mm.CAVE_RXGATE[0] <= syms["rx_gate"] < mm.CAVE_RXGATE[1]


def test_the_image(official_path, main, fast):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=35, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=34, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("1f44982f")      # the fast image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == fast[0]
    spans = [mm.CAVE_RXGATE, (mm.RX_CALL + 2, mm.RX_CALL + 6)]
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)] == []
    print("rxoff image", hashlib.sha256(raw).hexdigest())
