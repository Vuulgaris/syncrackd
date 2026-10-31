"""The box image: the switch image with the dotted boxes around SOLO and REC on the TRIG page wiped, and REC only OFF
or ONCE.




The box is stock's picture for a place with no record (0x444e00b4, 17 x 17, its bits at 0x402e9eb8 and its mask at
0x402e9e74, built at 0x4014925a), drawn by the TRIG page's own draw at x 25 + 26 a column, y 7 on the lower row. The
blit (0x400f8f70) is a masked copy, so a picture of 0 bits under that mask wipes it: ours is 28 bytes, its rows read
from one row (a stride of 0). REC: right is ONCE and left is OFF, on the TRIG page and the sampling page; the switch is
on at ONCE. Held here with stock's blit run as it is on a surface of the test's; not held: how it looks.
"""
import shutil

import numpy as np
import pytest

import test_gear as G
import test_trig as T
from test_page import HEAP, SURFACE
from test_reclock import REC_KNOB
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SWITCH, BLIT = 0x400703da, 0x400f8f70
DOTS, MASK = 0x402e9eb8, mm.DOTTED_MASK
BITS, DOTTED = HEAP + 0x9000, HEAP + 0x9800       # the surface's bits; a dotted box object
ROWS, STRIDE = 128, 4                             # the blit's third argument is a row of the surface (times its stride), the
COLS = 32 * STRIDE                                # fourth a bit across it: stock's "x 25, y 7" is rows 25 to 41, bits 7 to 23


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=25)


def rig(built, track):
    """test_trig's rig with a real surface, stock's blit run as it is, and stock's switch played."""
    r = T.trig(built, track)
    mc = r.mc
    for at, v in ((4, ROWS), (8, COLS), (12, STRIDE), (16, BITS)):
        mc.w32(SURFACE + at, v)
    for at, v in ((4, 17), (8, 17), (12, 1), (16, DOTS), (20, MASK)):
        mc.w32(DOTTED + at, v)
    r.switches = []
    r.stub(SWITCH, lambda obj, value, surface, x, y: r.switches.append((value >> 8, x, y)) or 0)
    mc.uc.ctl_flush_tb()
    return r


def screen(r):
    return np.unpackbits(np.frombuffer(bytes(r.mc.read(BITS, 4 * STRIDE * ROWS)), dtype=np.uint8)).reshape(ROWS, COLS)


def box(r, x, y):
    r.mc.call(BLIT, SURFACE, DOTTED, x, y, 0)


def area(dots, row, bit):
    return dots[row:row + 17, bit:bit + 17]


@pytest.mark.parametrize("track", [0, 6])
def test_the_dotted_boxes_of_e_and_f_are_wiped_and_nothing_else(main, track):
    r = rig(main, track)
    rng = np.random.default_rng(track)
    r.mc.write(BITS, rng.integers(0, 256, 4 * STRIDE * ROWS, dtype=np.uint8).tobytes())   # whatever else is drawn
    for x in (25, 51, 77):
        box(r, x, 7)                                            # stock's boxes at E, F and G
    before = screen(r).copy()
    dots = np.unpackbits(np.frombuffer(bytes(r.mc.read(DOTS, 68)), dtype=np.uint8)).reshape(17, 32)[:, :17]
    assert (area(before, 25, 7) == dots).all() and dots.sum() > 0                    # stock's box, as stock blits it
    r.show()
    after = screen(r)
    assert not area(after, 25, 7).any() and not area(after, 51, 7).any()
    keep = np.ones((ROWS, COLS), bool)
    keep[25:42, 7:24] = keep[51:68, 7:24] = False
    assert (after[keep] == before[keep]).all()                  # G's box and every other dot as they were
    assert r.switches == [(0, 24, 7), (0, 50, 7)]


def test_off_a_sampler_nothing_is_wiped(main):
    r = rig(main, 9)
    box(r, 25, 7)
    before = screen(r).copy()
    r.show()
    assert (screen(r) == before).all() and r.switches == []


def test_rec_on_the_trig_page_is_off_or_once(main):
    track = 3
    r = rig(main, track)
    G.geared(r, [256, 256, 256, -256, -256])
    seen = []
    for steps in (1, 1, 1, -1, -1):
        G.twist(r, T.F, steps)
        r.switches = []
        r.show()
        seen.append((r.mc.read(mm.ONCE_ARM + track, 1)[0], G.own(r, track) & 1, r.switches[-1][0]))
    assert seen == [(1, 0, 1), (1, 0, 1), (1, 0, 1), (0, 0, 0), (0, 0, 0)]     # ONCE and the switch on; never ON


def test_rec_on_the_sampling_page_is_off_or_once(main):
    track = 5
    r = T.A.page(main, track)
    G.geared(r, [256, 256, -256])
    words = []
    for steps in (1, 1, -1):
        G.twist(r, REC_KNOB, steps)
        words.append([t[2] for t in r.show() if t[2] in ("ON", "OFF", "ONCE")])
    assert words == [["ONCE"], ["ONCE"], ["OFF"]] and G.own(r, track) & 1 == 0


def test_a_held_step_locks_once_or_off(main):
    """With a step held, right locks the step to ONCE and left takes the lock off (the track's own is OFF): never ON."""
    track = 1
    r = rig(main, track)
    G.geared(r, [256, 256, -256])
    r.hold(4)
    seen = []
    for steps in (1, 1, -1):
        G.twist(r, T.F, steps)
        seen.append(r.lock_at(4, mm.REC_SLOT))
    assert seen == [mm.ONCE_WORD, mm.ONCE_WORD, 0xffff]
    assert r.mc.read(mm.ONCE_ARM + track, 1)[0] == 0 and G.own(r, track) & 1 == 0


def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=25)
    was = build.build(official_path, log=quiet, xfade=24)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] and built.section(7) == was.section(7)
    lo = mm.CAVE_TRIG4[0]
    assert new[mm.off(lo):mm.off(lo) + 28] == bytes.fromhex("00000000" "00000011" "00000011" "00000000") + (lo + 24).to_bytes(4, "big") + MASK.to_bytes(4, "big") + bytes(4)
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3, mm.CAVE_TRIG4,
             (mm.TRIG_CLASS, mm.TRIG_CLASS + 0x100), (mm.TRIG_SIDE + 8, mm.TRIG_SIDE + 12), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100),
             (mm.SYN_SIDE + 8, mm.SYN_SIDE + 12), (mm.SYN_BUILD, mm.SYN_BUILD + 0x20)]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    print("box image", __import__("hashlib").sha256(raw).hexdigest())
