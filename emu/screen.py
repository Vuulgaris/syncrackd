"""A page of the main CPU's UI drawn by stock's own code, as a PNG. OS 1.42 only.

    python -m emu.screen fltr2 [IMAGE] [--machine 44]

IMAGE is a built image's name (build/images/Syntakt_OS1.42_sampler_IMAGE.syx) or "stock" (the official file).
Writes build/screens/IMAGE_PAGE_mMACHINE.png, 128 x 64 at four times the size. Made from Elektron code: never commit
it (rule 2).

What runs as it is: section 3 loaded at its base, the hot code copied on-chip as the start does, all 136 static
constructors (0x40339510; fonts, pictures, the knobs' display table), then the UI object's getter (0x4016f060), which
builds every page and its managers; then the page's own draw onto a surface of the unit's size (128 x 64, two longs a
column, made by stock's own surface constructor). Stock's y 0 is the bottom row: the panel scans bottom up, so a column's
first bit is the bottom (text stock draws at y 0 fills the last five rows). Stand-ins, and only these: memory nobody mapped reads 0 (no project is loaded: every value is 0), a divide by
0 leaves its register and goes on (the sequencer's, with no pattern), and the active track's machine is MACHINE for
every track (0x4000f692). Not run: the RTOS, the tasks, the screen's driver, what a project or a turn puts in the kit.
"""
import argparse
import os
import re
import struct
import sys
import zlib

import numpy as np
from unicorn import UC_HOOK_INTR, UC_HOOK_MEM_UNMAPPED, UcError
from unicorn.m68k_const import UC_M68K_REG_A0, UC_M68K_REG_PC, UC_M68K_REG_SR

from emu.machine import Machine
from tools import fw
from tools import mainmap as mm

ROOT = os.path.join(os.path.dirname(__file__), "..")
CTORS = 0x40339510                  # the count at - 4, then the constructors
UI_GET = 0x4016f060                 # (a0: where to put it) -> the UI object, built at the first call
HOT = 0x4000045c                    # the start's copy of the hot code into on-chip memory
MACHINE_OF = 0x4000f692             # (kit, track) -> the track's machine
SURFACE_NEW = 0x400f7242            # (surface, w, h): stock's, as the UI makes its 128 x 64 ones (0x400304c2)
SURFACE_FILL = 0x400f8508           # (surface, colour, 0): what the UI does with a new one (0x400304d2)
W, H = 128, 64
RET, SP, OUT = 0x47fffff0, 0x47ffff00, 0x47fff000
SURF = 0x47ff0000
PAGES = {                           # name: (class, the first page of the object's list, which of its pages shows)
    "syn": (mm.SYN_CLASS, 6, 0), "sampling": (mm.SYN_CLASS, 6, 1),      # a sampler track's second SYN page is ours (list 6, 6)
    "trig": (mm.TRIG_CLASS, 1, 0), "eucl": (mm.TRIG_CLASS, 1, 1),        # a digital track's TRIG object: pages 1 and 3
    "atrig": (mm.TRIG_CLASS, 26, 0),                                     # an analog track's: pages 26 and 3
    "fltr1": (mm.FILTER_CLASS, 9, 0), "fltr2": (mm.FILTER_CLASS, 9, 1),
}


def section3(name):
    if name == "stock":
        path = next(os.path.join(r, f) for r, _, fs in os.walk(os.path.join(ROOT, "firmware")) for f in fs if f.endswith(".syx"))
        return fw.load(path).section(3)
    with open(os.path.join(ROOT, "build", "images", "Syntakt_OS1.42_sampler_%s.syx" % name), "rb") as f:
        return fw.Image(f.read()).section(3)


