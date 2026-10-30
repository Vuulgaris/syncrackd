"""The ptn image: the takes are written to the +Drive when a whole pattern is saved to the project, and the
sampling page has no SAVE box. Builds and emulation only.

Stock has one pattern save (0x4001a8d2) and five calls of it. The two behind the pattern menu's SAVE TO
PROJ, WHOLE PATTERN go to a routine of ours (engine/keeptakes.c, ptn_keep) that calls stock's and, when
its answer's low byte is set, starts the job the save image's box started. The other three are stock's:
the main screen's save to the temp area, KIT DATA and SEQUENCE DATA.

Run as they are here: stock's pattern save, with the routines under it played by the test (the project's
number, the write protection, the two writes, the messages); stock's four callbacks of the menu, with
theirs played (the manager, the pattern's number, the names, the menu's end); the store's write under the
job, as in tests/test_save.py. The runner of jobs is the test's, as there.

What this cannot show: that the runner takes a job from the task the menu's callbacks run in, which
screens stock has up while the takes are written, and anything the drive itself does.
"""
import re
import shutil

import pytest

from emu.machine import boundaries
from test_banks import RUN
from test_keep import Takes, header, noise, sector_of
from test_gain import GAIN_KNOB
from test_mode import TAKE_KNOB
from test_pack import DEST_KNOB
from test_page import PAGE
from test_reclock import REC_KNOB, SRC_KNOB
from test_save import BUSY, DONE, FAIL, IDLE, RUNNER, SAVE_KNOB, WORDS, SaveRig, word
from test_stops import LAYOUTS, StopsPage
from tools import build, build_engine, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

MGR, MENU, PATTERN, KIT, HOLDER_OF, POPUPS = 0x41230000, 0x41240000, 0x41250000, 0x41260000, 0x41270000, 0x41280000
SCRATCH = 0x40700100                        # a callback's storage and the name it is handed
JUNK = 0xDEADBEEF                           # what a stock routine leaves in d0 when its answer is not one
YES_NO, NAMED, KIT_DATA, SEQ_DATA = 0x40182728, 0x401826da, 0x4018276a, 0x401827aa     # the menu's four callbacks
NAME_AND_SAVE = 0x40182632                  # what the naming screen's callback calls
SEQ_WRITE, KIT_WRITE = 0x4001a36a, 0x4001a458                                           # (manager, to the temp area, pattern)
NOT_SAVED, PROTECTED, RESAVE, ERROR = "N/A: Unsaved Project", "N/A: Write-protected", "Prj must be re-saved!", "Save Error"
WHOLE, OTHERS = mm.PATTERN_SAVE_CALLS, mm.PATTERN_SAVE_OTHERS


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, ptn=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, solo=True)


