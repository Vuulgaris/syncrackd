"""The dma image: the gfade image with the right channels brought out of the window by the transfer controller.

The maintainer, 2026-10-12, with the gfade image on the maintainer's unit: the screen and knobs lag when stereo samples play and not
when mono ones do; "i def need all 8 move it the way stock does. we sould do the full fix like ewlektorn would do".

Emulation has no transfer controller. What is shown here: our two channels are written what stock writes its own
channel 47, word for word and in its order (stock's own code is run for that); the routine around them, with a
stand-in for the controller that moves what its words say when a channel is started (TransferModel: a stand-in, and
it would share a mistake about the controller itself); what the routine does when the stand-in brings something
else, brings nothing, or never ends. That a transfer ends on the unit and what it brings there, only the unit can
show, which is why the routine checks its transfers against the CPU's reads for a second after every start.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC

import test_mode as MO
import test_stereo as S
import test_xfade as X
from test_stereo import some_tracks, stock3, window_of  # noqa: F401  (stock3 is a fixture)
from emu.machine import Machine
from tools import audiomap as m
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

RIGHT, SCRATCH, STATE = mm.RIGHT_SRAM, mm.RIGHT_SCRATCH, mm.RIGHT_STATE
S_MASK, S_ARMED, S_GOOD, S_BAD, S_MODE, S_SET, S_POLLS, S_WHY = range(8)
CHECK, TRUSTED, DEAD = range(3)
GOOD_BLOCKS, BAD_BLOCKS, POLL_LIMIT = 1500, 16, 20000
CH_A, CH_B = mm.DMA_RIGHT
TCD, SSRT, CERQ = 0xfc045000, 0xfc04401e, 0xfc044019
STACK = 0x407ff000
STOPS_MARK = mm.SHARED + 0x5bc


@pytest.fixture(scope="module")
def main(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=3)


@pytest.fixture(scope="module")
def gfade(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=2)


class TransferModel:
    """A stand-in for the controller. A write of a channel's number to the start register moves what the channel's
    words say, sixteen bytes a turn, and sets its done bit: at once, or after `late` reads of its last word, or never."""

    def __init__(self, mc, late=0, never=False, spoil=None, nothing=False):
        self.mc, self.late, self.never, self.spoil, self.nothing = mc, late, never, spoil, nothing
        self.started, self.waiting, self.polls, self.log = [], {}, {}, []
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, self.wrote, begin=0xfc044000, end=0xfc045fff)
        mc.uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=TCD, end=0xfc045fff)

    def words(self, ch):
        t, mc = TCD + 32 * ch, self.mc
        w16 = lambda a: int.from_bytes(mc.read(a, 2), "big")
        return dict(src=mc.r32(t), attr=w16(t + 4), soff=w16(t + 6), nbytes=mc.r32(t + 8), slast=mc.r32(t + 12), dst=mc.r32(t + 16),
                    citer=w16(t + 20), doff=w16(t + 22), dlast=mc.r32(t + 24), biter=w16(t + 28), csr=w16(t + 30))

    def wrote(self, uc, access, address, size, value, user):
        self.log.append((address, size, value & (1 << 8 * size) - 1))
        if address == SSRT:
            ch = value & 0xff
            self.started.append(ch)
            w = self.words(ch)
            self.mc.write(TCD + 32 * ch + 30, bytes(2))                 # a channel that is started is not done
            self.waiting[ch], self.polls[ch] = w, 0
            if not self.late and not self.never:
                self.move(ch)

    def read(self, uc, access, address, size, value, user):
        ch, word = (address - TCD) // 32, (address - TCD) % 32
        if word == 30 and ch in self.waiting and not self.never:
            self.polls[ch] += 1
            if self.polls[ch] > self.late:
                self.move(ch)

    def move(self, ch):
        w = self.waiting.pop(ch)
        assert w["attr"] == 0x0404 and w["soff"] == w["doff"] == w["nbytes"] == 16 and not w["slast"] and not w["dlast"]
        assert w["citer"] == w["biter"] and w["citer"] >> 15 and w["citer"] >> 9 & 0x3f == ch       # every turn starts the next of its own channel
        assert not w["src"] % 16 and not w["dst"] % 16
        n = 16 * (w["citer"] & 0x1ff)
        data = bytearray(self.mc.read(w["src"], n))
        if self.spoil is not None and self.spoil < n:
            data[self.spoil] ^= 0x40
        if not self.nothing:
            self.mc.write(w["dst"], bytes(data))
        self.mc.write(TCD + 32 * ch + 30, b"\x00\x80")


class Rig:
    """The main CPU around the two routines: on-chip memory, the window, the controller's words as memory."""

    def __init__(self, built, **model):
        image, self.syms = built
        mc = self.mc = Machine()
        for base, size in ((0x40000000, 0x800000), (0x80000000, 0x10000), (0x43bd0000, 0x10000), (mm.SHARED, 0x2000), (0xfc000000, 0x100000)):
            mc.map(base, size)
        mc.write(mm.BASE, image)
        for a, b in (mm.CAVE_DMA, mm.CAVE_DMA2, (mm.BLOCK_FIRST, mm.BLOCK_FIRST + 0x14), (mm.BLOCK_FIRST_CALL, mm.BLOCK_FIRST_CALL + 6),
                     (mm.PRE_MIX_CALL, mm.PRE_MIX_CALL + 6), (mm.DMA_WAIT, mm.DMA_WAIT + 0x22), (mm.RIGHT_HOOK, S.SEND)):
            mc.load_code(a, image[mm.off(a):mm.off(b)])
        mc.set_stack(STACK, 0x40000100)
        mc.set_exits([0x40000100, mm.BLOCK_FIRST_CALL + 6, mm.PRE_MIX_CALL + 6, mm.PRE_MIX, S.SEND, S.SKIP])
        self.reads, self.writes = [], []
        mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: self.reads.append((a, s)))
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: self.writes.append((a, s)))
        self.model = TransferModel(mc, **model)
        mc.uc.ctl_flush_tb()
        mc.write(SCRATCH - 64, b"\xee" * (STATE + 32 + 64 - (SCRATCH - 64)))
        mc.write(STATE, bytes(32))                      # as the startup leaves it
        mc.w32(mm.AUDIO_UP, 1)

    def state(self, k, v=None):
        if v is None:
            return self.mc.r32(STATE + 4 * k)
        self.mc.w32(STATE + 4 * k, v)

    def block(self, tracks, window, up=1):
        """One block: the first call's routine, stock's own transfer of the left buffers, the routine where stock waits
        for it, the routine before the mixer."""
        mc = self.mc
        mc.write(mm.SHARED, window)
        mc.w32(mm.AUDIO_UP, up)
        mc.write(S.DMA_FLAG, b"\0")                     # no transfer of stock's is running: its wait ends at once
        self.reads, self.writes, self.model.started, self.model.log = [], [], [], []
        mc.call(self.syms["right_begin"])
        self.begin_reads = list(self.reads)
        mc.write(mm.TRACKS, np.asarray(tracks).astype(">i4").tobytes())
        assert mc.call(self.syms["right_mid"]) == up
        self.mid_reads = self.reads[len(self.begin_reads):]
        mc.call(self.syms["right_end"])
        return np.frombuffer(mc.read(RIGHT, 1024), dtype=">i4").reshape(8, 32).astype(np.int32)

    def window_reads(self, reads=None):
        return sorted(a - mm.SHARED for a, s in (self.reads if reads is None else reads) if mm.SHARED <= a < mm.SHARED + 0x2000)

    def window_writes(self):
        return sorted((a - mm.SHARED, s) for a, s in self.writes if mm.SHARED <= a < mm.SHARED + 0x2000)


