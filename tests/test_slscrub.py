"""The slscrub image (engine/sampler.h, SLSCRUB): the scrub image with STRT and LEN followed on a slice.

On request. The slice image left a slice's knobs
alone while it played. Here:
  - a looping slice, stretched and not, follows LEN and then STRT to where a new trig with those knobs would start;
    on the scrub image it stays where its note began;
  - whole-sample notes with the knobs moved, and slices at rest, the scrub image's to the bit;
  - the main CPU the lock image's.
Emulation only."""

import shutil

import numpy as np
import pytest

import test_hits as H
import test_pagerec as P
import test_stretch as X
from test_fade import LENGTH, LOOP, SAMPLE, START
from test_quick import ST, Folded
from tools import build_engine, build_main

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

POS, PA, PB, PC, DUCK = 8, 36, 40, 44, 69       # struct st
SLCE = 0x80 / 256                               # slot 24 as sent: KEYS on slices (SLICE_BIT), REC off
SLST = ((0x80 | 64) << 8 | 0xc0) / 256          # and stretched, SPD 64
MOVES = {100: {LENGTH: 10}, 160: {START: 64}}


@pytest.fixture(scope="module")
def scrub(official):
    return build_engine.patched_image(official.section(7), scrub=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), slscrub=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def run(built, word, note, moves, blocks, loop=1, retrig=False):
    """Track 0 on a tone, slot 24 `word`, its knobs moved at the blocks `moves` says; with retrig, a trig and three more
    block. -> its output, and (place, pa, pb, pc, duck) a block."""
    x = X.tone()
    e = P.engine(built, pool={0: x, 1: x})
    for slot, v in {SAMPLE: H.PK.knob_of(0), P.MODE: 0, P.TUNE: 64, LENGTH: 127, START: 0, LOOP: loop, 24: word}.items():
        e.set_slot(0, slot, v)
    e.set_note(0, note)
    st = e.voice(0) + ST
    out, state = [], []
    for b in range(blocks + 3 * retrig):
        for slot, v in moves.get(b, {}).items():
            e.set_slot(0, slot, v)
        out.append(e.block(1 if b in (0, blocks) else 0, 0)[0])
        state.append(tuple(e.mc.r32(st + o) for o in (POS, PA, PB, PC)) + (e.mc.read(st + DUCK, 1)[0],))
    return np.concatenate(out).astype(np.int64), state


@pytest.mark.parametrize("word", [SLST, SLCE], ids=["SLST", "SLCE"])
def test_a_looping_slice_follows_len_then_strt(scrub, engine, word):
    for built, fixed in ((scrub, False), (engine, True)):
        y, s = run(built, word, 62, MOVES, 260, retrig=True)
        start, followed, fresh = s[50], s[259], s[-1]
        print("%s: began pc %d; after the moves pa %d pb %d pc %d place %d; a trig with them pa %d pb %d pc %d"
              % (("scrub", "slscrub")[fixed], start[3], followed[1], followed[2], followed[3], followed[0] >> 12, *fresh[1:4]))
        if fixed:
            assert followed[1:4] == fresh[1:4] and followed[3] != start[3] and followed[4] == 0
            assert followed[1] <= followed[0] >> 12 < followed[2] and np.abs(y[-32 * 30:-32]).max() > 0
        else:
            assert followed[3] == start[3] != fresh[3]                  # stays where its note began


@pytest.mark.parametrize("word, note, moves", [(0, 60, MOVES), (X.sent24(64), 60, MOVES), (SLST, 63, {}), (SLCE, 57, {})],
                         ids=["CHRO moved", "CHST moved", "SLST at rest", "SLCE at rest"])
def test_the_scrub_images_to_the_bit(scrub, engine, word, note, moves):
    a, _ = run(scrub, word, note, moves, 260)
    b, _ = run(engine, word, note, moves, 260)
    assert np.array_equal(a, b) and a.any()


def test_the_main_cpu_is_the_lock_images(official):
    assert build_main.patched_image(official.section(3), xfade=56)[0] == build_main.patched_image(official.section(3), xfade=54)[0]
