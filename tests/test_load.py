"""The "load" image: LOAD PROJECT puts the drive's samples back in the slots recorded over.

A take that is not on the +Drive lives in the audio CPU's memory, and stock loads samples at
boot only. Here the main CPU, after the stock project load, asks which slots hold such a take
and sends each the samples the drive has for it, a sector a request, through the box that
keeping takes uses the other way.

Audio CPU side (engine/sampler.c built with LOAD) runs inside the real voice loop hook. Main CPU
side (the load half of engine/keeptakes.c) runs with the project routines and the drive replaced
by stubs, against a drive that is a Python dictionary; the store's own read runs as it is. Two
tests join the sides by carrying the window's bytes across.

Nothing here says what the unit does while the load job waits, how long the drive takes, or
that the audio CPU goes on answering while a project is loaded: see docs/FINDINGS.md.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from emu.engine import BLOCK
from tools import audiomap as m
from tools import build_engine, build_main, deadcode
from tools import mainmap as mm
from test_keep import STACK, STORE, Rig, header, sector_of
from test_pagerec import MODE, MONO, REC, STEREO, engine, hold, slot_entry, taken

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

BOX = m.KEEP_BOX
PUT = m.KEEP_PUT
SLOTS = 64
SECTORS = build_main.BIG_SLOT_SECTORS


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def audio(stock):
    return build_engine.patched_image(stock, load=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, load=True)


def sample(frames, seed):
    """A sample's bytes as the drive and the pool hold them."""
    return np.random.default_rng(seed).integers(-32768, 32768, frames).astype(">i2").tobytes()


def pieces(data):
    """(offset, bytes) as the main CPU cuts a slot: what is left of the first sector, then whole sectors."""
    out, off, n = [], 0, 512 - 64
    while off < len(data):
        out.append((off, data[off:off + n]))
        off, n = off + n, 512
    return out


# ---- audio CPU ----------------------------------------------------------------------------------

def ask(e, slot, off, data=None, blocks=1):
    """Write a request as the main CPU does, run blocks, return (answered, frames, data)."""
    req = (e.mc.r32(BOX + m.KEEP_ACK) + 1) & 0xFFFF
    if data is not None:
        e.mc.write(BOX + m.KEEP_DATA, data)
    e.mc.write(BOX + m.KEEP_SLOT, slot.to_bytes(2, "big") + off.to_bytes(4, "big"))
    e.mc.write(BOX + m.KEEP_REQ, req.to_bytes(2, "big"))
    for _ in range(blocks):
        e.block()
    box = bytes(e.mc.read(BOX, m.KEEP_SIZE))
    return box[m.KEEP_ACK:m.KEEP_ACK + 4] == req.to_bytes(4, "big"), int.from_bytes(box[12:16], "big"), box[16:]