def rights():
    return {t: some_tracks(30 + t)[t] for t in range(8)}


def want(tracks, right, mask):
    return np.array([right[t] if mask >> t & 1 else tracks[t] for t in range(8)])


HALVES = [m.rw_half(h) + 4 * k for h in range(16) for k in range(16)]


def halves_of(mask):
    return [m.rw_half(h) + 4 * k for t in range(8) if mask >> t & 1 for h in (2 * t, 2 * t + 1) for k in range(16)]


# ---- the controller's words -------------------------------------------------------------------------------------

def stock_writes(stock3, start, end):  # noqa: F811
    """What stock writes the controller between two places of its own code, in order: (address, size, value)."""
    mc = Machine()
    for base, size in ((0x40000000, 0x800000), (0x80000000, 0x10000), (0x43bd0000, 0x10000), (0xfc000000, 0x100000)):
        mc.map(base, size)
    mc.write(mm.BASE, stock3)
    mc.load_code(start, stock3[mm.off(start):mm.off(end)])
    mc.set_stack(STACK, 0x40000100)
    mc.set_exits([end])
    log = []
    mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: log.append((a, s, v & (1 << 8 * s) - 1)), begin=0xfc044000, end=0xfc045fff)
    mc.uc.ctl_flush_tb()
    mc.uc.emu_start(start, end)
    return log


