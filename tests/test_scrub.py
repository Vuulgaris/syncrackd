"""The scrub image (engine/sampler.h, SCRUB): the lock image with STRT and LEN followed on a stretched note.


A turn that put the region's far
end behind the place set duck and waited for play()'s fade, which a stretched note never runs. Here:
  - a stretched loop follows LEN and then STRT after such a turn; on the lock image it is stuck;
  - a stretched one-shot so stopped goes down over a block;
  - a note not stretched, and a stretched one with the knobs at rest, the lock image's to the bit;
  - the main CPU the lock image's.
Emulation only."""

import shutil

import numpy as np
import pytest

import test_pagerec as P
import test_stretch as X
from test_fade import LENGTH, LOOP, SAMPLE, START
from test_quick import ST, Folded
from tools import build_engine, build_main
import test_hits as H

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

POS, PLAYING, PC, DUCK = 8, 20, 44, 69          # struct st


@pytest.fixture(scope="module")
def lock(official):
    return build_engine.patched_image(official.section(7), lock=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), scrub=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def run(built, loop, moves, blocks, stretched=True, x=None):
    """Track 0 on x, its knobs moved at the blocks `moves` says. -> its output, and (place, pc, duck, playing) a block."""
    x = X.tone() if x is None else x
    e = P.engine(built, pool={0: x, 1: x})
    for slot, v in {SAMPLE: H.PK.knob_of(0), P.MODE: 0, P.TUNE: 64, LENGTH: 127, START: 0, LOOP: loop,
                    24: X.sent24(64) if stretched else 0}.items():
        e.set_slot(0, slot, v)
    e.set_note(0, 60)
    st = e.voice(0) + ST
    out, state = [], []
    for b in range(blocks):
        for slot, v in moves.get(b, {}).items():
            e.set_slot(0, slot, v)
        out.append(e.block(1 if b == 0 else 0, 0)[0])
        state.append((e.mc.r32(st + POS) >> 12, e.mc.r32(st + PC), e.mc.read(st + DUCK, 1)[0], e.mc.r32(st + PLAYING)))
    return np.concatenate(out).astype(np.int64), state


SCRUB = {100: {LENGTH: 10}, 160: {START: 64}}     # place about 3,200 when LEN puts the end at about 1,900; then STRT half


def test_a_stretched_loop_follows_len_then_strt(lock, engine):
    for built, fixed in ((lock, False), (engine, True)):
        y, s = run(built, 1, SCRUB, 260)
        after_len, after_strt = s[150], s[259]
        print("%s: after LEN place %d pc %d duck %d; after STRT place %d pc %d duck %d"
              % (("lock", "scrub")[fixed], *after_len[:3], *after_strt[:3]))
        if fixed:
            assert after_len[2] == 0 and after_len[0] < 2000                    # back inside the short region
            assert after_strt[2] == 0 and after_strt[1] == 12000 and 12000 <= after_strt[0] < 12000 + 1100
            assert np.abs(y[-32 * 20:]).max() > 0                               # still sounding
        else:
            assert after_len[2] == 1 and after_strt[2] == 1 and after_strt[1] == 0   # the fault: stuck until a trig


def test_a_stretched_one_shot_so_stopped_goes_down(engine):
    y, s = run(engine, 0, {100: {LENGTH: 10}}, 140)
    stop = next(b for b in range(101, 140) if not s[b][3])
    last = y[32 * stop:32 * stop + 32]
    print("stopped in block %d; its last frames %s, the note's peak %d" % (stop, last[-4:], np.abs(y).max()))
    assert stop <= 103 and np.abs(last[-4:]).max() < np.abs(y).max() / 8 and not y[32 * (stop + 1):].any()


@pytest.mark.parametrize("loop, stretched, moves", [(1, False, SCRUB), (0, False, {100: {LENGTH: 10}}),
                                                    (1, True, {}), (2, True, {})])
def test_the_lock_images_to_the_bit(lock, engine, loop, stretched, moves):
    a, _ = run(lock, loop, moves, 260, stretched)
    b, _ = run(engine, loop, moves, 260, stretched)
    assert np.array_equal(a, b) and a.any()


def test_the_main_cpu_is_the_lock_images(official):
    assert build_main.patched_image(official.section(3), xfade=55)[0] == build_main.patched_image(official.section(3), xfade=54)[0]