def send(e, slot, data):
    """A slot's samples, then the word that makes them the slot."""
    for off, piece in pieces(data):
        assert ask(e, slot | PUT, off, piece)[0]
    assert ask(e, slot | PUT, m.KEEP_DONE, (len(data) // 2).to_bytes(4, "big"))[0]


def buffer_of(k):
    return m.REC_BASE + m.REC_STRIDE * k


def heard(e, track, blocks=8):
    e.set_slot(track, MODE, STEREO)
    return np.array([e.block(trig=1 << track if b == 0 else 0) for b in range(blocks)])


def test_the_request_bit_is_no_slot_and_the_buffers_end_under_the_stack():
    assert PUT > SLOTS and PUT < 0x10000
    assert buffer_of(SLOTS) <= m.STACK_TOP - 0x100000       # the last slot's buffer ends well under the stack
    assert m.REC_STRIDE == 2 * m.REC_MAX and m.REC_STRIDE % 512 == 0


def test_pieces_land_in_the_slots_buffer_and_the_last_word_makes_them_the_slot(audio):
    e = engine(audio)
    x = sample(1500, 1)
    before = slot_entry(e, 10)
    for off, piece in pieces(x):
        ok, _, _ = ask(e, 10 | PUT, off, piece)
        assert ok and slot_entry(e, 10) == before           # not the slot yet
    assert bytes(e.mc.read(buffer_of(10), len(x))) == x
    assert ask(e, 10 | PUT, m.KEEP_DONE, (1500).to_bytes(4, "big"))[0]
    assert slot_entry(e, 10) == (1500, buffer_of(10))
    assert e.mc.r32(m.KEPT + 4 * 10) == 1500 ^ m.KEEP_MARK
    assert ask(e, 10, 0)[1] == 0                            # the drive has it: a save has nothing to write
    assert all(slot_entry(e, k)[0] == 0 for k in range(SLOTS) if k != 10)


def test_a_slot_loaded_this_way_sounds_as_if_loaded_at_boot(audio):
    left, right = sample(700, 2), sample(700, 3)
    pool = {10: np.frombuffer(left, dtype=">i2").astype(np.int16), 11: np.frombuffer(right, dtype=">i2").astype(np.int16)}
    want = heard(engine(audio, pool=pool), 5)
    e = engine(audio)
    send(e, 10, left)
    send(e, 11, right)
    got = heard(e, 5)
    assert np.array_equal(got, want) and np.any(got)


def test_it_takes_the_place_of_a_sample_from_the_pool(audio):
    old = np.arange(900, dtype=np.int16)
    e = engine(audio, pool={10: old, 11: old})
    x = sample(300, 4)
    assert ask(e, 10 | PUT, 0, x[:448])[0]
    assert slot_entry(e, 10)[0] == 900                      # the pool's sample plays on until the last word
    send(e, 10, x)
    assert slot_entry(e, 10) == (300, buffer_of(10)) and slot_entry(e, 11)[0] == 900


def test_a_take_is_silent_while_its_buffer_is_written_and_then_gone(audio):
    e = engine(audio)
    e.set_slot(5, MODE, REC)
    hold(e, 5, 12)
    e.set_slot(5, MODE, MONO)
    old_left, old_right = taken(e, 10).tobytes(), taken(e, 11).tobytes()
    assert ask(e, 10, 0)[1] == len(old_left) // 2           # a take the drive does not have
    x = sample(200, 5)
    assert ask(e, 10 | PUT, 0, x[:448])[0]
    assert slot_entry(e, 10) == (0, buffer_of(10))          # no frames: not heard half old, half new
    assert taken(e, 11).tobytes() == old_right              # its right half is another slot
    send(e, 10, x)
    assert slot_entry(e, 10) == (200, buffer_of(10))
    assert bytes(e.mc.read(buffer_of(10), 400)) == x
    assert ask(e, 10, 0)[1] == 0 and ask(e, 11, 0)[1] == len(old_right) // 2


def test_a_slot_the_drive_has_nothing_for_is_left_empty(audio):
    e = engine(audio)
    e.set_slot(5, MODE, REC)
    hold(e, 5, 6)
    e.set_slot(5, MODE, MONO)
    assert slot_entry(e, 10)[0]
    assert ask(e, 10 | PUT, m.KEEP_DONE, bytes(4))[0]
    assert slot_entry(e, 10) == (0, buffer_of(10)) and ask(e, 10, 0)[1] == 0
    e.set_slot(5, MODE, STEREO)
    assert not np.any([e.block(trig=1 << 5 if b == 0 else 0) for b in range(4)])


def test_a_length_is_held_to_a_buffer(audio):
    e = engine(audio)
    for frames in (m.REC_MAX, m.REC_MAX + 1, 0x7FFFFFFF, 0xFFFFFFFF):
        assert ask(e, 20 | PUT, m.KEEP_DONE, frames.to_bytes(4, "big"))[0]
        assert slot_entry(e, 20) == (m.REC_MAX, buffer_of(20))
        assert e.mc.r32(m.KEPT + 4 * 20) == m.REC_MAX ^ m.KEEP_MARK


def test_the_last_piece_stops_at_the_buffers_end(audio):
    e = engine(audio)
    e.mc.write(buffer_of(10) + m.REC_STRIDE - 512, bytes(1024))
    piece = bytes(range(256)) * 2
    assert ask(e, 10 | PUT, m.REC_STRIDE - 256, piece)[0]   # not a place the main CPU cuts at: 256 bytes of room
    assert bytes(e.mc.read(buffer_of(10) + m.REC_STRIDE - 512, 1024)) == bytes(256) + piece[:256] + bytes(512)
    assert ask(e, 63 | PUT, m.REC_STRIDE - 512, piece)[0]   # the last buffer's last sector
    assert bytes(e.mc.read(buffer_of(64) - 512, 512)) == piece


def test_requests_that_name_no_place_are_answered_and_write_nothing(audio):
    e = engine(audio)
    table = bytes(e.mc.read(m.SLOT_LEN, 8 * SLOTS))
    marks = bytes(e.mc.read(m.KEPT, 4 * SLOTS))
    wrote = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: wrote.append(addr), begin=m.KEPT, end=m.STACK_TOP - 0x10000)
    e.mc.uc.ctl_flush_tb()
    piece = bytes([0x5a]) * 512
    for slot, off in ((64, 0), (65, 448), (0x7FFF, 0), (64, m.KEEP_DONE), (0x7FFF, m.KEEP_DONE),     # no such slot
                      (10, m.REC_STRIDE), (10, m.REC_STRIDE + 512), (10, 0x7FFFFE00), (10, 0xFFFFFE00),   # past the buffer
                      (10, 1), (10, 2), (10, 449), (10, 0xFFFFFFFE)):                                # not on a long
        assert ask(e, slot | PUT, off, piece)[0], (slot, off)
    assert not wrote
    assert bytes(e.mc.read(m.SLOT_LEN, 8 * SLOTS)) == table and bytes(e.mc.read(m.KEPT, 4 * SLOTS)) == marks


def test_the_audio_cpu_touches_the_window_in_longs_and_writes_only_its_answer(audio):
    e = engine(audio)
    x = sample(600, 6)
    seen = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: seen.append(("w", addr, size)), begin=0, end=0x1fff)
    e.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, u: seen.append(("r", addr, size)), begin=0, end=0x1fff)
    e.mc.uc.ctl_flush_tb()
    send(e, 10, x)
    writes = [(addr, size) for kind, addr, size in seen if kind == "w"]
    assert writes and all(w == (BOX + m.KEEP_ACK, 4) for w in writes)
    assert all(size in (2, 4) and addr % size == 0 for kind, addr, size in seen if kind == "r")


