"""The probe17 image, a tool: the fltr image with slot 17 and this block's solos on the sampling page.

The maintainer, 2026-10-16: a trigless step's SOLO lock "doesnt work currentlty", and "build a probe image that shows slot 17
on screen". The fifth place reads S17 and the track's slot 17 in the block a trig's locks are written into (0x800021b0),
the sixth NOW and the solos the mixer goes by (0x400a2938). Only the unit can show what a trigless step leaves there.
"""
import shutil

import pytest

import test_trig as T
from tools import build_main

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def probe17(official):
    build_main.EXTRA_DEFS = ("PROBE17",)
    try:
        return build_main.patched_image(official.section(3), xfade=28)
    finally:
        build_main.EXTRA_DEFS = ()


@pytest.fixture(scope="module")
def fltr(official):
    return build_main.patched_image(official.section(3), xfade=28)


@pytest.mark.parametrize("track", [0, 2])
def test_the_fifth_and_sixth_places_show_slot_17_and_the_solos(probe17, fltr, track):
    r, old = T.A.page(probe17, track), T.A.page(fltr, track)
    for q in (r, old):
        q.mc.map(0x80003000, 0x1000)
    r.mc.map(0x80002000, 0x1000)
    r.mc.write(0x800021b0 + 142 * track + 28 + 2 * 17, b"\x35\x80")
    r.mc.write(0x400a2938, (0x804 | 1 << track).to_bytes(4, "big"))
    new, was = r.show(), old.show()
    assert [t for t in was if t not in new] == []
    extra = sorted(t[2] for t in new if t not in was)
    assert extra == sorted(["S17", "3580", "NOW", "%03X" % (0x804 | 1 << track)])
