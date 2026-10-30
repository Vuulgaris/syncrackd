"""The "stereo" image: a stereo sample on one track (engine/sampler.c and engine/rightfill.c built with ONETRACK).

On request. Up to the save image a stereo
sample takes two tracks: its right channel is put in the next track's buffer, which goes through
that track's own copy of the audio CPU's four stages and is panned hard right by the main CPU. Here
the right channel stays with its track. docs/STEREO.md, "One-track stereo", has the design.

What is held here, all of it in emulation:
  - Audio CPU. The right channel comes out of stock's four stages exactly as a stock track would
    have made it, fed that signal with those knobs and trigs: the real interrupt of the built image
    against the stock interrupt, bit for bit, with the knobs, trigs, MODE and machines moving. The
    left channels and every other machine are what they were.
  - Main CPU. The real mixer with its four right-hand passes pointed at a second set of buffers:
    the left side of every sum is stock's of the left buffers, the right side stock's of the right
    ones, and with the second set a copy of the first it is stock bit for bit.
  - Across. What the audio CPU leaves in the window is what the main CPU's routine puts in the
    second set, and a window that does not answer leaves every track as it was: mono.

Not held here, and not to be had without the unit: that the two stretches of the window are real
shared memory, what the right channels cost either CPU in time, and whether the main CPU always
reads a right channel before the audio CPU writes the next.
"""
import re
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC

import test_mixer_whole as W
from emu.machine import Machine, boundaries
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode, params
from tools import mainmap as mm
from stereo_rig import AFTER_AMP, AFTER_VOICES, AMP_CALL, STAGE_KNOBS, Rig, stock_of
from test_meter import FeedRig
import test_pagerec as P
from test_pagerec import HookEngine
from test_recorder import frames, make_block
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER, TONE = 44, 4
TUNE, SAMPLE, START, LENGTH, LOOP, MODE, DECAY = 18, 19, 20, 21, 22, 23, 25
ST = 1712                   # a voice's sampler state
RVALID, RLIVE = 50, m.RLIVE


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stereo(stock):
    return build_engine.patched_image(stock, stereo=True)


@pytest.fixture(scope="module")
def pitch(stock):
    return build_engine.patched_image(stock, pitch=True)


@pytest.fixture(scope="module")
def factory(official):
    """The filter and amp pages as a new project has them."""
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


def samplers(r, factory, **knobs):
    """Eight sampler tracks on an empty slot, the stages at their factory settings, then `knobs` on every track."""
    for t in range(8):
        r.set_machine(t, SAMPLER)
        r.set_note(t, 60)
        for s in range(18, 27):
            r.set_slot(t, s, 0)
        for s, v in list(factory.items()) + [(TUNE, 64), (SAMPLE, 64 + 63), (LENGTH, 127), (DECAY, 127)]:
            r.set_slot(t, s, v)
        for k, v in knobs.items():
            r.set_slot(t, globals()[k.upper()], v)
        r.set_cutoff(t, 0x60000000)


def pool():
    """Four stereo samples, slots 2n and 2n + 1. The last one's right slot is the shorter: it has no right channel."""
    rng = np.random.default_rng(11)
    out = {k: rng.integers(-30000, 30000, 2400 + 100 * k).astype(np.int16) for k in range(6)}
    out[6] = rng.integers(-30000, 30000, 2000).astype(np.int16)
    out[7] = rng.integers(-30000, 30000, 900).astype(np.int16)
    return out


def knobs_of(rng, tracks=range(8)):
    """A setting of every stage knob of some tracks, as a list a rig can be given."""
    sets = [(t, slot, int(rng.integers(0, top + 1))) for t in tracks for slot, top in STAGE_KNOBS.items()]
    cuts = [(t, int(rng.integers(0, 0x7f000000))) for t in tracks]
    return sets, cuts, int(rng.integers(0, 256))


def scenario(seed, blocks=80):
    """Blocks of (what to set before it, trig, release): eight sampler tracks, some stereo, with the stage knobs,
    the notes, MODE and the machines moving. The same list drives the built image and stock."""
    rng = np.random.default_rng(seed)
    stereo_tracks = int(rng.integers(1, 256))
    steps = []
    for n in range(blocks):
        sets, cuts, flags, machines, notes = [], [], None, [], []
        if n == 0:
            for t in range(8):
                machines.append((t, SAMPLER))
                notes.append((t, float(rng.choice([60, 60, 48, 67, 55.25, 72]))))
                sets += [(t, s, 0) for s in range(18, 27)]
                sets += [(t, TUNE, 64), (t, SAMPLE, 64 + int(rng.integers(0, 4))), (t, LENGTH, 127), (t, DECAY, 127),
                         (t, LOOP, int(rng.integers(0, 3))), (t, MODE, stereo_tracks >> t & 1)]
        if n == 0 or rng.random() < 0.06:
            s2, cuts, flags = knobs_of(rng)
            sets += s2
        if n and rng.random() < 0.08:                   # MODE turned on a track: its right channel goes or comes
            t = int(rng.integers(0, 8))
            stereo_tracks ^= 1 << t
            sets.append((t, MODE, stereo_tracks >> t & 1))
        if n and rng.random() < 0.05:                   # another machine on a track, or the sampler back
            t = int(rng.integers(0, 8))
            machines.append((t, TONE if rng.random() < 0.6 else SAMPLER))
        if n and rng.random() < 0.05:
            notes.append((int(rng.integers(0, 8)), float(rng.uniform(40, 80))))
        trig = int(rng.integers(0, 256)) if n == 1 or rng.random() < 0.15 else 0
        release = int(rng.integers(0, 256)) if rng.random() < 0.08 else 0

        def prepare(r, sets=sets, cuts=cuts, flags=flags, machines=machines, notes=notes):
            for t, mtype in machines:
                r.set_machine(t, mtype)
            for t, note in notes:
                r.set_note(t, note)
            for t, slot, v in sets:
                r.set_slot(t, slot, v)
            for t, v in cuts:
                r.set_cutoff(t, v)
            if flags is not None:
                r.extra[0x1a8 - 0x170] = flags
        steps.append((prepare, trig, release))
    return steps


def played(image, script, earlier=False):
    """The built image through the script. -> a list a block of dict(voices, waiting, left, mask, right).
    earlier: an image from before this one, which leaves nothing in the window to say."""
    r = Rig(image)
    r.load_pool(pool())
    out = []
    for prepare, trig, release in script:
        if prepare:
            prepare(r)
        voices, waiting, left = r.block(trig, release)
        mask = 0 if earlier else r.mask()
        out.append(dict(voices=voices, waiting=waiting, left=left, mask=mask, right={t: r.right(t) for t in range(8) if mask >> t & 1}))
    return r, out


def stretches(masks, t):
    """[first block, one past the last) of every run of blocks in which track t has a right channel."""
    out, n = [], 0
    while n < len(masks):
        if masks[n] >> t & 1:
            end = n
            while end < len(masks) and masks[end] >> t & 1:
                end += 1
            out.append((n, end))
            n = end
        else:
            n += 1
    return out


# ---- the audio CPU: a right channel is what stock would have made of it ------------------------------

@pytest.mark.parametrize("seed", range(6))
def test_a_right_channel_comes_out_as_a_stock_track_would_have_made_it(stock, stereo, seed):
    """The built image's interrupt, then stock's on the same signals. The left: stock fed what the voices made.
    A right channel, for as long as its track has one: stock fed the left up to the block it came on and the
    right from then, on that track. Bit for bit, the stage knobs, trigs, MODE and machines moving."""
    image, _ = stereo
    script = scenario(seed)
    _, got = played(image, script)
    voices = np.array([b["voices"] for b in got])
    masks = [b["mask"] for b in got]
    assert np.array_equal(np.array([b["left"] for b in got]), stock_of(stock, script, voices))
    checked = loud = 0
    for t in range(8):
        for a, b in stretches(masks, t):
            fed = voices[:b].copy()
            fed[a:b, t] = [got[n]["waiting"][t] for n in range(a, b)]
            want = stock_of(stock, script[:b], fed)
            for n in range(a, b):
                assert np.array_equal(got[n]["right"][t], want[n][t]), (t, n, a)
                checked += 1
                loud += bool(got[n]["right"][t].any())
    assert checked > 40 and loud > 20


SWARM = 117348              # the audio CPU's whole interrupt with stock's heaviest machine on all eight tracks (docs/FINDINGS.md, Phase 5)


