"""Phase 5: the sampler engine, compiled for ColdFire, inside the real voice loop."""
import re
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ

from emu import engine as E
from emu import sampler_ref as ref
from emu.engine import BLOCK, Engine
from emu.machine import boundaries
from tools import audiomap as m
from tools import build_engine, params

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
TUNE, SAMPLE, START, LENGTH, LOOP, MODE, DECAY = 18, 19, 20, 21, 22, 23, 25
BUDGET = 10506  # SY SWARM, instructions per voice per block (Phase 3)
STOCK_TWINSHOT = 3883
MONO_STEREO = (2176, 2904)  # the sampler, one voice, steady
WORST = (7848, 9079)  # steady and in any one block, see test_instruction_budget


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def built(stock):
    return build_engine.patched_image(stock)


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


def make_pool():
    """Noise-like slots of awkward lengths, so every frame and seam is distinguishable."""
    rng = np.random.default_rng(7)

    def noise(n):
        return rng.integers(-32768, 32768, n).astype(np.int16)
    pool = {0: noise(1500), 1: noise(1500)}
    pool.update({4: noise(300), 5: noise(257), 6: noise(411)})  # a mono chain; slot 7 empty
    pool.update({10: noise(350), 11: noise(350), 12: noise(290), 13: noise(290)})  # a stereo chain
    pool[20] = (np.arange(64) * 500 - 16000).astype(np.int16)  # a ramp
    return pool


def setup(image, syms, pool, track=0, note=60, **knobs):
    e = Engine(image, loop_entry=syms["sampler_hook"])
    e.load_pool(pool)
    values = {TUNE: 64, SAMPLE: 64, START: 0, LENGTH: 127, LOOP: 0, MODE: 0, DECAY: 127}
    values.update({globals()[k.upper()]: v for k, v in knobs.items()})
    for t in range(m.N_VOICES):
        e.set_machine(t, SAMPLER)
        e.set_note(t, note)
        for slot in range(18, 27):
            e.set_slot(t, slot, 0)
        e.set_slot(t, SAMPLE, 64 + 63)  # the other tracks point at an empty slot
        e.set_slot(t, DECAY, 127)
    for slot, v in values.items():
        e.set_slot(track, slot, v)
    return e


def run_both(image, syms, pool, blocks, track=0, note=60, **knobs):
    """Engine output and the reference's, from the block the note starts in."""
    e = setup(image, syms, pool, track=track, note=note, **knobs)
    x = e.render(blocks + 1, trig=1 << track)
    assert not x[:, :BLOCK].any()
    p = ref.Player(pool)
    p.inc = e.player(track, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127),
              loop=knobs.get("loop", 0), mode=knobs.get("mode", 0))
    left, right = [], []
    for _ in range(blocks):
        l, r = p.block(stereo_out=track < m.N_VOICES - 1)
        left += ref.tail(l)
        right += ref.tail(r) if r is not None else []
    return e, x[:, BLOCK:], np.array(left), np.array(right), p


# ---- the code lives only in dead stock code ---------------------------------

ALL_CAVES = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES)  # the later images' runs are held to the same rules
NOT_A_POINTER = 0x4001c7f2  # two neighbours in a table of rising longs, read across their join: see the test


