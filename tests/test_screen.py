"""Names and words on screen: the "screen" image (engine/knobtext.c). OS 1.42 only.

SMPL shows the stereo sample's name when MODE counts stereo samples, LOOP and MODE show
words. One routine in the main program, called where stock calls its slot text function.

Emulated here: our routine, alone and through the stock code that calls a record's text
function, with the manager, the object that holds a track's values and the slot text function
played by the test; and the stock slot text function itself up to the name it asks the sample
store for. Not emulated, because the main program is not run as a whole: that the manager's
routine gives the active track's values on the unit, and what the unit draws with the text:
see docs/FINDINGS.md.
"""
import shutil

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build_main, deadcode, uitable
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STACK = (0x407f0000, 0x407ff000)
HEAP = 0x41000000
MANAGER, HOLDER, METHODS, VALUE_FN, OUT = HEAP + 0x40, HEAP + 0x100, HEAP + 0x200, HEAP + 0x300, HEAP + 0x400
TEXT0 = mm.UI_TABLE + 0x14
SMPL, LOOP, MODE = (TEXT0 + mm.UI_STRIDE * r for r in (mm.R_SMPL, mm.R_LOOP, mm.R_MODE))
MONO, PAIRS = (0, 4), (1, 2, 3, 5)
NO_SAMPLE = "NO SAMPLE"
NAME_FETCH, SPRINTF = 0x401113b6, 0x40000e82      # in the stock slot text function: (store, slot, string), (out, format, ...)
SLOT_GUARD, STORE_GLOBAL = 0x41bab1b0, 0x444e239c


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def screen(stock3):
    return build_main.patched_image(stock3, screen=True)


@pytest.fixture(scope="module")
def double(stock3):
    return build_main.patched_image(stock3, double=True)


def knob_value(n, reverse=False):
    """The 8.8 value of the SMPL knob that reads n (1..64), on either half."""
    return ((64 - n) if reverse else (n + 63)) << 8


def stock_number(value):
    v = value >> 8
    return v - 63 if v > 63 else 64 - v