def test_all_eight_tracks_stereo(factory, stock, stereo):
    """Eight stereo samples at once, which is what it is for. Every right channel is stock's of it."""
    def script(mode):
        def first(r):
            samplers(r, factory, loop=1, mode=mode)
            for t in range(8):
                r.set_slot(t, SAMPLE, 64 + t % 3)
        return [(first, 0, 0), (None, 0xff, 0)] + [(None, 0, 0)] * 22

    image, _ = stereo
    r, got = played(image, script(1))
    assert [b["mask"] for b in got[2:]] == [0xff] * 22 and got[0]["mask"] == 0
    voices = np.array([b["voices"] for b in got])
    assert np.array_equal(np.array([b["left"] for b in got]), stock_of(stock, script(1), voices))
    fed = voices.copy()
    for n in range(2, 24):
        fed[n] = got[n]["waiting"]
    want = stock_of(stock, script(1), fed)
    for n in range(3, 24):                              # from the block after the one they all came on in: one reference for all
        for t in range(8):
            assert np.array_equal(got[n]["right"][t], want[n][t]) and got[n]["right"][t].any()


def whole(image, factory, stereo_tracks, note, mode=1, earlier=False):
    """Instructions of an interrupt, a steady block: eight sampler tracks looping, `stereo_tracks` of them on a
    sample, the rest on an empty slot. -> (the voices, stock's stages, the last stage's call, all of it)"""
    def first(r):
        samplers(r, factory, loop=1, mode=mode)
        for t in range(stereo_tracks):
            r.set_slot(t, SAMPLE, 64 + t % 3)
        for t in range(8):
            r.set_note(t, note)
    r, _ = played(image, [(first, 0, 0), (None, 0xff, 0)] + [(None, 0, 0)] * 10, earlier)
    c = r.cost
    return c[AFTER_VOICES], c[AMP_CALL], c[AFTER_AMP], sum(c.values())


def test_what_the_right_channels_cost_the_audio_cpu(factory, stock, stereo, pitch):
    """Instructions, which are a lower bound on time: the emulator knows nothing of the cache or of how long the
    window takes to answer. Against the one thing known to work on the unit, stock's heaviest machine on all eight
    tracks: SWARM instructions an interrupt."""
    image, _ = stereo
    before, _ = pitch
    # no right channel anywhere: what the image costs a unit that never uses it
    idle, was = whole(image, factory, 8, 60, mode=0), whole(before, factory, 8, 60, mode=0, earlier=True)
    assert idle[1] == was[1] and 0 < idle[2] - was[2] <= 30 and idle[3] <= was[3]      # 23 more in the last stage's call, fewer after the voices
    # the right channels themselves: the first costs the two stages that do all eight tracks a call, each one after it its own two
    # (the third build's copies move more longs a turn: 16,041, 2,703 and 34,962 before it)
    last = [whole(image, factory, n, 60)[2] - idle[2] for n in (1, 2, 8)]
    assert 13800 < last[0] < 14800 and 2300 < last[1] - last[0] < 2700 and 31000 < last[2] < 32500
    # whole interrupts. At a sample's own pitch all eight stereo are under stock's heaviest
    assert whole(image, factory, 8, 60)[3] < 0.66 * SWARM
    # pitched, a stereo voice sums sixteen frames twice a frame. The image's first build made those sums as the pitch
    # image does, and eight tracks of them were 160,319, 1.37 of stock's heaviest: on the unit, "major distortion".
    # The second makes them stock's way, a run of frames a call (tests/test_quick.py): eight were 116,679, 0.99 of
    # it by count, and on the unit's own meter 99 hundredths of a block and at times over, where stock's heaviest is
    # about 88. The third takes 7,905 more off (tests/test_lean.py)
    four, eight = whole(image, factory, 4, 55.25)[3], whole(image, factory, 8, 55.25)[3]
    assert four < 0.69 * SWARM and 0.92 * SWARM < eight < 0.94 * SWARM
    assert eight < whole(before, factory, 8, 55.25, earlier=True)[3]            # less than the pitch image's eight with four right channels


# ---- the audio CPU: everything else is as it was ------------------------------------------------------

@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


@pytest.mark.parametrize("mtype", [t for t in m.TYPE_OF_ENGINE if t != SAMPLER])
def test_a_stock_machine_goes_through_the_interrupt_as_it_did(official, stock, stereo, descs, mtype):
    """Every stock machine on all eight tracks through the whole interrupt, the stage knobs at their factory values:
    what the audio CPU sends is stock's, bit for bit, and the long in the window says no track has a right channel."""
    image, _ = stereo
    track_defaults = {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}
    out = []
    for img in (stock, image):
        b = Rig(img)
        for t in range(m.N_VOICES):
            b.set_defaults(t, mtype, descs)
            b.set_note(t, 50 + 4 * t)
            for slot, v in track_defaults.items():
                b.set_slot(t, slot, v)
            b.set_cutoff(t, 0x60000000)
        blocks = [b.block(0xff if n in (0, 5) else 0, 0xff if n == 8 else 0)[2] for n in range(11)]
        out.append((np.array(blocks), b))
    assert np.array_equal(out[0][0], out[1][0]) and out[0][0].any()
    assert out[1][1].word() == m.rw_word(0)
    assert out[0][1].word() == 0                        # stock leaves that place alone


def voice(e, t):
    at = e.voice(t) + ST
    return dict(rvalid=e.mc.read(at + RVALID, 1)[0], rlive=e.mc.read(at + RLIVE, 1)[0], r=e.mc.r32(at + 4), playing=e.mc.r32(at + 20))


def one_note(image, factory, track, blocks=12, **knobs):
    """One note on one track of a Rig, the other tracks on an empty slot. -> (rig, blocks as played() gives them)"""
    def first(r):
        samplers(r, factory)
        for k, v in knobs.items():
            r.set_slot(track, globals()[k.upper()], v)
    return played(image, [(first, 0, 0), (None, 1 << track, 0)] + [(None, 0, 0)] * blocks)


@pytest.mark.parametrize("track", [0, 7])
def test_a_mono_note_has_no_right_channel_and_nothing_is_written_for_it(stereo, factory, track):
    image, _ = stereo
    r, got = one_note(image, factory, track, sample=64)
    assert {b["mask"] for b in got} == {0}
    assert any(b["left"][track].any() for b in got)
    assert not any(r.mc.read(m.rw_half(h), 64) != bytes(64) for h in range(16))
    assert voice(r, track) == dict(rvalid=0, rlive=0, r=0, playing=1)


@pytest.mark.parametrize("track", [0, 7])
def test_a_stereo_note_has_one_from_the_block_it_starts_in(stereo, factory, track):
    """And the last track can hold one, which it could not while a right channel took the next track."""
    image, _ = stereo
    r, got = one_note(image, factory, track, sample=64, mode=1)
    assert [b["mask"] for b in got] == [0, 0] + [1 << track] * 12      # the trig's block has no note yet
    assert all(b["right"][track].any() and b["left"][track].any() for b in got[2:])
    assert not np.array_equal(got[4]["right"][track], got[4]["left"][track])
    assert voice(r, track)["rlive"] == 1
    # the window: the two halves of this track and the long, and nothing else of the two stretches
    for h in range(16):
        assert (r.mc.read(m.rw_half(h), 64) != bytes(64)) == (h // 2 == track)


def test_a_stereo_sample_whose_right_slot_is_the_shorter_plays_as_one_channel(stereo, factory):
    """Sample 3 of the pool. The engine has always dropped such a right channel: now the main CPU is told there is
    none and puts the left on both sides, where the next track played silence."""
    image, _ = stereo
    r, got = one_note(image, factory, 2, sample=64 + 3, mode=1)
    assert {b["mask"] for b in got} == {0} and any(b["left"][2].any() for b in got)
    assert voice(r, 2)["r"] == 0


def test_turning_mode_takes_the_right_channel_away_and_a_note_brings_it_back(stereo, factory):
    image, _ = stereo

    def mode(v):
        return lambda r: r.set_slot(1, MODE, v)

    def first(r):
        samplers(r, factory)
        r.set_slot(1, SAMPLE, 64)
        r.set_slot(1, MODE, 1)
    script = [(first, 0, 0), (None, 2, 0)] + [(None, 0, 0)] * 4 + [(mode(0), 0, 0)] + [(None, 0, 0)] * 3 + [(mode(1), 0, 0)] + [(None, 0, 0)] * 3 \
        + [(mode(0), 0, 0), (None, 2, 0)] + [(None, 0, 0)] * 3 + [(mode(1), 0, 0)] + [(None, 0, 0)] * 3
    _, got = played(image, script)
    masks = [b["mask"] for b in got]
    assert masks[:10] == [0, 0, 2, 2, 2, 2, 0, 0, 0, 0]         # MODE to mono: gone in that block
    assert masks[10:14] == [2, 2, 2, 2]                          # and back: the note is still a stereo one
    assert masks[14:] == [0] * 9                                 # a note that started mono has no right channel, whatever MODE says after


# ---- the main CPU: the second set of buffers ----------------------------------------------------------

RSET = mm.RIGHT_SET
DMA_FLAG, DMA_STATUS = 0x43bde73c, 0xfc0455fe       # stock's "a transfer was started", and channel 47's status word
SEND, SKIP = mm.RIGHT_HOOK + 12, 0x400a4e74         # after stock's test at the place we take: the audio CPU up, or down
STACK = 0x407ff000


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, stereo=True)