def test_caves_are_unreferenced(stock):
    def in_cave(a):
        return any(s <= a < e for s, e in ALL_CAVES.values())
    # no 32-bit value anywhere in the image points into a cave
    for o in range(0, len(stock) - 3, 2):
        if not in_cave(m.BASE + o) and m.BASE + o != NOT_A_POINTER:
            assert not in_cave(int.from_bytes(stock[o:o + 4], "big")), hex(m.BASE + o)
    # but for one place, where the low half of one entry of a rising table and the high half of the next read as an
    # address in the fade image's run. It is an odd number, which no code address is, and the table says what it is.
    o = m.off(NOT_A_POINTER) - 18
    table = [int.from_bytes(stock[o + 4 * k:o + 4 * k + 4], "big") for k in range(10)]
    assert table[4:6] == [0x2fa24000, 0x38519380] and all(a < b for a, b in zip(table, table[1:]))
    assert int.from_bytes(stock[m.off(NOT_A_POINTER):m.off(NOT_A_POINTER) + 4], "big") == 0x40003851
    assert NOT_A_POINTER > m.CODE_END
    # no instruction outside a cave names an address inside one, and nothing jumps through a table
    for addr, _, text in boundaries(stock[4:m.off(m.CODE_END)], m.BASE + 4):
        if in_cave(addr):
            continue
        assert not re.match(r"jmp %", text), hex(addr)
        for x in re.findall(r"0x([0-9a-f]{8})\b", text):
            assert not in_cave(int(x, 16)), hex(addr)
    # each cave starts on a function entry and the byte before it ends one
    for start, end in ALL_CAVES.values():
        assert stock[m.off(start) - 2:m.off(start)] in (b"\x4e\x75", b"\x00\x00")
        assert stock[m.off(end) - 2:m.off(end)] in (b"\x4e\x75", b"\x00\x00")
        assert start < m.CODE_END and end <= m.CODE_END


def test_caves_never_run_or_get_read_in_the_stock_engine(stock, descs, official):
    """Every stock machine through the voice loop, and the whole interrupt: caves untouched."""
    seen = []
    track_defaults = {p.slot: p.default for p in params.load(official.section(3), official.version)
                      if p.type in (47, 45)}
    b = E.Board(stock)
    b.load_pool({0: np.arange(2000, dtype=np.int16)})
    for start, end in ALL_CAVES.values():
        b.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.append(a), begin=start, end=end - 1)
        b.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: seen.append(a), begin=start, end=end - 1)
    b.mc.uc.ctl_flush_tb()
    for mtype in m.TYPE_OF_ENGINE:
        for t in range(m.N_VOICES):
            b.set_defaults(t, mtype, descs)
            b.set_note(t, 48 + 5 * t)
            for slot, v in track_defaults.items():
                b.set_slot(t, slot, v)
        for blk in range(12):
            b.interrupt(0xFF if blk in (0, 6) else 0, 0xFF if blk == 9 else 0)
    assert not seen


def test_patch_touches_only_the_caves_and_three_pointers(stock, built):
    image, syms = built
    diff = {m.BASE + i for i in range(len(stock)) if stock[i] != image[i]}
    allowed = set()
    for start, end in m.CAVES.values():
        allowed |= set(range(start, end))
    for site in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE,
                 m.ISR_VOICE_LOOP_CALL + 2):
        allowed |= set(range(site, site + 4))
    assert diff <= allowed
    assert m.u32(image, m.UPDATE_TABLE + 4 * m.TWIN_ENGINE) == syms["sampler_update"]
    assert m.u32(image, m.RENDER_TABLE + 4 * m.TWIN_ENGINE) == syms["sampler_render"]
    assert m.u32(image, m.ISR_VOICE_LOOP_CALL + 2) == syms["sampler_hook"]
    assert image[m.off(m.ISR_VOICE_LOOP_CALL):m.off(m.ISR_VOICE_LOOP_CALL) + 2] == b"\x4e\xb9"  # still jsr (xxx).L
    # stock Twinshot is still there, byte for byte, just unreached
    assert image[m.off(m.TWIN_UPDATE):m.off(0x40009b1a)] == stock[m.off(m.TWIN_UPDATE):m.off(0x40009b1a)]


def test_engine_code_is_plain_integer_code(built):
    image, syms = built
    e = Engine(image)
    for start, end in m.CAVES.values():
        assert not [a for a in e.mc.emac_sites if start <= a < end]  # no EMAC of our own
    for name, addr in syms.items():
        assert any(s <= addr < e_ for s, e_ in m.CAVES.values()), name


# ---- stock machines are untouched --------------------------------------------

