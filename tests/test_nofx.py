"""The nofx image: the cut image with the FX track's mute taken out and no frame of ours in SDRAM."""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_feed as F
import test_pre as T
import test_prewas as W
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

FX = T.FX


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=42)


@pytest.fixture(scope="module")
def cut(official):
    return build_main.patched_image(official.section(3), xfade=41)


def rig_of(built):
    r = T.Rig(*built)
    r.stores = []
    r.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: r.stores.append(addr), begin=0x45566490, end=0x4556ffff)
    return r


@pytest.fixture(scope="module")
def rig(main):
    return rig_of(main)


@pytest.fixture(scope="module")
def was(cut):
    return rig_of(cut)


TAKES = [{0: 2}, {3: 9, 5: 4}, {1: FX}, {t: 2 + t for t in range(8)}, {0: 5, 2: FX, 6: 5, 7: 3}, {4: 0}, {2: 12}]


@pytest.mark.parametrize("takes", range(len(TAKES)))
def test_every_take_is_the_cut_images(rig, was, takes):
    got = W.go(rig, TAKES[takes], seed=70 + takes)
    want = W.go(was, TAKES[takes], seed=70 + takes)
    assert got[2] == want[2]
    assert np.array_equal(rig.at_mixer, was.at_mixer)


@pytest.mark.parametrize("source", [2, 5, 9, FX, 0, 12])
def test_the_meter_is_the_cut_images(rig, was, source):
    W.go(rig, {}, seed=80 + source, page=F.FEED_PAGE, source=source, quiet=1)
    W.go(was, {}, seed=80 + source, page=F.FEED_PAGE, source=source, quiet=1)
    assert rig.vars[3] == was.vars[3] != 0


@pytest.mark.parametrize("mutes,pattern", [(T.FX_BIT, 0), (0, T.FX_BIT), (T.FX_BIT, T.FX_BIT)])
def test_muting_the_fx_track_changes_nothing_the_mixer_is_shown(rig, mutes, pattern):
    for step in range(3):
        *_, inputs = W.go(rig, {2: FX}, seed=90 + step, mutes=mutes, pattern=pattern)
        assert np.array_equal(rig.at_mixer, inputs), step


def test_nothing_is_stored_in_that_memory_with_takes_and_the_meter(rig):
    rig.stores.clear()
    W.go(rig, {t: 2 + t for t in range(8)}, seed=5)
    W.go(rig, {1: FX}, seed=6, mutes=T.FX_BIT)
    W.go(rig, {}, seed=7, page=F.FEED_PAGE, source=FX, quiet=1)
    assert rig.stores == []


def test_the_image(official_path, main, cut):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=42, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=41, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("5ac6638c")  # the cut image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == cut[0]
    spans = [mm.CAVE_PRE, mm.CAVE_PROF, mm.CAVE_FAST, mm.CAVE_SRR, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_AMUTE, mm.CAVE_ALOCK,
             mm.CAVE_FEED, mm.CAVE_SOLO]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
             and not moved(k)]
    assert stray == [] and new != old
    print("nofx image", hashlib.sha256(raw).hexdigest())
