"""Recording with the sampling page: record and its source as bits of MODE, the take's"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from emu.engine import BLOCK, Engine
from tools import audiomap as m
from tools import build_engine, build_main
from tools import mainmap as mm
from test_recorder import MainRig, frames, junk, make_block, ring_at, rnd_of, to16

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
TUNE, SAMPLE, LENGTH, MODE, DECAY = 18, 19, 21, 23, 25
MONO, STEREO, REC, EXT = 0, m.MODE_STEREO, m.MODE_REC, m.MODE_EXT  # MODE's three switches
BOX = m.REC_BOX
MARKS = m.REC_MARK.to_bytes(4, "big") + (m.REC_MARK ^ 0xFFFFFFFF).to_bytes(4, "big")
SMPL = m.DEST_SMPL


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def audio(stock):
    return build_engine.patched_image(stock, page=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, page=True)


def box_bytes(dest=None, marks=MARKS):
    """The box as the page leaves it: a destination a track."""
    dest = dict(dest or {})
    return marks + b"".join(dest.get(t, SMPL).to_bytes(2, "big") for t in range(8))


# ---- audio CPU ----------------------------------------------------------------------------------

class HookEngine(Engine):
    def block(self, trig=0, release=0):
        self.mc.set_reg(2, trig)
        self.mc.set_reg(4, release)
        return super().block(trig, release)


def engine(built, mode=MONO, pool=None):
    """Every track a sampler with SMPL on t + 1, none in a record MODE. Mono: a stereo one's right channel takes the next
    track, so a test sets STEREO on the one track it is about.
    """
    image, syms = built
    e = HookEngine(image, loop_entry=syms["sampler_hook"])
    e.mc.map(0, 0x2000)  # the shared window
    e.mc.write(0x800, bytes(np.random.default_rng(5).integers(0, 256, 0x800, dtype=np.uint8)))  # as a boot leaves it
    e.mc.write(m.MAILBOX, bytes(16))
    e.mc.write(m.KEEP_BOX, bytes(m.KEEP_SIZE))  # no save is asking for a take
    e.load_pool(pool or {})
    for t in range(m.N_VOICES):
        e.set_machine(t, SAMPLER)
        e.set_note(t, 60)
        for s in range(18, 27):
            e.set_slot(t, s, 0)
        for s, v in ((TUNE, 64), (SAMPLE, 64 + t), (LENGTH, 127), (DECAY, 127), (MODE, mode)):
            e.set_slot(t, s, v)
    e.seq = 0
    return e


def box(e, dest=None, marks=MARKS):
    e.mc.write(BOX, box_bytes(dest, marks))


def fed(e, data, trig=0, release=0):
    """One block from the feed, then one block of the audio CPU."""
    e.seq = (e.seq + 1) & 0xFFFF
    e.mc.write(m.MAILBOX + m.MAILBOX_RING + 4 * BLOCK * (e.seq % m.MAILBOX_BLOCKS), np.asarray(data).astype(">i2").tobytes())
    e.mc.write(m.MAILBOX, e.seq.to_bytes(2, "big"))
    return e.block(trig, release)


def noise(n, seed):
    return np.random.default_rng(seed).integers(-32768, 32768, (n, BLOCK, 2)).astype(np.int16)


def slot_entry(e, k):
    return e.mc.r32(m.SLOT_LEN + 8 * k), e.mc.r32(m.SLOT_PTR + 8 * k)


def taken(e, k):
    n, ptr = slot_entry(e, k)
    assert ptr == m.REC_BASE + m.REC_STRIDE * k and n
    return np.frombuffer(bytes(e.mc.read(ptr, 2 * n)), dtype=">i2")


def hold(e, track, n, seed=1):
    """A trig on the track, held for n fed blocks. Returns everything that was fed."""
    data = noise(n + 3, seed)
    for b in range(n + 3):
        fed(e, data[b], trig=1 << track if b == 0 else 0, release=1 << track if b == n else 0)
    return data


def is_take(got, data, col, n):
    """got is a stretch of what was fed, in order, ending where the note ended, about n blocks long."""
    want = data[:n + 1, :, col].ravel()
    return (n - 2) * BLOCK <= len(got) <= (n + 1) * BLOCK and np.array_equal(got, want[len(want) - len(got):])


def untouched(e, but=()):
    return all(slot_entry(e, k)[0] == 0 for k in range(m.SLOTS) if k not in but)


@pytest.mark.parametrize("mode", [REC, REC | STEREO, REC | EXT, REC | EXT | STEREO])
def test_with_the_record_bit_a_trig_starts_a_take_where_smpl_points(audio, mode):
    """Whatever the other two switches say. No box, or a box that says SMPL: the track's own stereo sample."""
    for setup in (lambda e: None, lambda e: box(e)):
        e = engine(audio)
        setup(e)
        e.set_slot(5, MODE, mode)
        data = hold(e, track=5, n=20)
        assert is_take(taken(e, 10), data, 0, 20) and is_take(taken(e, 11), data, 1, 20)
        assert untouched(e, but=(10, 11))