class Screen:
    def __init__(self, image, machine=44):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x08000000)
        mc.map(0x80000000, 0x20000)
        mc.write(mm.BASE, image)
        mc.write(RET, b"\x4e\x71\x4e\x71")
        mc.uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda uc, acc, addr, size, v, u: uc.mem_map(addr & ~0xfff, 0x1000) or True)
        mc.uc.hook_add(UC_HOOK_INTR, self.intr)
        self.run(HOT)
        for k in range(mc.r32(CTORS - 4)):
            self.run(mc.r32(CTORS + 4 * k))
        mc.uc.reg_write(UC_M68K_REG_A0, OUT)
        self.run(UI_GET, limit=50_000_000)
        mc.write(MACHINE_OF, bytes([0x70, machine, 0x4e, 0x75]))       # moveq #machine,%d0 ; rts
        mc.uc.ctl_flush_tb()

    def intr(self, uc, intno, user):
        if intno != 5:                  # a divide by 0 goes on; anything else stops
            uc.emu_stop()
            self.fault = intno
            return
        uc.reg_write(UC_M68K_REG_PC, uc.reg_read(UC_M68K_REG_PC) + 4)

    def run(self, addr, *args, limit=20_000_000):
        mc = self.mc
        sp = SP - 4 * len(args)
        mc.w32(sp, RET)
        for k, a in enumerate(args):
            mc.w32(sp + 4 + 4 * k, a)
        mc.uc.reg_write(UC_M68K_REG_SR, 0x2700)
        mc.set_reg(15, sp)
        mc.uc.ctl_exits_enabled(True)
        mc.uc.ctl_set_exits([RET])
        self.fault = None
        try:
            mc.uc.emu_start(addr, 0, count=limit)
        except UcError as e:
            raise RuntimeError("%#x: %s at %#x" % (addr, e, mc.uc.reg_read(UC_M68K_REG_PC)))
        pc = mc.uc.reg_read(UC_M68K_REG_PC)
        if pc != RET:
            raise RuntimeError("%#x: stopped at %#x (exception %s)" % (addr, pc, self.fault))

    def page(self, cls, first, index):
        """The page object of this class whose list begins with first, set to show its index'th page."""
        mc = self.mc
        lo, hi = mm.MAIN_HEAP[0], mm.MAIN_HEAP[0] + 0x400000
        heap = bytes(mc.read(lo, hi - lo))
        for m in re.finditer(re.escape(struct.pack(">I", cls)), heap):
            obj = lo + m.start()
            lst, end = mc.r32(obj + mm.PAGE_LIST), mc.r32(obj + mm.PAGE_LIST_END)
            nums = [mc.r32(a) for a in range(lst, end, 4)] if 0 <= end - lst <= 64 else []
            if nums[:1] == [first] and index < len(nums):
                mc.w32(obj + mm.PAGE_INDEX, index)
                return obj
        raise LookupError("no page object of class %#x whose list begins with %d" % (cls, first))

    def draw(self, obj):
        """-> the 64 x 128 dots, row 0 the top."""
        mc = self.mc
        self.run(SURFACE_NEW, SURF, W, H)
        self.run(SURFACE_FILL, SURF, 0, 0)          # the heap is not cleared; stock fills a new surface with 0 next
        stride, dots = mc.r32(SURF + mm.SURFACE_STRIDE), mc.r32(SURF + mm.SURFACE_DATA)
        self.run(mc.r32(mc.r32(obj) + mm.PAGE_DRAW_METHOD), obj, SURF)
        bits = np.unpackbits(np.frombuffer(bytes(mc.read(dots, 4 * stride * W)), np.uint8)).reshape(W, 32 * stride)
        return bits.T[::-1][32 * stride - H:]     # a column's first bit is the bottom row


def png(path, dots, k=4):
    a = np.kron(np.asarray(dots, np.uint8) * 255, np.ones((k, k), np.uint8))
    h, w = a.shape
    raw = b"".join(b"\x00" + r.tobytes() for r in a)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("page", choices=sorted(PAGES))
    ap.add_argument("image", nargs="?", default="stock")
    ap.add_argument("--machine", type=int, default=44)
    a = ap.parse_args(argv)
    s = Screen(section3(a.image), a.machine)
    dots = s.draw(s.page(*PAGES[a.page]))
    out = os.path.join(ROOT, "build", "screens")
    os.makedirs(out, exist_ok=True)
    path = os.path.normpath(os.path.join(out, "%s_%s_m%d.png" % (a.image, a.page, a.machine)))
    png(path, dots)
    print(path)


if __name__ == "__main__":
    sys.exit(main())