@pytest.mark.parametrize("mtype", [t for t in m.TYPE_OF_ENGINE if t != SAMPLER])
def test_stock_machines_stay_bit_identical(stock, built, descs, mtype):
    image, syms = built
    out = []
    for img, entry in ((stock, m.VOICE_LOOP), (image, m.VOICE_LOOP), (image, syms["sampler_hook"])):
        e = Engine(img, loop_entry=entry)
        for t in range(m.N_VOICES):
            e.set_defaults(t, mtype, descs)
            e.set_note(t, 55 + 3 * t)
        out.append((e.render(24, trig=0xFF), e.mc.insns))
    assert out[0][0].any()
    assert np.array_equal(out[0][0], out[1][0]) and np.array_equal(out[0][0], out[2][0])
    assert out[0][1] == out[1][1]  # same instruction count through the stock entry


# ---- bit-identical to the reference model -----------------------------------

CASES = {
    "one-shot": dict(),
    "one-shot, up a fifth": dict(note=67),
    "one-shot, down 7": dict(note=53),
    "tuned by the knob": dict(tune=70.5),
    "reverse": dict(sample=63),
    "reverse, pitched": dict(sample=63, note=65),
    "start and length": dict(start=40, length=50),
    "start and length, reverse": dict(sample=63, start=40, length=50, note=62),
    "loop": dict(loop=1, start=10, length=30, note=64),
    "loop whole sample": dict(loop=1, note=58),
    "loop, reverse": dict(sample=63, loop=1, start=10, length=30, note=64),
    "ping-pong": dict(loop=2, start=10, length=30, note=64),
    "ping-pong, reverse": dict(sample=63, loop=2, start=5, length=40, note=66),
    "loop knob at 3 is ping-pong": dict(loop=3, start=10, length=30, note=64),
    "loop knob reads its low two bits": dict(loop=65, start=10, length=30, note=64),
    "tiny loop, fast": dict(loop=1, start=20, length=1, note=84),
    "loop too small for its pitch": dict(loop=1, start=20, length=1, note=108),
    "ping-pong too small for its pitch": dict(loop=2, start=20, length=1, note=108),
    "chain": dict(sample=68, mode=4),
    "chain, pitched": dict(sample=68, mode=4, note=71),
    "chain, reverse": dict(sample=63 - 4, mode=4, note=63),
    "chain, region across seams": dict(sample=68, mode=4, start=20, length=100, note=57),
    "chain, loop across seams": dict(sample=68, mode=4, loop=1, start=20, length=100, note=66),
    "chain, ping-pong across seams": dict(sample=68, mode=4, loop=2, start=20, length=110, note=69),
    "chain, reverse ping-pong": dict(sample=63 - 4, mode=4, loop=2, start=15, length=110, note=61),
    "chain mode on a single slot": dict(sample=64 + 20, mode=4, note=48),
    "record modes play as mono without the recorder": dict(mode=2),
    "record modes play as mono without the recorder, chain": dict(sample=68, mode=7, loop=1, note=66),
    "empty slot": dict(sample=64 + 30),
}


@pytest.mark.parametrize("name", CASES)
def test_engine_matches_reference(built, name):
    image, syms = built
    knobs = dict(CASES[name])
    note = knobs.pop("note", 60)
    e, x, left, right, p = run_both(image, syms, make_pool(), 150, note=note, **knobs)
    assert np.array_equal(x[0], left), name
    assert not x[1:].any()
    if name != "empty slot":
        assert left.any()
    assert bool(e.player(0, 0)["playing"]) == p.playing


STEREO_CASES = {
    "stereo": dict(sample=64 + 5, mode=1),  # stereo sample 5: slots 10 and 11
    "stereo, pitched reverse": dict(sample=63 - 5, mode=1, note=66),
    "stereo loop": dict(sample=64 + 5, mode=1, loop=1, start=10, length=60, note=62),
    "stereo chain": dict(sample=64 + 5, mode=5, note=64),
    "stereo chain ping-pong": dict(sample=64 + 5, mode=5, loop=2, start=10, length=110, note=67),
}


@pytest.mark.parametrize("track", [0, 3, 6])
@pytest.mark.parametrize("name", STEREO_CASES)
def test_stereo_puts_right_on_the_next_track(built, name, track):
    image, syms = built
    knobs = dict(STEREO_CASES[name])
    note = knobs.pop("note", 60)
    e, x, left, right, p = run_both(image, syms, make_pool(), 100, track=track, note=note, **knobs)
    assert np.array_equal(x[track], left)
    assert np.array_equal(x[track + 1], right)
    assert right.any() and not np.array_equal(left, right)
    others = [t for t in range(m.N_VOICES) if t not in (track, track + 1)]
    assert not x[others].any()