@pytest.mark.parametrize("dest", [0, 9, 31])
def test_dest_on_the_page_sends_the_take_to_another_stereo_sample(audio, dest):
    e = engine(audio)
    e.set_slot(2, MODE, REC)
    box(e, dest={2: dest})
    data = hold(e, track=2, n=12, seed=dest + 2)
    assert is_take(taken(e, 2 * dest), data, 0, 12) and is_take(taken(e, 2 * dest + 1), data, 1, 12)
    assert untouched(e, but=(2 * dest, 2 * dest + 1))


def test_a_destination_is_for_takes_only_and_only_its_own_tracks(audio):
    rng = np.random.default_rng(3)
    pool = {k: rng.integers(-20000, 20000, 3000).astype(np.int16) for k in range(16)}
    e = engine(audio, pool=pool)
    e.set_slot(4, MODE, REC)
    box(e, dest={0: 30, 2: 31, 4: 20})  # tracks 1 and 3 play: their destinations are not asked
    data = noise(14, 4)
    out = [fed(e, data[b], trig=0b10101 if b == 0 else 0, release=0b10101 if b == 10 else 0) for b in range(14)]
    out = np.concatenate(out, axis=1)
    assert np.any(out[0]) and np.any(out[2])  # tracks 1 and 3 play the samples SMPL is on
    assert not np.any(out[4])  # the one in record is silent
    assert is_take(taken(e, 40), data, 0, 10) and untouched(e, but=tuple(range(16)) + (40, 41))
    assert all(slot_entry(e, k)[1] != m.REC_BASE + m.REC_STRIDE * k for k in range(16))  # nothing they play was taped over


def test_switching_the_record_bit_off_ends_the_take(audio):
    e = engine(audio)
    e.set_slot(1, MODE, REC | STEREO)
    data = noise(12, 6)
    for b in range(6):
        fed(e, data[b], trig=2 if b == 0 else 0)
    e.set_slot(1, MODE, STEREO)
    for b in range(6, 12):
        fed(e, data[b])
    got = taken(e, 2)
    assert 4 * BLOCK <= len(got) <= 7 * BLOCK  # it stopped when REC went off, with the key still held
    whole = data[:, :, 0].ravel()
    assert any(np.array_equal(got, whole[a:a + len(got)]) for a in range(0, 3 * BLOCK, BLOCK))  # a stretch of what was fed


@pytest.mark.parametrize("marks", [bytes(8), MARKS[:4] + bytes(4), bytes(4) + MARKS[4:], MARKS[4:] + MARKS[:4], b"\xff" * 8])
def test_a_box_the_page_has_not_set_up_is_not_believed(audio, marks):
    """After a boot that part of the window holds the loader's last chunk: sample data, any value."""
    e = engine(audio)
    e.set_slot(3, MODE, REC)
    box(e, dest={t: 25 for t in range(8)}, marks=marks)
    data = hold(e, track=3, n=8)
    assert is_take(taken(e, 6), data, 0, 8) and untouched(e, but=(6, 7))  # where SMPL points, not where the junk says


def test_a_number_past_the_last_stereo_sample_means_smpl(audio):
    e = engine(audio)
    e.set_slot(3, MODE, REC)
    box(e, dest={3: 32})
    data = hold(e, track=3, n=6)
    assert is_take(taken(e, 6), data, 0, 6) and untouched(e, but=(6, 7))


