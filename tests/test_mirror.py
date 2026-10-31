"""The mirror image (engine/mirror.c, MIRROR): the kind image with the screen sent to a viewer over USB as SysEx."""

import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SINK, SINK_MADE, CLOCK = 0x4449c51c, 0x4449c808, 0xfc07000c
VT, PUT, COMMIT = 0x44500000, 0x44500100, 0x44500110
SHOWN_AT, FRAME_AT, UI = mm.PANEL_SHOWN, 0x44510000, 0x44520000
OTHER_AT, OTHER = 0x402d7110, 0x44511000
TICKS = 132000000


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=64)


class Rig:
    def __init__(self, built, stock_paint=False, bus=False):
        self.image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x44400000, 0x200000)
        mc.map(0xfc070000, 0x1000)
        mc.write(mm.BASE, self.image)
        mc.set_stack(0x407ff000, 0x40000100)
        self.sent, self.commits, self.asked = [], 0, 0
        mc.w32(SINK, VT)
        mc.w32(VT + 12, COMMIT)
        mc.w32(VT + 16, PUT)
        mc.w32(SINK_MADE, 1)
        self.frame = np.random.default_rng(1).integers(0, 256, 1024).astype(np.uint8).tobytes()
        mc.write(FRAME_AT, self.frame)
        mc.w32(SHOWN_AT, FRAME_AT)
        self.stub(PUT, lambda sink, data, n: self.sent.append(bytes(mc.read(data, n))))
        self.stub(COMMIT, lambda sink: self.commit())
        self.panel = bytearray(1024)
        if stock_paint:  # stock's send run as it is; the panel played column by column
            mc.w32(OTHER_AT, OTHER)
            if bus:  # the column sender run too, the panel played from its bytes on the bus
                self.said = []
                self.stub(0x40002762, lambda: 0)
                self.stub(0x40002772, lambda: 0)
                self.stub(0x4000271e, lambda b: self.said.append(b & 0xff))
                self.stub(0x40002550, lambda n, data: self.bus(n, data))
            else:
                self.stub(mm.PANEL_COLUMNS, lambda column, page, data: self.columns(column, page, data))
            self.stub(mm.PANEL_BRACKET, lambda: 0)
        else:
            self.stub(mm.PANEL_PAINT, lambda: 0x44530000)
        self.stub(mm.UI_DIRTY, lambda ui: self.ask())
        self.clock(1000)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
            uc.reg_write(UC_M68K_REG_D0, (fn(*args) or 0) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def columns(self, column, page, data):
        for k, b in enumerate(self.mc.read(data, 8)):
            self.panel[8 * (column + k) + page] = b

    def bus(self, n, data):
        (cmd, column), self.said = self.said[-2:], []
        assert cmd & 0xf8 == 0x10 and n == 8
        self.columns(column, cmd & 7, data)

    def commit(self):
        self.commits += 1

    def ask(self):
        self.asked += 1
        return 0x5501  # stock's answer, passed on as it is

    def clock(self, t):
        self.mc.w32(CLOCK, t & 0xFFFFFFFF)

    def sysex(self, *message):
        data = bytes([0, 0, 1, 0, 0]) + bytes(message)
        self.mc.write(0x44540000, data)
        self.mc.call(self.syms["knows_sysex"], 0x44540000, len(data), 2)

    def paint(self):
        return self.mc.call(self.syms["mirror_paint"])

    def tick(self):
        return self.mc.call(self.syms["mirror_tick"], UI)

    def frames(self):
        """The frames sent so far, each as the bytes of its writes joined."""
        out, cur = [], b""
        for w in self.sent:
            cur += w
            if w.endswith(b"\xf7"):
                out.append(cur)
                cur = b""
        return out


def decode(f):
    assert f[:12] == bytes([0xf0, 0x00, 0x20, 0x3c, 0x10, 0x00, 0, 0, 1, 0, 0, 0x69]) and f[-1] == 0xf7
    body, out = f[13:-1], bytearray()
    assert all(b < 0x80 for b in f[1:-1])
    i = 0
    while i < len(body):
        hi, g = body[i], min(7, len(body) - i - 1)
        out += bytes(body[i + 1 + k] | (hi >> (6 - k) & 1) << 7 for k in range(g))
        i += g + 1
    return f[12], bytes(out)


def test_a_frame_goes_once_asked_and_decodes_to_the_panels_bytes(main):
    r = Rig(main)
    r.paint()
    assert r.tick() == 0x5501 and not r.sent  # no viewer: nothing, stock's answer passed on
    r.sysex(0x67, 30)
    r.clock(1000 + TICKS // 30)
    r.paint()
    assert r.tick() == 0x5501
    (f,) = r.frames()
    assert len(f) == 1185 and r.commits == 1
    count, data = decode(f)
    assert count == 0 and data == r.frame


def test_the_frame_sent_is_the_panels(main):
    r = Rig(main, stock_paint=True)
    mc, rng = r.mc, np.random.default_rng(2)
    mc.write(FRAME_AT, bytes(1024))  # as at the start: both frames and the panel clear
    mc.write(OTHER, bytes(1024))
    r.sysex(0x67, 0)
    picture = bytearray(rng.integers(0, 256, 1024).astype(np.uint8).tobytes())
    for n in range(4):
        for g in rng.choice(128, 3, replace=False):  # a few columns change a frame, as a dial turned
            picture[8 * g:8 * g + 8] = rng.integers(0, 256, 8).astype(np.uint8).tobytes()
        drawn = mc.r32(OTHER_AT)  # the UI draws in *0x402d7110
        mc.write(drawn, bytes(picture))
        nxt = r.paint()
        assert nxt == mc.r32(OTHER_AT) != drawn and mc.r32(SHOWN_AT) == drawn
        assert bytes(r.panel) == bytes(picture)  # stock's send: the panel is the frame drawn
        r.clock(1000 + (n + 1) * TICKS // 15)
        r.tick()
        assert decode(r.frames()[-1])[1] == bytes(r.panel)
        assert n == 0 or bytes(mc.read(nxt, 1024)) != bytes(r.panel)
    assert len(r.frames()) == 4


def test_at_most_the_rate_and_only_a_new_frame(main):
    r = Rig(main)
    r.sysex(0x67, 10)  # ten a second
    t = 1000 + TICKS // 10
    r.clock(t)
    r.paint()
    r.tick()
    r.paint()
    r.tick()  # too soon: held
    assert len(r.frames()) == 1
    r.clock(t + TICKS // 10)
    r.tick()  # the held frame, at the next asking
    r.tick()  # nothing new
    r.clock(t + 3 * TICKS // 10)
    r.tick()
    assert [decode(f)[0] for f in r.frames()] == [0, 1]


def test_a_viewer_gone_or_off_stops_it(main):
    r = Rig(main)
    r.sysex(0x67, 0)  # 0: fifteen a second
    r.clock(1000 + 3 * TICKS + 1)  # 3 s and no renewal
    r.paint()
    r.tick()
    assert not r.sent
    r.sysex(0x67, 0)
    r.clock(1000 + 4 * TICKS)
    r.paint()
    r.tick()
    assert len(r.frames()) == 1
    r.sysex(0x68)
    r.clock(1000 + 5 * TICKS)
    r.paint()
    r.tick()
    assert len(r.frames()) == 1


def test_what_a_frame_costs(main):
    r = Rig(main)
    r.sysex(0x67, 15)
    r.clock(1000 + TICKS)
    r.paint()
    n = [0]
    h = r.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: n.__setitem__(0, n[0] + 1))
    r.tick()
    sent = n[0]
    n[0] = 0
    r.tick()
    r.mc.uc.hook_del(h)
    print("a frame", sent, "instructions; an asking with none", n[0])
    assert len(r.frames()) == 1 and sent < 40000 and n[0] < 40


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=64, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=63, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("d542b1fe")  # the kind image, as it is
    print("mirror image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_MIRROR, mm.CAVE_MIRROR2, mm.CAVE_MIRROR3, mm.CAVE_PHONE, mm.CAVE_PHONE2, mm.CAVE_PHONE3,
             (mm.UI_PAINT_LEA + 2, mm.UI_PAINT_LEA + 6), (mm.UI_DIRTY_CALL + 2, mm.UI_DIRTY_CALL + 6), (mm.SYSEX_IN_JMP + 2, mm.SYSEX_IN_JMP + 6)]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
