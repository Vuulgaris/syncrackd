"""The save image: SAVE on the sampling page writes the takes to the +Drive, and not the project.
Builds and emulation only.

The drive may be written from a job. Stock has a runner of jobs, and a job is started with a name and
two function objects: what to do and what to call after. Ours (engine/keeptakes.c, save_start) does
what the second half of a project save does and nothing of the first. The runner itself is not run
here: it needs the unit's heap and its locks. What is run as it is: stock's two routines that copy a
function object and the one that ends it, on ours; and the store's write under the job, as in
tests/test_banks.py.

What this cannot show: that the runner takes a job from the task a knob's turn arrives in, and that
it runs ours.
"""
import shutil

import numpy as np
import pytest

from emu.machine import Machine
from tools import audiomap as m
from tools import build, build_main
from tools import mainmap as mm
from test_banks import RUN, BankRig
from test_keep import Takes, header, noise, sector_of
from test_meter import MeterRig, bar_picture, src
from test_page import PAGE
from test_reclock import ON, REC_KNOB, SRC_KNOB
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
IDLE, BUSY, DONE, FAIL = 0, 1, 2, 3
WORDS = ["SAVE", "BUSY", "DONE", "FAIL"]
SAVE_KNOB = 5                       # the fifth knob, as a turn names it
RUNNER = 0x41234560
JOB, COPY, SCRATCH = 0x40700000, 0x40700040, 0x40700080     # a function object as the runner would hold it, a copy, a long


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, save=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, meter=True)


# ---- the job -------------------------------------------------------------------------------------

class SaveRig(BankRig):
    """tests/test_banks.py's rig on the save image, with stock's runner of jobs played by the test: it
    keeps what it is handed, and run() does what its worker would."""

    def __init__(self, built, bank=0):
        self.jobs = []
        super().__init__(built, bank=bank)
        self.stub(mm.JOB_RUNNER, lambda: RUNNER)
        self.stub(mm.JOB_START, lambda runner, name, body, done: self.started(runner, name, body, done))
        self.mc.uc.ctl_flush_tb()

    def wrote(self, uc, access, address, size, value, user):
        if not mm.SAVE_STATE <= address < mm.SAVE_STATE + 4:
            super().wrote(uc, access, address, size, value, user)

    @property
    def state(self):
        return self.mc.r32(mm.SAVE_STATE)

    def started(self, runner, name, body, done):
        raw = bytes(self.mc.read(name, 16))
        self.jobs.append(dict(runner=runner, name=raw[:raw.index(0)].decode(), body=bytes(self.mc.read(body, 16)),
                              done=bytes(self.mc.read(done, 16)), state=self.state))
        return 0

    def start(self):
        self.mc.call(self.syms["save_start"])

    def run(self):
        """The job as the runner's worker calls it: the routine at + 12 of its copy of the object, with the copy."""
        job = self.jobs[-1]
        self.mc.write(JOB, job["body"])
        failed = self.mc.call(int.from_bytes(job["body"][12:], "big"), JOB) & 0xFF
        self.mc.write(JOB, job["done"])
        self.mc.call(int.from_bytes(job["done"][12:], "big"), JOB, failed)
        return failed


def word(v):
    return v.to_bytes(4, "big")


def test_a_save_hands_stocks_runner_a_job_of_ours(main):
    rig = SaveRig(main)
    assert rig.state == IDLE
    rig.start()
    syms = rig.syms
    assert rig.jobs == [dict(runner=RUNNER, name="Take Save", state=BUSY,          # it says BUSY before the runner has it
                             body=bytes(8) + word(syms["fn_manage"]) + word(syms["save_body"]),
                             done=bytes(8) + word(syms["fn_manage"]) + word(syms["save_done"]))]
    assert rig.state == BUSY and not rig.stray and not rig.writes and not rig.saves
    rig.start()                                                                     # one is running: no second job
    assert len(rig.jobs) == 1