def test_in_stereo_the_sample_knob_counts_stereo_samples(built):
    """Every value of the knob is a left slot: number n is slots 2n and 2n + 1. In mono it is slot n. Past number 31
    there is no stereo sample, and nothing plays or is read.
    """
    image, syms = built
    rng = np.random.default_rng(5)
    pool = {k: rng.integers(-32768, 32768, 200 + k).astype(np.int16) for k in range(64)}
    for knob, slot in ((64, 0), (65, 2), (64 + 31, 62), (63, 0), (62, 2), (63 - 31, 62)):
        e, x, left, right, p = run_both(image, syms, pool, 12, track=2, sample=knob, mode=1)
        assert np.array_equal(x[2], left) and np.array_equal(x[3], right)
        want_l, want_r = pool[slot].astype(np.int64) << 15, pool[slot + 1].astype(np.int64) << 15
        if knob < 64:
            want_l, want_r = want_l[::-1], want_r[::-1]
        assert np.array_equal(x[2][:len(want_l)], want_l)
        assert np.array_equal(x[3][:len(want_l)], want_r[-len(want_l):] if knob < 64 else want_r[:len(want_l)])
    for knob in (64 + 32, 127, 63 - 32, 0):
        for mode in (1, 5):
            e = setup(image, syms, pool, track=2, sample=knob, mode=mode)
            assert not e.render(6, trig=4).any() and not e.player(2, 0)["playing"]
    e, x, left, right, p = run_both(image, syms, pool, 12, track=2, sample=64 + 5, mode=0)  # mono: slot 5 itself
    assert np.array_equal(x[2][:205], pool[5].astype(np.int64) << 15) and not x[3].any()


def test_stereo_on_the_last_track_plays_left_only(built):
    image, syms = built
    e, x, left, right, p = run_both(image, syms, make_pool(), 40, track=7, sample=64 + 5, mode=1)
    assert np.array_equal(x[7], left) and left.any()
    assert not x[:7].any() and len(right) == 0


def test_one_to_one_playback_is_the_sample_itself(built):
    image, syms = built
    pool = make_pool()
    e, x, left, right, p = run_both(image, syms, pool, 60)
    n = len(pool[0])
    assert np.array_equal(x[0][:n], pool[0].astype(np.int64) << 15)  # int16 at -6 dB, no rounding
    assert not x[0][n:].any()


def test_retrigger_fades_the_old_note_then_restarts(built):
    image, syms = built
    pool = make_pool()
    e = setup(image, syms, pool, note=60)
    p = ref.Player(pool)
    e.block(trig=1)
    got, want = [], []
    for b in range(1, 30):
        got.append(e.block(trig=1 if b == 12 else 0)[0])
        if b in (1, 13):  # a note starts the block after its trig
            p.inc = e.player(0, 0)["inc"]
            p.note_on()
        l, _ = p.block()
        want.append(ref.tail(l, trig=b == 12))
    assert np.array_equal(np.concatenate(got), np.concatenate(want))
    assert np.abs(got[11][-4:]).max() < 0.02 * np.abs(got[11][:4]).max()  # faded out by the end of the trig block


def test_long_sample_across_slots_past_the_one_slot_limit(built):
    """Three chained slots, 600,000 frames: more than one slot's 524,287 can hold."""
    image, syms = built
    rng = np.random.default_rng(3)
    pool = {8 + k: rng.integers(-32768, 32768, 200000).astype(np.int16) for k in range(3)}
    blocks = 600000 // (BLOCK * 8) + 40  # three octaves up: 8 frames per frame
    e, x, left, right, p = run_both(image, syms, pool, blocks, note=96, sample=64 + 8, mode=4)
    assert e.player(0, 0)["inc"] == 8 * 4096
    assert np.array_equal(x[0], left)
    last = np.flatnonzero(x[0])[-1]
    assert 600000 // 8 - 4 <= last < 600000 // 8  # it ran to the end of the third slot
    assert not p.playing