class PtnRig(SaveRig):
    """tests/test_save.py's rig on the ptn image. stock: the pattern save runs as it is and the routines under it are
    the test's; otherwise the pattern save itself is the test's."""

    def __init__(self, built, bank=0, stock=True):
        self.did, self.answer = [], 1
        self.project, self.protected, self.version, self.seq_ok, self.kit_ok, self.pattern = 5, 0, 13, 1, 1, 37
        super().__init__(built, bank=bank)
        say = lambda what, answer=JUNK: lambda: self.did.append(what) or answer
        if stock:
            self.stub(mm.PROJECT_NUMBER, lambda mgr: self.did.append(("project", mgr)) or self.project)
            self.stub(0x40110584, lambda store, project: self.protected)
            self.stub(0x4011067e, lambda store, project: self.version)
            self.stub(SEQ_WRITE, lambda mgr, temp, n: self.did.append(("seq", mgr, temp, n)) or self.seq_ok)
            self.stub(KIT_WRITE, lambda mgr, temp, n: self.did.append(("kit", mgr, temp, n)) or self.kit_ok)
            self.stub(0x4016ea6e, lambda: POPUPS)
            self.stub(0x400c347c, lambda popups, text: self.did.append(("error", self.cstr(text))) or JUNK)
            self.stub(0x40175912, lambda text, s: self.did.append(("said", self.cstr(text))) or JUNK)
            for addr in (0x401bf31e, 0x400c3422):                       # a string made, the message shown
                self.stub(addr, lambda: JUNK)
        else:
            self.stub(mm.PATTERN_SAVE, lambda a, b, c, d, e: self.did.append(("save", a, b, c, d, e)) or self.answer)
        # what the menu's callbacks ask for around the save
        self.stub(mm.UI_MANAGER, lambda: MGR)
        self.stub(0x4016eb0a, lambda: MENU)
        self.stub(0x400c2154, lambda menu: self.pattern)
        self.stub(0x4004a4c6, say("menu closed"))
        self.stub(0x40019000, lambda mgr: HOLDER_OF)
        self.stub(0x40016056, lambda holder: PATTERN)
        self.stub(0x40018464, lambda mgr: KIT)
        self.stub(0x40015d04, lambda pattern, name: self.did.append(("pattern named", pattern)) or JUNK)
        self.stub(0x4000ee62, lambda kit, name: self.did.append(("kit named", kit)) or JUNK)
        for addr in (0x401bea14, 0x401bd86e):                           # a string copied, a string ended
            self.stub(addr, lambda: JUNK)
        self.mc.uc.ctl_flush_tb()

    def cstr(self, at):
        raw = bytes(self.mc.read(at, 32))
        return raw[:raw.index(0)].decode()

    def wrote(self, uc, access, address, size, value, user):
        if not SCRATCH <= address < SCRATCH + 0x40:
            super().wrote(uc, access, address, size, value, user)

    def ptn(self, *args):
        """Ours, as the two calls reach it."""
        return self.mc.call(self.syms["ptn_keep"], *args)

    def menu(self, callback, yes=1):
        """One of the menu's callbacks as stock calls it: (its storage, the answer, a byte), or for the naming
        screen's (its storage, the name, a long)."""
        self.mc.w32(SCRATCH, MENU)
        self.mc.w32(SCRATCH + 8, 0x41290000)
        if callback == NAMED:
            return self.mc.call(callback, SCRATCH, SCRATCH + 8, 0)
        return self.mc.call(callback, SCRATCH, 0x5a5a5a00 | yes)

    def writes_of(self, kind):
        return [d[1:] for d in self.did if d[0] == kind]


def job_of(syms):
    """The job as the runner is handed it. It says BUSY before the runner has it."""
    return dict(runner=RUNNER, name="Take Save", state=BUSY, body=bytes(8) + word(syms["fn_manage"]) + word(syms["save_body"]),
                done=bytes(8) + word(syms["fn_manage"]) + word(syms["save_done"]))


