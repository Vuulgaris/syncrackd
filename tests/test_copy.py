"""The copy image: the rxcap image with every mono track's right buffer copied eight longs a move (movem).

Before the mixer,
every digital track with no right channel this block is given a copy of its left in the second set of buffers
(engine/rightdma.c, right_end). take() moved it one long at a time in a loop; mono_copy (MOVEM, in a run of its own)
moves eight longs each way four times a track. A hardware transfer for it was weighed and left: it would have to start
after stock's own transfer and end before the mixer, and emulation has no transfer controller; this one is held here
bit for bit.

Held here, with tests/test_dma.py's rig (the transfers modelled): every mix of stereo and mono tracks gives the right
buffers the rxcap image gives them, in every mode, nothing beyond them written; and what it costs.
"""
import hashlib
import shutil

import numpy as np
import pytest

import test_dma as D
from test_stereo import some_tracks, window_of
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=37)


@pytest.fixture(scope="module")
def rxcap(official):
    return build_main.patched_image(official.section(3), xfade=36)


def rig(built, mode):
    r = D.Rig(built)
    r.mc.load_code(mm.CAVE_COPY[0], built[0][mm.off(mm.CAVE_COPY[0]):mm.off(mm.CAVE_COPY[1])])
    r.mc.uc.ctl_flush_tb()
    r.state(D.S_MODE, mode)
    r.state(D.S_GOOD, D.GOOD_BLOCKS if mode == D.TRUSTED else 0)
    return r


def run(built, mask, mode, seed=0):
    r = rig(built, mode)
    tracks, right = some_tracks(40 + seed), D.rights()
    start = r.mc.insns
    got = r.block(tracks, window_of(right, mask))
    return got, r.mc.insns - start, r.mc.read(D.RIGHT + 1024, 256), r.mc.read(D.STATE + 32, 64), [r.state(k) for k in range(8)]


@pytest.mark.parametrize("mode", [D.TRUSTED, D.CHECK, D.DEAD])
@pytest.mark.parametrize("mask", [0x00, 0xff, 0x01, 0x80, 0x5a, 0x0f, 0x3c])
def test_the_right_buffers_are_the_rxcap_images_bit_for_bit(main, rxcap, mask, mode):
    got, _, after, beyond, state = run(main, mask, mode)
    want, _, after0, beyond0, state0 = run(rxcap, mask, mode)
    assert np.array_equal(got, want)
    assert after == after0 == b"\xee" * 256 and beyond == beyond0 and state == state0


def test_eight_mono_tracks_cost_a_fraction_of_the_instructions(main, rxcap):
    _, n, *_ = run(main, 0x00, D.TRUSTED)
    _, m, *_ = run(rxcap, 0x00, D.TRUSTED)
    print("a block with eight mono tracks: %d instructions, %d on the rxcap image" % (n, m))
    assert n * 3 < m
    _, n8, *_ = run(main, 0xff, D.TRUSTED)
    _, m8, *_ = run(rxcap, 0xff, D.TRUSTED)
    assert n8 <= m8 + 50                        # with every track stereo there is nothing to copy: eight tests of a bit either way


def test_the_image(official_path, main, rxcap):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=37, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=36, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("07bf23ed")      # the rxcap image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == rxcap[0]
    spans = [mm.CAVE_DMA, mm.CAVE_DMA2, mm.CAVE_COPY, mm.CAVE_LAP]           # the transfers' compile: its runs
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
            and not moved(k)] == []
    print("copy image", hashlib.sha256(raw).hexdigest())
