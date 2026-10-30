"""The sink image (engine/mirror.c, PIECES): the shadow image with the viewer's frame put into the SysEx sink whole.

On the unit the shadow image's frames still had strokes at the dials, in the same places on every page: the 56-byte
pieces whose 64 packed bytes cross the stream's byte 144, 288 and so on, from that byte to the piece's end (the
viewer's session, from the frames as received). Stock's put (0x40105f24) sends the sink's 144 bytes when they are full
and copies the rest of the write from the write's start again. Here, the main CPU only, with stock's sink run as it is
(its vtable 0x40242594, put, its send when full, the flush) and only the send to USB (0x40106976) played:
  - the shadow image's frame comes out with those pieces damaged, as on the unit;
  - the sink image's frame is the panel's to the byte, no write crossing a send;
  - section 7 the shadow image's, and only our places differ from it in section 3.
Only the unit can show: the viewer's picture clean."""

import hashlib
import shutil

import numpy as np
import pytest

from tests.test_mirror import SINK, TICKS, Rig, decode
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SINK_VT, SINK_SEND, SIZE = 0x40242594, 0x40106976, 144


@pytest.fixture(scope="module")
def sink(official):
    return build_main.patched_image(official.section(3), xfade=67)


@pytest.fixture(scope="module")
def shadow(official):
    return build_main.patched_image(official.section(3), xfade=66)


def rig(built):
    r = Rig(built)
    mc = r.mc
    r.stub(0x40103952, lambda n: 0)                             # no heap here: the frame shown is sent, as the second build
    mc.w32(SINK, SINK_VT)
    for off, v in ((4, 0), (8, 0), (12, 2), (16, 0), (532, SIZE)):
        mc.w32(SINK + off, v)
    r.wire, r.sends = b"", []
    def send(buf, n, a, b):
        r.wire += bytes(mc.read(buf, n))
        r.sends.append(n)
        return 1
    r.stub(SINK_SEND, send)
    mc.uc.ctl_flush_tb()
    r.sysex(0x67, 0)
    r.clock(1000 + TICKS)
    r.paint()
    r.tick()
    return r


def bad_pieces(frame, sent):
    return sorted({k // 56 for k in range(1024) if frame[k] != sent[k]})


def test_the_shadow_images_frame_is_damaged_where_a_write_crosses_a_send(shadow):
    r = rig(shadow)
    assert len(r.wire) == 1185 and r.sends[:-1] == [SIZE] * 8
    bad = bad_pieces(r.frame, decode(r.wire)[1])
    crossing = sorted({(s - 13) // 64 for s in range(SIZE, 1185, SIZE)})
    print("damaged pieces", bad, "crossing a send", crossing)
    assert bad == crossing == [2, 4, 6, 8, 11, 13, 15, 17]


def test_the_sink_images_frame_is_whole(sink):
    r = rig(sink)
    assert len(r.wire) == 1185 and r.sends == [SIZE] * 8 + [1185 - 8 * SIZE]
    count, data = decode(r.wire)
    assert count == 0 and data == r.frame


def test_the_image(official_path, official, sink):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=67, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=66, prof=True)
    print("shadow image", hashlib.sha256(was_raw).hexdigest())
    print("sink image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == sink[0]
    spans = [mm.CAVE_MIRROR, mm.CAVE_MIRROR2, mm.CAVE_MIRROR3, mm.CAVE_MIRROR4, (mm.PANEL_COLUMNS + 2, mm.PANEL_COLUMNS + 6),
             (mm.UI_PAINT_LEA + 2, mm.UI_PAINT_LEA + 6), (mm.UI_DIRTY_CALL + 2, mm.UI_DIRTY_CALL + 6)]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