def test_the_bit_that_was_chain_no_longer_chains(stock, audio):
    """MODE 4 and 5 were chained mono and stereo. Here the 4 is "from the input", which playing does not read."""
    def run(mode):
        rng = np.random.default_rng(12)
        e = engine(audio, pool={k: rng.integers(-20000, 20000, 400).astype(np.int16) for k in range(8)})
        e.set_slot(0, MODE, mode)
        e.block(trig=1)
        return np.concatenate([e.block() for _ in range(40)], axis=1)[:2]
    assert np.array_equal(run(EXT), run(MONO)) and np.array_equal(run(EXT | STEREO), run(STEREO))
    assert not np.any(run(MONO)[0][-10 * BLOCK:])  # one slot of 400 frames, then silence: the next is not played on


def test_a_new_take_is_not_on_the_drive(audio):
    e = engine(audio)
    for k in (12, 13, 14):
        e.mc.w32(m.KEPT + 4 * k, 0x1234 + k)
    e.set_slot(0, MODE, REC)
    box(e, dest={0: 6})
    hold(e, track=0, n=4)
    assert (e.mc.r32(m.KEPT + 4 * 12), e.mc.r32(m.KEPT + 4 * 13)) == (0, 0)  # so the next project save keeps it
    assert e.mc.r32(m.KEPT + 4 * 14) == 0x1234 + 14


def test_the_audio_cpu_reads_the_box_in_words_and_longs_and_writes_nothing_there(audio):
    e = engine(audio)
    seen = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: seen.append(("w", addr, size)), begin=BOX, end=BOX + m.REC_SIZE - 1)
    e.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, u: seen.append(("r", addr, size)), begin=BOX, end=BOX + m.REC_SIZE - 1)
    e.mc.uc.ctl_flush_tb()
    e.set_slot(3, MODE, REC | EXT)
    box(e, dest={3: 11})
    hold(e, track=3, n=5)
    assert seen and all(kind == "r" and size in (2, 4) and addr % size == 0 for kind, addr, size in seen)
    assert (BOX + m.REC_DEST + 6, 2) in {(addr, size) for _, addr, size in seen}  # track 4's destination


def test_the_take_plays_back_when_the_record_bit_goes_off(audio):
    """REC on, hold a trig, REC off, play: with DEST on SMPL the track plays what it just recorded."""
    e = engine(audio)
    e.set_slot(3, MODE, REC | STEREO)
    box(e)
    hold(e, track=3, n=40, seed=11)
    e.set_slot(3, MODE, STEREO)
    e.block(trig=1 << 3)
    out = [e.block() for _ in range(6)]
    left = np.concatenate([o[3] for o in out]).astype(np.float64)
    right = np.concatenate([o[4] for o in out]).astype(np.float64)
    want = taken(e, 6).astype(np.float64), taken(e, 7).astype(np.float64)
    heard = lambda x, w: max(np.corrcoef(x[k:k + 5 * BLOCK], w[:5 * BLOCK])[0, 1] for k in range(BLOCK + 1))
    assert heard(left, want[0]) > 0.99 and heard(right, want[1]) > 0.99  # left on the track, right on the next


@pytest.mark.parametrize("setup", ["no box", "a box"])
def test_playing_is_the_keep_images_sample_for_sample(stock, audio, setup):
    def run(built):
        rng = np.random.default_rng(12)
        e = engine(built, pool={k: rng.integers(-20000, 20000, 3000).astype(np.int16) for k in range(8)})
        e.set_slot(2, MODE, STEREO)
        if setup != "no box":
            box(e, dest={t: t + 3 for t in range(8)})
        e.block(trig=0b0101)
        return np.concatenate([e.block() for _ in range(12)], axis=1)
    assert np.array_equal(run(audio), run(build_engine.patched_image(stock, keep=True)))


