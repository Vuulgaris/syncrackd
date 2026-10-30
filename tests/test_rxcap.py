"""The rxcap image: the rxoff image with the USB audio receive off only while the phone has said a capture is on.

On request: a host that has the Syntakt as its
output and input (Ableton) takes the unit's audio the whole time, so the unit is always sending and rxoff never ran the
receive. The maintainer's choice, "do 1": the phone says when it captures. engine/phone.c, CAPTURE: 0x65 sets the word first in the
gate's run, 0x66 clears it; neither is answered or handed on. engine/rxgate.S, CAPTURE: the receive is skipped only with
the word set and the unit sending, and the word is cleared whenever the unit sends nothing.

Held here by running the gate (stock's clear run, stock's receive played) and the SysEx entry with test_phone's rig;
not held: the USB controller, the phone's frames on the wire.
"""
import hashlib
import shutil

import pytest

import test_phone as P
import test_rxoff as R
from test_rpc import case_of
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

WORD = mm.CAVE_RXGATE[0]


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=36)


@pytest.fixture(scope="module")
def rxoff(official):
    return build_main.patched_image(official.section(3), xfade=35)


def gate(built, sending, word):
    import test_rxoff
    mc_seen = []
    orig = test_rxoff.Machine

    class M(orig):
        def write(self, addr, data):
            super().write(addr, data)
            if addr == mm.BASE:
                super().write(WORD, word.to_bytes(4, "big"))
    test_rxoff.Machine = M
    try:
        mc, seen = R.gate(built, sending)
    finally:
        test_rxoff.Machine = orig
    return mc, seen


@pytest.mark.parametrize("sending,word,receives,left", [(0, 0, True, 0), (0, 1, True, 0), (1, 0, True, 0), (1, 1, False, 1)])
def test_the_receive_is_off_only_with_the_phones_word_and_the_unit_sending(main, sending, word, receives, left):
    mc, seen = gate(main, sending, word)
    assert (len(seen) == 1) == receives
    if not receives:
        assert mc.read(R.USB_IN, 256) == bytes(256)
    assert mc.r32(WORD) == left                                    # cleared when the unit sends nothing


def test_the_word_is_first_in_the_gates_run(main):
    assert main[1]["rx_capture"] == WORD < main[1]["rx_gate"]


def test_0x65_and_0x66_go_nowhere_in_stocks_parser(official):
    assert case_of(official.section(3), 0x65) == mm.RPC_NONE and case_of(official.section(3), 0x66) == mm.RPC_NONE


@pytest.mark.parametrize("ident,word", [(0x65, 1), (0x66, 0)])
def test_the_phones_frames_set_and_clear_the_word_and_are_neither_answered_nor_handed_on(main, ident, word):
    r = P.Rig(main)
    r.mc.w32(WORD, 1 - word)
    data, n = r.frame(ident, 0, 6)
    r.mc.call(r.syms["knows_sysex"], data, n, 2)
    assert r.mc.r32(WORD) == word and r.log == []


def test_every_other_frame_goes_where_it_went(main):
    r = P.Rig(main)
    data, n = r.frame(0x53, 0, 12)
    r.mc.call(r.syms["knows_sysex"], data, n, 4)
    assert r.log == [("handle", data, n, 4)] and r.mc.r32(WORD) == 0


def test_the_image(official_path, main, rxoff):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=36, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=35, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("32c67235")      # the rxoff image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == rxoff[0]
    spans = [mm.CAVE_RXGATE, mm.CAVE_PHONE3, (mm.RX_CALL + 2, mm.RX_CALL + 6), (mm.SYSEX_IN_JMP + 2, mm.SYSEX_IN_JMP + 6),
             (mm.PROJECT_LOAD_CALL + 2, mm.PROJECT_LOAD_CALL + 6)]
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)] == []
    print("rxcap image", hashlib.sha256(raw).hexdigest())
