"""The fast image: the mixtime image with a block that has nothing to change going straight to stock's mixer."""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_mainpatch as M
import test_mixer_whole as W
import test_xfade as X
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STRIDE, KNOBS, DEC, SOLO, SOLO_A, BACK = 142, 28, 25, 17, 26, 0x4198
ON, OFF = 0x35, 0x1a
SOLO_NOW, MIX_TRACKS = 0x400a2938, 12


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=34)


@pytest.fixture(scope="module")
def before(official):
    return build_main.patched_image(official.section(3), xfade=33)


def rig(built):
    r = X.Rig(*built, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    r.mc.map(0xfc000000, 0x100000)  # the profile's timer, which mix_timed reads
    r.n = 0

    def count(uc, address, size, user):
        r.n += 1
    r.mc.uc.hook_add(UC_HOOK_CODE, count)
    return r


@pytest.fixture(scope="module")
def fast(main):
    return rig(main)


@pytest.fixture(scope="module")
def old(before):
    return rig(before)


def scene(r, xfd=(), xf=None, marks=None, machines=X.MACHINES, seed=6, **state):
    """One mixer call: the sampler tracks' slot 25 at 127 (no crossfade) but for xfd {track: amount}, the solo marks
    {track: byte}, the twelve numbers xf. -> everything the mixer is shown and what is left, and the instructions.
    """
    block, level2 = M.make_block(machines, [0] * 12, seed=seed)
    block = bytearray(block)
    for t in range(8):
        at = STRIDE * t + KNOBS + 2 * DEC
        block[at:at + 2] = ((127 - dict(xfd).get(t, 0)) << 8).to_bytes(2, "big")
    block = bytes(block)
    back = M.PARAMS - BACK
    r.mc.write(back, bytes(STRIDE * 12))
    for t, d in (marks or {}).items():
        r.mc.write(back + STRIDE * t + KNOBS + 2 * (SOLO_A if t >= 8 else SOLO), bytes([d, 0x80]))
    was = np.random.default_rng(seed + 6).integers(1, 256, M.CONTROL_BYTES, dtype=np.uint8).tobytes()
    r.mc.write(mm.CONTROL, was)
    r.mc.write(mm.XFADES, bytes(xf or [0] * 12))
    r.n = 0
    ret, after, level2_after = r.run(block, level2, **state)
    n = r.n
    return (ret, after == block, level2_after == level2, r.seen["params"], r.seen["level2"], r.seen["control"],
            r.mc.read(mm.CONTROL, M.CONTROL_BYTES), r.left, r.mc.r32(SOLO_NOW), list(r.mc.read(mm.XFADES, 12))), n


CASES = [
    dict(),  # idle: the fast way
    dict(mutes=1 << 3), dict(mutes=1 << 9), dict(pattern=1 << 5), dict(pattern=1 << 12),  # 12: the FX track only
    dict(knob=1 << 2), dict(knob=1 << 10), dict(marks={4: ON}), dict(marks={4: OFF}, knob=1 << 4), dict(marks={9: ON}),
    dict(marks={1: 0x99}), dict(xfd={2: 40}), dict(xf=[0] * 9 + [30, 0, 0]), dict(xfd={0: 127}, mutes=1 << 0),
    dict(machines=[X.SAMPLER] * 6 + [3, 4, 8, 9, 10, 11], knob=1 << 6),  # a solo left on a track no sampler any more
    dict(machines=[X.SAMPLER] * 6 + [3, 4, 8, 9, 10, 11], marks={6: ON}),
]


@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_mixer_is_shown_what_the_mixtime_image_shows_it(fast, old, case):
    got, _ = scene(fast, **CASES[case])
    want, _ = scene(old, **CASES[case])
    assert got == want
    assert got[0] == 0x8000DBD0 and got[1] and got[2]


def test_the_idle_block_goes_straight_to_the_mixer_for_a_fraction_of_the_work(fast, old):
    (_, n), (_, m) = scene(fast), scene(old)
    print("idle block: %d instructions, %d on the mixtime image" % (n, m))
    assert n * 3 < m
    (_, n2), (_, m2) = scene(fast, mutes=1 << 3), scene(old, mutes=1 << 3)
    assert n2 <= m2  # with work to do, no dearer


def test_a_pattern_mute_of_the_fx_track_alone_is_still_idle(fast):
    assert scene(fast, pattern=1 << 12)[1] == scene(fast)[1]


def test_stocks_mixer_writes_nothing_of_the_block(official):
    m = W.Mixer(official.section(3))
    busy = np.random.default_rng(5).integers(-2 ** 26, 2 ** 26, (8, 32))
    m.run(busy, pan=64, delay=100, reverb=100, blocks=1)
    was = bytes(m.mc.read(W.PARAMS, 0x800))
    assert m.mc.call(mm.MIX, 0, 0, W.PARAMS) == mm.BUS_L
    assert bytes(m.mc.read(W.PARAMS, 0x800)) == was


def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=34, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=33, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("7d7312c7")  # the mixtime image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_AMUTE, mm.CAVE_ALOCK, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_PROF, mm.CAVE_FAST]  # the analog mute's compile: its runs
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))  # a call of one of them, moved
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
            and not moved(k)] == []
    print("fast image", hashlib.sha256(raw).hexdigest())