def test_what_it_costs_on_the_audio_cpu(stock, audio):
    def count(built, starting):
        e = engine(built)
        box(e)
        e.block(trig=0xFF)
        e.block()
        e.block(trig=0xFF if starting else 0)
        n0 = e.mc.insns
        e.block()
        return e.mc.insns - n0
    keep = build_engine.patched_image(stock, keep=True)
    playing = count(audio, False) - count(keep, False)
    starting = count(audio, True) - count(keep, True)
    assert (playing, starting) == COST  # eight sampler voices; a voice's budget is 10,506


COST = (0, 128)  # a block more than the keep image's, all eight tracks samplers: notes running, notes starting


# ---- main CPU: the feed ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return MainRig(*main)


ALL = [SAMPLER] * 8 + [8, 9, 10, 11]


def fed_from(before, frame, left):
    want = bytearray(before)
    want[m.MAILBOX:m.MAILBOX + 2] = (0x0106).to_bytes(2, "big")
    pair, rnd = to16(frame[:, left:left + 2], rnd_of(before))
    want[ring_at(0x0106):ring_at(0x0106) + 4 * BLOCK] = pair.astype(">i2").tobytes()
    want[m.MAILBOX + 4:m.MAILBOX + 8] = rnd.to_bytes(4, "big")
    return bytes(want)


@pytest.mark.parametrize("mode, left", [(REC, mm.F_MAIN_L), (REC | STEREO, mm.F_MAIN_L), (REC | EXT, mm.F_EXT_L), (REC | EXT | STEREO, mm.F_EXT_L)])
@pytest.mark.parametrize("track", [0, 7])
def test_the_feed_runs_for_a_track_whose_record_bit_is_set_from_the_source_its_own_bit_says(rig, track, mode, left):
    frame = frames()
    before = junk(0x0105)
    ret, after = rig.run(make_block(ALL, [0] * track + [mode] + [0] * (11 - track)), frame, before)
    assert ret == 0x8000DBD0
    assert after == fed_from(before, frame, left)  # one block, the counter, the dither's number: nothing else


@pytest.mark.parametrize("mode", [MONO, STEREO, EXT, EXT | STEREO])
def test_without_the_record_bit_nothing_is_fed(rig, mode):
    before = junk(0x0105)
    _, after = rig.run(make_block(ALL, [mode] * 12), frames(), before)
    assert after == before


def test_the_first_track_in_record_picks_the_source(rig):
    frame = frames()
    before = junk(0x0105)
    _, after = rig.run(make_block(ALL, [0, 0, REC, 0, 0, REC | EXT] + [0] * 6), frame, before)
    assert after == fed_from(before, frame, mm.F_MAIN_L)
    _, after = rig.run(make_block(ALL, [0, 0, REC | EXT, 0, 0, REC] + [0] * 6), frame, before)
    assert after == fed_from(before, frame, mm.F_EXT_L)


def test_nothing_is_fed_while_the_boot_loader_has_the_window(rig):
    rig.mc.w32(mm.AUDIO_UP, 0)
    try:
        before = junk(0x0105)
        _, after = rig.run(make_block(ALL, [REC] * 12), frames(), before)
        assert after == before
    finally:
        rig.mc.w32(mm.AUDIO_UP, 1)


def test_the_feed_does_not_touch_the_box(main):
    r = MainRig(*main)
    seen = []
    for kind in (UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE):
        r.mc.uc.hook_add(kind, lambda uc, a, addr, size, v, u: seen.append(addr), begin=mm.SHARED + BOX, end=mm.SHARED + BOX + m.REC_SIZE - 1)
    r.mc.uc.ctl_flush_tb()
    r.run(make_block(ALL, [REC | EXT] * 12), frames(), junk(0x0105))
    assert not seen


# ---- the image --------------------------------------------------------------------------------------

def test_the_audio_program_differs_from_the_keep_images_only_in_our_code_space(stock, audio):
    keep = build_engine.patched_image(stock, keep=True)[0]
    diff = [m.BASE + i for i in range(len(keep)) if keep[i] != audio[0][i]]
    spans = list(m.CAVES.values()) + list(m.REC_CAVES.values())
    # and the three pointers into it, which follow the code as it moves
    spans += [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    assert m.REC_BOX + m.REC_SIZE <= 0x1000 and m.REC_BOX == m.KEEP_BOX + m.KEEP_SIZE  # in the window, past the keep box
