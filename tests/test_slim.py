"""The slim image (engine/sampler.h, SLIM): the trim image for less again, the sound the same to the bit.

The maintainer, 2026-10-14, after the trim image on the maintainer's unit ("def tell it sbetter ... but still cant trend to max at the
wrong times"): "do hits off when unused, and tightening the pitched sum" (the second: DEL does not reach the audio CPU, see
engine/sampler.h, SLIM). Here, against the trim image's engine:
  - the sound to the bit: eight tracks, stereo and mono, pitched up and down and at their own pitch, forward and
    backward, one-shot, loop and ping-pong, cut out of their samples and not;
  - what it costs.
Emulation only."""

import shutil

import numpy as np
import pytest

import test_pagerec as P
import test_stereo as T
from stereo_rig import Rig
from test_fade import LENGTH, LOOP, SAMPLE, START
from test_quick import Folded
from tools import audiomap as m
from tools import build_engine, params

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

CYCLE = 90


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def trim(stock):
    return build_engine.patched_image(stock, trim=True)


@pytest.fixture(scope="module")
def slim(stock):
    return build_engine.patched_image(stock, slim=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def render(image, factory, note, blocks, mono=False, back=False, own=False, **knobs):
    """Eight tracks, trigged together every CYCLE blocks from the first: -> each block's cost, the sound (the left
    after the last stage, the right channels as the main CPU reads them), the hits word, and the rig. mono: each
    sample's right slot the shorter, so none has a right channel. back: every sample played backward. own: every
    track at the note, none a little apart."""
    r = Rig(image)
    rng = np.random.default_rng(11)
    r.load_pool({k: rng.integers(-30000, 30000, 4000 if mono and k % 2 else 9000).astype(np.int16) for k in range(8)})
    T.samplers(r, factory, loop=knobs.get("loop", 1))
    for t in range(8):
        r.set_slot(t, SAMPLE, 63 - t % 3 if back else 64 + t % 3)
        r.set_slot(t, START, knobs.get("start", 0))
        r.set_slot(t, LENGTH, knobs.get("length", 127))
        r.set_note(t, note if own else note + (t % 4) * 3.1)
    r.block(0, 0)
    cost, sound, word = [], [], []
    for b in range(blocks):
        _, _, left = r.block(0xff if b % CYCLE == 0 else 0, 0)
        cost.append(sum(r.cost.values()))
        sound.append(np.concatenate([left] + [r.right(t)[None] for t in range(8)]))
        word.append(r.mc.r32(m.HIT_BOX))
    return np.array(cost), np.concatenate(sound, axis=1).astype(np.int64), np.array(word, dtype=np.uint64), r


CASES = [
    dict(note=55.25),
    dict(note=55.25, start=30, length=40),
    dict(note=67, loop=2),
    dict(note=40, loop=0),
    dict(note=55.25, back=True, start=30, length=40),
    dict(note=79, back=True, loop=2),
    dict(note=55.25, mono=True, start=30, length=40),
    dict(note=44, mono=True, back=True),
    dict(note=60, start=30, length=40),
]


@pytest.mark.parametrize("case", CASES, ids=[",".join("%s=%s" % kv for kv in c.items()) for c in CASES])
def test_the_sound_is_the_trim_images_to_the_bit(trim, slim, factory, case):
    """Tracks a few steps apart in pitch, so their stretches end at different frames; one-shots that reach their
    sample's end and are summed from what the note's start wrote out of it; loops that go into their blends."""
    note = case["note"]
    knobs = {k: v for k, v in case.items() if k != "note"}
    _, was, _, _ = render(trim[0], factory, note, 2 * CYCLE, **knobs)
    _, now, _, _ = render(slim[0], factory, note, 2 * CYCLE, **knobs)
    assert np.array_equal(was, now)


def test_what_it_costs(trim, slim, factory):
    """Instructions, eight stereo tracks a little apart in pitch, against the trim image's, the second note: a steady
    block, the trig's, the fade in's two, and the heaviest. Then the same with every sample mono (the trim image's, to the instruction), and at a
    sample's own pitch on every track (a frame of the sample's own: 1 fewer)."""
    got = {}
    for name, note, kw in (("stereo", 55.25, {}), ("cut", 55.25, dict(start=30, length=40)), ("mono", 55.25, dict(mono=True)),
                           ("own", 60, dict(own=True))):
        was, *_ = render(trim[0], factory, note, 2 * CYCLE, **kw)
        now, *_ = render(slim[0], factory, note, 2 * CYCLE, **kw)
        b, less = CYCLE, was - now
        got[name] = int(np.median(less[b + 60:b + 80]))
        print("%s: steady %d, trig %d, fade %d %d, the heaviest %d -> %d, least saved %d" % (
            name, got[name], less[b], less[b + 1], less[b + 2], was[b:].max(), now[b:].max(), less[b:].min()))
        if name == "mono":
            assert (less == 0).all()                            # one channel's frames are the trim image's, step for step
        else:
            assert now[b:].max() < was[b:].max() and less[b:].min() > 0
    print(got)
