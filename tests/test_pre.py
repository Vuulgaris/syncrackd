"""The pre image: the soft image with a take's sources read before the mixer.

A muted track showed no level on the sampling page and recorded nothing, and the FX track's mute did nothing. The mixer is shown a muted track at a volume of 0, and a take was made from the frame the mixer
leaves. Here the buffer of every digital track that is a take's source, or the meter's, and the FX track's return,
are copied into a frame of ours before the mixer is called, and the feed and the meter read them there
(engine/recfeed.c, PRE). And the FX track's mute, global or the pattern's, takes its return to nothing in its own
buffers before the mixer, over a block, after the copy.

Held here, the mixer a stand-in that changes nothing: a take of a track or of the return is made from the buffers as
they were before the mixer, whatever the frame holds; every other source is the frame's, the window the prof image's
to the bit; only the channels asked for are copied; the return under a mute goes down over a block, is nothing, comes
up over a block, and its take is whole all the while; the meter reads the copy; and the image is the soft image but
for the feed's runs.

Not held, and only the unit can show it: that the track buffers before the mixer are the track's sound before its
level (read from the meter going dark under a mute, not from the mixer); that the return reaches the outputs through
the mixer alone, so that its mute is heard; how loud a take of a track now is.
"""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_feed as F
import test_multi as M
import test_prof as PR
import test_srr as S
from emu.engine import BLOCK
from test_meter import ALL
from test_recorder import STRIDE, frames, junk, make_block
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ON, OFF = S.ON, S.OFF
FX, FX_BIT = 14, 1 << 12


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=13)


@pytest.fixture(scope="module")
def prof(stock3):
    return build_main.patched_image(stock3, xfade=12)         # the soft image's main program is the prof image's


class Rig(PR.Rig):
    """The prof image's rig with the copies' run, the frame of ours, and the inputs as the mixer finds them."""

    def __init__(self, image, syms, pre=True):
        super().__init__(image, syms)
        mc = self.mc
        if pre:
            lo, hi = mm.CAVE_PRE
            mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        mc.map(mm.PRE_FRAME & ~0xffff, 0x10000)
        self.at_mixer = None
        mc.uc.hook_add(UC_HOOK_CODE, self._mixer, begin=mm.MIX, end=mm.MIX)
        mc.uc.ctl_flush_tb()

    def _mixer(self, uc, address, size, user):
        self.at_mixer = longs(self.mc, mm.INPUTS, 8)


def longs(mc, at, rows):
    return np.frombuffer(bytes(mc.read(at, 4 * BLOCK * rows)), dtype=">i4").astype(np.int64).reshape(rows, BLOCK)


@pytest.fixture(scope="module")
def rig(main):
    return Rig(*main)


@pytest.fixture(scope="module")
def was(prof):
    return Rig(*prof, pre=False)


def sound(seed):
    rng = np.random.default_rng(seed)
    return rng.integers(-2 ** 31, 2 ** 31, (8, BLOCK)).astype(np.int32), rng.integers(-2 ** 31, 2 ** 31, (8, BLOCK)).astype(np.int32)


def go(r, takes, seed=3, mutes=0, pattern=0, page=0, source=0, quiet=0):
    """One block. takes: {track: source}. -> the window before, the frame, the window after, the tracks, the inputs."""
    mc = r.mc
    tracks, inputs = sound(seed)
    r.reset(page=page, source=source, quiet=quiet, gains=M.GAINS)
    r.window = []
    r.clock(1, 2, 3)
    mc.w32(r.syms["prof_on"], 0)
    mc.write(mm.TRACKS, tracks.astype(">i4").tobytes())
    mc.write(mm.INPUTS, inputs.astype(">i4").tobytes())
    mc.write(mm.MUTES, mutes.to_bytes(4, "big") + bytes(4))
    mc.write(mm.PATTERN_MUTES, pattern.to_bytes(2, "big"))
    window, frame = junk(0x0105), frames(seed=seed + 50)
    b = bytearray(make_block(ALL, [0] * 12))
    for t in range(8):
        b[STRIDE * t + F.P_REC:STRIDE * t + F.P_REC + 2] = (ON << 8 | takes[t] if t in takes else OFF << 8 | 7).to_bytes(2, "big")
    ret, after = r.run(bytes(b), frame, window)
    assert all(size in (2, 4) for _, _, size, _ in r.window)        # the window stores words: never a byte
    assert np.array_equal(longs(mc, mm.TRACKS, 8), tracks)          # the tracks' buffers are only read
    return window, frame, after, tracks, inputs


def before_the_mixer(frame, tracks, inputs):
    """The frame a take is made from: a digital track's channel and the return's two are the buffers'."""
    f = np.array(frame)
    f[:, 2:10] = tracks.T
    f[:, 14], f[:, 15] = inputs[6], inputs[7]
    return f


@pytest.mark.parametrize("takes", [{0: 2}, {3: 9, 5: 4}, {1: FX}, {t: 2 + t for t in range(8)}, {0: 5, 2: FX, 6: 5, 7: 3}])
def test_a_take_of_a_track_or_of_the_return_is_made_from_the_buffers_before_the_mixer(rig, takes):
    window, frame, after, tracks, inputs = go(rig, takes)
    want = M.want(window, before_the_mixer(frame, tracks, inputs), {t: (n, True) for t, n in takes.items()}, M.GAINS)
    assert after == want != M.want(window, frame, {t: (n, True) for t, n in takes.items()}, M.GAINS)


