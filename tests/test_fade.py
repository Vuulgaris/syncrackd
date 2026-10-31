"""The "fade" image: the sound engine fades where a sample is cut into (engine/sampler.c built with FADE)."""
import shutil

import numpy as np
import pytest

from emu import sampler_ref as ref
from emu.engine import BLOCK
from tools import audiomap as m
from tools import build_engine
from tools import mainmap as mm
from test_pagerec import engine

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TUNE, SAMPLE, START, LENGTH, LOOP, MODE, DECAY = 18, 19, 20, 21, 22, 23, 25
ONE, IN, OUT = m.FADE_ONE, m.FADE_IN, m.FADE_OUT
BUDGET = 10506  # SY SWARM, instructions a voice a block
FULL = 0x7fffffff  # what a sample plays at since the keep image


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def fade(stock):
    return build_engine.patched_image(stock, fade=True)


@pytest.fixture(scope="module")
def bank(stock):
    return build_engine.patched_image(stock, bank=True)


def make_pool():
    rng = np.random.default_rng(7)
    ramp = np.linspace(-20000, 20000, 6000).astype(np.int16)
    return {0: rng.integers(-32768, 32768, 6000).astype(np.int16), 1: rng.integers(-32768, 32768, 6000).astype(np.int16),
            2: np.full(6000, 20000, dtype=np.int16),  # a steady level: a fade is all there is to see
            3: np.full(6000, 20000, dtype=np.int16),
            4: ramp, 5: ramp,  # ends far from where it begins: a loop of it clicks, once a pass
            6: rng.integers(-32768, 32768, 300).astype(np.int16)}  # short: a loop of it is a tone


POOL = make_pool()


def tail(buf):
    """What the stock amp and mix stages do to a player buffer at a sample's full level, decay at 127."""
    return [((((-((-(1 << 31) * x) >> 23)) >> 8) * FULL) >> 23) >> 8 for x in buf]


def start(built, track=0, note=60, **knobs):
    e = engine(built, pool=POOL)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)  # the other tracks point at an empty slot
    values = {TUNE: 64, SAMPLE: 64, START: 0, LENGTH: 127, LOOP: 0, MODE: 0, DECAY: 127}
    values.update({globals()[k.upper()]: v for k, v in knobs.items()})
    for slot, v in values.items():
        e.set_slot(track, slot, v)
    e.set_note(track, note)
    return e


def render(built, blocks, track=0, note=60, **knobs):
    """-> (left, right): the track's output and the next track's, from the block the note starts in."""
    e = start(built, track, note, **knobs)
    out = np.array([e.block(trig=1 << track if b == 0 else 0) for b in range(blocks + 1)])
    assert not out[0].any()
    return e, out[1:, track, :].ravel(), out[1:, track + 1, :].ravel()


def model(e, blocks, track=0, fades=True, **knobs):
    p = ref.Player(POOL, fade=fades)
    p.inc = e.player(track, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127),
              loop=knobs.get("loop", 0), mode=knobs.get("mode", 0))
    left, right, gains = [], [], []
    for _ in range(blocks):
        for _ in range(1):
            pass
        g0 = p.fade
        l, r = p.block()
        left += tail(l)
        right += tail(r) if r is not None else [0] * BLOCK
        gains.append(g0)
    return np.array(left), np.array(right), p


CASES = [
    dict(),  # the whole sample, once: no fade anywhere
    dict(start=40),  # cut into at the start
    dict(length=60),  # cut off at the end
    dict(start=30, length=50),
    dict(sample=63),  # reversed, whole
    dict(sample=63, start=20, length=50),  # reversed: it starts at the cut end and ends at the cut start
    dict(loop=1),  # a loop of the whole sample
    dict(loop=1, start=10, length=40),
    dict(loop=1, sample=63, length=70),  # a loop played backwards
    dict(loop=2, start=25, length=30),  # ping-pong: a fade in, and no fade at a turn
    dict(mode=1),  # stereo
    dict(mode=1, loop=1, start=5, length=45),
    dict(sample=70, loop=1),  # the short slot: too short for a seam's fades
    dict(sample=70, start=30, length=60),
    dict(sample=66, loop=1, length=90),  # the steady level
    dict(sample=68, loop=1),  # the ramp
]


