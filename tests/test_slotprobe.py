"""The slotprobe image, a tool: the spread image with locks on knob slots 0, 55 and 70 made and shown."""
import shutil

import pytest

import test_trig as T
from tools import build_main

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def probe(official):
    build_main.EXTRA_DEFS = ("SLOTPROBE",)
    try:
        return build_main.patched_image(official.section(3), xfade=59)
    finally:
        build_main.EXTRA_DEFS = ()


@pytest.mark.parametrize("track", [0, 2])
def test_d_f_and_g_show_the_block_words_with_no_step_held(probe, track):
    r = T.A.page(probe, track)
    r.mc.map(0x80003000, 0x1000)
    r.mc.map(0x80002000, 0x1000)
    base = 0x800021b0 + 142 * track + 28
    for slot, word in ((0, 0x1234), (55, 0xbeef), (70, 0x0a0b)):
        r.mc.write(base + 2 * slot, word.to_bytes(2, "big"))
    says = [s for _, _, s in r.show()]
    for name, value in (("B00", "1234"), ("B55", "BEEF"), ("B70", "0A0B")):
        assert name in says and value in says
    assert "PROF" not in says


def test_g_with_steps_held_makes_and_takes_off_the_three_locks_by_stocks_routines(probe):
    import test_gear as G
    import test_stsw as S
    from test_reclock import NONE
    r = T.trig(probe, 3)
    S.sampling(r, probe)
    G.geared(r, [256, -256])
    r.hold(5, 9)
    G.twist(r, 7, 1)
    for step in (5, 9):
        assert [r.lock_at(step, s) for s in (0, 55, 70)] == [0x1080, 0x1180, 0x1280]
        assert r.lock_at(step, 17) == NONE and r.lock_at(step, 24) == NONE  # nothing else of the step's
    says = [s for _, _, s in r.show()]
    assert all(t in says for t in ("L00", "1080", "L55", "1180", "L70", "1280"))
    G.twist(r, 7, -1)
    for step in (5, 9):
        assert [r.lock_at(step, s) for s in (0, 55, 70)] == [NONE] * 3