@pytest.mark.parametrize("bank", [0, 2])
def test_the_job_writes_the_takes_and_not_the_project(main, bank):
    rig = SaveRig(main, bank=bank)
    takes = {10: noise(960, 1), 11: noise(960, 2), 62: noise(4000, 3), 63: noise(4000, 4), 30: noise(224, 7), 31: noise(224, 8)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    rig.start()
    assert rig.run() == 0 and rig.state == DONE
    want = {}
    for slot, x in takes.items():
        raw = header(len(x) // 2, slot) + x
        raw = raw.ljust((len(raw) + 511) // 512 * 512, b"\0")
        for j in range(len(raw) // 512):
            want[sector_of(slot) + bank * RUN + j] = raw[512 * j:512 * j + 512]
    assert rig.drive == want                                # the takes' sectors in the loaded bank, and nothing else on the drive
    assert audio.kept == set(takes) and not rig.saves and not rig.loads and not rig.erased and not rig.stray
    assert rig.mark is None                                 # our sector of the banks is a project save's to write
    rig.start()                                             # again: they are on the drive, nothing is written
    n = len(rig.writes)
    assert rig.run() == 0 and rig.state == DONE and len(rig.writes) == n and len(rig.jobs) == 2


def test_with_no_take_it_says_done(main):
    rig = SaveRig(main)
    rig.serve(Takes(rig, {}))
    rig.start()
    assert rig.run() == 0 and rig.state == DONE and not rig.writes


@pytest.mark.parametrize("fail_at", [0, 3, 8])
def test_a_drive_error_says_fail_and_the_next_save_tries_again(main, fail_at):
    rig = SaveRig(main)
    takes = {4: noise(2000, 1), 5: noise(2000, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    rig.fail_at = fail_at
    rig.start()
    assert rig.run() == 1 and rig.state == FAIL and audio.kept != set(takes)
    rig.fail_at = None
    rig.start()
    assert rig.jobs[-1]["state"] == BUSY and rig.run() == 0 and rig.state == DONE and audio.kept == set(takes)
    assert rig.slot(4) == (header(2000, 4), takes[4]) and rig.slot(5) == (header(2000, 5), takes[5])


def test_with_the_audio_cpu_not_up_it_says_fail(main):
    rig = SaveRig(main)
    rig.mc.w32(mm.AUDIO_UP, 0)
    rig.start()
    assert rig.run() == 1 and rig.state == FAIL and not rig.writes


def test_a_project_save_keeps_the_takes_as_before_and_leaves_the_word(main):
    rig = SaveRig(main)
    takes = {20: noise(700, 1), 21: noise(700, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    assert rig.keep() == 1 and audio.kept == set(takes) and len(rig.saves) == 1
    assert rig.slot(20) == (header(700, 20), takes[20]) and rig.state == IDLE and not rig.jobs


def test_stocks_own_routines_copy_and_end_our_function_objects(main):
    """What the runner does with what it is handed, run as it is: a copy by the object's second routine with 2,
    an end with 3. Ours keep nothing in the storage, so a copy is the 16 bytes and an end changes nothing."""
    image, syms = main
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.write(mm.BASE, image)
    mc.set_stack(0x407ff000, 0x40000100)
    for copy, call in ((mm.FN_COPY, "save_body"), (mm.FN_COPY_DONE, "save_done")):
        obj = b"\x12\x34\x56\x78\x9a\xbc\xde\xf0" + word(syms["fn_manage"]) + word(syms[call])
        mc.write(JOB, obj)
        mc.write(COPY, b"\xa5" * 16)
        mc.call(copy, COPY, JOB)
        assert bytes(mc.read(COPY, 16)) == obj and bytes(mc.read(JOB, 16)) == obj
        mc.call(mm.FN_END, COPY)
        assert bytes(mc.read(COPY, 16)) == obj
    # asked where its storage is, it is where it is; asked for its type, it has none; and it always answers 0
    mc.write(SCRATCH, b"\xa5" * 8)
    assert mc.call(syms["fn_manage"], SCRATCH, JOB, 1) & 0xFF == 0 and mc.r32(SCRATCH) == JOB
    assert mc.call(syms["fn_manage"], SCRATCH, JOB, 0) & 0xFF == 0 and mc.r32(SCRATCH) == 0
    assert mc.call(syms["fn_manage"], SCRATCH, JOB, 3) & 0xFF == 0 and bytes(mc.read(SCRATCH, 8)) == bytes(4) + b"\xa5" * 4


# ---- the page ------------------------------------------------------------------------------------

class PageRig(MeterRig):
    """The meter image's page rig on the save image: save_start is the test's."""

    def __init__(self, built, machines, **kw):
        self.saves = []
        super().__init__(built, machines, **kw)
        self.stub(self.syms["save_start"], lambda: self.saves.append(self.state) or 0)
        self.mc.uc.ctl_flush_tb()
        self.mc.w32(0x40196aba, 0), self.mc.w32(0x40196abe, 0)      # the bank numbers the page also draws

    def wrote(self, uc, access, address, size, value, user):
        if not mm.SAVE_STATE <= address < mm.SAVE_STATE + 4:
            super().wrote(uc, access, address, size, value, user)

    @property
    def state(self):
        return self.mc.r32(mm.SAVE_STATE)


@pytest.mark.parametrize("state", [IDLE, BUSY, DONE, FAIL])
def test_the_fifth_places_box_reads_how_the_save_is_going(main, state):
    r = PageRig(main, {0: SAMPLER}, index=1, mode=src(3))
    r.mc.w32(mm.SAVE_STATE, state)
    r.set(level=9000)
    texts = r.show()
    assert (33, 12, WORDS[state]) in texts                              # where a value goes in the first place of the lower row
    assert not [t for t in texts if t[1] == 0]                          # and no name under it: the bar is there
    assert (r.dots == bar_picture(9000)).all() and r.src() == "T2" and not r.stray


def test_a_turn_to_the_right_starts_a_save_and_one_to_the_left_puts_the_word_back(main):
    r = PageRig(main, {0: SAMPLER}, index=1, mode=src(3))
    assert r.twist(SAVE_KNOB, 1) == 1 and r.saves == [IDLE] and r.redrawn == [PAGE]
    assert r.twist(SAVE_KNOB, 3) == 1 and len(r.saves) == 2            # (whether one is running is save_start's to say)
    for state, after in ((DONE, IDLE), (FAIL, IDLE), (IDLE, IDLE), (BUSY, BUSY)):
        r.mc.w32(mm.SAVE_STATE, state)
        assert r.twist(SAVE_KNOB, -1) == 1 and r.state == after
    assert r.twist(SAVE_KNOB, 0) == 1 and len(r.saves) == 2
    assert r.mode == src(3) and not r.changes and not r.locked and not r.rec_locks and not r.popped and not r.stray


def test_the_other_knobs_and_the_other_pages_are_as_they_were(main):
    r = PageRig(main, {0: SAMPLER}, index=1, mode=src(3))
    r.twist(SRC_KNOB, 2), r.twist(REC_KNOB, 1)
    assert r.mode == m.MODE_REC | src(5) and not r.saves
    for knob in (6, 7, 8):                                              # the rest of the lower row: still nothing
        assert r.twist(knob, 1) == 1
    assert r.mode == m.MODE_REC | src(5) and not r.saves and not r.stray
    r = PageRig(main, {0: SAMPLER}, index=0, mode=src(3))               # the first page: the fifth knob is stock's
    assert r.twist(SAVE_KNOB, 1) == r.turn_answer and not r.saves and len(r.turned) == 1
    assert not [t for t in r.show() if t[2] in WORDS]
    r = PageRig(main, {0: 4}, index=1)                                  # another machine: no second page
    r.put(7, ON)
    assert not r.show() and r.rec_locks == {}                           # and the REC locks it was left with still go


def test_a_held_steps_rec_is_still_a_lock_of_its_own_on_this_main_program(main):
    """
    Not seen here: the lock is made, MODE is left alone, and it is shown."""
    r = PageRig(main, {0: SAMPLER}, index=1, mode=src(3))
    r.hold(5)
    assert r.twist(REC_KNOB, 1) == 1
    assert r.rec_locks == {5: ON} and not r.others and not r.locks and r.mode == src(3)
    assert r.edited and r.done and r.rec() == "ON"
    r.hold()
    assert r.rec() == "OFF"                                             # the track's own
    r.hold(5)
    r.twist(REC_KNOB, -1)
    assert not r.rec_locks and r.mode == src(3)


def test_the_probe_image_shows_slot_24_of_the_track_in_both_blocks(stock3, main):
    """The probe image (hardware log, 2026-10-10): the save image's main program with two numbers on the lower
    row of the sampling page, slot 24 of the track where a trig's locks are written and where the audio CPU is sent it."""
    built = build_main.patched_image(stock3, probe=True)
    words, sent, place = 0x800021b0, 0x80006348, 142 * 3 + 28 + 2 * m.K_REC
    r = PageRig(built, {3: SAMPLER}, track=3, index=1, mode=src(0))
    for page in (words & ~0xFFF, sent & ~0xFFF):
        r.mc.map(page, 0x1000)
    r.mc.write(words + place, ON.to_bytes(2, "big"))
    r.mc.write(sent + place, (0x3fa).to_bytes(2, "big"))
    r.mc.write(words + place - 142, b"\x11\x11"), r.mc.write(sent + place + 142, b"\x22\x22")     # the tracks either side
    shown = r.show()
    assert (59, 12, "5280") in shown and (85, 12, "03FA") in shown and not r.stray
    assert sent - words == 0x4198 and ON == 0x5280
    plain = PageRig(main, {3: SAMPLER}, track=3, index=1, mode=src(0)).show()       # the save image shows neither
    assert [t for t in shown if t not in plain] == [(59, 12, "5280"), (85, 12, "03FA")]
    pointers = [mm.SYN_CLASS + k for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    pointers += [mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_BUILD + 6]
    ours = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3] + [(at, at + 4) for at in pointers]
    for at in (k for k in range(len(main[0])) if built[0][k] != main[0][k]):        # the page's runs and the pointers into them
        assert any(lo <= mm.BASE + at < hi for lo, hi in ours), hex(mm.BASE + at)


# ---- a step's REC and stock's hold flag ------------------------------------------------------------
#
# Found on the unit with the probe image: slot 24 read 5280 in the block a trig's locks are written
# into and 0 or 1 in the block the audio CPU is sent. Stock writes its hold flag over slot 24 of
# every digital track after the block is built. The tests of the reclock image put the mark straight
# into the block that is sent and never ran that loop.

OFF_WORD = m.REC_WORD_OFF
SLOT24 = 28 + 2 * m.K_REC


def hold_loop(image, tracks):
    """Stock's loop (0x400a4c3e to 0x400a4c7a) run as it is. tracks: eight of (machine, slot 24 where the locks
    are written, the word at + 128, the word at + 110) -> (the block that is sent after it, as it was before)."""
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x80000000, 0x10000)
    mc.write(mm.BASE, image)
    mc.set_stack(0x407ff000, 0x40000100)
    mc.set_exits([0x40000100, mm.HOLD_END])
    words = bytearray(b"\x33" * (142 * 8))
    sent = bytearray(b"\x44" * (142 * 8))
    for t, (machine, lock, held, level) in enumerate(tracks):
        words[142 * t + SLOT24:142 * t + SLOT24 + 2] = lock.to_bytes(2, "big")
        sent[142 * t + 128:142 * t + 130] = held.to_bytes(2, "big")
        sent[142 * t + 110:142 * t + 112] = level.to_bytes(2, "big")
    mc.write(mm.MACHINE_BYTES, bytes(t[0] for t in tracks))
    mc.write(mm.PARAM_WORDS, bytes(words)), mc.write(mm.PARAM_SENT, bytes(sent))
    mc.set_reg(10, mm.PARAM_SENT)                           # a2: the block, as 0x400979ca answered it
    mc.set_reg(15, 0x407ff000)
    mc.run(mm.HOLD_LOOP, mm.HOLD_END)
    assert bytes(mc.read(mm.PARAM_WORDS, len(words))) == bytes(words)       # where the locks are written is only read
    return bytes(mc.read(mm.PARAM_SENT, len(sent))), bytes(sent)


TRACKS = [(SAMPLER, ON, 0, 0),              # a step locked on: the mark
          (SAMPLER, OFF_WORD, 1, 0),        # locked off, with stock's flag at 1: the mark
          (SAMPLER, 0x1234, 5, 0),          # no mark: stock's flag, 1 for the word at + 128
          (SAMPLER, 0x5300, 0, 0x7f00),     # nearly a mark: stock's flag, 1 for the word at + 110
          (4, ON, 0, 0x7eff),               # a mark on another machine: stock's flag, 0
          (4, ON, 9, 0),                    # and 1
          (SAMPLER, 0x52ff, 0, 0),          # the mark is the high byte: the word goes as it is
          (SAMPLER, 0, 0, 0x7eff)]          # nothing: stock's flag, 0
STOCK_FLAGS = [0, 1, 1, 1, 0, 1, 0, 0]


def test_stocks_hold_flag_no_longer_takes_a_steps_rec_from_the_block_that_is_sent(main):
    sent, was = hold_loop(main[0], TRACKS)
    want = [ON, OFF_WORD, 1, 1, 0, 1, 0x52ff, 0]
    for t, (machine, lock, held, level) in enumerate(TRACKS):
        at = 142 * t
        assert int.from_bytes(sent[at + SLOT24:][:2], "big") == want[t], t
        assert sent[at + 62:at + 64] == bytes((machine, 0))                 # the machine, as stock writes it
        assert sent[at:at + 62] == was[at:at + 62] and sent[at + 64:at + SLOT24] == was[at + 64:at + SLOT24]
        assert sent[at + SLOT24 + 2:at + 142] == was[at + SLOT24 + 2:at + 142]
    assert SLOT24 == 76 and mm.PARAM_SENT - mm.PARAM_WORDS == 0x4198 and ON >> 8 == 0x52 and OFF_WORD >> 8 == 0x29


def test_on_the_images_before_it_did(stock3):
    """The reclock image's main program: every track's slot 24 is stock's flag whatever the step locked."""
    sent, _ = hold_loop(build_main.patched_image(stock3, reclock=True)[0], TRACKS)
    assert [int.from_bytes(sent[142 * t + SLOT24:][:2], "big") for t in range(8)] == STOCK_FLAGS


def test_the_routine_is_in_the_room_the_feed_left_and_stock_is_as_it_was_around_it(stock3, main):
    image, syms = main
    lo, hi = mm.CAVE_REC
    assert lo < syms["mute_trig"] + 34 <= syms["rec_word"] < syms["rec_word"] + 50 <= hi
    assert image[mm.off(mm.HOLD_WRITE):mm.off(mm.HOLD_WRITE) + 8] == b"\x4e\xb9" + syms["rec_word"].to_bytes(4, "big") + b"\x4e\x71"
    assert stock3[mm.off(mm.HOLD_WRITE):mm.off(mm.HOLD_WRITE) + 8] == bytes.fromhex(fw.sx("dc51e2da2e3bc5c575281d33"))
    assert image[mm.off(mm.HOLD_LOOP):mm.off(mm.HOLD_WRITE)] == stock3[mm.off(mm.HOLD_LOOP):mm.off(mm.HOLD_WRITE)]
    assert image[mm.off(syms["rec_word"]) + 50:mm.off(hi)] == b"\x4e\x71" * ((hi - syms["rec_word"] - 50) // 2)


# ---- the image -----------------------------------------------------------------------------------

def test_the_image_is_the_meter_image_but_for_the_keep_code_and_the_page(official_path, official, stock3, main, before):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, meter=True)[2]
    raw, _, built, regions, syms = build.build(official_path, log=quiet, save=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] and was.section(3) == before[0]
    assert built.section(7) == was.section(7)                       # the audio CPU's program is the meter image's
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    spans = [mm.CAVE_KEEP, mm.CAVE_BANK, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3]
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(x, x + 4) for x in (mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_BUILD + 6, mm.PROJECT_LOAD_CALL + 2)]
    spans += [(x + 2, x + 6) for x in mm.PROJECT_SAVE_CALLS]
    diff = [k for k in range(len(stock3)) if before[0][k] != main[0][k]]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    image, syms = main
    lo, hi = mm.CAVE_KEEP
    assert syms["save_state"] == lo == mm.SAVE_STATE and image[mm.off(lo):mm.off(lo) + 4] == bytes(4)
    for name in ("save_start", "save_body", "save_done", "fn_manage", "save_keep"):
        assert lo + 4 <= syms[name] < hi
    lo, hi = mm.CAVE_PAGE3
    for name in ("save_place", "save_turn", "strays"):
        assert lo <= next(a for n, a in syms.items() if n.split(".")[0] == name) < hi
    # the page names the keep code's routine by its address
    assert image.find(word(syms["save_start"]), mm.off(lo), mm.off(hi)) >= 0


def test_the_stock_routines_it_calls_are_as_they_were(stock3, main):
    for lo, hi in ((mm.JOB_RUNNER, mm.JOB_RUNNER + 0x90), (mm.JOB_START, mm.JOB_START + 0x160), (mm.FN_COPY, mm.FN_COPY + 0x32),
                   (mm.FN_COPY_DONE, mm.FN_COPY_DONE + 0x32), (mm.FN_END, mm.FN_END + 0x1c), (0x4005b4ba, 0x4005b6c0), (0x4005a326, 0x4005a3ae),
                   (0x4005ba50, 0x4005bad8), (0x4005badc, 0x4005bafa), (0x4005cbc0, 0x4005cc10)):
        assert main[0][mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]


def test_the_safe_image_is_the_save_images_main_program_on_the_reclock_images_sound_engine(official_path, official, main):
    """The pitch image's sound engine was noisy on the maintainer's unit. This is everything since on the main CPU, with the
    audio program that ran clean there: each half is byte for byte one that has its own tests."""
    quiet = lambda s: None
    reclock = build.build(official_path, log=quiet, reclock=True)[2]
    save = build.build(official_path, log=quiet, save=True)[2]
    raw, _, safe, regions, _ = build.build(official_path, log=quiet, safe=True)
    assert sorted(regions) == [3, 7]
    assert safe.section(7) == reclock.section(7) != save.section(7)
    assert safe.section(3) == save.section(3) == main[0] != reclock.section(3)
    for sid in official.ids:
        if sid not in (3, 7):
            assert safe.container.by_id(sid).stored == official.container.by_id(sid).stored