@pytest.fixture(scope="module")
def save3(stock3):
    return build_main.patched_image(stock3, save=True)


def window_of(rights, mask, word=None):
    """The audio CPU's part of the window as bytes: {track: 32 longs} in their halves, and the long."""
    w = bytearray(np.random.default_rng(21).integers(0, 256, 0x1000, dtype=np.uint8).tobytes())
    for t, x in rights.items():
        raw = np.asarray(x).astype(">i4").tobytes()
        for k, h in enumerate((2 * t, 2 * t + 1)):
            w[m.rw_half(h):m.rw_half(h) + 64] = raw[64 * k:64 * k + 64]
    w[m.RW_HEAD:m.RW_HEAD + 4] = (m.rw_word(mask) if word is None else word).to_bytes(4, "big")
    return bytes(w)


class FillRig:
    """The main CPU around our routine: stock's wait, the place in the per-block routine it is called from, the window."""

    def __init__(self, image, syms=None):
        mc = self.mc = Machine()
        for base, size in ((0x40000000, 0x800000), (0x80000000, 0x10000), (0x43bd0000, 0x10000), (0x45560000, 0x10000),
                           (mm.SHARED, 0x2000), (0xfc000000, 0x100000)):
            mc.map(base, size)
        mc.write(mm.BASE, image)
        for a, b in (mm.CAVE_RIGHT, (mm.DMA_WAIT, mm.DMA_WAIT + 0x22), (mm.RIGHT_HOOK, SEND)):
            mc.load_code(a, image[mm.off(a):mm.off(b)])
        mc.set_stack(STACK, 0x40000100)
        mc.set_exits([0x40000100, SEND, SKIP])
        self.fill = syms and syms["right_fill"]
        self.reads, self.writes = [], []
        mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: self.reads.append((a, s)))
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: self.writes.append((a, s)))
        mc.uc.ctl_flush_tb()

    def set(self, tracks, window, up=1, busy=False):
        mc = self.mc
        mc.write(mm.TRACKS, np.asarray(tracks).astype(">i4").tobytes())
        mc.write(mm.SHARED, window)
        mc.write(RSET - 64, b"\xee" * (64 + 1280 + 64))
        mc.w32(mm.AUDIO_UP, up)
        mc.write(DMA_FLAG, bytes([1 if busy else 0]))
        mc.write(DMA_STATUS, b"\x00\x80")               # done, so stock's wait ends
        self.reads, self.writes = [], []

    def right(self):
        return np.frombuffer(self.mc.read(RSET, 1024), dtype=">i4").reshape(8, 32).astype(np.int32)

    def window_reads(self):
        return sorted({a - mm.SHARED for a, s in self.reads if mm.SHARED <= a < mm.SHARED + 0x2000})


def some_tracks(seed=4):
    return np.random.default_rng(seed).integers(-2 ** 31, 2 ** 31, (8, 32)).astype(np.int32)


@pytest.mark.parametrize("mask", [0, 0x01, 0x80, 0x10, 0x5a, 0xff])
def test_the_second_set_is_each_tracks_right_channel_or_a_copy_of_its_left(main, mask):
    """Track 5 (mask 0x10) is the one whose two halves are in different stretches of the window."""
    r = FillRig(*main)
    tracks, rights = some_tracks(), {t: some_tracks(30 + t)[t] for t in range(8)}
    window = window_of(rights, mask)
    r.set(tracks, window)
    assert r.mc.call(r.fill) == 1
    got = r.right()
    for t in range(8):
        assert np.array_equal(got[t], rights[t] if mask >> t & 1 else tracks[t]), t
    # nothing but the eight buffers is written: not the two returns after them, not the window, not the tracks
    assert all(RSET <= a and a + s <= RSET + 1024 or STACK - 0x100 <= a < STACK for a, s in r.writes)
    assert r.mc.read(RSET - 64, 64) == b"\xee" * 64 and r.mc.read(RSET + 1024, 320) == b"\xee" * 320
    assert r.mc.read(mm.SHARED, 0x1000) == window and np.array_equal(np.frombuffer(r.mc.read(mm.TRACKS, 1024), dtype=">i4").reshape(8, 32), tracks)
    # of the window, the long and the halves of the tracks it names are read, a long at a time, and nothing else
    want = [m.RW_HEAD] + [m.rw_half(h) + 4 * k for t in range(8) if mask >> t & 1 for h in (2 * t, 2 * t + 1) for k in range(16)]
    assert r.window_reads() == sorted(want)
    assert all(s == 4 for a, s in r.reads if mm.SHARED <= a < mm.SHARED + 0x2000)


@pytest.mark.parametrize("word", [0, 0xffffffff, 0x52570000, 0x5257ffff, 0x5257fe00, 0x5357ff00, 0x1257a55a, 0x5a5aa55a, m.rw_word(0x3c) ^ 0x100])
def test_a_long_that_does_not_agree_with_itself_leaves_every_track_mono(main, word):
    """What that place holds if it is not memory the audio CPU can write: anything. Then no half is read, and
    every right buffer is the left's: the unit sounds as it would with every sample mono."""
    assert word != m.rw_word(word & 0xff)
    r = FillRig(*main)
    tracks = some_tracks()
    r.set(tracks, window_of({t: some_tracks(40)[t] for t in range(8)}, 0, word))
    assert r.mc.call(r.fill) == 1
    assert np.array_equal(r.right(), tracks) and r.window_reads() == [m.RW_HEAD]


def test_with_the_audio_cpu_down_the_window_is_not_read_and_the_long_is_cleared(main):
    """Stock clears the track buffers then, and the boot loader has the window: the copies are of silence. The long
    is set to 0, so that the audio CPU's restart does not leave the main CPU a block of what was there before it:
    the audio CPU clears stock's part of the window at its start and none of ours."""
    r = FillRig(*main)
    tracks = np.zeros((8, 32), dtype=np.int32)
    window = window_of({t: some_tracks(40)[t] for t in range(8)}, 0xff)
    r.set(tracks, window, up=0)
    assert r.mc.call(r.fill) == 0
    assert np.array_equal(r.right(), tracks) and r.window_reads() == []
    wrote = [(a - mm.SHARED, s) for a, s in r.writes if mm.SHARED <= a < mm.SHARED + 0x2000]
    assert wrote == [(m.RW_HEAD, 4)]
    assert r.mc.read(mm.SHARED, 0x1000) == window[:m.RW_HEAD] + bytes(4) + window[m.RW_HEAD + 4:]
    # the block after: the audio CPU is up and has not written yet. No track has a right channel
    r.set(tracks, r.mc.read(mm.SHARED, 0x1000))
    assert r.mc.call(r.fill) == 1 and np.array_equal(r.right(), tracks) and r.window_reads() == [m.RW_HEAD]
    # the boot's exchange is elsewhere in the window: its words at 0 to 0xc, its chunks from 0x800
    assert m.RW_HEAD + 4 <= m.POOL_CHUNK and m.RW_HEAD >= 0x1b0 + 0x400


def test_it_waits_for_the_left_buffers_as_stock_does_before_it_reads_anything(main):
    r = FillRig(*main)
    r.set(some_tracks(), window_of({0: some_tracks(40)[0]}, 1), busy=True)
    r.mc.call(r.fill)
    order = [a for a, s in r.reads if a in (DMA_FLAG, DMA_STATUS) or mm.SHARED <= a < mm.SHARED + 0x2000 or mm.TRACKS <= a < mm.TRACKS + 1024]
    assert order[:2] == [DMA_FLAG, DMA_STATUS] and r.mc.read(DMA_FLAG, 1) == b"\0"     # stock's routine: it saw the transfer done and said so
    assert (DMA_FLAG, 1) in r.writes


@pytest.mark.parametrize("up", [0, 1, 0x100])
def test_the_place_it_is_called_from_goes_on_as_stock_does(stock3, main, up):
    """Stock: wait, test "the audio CPU is up", send the knobs or skip that. Ours: the routine, which waits and
    answers what stock tested, then the same branch. Both run from that place to where the two ways part, every
    register a routine may not change left as it was."""
    image, syms = main
    ends = []
    for img in (stock3, image):
        r = FillRig(img, syms)
        r.set(some_tracks(), window_of({}, 0), up=up, busy=True)
        for k in range(2, 8):
            r.mc.set_reg(k, 0x1000 + k)
            r.mc.set_reg(8 + k, 0x2000 + k)             # a2..a7: a7 is set again below
        r.mc.uc.reg_write(UC_M68K_REG_A7, STACK - 0x40)
        r.mc.uc.emu_start(mm.RIGHT_HOOK, 0)
        ends.append((r.mc.uc.reg_read(UC_M68K_REG_PC), [r.mc.reg(k) for k in range(2, 8)], [r.mc.reg(8 + k) for k in range(2, 8)],
                     r.mc.read(DMA_FLAG, 1)))
    assert ends[0] == ends[1] and ends[0][0] == (SEND if up else SKIP)
    assert ends[1][1] == [0x1000 + k for k in range(2, 8)] and ends[1][2][:5] == [0x2000 + k for k in range(2, 7)] and ends[1][2][5] == STACK - 0x40


