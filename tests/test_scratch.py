"""The scratch image: every take held on the drive once recording stops, so a power off before a save keeps it."""
import hashlib
import shutil

import pytest
from unicorn import UC_HOOK_CODE

import test_banks as B
from test_keep import Takes, header, noise, sector_of
from test_load import PUT
from tools import build, build_main, deadcode
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TABLE, FIRST, PLACES = mm.SCRATCH_TABLE, mm.SCRATCH_FIRST, mm.SCRATCH_PLACES
MAGIC = 0x53435254
FED = mm.SHARED + 0x800
RUNS = (mm.CAVE_SCRATCH, mm.CAVE_SCRATCH2, mm.CAVE_SCRATCH3, mm.CAVE_SCRATCH4, mm.CAVE_SCRATCH5, mm.CAVE_SCRATCH6)


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=47)


def place(p):
    return FIRST + 2048 * p


def table(bank, places):
    t = [0] * 128
    t[0], t[1], t[127] = MAGIC, bank, ~MAGIC & 0xFFFFFFFF
    for p, slot in places.items():
        t[2 + p] = slot + 1
    return b"".join(v.to_bytes(4, "big") for v in t)


def read_table(r):
    raw = r.drive[TABLE]
    t = [int.from_bytes(raw[4 * j:4 * j + 4], "big") for j in range(128)]
    assert (t[0], t[127]) == (MAGIC, ~MAGIC & 0xFFFFFFFF)
    return t[1], {p: t[2 + p] - 1 for p in range(PLACES) if t[2 + p]}


class Rig(B.BankRig):
    def __init__(self, built, bank=0):
        super().__init__(built, bank)
        self.jobs = []
        self.stub(0x4016ec18, lambda: 0x41230000)
        self.stub(0x400bdc48, lambda runner, name, what, done: self.jobs.append(
            (bytes(self.mc.read(name, 9)).decode(), self.mc.r32(what + 12))) or 0)

    def wrote(self, uc, access, address, size, value, user):
        v = self.syms["scr_vars"]
        if not (v <= address < v + 16 or mm.CAVE_PHONE[0] <= address < mm.CAVE_PHONE[0] + 8):
            super().wrote(uc, access, address, size, value, user)

    def serve(self, fn):
        super().serve(fn)
        ask = self.syms["scr_ask"]

        def hook(uc, address, size, user):
            box = self.mc.read(mm.KEEP_BOX, B.m.KEEP_ACK + 4)
            if bytes(2) + box[B.m.KEEP_REQ:B.m.KEEP_REQ + 2] != box[B.m.KEEP_ACK:B.m.KEEP_ACK + 4]:
                fn()
        self.mc.uc.hook_add(UC_HOOK_CODE, hook, begin=ask, end=self.syms["scr_put"] - 1)

    def run(self, name):
        return self.mc.call(self.syms[name], 0)

    def vars(self):
        return [self.mc.r32(self.syms["scr_vars"] + 4 * k) for k in range(4)]

    def hold(self, p, slot, data):
        raw = (header(len(data) // 2, slot) + data).ljust((64 + len(data) + 511) // 512 * 512, b"\0")
        for j in range(len(raw) // 512):
            self.drive[place(p) + j] = raw[512 * j:512 * j + 512]


def test_the_room_is_after_the_banks_sector_and_under_what_is_free():
    assert TABLE == mm.BANK_MARK_SECTOR + 1 and FIRST == TABLE + 1
    assert place(PLACES) <= mm.DRIVE_FREE[1] < place(PLACES + 1)
    for lo, hi in RUNS:
        others = [r for n, r in vars(mm).items() if n.startswith("CAVE") and isinstance(r, tuple) and len(r) == 2 and r not in RUNS]
        assert not any(a < hi and lo < b for a, b in others)


def test_the_code_is_in_runs_nothing_reaches(official, main):
    stock3 = official.section(3)
    usable = deadcode.usable(deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)]))
    assert all(run in usable for run in RUNS)
    syms = main[1]
    assert syms["scr_vars"] == mm.CAVE_SCRATCH[0]
    for name in ("hold_body", "back_body", "scratch_commit", "scratch_drop", "scratch_poll", "scr_take"):
        assert any(lo <= syms[name] < hi for lo, hi in RUNS)
    lo, hi = mm.CAVE_ONCE
    assert main[0][mm.off(lo):mm.off(hi)].count(b"\x4e\xb9" + syms["scratch_poll"].to_bytes(4, "big")) == 1  # the main task's loop calls it


def test_a_take_goes_to_a_place_header_last_then_the_table_and_is_marked_kept(main):
    r = Rig(main)
    takes = Takes(r, {10: noise(960, 1), 11: noise(500, 2)})
    r.serve(takes)
    r.run("hold_body")
    assert takes.kept == {10, 11}
    assert r.writes == [place(0) + 1, place(0) + 2, place(0) + 3, place(0), TABLE, place(1) + 1, place(1) + 2, place(1), TABLE]
    assert read_table(r) == (0, {0: 10, 1: 11})
    assert r.drive[place(0)] == (header(960, 10) + takes.takes[10])[:512]
    assert b"".join(r.drive[place(0) + j] for j in range(4))[64:64 + 1920] == takes.takes[10]
    assert not any(B.FIRST <= w < TABLE - 1 for w in r.writes) and r.vars()[0] == 0 and not r.stray