@pytest.mark.parametrize("note", [60, 67, 50, 84, 36])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_engine_is_the_reference_model_bit_for_bit(fade, case, note):
    knobs = CASES[case]
    e, left, right = render(fade, 44, note=note, **knobs)
    want_l, want_r, p = model(e, 44, **knobs)
    assert np.array_equal(left, want_l)
    if knobs.get("mode") == 1:
        assert np.array_equal(right, want_r) and np.any(right)
    assert np.any(left)


@pytest.mark.parametrize("note", [60, 72, 48])
@pytest.mark.parametrize("knobs", [dict(), dict(sample=63), dict(loop=2), dict(mode=1), dict(mode=1, loop=2, sample=63),
                                   dict(sample=70, loop=1), dict(sample=70, loop=1, length=80)])
def test_where_nothing_is_cut_into_it_is_the_engine_it_was(fade, bank, knobs, note):
    """The whole sample played once, a ping-pong of it, and a loop too short for fades: the bank image's output, to the
    bit.
    """
    _, a, ar = render(fade, 40, note=note, **knobs)
    _, b, br = render(bank, 40, note=note, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


def level(x):
    """Output as a fraction of the steady level's full output."""
    return np.asarray(x, dtype=np.float64) / tail([20000 << 16])[0]


def test_a_note_that_starts_inside_the_sample_fades_in(fade, bank):
    _, a, _ = render(fade, 6, sample=66, start=40)
    _, b, _ = render(bank, 6, sample=66, start=40)
    la, lb = level(a), level(b)
    assert lb[0] == 1.0  # as it was: full from the first frame, a click
    assert la[0] == 0.0 and np.all(np.diff(la[:IN + 1]) > 0)  # now: from nothing, upward
    assert np.allclose(la[:IN], np.arange(IN) / IN, atol=1e-3) and np.all(la[IN:] == 1.0)
    assert np.array_equal(a[IN:], b[IN:])  # and after the fade, the same frames


def test_a_note_that_starts_at_the_samples_start_does_not(fade, bank):
    """A drum keeps its attack."""
    _, a, _ = render(fade, 6, sample=66, length=80)
    assert level(a)[0] == 1.0


def test_a_one_shot_cut_off_inside_the_sample_fades_out_to_its_end(fade, bank):
    _, a, _ = render(fade, 80, sample=66, length=40)
    _, b, _ = render(bank, 80, sample=66, length=40)
    la, lb = level(a), level(b)
    end = int(np.flatnonzero(lb)[-1]) + 1  # as it was: full to the last frame, then nothing
    assert lb[end - 1] == 1.0 and not lb[end:].any()
    assert not la[end:].any() and la[end - 1] < 0.02  # now: all but nothing by the same last frame
    assert np.all(np.diff(la[end - OUT:end]) < 0) and la[end - OUT - 1] == 1.0
    assert np.array_equal(a[:end - OUT], b[:end - OUT])


def test_a_sample_played_to_its_own_end_is_not_faded(fade, bank):
    _, a, _ = render(fade, 80, sample=66, start=30)
    _, b, _ = render(bank, 80, sample=66, start=30)
    assert np.array_equal(a[IN:], b[IN:]) and level(b)[np.flatnonzero(b)[-1]] == 1.0


def jumps(x):
    return np.abs(np.diff(np.asarray(x, dtype=np.int64)))


@pytest.mark.parametrize("knobs", [dict(sample=68, loop=1), dict(sample=68, loop=1, start=20, length=60), dict(sample=59, loop=1),
                                   dict(sample=66, loop=1, mode=1)])  # in stereo SMPL counts pairs: the ramp is the third
def test_a_loops_seam_does_not_click_and_does_not_move(fade, bank, knobs):
    """The ramp ends far from where it begins. As it was, a loop of it jumps there once a pass. Now the sound is down
    before the jump and up after it, and every frame outside those two fades is the frame it was.
    """
    e, a, ar = render(fade, 600, **knobs)
    _, b, br = render(bank, 600, **knobs)
    skip = IN if knobs.get("start") else 0  # a loop cut into at its start fades in first, as any note does
    a, b, ar, br = a[skip:], b[skip:], ar[skip:], br[skip:]
    seams = np.flatnonzero(jumps(b) > jumps(b).max() / 2)  # the old engine's clicks: one a pass
    assert len(seams) >= 3 and len(set(np.diff(seams))) <= 2  # (a pass is a whole number of frames give or take one)
    assert jumps(a).max() < jumps(b).max() / 20  # nowhere a jump like it any more
    differ = np.flatnonzero(a != b)
    for seam in seams[:-1]:  # all that differs is the fade out up to a seam and the fade in after it
        near = differ[(differ > seam - 2 * OUT) & (differ < seam + 2 * OUT)]
        assert near.min() >= seam - OUT - 1 and near.max() <= seam + IN + 1 and len(near) > OUT
        assert abs(int(a[seam])) < abs(int(b[seam])) / 20 or abs(int(b[seam])) < 2 ** 20  # all but silent at the seam itself
    assert all(np.any(np.abs(differ - seam) <= OUT + IN) for seam in seams) and np.all(np.min(np.abs(differ[:, None] - seams[None, :]), axis=1) <= OUT + IN + 1)
    if knobs.get("mode"):
        assert np.array_equal(a != b, ar != br) and np.any(ar)  # stereo: both sides, the same frames


def test_a_loop_of_a_steady_level_dips_at_its_seam_and_nowhere_else(fade, bank):
    """What the fades cost: where there was no click to remove, a dip of 4 ms a pass."""
    _, a, _ = render(fade, 400, sample=66, loop=1)
    _, b, _ = render(bank, 400, sample=66, loop=1)
    la = level(a)
    assert np.all(level(b) == 1.0) and la.min() < 0.02 and np.count_nonzero(la < 1.0) <= 2 * (OUT + IN) + 4


def test_a_ping_pong_turn_is_left_alone(fade, bank):
    _, a, _ = render(fade, 600, sample=68, loop=2)
    _, b, _ = render(bank, 600, sample=68, loop=2)
    assert np.array_equal(a, b)


def test_the_fades_are_as_long_at_any_pitch(fade):
    """Lengths are in frames put out, not frames of the sample."""
    for note in (48, 60, 72):
        _, a, _ = render(fade, 6, note=note, sample=66, start=40)
        la = level(a)
        assert la[0] == 0.0 and la[IN - 1] < 1.0 and np.all(la[IN:IN + 40] == 1.0)


def test_a_new_trig_starts_clean(fade):
    """A fade that was on when the next note came does not carry over."""
    e = start(fade, sample=66, start=40)
    out = [e.block(trig=1 if b in (0, 2) else 0)[0] for b in range(8)]
    first, second = level(np.concatenate(out[1:3])), level(np.concatenate(out[3:]))
    assert first[0] == 0.0 and second[0] == 0.0 and np.all(second[IN:] == 1.0)
    e = start(fade, sample=66, start=40)
    e.block(trig=1)
    e.block()
    e.set_slot(0, START, 0)  # the next note starts at the sample's start: no fade
    e.block(trig=1)
    assert level(e.block()[0])[0] == 1.0


def test_cost_on_the_audio_cpu(fade, bank):
    """Instructions in the dearest block of a run, the whole voice loop, over the bank image's engine."""
    def count(built, blocks, **knobs):
        e = start(built, **knobs)
        e.block(trig=1)
        worst = 0
        for _ in range(blocks):
            n0 = e.mc.insns
            e.block()
            worst = max(worst, e.mc.insns - n0)
        return worst
    plain = count(fade, 6) - count(bank, 6)  # no fade on: two tests a frame
    fading = count(fade, 400, sample=66, loop=1, mode=1)  # a stereo voice at its loop's seam
    over = fading - count(bank, 400, sample=66, loop=1, mode=1)
    assert (plain, over) == COST and fading < 8 * BUDGET


COST = (313, 921)  # a block with no fade on, and the dearest block of a stereo loop


def test_the_code_is_in_a_fourth_run_and_the_image_differs_there_only(official_path, official, stock, fade, bank):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, fade=True)
    assert sorted(regions) == [3, 7] and built.section(7) == fade[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    banked = build.build(official_path, log=quiet, bank=True)[2]
    assert built.section(3) == banked.section(3)  # the main CPU's program is the bank image's
    lo, hi = m.FADE_CAVES["w"]
    assert banked.section(7)[m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
    assert stock[m.off(lo) - 2:m.off(lo)] == b"\x4e\x75" and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
    assert all(lo <= fade[1][s] < hi for s in ("faded", "fade_move", "fade_on", "scale", "locate"))
    spans = list(m.CAVES.values()) + list(m.REC_CAVES.values()) + list(m.FADE_CAVES.values())
    assert not any(a < d and c < b for k, (a, b) in enumerate(spans) for c, d in spans[k + 1:])
    spans += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    diff = [k for k in range(len(stock)) if stock[k] != built.section(7)[k]]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in spans) for k in diff)