class Screen:
    """The patched main program with the manager, the holder of a track's values and (unless
    real_slot_text) the stock slot text function played by the test."""

    def __init__(self, built, mode=0, names=None, real_slot_text=False):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x41b90000, 0x30000)                        # the function objects, the table, the text buffer
        mc.map(STORE_GLOBAL & ~0xFFF, 0x1000)
        mc.map(HEAP, 0x10000)
        mc.write(mm.BASE, image)
        mc.set_stack(STACK[1], 0x40000100)
        self.mode, self.names, self.holder = mode, names or {}, HOLDER
        self.asked, self.valued, self.slot_texts, self.fetched, self.stray = [], [], [], [], []
        mc.w32(HOLDER, METHODS)
        mc.w32(METHODS + mm.KNOB_VALUE, VALUE_FN)
        self.stub(mm.UI_MANAGER, lambda: MANAGER)
        self.stub(mm.KNOB_HOLDER, lambda manager, record, track: self.ask(manager, record, track))
        self.stub(VALUE_FN, lambda holder, record: self.value(holder, record))
        if real_slot_text:
            mc.write(SLOT_GUARD, b"\x01")                  # its one-time set-up is done
            mc.w32(STORE_GLOBAL, 0x12345678)               # and the sample store exists
            self.stub(NAME_FETCH, lambda store, slot, string: self.fetch(store, slot))
            self.stub(SPRINTF, lambda out, fmt, arg: self.put(out, self.cstr(arg)))
        else:
            self.stub(mm.TEXT_SLOT, lambda obj, value, out: self.slot_text(obj, value, out))
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, self.wrote)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
            uc.reg_write(UC_M68K_REG_D0, (fn(*args) or 0) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def wrote(self, uc, access, address, size, value, user):
        if not (STACK[0] <= address < STACK[1] or OUT <= address < OUT + 16 or mm.TEXT_OUT <= address < mm.TEXT_OUT + 16):
            self.stray.append(address)

    def ask(self, manager, record, track):
        self.asked.append((manager, record, track))
        return self.holder

    def value(self, holder, record):
        self.valued.append((holder, record))
        return self.mode << 8

    def fetch(self, store, slot):
        self.fetched.append((store, slot))
        return 0                                           # no sample there: the stock function writes NO SAMPLE

    def put(self, out, text):
        self.mc.write(out, text.encode() + b"\0")

    def cstr(self, addr):
        raw = bytes(self.mc.read(addr, 32))
        return raw[:raw.index(0)].decode()

    def slot_text(self, obj, value, out):
        """What stock writes: the name of the slot the value is on, or NO SAMPLE."""
        self.slot_texts.append((obj, value))
        self.put(out, self.names.get(stock_number(value), NO_SAMPLE))

    def text(self, obj, value):
        self.mc.write(OUT, b"\xee" * 16)
        self.mc.call(self.syms["knob_text"], obj, value, OUT)
        return self.cstr(OUT)


def test_code_space_is_a_run_nothing_reaches(stock3, official, screen):
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert mm.CAVE_TEXT in deadcode.usable(runs)
    lo, hi = mm.CAVE_TEXT
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    others = (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, build_main.POOL_STAGE)
    assert not any(lo < b and a < hi for a, b in others)
    image, syms = screen
    assert all(lo <= syms[s] < hi for s in ("knob_text", "put"))
    # the stock function's address is in the program once, where its object is built: that is the place changed
    assert stock3.count(mm.TEXT_SLOT.to_bytes(4, "big")) == 1
    cave = image[mm.off(lo):mm.off(hi)]
    assert image.count(mm.TEXT_SLOT.to_bytes(4, "big")) == cave.count(mm.TEXT_SLOT.to_bytes(4, "big")) == 2     # our two calls of it
    assert image[mm.off(mm.TEXT_SLOT_SITE):mm.off(mm.TEXT_SLOT_SITE) + 6] == b"\x22\x3c" + syms["knob_text"].to_bytes(4, "big")
    # the stock function itself is untouched: our routine calls it
    end = mm.TEXT_FOR
    assert image[mm.off(mm.TEXT_SLOT):mm.off(end)] == stock3[mm.off(mm.TEXT_SLOT):mm.off(end)]


def test_three_knobs_and_no_others_get_their_text_from_our_routine(stock3, screen, double):
    ours = screen[1]["knob_text"]
    new, old, was = uitable.table(screen[0]), uitable.table(double[0]), uitable.table(stock3)
    assert len(new) == mm.UI_COUNT
    mine = [k for k, e in enumerate(new) if e.get("text", {}).get("target") == ours]
    assert mine == [mm.R_SMPL, mm.R_LOOP, mm.R_MODE]
    for k in mine:
        assert new[k]["text"]["object"] == mm.OBJ_TEXT_SLOT
    # stock gave that object to the two sample selectors and to nothing else
    assert [k for k, e in enumerate(was) if e.get("text", {}).get("object") == mm.OBJ_TEXT_SLOT] == [mm.R_SMPL, mm.R_MODE]
    assert was[mm.R_SMPL]["text"]["target"] == mm.TEXT_SLOT
    # every other field of every entry is the double image's
    for k, (a, b) in enumerate(zip(new, old)):
        if k in mine:
            a, b = dict(a), dict(b)
            assert a.pop("text") != b.pop("text") or k == mm.R_SMPL
        assert {f: (v["object"] if isinstance(v, dict) else v) for f, v in a.items()} \
            == {f: (v["object"] if isinstance(v, dict) else v) for f, v in b.items()}, k


@pytest.mark.parametrize("mode", MONO)
def test_in_mono_smpl_shows_what_stock_shows(screen, mode):
    names = {1: "COUNT", 3: "PAD L", 4: "PAD R", 64: "LAST_L"}
    s = Screen(screen, mode, names)
    for v in range(128):
        assert s.text(SMPL, v << 8) == names.get(stock_number(v << 8), NO_SAMPLE)
    assert [value for _, value in s.slot_texts] == [v << 8 for v in range(128)]      # the value goes through as it came
    assert all(obj == SMPL for obj, _ in s.slot_texts) and not s.stray


@pytest.mark.parametrize("mode", PAIRS)
def test_in_stereo_smpl_shows_the_left_slots_name_without_its_side(screen, mode):
    names = {1: "KICK L", 2: "KICK R", 3: "sample02_L", 4: "sample02_R", 5: "TAKE 03 L", 7: "bass-l", 9: "TOM.L",
             11: "BELL", 13: "L", 15: "AL", 17: "FULL", 18: "ONLY RIGHT", 63: "123456789012_L"}
    shown = {1: "KICK", 2: "sample02", 3: "TAKE 03", 4: "bass", 5: "TOM", 6: "BELL", 7: "L", 8: "AL", 9: "FULL", 32: "123456789012"}
    s = Screen(screen, mode, names)
    for n in range(1, 33):
        for reverse in (False, True):
            assert s.text(SMPL, knob_value(n, reverse)) == shown.get(n, NO_SAMPLE), (n, reverse)
    # stock was asked for the slot 2n-1 each time, with the table's own object
    assert [stock_number(value) for _, value in s.slot_texts] == [2 * n - 1 for n in range(1, 33) for _ in range(2)]
    assert all(obj == SMPL for obj, _ in s.slot_texts) and not s.stray


@pytest.mark.parametrize("mode", PAIRS)
def test_past_32_there_is_no_stereo_sample(screen, mode):
    s = Screen(screen, mode, {n: "FULL %d" % n for n in range(1, 65)})
    for n in range(33, 65):
        for reverse in (False, True):
            assert s.text(SMPL, knob_value(n, reverse)) == NO_SAMPLE
    assert not s.slot_texts and not s.stray


def test_mode_is_asked_the_way_a_page_asks(screen):
    s = Screen(screen, 1, {1: "A L"})
    assert s.text(SMPL, knob_value(1)) == "A"
    assert s.asked == [(MANAGER, mm.R_MODE, 0xFFFFFFFF)]                # the manager, MODE's record, the active track
    assert s.valued == [(HOLDER, mm.R_MODE)]


def test_loop_and_mode_read_as_words(screen):
    s = Screen(screen)
    assert [s.text(MODE, v << 8) for v in range(6)] == ["MONO", "STEREO", "REC MAIN", "REC EXT", "CHAIN", "ST CHAIN"]
    assert [s.text(LOOP, v << 8) for v in range(3)] == ["OFF", "FWD", "PING"]
    assert s.text(MODE, (1 << 8) + 0xff) == "STEREO"                    # the fraction of an 8.8 value is not read
    assert not s.asked and not s.slot_texts and not s.stray             # no other routine is needed for a word


def test_a_value_no_knob_has_reads_as_its_number(screen):
    s = Screen(screen)
    assert [s.text(MODE, v << 8) for v in (6, 9, 10, 65, 100, 127)] == ["6", "9", "10", "65", "100", "127"]
    assert [s.text(LOOP, v << 8) for v in (3, 64)] == ["3", "64"]
    assert not s.asked and not s.slot_texts and not s.stray


@pytest.mark.parametrize("obj", [mm.OBJ_TEXT_SLOT, SMPL + 2, TEXT0 - mm.UI_STRIDE, TEXT0 + mm.UI_STRIDE * 7, HEAP + 0x800])
def test_an_object_that_is_not_loops_or_modes_is_treated_as_smpl(screen, obj):
    s = Screen(screen, 1, {1: "ONE L", 5: "THREE L"})
    assert s.text(obj, knob_value(3)) == "THREE"
    assert s.slot_texts == [(obj, knob_value(5))]                       # the object is passed on as it came
    s = Screen(screen, 0, {3: "THREE"})
    assert s.text(obj, knob_value(3)) == "THREE"


def test_without_a_holder_smpl_reads_as_in_mono(screen):
    s = Screen(screen, 1, {2: "TWO", 3: "THREE L"})
    s.holder = 0
    assert s.text(SMPL, knob_value(2)) == "TWO"
    assert not s.valued


def test_through_the_stock_code_that_asks_for_a_records_text(screen):
    """TEXT_FOR and TEXT_CALL are stock, run as they are: record -> the table's object -> our routine."""
    s = Screen(screen, 1, {3: "PAD L", 4: "PAD R"})
    for record in (mm.R_SMPL, mm.R_LOOP, mm.R_MODE):
        obj = TEXT0 + mm.UI_STRIDE * record
        s.mc.w32(obj + 8, 1)                                            # a filled object, as the start-up routine leaves it
        s.mc.w32(obj + 12, s.syms["knob_text"])
    for record, value, text in ((mm.R_SMPL, knob_value(2), "PAD"), (mm.R_SMPL, knob_value(2, True), "PAD"),
                                (mm.R_SMPL, knob_value(40), NO_SAMPLE), (mm.R_LOOP, 2 << 8, "PING"), (mm.R_MODE, 3 << 8, "REC EXT")):
        assert s.mc.call(mm.TEXT_FOR, record, value) == mm.TEXT_OUT
        assert s.cstr(mm.TEXT_OUT) == text
    assert not s.stray


@pytest.mark.parametrize("mode", MONO + PAIRS)
def test_the_stock_slot_text_function_looks_up_the_left_slot(screen, mode):
    """The stock function is run for real, up to the name it asks the sample store for."""
    s = Screen(screen, mode, real_slot_text=True)
    for n in (1, 2, 17, 32):
        for reverse in (False, True):
            assert s.text(SMPL, knob_value(n, reverse)) == NO_SAMPLE
    step = 2 if mode in PAIRS else 1
    assert [slot for _, slot in s.fetched] == [step * (n - 1) for n in (1, 2, 17, 32) for _ in range(2)]     # slots count from 0
    assert all(store == 0x12345678 for store, _ in s.fetched)


def test_the_words_fit_where_stock_put_a_sample_name(screen):
    image, syms = screen
    lo, hi = mm.CAVE_TEXT
    words = image[mm.off(lo):mm.off(syms["put"])].split(b"\0")
    words = [w.decode() for w in words if w]
    assert words == ["MONO", "STEREO", "REC MAIN", "REC EXT", "CHAIN", "ST CHAIN", "OFF", "FWD", "PING", NO_SAMPLE]
    assert max(map(len, words)) <= 9                                    # a slot's name is up to 15
    assert image[mm.off(0x40251d2f):mm.off(0x40251d2f) + 10] == NO_SAMPLE.encode() + b"\0"     # stock's own words for an empty slot


def test_screen_image_builds_and_the_others_do_not_contain_it(official_path, official, stock3, screen):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, screen=True)
    assert sorted(regions) == [3, 7] and built.section(3) == screen[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    dbl = build.build(official_path, log=quiet, double=True)[2]
    assert built.section(7) == dbl.section(7)                           # nothing changes on the audio CPU
    lo, hi = mm.CAVE_TEXT
    assert dbl.section(3)[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    assert dbl.section(3)[mm.off(mm.TEXT_SLOT_SITE):mm.off(mm.TEXT_SLOT_SITE) + 6] == b"\x22\x3c" + mm.TEXT_SLOT.to_bytes(4, "big")
    # apart from the new code, the object's function and the two text objects, section 3 is the double image's
    a, b = bytearray(dbl.section(3)), bytearray(built.section(3))
    for start, end in (mm.CAVE_TEXT, (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6), (0x40194360, 0x40194364), (0x401943aa, 0x401943ae)):
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b


# ---- the pages behind a track key (read for the sampling page; nothing here is patched) ---------------

def test_the_page_table_as_the_start_up_code_fills_it(stock3):
    def text(addr):
        raw = stock3[mm.off(addr):mm.off(addr) + 24]
        return raw[:raw.index(0)].decode()

    assert stock3[mm.off(mm.PAGE_ENTRY):mm.off(mm.PAGE_ENTRY) + 26] == bytes.fromhex(
        fw.sx("639f4721a32537760a5cb41e7265bf8cfc2ec5bc004f608f0422361c2410"))
    assert mm.PAGE_TABLE + mm.PAGE_STRIDE * mm.PAGE_COUNT == mm.UI_TABLE
    pages = uitable.pages(stock3)
    name = {k: text(p["name"]) for k, p in pages.items()}
    # a key with two pages: stock has them for the filter, the amp and the LFOs
    assert [name[k] for k in (4, 5, 7, 8, 13, 15)] == ["LFO1", "LFO2", "FLTR1", "FLTR2", "AMP1", "AMP2"]
    # SYN has no records of its own, and the entry before the table is the sampler's page, knob by knob
    assert name[mm.PAGE_SYN] == "SYN" and pages[mm.PAGE_SYN]["knobs"] == [0] * 8
    first = mm.SAMP_FIRST
    assert name[-1] == "SYN" and pages[-1]["knobs"] == [first, first + 1, first + 2, first + 7, first + 4, first + 5, first + 3, first + 6]
    assert pages[-1]["level"] == 10
    # every knob of every page is a record that exists, and two numbered pages hold none at all
    used = {r for p in pages.values() for r in p["knobs"] + [p["level"]]}
    assert max(used) < mm.UI_COUNT
    assert [k for k, p in pages.items() if p["knobs"] == [0] * 8 and not p["level"]] == [0, 25]
    assert (name[0], name[25]) == ("NONE", "OB8")