def test_fastest_pitch_cannot_overflow_the_position(built):
    """A slot at the length limit, played at the top of the pitch range, ends cleanly."""
    image, syms = built
    n = ref.MAX_FRAMES + 300  # longer than the engine will use
    pool = {0: np.full(n, 12345, dtype=np.int16)}
    e = setup(image, syms, pool, note=127, tune=88, start=126.9)
    x = e.render(60, trig=1)[0]
    inc = e.player(0, 0)["inc"]
    assert 4096 * 32 < inc < 4096 * 64  # the largest step the stock pitch code gives
    assert (ref.MAX_FRAMES << 12) + inc < 1 << 31
    played = np.flatnonzero(x)
    assert len(played) and set(np.unique(x[played])) == {12345 << 15}  # only ever read real samples
    assert not e.player(0, 0)["playing"]


def test_decay_knob_still_shapes_the_note(built):
    """The stock envelope is reused as is: 127 holds, lower values fall faster."""
    image, syms = built
    pool = {0: np.full(6000, 20000, dtype=np.int16)}

    def level(decay):
        x = setup(image, syms, pool, decay=decay).render(100, trig=1)[0].astype(float)
        assert np.all(np.diff(np.abs(x[BLOCK:])) <= 0)  # never rises
        return np.abs(x[-BLOCK:]).max()
    assert level(127) == 20000 << 15
    assert level(10) < level(40) < level(80) < level(127)
    assert level(10) < 0.1 * level(127)


# ---- CPU budget ----------------------------------------------------------------

def per_voice(image, syms, pool, blocks=40, note=60, **knobs):
    e = setup(image, syms, pool, note=note, **knobs)
    for t in range(m.N_VOICES):
        for slot in range(18, 27):
            e.mc.write(e.params(t) + m.PARAM_KNOBS + 2 * slot,
                       e.mc.read(e.params(0) + m.PARAM_KNOBS + 2 * slot, 2))
    counts = []
    for b in range(blocks):
        before = e.mc.insns
        e.mc.call(m.VOICE_LOOP, m.OUT_BUF, m.PARAM_BUF, 0xFF if b == 0 else 0, 0)
        counts.append(e.mc.insns - before)
    return max(counts[2:]) / m.N_VOICES, max(counts) / m.N_VOICES


def test_a_loop_too_small_for_its_pitch_stops_the_note(built):
    """9 frames, 16 frames a frame: 57 turns a block where 40 are allowed. Two octaves lower it plays on."""
    image, syms = built
    for note, plays in ((84, True), (108, False)):
        e = setup(image, syms, make_pool(), note=note, loop=1, start=20, length=1)
        x = e.render(6, trig=1)[0]
        assert x[BLOCK:2 * BLOCK].any()  # it starts either way
        assert bool(x[3 * BLOCK:].any()) == plays and bool(e.player(0, 0)["playing"]) == plays


def test_instruction_budget(built):
    image, syms = built
    big = {k: np.zeros(50000, dtype=np.int16) for k in (0, 1)}
    mono, _ = per_voice(image, syms, big)
    stereo, _ = per_voice(image, syms, big, mode=1)
    assert mono < STOCK_TWINSHOT  # cheaper than the machine it replaces
    assert stereo < STOCK_TWINSHOT
    assert (round(mono), round(stereo)) == MONO_STEREO
    # the worst there is: a stereo chain looping over a few frames around a slot seam, octaves up. The loops that fit
    # the pitch play on; the others stop within a block (MAX_EDGES).
    steady, spikes, playing = [], [], 0
    for note, length in ((96, 5), (96, 6), (96, 7), (108, 9), (108, 12), (127, 20), (127, 40)):
        for loop in (1, 2):
            knobs = dict(note=note, mode=5, loop=loop, sample=64 + 5, start=69, length=length)
            a, b = per_voice(image, syms, make_pool(), **knobs)
            steady.append(a)
            spikes.append(b)
            e = setup(image, syms, make_pool(), **knobs)
            e.render(20, trig=1)
            playing += e.player(0, 0)["playing"]
    assert 4 <= playing <= 10  # both kinds are in the sweep
    assert max(spikes) < BUDGET
    assert (round(max(steady)), round(max(spikes))) == WORST


