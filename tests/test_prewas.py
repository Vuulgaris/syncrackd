"""The prewas image: the allright image with the pre frame's flag on-chip.

The maintainer, 2026-10-17, of the lag with the unit's USB audio streaming, after the allright image ("yea sitll lgs alot"):
test D (the meter image with 1 KB a block stored at 0x4556a000) lags, test G (the same reads, nothing stored) and test F
(the same stores on-chip) do not. What every image since the pre image stores in that memory on any page is one long a
block: the pre frame's first, whether the FX track's return was muted the block before (engine/recfeed.c, PRE_WAS).
PREWAS: that long at 0x80007d20, on-chip, after the transfers' eight (stock clears it at every start, as it is to be).

Held here with test_pre's rig: with no take and the page shut nothing is stored from 0x45566490 (what stock clears up to)
to 0x45570000 (the effects' memory), and the FX track's mute goes as on the pre image with the flag in its new place.
Not held: the lag.
"""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_pre as T
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=40)


@pytest.fixture(scope="module")
def allright(official):
    return build_main.patched_image(official.section(3), xfade=39)


@pytest.fixture(scope="module")
def rig(main):
    r = T.Rig(*main)
    r.stores = []
    r.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: r.stores.append(addr), begin=0x45566490, end=0x4556ffff)
    return r


def go(r, takes, **k):
    """test_pre's block, with as many timer readings as this image makes (more than the pre image's three)."""
    cls = type(r)
    r.clock = lambda *c: cls.clock(r, *range(1, 65))
    try:
        return T.go(r, takes, **k)
    finally:
        del r.clock


def test_the_flag_is_after_the_transfers_state():
    assert mm.PRE_WAS_SRAM == mm.RIGHT_STATE + 32 < 0x80008000


def test_with_no_take_and_the_page_shut_nothing_is_stored_in_that_memory(rig):
    rig.stores.clear()
    for seed in range(3):
        go(rig, {}, seed=50 + seed)
    assert rig.stores == []


def test_the_fx_tracks_mute_goes_as_before_with_the_flag_on_chip(rig):
    rig.mc.w32(mm.PRE_WAS_SRAM, 0)
    k = np.arange(BLOCK := T.BLOCK)
    for step, (mutes, gain) in enumerate([(T.FX_BIT, BLOCK - 1 - k), (T.FX_BIT, 0 * k), (0, k + 1), (0, None)]):
        rig.stores.clear()
        *_, inputs = go(rig, {}, seed=60 + step, mutes=mutes)
        want = inputs.astype(np.int64)
        if gain is not None:
            want[6:] = (want[6:] >> 5) * gain
        assert np.array_equal(rig.at_mixer, want), step
        assert rig.mc.r32(mm.PRE_WAS_SRAM) == (mutes != 0) and rig.stores == [], step


def test_the_image(official_path, main, allright):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=40, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=39, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("bee5bbfc")      # the allright image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == allright[0]
    spans = [mm.CAVE_PRE, mm.CAVE_PROF, mm.CAVE_FAST, mm.CAVE_SRR, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_AMUTE, mm.CAVE_ALOCK]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
             and not moved(k)]
    assert stray == [] and new != old
    o = mm.off(mm.CAVE_PRE[0])
    run = new[o:mm.off(mm.CAVE_PRE[1])]
    assert run.count((0x80007d20).to_bytes(4, "big")) >= 1
    print("prewas image", hashlib.sha256(raw).hexdigest())