def on_drive(takes, bank=0):
    """The sectors a set of takes is on the drive: {sector: its 512 bytes}."""
    want = {}
    for slot, x in takes.items():
        raw = header(len(x) // 2, slot) + x
        raw = raw.ljust((len(raw) + 511) // 512 * 512, b"\0")
        for j in range(len(raw) // 512):
            want[sector_of(slot) + bank * RUN + j] = raw[512 * j:512 * j + 512]
    return want


class Once(Takes):
    """A take that grows once while it is written: while its third sector is fetched."""

    def __init__(self, rig, takes, slot):
        super().__init__(rig, takes)
        self.slot, self.grown = slot, False

    def __call__(self):
        box = bytes(self.rig.mc.read(mm.KEEP_BOX, 8))
        if not self.grown and box[2:] == self.slot.to_bytes(2, "big") + (960).to_bytes(4, "big"):
            self.takes[self.slot] = self.takes[self.slot] + bytes(64)
            self.grown = True
        super().__call__()


# ---- which calls ------------------------------------------------------------------------------------

def test_the_two_whole_pattern_calls_name_ours_and_the_other_three_stocks(stock3, main):
    image, syms = main
    jsr = lambda to: b"\x4e\xb9" + word(to)
    for call in WHOLE + OTHERS:
        assert stock3[mm.off(call):mm.off(call) + 6] == jsr(mm.PATTERN_SAVE)
    for call in WHOLE:
        assert image[mm.off(call):mm.off(call) + 6] == jsr(syms["ptn_keep"])
    for call in OTHERS:
        assert image[mm.off(call):mm.off(call) + 6] == jsr(mm.PATTERN_SAVE)
    # five calls in stock and nothing else that names the routine; three and ours' own now
    assert stock3.count(word(mm.PATTERN_SAVE)) == 5 == stock3.count(jsr(mm.PATTERN_SAVE))
    assert image.count(jsr(mm.PATTERN_SAVE)) == 4 == image.count(word(mm.PATTERN_SAVE))
    assert image.count(word(syms["ptn_keep"])) == 2
    # what each call is given, in stock's bytes before it: kit, sequence, pattern, to the temp area, manager
    one, none = fw.sx("93249438fface282"), "42a7"
    pushes = {WHOLE[0]: one + one + "2f02" + none + "2f00", WHOLE[1]: one + one + "2f02" + none + "2f00",
              OTHERS[0]: one + one + "2f00" + one + fw.sx("c0f6c16d113cf14b"), OTHERS[1]: one + none + "2f02" + none + "2f00", OTHERS[2]: none + one + "2f02" + none + "2f00"}
    for call, text in pushes.items():
        raw = bytes.fromhex(text)
        assert stock3[mm.off(call) - len(raw):mm.off(call)] == raw == image[mm.off(call) - len(raw):mm.off(call)], hex(call)


def test_stock_takes_the_second_call_for_a_pattern_with_no_name_in_a_project_with_a_place(stock3):
    """Read from the listing and pinned here: WHOLE PATTERN (0x401834f8) asks whether the pattern has a name, and if
    not whether the project has a number on the drive; with no name and a number it opens the naming screen, whose
    callback names the pattern and the kit and saves both to the project. Otherwise the Y/N, whose callback saves."""
    at = lambda a, n: stock3[mm.off(a):mm.off(a) + n].hex()
    assert at(mm.PATTERN_MENU_WHOLE + 0x52, 34) == fw.sx("a776c84adbc4a35ec205fc34aafd98613f9c1b4d76ece88267430fe9cc37aec38276e3adaaed")
    assert mm.PATTERN_MENU_WHOLE + 0x70 + 2 + 0x10c == 0x40183676                   # the branch: the naming screen's part
    assert at(0x4018368a, 6) == "203c" + "%08x" % NAMED and at(0x401835f2, 6) == "203c" + "%08x" % YES_NO
    assert at(0x401836f8, 6) == fw.sx("659558fd1c781e22c0ee") and stock3[mm.off(0x4024f1ec):][:25] == fw.sb("d02d08490fc2330247a0a1dbe8e835f86439540b590c0be21cc9d9243c")
    assert at(0x401835aa, 6) == fw.sx("5275f9277a55aaa4728c") and stock3[mm.off(0x4024f205):][:16] == fw.sb("05986526699c89010e42c97ca2c3e6f6704884fb")
    assert at(NAMED + 0x20, 6) == "4eb9" + "%08x" % NAME_AND_SAVE
    for addr, n in ((YES_NO, 1), (NAMED, 1), (KIT_DATA, 1), (SEQ_DATA, 1), (NAME_AND_SAVE, 2), (mm.PATTERN_MENU_WHOLE, 1)):
        assert stock3.count(word(addr)) == n, hex(addr)
    assert stock3[mm.off(0x4025006d)] == 0                                          # the name a pattern is not named by


def test_stocks_two_tests_run_as_they_are(main):
    """A pattern is named when its settings' name is not the empty string; a project has a place when its number is
    not negative. Stock's two routines and the compare under the first, with the pattern's method and the number played."""
    rig = PtnRig(main)
    mc = rig.mc
    obj, methods, settings, fn = SCRATCH, SCRATCH + 8, 0x40700300, 0x40700200
    mc.w32(obj, methods - 40), mc.w32(methods, fn)              # the pattern's method at + 40: () -> its settings, or 0
    there = [settings]
    rig.stub(fn, lambda o: there[0])
    mc.uc.ctl_flush_tb()
    for name, want in (("", 0), ("A", 1), ("UNTITLED", 1), ("NEW PATTERN NAME", 1)):
        mc.write(settings, name.encode().ljust(20, b"\0"))
        assert mc.call(mm.PATTERN_NAMED, obj) & 0xFF == want, name
    there[0] = 0                                                # a pattern with no settings: not named
    assert mc.call(mm.PATTERN_NAMED, obj) & 0xFF == 0
    for number, want in ((0, 1), (5, 1), (127, 1), (-1, 0)):
        rig.project = number
        assert mc.call(mm.PROJECT_PLACED, MGR) == want, number
    assert not rig.stray


# ---- ours, with stock's pattern save played ----------------------------------------------------------

@pytest.mark.parametrize("answer, starts", [(1, True), (0x12345601, True), (0xFFFFFFFF, True), (0, False), (0x100, False), (0xABCDEF00, False)])
def test_the_five_arguments_and_stocks_answer_go_through(main, answer, starts):
    rig = PtnRig(main, stock=False)
    rig.answer = answer
    assert rig.ptn(MGR, 0, 37, 1, 1) == answer and rig.did == [("save", MGR, 0, 37, 1, 1)]
    assert rig.ptn(0x11111111, 0x22222222, 0x33333333, 0x44444444, 0x55555555) == answer
    assert rig.did[1] == ("save", 0x11111111, 0x22222222, 0x33333333, 0x44444444, 0x55555555)
    assert rig.jobs == ([job_of(rig.syms)] if starts else [])                       # the low byte is the answer; one job for the two
    assert rig.state == (BUSY if starts else IDLE) and not rig.writes and not rig.saves and not rig.stray


def test_nothing_is_written_where_the_pattern_is_saved(main):
    """The takes are the job's: ours asks the audio CPU for nothing and writes nothing before it answers."""
    rig = PtnRig(main, stock=False)
    audio = Takes(rig, {10: noise(960, 1), 11: noise(960, 2)})
    rig.serve(audio)
    box = bytes(rig.mc.read(mm.KEEP_BOX, 16))
    assert rig.ptn(MGR, 0, 3, 1, 1) == 1
    assert not audio.asked and not rig.writes and bytes(rig.mc.read(mm.KEEP_BOX, 16)) == box and len(rig.jobs) == 1


# ---- stock's pattern save as it is, under ours --------------------------------------------------------

def test_a_whole_pattern_saved_to_the_project_starts_our_job_once(main):
    rig = PtnRig(main)
    assert rig.ptn(MGR, 0, 37, 1, 1) == 1
    # stock's own work, in its order: the project's number, both halves to the project, both to the temp area, its message
    assert rig.did == [("project", MGR), ("seq", MGR, 0, 37), ("kit", MGR, 0, 37), ("seq", MGR, 1, 37), ("kit", MGR, 1, 37), ("said", "Ptn saved to ")]
    assert rig.jobs == [job_of(rig.syms)] and rig.state == BUSY
    assert not rig.writes and not rig.saves and not rig.stray


@pytest.mark.parametrize("why, text", [("no project", NOT_SAVED), ("protected", PROTECTED), ("old", RESAVE), ("kit", ERROR), ("seq", ERROR),
                                       ("kit to temp", ERROR), ("seq to temp", ERROR)])
def test_a_failed_pattern_save_starts_nothing(main, why, text):
    """Stock's failures, each run: a byte of 0 under whatever its message routine left, and no job."""
    rig = PtnRig(main)
    calls = []
    if why == "no project":
        rig.project = -1
    elif why == "protected":
        rig.protected = 1
    elif why == "old":
        rig.version = 12
    else:                                                                           # one of the four writes answers 0
        nth = {"seq": 0, "kit": 1, "seq to temp": 2, "kit to temp": 3}[why]
        ok = lambda: calls.append(1) or int(len(calls) - 1 != nth)
        rig.stub(SEQ_WRITE, lambda mgr, temp, n: ok())
        rig.stub(KIT_WRITE, lambda mgr, temp, n: ok())
        rig.mc.uc.ctl_flush_tb()
    answer = rig.ptn(MGR, 0, 37, 1, 1)
    assert answer & 0xFF == 0 and answer == JUNK & ~0xFF                            # the rest of the long is not an answer
    assert rig.writes_of("error") == [(text,)] and not rig.writes_of("said")
    assert not rig.jobs and rig.state == IDLE and not rig.writes and not rig.stray


@pytest.mark.parametrize("bank", [0, 2])
def test_the_job_writes_the_takes_into_the_loaded_bank(main, bank):
    rig = PtnRig(main, bank=bank)
    takes = {10: noise(960, 1), 11: noise(960, 2), 62: noise(4000, 3), 63: noise(4000, 4), 30: noise(224, 7), 31: noise(224, 8)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    assert rig.ptn(MGR, 0, 9, 1, 1) == 1 and not rig.writes
    assert rig.run() == 0 and rig.state == DONE
    assert rig.drive == on_drive(takes, bank)                   # the takes' sectors in the loaded bank, and nothing else on the drive
    assert audio.kept == set(takes) and not rig.saves and not rig.loads and not rig.erased and not rig.stray
    assert rig.mark is None                                     # our sector of the banks is a project save's to write


def test_two_saves_in_a_row_and_a_save_while_the_job_is_busy(main):
    rig = PtnRig(main)
    takes = {4: noise(2000, 1), 5: noise(2000, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1 and rig.state == BUSY
    assert rig.ptn(MGR, 0, 2, 1, 1) == 1                        # the job has not run: the pattern is saved, and no second job
    assert len(rig.jobs) == 1 and rig.writes_of("said") == [("Ptn saved to ",)] * 2 and not rig.writes
    assert rig.run() == 0 and rig.state == DONE and rig.drive == on_drive(takes)
    n = len(rig.writes)
    assert rig.ptn(MGR, 0, 2, 1, 1) == 1                        # after it: a job again, which finds every take on the drive
    assert len(rig.jobs) == 2 and rig.state == BUSY
    assert rig.run() == 0 and rig.state == DONE and len(rig.writes) == n and not rig.stray
    takes[8] = audio.takes[8] = noise(700, 3)                   # a take made since
    takes[9] = audio.takes[9] = noise(700, 4)
    assert rig.ptn(MGR, 0, 2, 1, 1) == 1 and rig.run() == 0 and rig.drive == on_drive(takes) and len(rig.jobs) == 3


@pytest.mark.parametrize("fail_at", [0, 3, 8])
def test_a_write_that_fails_says_fail_and_the_next_save_tries_again(main, fail_at):
    rig = PtnRig(main)
    takes = {4: noise(2000, 1), 5: noise(2000, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    rig.fail_at = fail_at
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1                        # the pattern is saved all the same
    assert rig.run() == 1 and rig.state == FAIL and audio.kept != set(takes)
    rig.fail_at = None
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1 and len(rig.jobs) == 2 and rig.state == BUSY
    assert rig.run() == 0 and rig.state == DONE and audio.kept == set(takes) and rig.drive == on_drive(takes)


def test_a_take_that_changed_while_it_was_written_is_left_and_the_slots_after_it_are_written(main):
    rig = PtnRig(main)
    takes = {10: noise(960, 1), 11: noise(960, 2), 40: noise(300, 3), 63: noise(1500, 4)}
    audio = Once(rig, takes, 10)
    rig.serve(audio)
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1
    assert rig.run() == 1 and rig.state == FAIL                 # not every take is on the drive
    assert audio.kept == {11, 40, 63} and sector_of(10) not in rig.writes       # no header: the drive's old one stands
    for slot in (11, 40, 63):
        assert rig.slot(slot) == (header(len(takes[slot]) // 2, slot), takes[slot])
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1 and rig.run() == 0 and rig.state == DONE      # the next save: the take as it now is
    assert audio.kept == set(takes) and rig.slot(10) == (header(992, 10), audio.takes[10]) and not rig.stray


def test_on_the_image_before_such_a_take_ended_the_run(before):
    """The solo image's keep code, which is the save image's: its text is as it was."""
    rig = SaveRig(before)
    takes = {10: noise(960, 1), 11: noise(960, 2), 40: noise(300, 3)}
    audio = Once(rig, takes, 10)
    rig.serve(audio)
    rig.start()
    assert rig.run() == 1 and rig.state == FAIL and not audio.kept
    assert not [w for w in rig.writes if w >= sector_of(11)]
    assert "ptn_keep" not in before[1]


def test_with_the_audio_cpu_not_up_it_says_fail(main):
    rig = PtnRig(main)
    rig.mc.w32(mm.AUDIO_UP, 0)
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1
    assert rig.run() == 1 and rig.state == FAIL and not rig.writes


# ---- a project's save ---------------------------------------------------------------------------------

@pytest.mark.parametrize("state", [IDLE, DONE, FAIL])
def test_a_project_save_still_writes_the_takes_and_leaves_the_word(main, state):
    rig = PtnRig(main)
    takes = {20: noise(700, 1), 21: noise(700, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    rig.mc.w32(mm.SAVE_STATE, state)
    assert rig.keep() == 1 and audio.kept == set(takes) and len(rig.saves) == 1 and rig.saves[0][3] == 0   # the project first
    assert all(rig.drive[sector] == raw for sector, raw in on_drive(takes).items())
    assert rig.slot(20) == (header(700, 20), takes[20]) and rig.state == state and not rig.jobs and not rig.did


def test_a_project_save_also_goes_on_after_a_take_that_changed(main):
    rig = PtnRig(main)
    takes = {10: noise(960, 1), 11: noise(960, 2), 40: noise(300, 3)}
    audio = Once(rig, takes, 10)
    rig.serve(audio)
    assert rig.keep() == 1 and audio.kept == {11, 40} and sector_of(10) not in rig.writes
    assert rig.keep() == 1 and audio.kept == set(takes) and rig.state == IDLE


def test_a_failed_project_save_still_keeps_nothing(main):
    rig = PtnRig(main)
    audio = Takes(rig, {10: noise(960, 1)})
    rig.serve(audio)
    rig.saved = 0xABCDEF00
    assert rig.keep() == 0xABCDEF00 and not rig.writes and not audio.asked and not rig.jobs


# ---- stock's callbacks as they are ---------------------------------------------------------------------

def test_the_yes_of_save_pattern_to_project_saves_and_starts_the_job(main):
    rig = PtnRig(main)
    takes = {6: noise(900, 1), 7: noise(900, 2)}
    rig.serve(Takes(rig, takes))
    rig.menu(YES_NO, yes=1)
    assert rig.did == [("project", MGR), ("seq", MGR, 0, 37), ("kit", MGR, 0, 37), ("seq", MGR, 1, 37), ("kit", MGR, 1, 37),
                       ("said", "Ptn saved to "), "menu closed"]
    assert rig.jobs == [job_of(rig.syms)] and not rig.writes
    assert rig.run() == 0 and rig.drive == on_drive(takes) and not rig.stray


def test_its_no_does_nothing(main):
    rig = PtnRig(main)
    rig.menu(YES_NO, yes=0)
    assert not rig.did and not rig.jobs and rig.state == IDLE and not rig.stray


def test_the_naming_screens_callback_names_both_saves_and_starts_the_job(main):
    rig = PtnRig(main)
    takes = {6: noise(900, 1), 7: noise(900, 2)}
    rig.serve(Takes(rig, takes))
    rig.menu(NAMED)
    assert rig.did == [("pattern named", PATTERN), ("kit named", KIT), ("project", MGR), ("seq", MGR, 0, 37), ("kit", MGR, 0, 37),
                       ("seq", MGR, 1, 37), ("kit", MGR, 1, 37), ("said", "Ptn saved to "), "menu closed"]
    assert rig.jobs == [job_of(rig.syms)] and not rig.writes
    assert rig.run() == 0 and rig.drive == on_drive(takes) and not rig.stray


def test_a_whole_pattern_that_stock_cannot_save_starts_nothing_from_the_menu(main):
    for callback in (YES_NO, NAMED):
        rig = PtnRig(main)
        rig.project = -1
        rig.menu(callback)
        assert rig.writes_of("error") == [(NOT_SAVED,)] and "menu closed" in rig.did and not rig.jobs and rig.state == IDLE


@pytest.mark.parametrize("callback, wrote, said", [(KIT_DATA, "kit", "Kit saved to "), (SEQ_DATA, "seq", "Seq. saved to ")])
def test_kit_data_and_sequence_data_are_stocks_and_start_nothing(main, callback, wrote, said):
    rig = PtnRig(main)
    rig.serve(Takes(rig, {6: noise(900, 1), 7: noise(900, 2)}))
    rig.menu(callback, yes=1)
    assert rig.did == [("project", MGR), (wrote, MGR, 0, 37), (wrote, MGR, 1, 37), ("said", said), "menu closed"]
    assert not rig.jobs and rig.state == IDLE and not rig.writes and not rig.stray


def test_a_save_to_the_temp_area_by_stocks_routine_starts_nothing(main):
    """What the main screen's call does, (manager, 1, pattern, 1, 1): stock's routine, which ours is not in the way of."""
    rig = PtnRig(main)
    assert rig.mc.call(mm.PATTERN_SAVE, MGR, 1, 37, 1, 1) == 1
    assert rig.did == [("seq", MGR, 1, 37), ("kit", MGR, 1, 37), ("said", "Ptn saved to ")] and not rig.jobs and rig.state == IDLE


# ---- the page -------------------------------------------------------------------------------------------

def page(built, state=IDLE, **kw):
    r = StopsPage(built, LAYOUTS["a hole in each stack"][0], **kw)
    r.saves = []
    r.stub(r.syms["save_start"], lambda: r.saves.append(1) or 0)
    r.mc.uc.ctl_flush_tb()
    r.mc.w32(PAGE + mm.PAGE_INDEX, 1)
    r.mc.w32(mm.SAVE_STATE, state)
    return r


@pytest.mark.parametrize("state", [IDLE, BUSY, DONE, FAIL])
def test_the_fifth_place_is_blank_but_after_a_save_that_failed(main, before, state):
    r, old = page(main, state), page(before, state)
    got, was = r.show(), old.show()
    mine = [t for t in got if t[:2] == (33, 12)]
    assert mine == ([(33, 12, "FAIL")] if state == FAIL else [])            # idle, busy, done: nothing at all
    assert (33, 12, WORDS[state]) in was                                    # where the solo image has its box's word
    assert [t for t in got if t[:2] != (33, 12)] == [t for t in was if t[:2] != (33, 12)]      # the rest of the page as it was
    assert not [t for t in got if t[2] in ("SAVE", "BUSY", "DONE")]
    assert (r.dots == old.dots).all() and r.mc.r32(mm.SAVE_STATE) == state and not r.stray


@pytest.mark.parametrize("state", [IDLE, BUSY, DONE, FAIL])
def test_knob_e_turns_nothing(main, state):
    r = page(main, state)
    was = (r.mode, r.dest, r.gains, r.box, r.smpl)
    for steps in (1, 3, -1, -5, 0):
        for side in (True, False):
            assert r.twist(SAVE_KNOB, steps, side) == 1                     # ours, as an empty place's knob is: stock is not asked
    assert r.mc.r32(mm.SAVE_STATE) == state and not r.saves and not r.turned
    assert (r.mode, r.dest, r.gains, r.box, r.smpl) == was and not r.changes and not r.locked and not r.did and not r.stray
    assert r.redrawn == [PAGE] * 10


def test_the_pages_other_knobs_are_the_solo_images_turn_for_turn(main, before):
    r, old = page(main, track=6), page(before, track=6)
    for knob, steps in ((SRC_KNOB, 3), (DEST_KNOB, 40), (REC_KNOB, 1), (GAIN_KNOB, 9), (TAKE_KNOB, -1), (SRC_KNOB, -1), (4, 1), (DEST_KNOB, -3), (REC_KNOB, -1),
                        (TAKE_KNOB, 1), (8, 2)):
        assert r.twist(knob, steps) == old.twist(knob, steps) and (r.mode, r.dest, r.gains, r.box) == (old.mode, old.dest, old.gains, old.box)
        assert [t for t in r.show() if t[:2] != (33, 12)] == [t for t in old.show() if t[:2] != (33, 12)]
    assert r.changes == old.changes and r.stray == old.stray and not r.saves and not old.saves
    r.mc.w32(PAGE + mm.PAGE_INDEX, 0), old.mc.w32(PAGE + mm.PAGE_INDEX, 0)              # the first page: the fifth knob is stock's
    assert r.twist(SAVE_KNOB, 1) == old.twist(SAVE_KNOB, 1) == r.turn_answer and len(r.turned) == 1
    assert r.show() == old.show() and not [t for t in r.show() if t[2] == "FAIL"]


# ---- the image ------------------------------------------------------------------------------------------

def test_the_main_program_is_the_solo_images_but_for_two_calls_and_three_runs(main, before, stock3):
    image, syms = main
    old, was = before
    spans = [mm.CAVE_KEEP, mm.CAVE_PAGE, mm.CAVE_PAGE3]
    spans += [(x + 2, x + 6) for x in mm.PROJECT_SAVE_CALLS + mm.PATTERN_SAVE_CALLS]
    diff = [k for k in range(len(stock3)) if image[k] != old[k]]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    for x in mm.PATTERN_SAVE_CALLS:                                         # each of the two calls did change
        assert any(mm.off(x + 2) <= k < mm.off(x + 6) for k in diff)
    for lo, hi in (mm.CAVE_BANK, mm.CAVE_PAGE2, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_SOLO, mm.CAVE_METER, mm.CAVE_RIGHT):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]
    # the keep code: the number first, every routine in the run, what is left of the run not touched
    lo, hi = mm.CAVE_KEEP
    assert syms["save_state"] == lo == mm.SAVE_STATE and image[mm.off(lo):mm.off(lo) + 4] == bytes(4)
    ours = ("keep_takes", "save_start", "save_body", "save_done", "fn_manage", "save_keep")
    for name in ours + ("ptn_keep",):
        assert lo + 4 <= syms[name] < hi
    end = syms["ptn_keep"] + 48
    assert max(syms[n] for n in ours) < syms["ptn_keep"]                    # it is the last routine in the run
    assert image[mm.off(end) - 2:mm.off(end)] == b"\x4e\x75" and image[mm.off(end):mm.off(hi)] == b"\x4e\x71" * ((hi - end) // 2)
    assert hi - end == 106                                                  # the room left in the run
    for call in mm.PROJECT_SAVE_CALLS:
        assert image[mm.off(call):mm.off(call) + 6] == b"\x4e\xb9" + word(syms["save_keep"])
    # the page: no routine for a turn of SAVE, and nothing in it names the routine that starts a save
    assert not [n for n in syms if n.split(".")[0] == "save_turn"] and [n for n in was if n.split(".")[0] == "save_turn"]
    for lo, hi in (mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6):
        assert image.find(word(syms["save_start"]), mm.off(lo), mm.off(hi)) < 0
    assert old.find(word(was["save_start"]), mm.off(mm.CAVE_PAGE3[0]), mm.off(mm.CAVE_PAGE3[1])) >= 0
    assert image.count(word(syms["save_start"])) == 0                       # ours calls it from beside it, in the same run


def test_ours_is_stocks_call_and_then_the_jobs_start(main):
    image, syms = main
    at = syms["ptn_keep"]
    ops = [text for _, _, text in boundaries(image[mm.off(at):mm.off(at) + 48], at)]
    calls = [t for t in ops if t.startswith("jsr")]
    assert calls == ["jsr %#x" % mm.PATTERN_SAVE, "jsr %%pc@(%#x)" % syms["save_start"]]
    assert ops[-1] == "rts" and ops.count("rts") == 1
    assert ops.count("movel %sp@(24),%sp@-") == 5                           # the five it was given, as they came
    assert "tstb %d0" in ops and ops.index("tstb %d0") > ops.index(calls[0])        # the answer's low byte, nothing above it


ROUTINES = [(0x40182632, 0x401827ea), (mm.PATTERN_MENU_WHOLE, 0x401837cc), (0x40033ee0, 0x40035148)]    # the menu's, and the main screen's keys


def test_nothing_else_in_the_program_goes_into_a_changed_place(stock3):
    """No address in the program points inside one of the two operands, and no branch of the routines around the
    calls, or of the main screen's key routine, lands in one or between a call's pushes and the call."""
    inside = [a for call in WHOLE for a in range(call - 13, call + 6)]
    for a in inside:
        assert word(a) not in stock3, hex(a)
    seen = 0
    for lo, hi in ROUTINES:
        for at, raw, text in boundaries(stock3[mm.off(lo):mm.off(hi)], lo):
            for target in re.findall(r"0x(4[0-9a-f]{7})\b", text):
                seen += 1
                assert int(target, 16) not in inside, hex(at)
    assert seen > 300                                                       # the listing does name its branches' targets


def test_the_stock_routines_it_leans_on_are_as_they_were(stock3, main):
    for lo, hi in ((mm.PATTERN_SAVE, 0x4001aaaa), (SEQ_WRITE, mm.PATTERN_SAVE), (0x40182632, 0x401826c2), (0x401826c6, 0x40182756), (0x4018275a, 0x401827ea),
                   (mm.PATTERN_MENU_WHOLE, 0x401837cc), (0x400341b4, 0x400341e6), (mm.PATTERN_NAMED, 0x40015da2), (mm.PROJECT_NUMBER, 0x40018c5e),
                   (mm.JOB_RUNNER, mm.JOB_RUNNER + 0x90), (mm.JOB_START, mm.JOB_START + 0x160)):
        assert main[0][mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)], hex(lo)


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, ptn=True)
    was = build.build(official_path, log=quiet, solo=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the solo image's byte for byte, which is the stops image's
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