# ---- stereo through the real interrupt: the next track follows -------------------

AMP_STATE = 0x800049e0  # 12 bytes per track, kept by the amp stage


def stereo_board(image, mode, track1_machine=SAMPLER):
    rng = np.random.default_rng(11)
    both = rng.integers(-20000, 20000, 3000).astype(np.int16)
    b = E.Board(image)
    b.load_pool({10: both, 11: both.copy()})  # dual mono: left and right carry the same data
    for t in range(m.N_VOICES):
        b.set_machine(t, SAMPLER)
        b.set_note(t, 60)
        for slot in range(18, 52):
            b.set_slot(t, slot, 0)
        b.set_slot(t, SAMPLE, 127)  # empty slot
        b.set_slot(t, DECAY, 127)
    # track 0: the instrument, with its own filter, drive and amp settings
    for slot, v in ((TUNE, 64), (LENGTH, 127), (SAMPLE, 64 + (5 if mode == 1 else 10)), (MODE, mode), (26, 90), (27, 2), (29, 40), (37, 20), (38, 100),
                    (40, 0), (41, 64), (42, 127), (43, 100), (44, 32), (50, 1), (51, 1)):
        b.set_slot(0, slot, v)
    b.set_cutoff(0, 0x52345678)
    # track 1: deliberately different, and with a different machine if asked
    b.set_machine(1, track1_machine)
    for slot, v in ((26, 5), (27, 5), (29, 99), (37, 77), (38, 11), (41, 3), (42, 9), (43, 1), (44, 120)):
        b.set_slot(1, slot, v)
    b.set_cutoff(1, 0x00777777)
    return b


@pytest.mark.parametrize("track1_machine", [SAMPLER, 4, 38])
def test_right_track_gets_the_left_tracks_filter_amp_and_trigs(built, track1_machine):
    image, syms = built
    b = stereo_board(image, mode=1, track1_machine=track1_machine)
    for blk in range(14):
        b.interrupt(trig=0x01 if blk in (0, 8) else 0, release=0x01 if blk == 5 else 0)
        for name in ("voice_loop", "gain", "drive", "filter", "amp"):
            assert np.array_equal(b.stages[name][1], b.stages[name][0]), (blk, name)
        if blk >= 1:
            assert b.stages["voice_loop"][0].any() and b.stages["amp"][0].any()
        assert not b.stages["voice_loop"][2:].any()
        p0, p1 = b.mc.read(b.params(0), m.PARAM_STRIDE), b.mc.read(b.params(1), m.PARAM_STRIDE)
        assert p1[80:132] == p0[80:132]  # OVER and the filter and amp pages
        assert p1[62] == track1_machine  # its own machine setting is left alone
        assert b.mc.r32(0x80008188 + 4) == 0x52345678
        assert b.mc.read(AMP_STATE + 12, 12) == b.mc.read(AMP_STATE, 12)  # same trigs reached the amp stage


def test_mono_notes_leave_the_next_track_alone(built):
    image, syms = built
    b = stereo_board(image, mode=0)
    for blk in range(6):
        b.interrupt(trig=0x01 if blk == 0 else 0)
    assert b.stages["voice_loop"][0].any() and not b.stages["voice_loop"][1:].any()
    p1 = b.mc.read(b.params(1), m.PARAM_STRIDE)
    assert p1[0x1c + 2 * 37] == 77 and p1[0x1c + 2 * 26] == 5  # its own settings survive
    assert b.mc.r32(0x80008188 + 4) == 0x00777777


def test_interrupt_still_hands_over_eight_buffers(built):
    image, syms = built
    b = stereo_board(image, mode=1)
    for blk in range(4):
        out = b.interrupt(trig=0x01 if blk == 0 else 0)
    assert b.dma() == (m.OUT_BUF, E.HOST + E.HOST_AUDIO, m.N_VOICES * m.OUT_STRIDE)
    assert np.array_equal(out, b.stages["amp"])
