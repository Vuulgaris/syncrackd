"""The allright image: the nodiv image with the audio CPU sending every track's right half, so the main CPU copies none.




engine/stub.S, send_all (ALLRIGHT): at the end of every
interrupt every track's right half goes to the window, a stereo track's right channel as before and every other track's
own buffer (at 0x80003840, where stock's last stage leaves it and its transfer takes it), and the long says all eight.
The main CPU's code is the nodiv image's: with all eight said it starts both transfers and copies nothing.

Held here by running the audio CPU's whole interrupt (tests/stereo_rig.py); not held: the transfers on the unit, the
lag.
"""
import hashlib
import shutil

import numpy as np
import pytest

import stereo_rig as SR
from tools import build, build_engine
from tools import audiomap as m

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), xknob=True, slice=True, ring=True, allright=True)


@pytest.fixture(scope="module")
def ring(official):
    return build_engine.patched_image(official.section(7), xknob=True, slice=True, ring=True)


def feed(seed):
    return np.random.default_rng(seed).integers(-2 ** 26, 2 ** 26, (8, 32))


def test_the_left_buffers_are_where_send_all_takes_them():
    assert m.OUT_BUF == 0x80003840 and m.R_MASK == 0x44050400 and m.STASH == 0x44050000


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_with_no_stereo_note_every_track_s_right_half_is_its_own_buffer_and_all_eight_are_said(engine, ring, seed):
    r = SR.Rig(engine[0])
    voices, waiting, left = r.block(feed=feed(seed))
    assert r.mask() == 0xff
    for t in range(8):
        assert np.array_equal(r.right(t), left[t]), t
    o = SR.Rig(ring[0])
    _, _, left0 = o.block(feed=feed(seed))
    assert np.array_equal(left, left0) and o.mask() == 0          # the left the same as before; the ring image said none


def test_a_stereo_track_s_right_half_is_its_right_channel_and_the_rest_their_own(engine):
    r = SR.Rig(engine[0])
    mc = r.mc
    rng = np.random.default_rng(9)
    mc.write(m.HOST if hasattr(m, "HOST") else SR.E.HOST, r.host_block(0, 0))
    mc.write(SR.E.TCD47 + 0x1e, b"\x00\x80")
    from unicorn.m68k_const import UC_M68K_REG_A7
    mc.uc.reg_write(UC_M68K_REG_A7, m.STACK_TOP - 0x100)
    r.go(SR.E.ISR, SR.AFTER_VOICES)
    mc.write(m.OUT_BUF, np.asarray(feed(4)).astype(">i4").tobytes())
    mc.write(m.STASH, np.asarray(rng.integers(-2 ** 26, 2 ** 26, (8, 32))).astype(">i4").tobytes())
    mc.w32(m.R_MASK, 0b10100101)
    r.go(SR.AFTER_VOICES, SR.AMP_CALL)
    r.go(SR.AMP_CALL, SR.AFTER_AMP)
    left, right = r.tracks(m.OUT_BUF), r.tracks(m.STASH)
    r.go(SR.AFTER_AMP, SR.E.ISR_RTE)
    assert r.mask() == 0xff
    for t in range(8):
        assert np.array_equal(r.right(t), right[t] if 0b10100101 >> t & 1 else left[t]), t


def test_the_image(official_path):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=39, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=38, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("13474a00")      # the nodiv image, as it is
    assert built.section(3) == was.section(3)
    a7, b7 = built.section(7), was.section(7)
    runs = [r for d in (m.CAVES, m.REC_CAVES, m.PITCH_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                         m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES, m.HITS_CAVES) for r in d.values()]
    into = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(into(a7, j) and into(b7, j) for j in range(k - 3, k + 1))
    stray = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs) and not moved(k)]
    assert stray == [] and a7 != b7
    print("allright image", hashlib.sha256(raw).hexdigest())