def test_our_channels_are_written_what_stock_writes_its_own(stock3, main):  # noqa: F811
    """Stock's code is run for its channel 47: the standing words it writes once, and a transfer's. Ours are those,
    in that order and of those sizes, with our channel's number where stock's has 47 and our addresses and turns."""
    standing = stock_writes(stock3, mm.DMA_47_SET, mm.DMA_47_SET + 0x34)
    assert [a for a, s, v in standing] == [TCD + 32 * 47 + k for k in (0x18, 0x0c, 0x04, 0x06, 0x08, 0x16, 0x1e)]
    a_transfer = stock_writes(stock3, mm.TRACKS_IN[1], mm.TRACKS_IN[1] + 0x38)
    assert [(a, s) for a, s, v in a_transfer] == [(TCD + 32 * 47 + 0x10, 4), (TCD + 32 * 47, 4), (TCD + 32 * 47 + 0x14, 2), (TCD + 32 * 47 + 0x1c, 2),
                                                  (S.DMA_FLAG, 1), (SSRT, 1)] or \
        [(a, s) for a, s, v in a_transfer if a != S.DMA_FLAG] == [(TCD + 32 * 47 + 0x10, 4), (TCD + 32 * 47, 4), (TCD + 32 * 47 + 0x14, 2),
                                                                  (TCD + 32 * 47 + 0x1c, 2), (SSRT, 1)]
    turns = a_transfer[2][2]
    assert turns == a_transfer[3][2] == 0x8000 | 47 << 9 | 64 and a_transfer[-1][2] == 47
    assert a_transfer[0][2] == mm.TRACKS and a_transfer[1][2] == mm.SHARED + 0x1b0

    r = Rig(main)
    r.block(some_tracks(), window_of(rights(), 0xff))
    log = [x for x in r.model.log]
    move = lambda ch, rows: [(a - 32 * 47 + 32 * ch if TCD <= a < TCD + 0x800 else a, s, v) for a, s, v in rows]
    k = 0
    for ch in (CH_A, CH_B):                             # the first block: no request line starts a channel, then its standing words
        assert log[k] == (CERQ, 1, ch)
        assert log[k + 1:k + 1 + len(standing)] == move(ch, standing)
        k += 1 + len(standing)
    for ch, src, dst, n in ((CH_A, mm.SHARED + 0x5c0, RIGHT, 36), (CH_B, mm.SHARED + 0xe40, RIGHT + 576, 28)):
        t = TCD + 32 * ch
        assert log[k] == (t + 0x1e, 2, 0)               # "done" is taken away first: the last word as the channel was set
        assert log[k + 1:k + 6] == [(t + 0x10, 4, dst), (t, 4, src), (t + 0x14, 2, 0x8000 | ch << 9 | n), (t + 0x1c, 2, 0x8000 | ch << 9 | n), (SSRT, 1, ch)]
        k += 6
    assert k == len(log)
    # the two stretches are the sixteen halves in order, and a transfer lands on a boundary of sixteen
    assert [m.rw_half(h) for h in range(9)] == [0x5c0 + 64 * h for h in range(9)] and [m.rw_half(h) for h in range(9, 16)] == [0xe40 + 64 * h for h in range(7)]
    assert 36 * 16 == 9 * 64 and 28 * 16 == 7 * 64 and not RIGHT % 16
    # the block after: the standing words are not written again
    r.block(some_tracks(), window_of(rights(), 0xff))
    assert len(r.model.log) == 12 and r.model.started == [CH_A, CH_B]