def test_what_it_costs_the_main_cpu(main):
    """Instructions a block: eight copies when no track is stereo, the same from the window when all are. The
    mixer without its effects is 21,381. What a long read from the window costs in time is not known."""
    r = FillRig(*main)
    counts = []
    for mask in (0, 1, 0xff):
        r.set(some_tracks(), window_of({t: some_tracks(40)[t] for t in range(8)}, mask))
        was = r.mc.insns
        r.mc.call(r.fill)
        counts.append(r.mc.insns - was)
    assert counts == COST_MAIN


COST_MAIN = [732, 762, 979]          # no track stereo, one, all eight


# ---- the main CPU: the real mixer with its right-hand passes on the second set ---------------------------

BUSES = dict(send=(mm.BUS_L, 256), dry=(mm.BUS_DRY_L, 256), fx=(mm.BUS_FX_L, 256), out=(W.OUT_FRAME, 1024), frame=(mm.FRAME, 4 * 32 * mm.FRAME_CH))
RETURNS = (0x8000dcd0, 0x8000ddd0)      # what the delay and the reverb leave for the mix: a stereo pair each


class Mix(W.Mixer):
    """tests/test_mixer_whole.py's rig: the whole mixer, its effects made returns. Here the delay's and the reverb's
    outputs are given numbers and their levels turned up, so that the two returns reach the sums too."""

    def __init__(self, image):
        super().__init__(image)
        self.mc.map(0x45560000, 0x10000)

    def block(self, left, right, pans, sends, routes, returns):
        """One call. left: the eight track buffers. right: the second set's, or None for an image without one."""
        mc = self.mc
        b = bytearray(0x800)
        b[1780:1782] = (90 << 8).to_bytes(2, "big")             # the delay's level into the mix, and the reverb's
        b[1798:1800] = (110 << 8).to_bytes(2, "big")
        for t in range(12):
            p = W.STRIDE * t
            b[2 * t:2 * t + 2] = (100 << 8).to_bytes(2, "big")
            b[p + 62] = 44 if t < 8 else 0
            for at, v in ((mm.P_DELAY_SEND, sends[0][t]), (mm.P_REVERB_SEND, sends[1][t]), (mm.P_PAN, pans[t]), (mm.P_VOL, 100), (126, routes[t])):
                b[p + at:p + at + 2] = (v << 8).to_bytes(2, "big")
        mc.write(W.PARAMS, bytes(b))
        mc.write(mm.TRACKS, np.asarray(left).astype(">i4").tobytes())
        if right is not None:
            mc.write(RSET, np.asarray(right).astype(">i4").tobytes())
        mc.write(mm.INPUTS, bytes(1024))
        for at, x in zip(RETURNS, returns):
            mc.write(at, np.asarray(x).astype(">i4").tobytes())
        mc.emac.macsr = 0x20
        assert mc.call(mm.MIX, 0, 0, W.PARAMS) == mm.BUS_L
        return {n: np.frombuffer(mc.read(a, size), dtype=">i4").reshape(32, -1) for n, (a, size) in BUSES.items()}


def a_mix(seed, blocks=6):
    rng = np.random.default_rng(seed)
    left, other = (rng.integers(-2 ** 26, 2 ** 26, (blocks, 8, 32)) for _ in range(2))
    knobs = dict(pans=[int(x) for x in rng.integers(0, 128, 12)], sends=[[int(x) for x in rng.integers(0, 128, 12)] for _ in range(2)],
                 routes=[int(x) for x in rng.integers(0, 2, 12)])
    returns = rng.integers(-2 ** 26, 2 ** 26, (blocks, 2, 64))
    return left, other, knobs, returns, int(rng.integers(1, 256))


def mixed(image, lefts, rights, knobs, returns):
    mx = Mix(image)
    return [mx.block(lefts[n], None if rights is None else rights[n], returns=returns[n], **knobs) for n in range(len(lefts))], mx


@pytest.mark.parametrize("seed", range(4))
def test_with_every_right_buffer_a_copy_of_its_left_the_mixer_is_stock(stock3, main, seed):
    """Every sum, both output frames, and the gains it leaves for the next block: bit for bit, the returns sounding."""
    left, _, knobs, returns, _ = a_mix(seed)
    was, a = mixed(stock3, left, None, knobs, returns)
    now, b = mixed(main[0], left, left, knobs, returns)
    for n in range(len(left)):
        for name in BUSES:
            assert np.array_equal(was[n][name], now[n][name]), (n, name)
    assert was[-1]["dry"].any() and was[-1]["send"].any() and was[-1]["fx"].any()
    for gains in (mm.GAIN_L, mm.GAIN_R, mm.GAIN_DRY_L, mm.GAIN_DRY_R):
        assert a.mc.read(gains, 40) == b.mc.read(gains, 40)
    assert np.frombuffer(a.mc.read(mm.GAIN_DRY_L, 40), dtype=">i4")[8:].all()          # the two returns are in the dry sum
    assert a.mc.read(mm.RETURN_DELAY, 256) != b.mc.read(mm.RETURN_DELAY, 256)          # the right returns went to our set, the left stayed
    assert a.mc.insns == b.mc.insns


@pytest.mark.parametrize("seed", range(4))
def test_a_stereo_track_is_its_left_on_the_left_and_its_right_on_the_right(stock3, main, seed):
    """Some tracks stereo. The left side of every sum is stock's with the left buffers, the right side stock's with
    every track holding what its right buffer holds: pan is balance, the sends are stereo, the returns as they were.
    In the frame of 20 the main mix's two channels follow, and a stereo track's own channel is its left."""
    left, other, knobs, returns, stereo_tracks = a_mix(seed)
    right = left.copy()
    for t in range(8):
        if stereo_tracks >> t & 1:
            right[:, t] = other[:, t]
    of_left, _ = mixed(stock3, left, None, knobs, returns)
    of_right, _ = mixed(stock3, right, None, knobs, returns)
    now, _ = mixed(main[0], left, right, knobs, returns)
    for n in range(len(left)):
        for name in ("send", "dry", "fx"):
            assert np.array_equal(now[n][name][:, 0], of_left[n][name][:, 0]), (n, name)
            assert np.array_equal(now[n][name][:, 1], of_right[n][name][:, 1]), (n, name)
            assert not np.array_equal(of_left[n][name][:, 1], of_right[n][name][:, 1])
        out, l, r = now[n]["out"], of_left[n]["out"], of_right[n]["out"]
        assert np.array_equal(out[:, 7], l[:, 7]) and np.array_equal(out[:, 2], r[:, 2])           # the dry mix's two slots
        assert not np.array_equal(l[:, 2], r[:, 2])
        frame, l, r = now[n]["frame"], of_left[n]["frame"], of_right[n]["frame"]
        assert np.array_equal(frame[:, mm.F_MAIN_L], l[:, mm.F_MAIN_L]) and np.array_equal(frame[:, mm.F_MAIN_R], r[:, mm.F_MAIN_R])
        assert np.array_equal(frame[:, mm.F_T1:mm.F_T1 + 8], l[:, mm.F_T1:mm.F_T1 + 8])           # a track's own channel: the left
        rest = [c for c in range(mm.FRAME_CH) if c not in (mm.F_MAIN_L, mm.F_MAIN_R)]
        assert np.array_equal(frame[:, rest], l[:, rest]) or np.array_equal(frame[:, rest][:, 8:], r[:, rest][:, 8:])


def test_a_stereo_tracks_pan_is_its_balance(main):
    """Hard left: the left channel alone, at full level. Hard right: the right alone. In the middle both, each on its side."""
    rng = np.random.default_rng(8)
    l, r = rng.integers(-2 ** 26, 2 ** 26, (2, 32))
    left, right = np.zeros((8, 32), dtype=np.int64), np.zeros((8, 32), dtype=np.int64)
    left[3], right[3] = l, r
    zero = dict(sends=[[0] * 12] * 2, routes=[0] * 12)
    got = {}
    for pan in (0, 64, 127):
        mx = Mix(main[0])
        for _ in range(6):                               # the ramped gains arrive
            dry = mx.block(left, right, returns=np.zeros((2, 64)), pans=[pan] * 12, **zero)["dry"].astype(np.int64)
        got[pan] = dry
    assert not got[0][:, 1].any() and np.corrcoef(got[0][:, 0], l)[0, 1] > 0.999999
    assert np.abs(got[127][:, 0]).max() < 16 and np.corrcoef(got[127][:, 1], r)[0, 1] > 0.999999
    assert np.corrcoef(got[64][:, 0], l)[0, 1] > 0.999999 and np.corrcoef(got[64][:, 1], r)[0, 1] > 0.999999
    assert abs(np.abs(got[64][:, 0]).sum() / np.abs(got[0][:, 0]).sum() - 0.75) < 0.01      # the pan law's middle: 0.75 a side


