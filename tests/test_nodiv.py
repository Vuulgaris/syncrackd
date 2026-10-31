"""The nodiv image: the copy image with the mixer link's crossfade shares made without the CPU's divide, exactly."""
import hashlib
import shutil

import numpy as np
import pytest

import test_fast as F
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=38)


@pytest.fixture(scope="module")
def copy(official):
    return build_main.patched_image(official.section(3), xfade=37)


def div127(p):
    """engine/sampler.h's div127, in 32-bit unsigned arithmetic."""
    p = np.asarray(p, dtype=np.uint64)
    q = ((p + (p >> 7) + (p >> 14) + (p >> 21)) >> 7) & 0xffffffff
    r = (p - q * 127) & 0xffffffff
    for _ in range(4):
        up = r >= 127
        q, r = q + up, np.where(up, r - 127, r)
    assert not (r >= 127).any()
    return q


def test_div127_is_the_divide_for_every_volume_times_every_share():
    p = np.arange(0, 65536 * 128, dtype=np.uint64)  # a volume word (16 bits) times a share (0..127)
    assert (div127(p) == p // 127).all()


def test_and_far_past_it():
    rng = np.random.default_rng(1)
    p = np.concatenate([rng.integers(0, 2 ** 30, 2_000_000, dtype=np.uint64), np.arange(2 ** 30 - 4096, 2 ** 30, dtype=np.uint64)])
    assert (div127(p) == p // 127).all()


@pytest.fixture(scope="module")
def rigs(main, copy):
    return F.rig(main), F.rig(copy)


CASES = [dict(xfd={t: x}) for t in (0, 3, 7) for x in (1, 2, 40, 63, 64, 126, 127)] + \
        [dict(xfd={2: 40}, mutes=1 << 3), dict(xfd={2: 40, 5: 90}), dict(xfd={1: 30}, knob=1 << 4), dict(xf=[0] * 9 + [50, 0, 0]),
         dict(xfd={4: 70}, marks={4: 0x35}), dict(xfd={0: 127}, mutes=1 << 0), dict(), dict(mutes=1 << 9), dict(pattern=1 << 5)]


@pytest.mark.parametrize("case", range(len(CASES)))
@pytest.mark.parametrize("seed", [6, 11])
def test_the_mixer_is_shown_what_the_copy_image_shows_it(rigs, case, seed):
    fast, old = rigs
    got, _ = F.scene(fast, seed=seed, **CASES[case])
    want, _ = F.scene(old, seed=seed, **CASES[case])
    assert got == want and got[0] == 0x8000DBD0


def test_the_link_has_no_divide_and_lives_in_its_own_run(main, copy):
    image, syms = main
    assert mm.CAVE_LINK2[0] <= syms["mix_link"] < mm.CAVE_LINK2[1]
    run = image[mm.off(mm.CAVE_LINK2[0]):mm.off(mm.CAVE_LINK2[1])]
    assert not any(run[k:k + 2] == b"\x4c\x40" or run[k:k + 2] == b"\x4c\x41" or run[k:k + 2] == b"\x4c\x46" for k in range(0, len(run), 2))
    stock = copy[0]
    assert image[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])] != stock[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])]  # the old run left as stock has it


def test_the_image(official_path, official, main, copy):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=38, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=37, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("681d603c")  # the copy image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0] and old == copy[0]
    assert new[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])] == official.section(3)[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])]
    spans = [mm.CAVE, mm.CAVE_LINK2, mm.CAVE_SPLIT, mm.CAVE_AMUTE, mm.CAVE_ALOCK, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_PROF, mm.CAVE_FAST]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))
    assert [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
            and not moved(k)] == []
    print("nodiv image", hashlib.sha256(raw).hexdigest())