def test_the_channels_and_the_memory_are_named_by_nothing(stock3):  # noqa: F811
    """Every channel a word of which the main program names is known, and ours are two others of the lowest group,
    which the controller is set to serve after the three above it. Of on-chip memory's first half, what the startup
    copies ends at 0x80007330 and the rest is cleared: ours is in the rest."""
    seen = set()
    for i in range(0, len(stock3) - 3, 2):
        v = int.from_bytes(stock3[i:i + 4], "big")
        if TCD <= v < TCD + 0x800:
            seen.add((v - TCD) // 32)
    assert seen == set(mm.DMA_STOCK) and not seen & set(mm.DMA_RIGHT) and all(ch < 16 for ch in mm.DMA_RIGHT)
    assert mm.SRAM_LOW[0] < SCRATCH and SCRATCH + 1024 <= RIGHT and RIGHT + 1280 <= STATE and STATE + 32 <= mm.SRAM_LOW[1]
    build_main._dma_free(stock3)
    code_hits = sorted(a for a, v in build_main.DMA_MEMORY_SEEN if a < 0x401d0000)
    for a in code_hits:                                 # in code: the long is the end of one instruction and the start of the next, and odd
        v = int.from_bytes(stock3[mm.off(a):mm.off(a) + 4], "big")
        assert v & 1


# ---- from a start: checked ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("mask", [0, 0x01, 0x10, 0x5a, 0xff])
def test_from_a_start_the_cpu_reads_too_and_the_two_are_compared(main, mask):
    r = Rig(main)
    tracks, right = some_tracks(), rights()
    window = window_of(right, mask)
    got = r.block(tracks, window)
    assert np.array_equal(got, want(tracks, right, mask))
    assert r.model.started == [CH_A, CH_B]              # both, whatever plays: an idle unit's window is what is compared
    assert r.window_reads() == sorted([m.RW_HEAD] + HALVES) == r.window_reads(r.begin_reads)       # all of it in the first call's routine
    assert all(s == 4 for a, s in r.reads if mm.SHARED <= a < mm.SHARED + 0x2000) and not r.window_writes()
    assert (r.state(S_GOOD), r.state(S_BAD), r.state(S_MODE), r.state(S_WHY)) == (1, 0, CHECK, 0)
    assert r.mc.read(SCRATCH, 1024) == b"".join(window[m.rw_half(h):m.rw_half(h) + 64] for h in range(16))
    assert r.mc.read(RIGHT + 1024, 256) == b"\xee" * 256                    # the returns after the eight are the mixer's
    assert r.mc.read(SCRATCH - 64, 64) == b"\xee" * 64 and r.mc.read(STATE + 32, 64) == b"\xee" * 64     # and nothing either side of ours is written
    assert r.mc.read(mm.SHARED, 0x1000) == window


def test_after_a_second_of_blocks_that_agree_the_transfers_alone_are_used(main):
    r = Rig(main)
    tracks, right = some_tracks(), rights()
    r.state(S_GOOD, GOOD_BLOCKS - 2)
    for mode in (CHECK, TRUSTED):
        r.block(tracks, window_of(right, 0x21))
        assert r.state(S_MODE) == mode
    assert r.state(S_GOOD) == GOOD_BLOCKS and GOOD_BLOCKS * 32 / 48000 == 1.0
    for mask in (0x21, 0x01, 0x80, 0x10, 0xff, 0):
        got = r.block(tracks, window_of(right, mask))
        assert np.array_equal(got, want(tracks, right, mask)), mask
        assert r.window_reads() == [m.RW_HEAD]          # the CPU reads the one long and no right channel
        assert r.model.started == [CH_A] * bool(mask & 0x1f) + [CH_B] * bool(mask & 0xf0), mask     # track 5's halves are one in each stretch
        assert r.state(S_MODE) == TRUSTED and r.state(S_GOOD) == GOOD_BLOCKS
    assert not any(a for a, s, v in r.model.log)        # no stereo track: the controller is not touched


@pytest.mark.parametrize("model", [dict(spoil=0), dict(spoil=575), dict(nothing=True)])
def test_transfers_that_bring_something_else_are_given_up_and_never_heard(main, model):
    """A byte wrong in what a channel brings, or a channel that says done and brought nothing (the mark the routine
    leaves where it has to write is still there). The sound is the CPU's in every block."""
    r = Rig(main, **model)
    tracks, right = some_tracks(), rights()
    for n in range(1, BAD_BLOCKS + 1):
        got = r.block(tracks, window_of(right, 0xa5))
        assert np.array_equal(got, want(tracks, right, 0xa5))
        assert (r.state(S_BAD), r.state(S_GOOD)) == (n, 0)
        assert r.state(S_MODE) == (DEAD if n == BAD_BLOCKS else CHECK)
    assert r.state(S_WHY) == 3
    got = r.block(tracks, window_of(right, 0x3c))       # from then on: the CPU reads, and no channel is started
    assert np.array_equal(got, want(tracks, right, 0x3c)) and not r.model.started and not r.model.log
    assert r.window_reads() == sorted([m.RW_HEAD] + halves_of(0x3c)) == r.window_reads(r.mid_reads)     # where the images before read them


@pytest.mark.parametrize("trusted", [False, True])
def test_a_wait_that_does_not_end_is_given_up_in_that_block(main, trusted):
    r = Rig(main, never=True)
    tracks, right = some_tracks(), rights()
    if trusted:
        r.state(S_MODE, TRUSTED)
    got = r.block(tracks, window_of(right, 0x81))
    assert np.array_equal(got, want(tracks, right, 0x81))           # that block's right channels are the CPU's all the same
    assert (r.state(S_MODE), r.state(S_WHY), r.state(S_POLLS)) == (DEAD, 2 if trusted else 1, POLL_LIMIT)
    got = r.block(tracks, window_of(right, 0x42))
    assert np.array_equal(got, want(tracks, right, 0x42)) and not r.model.started


def test_a_transfer_that_is_not_done_yet_is_waited_for(main):
    r = Rig(main, late=300)
    tracks, right = some_tracks(), rights()
    r.state(S_MODE, TRUSTED)
    got = r.block(tracks, window_of(right, 0xff))
    assert np.array_equal(got, want(tracks, right, 0xff)) and r.state(S_MODE) == TRUSTED
    assert 300 <= r.state(S_POLLS) <= 600               # the longest wait is kept, in turns of the loop


# ---- given up: as the images before ---------------------------------------------------------------------------------

@pytest.mark.parametrize("mask", [0, 0x01, 0x80, 0x10, 0x5a, 0xff])
def test_given_up_it_is_the_gfade_images_routine(main, gfade, mask):
    """The second set and what is read of the window are the older routine's (engine/rightfill.c), run beside it."""
    tracks, right = some_tracks(), rights()
    window = window_of(right, mask)
    old = S.FillRig(*gfade)
    old.set(tracks, window)
    old.mc.call(old.fill)
    r = Rig(main)
    r.state(S_MODE, DEAD)
    got = r.block(tracks, window)
    assert np.array_equal(got, old.right()) and r.window_reads() == old.window_reads() == r.window_reads(r.mid_reads)
    assert not r.model.log and not r.window_writes()
    # and in the place of the per-block routine those images read them: after stock's wait for the left buffers
    order = [a for a, s in r.mid_reads if a in (S.DMA_FLAG, S.DMA_STATUS) or mm.SHARED <= a < mm.SHARED + 0x2000]
    assert order[0] == S.DMA_FLAG and all(a >= mm.SHARED for a in order[1:])


@pytest.mark.parametrize("word", [0, 0xffffffff, 0x52570000, 0x5257fe00, m.rw_word(0x3c) ^ 0x100])
@pytest.mark.parametrize("mode", [TRUSTED, DEAD])
def test_a_long_that_does_not_agree_with_itself_leaves_every_track_mono(main, word, mode):
    r = Rig(main)
    r.state(S_MODE, mode)
    tracks = some_tracks()
    got = r.block(tracks, window_of(rights(), 0, word))
    assert np.array_equal(got, tracks) and r.window_reads() == [m.RW_HEAD] and not r.model.started


@pytest.mark.parametrize("mode", [CHECK, TRUSTED, DEAD])
def test_with_the_audio_cpu_down_nothing_is_read_or_started_and_the_long_is_cleared(main, mode):
    r = Rig(main)
    r.state(S_MODE, mode)
    tracks = np.zeros((8, 32), dtype=np.int32)          # stock clears the track buffers then
    window = window_of(rights(), 0xff)
    got = r.block(tracks, window, up=0)
    assert np.array_equal(got, tracks) and r.window_reads() == [] and not r.model.log
    assert r.window_writes() == [(m.RW_HEAD, 4), (STOPS_MARK - mm.SHARED, 4)]
    assert r.mc.r32(mm.SHARED + m.RW_HEAD) == 0 and r.mc.r32(STOPS_MARK) == 0
    assert (r.state(S_MODE), r.state(S_GOOD), r.state(S_BAD)) == (mode, 0, 0)
    # the block after: up, and the audio CPU has not written yet
    got = r.block(tracks, r.mc.read(mm.SHARED, 0x1000))
    assert np.array_equal(got, tracks)


def test_a_block_whose_first_call_did_not_come_is_every_track_mono(main):
    """The second routine believes the long only of a block the first ran in."""
    r = Rig(main)
    r.state(S_MODE, TRUSTED)
    r.state(S_MASK, 0xff)
    tracks = some_tracks()
    r.mc.write(mm.TRACKS, tracks.astype(">i4").tobytes())
    r.mc.write(mm.SHARED, window_of(rights(), 0xff))
    r.mc.call(r.syms["right_end"])
    assert np.array_equal(np.frombuffer(r.mc.read(RIGHT, 1024), dtype=">i4").reshape(8, 32), tracks)


# ---- the two places, and the image --------------------------------------------------------------------------------------

def test_the_two_places_go_on_to_what_stock_called(stock3, main):  # noqa: F811
    image, syms = main
    assert image[mm.off(mm.BLOCK_FIRST_CALL):mm.off(mm.BLOCK_FIRST_CALL) + 6] == b"\x4e\xb9" + syms["right_start"].to_bytes(4, "big")
    assert image[mm.off(mm.PRE_MIX_CALL):mm.off(mm.PRE_MIX_CALL) + 6] == b"\x4e\xb9" + syms["right_ready"].to_bytes(4, "big")
    assert stock3[mm.off(mm.BLOCK_FIRST_CALL):mm.off(mm.BLOCK_FIRST_CALL) + 6] == b"\x4e\xb9" + mm.BLOCK_FIRST.to_bytes(4, "big")
    assert stock3[mm.off(mm.PRE_MIX_CALL):mm.off(mm.PRE_MIX_CALL) + 6] == b"\x4e\xb9" + mm.PRE_MIX.to_bytes(4, "big")
    # the first: stock's routine is run after ours and its answer comes back, the registers a routine keeps as they were
    r = Rig(main)
    r.mc.write(mm.SHARED, window_of(rights(), 0x0f))
    r.mc.w32(0xfc03c02c, 1 << 28)                       # what stock's routine waits for
    for k in range(2, 8):
        r.mc.set_reg(k, 0x1000 + k)
        r.mc.set_reg(8 + k, 0x2000 + k)
    r.mc.uc.reg_write(UC_M68K_REG_A7, STACK - 0x40)
    r.mc.uc.emu_start(mm.BLOCK_FIRST_CALL, 0)
    assert r.mc.uc.reg_read(UC_M68K_REG_PC) == mm.BLOCK_FIRST_CALL + 6 and r.mc.reg(0) == 0
    assert [r.mc.reg(k) for k in range(2, 8)] == [0x1000 + k for k in range(2, 8)]
    assert [r.mc.reg(8 + k) for k in range(2, 7)] == [0x2000 + k for k in range(2, 7)] and r.mc.uc.reg_read(UC_M68K_REG_A7) == STACK - 0x40
    assert r.model.started == [CH_A, CH_B] and (0xfc03c02c, 4) in r.reads
    # the second: stock's routine is reached with the stack as stock's call leaves it
    r.mc.uc.reg_write(UC_M68K_REG_A7, STACK - 0x40)
    r.mc.w32(STACK - 0x40, 0x11112222)
    r.mc.w32(STACK - 0x3c, 0x33334444)
    r.mc.uc.emu_start(mm.PRE_MIX_CALL, 0)
    sp = r.mc.uc.reg_read(UC_M68K_REG_A7)
    assert r.mc.uc.reg_read(UC_M68K_REG_PC) == mm.PRE_MIX and sp == STACK - 0x44
    assert (r.mc.r32(sp), r.mc.r32(sp + 4), r.mc.r32(sp + 8)) == (mm.PRE_MIX_CALL + 6, 0x11112222, 0x33334444)
    assert [r.mc.reg(k) for k in range(2, 8)] == [0x1000 + k for k in range(2, 8)] and [r.mc.reg(8 + k) for k in range(2, 7)] == [0x2000 + k for k in range(2, 7)]
    assert r.state(S_GOOD) == 1


@pytest.mark.parametrize("up", [0, 1, 0x100])
@pytest.mark.parametrize("mode", [CHECK, TRUSTED, DEAD])
def test_the_place_stock_waits_goes_on_as_stock_does(stock3, main, up, mode):  # noqa: F811
    """Stock: wait, test "the audio CPU is up", send the knobs or skip that. Ours: the routine, which waits as stock
    does and answers what stock tested, then the same branch. Both from that place to where the two ways part."""
    ends = []
    for built in ((stock3, {}), main):
        r = Rig(built)
        r.state(S_MODE, mode)
        r.mc.write(mm.SHARED, window_of(rights(), 0x33))
        r.mc.w32(mm.AUDIO_UP, up)
        r.mc.write(S.DMA_FLAG, b"\1")
        r.mc.write(S.DMA_STATUS, b"\x00\x80")           # channel 47 is done, so stock's wait ends
        for k in range(2, 8):
            r.mc.set_reg(k, 0x1000 + k)
            r.mc.set_reg(8 + k, 0x2000 + k)
        r.mc.uc.reg_write(UC_M68K_REG_A7, STACK - 0x40)
        r.mc.uc.emu_start(mm.RIGHT_HOOK, 0)
        ends.append((r.mc.uc.reg_read(UC_M68K_REG_PC), [r.mc.reg(k) for k in range(2, 8)], [r.mc.reg(8 + k) for k in range(2, 8)],
                     r.mc.read(S.DMA_FLAG, 1)))
    assert ends[0] == ends[1] and ends[0][0] == (S.SEND if up else S.SKIP) and ends[0][3] == b"\0"
    assert ends[1][1] == [0x1000 + k for k in range(2, 8)] and ends[1][2][:5] == [0x2000 + k for k in range(2, 7)] and ends[1][2][5] == STACK - 0x40


def test_what_it_costs_the_main_cpu(main, gfade):
    """Instructions a block, the transfers believed: against the older routine's. What is gone is not instructions
    but the slow reads: 512 of the window's words a block with eight stereo tracks, now 2."""
    tracks, right = some_tracks(), rights()
    new, old, slow = [], [], []
    for mask in (0, 1, 0xff):
        r = Rig(main)
        r.state(S_MODE, TRUSTED)
        r.block(tracks, window_of(right, 0xff))         # the block the standing words are written in is not the one counted
        was = r.mc.insns
        r.block(tracks, window_of(right, mask))
        new.append(r.mc.insns - was)
        slow.append(2 * len(r.window_reads()))
        o = S.FillRig(*gfade)
        o.set(tracks, window_of(right, mask))
        was = o.mc.insns
        o.mc.call(o.fill)
        old.append(o.mc.insns - was)
    print("instructions a block, no stereo track, one, eight: new %s, old %s" % (new, old))
    assert slow == [2, 2, 2]
    assert new[0] < old[0] + 60 and new[2] < new[0] and new[2] < 250 < old[2]


def page(built):
    r = X.Page(built, track=2)
    r.mc.map(0x80007000, 0x1000)                        # on-chip memory, where the routine's eight longs are: 0 from a start
    r.mc.write(MO.PEAK_AT, b"P047")
    return r


def test_the_page_says_how_the_right_channels_come(main, gfade):
    """The letter before the audio CPU's load: C while the transfers are checked, H when they are used, X given up."""
    for mode, letter in ((CHECK, "C"), (TRUSTED, "H"), (DEAD, "X")):
        r = page(main)
        r.mc.w32(STATE + 4 * S_MODE, mode)
        shown = [t[2] for t in r.show()]
        assert letter + "047" in shown and "P047" not in shown, shown
    old = X.Page(gfade, track=2)
    old.mc.write(MO.PEAK_AT, b"P047")
    assert [t for t in page(main).show() if t[2] != "C047"] == [t for t in old.show() if t[2] != "P047"]


def test_the_image(official_path, official, stock3, main, gfade):  # noqa: F811
    """The gfade image's but for: our two runs, the two calls, the seven operands of the mixer that name the second
    set, the routine called where stock waits for the first set, the older routine's run (stock's again), and the
    page's code."""
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=3)[2]
    was = build.build(official_path, log=quiet, xfade=2)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    for a in mm.RIGHT_PASSES:
        assert mm.u32(old, a + 2) == mm.RIGHT_SET and mm.u32(new, a + 2) == RIGHT
    for a, ret in mm.RIGHT_RETURNS:
        assert mm.u32(old, a + 2) == mm.RIGHT_SET + ret - mm.TRACKS and mm.u32(new, a + 2) == RIGHT + ret - mm.TRACKS
    for a in mm.LEFT_PASSES + mm.TRACK_OUTS:
        assert mm.u32(new, a + 2) == mm.TRACKS
    lo, hi = mm.off(mm.RIGHT_HOOK), mm.off(mm.RIGHT_HOOK) + 10
    assert new[lo:hi] == b"\x4e\xb9" + main[1]["right_mid"].to_bytes(4, "big") + bytes.fromhex("4a80" "4e71") != old[lo:hi]
    assert old[lo:lo + 2] == b"\x4e\xb9" and old[lo + 6:hi] == new[lo + 6:hi]
    lo, hi = mm.off(mm.CAVE_RIGHT[0]), mm.off(mm.CAVE_RIGHT[1])
    assert new[lo:hi] == stock3[lo:hi] != old[lo:hi]
    spans = [mm.CAVE_DMA, mm.CAVE_DMA2, mm.CAVE_RIGHT, (mm.RIGHT_HOOK, mm.RIGHT_HOOK + 10), (mm.BLOCK_FIRST_CALL + 2, mm.BLOCK_FIRST_CALL + 6),
             (mm.PRE_MIX_CALL + 2, mm.PRE_MIX_CALL + 6), mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6]
    spans += [(a + 2, a + 6) for a in mm.RIGHT_PASSES] + [(a + 2, a + 6) for a, _ in mm.RIGHT_RETURNS]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 8, [hex(mm.BASE + k) for k in stray]      # an operand that names a routine of the page that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