# ---- from the audio CPU's interrupt to the mixer's sums ---------------------------------------------------

def test_from_the_voices_to_the_mix(factory, stock, stereo, stock3, main):
    """The two programs together, as far as they can be run: the audio CPU's interrupt makes eight left buffers and
    leaves three right channels in the window; the main CPU's routine fills the second set from it; the mixer sums.
    Held against stock all the way: stock's stages fed the left and the right signals, stock's mixer fed the results."""
    def first(r):
        samplers(r, factory, loop=1)
        for t, mode in ((0, 1), (3, 1), (7, 1), (5, 0)):
            r.set_slot(t, SAMPLE, 64 + t % 3)
            r.set_slot(t, MODE, mode)
        r.set_note(3, 55.25)
    script = [(first, 0, 0), (None, 0xa9, 0)] + [(None, 0, 0)] * 8
    audio = Rig(stereo[0])
    audio.load_pool(pool())
    fill, mx = FillRig(*main), Mix(main[0])
    knobs = dict(pans=[20, 64, 64, 100, 64, 64, 64, 64] + [64] * 4, sends=[[30] * 12, [50] * 12], routes=[0] * 12)
    silent = np.zeros((2, 64))
    voices, waiting, masks, sums = [], [], [], []
    for prepare, trig, release in script:
        if prepare:
            prepare(audio)
        v, w, left = audio.block(trig, release)
        voices.append(v), waiting.append(w), masks.append(audio.mask())
        fill.set(left, audio.mc.read(0, 0x1000))                # what stock's transfer brings, and the window as the audio CPU left it
        fill.mc.call(fill.fill)
        sums.append(mx.block(left, fill.right(), returns=silent, **knobs))
    assert masks == [0, 0] + [0x89] * 8                         # tracks 1, 4 and 8; track 6 plays mono
    voices = np.array(voices)
    as_right = voices.copy()
    for n in range(2, 10):
        for t in (0, 3, 7):
            as_right[n, t] = waiting[n][t]
    of_left, _ = mixed(stock3, stock_of(stock, script, voices), None, knobs, [silent] * 10)
    of_right, _ = mixed(stock3, stock_of(stock, script, as_right), None, knobs, [silent] * 10)
    for n in range(10):
        for name in ("send", "dry"):
            assert np.array_equal(sums[n][name][:, 0], of_left[n][name][:, 0]) and np.array_equal(sums[n][name][:, 1], of_right[n][name][:, 1])
    assert sums[-1]["dry"][:, 0].any() and sums[-1]["dry"][:, 1].any() and not np.array_equal(of_left[-1]["dry"][:, 1], of_right[-1]["dry"][:, 1])


# ---- no track follows another any more --------------------------------------------------------------------

def test_the_track_after_a_stereo_one_is_its_own_again(save3, main):
    """Up to the save image the mixer was shown the next track's pan, volume and sends as the stereo track's, and
    the two pans forced apart. Here it is shown every track as it is. The mute is as it was."""
    machines, modes = [SAMPLER] * 8 + [8, 9, 10, 11], [1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0]
    block, frame = make_block(machines, modes), frames()
    now, was = FeedRig(*main), FeedRig(*save3)
    now.run(block, frame)
    was.run(block, frame)
    assert now.seen["params"] == block and was.seen["params"] != block
    now.mc.w32(mm.MUTES, 0b101)                           # tracks 1 and 3 muted: their volumes are 0 for the mixer, and no other's
    now.run(block, frame)
    shown = now.seen["params"]
    for t in range(12):
        at = 142 * t + mm.P_VOL
        assert shown[at:at + 2] == (b"\0\0" if t in (0, 2) else block[at:at + 2])
    assert all(shown[k] == block[k] for k in range(len(block)) if k % 142 not in (mm.P_VOL, mm.P_VOL + 1) or k // 142 > 11)


# ---- where the code and its memory are --------------------------------------------------------------------

EARLIER = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES)
OURS = dict(EARLIER, **m.ONE_CAVES)
FREE = (m.STASH, m.STASH + 0xa00)       # the right channels, the mask, two copies of state and the shape of stock's filter memory
NOT_A_POINTER = 0x4000cfba              # in stock's tables: reads as 0x440504c5. See the test of that memory


def test_the_four_new_runs_are_code_nothing_reaches(stock):
    """The same rules the earlier runs are held to (tests/test_sampler.py). One of the four lies before the entry
    point, where tools/deadcode.py calls everything live: with the entry's own piece as the one thing taken on
    trust, the survey finds it reached by nothing, as it finds the other three."""
    def ours(a):
        return any(lo <= a < hi for lo, hi in OURS.values())

    def new(a):
        return any(lo <= a < hi for lo, hi in m.ONE_CAVES.values())
    spans = sorted(OURS.values())
    assert not any(b > c for (a, b), (c, d) in zip(spans, spans[1:]))                  # no two runs share a byte
    for o in range(0, len(stock) - 3, 2):                                               # no 32-bit value points into one
        if not ours(m.BASE + o):
            assert not new(int.from_bytes(stock[o:o + 4], "big")), hex(m.BASE + o)
    for addr, _, text in boundaries(stock[4:m.off(m.CODE_END)], m.BASE + 4):            # no instruction outside our runs names one
        if not ours(addr):
            for x in re.findall(r"0x([0-9a-f]{8})\b", text):
                assert not new(int(x, 16)), hex(addr)
    for lo, hi in m.ONE_CAVES.values():
        assert stock[m.off(lo) - 2:m.off(lo)] == b"\x4e\x75" and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
        assert hi <= m.CODE_END
    unreached = {(lo, hi): named for lo, hi, named, clean in deadcode.survey(stock, m.BASE, m.CODE_END, m.BASE + 4) if clean}
    for lo, hi in m.ONE_CAVES.values():
        assert unreached[(lo, hi)] == 0
    # the run before the entry: stock's reader of a pool from a flash chip, called by one routine that nothing calls
    lo, hi = m.ONE_CAVES["h"]
    assert hi == m.SLOT_BUILD and lo < m.POOL_LOAD < hi < m.ENTRY
    assert stock[m.off(0x40000cfc):m.off(0x40000d00)] == bytes.fromhex(fw.sx("74900625854a03f9"))      # jsr %pc@(lo), inside the run


def test_the_new_runs_are_never_run_or_read_by_stock(official, stock, descs, factory):
    seen = []
    b = Rig(stock)
    b.load_pool({0: np.arange(2000, dtype=np.int16)})
    for lo, hi in m.ONE_CAVES.values():
        b.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.append(a), begin=lo, end=hi - 1)
        b.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: seen.append(a), begin=lo, end=hi - 1)
    b.mc.uc.ctl_flush_tb()
    for mtype in m.TYPE_OF_ENGINE:
        for t in range(m.N_VOICES):
            b.set_defaults(t, mtype, descs)
            b.set_note(t, 48 + 5 * t)
            for slot, v in factory.items():
                b.set_slot(t, slot, v)
        for n in range(8):
            b.block(0xff if n in (0, 4) else 0, 0xff if n == 6 else 0)
    assert not seen


