"""The trim image (engine/sampler.h, TRIM): a pitched note, a fade and a loop's blend for less of the audio CPU's block.


Here, against the hits image's engine (the hitui image's section 7):
  - the fade pass makes the hits image's frames and leaves its gain and step as it does, to the bit;
  - at a sample's own pitch, eight stereo loops trigged again and again, the sound is the hits image's to the bit;
    and with the slots' frames made new between notes, still (a blend kept is never one of other frames);
  - pitched, a frame is within what the row's numbers add up to of the hits image's;
  - a note whose seam is the one written has its blend at once, and it is the one the hits image writes again;
  - what it costs, eight stereo tracks looping, trigged together.
Emulation only. What it is in time, and that it sounds right, is the unit's to say."""

import shutil

import numpy as np
import pytest

import test_pagerec as P
import test_stereo as T
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_quick import Folded
from tools import audiomap as m
from tools import build_engine, params

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ST, S_XN = 1712, 84                     # a voice's sampler state, and the blend's frames written in it
XF, XF_STRIDE, XF_N = 0x44062000, 0x800, 352
XF_FRAMES = 16 + 4 * XF_N               # a voice's blend: the seam's four longs, then the left's frames and the right's
OUT, RIGHT = 0x44070000, 0x44070100     # free memory for the fade's two buffers in a call of it
CYCLE = 90                              # blocks between trigs
ONE = 65536                             # a step of a 16-bit frame, as a track's buffer has it


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def hits(stock):
    return build_engine.patched_image(stock, hits=True)