def test_keeping_a_take_is_answered_as_in_the_page_image(stock, audio):
    boxes = []
    for built in (build_engine.patched_image(stock, page=True), audio):
        e = engine(built)
        e.set_slot(5, MODE, REC)
        hold(e, 5, 9, seed=7)
        e.set_slot(5, MODE, MONO)
        n = 2 * slot_entry(e, 10)[0]
        boxes.append([ask(e, slot, off) for slot, off in ((10, 0), (10, 448), (11, n - 512), (12, 0), (64, 0), (10, m.KEEP_DONE), (10, 0))])
    assert boxes[0] == boxes[1] and boxes[0][0][1] and boxes[0][-1][1] == 0


def test_with_nothing_asked_it_runs_like_the_page_image(stock, audio):
    outs = []
    for built in (build_engine.patched_image(stock, page=True), audio):
        e = engine(built)
        e.set_slot(5, MODE, REC)
        hold(e, 5, 5, seed=8)
        e.set_slot(5, MODE, MONO)
        outs.append((taken(e, 10).tobytes(), taken(e, 11).tobytes(), heard(e, 5)))
    assert outs[0][0] == outs[1][0] and outs[0][1] == outs[1][1]
    assert np.array_equal(outs[0][2], outs[1][2]) and np.any(outs[1][2])