def test_the_engine_is_the_pitch_images_but_for_the_right_channel(stock, stereo, pitch):
    """What differs from the save image's audio program: the four new runs, the runs the changed routines are in
    (the render; the step after the voice loop with what it calls now; and with the second build the player, the
    making of the table, and Twinshot's update and render, where the sums are made now), and one more call of the
    interrupt's."""
    image, syms = stereo
    lo, hi = m.CAVES["y"]                                               # the hook still calls the step after the voice loop
    assert image.index(b"\x4e\xb9" + syms["sampler_post"].to_bytes(4, "big"), m.off(lo), m.off(hi)) > m.off(syms["sampler_hook"])
    spans = [m.CAVES["x"], m.CAVES["y"], m.PITCH_CAVES["p"], m.PITCH_CAVES["t"]] + list(m.ONE_CAVES.values()) + list(m.QUICK_CAVES.values())
    spans += list(m.LEAN_CAVES.values()) + [m.PITCH_CAVES["s"]]         # the third build: the level and the gain in one pass, a note's start
    # and where a routine that has moved is named by one that has not: in two of the earlier runs, three places
    moved = {syms[n].to_bytes(4, "big") for n in syms if n in pitch[1] and syms[n] != pitch[1][n]}
    assert pitch[1]["slot_frames"] != syms["slot_frames"] and m.ONE_CAVES["a"][0] <= syms["slot_frames"] < m.ONE_CAVES["a"][1]
    named = [(m.BASE + o, m.BASE + o + 4) for lo, hi in (m.FADE_CAVES["w"], m.PITCH_CAVES["q"])
             for o in range(m.off(lo), m.off(hi), 2) if image[o:o + 4] in moved]
    assert len(named) == 3
    spans += named
    spans += [(m.ISR_AMP_CALL + 2, m.ISR_AMP_CALL + 6), (m.ISR_VOICE_LOOP_CALL + 2, m.ISR_VOICE_LOOP_CALL + 6)]      # and the hook, which has moved in its run
    assert m.u32(image, m.ISR_VOICE_LOOP_CALL + 2) == syms["sampler_hook"] != pitch[1]["sampler_hook"] == m.u32(pitch[0], m.ISR_VOICE_LOOP_CALL + 2)
    diff = [m.BASE + k for k in range(len(image)) if image[k] != pitch[0][k]]
    assert diff and all(any(lo <= a < hi for lo, hi in spans) for a in diff)
    assert m.u32(stock, m.ISR_AMP_CALL + 2) == m.STAGE_AMPS and m.u32(image, m.ISR_AMP_CALL + 2) == syms["sampler_amp"]
    assert image[m.off(m.ISR_AMP_CALL):m.off(m.ISR_AMP_CALL) + 2] == stock[m.off(m.ISR_AMP_CALL):m.off(m.ISR_AMP_CALL) + 2] == b"\x4e\xb9"
    for lo, hi in m.ONE_CAVES.values():                                 # stock's own bytes in the image before
        assert pitch[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
    where = dict(right_track="h", right_pass="h", seed="a", send="b", seed_runs="b", sampler_amp="c")
    for name, cave in where.items():
        lo, hi = m.ONE_CAVES[cave]
        assert lo <= syms[name] < hi, name
    lo, hi = m.PITCH_CAVES["p"]
    assert all(lo <= syms[name] < hi for name in ("swap_filters", "right_mask", "sampler_post"))
    # the two that only move longs went, with the third build, to where there was room: tests/test_lean.py
    assert m.CAVES["x"][0] <= syms["swap"] < m.CAVES["x"][1] and m.QUICK_CAVES["k"][0] <= syms["longs"] < m.QUICK_CAVES["k"][1]
    # the stock routines it calls are where the interrupt calls them, and the four stages are untouched
    assert m.u32(stock, 0x40000a46 + 2) == m.STAGE_GAIN and m.u32(stock, 0x40000a5a + 2) == m.STAGE_DRIVE
    assert m.u32(stock, 0x40000a72 + 2) == m.STAGE_FILTER and stock[m.off(0x400016ac):m.off(0x400016b0)] == bytes.fromhex(fw.sx("8357fb1c74367366"))   # lea %pc@(STAGE_AMP1),%a2
    for lo, hi in ((m.STAGE_GAIN, 0x40001708), (m.STAGE_FILTER, 0x400024e0)):
        assert image[m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]


def test_the_memory_it_uses_is_no_one_elses(stock, stereo):
    """Free memory after the program's data: nothing in stock names it, and in the built image only our code does.
    The interpolation table and the takes are past it."""
    assert m.BSS[1] < FREE[0] and FREE[1] <= m.HQ_MARK < m.KEPT < m.REC_BASE
    assert m.STASH + 8 * 128 == m.R_MASK < m.R_GAIN and m.R_GAIN + (m.GAIN_STATE[1] - m.GAIN_STATE[0]) == m.R_AMP
    lo = min(a for a, b in m.FILTER_STATE) + m.R_SHADOW & 0xffffffff
    hi = max(b for a, b in m.FILTER_STATE) + m.R_SHADOW & 0xffffffff
    assert m.R_AMP + (m.AMP_STATE[1] - m.AMP_STATE[0]) <= lo < hi <= FREE[1]
    # one place in stock reads as an address there: two neighbours in a table of rising longs, read across their join
    o = m.off(NOT_A_POINTER) - 18
    table = [int.from_bytes(stock[o + 4 * k:o + 4 * k + 4], "big") for k in range(10)]
    assert table[4:6] == [0x04bb4405, 0x04c53d65] and all(a < b for a, b in zip(table, table[1:])) and NOT_A_POINTER > m.CODE_END
    for image in (stock, stereo[0]):
        named = [o for o in range(0, len(image) - 3, 2) if FREE[0] <= int.from_bytes(image[o:o + 4], "big") < FREE[1] and o != m.off(NOT_A_POINTER)]
        assert all(any(m.off(a) <= o < m.off(b) for a, b in OURS.values()) for o in named) and (named or image is stock)
    # the window: stock clears and uses 0x5b0 bytes of it and the boot's 2 KB at 0x800; ours end at 0xe38
    assert m.u32(stock, 0x40000e98) & 0xffff == 0x5b0 == m.RW_HEAD and m.REC_BOX + m.REC_SIZE == 0xe38
    halves = sorted(m.rw_half(h) for h in range(16))
    assert halves[0] == m.RW_HEAD + 16 and halves[8] + 64 == m.MAILBOX and halves[9] == 0xe40 and halves[15] + 64 == 0x1000
    assert all(b - a == 64 for a, b in zip(halves[:9], halves[1:9])) and all(b - a == 64 for a, b in zip(halves[9:], halves[10:]))


def allowed_writes(mask_tracks):
    """Where the right channels' routines may write."""
    spots = [(m.R_MASK, m.R_MASK + 4), (m.R_GAIN, m.R_AMP + 96), m.GAIN_STATE, (m.FILTER_LEFTOVER, m.FILTER_LEFTOVER + 8),
             (m.RW_HEAD, m.RW_HEAD + 4), (m.STACK_TOP - 0x400, m.STACK_TOP)]
    spots += list(m.FILTER_STATE) + [(a + m.R_SHADOW & 0xffffffff, b + m.R_SHADOW & 0xffffffff) for a, b in m.FILTER_STATE]
    spots += [(m.VOICES + m.VOICE_SIZE * t + ST + RLIVE, m.VOICES + m.VOICE_SIZE * t + ST + RLIVE + 1) for t in range(8)]
    spots += [(m.rw_half(h), m.rw_half(h) + 64) for t in mask_tracks for h in (2 * t, 2 * t + 1)]
    return spots


@pytest.mark.parametrize("seed", [1, 5])
def test_the_right_channels_routines_write_only_what_is_theirs(stereo, seed):
    """Every write made while one of our new routines is the one running, the stock stages it calls apart: the mask,
    the two copies, stock's memory of the stages and its shape in free memory, a byte of a voice, and in the window
    the long and the halves of the tracks that have a right channel. Stock's stages write what they always do."""
    image, syms = stereo
    names = ["longs", "swap", "swap_filters", "seed", "right_mask", "send", "right_track", "right_pass", "sampler_amp"]
    edges = sorted(set(syms.values()) | {hi for lo, hi in list(OURS.values()) + list(m.QUICK_CAVES.values()) + list(m.LEAN_CAVES.values())})
    spans = [(syms[n], edges[edges.index(syms[n]) + 1]) for n in names]
    r = Rig(image)
    r.load_pool(pool())
    wrote = []

    def on_write(uc, access, address, size, value, user):
        pc = uc.reg_read(UC_M68K_REG_PC)
        if any(lo <= pc < hi for lo, hi in spans):
            wrote.append((address, size))
    r.mc.uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    r.mc.uc.ctl_flush_tb()
    seen = 0
    for prepare, trig, release in scenario(seed, 40):
        prepare(r)
        del wrote[:]
        r.block(trig, release)
        ok = allowed_writes([t for t in range(8) if r.mask() >> t & 1])
        assert wrote and all(any(lo <= a and a + s <= hi for lo, hi in ok) for a, s in wrote)
        assert all(s == 4 for a, s in wrote if a < 0x1000)                  # the window: longs only
        seen += r.mask() != 0
    assert seen > 20


@pytest.mark.parametrize("seed", [0, 3])
def test_nothing_in_free_memory_is_believed_from_before_the_start(stock, stereo, seed):
    """That memory is cleared by nothing and comes back from a restart mostly as it was. Filled with noise before the
    first interrupt, and the two stretches of the window with it: every right channel is still stock's of it."""
    image, _ = stereo
    script = scenario(seed, 50)
    r = Rig(image)
    r.load_pool(pool())
    noise = np.random.default_rng(99).integers(0, 256, 0x1000, dtype=np.uint8).tobytes()
    r.mc.write(FREE[0], noise[:FREE[1] - FREE[0]])
    r.mc.write(m.RW_HEAD, noise[:m.MAILBOX - m.RW_HEAD])
    r.mc.write(0xe38, noise[:0x1000 - 0xe38])
    got = []
    for prepare, trig, release in script:
        prepare(r)
        voices, waiting, left = r.block(trig, release)
        got.append(dict(voices=voices, waiting=waiting, mask=r.mask(), right={t: r.right(t) for t in range(8) if r.mask() >> t & 1}))
    voices, masks = np.array([b["voices"] for b in got]), [b["mask"] for b in got]
    checked = 0
    for t in range(8):
        for a, b in stretches(masks, t):
            fed = voices[:b].copy()
            fed[a:b, t] = [got[n]["waiting"][t] for n in range(a, b)]
            want = stock_of(stock, script[:b], fed)
            assert all(np.array_equal(got[n]["right"][t], want[n][t]) for n in range(a, b))
            checked += b - a
    assert checked > 40


def test_a_voice_makes_the_two_channels_it_made(stereo, pitch):
    """The sampler's own part is not changed: the left in the track's buffer, and the right, which the save image put in
    the next track's buffer, waiting in free memory. Whole, cut, looped, backwards, pitched, and on the last track."""
    cases = [dict(), dict(loop=1, start=5, length=45), dict(sample=63), dict(loop=2, start=25, length=30), dict(start=30, length=50, note=55.25),
             dict(loop=1, note=67), dict(note=36)]
    for knobs in cases:
        note = knobs.pop("note", 60)
        out = []
        for built, track in ((pitch, 2), (stereo, 2), (stereo, 7)):
            e = HookEngine(built[0], loop_entry=built[1]["sampler_hook"])
            e.mc.map(0, 0x2000)
            e.load_pool(pool())
            for t in range(8):
                e.set_machine(t, SAMPLER)
                e.set_note(t, note)
                for s in range(18, 27):
                    e.set_slot(t, s, 0)
                for s, v in ((TUNE, 64), (SAMPLE, 64 + 63), (LENGTH, 127), (DECAY, 127)):
                    e.set_slot(t, s, v)
            for s, v in [(SAMPLE, 64), (MODE, 1)] + [(globals()[k.upper()], v) for k, v in knobs.items()]:
                e.set_slot(track, s, v)
            left, right, nxt = [], [], []
            for n in range(40):
                x = e.block(trig=1 << track if n == 0 else 0)
                left.append(x[track])
                nxt.append(x[(track + 1) % 8])
                right.append(np.frombuffer(e.mc.read(m.STASH + 128 * track, 128), dtype=">i4").astype(np.int32))
            out.append((np.array(left), np.array(right), np.array(nxt)))
        (l0, _, r0), (l1, r1, n1), (l7, r7, n7) = out
        assert np.array_equal(l0, l1) and np.array_equal(r0, r1) and l0.any() and r0.any()     # the save image's next track is our waiting buffer
        assert np.array_equal(l7, l0) and np.array_equal(r7, r0)                                 # the same on the last track
        assert not n1.any() and not n7.any()                                                     # and the next track is left alone


@pytest.mark.parametrize("track", [3, 7])
def test_a_take_is_recorded_as_before_and_plays_back_in_stereo_on_its_own_track(stereo, track):
    """The recorder is not changed: REC on, a held trig, and the take is what was fed, left and right, in the track's
    stereo sample. REC off and a trig: the left in the track's buffer, the right waiting for the stages, where the
    save image put it in the next track's buffer. On the last track too, which had no next one."""
    e = P.engine(stereo)
    e.set_slot(track, MODE, P.REC | P.STEREO)
    P.box(e)
    data = P.hold(e, track=track, n=40, seed=11)
    k = 2 * track
    assert P.is_take(P.taken(e, k), data, 0, 40) and P.is_take(P.taken(e, k + 1), data, 1, 40)
    e.set_slot(track, MODE, P.STEREO)
    e.block(trig=1 << track)
    left, right, nxt = [], [], []
    for _ in range(6):
        x = e.block()
        left.append(x[track])
        nxt.append(x[(track + 1) % 8])
        right.append(np.frombuffer(e.mc.read(m.STASH + 128 * track, 128), dtype=">i4").astype(np.int32))
    left, right = (np.concatenate(x).astype(np.float64) for x in (left, right))
    want = P.taken(e, k).astype(np.float64), P.taken(e, k + 1).astype(np.float64)
    heard = lambda x, w: max(np.corrcoef(x[j:j + 5 * 32], w[:5 * 32])[0, 1] for j in range(33))
    assert heard(left, want[0]) > 0.99 and heard(right, want[1]) > 0.99 and not np.array(nxt).any()
    assert e.mc.r32(m.R_MASK) == 1 << track                                    # and the track is one with a right channel


# ---- room: stock Twinshot's own code ------------------------------------------------------------------------

def reached_by_nothing(image, rooms, callers=()):
    """Nothing outside `rooms` and `callers` names an address in them, falls into them or branches there."""
    def inside(a):
        return any(lo <= a < hi for lo, hi in rooms)

    def ours(a):
        return inside(a) or any(lo <= a < hi for lo, hi in callers)
    for o in range(0, len(image) - 3, 2):                                                    # no 32-bit value names them
        v = int.from_bytes(image[o:o + 4], "big")
        if not ours(m.BASE + o) and not v & 1:                                               # code is at even addresses
            assert not inside(v), hex(m.BASE + o)
    for addr, _, text in boundaries(image[4:m.off(m.CODE_END)], m.BASE + 4):                 # no instruction outside them does
        if not ours(addr):
            for x in re.findall(r"0x([0-9a-f]{8})\b", text):
                assert not inside(int(x, 16)), hex(addr)
    src, dst = deadcode._reaches(image[:m.off(m.CODE_END)], m.BASE)                          # and no far branch, decoded or not
    assert not [hex(a) for a, d in zip(src.tolist(), dst.tolist()) if inside(d) and not ours(a)]


def never_run(image, runs, descs, factory):
    """Every machine through the whole interrupt of a built image, the sampler in stereo and pitched: -> the places
    of `runs` that were run or read."""
    seen = []
    b = Rig(image)
    b.load_pool(pool())
    for lo, hi in runs:
        b.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.append(a), begin=lo, end=hi - 1)
        b.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: seen.append(a), begin=lo, end=hi - 1)
    b.mc.uc.ctl_flush_tb()
    for mtype in m.TYPE_OF_ENGINE:
        for t in range(m.N_VOICES):
            b.set_defaults(t, mtype, descs)
            b.set_note(t, 48 + 5 * t)
            for slot, v in factory.items():
                b.set_slot(t, slot, v)
        if mtype == SAMPLER:
            samplers(b, factory, loop=1, mode=1)
            for t in range(8):
                b.set_slot(t, SAMPLE, 64 + t % 3)
                b.set_note(t, 55.25 + t)
        for n in range(8):
            b.block(0xff if n in (0, 4) else 0, 0xff if n == 6 else 0)
    return seen, b