@pytest.fixture(scope="module")
def trim(stock):
    return build_engine.patched_image(stock, trim=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def render(image, factory, note, blocks, change=(), **knobs):
    """Eight stereo tracks looping, trigged together every CYCLE blocks from the first: -> each block's cost, the
    sound (the left after the last stage, the right channels as the main CPU reads them), and each block's blend
    count of every voice. change: blocks before which every slot's frames are made new."""
    r = Rig(image)
    rng, new = np.random.default_rng(11), np.random.default_rng(12)
    r.load_pool({k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
    T.samplers(r, factory, loop=knobs.get("loop", 1))
    for t in range(8):
        r.set_slot(t, SAMPLE, 64 + t % 3)
        r.set_slot(t, START, knobs.get("start", 0))
        r.set_slot(t, LENGTH, knobs.get("length", 127))
        r.set_note(t, note)
    r.block(0, 0)
    cost, sound, xn = [], [], []
    for b in range(blocks):
        if b in change:
            r.load_pool({k: new.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
        _, _, left = r.block(0xff if b % CYCLE == 0 else 0, 0)
        cost.append(sum(r.cost.values()))
        sound.append(np.concatenate([left] + [r.right(t)[None] for t in range(8)]))
        xn.append([r.mc.r32(m.VOICES + m.VOICE_SIZE * t + ST + S_XN) >> 16 for t in range(8)])
    return np.array(cost), np.concatenate(sound, axis=1).astype(np.int64), np.array(xn), r


def test_the_fade_is_the_hits_images_to_the_bit(hits, trim):
    """fade_run, the hits image's and this one's, on the same frames: any gain, a fade in to its end and past it, a
    fade out to nothing and on, a gain already where it is held, one channel or two."""
    engines = [(P.engine(b).mc, b[1]) for b in (hits, trim)]
    rng = np.random.default_rng(14)
    note = OUT + 0x400
    for trial in range(200):
        g = int(rng.choice([0, 4096, int(rng.integers(0, 4097))]))
        step = int(rng.choice([64, -32, 7, -500, 0, 1, -1, 4095, -4096, 200, 4096 // 64]))
        n, end = int(rng.integers(0, 33)), int(rng.integers(0, 33))
        stereo = bool(trial % 3)
        left, right = (rng.integers(-2 ** 31, 2 ** 31, 32).astype(">i4").tobytes() for _ in range(2))
        got = []
        for mc, syms in engines:
            mc.write(note, bytes(88))
            mc.write(note + 60, g.to_bytes(2, "big") + (step & 0xffff).to_bytes(2, "big"))
            mc.write(OUT, left)
            mc.write(RIGHT, right)
            mc.call(syms["fade_run"], note, OUT, RIGHT if stereo else 0, n, end)
            got.append((mc.read(OUT, 128), mc.read(RIGHT, 128), mc.read(note + 60, 4)))
        assert got[0] == got[1], (trial, g, step, n, end, stereo)


@pytest.mark.parametrize("knobs", [dict(start=30, length=40), dict(length=40), dict(start=30)])
def test_at_its_own_pitch_the_sound_is_the_hits_images(hits, trim, factory, knobs):
    """Eight stereo loops cut out of their samples (or a start cut, with the fade in), trigged every CYCLE blocks:
    the frames to the bit, where the second note's blend is kept and the hits image writes it again."""
    *_, was, _, _ = render(hits[0], factory, 60, 3 * CYCLE, **knobs)
    *_, now, xn, _ = render(trim[0], factory, 60, 3 * CYCLE, **knobs)
    assert np.array_equal(was, now)


def test_a_blend_of_other_frames_is_never_kept(hits, trim, factory):
    """Every slot's frames made new before the second and third notes: the hits image writes each blend again from
    them, and so does this one. The sound is the same to the bit."""
    change = (CYCLE, 2 * CYCLE)
    _, was, _, _ = render(hits[0], factory, 60, 3 * CYCLE, change=change, start=30, length=40)
    _, now, xn, _ = render(trim[0], factory, 60, 3 * CYCLE, change=change, start=30, length=40)
    assert np.array_equal(was, now)
    assert (xn[CYCLE + 1] < XF_N).all() and (xn[2 * CYCLE + 1] < XF_N).all()    # written again, not believed


def test_a_note_on_the_same_seam_has_its_blend_at_once(hits, trim, factory):
    """The second and third notes: their blends whole once its fade in is over (the hits image's are 44 blocks
    writing), and the same frames as the hits image's when it has written them again."""
    *_, xh, rh = render(hits[0], factory, 60, 3 * CYCLE, start=30, length=40)
    *_, xt, rt = render(trim[0], factory, 60, 3 * CYCLE, start=30, length=40)
    for b in (CYCLE, 2 * CYCLE):
        kept = b + 1 + int(np.argmax((xt[b + 1:] == XF_N).all(axis=1)))       # the note starts the block after its trig
        written = b + 1 + int(np.argmax((xh[b + 1:] == XF_N).all(axis=1)))
        assert (xt[b + 1] < XF_N).all() and kept == b + 3 and written >= b + 44  # after the fade in's two blocks
    for t in range(8):
        a = XF + XF_STRIDE * t
        assert rh.mc.read(a, XF_FRAMES) == rt.mc.read(a, XF_FRAMES)


def test_pitched_a_frame_is_within_a_step_of_the_hits_images(hits, trim, factory):
    """Pitched, the sums' frames are taken with the next in their low half: off by what the row's numbers add up
    to times the low half's 2^-16, about a step of a 16-bit frame, and no more."""
    _, was, _, _ = render(hits[0], factory, 55.25, 2 * CYCLE, start=30, length=40)
    _, now, _, _ = render(trim[0], factory, 55.25, 2 * CYCLE, start=30, length=40)
    d = np.abs(now - was)
    print("pitched: frames off %d of %d, the most %.3f of a step, the mean %.4f" % ((d > 0).sum(), d.size, d.max() / ONE, d.mean() / ONE))
    assert (d > 0).mean() > 0.5 and d.max() < 2 * ONE


def test_what_it_costs(hits, trim, factory):
    """Instructions, eight stereo loops cut out of their samples, trigged together every CYCLE blocks, against the
    hits image's, the second note. Pitched: its trig's block 6,120 fewer, the two of its fade in 8,224 and 8,424
    (the heaviest of all, 117,008, is 108,784), the block its blend is taken back 5,696, the 43 its blend was
    written in 8,272, a steady one 6,144. At its own pitch: the fade in's two 2,272 and 2,280, the blocks the blend
    was written in 2,114, and the block its key is made 448 more, the one block that is: 56 a voice."""
    for note, want in ((55.25, dict(trig=6120, fade=(8224, 8424), after=5696, writing=8272, steady=6144)),
                       (60, dict(trig=0, fade=(2272, 2280), after=-448, writing=2114, steady=0))):
        was, *_ = render(hits[0], factory, note, 2 * CYCLE, start=30, length=40)
        now, *_ = render(trim[0], factory, note, 2 * CYCLE, start=30, length=40)
        b, less = CYCLE, was - now
        got = dict(trig=less[b], fade=(less[b + 1], less[b + 2]), after=less[b + 3],
                   writing=int(np.median(less[b + 5:b + 40])), steady=int(np.median(less[b + 60:b + 80])))
        print("note %s: %s, the heaviest %d -> %d" % (note, got, was[b:].max(), now[b:].max()))
        assert all(np.allclose(got[k], want[k], atol=60) for k in want), got
        assert now[b:].max() < was[b:].max() and less[b:].min() >= -500