def test_cost_on_the_audio_cpu(stock, audio):
    def count(built, slot):
        e = engine(built)
        e.block()
        if slot is not None:
            e.mc.write(BOX + m.KEEP_SLOT, slot.to_bytes(2, "big") + bytes(4))
            e.mc.write(BOX + m.KEEP_REQ, b"\0\1")
        n0 = e.mc.insns
        e.block()
        return e.mc.insns - n0
    page = build_engine.patched_image(stock, page=True)
    idle = count(audio, None) - count(page, None)
    piece = count(audio, 10 | PUT) - count(page, None)
    assert idle == 0                                        # no request: not one instruction more than the page image
    assert piece < 6000                                     # one block of a load: 512 bytes copied
    assert piece == COST


COST = 1062                 # a block with a piece in it, over one without. Budget: 10,506 a voice


# ---- main CPU -----------------------------------------------------------------------------------

class LoadRig(Rig):
    """The patched main program with the project routines and the drive replaced by stubs. The store's
    own read runs: its lock and the drive under it are the stubs."""

    def __init__(self, built):
        self.reads, self.loads, self.loaded, self.read_fails = [], [], 1, None
        super().__init__(built)
        self.stub(mm.PROJECT_LOAD, lambda a, b, c: self.project_load(a, b, c))

    def stub(self, addr, fn):
        if addr != mm.STORE_READ:
            super().stub(addr, fn)

    def wrote(self, uc, access, address, size, value, user):
        if not (STACK[0] <= address < STACK[1] or mm.KEEP_BOX <= address < mm.KEEP_BOX + m.KEEP_ACK
                or mm.KEEP_BOX + m.KEEP_DATA <= address < mm.KEEP_BOX + m.KEEP_SIZE     # the samples it sends
                or STORE <= address < STORE + 0x20000 or 0x4d800000 <= address):
            self.stray.append(address)

    def read(self, sector, n, dest):
        if self.read_fails is not None and len(self.reads) >= self.read_fails:
            return 5
        self.reads.append((sector, n))
        return super().read(sector, n, dest)

    def project_load(self, a, b, c):
        self.loads.append((a, b, c, len(self.reads)))
        return self.loaded

    def load(self, args=(0x1111, 0x2222, 0x3333)):
        return self.mc.call(self.syms["load_keep"], *args)

    def put(self, slot, data, name=None):
        """A sample on the drive, as Transfer or a kept take leaves it."""
        raw = (name or header(len(data) // 2, slot)) + data
        raw = raw.ljust((len(raw) + 511) // 512 * 512, b"\0")
        for j in range(len(raw) // 512):
            self.drive[sector_of(slot) + j] = raw[512 * j:512 * j + 512]


class Audio:
    """The audio CPU's side as the tests above show it: which slots hold a take the drive does not have,
    and what it is sent."""

    def __init__(self, rig, takes):
        self.rig, self.takes = rig, dict(takes)             # slot: frames
        self.asked, self.sent, self.done = [], {}, {}

    def __call__(self):
        mc = self.rig.mc
        box = bytes(mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
        slot, off = int.from_bytes(box[2:4], "big"), int.from_bytes(box[4:8], "big")
        self.asked.append((slot, off))
        if slot & PUT:
            k = slot & ~PUT
            if off == m.KEEP_DONE:
                self.done[k] = int.from_bytes(box[16:20], "big")
                self.takes.pop(k, None)
            else:
                buf = self.sent.setdefault(k, bytearray())
                buf[off:off + 512] = box[16:]               # as the audio CPU copies it: 512 bytes at off
        else:
            mc.write(mm.KEEP_BOX + m.KEEP_FRAMES, self.takes.get(slot, 0).to_bytes(4, "big") + bytes(512))
        mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(2) + box[:2])

    def got(self, k):
        return bytes(self.sent.get(k, b"")[:2 * self.done[k]])


@pytest.fixture()
def rig(main):
    return LoadRig(main)


def test_the_load_is_one_call_and_it_goes_to_ours(stock3, official, main):
    image, syms = main
    call = mm.PROJECT_LOAD_CALL
    assert stock3.count(b"\x4e\xb9" + mm.PROJECT_LOAD.to_bytes(4, "big")) == 1
    assert stock3.count(mm.PROJECT_LOAD.to_bytes(4, "big")) == 1
    assert image[mm.off(call):mm.off(call) + 6] == b"\x4e\xb9" + syms["load_keep"].to_bytes(4, "big")
    lo, hi = mm.CAVE_KEEP                                   # the code sits with the save's, in the run the keep image proved
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert mm.CAVE_KEEP in deadcode.usable(runs)
    assert all(lo <= syms[s] < hi for s in ("ask", "take", "keep_takes", "save_keep", "load_slots", "load_keep"))
    for save in mm.PROJECT_SAVE_CALLS:
        assert image[mm.off(save):mm.off(save) + 6] == b"\x4e\xb9" + syms["save_keep"].to_bytes(4, "big")


def test_the_stock_load_runs_first_and_its_answer_is_passed_on(rig):
    rig.serve(Audio(rig, {}))
    for answer in (1, 0x12345601, 0xFFFFFFFF):
        rig.loaded = answer
        assert rig.load((7, 8, 9)) == answer
        assert rig.loads[-1] == (7, 8, 9, 0)                # before anything is read here
    assert not rig.writes and not rig.reads and not rig.stray


def test_a_failed_project_load_changes_nothing(rig):
    audio = Audio(rig, {10: 960})
    rig.serve(audio)
    box = bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
    for answer in (0, 0x100, 0xABCDEF00):                   # the low byte is the answer
        rig.loaded = answer
        assert rig.load() == answer
    assert not audio.asked and not rig.reads and bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE)) == box


@pytest.mark.parametrize("frames", [1, 223, 224, 225, 480, 5000])
def test_a_slot_with_a_take_gets_the_drives_samples(rig, frames):
    """224 frames is exactly what is left of the first sector."""
    a, b = sample(frames, 1), sample(frames + 7, 2)
    rig.put(10, a)
    rig.put(11, b)
    rig.put(12, sample(100, 3))                             # no take there: it is left alone
    audio = Audio(rig, {10: 960, 11: 960})
    rig.serve(audio)
    assert rig.load() == 1
    assert audio.done == {10: frames, 11: frames + 7}
    assert audio.got(10) == a and audio.got(11) == b
    # every slot is asked once whether it holds a take, and only those two are read
    assert [s for s, off in audio.asked if not s & PUT] == list(range(SLOTS))
    want = [(sector_of(s) + j, 512) for s, x in ((10, a), (11, b)) for j in range((64 + len(x) + 511) // 512)]
    assert rig.reads == want
    for s, x in ((10, a), (11, b)):                         # the pieces in order, and the last word last
        mine = [off for k, off in audio.asked if k == s | PUT]
        assert mine == [off for off, _ in pieces(x)] + [m.KEEP_DONE]
    assert not rig.writes and not rig.stray                 # the drive is only read
    assert {size for _, size in rig.window} == {2, 4}       # words and longs, never a byte
    assert rig.load() == 1 and len(rig.reads) == len(want)  # nothing holds a take any more: nothing more is read


def test_a_slot_with_nothing_on_the_drive_is_loaded_as_empty(rig):
    rig.put(11, sample(50, 1), name=b"JUNK" + bytes(60))    # not a sample's first sector
    rig.put(12, b"")                                        # a header that says no frames
    audio = Audio(rig, {10: 960, 11: 960, 12: 960})
    rig.serve(audio)
    assert rig.load() == 1
    assert audio.done == {10: 0, 11: 0, 12: 0} and not audio.sent
    assert rig.reads == [(sector_of(k), 512) for k in (10, 11, 12)] and not rig.stray


def test_a_full_slot_is_read_to_its_end_and_no_further(rig):
    full = sample(m.REC_MAX, 4)
    rig.put(20, full)
    rig.put(63, full, name=header(0x7FFFFFFF, 63))          # a length no slot holds
    audio = Audio(rig, {20: 960, 63: 960})
    rig.serve(audio)
    assert rig.load() == 1
    assert audio.done == {20: m.REC_MAX, 63: m.REC_MAX} and audio.got(20) == full and audio.got(63) == full
    per = (64 + 2 * m.REC_MAX + 511) // 512
    assert per == 1921 <= SECTORS and len(rig.reads) == 2 * per
    assert all(sector_of(s) <= r < sector_of(s) + SECTORS for s in (20, 63) for r, _ in rig.reads[(s == 63) * per:][:per])
    last = max(off for s, off in audio.asked if s & PUT and off != m.KEEP_DONE)
    assert last == m.REC_STRIDE - 64                        # the last piece: 64 bytes of it are the slot's, and the audio CPU stops there
    assert not rig.stray


def test_nothing_is_done_until_the_audio_cpu_is_up(rig):
    audio = Audio(rig, {10: 960})
    rig.serve(audio)
    rig.mc.w32(mm.AUDIO_UP, 0)
    assert rig.load() == 1 and not audio.asked and not rig.reads and not rig.stray


def test_an_audio_cpu_that_does_not_answer_ends_it(rig):
    rig.put(10, sample(900, 1))
    assert rig.load() == 1                                  # nobody serves: the first question runs out of patience
    assert not rig.reads and not rig.stray


@pytest.mark.parametrize("fails", [0, 1, 3])
def test_a_drive_error_stops_it_without_the_last_word(rig, fails):
    rig.put(10, sample(2000, 1))
    audio = Audio(rig, {10: 960, 11: 960})
    rig.serve(audio)
    rig.read_fails = fails
    assert rig.load() == 1
    assert not audio.done and len(rig.reads) == fails and not rig.stray
    assert [off for s, off in audio.asked if s == 10 | PUT] == [off for off, _ in pieces(sample(2000, 1))][:fails]
    assert (11, 0) not in audio.asked                       # and the slots after it wait for the next load


def test_saving_still_keeps_takes(rig):
    from test_keep import Takes, noise
    takes = Takes(rig, {10: noise(960, 1), 11: noise(960, 2)})
    rig.serve(takes)
    assert rig.keep() == 1 and takes.kept == {10, 11}
    assert rig.slot(10) == (header(960, 10), noise(960, 1)) and not rig.stray


# ---- both sides ---------------------------------------------------------------------------------

def joined(e, rig):
    """Every request of the main CPU answered by one block of the audio CPU, the box carried across."""
    blocks = []

    def audio_block():
        box = bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
        e.mc.write(BOX, box[:m.KEEP_ACK])                   # the main CPU's fields
        e.mc.write(BOX + m.KEEP_DATA, box[m.KEEP_DATA:])    # and what it put in the shared one
        e.block()
        blocks.append(1)
        rig.mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(e.mc.read(BOX + m.KEEP_ACK, m.KEEP_SIZE - m.KEEP_ACK)))
    e.block()                                               # the audio CPU's first block settles the box
    rig.mc.write(mm.KEEP_BOX, bytes(e.mc.read(BOX, m.KEEP_SIZE)))
    rig.serve(audio_block)
    return blocks


def take(e, track, n, seed):
    e.set_slot(track, MODE, REC)
    hold(e, track, n, seed=seed)
    e.set_slot(track, MODE, MONO)
    return taken(e, 2 * track).tobytes(), taken(e, 2 * track + 1).tobytes()


def test_record_save_record_again_load_and_the_saved_take_is_back(audio, rig):
    """What the maintainer did on the unit on 2026-10-09, where the second take stayed."""
    e = engine(audio)
    first = take(e, 5, 20, seed=1)                          # stereo sample 6: slots 10 and 11
    blocks = joined(e, rig)
    assert rig.keep() == 1                                  # SAVE PROJECT: the take goes to the drive
    assert rig.slot(10)[1] == first[0] and rig.slot(11)[1] == first[1]
    second = take(e, 5, 31, seed=2)                         # the same destination again
    assert second[0] != first[0] and len(second[0]) > len(first[0])
    assert bytes(e.mc.read(buffer_of(10), len(second[0]))) == second[0]
    writes = len(rig.writes)
    del blocks[:]
    assert rig.load() == 1                                  # LOAD PROJECT
    for k, x in ((10, first[0]), (11, first[1])):
        assert slot_entry(e, k) == (len(x) // 2, buffer_of(k))
        assert bytes(e.mc.read(buffer_of(k), len(x))) == x
        assert e.mc.r32(m.KEPT + 4 * k) == (len(x) // 2) ^ m.KEEP_MARK
    sectors = sum((64 + len(x) + 511) // 512 for x in first)
    assert len(blocks) == SLOTS + sectors + 2               # a question a slot, a sector a block, a last word for each of the two
    assert len(rig.writes) == writes and not rig.stray      # the drive was only read
    # and it sounds like the first take
    fresh = engine(audio)
    assert take(fresh, 5, 20, seed=1) == first
    assert np.array_equal(heard(e, 5), heard(fresh, 5))
    # a save now has nothing to write, a load nothing to read
    reads = len(rig.reads)
    assert rig.keep() == 1 and len(rig.writes) == writes
    assert rig.load() == 1 and len(rig.reads) == reads


def test_a_sample_from_the_drive_recorded_over_is_back_after_a_load(audio, rig):
    left, right = sample(4000, 5), sample(4000, 6)
    rig.put(10, left, name=b"SAMP" + bytes(8) + b"KICK L".ljust(16, b"\0") + bytes(36))
    rig.put(11, right, name=b"SAMP" + bytes(8) + b"KICK R".ljust(16, b"\0") + bytes(36))
    for k in (10, 11):                                      # the header's length, as Transfer writes it
        first = rig.drive[sector_of(k)]
        rig.drive[sector_of(k)] = first[:8] + (4000).to_bytes(4, "big") + first[12:]
    pool = {10: np.frombuffer(left, dtype=">i2").astype(np.int16), 11: np.frombuffer(right, dtype=">i2").astype(np.int16)}
    e = engine(audio, pool=pool)                            # as the boot loaded it
    before = heard(e, 5)
    e.set_slot(5, MODE, MONO)
    over = take(e, 5, 9, seed=3)
    assert slot_entry(e, 10) == (len(over[0]) // 2, buffer_of(10))
    other = take(e, 0, 4, seed=4)                           # a take on slots 0 and 1, where the drive has nothing
    joined(e, rig)
    assert rig.load() == 1
    assert bytes(e.mc.read(buffer_of(10), 8000)) == left and bytes(e.mc.read(buffer_of(11), 8000)) == right
    assert slot_entry(e, 10) == (4000, buffer_of(10)) and slot_entry(e, 11) == (4000, buffer_of(11))
    assert np.array_equal(heard(e, 5), before) and np.any(before)
    assert slot_entry(e, 0) == (0, buffer_of(0)) and slot_entry(e, 1) == (0, buffer_of(1))    # that take is gone, as after a restart
    assert other[0] and not rig.writes and not rig.stray


# ---- the image ----------------------------------------------------------------------------------

def test_load_image_builds_and_the_page_image_does_not_contain_it(official_path, official, stock3, audio, main):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, load=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] and built.section(7) == audio[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    page = build.build(official_path, log=quiet, page=True)[2]
    call = mm.PROJECT_LOAD_CALL
    assert page.section(3)[mm.off(call):mm.off(call) + 6] == b"\x4e\xb9" + mm.PROJECT_LOAD.to_bytes(4, "big")
    # apart from the save and load code and the one call, section 3 is the page image's
    a, b = bytearray(page.section(3)), bytearray(built.section(3))
    for start, end in (mm.CAVE_KEEP, (call + 2, call + 6)) + tuple((c + 2, c + 6) for c in mm.PROJECT_SAVE_CALLS):
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b
    # the audio CPU: the page image's, with more in the runs that hold our code and the three pointers to it
    diff = [k for k in range(len(audio[0])) if page.section(7)[k] != built.section(7)[k]]
    ours = list(m.CAVES.values()) + list(m.REC_CAVES.values())
    ours += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in ours) for k in diff)
    assert "load_step" in syms and m.CAVES["x"][0] <= syms["load_step"] < m.CAVES["x"][1]