def test_stock_twinshot_is_reached_by_nothing_and_is_room(official, stock, stereo, pitch, descs, factory):
    """The on request, and to keep what it leaves. Its update, render,
    sample player and filter, 1,344 bytes, 830 in one run. In an image of ours that leaves them alone (the pitch
    image, whose engine 11 is the sampler as in every one) they are stock's bytes, nothing names them, nothing
    branches into them, and they are neither run nor read while every machine plays.

    The stereo image uses both since its third build: the update and render hold the sums of sixteen frames
    (tests/test_quick.py), the player and filter the pass of a voice's level and gain (tests/test_lean.py), each
    named by our own runs and by nothing else. What is room still: 442 bytes in four small runs."""
    image, syms = stereo
    rooms = list(m.TWIN_ROOM.values())
    assert rooms == [(m.TWIN_UPDATE, 0x40009b1a), (m.SAMPLE_PLAY, 0x40006966)] and m.TWIN_UPDATE < m.TWIN_RENDER < 0x40009b1a
    assert m.SAMPLE_PLAY < m.TWIN_FILTER < 0x40006966 and sum(hi - lo for lo, hi in rooms) == 1344
    assert sum(hi - lo for lo, hi in m.SPARE_RUNS) == 442
    assert list(m.QUICK_CAVES.values()) + list(m.LEAN_CAVES.values()) == rooms
    before = pitch[0]
    for lo, hi in rooms:
        assert before[m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]                    # not touched
        assert stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75" and stock[m.off(hi):m.off(hi) + 2] == b"\0\0"     # ends a routine, then padding
        assert image[m.off(lo):m.off(hi)] != stock[m.off(lo):m.off(hi)]
    # nothing falls into them: an rts before the player, and before the update a jump away
    for img in (before, image):
        assert img[m.off(m.SAMPLE_PLAY) - 2:m.off(m.SAMPLE_PLAY)] == b"\x4e\x75"
        assert img[m.off(m.TWIN_UPDATE) - 6:m.off(m.TWIN_UPDATE)] == bytes.fromhex(fw.sx("105ae57483566b050a6c"))
    # stock reaches them through engine 11's two table entries and from Twinshot's own render, and so did nothing else
    assert (m.u32(stock, m.UPDATE_TABLE + 4 * m.TWIN_ENGINE), m.u32(stock, m.RENDER_TABLE + 4 * m.TWIN_ENGINE)) == (m.TWIN_UPDATE, m.TWIN_RENDER)
    for img, s in ((before, pitch[1]), (image, syms)):
        assert (m.u32(img, m.UPDATE_TABLE + 4 * m.TWIN_ENGINE), m.u32(img, m.RENDER_TABLE + 4 * m.TWIN_ENGINE)) == (s["sampler_update"], s["sampler_render"])
    reached_by_nothing(before, rooms)
    ours = list(OURS.values())
    reached_by_nothing(image, [rooms[0]], callers=ours + [rooms[1]])        # the sums: called by the player, and one of them is there
    reached_by_nothing(image, [rooms[1]], callers=ours + [rooms[0]])        # the level and the gain: called by the render
    # the one odd number that reads as an address there: two neighbours of a table of longs, across their join
    o = m.off(0x40017e3a)
    assert image[o - 2:o + 6] == bytes.fromhex(fw.sx("93a3d2fed5dcf7629df6f2be")) and 0x40017e3a > m.CODE_END
    # the stock routines the sampler calls are not in them
    for a in (m.SAMPLE_PITCH, m.ENVELOPE, 0x400045a0, m.TWIN_MIX, m.STAGE_GAIN, m.STAGE_DRIVE, m.STAGE_FILTER, m.STAGE_AMPS, m.STAGE_AMP1):
        assert not any(lo <= a < hi for lo, hi in rooms)
    # run: every machine through the whole interrupt, the image that leaves them alone and this one
    seen, b = never_run(before, rooms + list(m.SPARE_RUNS), descs, factory)
    assert not seen
    seen, b = never_run(image, list(m.SPARE_RUNS), descs, factory)
    assert b.mask() == 0xff and not seen                                                     # the sampler played, in stereo, and none of it ran