def test_a_new_take_in_a_held_slot_goes_to_its_place_unlisted_while_written(main):
    r = Rig(main)
    r.drive[TABLE] = table(0, {0: 4, 1: 10})
    takes = Takes(r, {10: noise(300, 3)})
    r.serve(takes)
    r.run("hold_body")
    assert r.writes == [TABLE, place(1) + 1, place(1), TABLE] and read_table(r) == (0, {0: 4, 1: 10})


def test_a_take_still_growing_is_left_for_the_next_job(main):
    r = Rig(main)
    takes = Takes(r, {10: noise(960, 1)})
    seen = []

    def growing():
        box = bytes(r.mc.read(mm.KEEP_BOX, 8))
        if box[2:4] == (10).to_bytes(2, "big") and int.from_bytes(box[4:8], "big") == 0:
            seen.append(1)
            if len(seen) == 2:
                takes.takes[10] += noise(32, 9)
        takes()
    r.serve(growing)
    r.run("hold_body")
    assert not takes.kept and TABLE not in r.writes


def test_a_table_of_another_bank_is_not_believed(main):
    r = Rig(main, bank=1)
    r.drive[TABLE] = table(0, {0: 4})
    takes = Takes(r, {6: noise(100, 1)})
    r.serve(takes)
    r.run("hold_body")
    assert read_table(r) == (1, {0: 6})


def test_at_a_start_each_place_goes_back_to_its_slot(main):
    r = Rig(main)
    data = B.sample(500, 1)
    r.drive[TABLE] = table(0, {2: 7})
    r.hold(2, 7, data)
    audio = B.BankAudio(r, {})
    audio.busy = []
    r.serve(audio)
    r.run("back_body")
    assert audio.got(7) == data and audio.done == {7: 500}
    assert audio.busy and all(audio.busy) and r.mc.r32(B.BUSY) == 0 and not r.writes and r.vars()[0] == 0


def test_at_a_start_another_banks_places_are_left(main):
    r = Rig(main, bank=1)
    r.drive[TABLE] = table(0, {2: 7})
    r.hold(2, 7, B.sample(500, 1))
    audio = B.BankAudio(r, {})
    r.serve(audio)
    r.run("back_body")
    assert not audio.done and not r.writes


def test_a_save_copies_the_places_into_the_bank_then_writes_what_is_newer(main):
    r = Rig(main, bank=2)
    r.drive[B.MARK] = B.marker(now=2, of={5: 2})
    held = noise(960, 4)
    r.drive[TABLE] = table(2, {3: 10})
    r.hold(3, 10, held)
    takes = Takes(r, {12: noise(400, 5)})
    r.serve(takes)
    assert r.keep((7, 5, B.PROGRESS)) == 1
    bank = lambda s: sector_of(s) + 2 * B.RUN
    assert r.writes[:5] == [bank(10) + 1, bank(10) + 2, bank(10) + 3, bank(10), TABLE]
    assert b"".join(r.drive[bank(10) + j] for j in range(4))[:64 + 1920] == header(960, 10) + held
    assert read_table(r) == (2, {}) and takes.kept == {12} and r.name(10).startswith("TAKE 06")
    assert not any(B.FIRST <= w < B.FIRST + 2 * B.RUN for w in r.writes)


def test_a_load_has_the_held_slots_loaded_from_the_bank_and_empties_the_table(main):
    r = Rig(main)
    r.drive[B.MARK] = B.marker(now=0, of={12: 0})
    r.drive[TABLE] = table(0, {0: 10})
    r.put(10, B.sample(500, 1))
    audio = B.BankAudio(r, {})
    r.serve(audio)
    assert r.load((7, 12, B.PROGRESS)) == 1
    assert audio.done == {10: 500} and audio.got(10) == B.sample(500, 1)  # the take was kept: only the table says so
    assert read_table(r) == (0, {}) and r.writes == [TABLE]


def test_the_poll_starts_the_start_job_once_then_a_hold_when_the_feed_has_stopped(main):
    r = Rig(main)
    poll = lambda: r.mc.call(r.syms["scratch_poll"])
    done = lambda: r.mc.w32(r.syms["scr_vars"], 0)
    r.mc.w32(FED, 0x00120001)
    poll()
    assert r.jobs == [("Take Back", r.syms["back_body"])]
    poll()
    done()
    poll()
    assert len(r.jobs) == 1  # nothing fed since
    r.mc.w32(FED, 0x00400003)
    poll()
    assert len(r.jobs) == 1  # being fed
    poll()
    assert r.jobs[1:] == [("Take Hold", r.syms["hold_body"])]  # the same at the next message: stopped
    done()
    poll()
    assert len(r.jobs) == 2
    r.mc.w32(FED, 0x00410003)
    poll()
    r.mc.w32(mm.SAVE_STATE, 1)
    poll()
    assert len(r.jobs) == 2  # not while a save runs
    r.mc.w32(mm.SAVE_STATE, 2)
    r.mc.w32(r.syms["scr_vars"], 1)
    poll()
    assert len(r.jobs) == 2  # nor while one of ours does
    done()
    poll()
    assert len(r.jobs) == 3 and not r.stray


def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=47, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=46, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("a85e26c5")  # the scan image, as it is
    assert built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    runs = [r for n, r in vars(mm).items() if n.startswith("CAVE") and isinstance(r, tuple) and len(r) == 2]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))  # a call of ours whose routine moved
    diff = [mm.BASE + k for k in range(len(new)) if new[k] != old[k]]
    assert diff and [hex(a) for a in diff if not any(lo <= a < hi for lo, hi in runs) and not moved(mm.off(a))] == []
    print("scratch image", hashlib.sha256(raw).hexdigest())