@pytest.mark.parametrize("takes", [{0: 0}, {2: 1, 4: 10}, {1: 11, 3: 12, 5: 13, 7: 15}, {}])
def test_every_other_source_is_the_frames_and_the_window_the_prof_images(rig, was, takes):
    window, frame, after, _, _ = go(rig, takes, seed=6)
    assert after == go(was, takes, seed=6)[2] == M.want(window, frame, {t: (n, True) for t, n in takes.items()}, M.GAINS)
    assert rig.window == was.window                                 # and what is read and written there, in order


def test_only_what_is_asked_for_is_copied(rig):
    mc = rig.mc
    mark = np.full((BLOCK, mm.FRAME_CH), 0x5a5a5a5a, dtype=np.int64)
    mc.write(mm.PRE_FRAME, mark.astype(">u4").tobytes())
    mc.w32(mm.PRE_FRAME, 0)                                         # the return was not muted the block before
    _, _, _, tracks, inputs = go(rig, {1: 4, 6: FX}, seed=8)
    ours = np.frombuffer(bytes(mc.read(mm.PRE_FRAME, 4 * BLOCK * mm.FRAME_CH)), dtype=">i4").astype(np.int64).reshape(BLOCK, mm.FRAME_CH)
    want = mark.copy()
    want[:, 4], want[:, 14], want[:, 15] = tracks[2], inputs[6], inputs[7]
    want[0, 0] = 0
    assert np.array_equal(ours, want)
    assert np.array_equal(rig.at_mixer, inputs)                     # and with no mute the inputs reach the mixer as they came


def test_the_fx_tracks_mute_takes_its_return_down_over_a_block_and_the_take_is_whole(rig):
    rig.mc.w32(mm.PRE_FRAME, 0)
    k = np.arange(BLOCK)
    for step, (mutes, pattern, gain) in enumerate([(FX_BIT, 0, BLOCK - 1 - k), (FX_BIT, 0, 0 * k), (0, FX_BIT, 0 * k), (0, 0, k + 1), (0, 0, None),
                                                   (0xfff, 0xfff, None)]):       # every other track's mute is nothing to it
        window, frame, after, tracks, inputs = go(rig, {2: FX}, seed=20 + step, mutes=mutes, pattern=pattern)
        want = inputs.astype(np.int64)
        if gain is not None:
            want[6:] = (want[6:] >> 5) * gain
        assert np.array_equal(rig.at_mixer, want), step
        assert np.array_equal(rig.at_mixer[:6], inputs[:6])        # the analog tracks and the external input are not touched
        assert after == M.want(window, before_the_mixer(frame, tracks, inputs), {2: (FX, True)}, M.GAINS), step
    assert rig.mc.r32(mm.PRE_FRAME) == 0


def test_whatever_memory_held_at_a_start_costs_one_block_coming_up(rig):
    rig.mc.w32(mm.PRE_FRAME, 0xdeadbeef)
    _, _, _, _, inputs = go(rig, {}, seed=30)
    assert np.array_equal(rig.at_mixer[6:], (inputs[6:].astype(np.int64) >> 5) * (np.arange(BLOCK) + 1))
    _, _, _, _, inputs = go(rig, {}, seed=31)
    assert np.array_equal(rig.at_mixer, inputs)


@pytest.mark.parametrize("source", [2, 7, FX])
def test_the_meter_reads_the_copy(rig, source):
    _, frame, _, tracks, inputs = go(rig, {}, seed=40 + source, page=F.FEED_PAGE, source=source, quiet=1)
    f = before_the_mixer(frame, tracks, inputs).astype(np.int64)
    pair = f[:, [source, source + (source == FX)]]
    top = int((pair ^ (pair >> 31)).max()) >> 16
    assert rig.vars[3] == min(top, 32767) != 0


def test_with_the_page_shut_and_no_take_nothing_is_copied(rig):
    mc = rig.mc
    mc.write(mm.PRE_FRAME, bytes(4 * BLOCK * mm.FRAME_CH))
    go(rig, {}, seed=9)
    assert mc.read(mm.PRE_FRAME, 4 * BLOCK * mm.FRAME_CH) == bytes(4 * BLOCK * mm.FRAME_CH)


def test_the_image(official_path, official, main, prof):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=13)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=12)
    assert hashlib.sha256(was_raw).hexdigest().startswith("20f3d6b6")      # the soft image, as it is
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old == prof[0] and len(new) == len(old)
    assert built.section(7) == was.section(7)
    spans = [mm.CAVE_PRE, mm.CAVE_PROF, mm.CAVE_ALOCK, mm.CAVE_METER, (mm.MIX_CALL + 2, mm.MIX_CALL + 6)]       # the last: the mixer's call, to a routine that moved
    stray = [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert not stray, [hex(a) for a in stray[:24]]
    assert new[mm.off(mm.MIX_CALL):][:6] == b"\x4e\xb9" + syms["mix_rec"].to_bytes(4, "big")
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