# ---- the main CPU's program, and the image ----------------------------------------------------------------

def test_the_main_program_is_the_save_images_but_for_the_declared_places(stock3, save3, main):
    image, syms = main
    spans = [mm.CAVE, mm.CAVE_RIGHT, (mm.RIGHT_HOOK, mm.RIGHT_HOOK + 10)]
    spans += [(a + 2, a + 6) for a in mm.RIGHT_PASSES] + [(a + 2, a + 6) for a, _ in mm.RIGHT_RETURNS]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != save3[0][k]]
    assert diff and all(any(lo <= a < hi for lo, hi in spans) for a in diff)
    for a in mm.RIGHT_PASSES:
        assert mm.u32(stock3, a + 2) == mm.TRACKS and mm.u32(image, a + 2) == mm.RIGHT_SET and image[mm.off(a):mm.off(a) + 2] == b"\x48\x79"
    for a, ret in mm.RIGHT_RETURNS:
        assert mm.u32(stock3, a + 2) == ret and mm.u32(image, a + 2) == mm.RIGHT_SET + ret - mm.TRACKS
    for a in mm.LEFT_PASSES + mm.TRACK_OUTS:                               # every other use of the track buffers is as it was
        assert mm.u32(image, a + 2) == mm.TRACKS
    for a, ret in mm.LEFT_RETURNS:
        assert mm.u32(image, a + 2) == ret
    hook = image[mm.off(mm.RIGHT_HOOK):mm.off(mm.RIGHT_HOOK) + 12]
    assert hook == b"\x4e\xb9" + syms["right_fill"].to_bytes(4, "big") + bytes.fromhex("4a80" "4e71" "6738")
    assert stock3[mm.off(mm.RIGHT_HOOK):mm.off(mm.RIGHT_HOOK) + 12] == bytes.fromhex(fw.sx("49b449b7bfd5d41820f9ea518133c1ef"))
    assert mm.RIGHT_HOOK + 4 + int.from_bytes(stock3[mm.off(mm.RIGHT_HOOK) + 2:mm.off(mm.RIGHT_HOOK) + 4], "big", signed=True) - 2 == mm.DMA_WAIT
    assert mm.CAVE_RIGHT[0] <= syms["right_fill"] < mm.CAVE_RIGHT[1]


def test_every_place_the_main_program_names_the_track_buffers_is_known(stock3):
    """The eight track buffers and the two returns after them, by address, anywhere in the code: the mixer's four
    left and four right passes, its six copies of a return, its two last uses, and the three places of the per-block
    routine that fill or clear them. So nothing else reads the right side from where it was."""
    where = {}
    for o in range(0, mm.off(mm.CODE_END), 2):
        v = mm.u32(stock3, mm.BASE + o)
        if v in (mm.TRACKS, mm.RETURN_DELAY, mm.RETURN_REVERB):
            where.setdefault(v, []).append(mm.BASE + o - 2)
    fills = [mm.TRACKS_IN[0] + 8, mm.TRACKS_IN[1] + 8, mm.TRACKS_CLEAR + 4]
    assert sorted(where[mm.TRACKS]) == sorted(list(mm.RIGHT_PASSES + mm.LEFT_PASSES + mm.TRACK_OUTS) + fills)
    assert sorted(where[mm.RETURN_DELAY] + where[mm.RETURN_REVERB]) == sorted(a for a, _ in mm.RIGHT_RETURNS + mm.LEFT_RETURNS)


def test_nothing_branches_into_the_place_the_routine_is_called_from(stock3):
    """Ten bytes of the per-block routine are replaced: a branch to their middle would land inside our instruction.
    Every short branch near them, and every far one, call, lea and pea of the program: none goes there."""
    inside = range(mm.RIGHT_HOOK + 2, mm.RIGHT_HOOK + 10, 2)
    lo = mm.RIGHT_HOOK - 0x400
    for addr, _, text in boundaries(stock3[mm.off(lo):mm.off(mm.RIGHT_HOOK + 0x400)], lo):
        for x in re.findall(r"0x([0-9a-f]{8})\b", text):
            assert int(x, 16) not in inside, hex(addr)
    src, dst = deadcode._reaches(stock3[:mm.off(mm.CODE_END)], mm.BASE)
    assert not [hex(s) for s, d in zip(src.tolist(), dst.tolist()) if d in inside]
    v = np.frombuffer(stock3[:len(stock3) // 4 * 4], dtype=">u4")
    w = np.frombuffer(stock3[2:2 + (len(stock3) - 2) // 4 * 4], dtype=">u4")
    assert not np.isin(v, list(inside)).any() and not np.isin(w, list(inside)).any()


def test_the_main_cpus_new_run_and_the_second_sets_memory(stock3, official):
    lo, hi = mm.CAVE_RIGHT
    others = [official.section(k) for k in (2, 4, 6, 8)]
    assert (lo, hi) in deadcode.usable(deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, others), 256)
    taken = [mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, mm.CAVE_TEXT, mm.CAVE_PAGE, mm.CAVE_BANK, mm.CAVE_PAGE2,
             mm.CAVE_METER, mm.CAVE_PAGE3, build_main.POOL_STAGE]
    assert not any(a < hi and lo < b for a, b in taken)
    # the second set: after the program's data, before the effects' memory as it lies 0x08000000 lower, a page clear of both
    first, last = mm.RIGHT_SET, mm.RIGHT_SET + 1280
    assert mm.MAIN_BSS_END + 0x1000 <= first and last + 0x1000 <= mm.EFFECTS_MEMORY[0] - mm.UNCACHED
    assert mm.MAIN_HEAP[1] < mm.MAIN_BSS_END and mm.RETURN_REVERB + 128 - mm.TRACKS == 1280
    # nothing in the file names an address within 4 KB of it, as it is or 0x08000000 higher, at any offset
    for image in [stock3] + others:
        for shift in range(4):
            v = np.frombuffer(image[shift:shift + (len(image) - shift) // 4 * 4], dtype=">u4")
            for up in (0, mm.UNCACHED):
                assert not ((v >= first - 0x1000 + up) & (v < last + 0x1000 + up)).any()
    # and the effects' memory is where the map says: 9 x 64 KB, named three times
    code = stock3[:mm.off(mm.CODE_END)]
    assert [mm.BASE + o for o in range(0, len(code) - 3, 2) if code[o:o + 4] == mm.EFFECTS_MEMORY[0].to_bytes(4, "big")] == [0x40096c88, 0x40096e88, 0x400975a6]
    assert mm.EFFECTS_MEMORY[1] - mm.EFFECTS_MEMORY[0] == 9 << 16 == mm.u32(stock3, 0x40096c82)


def test_the_image(official_path, official, stereo, main):
    """The file: the save image's two programs with this one's changes, and every other section stored as it was."""
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, stereo=True)
    assert sorted(regions) == [3, 7] and built.section(7) == stereo[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    assert syms["sampler_amp"] == stereo[1]["sampler_amp"] and syms["right_fill"] == main[1]["right_fill"]
