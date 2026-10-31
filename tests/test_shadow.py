"""The shadow image (engine/mirror.c, SHADOW): the trap image with the viewer's frame copied from what reaches the panel."""

import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

from tests.test_mirror import FRAME_AT, OTHER, OTHER_AT, SHOWN_AT, TICKS, UI, Rig, decode
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

HEAP = 0x44560000


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=66)


def rig(main):
    r = Rig(main, stock_paint=True, bus=True)
    r.taken = []
    r.stub(0x40103952, lambda n: r.taken.append(n) or HEAP)
    r.mc.uc.ctl_flush_tb()
    r.mc.write(FRAME_AT, bytes(1024))  # as after the clear: both frames and the panel 0
    r.mc.write(OTHER, bytes(1024))
    return r


def test_the_frame_sent_is_what_reached_the_panel(main):
    r = rig(main)
    mc, rng = r.mc, np.random.default_rng(3)
    r.tick()
    assert not r.taken  # no viewer: nothing taken
    r.sysex(0x67, 0)
    shown = rng.integers(0, 256, 1024).astype(np.uint8).tobytes()
    mc.write(FRAME_AT, shown)  # what both buffers hold, not what the panel has
    mc.write(OTHER, shown)
    r.clock(1000 + TICKS // 15)
    r.paint()  # nothing differs: nothing sent, the panel still 0
    assert bytes(r.panel) == bytes(1024)
    r.tick()
    assert r.taken == [1024] and mc.read(UI + mm.UI_DRAW_MARK, 1) == b"\x01"
    assert bytes(mc.read(OTHER, 1024)) == bytes(b ^ 0xff for b in shown)  # turned over (the frame shown after the paint)
    assert decode(r.frames()[-1])[1] == shown
    picture = bytearray(rng.integers(0, 256, 1024).astype(np.uint8).tobytes())
    for n in range(4):
        for g in rng.choice(128, 3, replace=False):
            picture[8 * g:8 * g + 8] = rng.integers(0, 256, 8).astype(np.uint8).tobytes()
        mc.write(mc.r32(OTHER_AT), bytes(picture))  # the UI draws in *0x402d7110
        r.paint()
        assert bytes(r.panel) == bytes(picture)  # the first send rewrote the whole panel
        assert bytes(mc.read(HEAP, 1024)) == bytes(r.panel)
        mc.write(mc.r32(SHOWN_AT) + 8 * 31, b"\xff" * 40)  # strokes in the buffer after the send: not the panel's
        r.clock(1000 + (n + 2) * TICKS // 15)
        r.tick()
        assert decode(r.frames()[-1])[1] == bytes(r.panel)
    assert r.taken == [1024] and len(r.frames()) == 5


def test_what_a_column_send_costs(main):
    r = rig(main)
    r.sysex(0x67, 0)
    r.tick()
    n = [0]
    r.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: n.__setitem__(0, n[0] + 1), begin=0x40000000, end=0x401fffff)
    r.mc.write(0x44570000, bytes(range(8)))
    r.mc.call(mm.PANEL_COLUMNS, 40, 3, 0x44570000)
    print("a column send", n[0], "instructions")
    assert bytes(r.mc.read(HEAP + 8 * 40 + 3, 64))[::8] == bytes(range(8)) and n[0] < 80


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=66, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=65, prof=True)
    print("trap image", hashlib.sha256(was_raw).hexdigest())
    print("shadow image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_MIRROR, mm.CAVE_MIRROR2, mm.CAVE_MIRROR3, (mm.PANEL_COLUMNS, mm.PANEL_COLUMNS + 6),
             (mm.UI_PAINT_LEA + 2, mm.UI_PAINT_LEA + 6), (mm.UI_DIRTY_CALL + 2, mm.UI_DIRTY_CALL + 6)]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
