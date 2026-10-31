"""A second page behind SYN on a sampler track: the "page" image (engine/recpage.c). OS 1.42 only.

The sampling page: a second page behind SYN on a sampler track with SRC, DEST and REC. REC and
SRC are bits of the track's MODE parameter, changed the two ways the stock knob routine changes a
parameter, the track's value or the locks of held steps; DEST is the page's own. The MODE knob of
the first page becomes a switch between MONO and STEREO.

Emulated here: our routines with the active track, a track's machine, the stock methods they
stand in front of, the text routine and the redraw request played by the test; the stock routine
that makes the page list's vector, run as it is on our list; and the stock instructions that step
to the next page on a key press, run as they are on a page object our routine has just seen.

**The stock page methods that read and change a parameter run as they are** (+ 84 the value, + 88
the track's value changed, + 144, + 148, + 152 and + 164 for one held step, and stock's own + 156
and + 96 where a test compares), so what ours hands them is read by stock's own code. The test
plays one level under them: the holder's methods, the pattern's steps and their trigs, the keys
object's memory. A first build was tested against a stand-in for + 96 that changed the track's
value too; the real one does not, and on the unit nothing moved. A second took stock's first
question for "steps are held" and left held steps alone; on the unit a held trig locked nothing
(docs/FINDINGS.md, hardware log).

Not emulated, because the main program is not run as a whole: the page object as stock builds
it, the holder and what its methods do with a value, the text routine itself, what the unit shows.
"""
import shutil

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A2, UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC

from emu.machine import Machine
from tools import audiomap as m
from tools import build_main, deadcode
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STACK = (0x407f0000, 0x407ff000)
HEAP = 0x41000000
PAGE, LIST, TRACKS, KIT, VEC, FRESH = HEAP + 0x1000, HEAP + 0x2000, HEAP + 0x3000, HEAP + 0x4000, HEAP + 0x5000, HEAP + 0x6000
EVENT, SURFACE = HEAP + 0x7000, HEAP + 0x8000
PAGE_METHODS, RECORD_FN, MANAGER, HOLDER, HOLDER_METHODS, VALUE_FN = (HEAP + 0x9000 + 0x100 * k for k in range(6))
PLAIN_FN, LOCK_FN, MAKE_FN, MOVE_FN, STEPS, KITOBJ = (HEAP + 0x9600 + 0x100 * k for k in range(6))
KEYS = HEAP + 0xa000                                # the object at page + 108: held steps as 64 bits at + 344, "edited" at + 352
TEXT, CLOSURE = HEAP + 0xb000, HEAP + 0xb100        # where the test's text routine writes; what stock's + 156 allocates
VALUE = mm.KNOB_VALUE
JUNK = 0x5a3c0000                                   # what a routine that answers a byte or a word leaves above it
ANSWER = HEAP + 0xf100                              # a byte for a stock method's answer, when the test calls one itself
STEREO, REC, EXT_BIT = m.MODE_STEREO, m.MODE_REC, m.MODE_EXT
STATE = PAGE + mm.SYN_SIZE                         # ours: the bytes the build adds after the object
MAIN, EXT = 0, 1
BOX = mm.REC_BOX                                    # the settings as the feed and the audio CPU read them
SAMPLER = 44
ALLOC = 0x4010394c


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def page(stock3):
    return build_main.patched_image(stock3, page=True)


@pytest.fixture(scope="module")
def screen(stock3):
    return build_main.patched_image(stock3, screen=True)


class Rig:
    """The patched main program with a page object of the test's own, and the stock routines
    ours call played by the test."""

    def __init__(self, built, machines, track=0, index=0, pages=2, junk=False, mode=0):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(HEAP, 0x10000)
        mc.map(mm.UI_TABLE & ~0xFFF, 0x10000)                   # the display table: a record's flags say whether it can be locked
        mc.w32(mm.UI_TABLE + mm.UI_STRIDE * mm.R_MODE, 4)       # MODE's, as the start-up code leaves them (tools/uitable.py)
        mc.map(mm.SHARED, 0x2000)
        mc.write(mm.BASE, image)
        mc.set_stack(STACK[1], 0x40000100)
        mc.write(mm.SHARED, b"\x5a" * 0x1000)                   # the window holds whatever the boot left
        self.told = []                                          # (offset in the box, size, value) of every write to it
        self.mode, self.changes, self.read = mode, [], []       # the active track's MODE, as the stock code holds it
        self.locks, self.locked = {}, []                        # step: its lock of MODE; every (what, step, by) done to one
        self.steps, self.trigs, self.length = set(), set(), 64  # steps whose key is held; steps with a trig; the pattern's length
        self.popups, self.popped = True, []
        mc.w32(PAGE, PAGE_METHODS)
        for at, fn in ((mm.GET_METHOD, mm.PAGE_GET), (mm.PLAIN_METHOD, mm.PAGE_PLAIN), (mm.LOCK_METHOD, mm.PAGE_LOCK), (mm.LOCKS_METHOD, mm.PAGE_LOCKS),
                       (mm.LOCKABLE_METHOD, mm.PAGE_LOCKABLE), (mm.STEP_LOCK_METHOD, mm.PAGE_STEP_LOCK), (mm.STEP_MAKE_METHOD, mm.PAGE_STEP_MAKE),
                       (mm.STEP_MOVE_METHOD, mm.PAGE_STEP_MOVE), (mm.HELD_METHOD, mm.PAGE_HELD), (mm.STEP_ARG_METHOD, mm.PAGE_STEP_ARG),
                       (mm.HOLDER_METHOD, mm.PAGE_HOLDER), (112, RECORD_FN)):
            mc.w32(PAGE_METHODS + at, fn)                       # stock's own, but + 112 (the record behind a knob of a machine's page)
        mc.w32(PAGE + mm.PAGE_MANAGER, MANAGER)
        mc.w32(PAGE + mm.PAGE_KEYS, KEYS)
        mc.w32(HOLDER, HOLDER_METHODS)
        for at, fn in ((VALUE, VALUE_FN), (mm.HOLDER_PLAIN, PLAIN_FN), (mm.HOLDER_LOCK, LOCK_FN), (mm.HOLDER_MAKE, MAKE_FN), (mm.HOLDER_MOVE, MOVE_FN)):
            mc.w32(HOLDER_METHODS + at, fn)
        self.machines, self.track = machines, track
        self.asked, self.stock, self.stray = [], [], []
        self.drawn, self.texts, self.turned, self.redrawn, self.order = [], [], [], [], []
        self.turn_answer = 0x77
        if junk:
            mc.write(STATE, b"\xa5" * mm.SYN_ROOM)              # the memory comes as it is
        mc.w32(PAGE + 116, TRACKS)
        mc.w32(PAGE + 120, KIT)
        mc.w32(PAGE + mm.PAGE_LIST, LIST)
        mc.w32(PAGE + mm.PAGE_LIST_END, LIST + 4 * pages)
        mc.w32(PAGE + mm.PAGE_INDEX, index)
        mc.w32(LIST, 6)
        mc.w32(LIST + 4, 6)
        self.stub(mm.ACTIVE_TRACK, lambda tracks: self.active(tracks))
        self.stub(mm.MACHINE_OF, lambda kit, track: self.machine(kit, track))
        self.stub(mm.SYN_KNOB, lambda obj, knob: self.knob(obj, knob))
        self.stub(mm.SYN_DRAW, lambda obj, surface: self.draw(obj, surface))
        self.stub(mm.SYN_TURN, lambda obj, event: self.turn(obj, event))
        self.stub(mm.PAGE_REDRAW, lambda obj: self.redrawn.append(obj) or 0)
        self.stub(mm.UI_MANAGER, lambda: MANAGER)
        self.stub(mm.KNOB_HOLDER, lambda manager, record, track: self.holder(manager, record, track))
        self.stub(VALUE_FN, lambda holder, record: self.value(holder, record))
        self.stub(PLAIN_FN, lambda holder, record, change, track, flag, answer, a, b: self.plain(holder, record, change, track, flag, answer, a, b))
        self.stub(LOCK_FN, lambda holder, record, step: self.lock(holder, record, step))
        self.stub(MAKE_FN, lambda holder, record, value, step: self.make(holder, record, value, step))
        self.stub(MOVE_FN, lambda holder, record, change, step, flag, answer: self.move(holder, record, change, step, flag, answer))
        self.stub(RECORD_FN, lambda obj, track, record, knob: record)
        self.stub(mm.UI_STATE, lambda state: 0)
        self.stub(mm.PATTERN, lambda manager: STEPS if manager == MANAGER else 0)
        self.stub(mm.PATTERN_LENGTH, lambda steps: self.length)
        self.stub(mm.STEP_A, lambda steps, step: JUNK | (steps == STEPS and step in self.trigs and step % 2 == 0))    # a trig of one kind
        self.stub(mm.STEP_B, lambda steps, step: JUNK | (steps == STEPS and step in self.trigs and step % 2 == 1))    # or of the other
        self.stub(mm.STEP_TRIG, lambda steps, step, one: self.trig(steps, step, one))
        self.stub(mm.STEP_SOUND, lambda steps, step: JUNK | 0xFF)       # no sound of its own on any step
        self.stub(mm.KIT_OF, lambda tracks: KITOBJ)
        self.stub(0x40020172, lambda tracks: 0)                 # for stock's + 96: the first sixteen steps are on show
        self.stub(ALLOC, lambda size: CLOSURE)                  # for stock's + 156
        self.stub(0x4016dc10, lambda fn: 0)
        self.stub(mm.POPUPS, lambda tracks: 0 if self.popups else 1)
        self.stub(mm.TEXT_FOR, lambda record, value: self.text_for(record, value))
        self.stub(mm.POPUP, lambda keys, fmt, a, b: self.popup(keys, fmt, a, b))
        self.stub(mm.DRAW_TEXT, lambda surface, font, x, y, mode, fmt, arg: self.text(surface, font, x, y, mode, fmt, arg))
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, self.wrote)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
            uc.reg_write(UC_M68K_REG_D0, fn(*args) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def wrote(self, uc, access, address, size, value, user):
        if BOX <= address < BOX + m.REC_SIZE:
            self.told.append((address - BOX, size, value & (0xFFFF if size == 2 else 0xFFFFFFFF)))
        elif not (STACK[0] <= address < STACK[1] or address in (PAGE + mm.PAGE_LIST_END, PAGE + mm.PAGE_INDEX)
                  or STATE <= address < STATE + mm.SYN_ROOM or KEYS + 88 <= address < KEYS + 344 or address in (KEYS + 352, KEYS + 56)
                  or CLOSURE <= address < CLOSURE + 20):
            self.stray.append(address)

    @property
    def box(self):
        """The eight destinations as the box holds them, if both marks are there."""
        raw = bytes(self.mc.read(BOX, m.REC_SIZE))
        if raw[:8] != m.REC_MARK.to_bytes(4, "big") + (m.REC_MARK ^ 0xFFFFFFFF).to_bytes(4, "big"):
            return None
        return [int.from_bytes(raw[m.REC_DEST + 2 * t:m.REC_DEST + 2 * t + 2], "big") for t in range(8)]

    @property
    def dest(self):
        """The active track's DEST as the page object holds it: 0 is SMPL."""
        return self.mc.read(STATE + 4 + self.track, 1)[0]

    def holder(self, manager, record, track):
        self.read.append((manager, record, track))
        return HOLDER

    def value(self, holder, record):
        assert (holder, record) == (HOLDER, mm.R_MODE)
        return self.mode << 8

    def hold(self, *steps, trigs=True):
        """The keys of these steps are held: their bits in the keys object. They have trigs unless told otherwise."""
        self.steps = set(steps)
        if trigs:
            self.trigs |= self.steps
        bits = sum(1 << k for k in steps)
        self.mc.write(KEYS + mm.KEYS_HELD, bits.to_bytes(8, "big"))
        self.mc.write(KEYS + 88, b"\xa5" * 256)                 # what stock's "done" clears

    @property
    def edited(self):
        """The keys object's word that a turn has gone to held steps."""
        return self.mc.read(KEYS + 352, 1)[0]

    @property
    def done(self):
        """Stock's "done" has run on the keys object since the last hold()."""
        return bytes(self.mc.read(KEYS + 88, 256)) == bytes(256)

    def trig(self, steps, step, one):
        assert (steps, one) == (STEPS, 1) and step in self.steps and step not in self.trigs
        self.trigs.add(step)
        self.locked.append(("trig", step, 0))
        return 0

    def text_for(self, record, value):
        assert record == mm.R_MODE and value % 256 == 0
        self.mc.write(TEXT, b"mode %d\0" % (value >> 8))
        return TEXT

    def popup(self, keys, fmt, a, b):
        assert (keys, fmt) == (KEYS, mm.POPUP_FORMAT)
        self.popped.append((self.cstr(a), self.cstr(b)))
        return 0

    def plain(self, holder, record, change, track, flag, answer, a, b):
        """The holder's + 44, as stock's + 88 calls it: the track's value moves by the change."""
        change -= (change & 0x80000000) << 1
        assert (holder, record, track, flag, a, b) == (HOLDER, mm.R_MODE, self.track, 0, 1, 1) and change % 256 == 0
        assert STACK[0] <= answer < STACK[1] or answer == ANSWER
        self.changes.append(change // 256)
        self.mode += change // 256
        return 0

    def lock(self, holder, record, step):
        """The holder's + 64: a step's lock, negative when it has none."""
        assert (holder, record) == (HOLDER, mm.R_MODE)
        return self.locks[step] << 8 if step in self.locks else 0xFFFFFFFF

    def make(self, holder, record, value, step):
        """The holder's + 68, as stock's + 148 calls it: a lock at that value."""
        assert (holder, record) == (HOLDER, mm.R_MODE) and step in self.trigs and step not in self.locks and value % 256 == 0
        self.locks[step] = value >> 8
        self.locked.append(("make", step, value >> 8))
        return 1

    def move(self, holder, record, change, step, flag, answer):
        """The holder's + 76, as stock's + 152 calls it: the lock moves by the change."""
        change -= (change & 0x80000000) << 1
        assert (holder, record, flag) == (HOLDER, mm.R_MODE, 0) and step in self.locks and change % 256 == 0
        assert STACK[0] <= answer < STACK[1] or answer == ANSWER
        self.locks[step] += change // 256
        self.locked.append(("move", step, change // 256))
        return 0

    def cstr(self, addr):
        raw = bytes(self.mc.read(addr, 16))
        return raw[:raw.index(0)].decode()

    def active(self, tracks):
        self.asked.append(("track", tracks))
        return self.track

    def machine(self, kit, track):
        self.asked.append(("machine", kit, track))
        return self.machines[track]

    def knob(self, obj, knob):
        self.stock.append((obj, knob))
        return 400 + knob

    def draw(self, obj, surface):
        self.drawn.append((obj, surface))
        self.order.append("stock")
        return 0

    def text(self, surface, font, x, y, mode, fmt, arg):
        assert (surface, font, mode, fmt) == (SURFACE, mm.FONT_NAMES, 2, mm.FMT_NAME)
        self.texts.append((x, y, self.cstr(arg)))
        self.order.append("text")
        return 0

    def turn(self, obj, event):
        self.turned.append((obj, event))
        return self.turn_answer

    def ask(self, knob):
        return self.mc.call(self.syms["syn_knob"], PAGE, knob)

    def show(self):
        """One drawing of the page: -> the text ours wrote."""
        self.texts, self.order = [], []
        self.mc.call(self.syms["syn_draw"], PAGE, SURFACE)
        return list(self.texts)

    def twist(self, knob_id, steps, side=True):
        """A turn of a knob, the way the unit delivers it: a call on the object's second base, 4 bytes in."""
        self.mc.w32(EVENT + mm.EVENT_ID, knob_id)
        self.mc.w32(EVENT + mm.EVENT_STEPS, steps & 0xFFFFFFFF)
        if side:
            return self.mc.call(self.syms["syn_turn_side"], PAGE + 4, EVENT)
        return self.mc.call(self.syms["syn_turn"], PAGE, EVENT)

    @property
    def pages(self):
        return (self.mc.r32(PAGE + mm.PAGE_LIST_END) - self.mc.r32(PAGE + mm.PAGE_LIST)) // 4

    @property
    def index(self):
        return self.mc.r32(PAGE + mm.PAGE_INDEX)

    def press(self):
        """The stock instructions that step to the next page, up to the call that draws it."""
        stepped, skipped = mm.PAGE_STEP + 0x1e, mm.PAGE_STEP + 0x32    # the push for the redraw; where one page branches to
        self.mc.set_exits([0x40000100, stepped, skipped])
        self.mc.uc.reg_write(UC_M68K_REG_A2, PAGE)
        self.mc.uc.emu_start(mm.PAGE_STEP, 0, count=16)
        pc = self.mc.uc.reg_read(UC_M68K_REG_PC)
        assert pc in (stepped, skipped), hex(pc)
        return pc == stepped


def test_code_space_is_a_run_nothing_reaches(stock3, official, page):
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    image, syms = page
    others = [mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, mm.CAVE_TEXT, build_main.POOL_STAGE]
    for cave, names in ((mm.CAVE_PAGE, ("syn_knob", "syn_draw", "syn_turn", "syn_turn_side", "syn_pages")),
                        (mm.CAVE_PAGE2, ("flip", "mode", "held", "value"))):       # the second: the first filled up
        assert cave in deadcode.usable(runs)
        lo, hi = cave
        assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
        assert not any(lo < b and a < hi for a, b in others)
        assert all(lo <= syms[s] < hi for s in names)
        others.append(cave)


def test_one_object_serves_syn_and_it_now_gets_our_list_of_two(stock3, page):
    image, syms = page
    lo, hi = mm.PAGES_BUILD
    # stock names SYN's list once in the whole program, in the routine that builds the page objects
    assert stock3.count(mm.SYN_LIST.to_bytes(4, "big")) == 1
    assert lo <= mm.SYN_BUILD < hi
    assert image[mm.off(mm.SYN_BUILD):mm.off(mm.SYN_BUILD) + 10] == bytes.fromhex(fw.sx("dbe767df731d528350da")) + syms["syn_pages"].to_bytes(4, "big")
    ours = image[mm.off(syms["syn_pages"]):mm.off(syms["syn_pages"]) + 8]
    assert ours == (mm.PAGE_SYN).to_bytes(4, "big") * 2             # page 6 twice: no number stock does not know
    # nothing else in that routine changed: every other key's object and list is stock's
    a, b = bytearray(stock3[mm.off(lo):mm.off(hi)]), bytearray(image[mm.off(lo):mm.off(hi)])
    for start, n in ((mm.SYN_BUILD + 1, 1), (mm.SYN_BUILD + 6, 4), (mm.SYN_BUILD + 0x1a, 2)):     # the count, the list, the object's size
        a[start - lo:start - lo + n] = b[start - lo:start - lo + n] = bytes(n)
    assert a == b
    # the stock list is still there for anything that might read it
    assert image[mm.off(mm.SYN_LIST):mm.off(mm.SYN_LIST) + 4] == (6).to_bytes(4, "big")


def test_only_the_syn_class_and_only_three_of_its_methods_go_to_our_routines(stock3, page):
    image, syms = page
    table = lambda img: [int.from_bytes(img[mm.off(mm.SYN_CLASS) + 4 * k:mm.off(mm.SYN_CLASS) + 4 * k + 4], "big") for k in range(60)]
    was, now = table(stock3), table(image)
    ours = {mm.PAGE_DRAW_METHOD: (mm.SYN_DRAW, "syn_draw"), mm.PAGE_TURN_METHOD: (mm.SYN_TURN, "syn_turn"), mm.PAGE_KNOB_METHOD: (mm.SYN_KNOB, "syn_knob")}
    assert [4 * k for k in range(60) if was[k] != now[k]] == sorted(ours)
    lo, hi = mm.CAVE_PAGE
    for method, (stock, sym) in ours.items():
        assert was[method // 4] == stock and now[method // 4] == syms[sym]
        # the one change outside our code is that slot: wherever else stock names the method (other classes
        # share the draw and the knob routine) it still does
        mine = image[mm.off(lo):mm.off(hi)].count(stock.to_bytes(4, "big"))
        assert mine >= 1 and image.count(stock.to_bytes(4, "big")) == stock3.count(stock.to_bytes(4, "big")) - 1 + mine
    assert stock3.count(mm.SYN_KNOB.to_bytes(4, "big")) == 1          # the method that knows the machine is SYN's alone
    for start, n in ((mm.SYN_KNOB, 0xa6), (mm.SYN_DRAW, 0x2e6), (mm.SYN_TURN, 0x50)):      # the stock methods themselves are untouched
        assert image[mm.off(start):mm.off(start) + n] == stock3[mm.off(start):mm.off(start) + n]
    # a turn's real way in: the third entry of the second base's table, which stock points at a jump into its routine
    side = mm.SYN_SIDE + mm.SYN_SIDE_TURN
    assert stock3[mm.off(side):mm.off(side) + 4] == mm.SYN_TURN_THUNK.to_bytes(4, "big")
    assert image[mm.off(side):mm.off(side) + 4] == syms["syn_turn_side"].to_bytes(4, "big")
    assert stock3[mm.off(mm.SYN_TURN_THUNK):mm.off(mm.SYN_TURN_THUNK) + 6] == bytes.fromhex(fw.sx("24f7b5f466fb1a7d8a24"))
    assert mm.SYN_TURN_THUNK + 4 + 2 - 0x56 == mm.SYN_TURN                           # where that jump lands
    assert stock3.count(mm.SYN_TURN_THUNK.to_bytes(4, "big")) == 3                     # two other classes use the same jump:
    assert image.count(mm.SYN_TURN_THUNK.to_bytes(4, "big")) == 2                      # theirs are left alone
    # the object is asked for with room for our state after it
    assert image[mm.off(mm.SYN_BUILD + 0x18):mm.off(mm.SYN_BUILD + 0x1c)] == b"\x48\x78" + (mm.SYN_SIZE + mm.SYN_ROOM).to_bytes(2, "big")


def test_the_stock_routine_makes_a_vector_of_two_from_our_list(page):
    """VECTOR_FROM is stock, run as it is with the count and the list the patched builder hands it."""
    image, syms = page
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(HEAP, 0x10000)
    mc.write(mm.BASE, image)
    mc.set_stack(STACK[1], 0x40000100)
    asked = []
    mc.write(ALLOC, b"\x4e\x75")

    def alloc(uc, address, size, user):
        asked.append(mc.r32(uc.reg_read(UC_M68K_REG_A7) + 4))
        uc.reg_write(UC_M68K_REG_D0, FRESH)
    mc.uc.hook_add(UC_HOOK_CODE, alloc, begin=ALLOC, end=ALLOC)
    mc.uc.ctl_flush_tb()
    mc.call(mm.VECTOR_FROM, VEC, syms["syn_pages"], 2, 0)
    first, last = mc.r32(VEC), mc.r32(VEC + 4)
    assert asked == [8] and (first, last) == (FRESH, FRESH + 8)
    assert [mc.r32(first), mc.r32(first + 4)] == [mm.PAGE_SYN, mm.PAGE_SYN]


@pytest.mark.parametrize("index", [0, 1])
def test_a_sampler_track_has_two_pages_and_the_second_is_empty(page, index):
    r = Rig(page, {3: SAMPLER}, track=3, index=index, pages=1)
    got = [r.ask(k) for k in range(8)]
    assert r.pages == 2 and r.index == index
    if index:
        assert got == [0] * 8 and not r.stock                      # no record behind any knob, and stock is not asked
    else:
        assert got == [400 + k for k in range(8)]                  # the first page is stock's answer, knob by knob
        assert r.stock == [(PAGE, k) for k in range(8)]
    assert r.asked[:2] == [("track", TRACKS), ("machine", KIT, 3)]  # the active track's machine, the way the stock method finds it
    assert not r.stray


@pytest.mark.parametrize("machine", [0, 7, 8, 33, 35, 36, 43, 0xFFFFFFFF])
@pytest.mark.parametrize("index", [0, 1])
def test_any_other_machine_has_one_page(page, machine, index):
    r = Rig(page, {5: machine}, track=5, index=index, pages=2)
    assert [r.ask(k) for k in range(8)] == [400 + k for k in range(8)]
    assert r.pages == 1 and r.index == 0                            # and if it was on the second page, it is back on the first
    assert r.stock == [(PAGE, k) for k in range(8)] and not r.stray


def test_a_second_press_steps_only_on_a_sampler(page):
    """The stock stepping instructions, run on a page object after one drawing of the page."""
    r = Rig(page, {0: SAMPLER, 1: 4}, track=0)
    r.ask(0)
    assert r.press() and r.index == 1                              # second press: the empty page
    assert r.ask(0) == 0
    assert r.press() and r.index == 0                              # third press: back
    assert r.ask(0) == 400
    r.press()
    r.track = 1                                                     # on the second page, then to a track with another machine
    assert r.ask(0) == 400 and r.index == 0 and r.pages == 1
    assert not r.press() and r.index == 0                          # one page: a press does not step
    r.track = 0
    assert r.ask(0) == 400 and r.pages == 2                        # back on the sampler: its first page, two pages again


def test_page_image_builds_and_the_others_do_not_contain_it(official_path, official, stock3, page):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, page=True)
    assert sorted(regions) == [3, 7] and built.section(3) == page[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    scr = build.build(official_path, log=quiet, screen=True)[2]
    # the audio CPU's program is the one built with the page's take (tests/test_pagerec.py holds what differs in it)
    from tools import build_engine
    assert built.section(7) == build_engine.patched_image(official.section(7), page=True)[0] != scr.section(7)
    for lo, hi in (mm.CAVE_PAGE, mm.CAVE_PAGE2):
        assert scr.section(3)[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    # apart from the new code, SYN's object and its class's entries, the feed's routine, and MODE's words and range,
    # section 3 is the screen image's
    a, b = bytearray(scr.section(3)), bytearray(built.section(3))
    slots = [(mm.SYN_CLASS + m, mm.SYN_CLASS + m + 4) for m in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    slots.append((mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4))
    mode_max = mm.SAMP_RECORDS + 0x34 * 5 + 0xc                    # MODE's range, 0..7 here
    for start, end in [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_REC, mm.CAVE_TEXT, (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6), (mode_max, mode_max + 4),
                       (mm.SYN_BUILD + 1, mm.SYN_BUILD + 2), (mm.SYN_BUILD + 6, mm.SYN_BUILD + 10),
                       (mm.SYN_BUILD + 0x1a, mm.SYN_BUILD + 0x1c)] + slots:
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b


# ---- what is on the page ---------------------------------------------------------------------------

def test_the_second_page_shows_three_settings_where_stock_puts_a_knobs_name_and_picture(stock3, page):
    r = Rig(page, {0: SAMPLER}, index=1, junk=True)
    # stock's own places, from its draw: x 25 + 26 a column with the name centred 8 further, knobs 0..3 at y 34 with the name 7 above
    x0, y0 = stock3[mm.off(mm.PAGE_DRAW + 0xd)] + 8, int.from_bytes(stock3[mm.off(mm.PAGE_DRAW + 0x34):mm.off(mm.PAGE_DRAW + 0x36)], "big") - 7
    step = int.from_bytes(stock3[mm.off(mm.PAGE_DRAW + 0x11e):mm.off(mm.PAGE_DRAW + 0x122)], "big")
    assert (x0, y0, step) == (33, 27, 26)
    assert r.show() == [(x0, y0, "SRC"), (x0, y0 + 12, "MAIN"), (x0 + step, y0, "DEST"), (x0 + step, y0 + 12, "SMPL"),
                        (x0 + 2 * step, y0, "REC"), (x0 + 2 * step, y0 + 12, "OFF")]
    assert r.order == ["stock"] + ["text"] * 6 and r.drawn == [(PAGE, SURFACE)]       # stock draws first, ours on top
    assert r.dest == 0                                                                 # whatever the memory held, it starts here
    assert r.read == [(MANAGER, mm.R_MODE, 0xFFFFFFFF)]                                # MODE, of the active track, as a page reads it
    assert not r.stray


@pytest.mark.parametrize("mode, src, rec", [(0, "MAIN", "OFF"), (STEREO, "MAIN", "OFF"), (REC, "MAIN", "ON"), (REC | STEREO, "MAIN", "ON"),
                                            (EXT_BIT, "EXT", "OFF"), (EXT_BIT | STEREO, "EXT", "OFF"), (REC | EXT_BIT, "EXT", "ON"), (7, "EXT", "ON")])
def test_src_and_rec_are_read_out_of_mode(page, mode, src, rec):
    r = Rig(page, {0: SAMPLER}, index=1, mode=mode)
    shown = r.show()
    assert (shown[1][2], shown[5][2]) == (src, rec)


@pytest.mark.parametrize("machine, index", [(SAMPLER, 0), (0, 0), (0, 1), (8, 1), (35, 1), (0xFFFFFFFF, 1)])
def test_any_other_page_is_drawn_by_stock_alone(page, machine, index):
    r = Rig(page, {0: machine}, index=index)
    if machine != SAMPLER and index:
        r.ask(0)                                                    # stock's draw asks for each knob first, which puts the index back
    assert r.show() == [] and r.drawn == [(PAGE, SURFACE)]
    assert not r.stray and not r.read


@pytest.mark.parametrize("start", range(8))
def test_rec_and_src_each_switch_their_own_bit_of_the_tracks_mode(page, start):
    """No step held: the track's value, through stock's own + 88, which runs here as it is."""
    for knob, bit in ((1, EXT_BIT), (3, REC)):
        for steps in (1, 3, -1, -5, 0):
            r = Rig(page, {0: SAMPLER}, index=1, mode=start)
            assert r.twist(knob, steps) == 1
            want = start | bit if steps > 0 else start & ~bit if steps < 0 else start
            assert r.mode == want                                   # only that bit moved, and only as far as on or off
            assert r.changes == ([want - start] if want != start else [])
            assert r.redrawn == [PAGE] and not r.turned and not r.stray and not r.told
            assert not r.locks and not r.locked and not r.edited


def test_stocks_plus_96_does_nothing_for_a_turn_with_no_trig_about(page):
    """Found on the unit with the first build that made REC a bit of MODE: SRC, REC and MODE did not move. That
    build handed every turn to the page's + 96. Stock's + 96, run here as it is, touches steps with a trig among
    the sixteen on show, held or not, and never the track's value."""
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.mc.call(mm.PAGE_LOCK, PAGE, mm.R_MODE, 5, 2 << 8, 0, ANSWER)
    assert r.mode == 0 and not r.changes and not r.locked
    r.trigs = {4, 20}                                               # nothing held: the trig on show gets it all the same
    r.mc.call(mm.PAGE_LOCK, PAGE, mm.R_MODE, 5, 2 << 8, 0, ANSWER)
    r.mc.call(mm.PAGE_LOCK, PAGE, mm.R_MODE, 5, 2 << 8, 0, ANSWER)
    assert r.mode == 0 and not r.changes and r.locked == [("make", 4, 0), ("move", 4, 2)]


def test_what_stock_does_with_a_turn_while_a_step_is_held(page):
    """Stock's + 156, run as it is: the method its knob routine gives the turn to. It marks the keys object, makes
    the held step's lock at the track's value without applying the change, moves it the next time, and tidies up.
    Ours does the same with the same methods, one step at a time (the tests after this one)."""
    r = Rig(page, {0: SAMPLER}, index=1, mode=STEREO)
    r.trigs = {4, 9}
    r.hold(4)
    r.mc.call(mm.PAGE_HELD, PAGE, mm.R_MODE, REC << 8, 0, ANSWER)
    assert r.locked == [("make", 4, STEREO)] and r.edited == 1 and r.done
    r.mc.call(mm.PAGE_HELD, PAGE, mm.R_MODE, REC << 8, 0, ANSWER)
    assert r.locked == [("make", 4, STEREO), ("move", 4, REC)] and r.locks == {4: STEREO | REC}
    assert r.mode == STEREO and not r.changes                       # the track's value and the other trig are left alone


@pytest.mark.parametrize("knob, bit", [(1, EXT_BIT), (3, REC)])
def test_with_a_step_held_the_switch_goes_to_that_steps_lock_and_not_to_the_track(page, knob, bit):
    """What was asked for: hold a trig, turn REC, and that step records while the others play."""
    r = Rig(page, {0: SAMPLER}, index=1, mode=STEREO)
    r.trigs = {4, 9}
    r.hold(4)
    assert r.twist(knob, 1) == 1
    assert r.locks == {4: STEREO | bit} and r.mode == STEREO and not r.changes
    assert r.locked == [("make", 4, STEREO | bit)]                  # one click is enough: the lock is made at the value wanted
    assert r.edited == 1 and r.done                                 # the keys object is told before and after, as stock tells it
    for _ in range(3):                                              # more of the same turn: it is a switch, not a count
        r.twist(knob, 2)
    assert r.locks == {4: STEREO | bit} and len(r.locked) == 1
    r.twist(knob, -1)
    assert r.locks == {4: STEREO} and r.locked[1:] == [("move", 4, -bit)]
    r.twist(knob, -1)
    assert len(r.locked) == 2 and r.mode == STEREO and not r.changes and not r.stray
    assert r.redrawn == [PAGE] * 6 and not r.popped                 # no pop-up for a lock, as with stock


def test_a_held_step_with_nothing_to_change_gets_no_lock(page):
    r = Rig(page, {0: SAMPLER}, index=1, mode=REC)
    r.hold(9)
    r.twist(3, 1)                                                   # REC on, where the track has it on already
    r.twist(1, -1)                                                  # SRC to MAIN, where it is
    assert not r.locks and not r.locked and not r.changes
    r.twist(3, -1)                                                  # REC off on that step alone
    assert r.locks == {9: 0} and r.mode == REC


def test_every_held_step_is_switched_from_its_own_value(page):
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.locks = {2: EXT_BIT, 3: REC | STEREO, 40: 7}
    r.hold(2, 3, 7, 40)                                             # two with a lock, one without, one on a later page of steps
    r.twist(3, 1)
    assert r.locks == {2: EXT_BIT | REC, 3: REC | STEREO, 7: REC, 40: 7} and r.mode == 0
    assert r.locked == [("move", 2, REC), ("make", 7, REC)]
    r.twist(3, -1)
    assert r.locks == {2: EXT_BIT, 3: STEREO, 7: 0, 40: 5} and not r.changes and not r.stray


def test_a_held_step_with_no_trig_gets_one_with_its_lock(page):
    """Stock's + 148 does it: a lock needs a trig to sit on."""
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.hold(12, trigs=False)
    r.twist(3, 1)
    assert r.locked == [("trig", 12, 0), ("make", 12, REC)] and r.trigs == {12}


def test_steps_past_the_patterns_length_are_not_held_steps(page):
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.length = 12
    r.hold(11, 12, 30)
    r.twist(3, 1)
    assert r.locks == {11: REC} and not r.changes
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)                    # only keys past the end: the turn is the track's, as with stock
    r.length = 12
    r.hold(12, 63)
    r.twist(3, 1)
    assert not r.locks and r.mode == REC and r.changes == [REC] and not r.edited


def test_while_a_step_is_held_the_page_shows_that_steps_settings(page):
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.locks = {6: REC | EXT_BIT}
    assert [t[2] for t in r.show()[1::2]] == ["MAIN", "SMPL", "OFF"]
    r.hold(6)
    assert [t[2] for t in r.show()[1::2]] == ["EXT", "SMPL", "ON"]  # its lock
    r.hold(5)
    assert [t[2] for t in r.show()[1::2]] == ["MAIN", "SMPL", "OFF"]    # a held step with no lock: the track's
    r.mode = REC
    assert [t[2] for t in r.show()[1::2]] == ["MAIN", "SMPL", "ON"]
    r.hold(5, 6)                                                    # two held: the first one's
    assert [t[2] for t in r.show()[1::2]] == ["MAIN", "SMPL", "ON"]
    assert not r.stray and not r.locked and not r.edited


def test_a_plain_turn_gets_stocks_pop_up(page):
    """"""
    r = Rig(page, {0: SAMPLER}, index=0, mode=REC)
    r.twist(6, 1)                                                   # MODE on the first page
    assert r.popped == [("MODE", "mode %d" % (REC | STEREO))]       # the record's own name, and the text its knob shows
    r.twist(6, 1)
    assert len(r.popped) == 1                                       # nothing changed: nothing shown
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.twist(3, 1), r.twist(1, 1), r.twist(3, -1), r.twist(1, -1)
    assert r.popped == [("REC", "ON"), ("SRC", "EXT"), ("REC", "OFF"), ("SRC", "MAIN")]
    r = Rig(page, {0: SAMPLER}, index=1, mode=0)
    r.popups = False                                                # where stock shows none, none
    r.twist(3, 1)
    assert r.mode == REC and not r.popped


def test_mode_can_be_locked_and_the_start_up_code_says_so(page, stock3):
    """Stock's own test of a record (+ 140), run as it is on the flags the start-up code gives MODE's."""
    from tools import uitable
    assert uitable.table(stock3)[mm.R_MODE]["flags"] == 4
    r = Rig(page, {0: SAMPLER}, index=1)
    assert r.mc.call(mm.PAGE_LOCKABLE, PAGE, mm.R_MODE) & 0xFF == 1
    r.mc.w32(mm.UI_TABLE + mm.UI_STRIDE * mm.R_MODE, 5)             # a flag that would say no
    assert r.mc.call(mm.PAGE_LOCKABLE, PAGE, mm.R_MODE) & 0xFF == 0
    r.hold(4)                                                       # and then nothing is locked, by stock's own refusal
    r.twist(3, 1)
    assert not r.locks and not r.locked


def test_dest_is_the_pages_own_and_goes_to_the_box_in_words_with_the_marks_last(page):
    r = Rig(page, {0: SAMPLER}, index=1, junk=True)
    assert r.box is None                                            # what the boot left is not a box
    r.show()
    assert r.box == [m.DEST_SMPL] * 8                               # the first look at the page sets it up: every track on SMPL
    for steps, want in ((1, 1), (9, 10), (100, 32), (-1, 31), (-200, 0), (6, 6)):
        assert r.twist(2, steps) == 1 and r.dest == want
    assert r.box == [5] + [m.DEST_SMPL] * 7                         # DEST 06: stereo sample 5 from 0
    assert r.show()[2:4] == [(59, 27, "DEST"), (59, 39, "06")]
    r.told = []
    r.twist(2, 1)
    assert r.told == [(m.REC_DEST, 2, 6)] + [(m.REC_DEST + 2 * t, 2, m.DEST_SMPL) for t in range(1, 8)] + \
        [(m.REC_MARK1, 4, m.REC_MARK), (m.REC_MARK2, 4, m.REC_MARK ^ 0xFFFFFFFF)]
    assert not r.changes and not r.stray                            # and MODE is not touched


def test_each_track_has_its_own_destination(page):
    r = Rig(page, {0: SAMPLER, 3: SAMPLER, 7: SAMPLER}, index=1)
    r.twist(2, 9)
    r.track = 3
    assert r.show()[3] == (59, 39, "SMPL")
    r.twist(2, 30)
    r.track = 7
    r.twist(2, 1)
    assert r.box == [8, m.DEST_SMPL, m.DEST_SMPL, 29, m.DEST_SMPL, m.DEST_SMPL, m.DEST_SMPL, 0]
    r.track = 0
    assert r.show()[3] == (59, 39, "09") and not r.stray


def test_the_other_five_knobs_of_the_page_do_nothing(page):
    r = Rig(page, {0: SAMPLER}, index=1, mode=3)
    r.show()
    r.told = []
    for knob in range(4, 9):
        assert r.twist(knob, 3) == 1
    assert r.mode == 3 and not r.changes and not r.turned and not r.stray and not r.told


@pytest.mark.parametrize("start", range(8))
def test_on_the_first_page_mode_switches_between_mono_and_stereo_and_nothing_else(page, start):
    """MODE's value now holds record and its source too: the stock knob would walk through them."""
    for steps in (1, 4, -1, -3):
        r = Rig(page, {0: SAMPLER}, index=0, mode=start)
        assert r.twist(6, steps) == 1                               # the sixth knob: MODE's place on the sampler's page
        want = start | STEREO if steps > 0 else start & ~STEREO
        assert r.mode == want and r.changes == ([want - start] if want != start else [])
        assert r.redrawn == [PAGE] and not r.turned and not r.stray


def test_on_the_first_page_mode_can_be_locked_to_a_step_too(page):
    r = Rig(page, {0: SAMPLER}, index=0, mode=REC)
    r.hold(0)
    assert r.twist(6, 1) == 1
    assert r.locks == {0: REC | STEREO} and r.mode == REC and not r.changes and not r.popped


def test_the_other_knobs_of_the_first_page_are_stocks(page):
    r = Rig(page, {0: SAMPLER}, index=0, mode=1)
    for knob in (1, 2, 3, 4, 5, 7, 8, 9):
        assert r.twist(knob, 1) == r.turn_answer
    assert r.turned == [(PAGE, EVENT)] * 8 and not r.redrawn and not r.changes and r.mode == 1


@pytest.mark.parametrize("knob_id", [9, 0, 10, 0xFFFFFFFF])
def test_level_and_anything_that_is_not_one_of_the_eight_go_to_stock(page, knob_id):
    for index in (0, 1):
        r = Rig(page, {0: SAMPLER}, index=index)
        assert r.twist(knob_id, 2) == r.turn_answer                 # stock's answer is passed on
        assert r.turned == [(PAGE, EVENT)] and not r.redrawn and not r.changes


@pytest.mark.parametrize("machine", [0, 8, 35])
def test_on_another_machine_every_knob_goes_to_stock(page, machine):
    r = Rig(page, {0: machine}, index=0, mode=1)
    for knob in range(1, 10):
        assert r.twist(knob, 1) == r.turn_answer
    assert r.turned == [(PAGE, EVENT)] * 9 and not r.redrawn and not r.changes and not r.stray


# ---- found on the unit with the build before this one ------------------------------------------------

@pytest.mark.parametrize("index", [0, 1])
def test_level_is_stocks_on_both_pages(page, index):
    """Knob 8 is LEVEL. The build before answered "no record" for it too on the second page: no level shown, no level knob."""
    r = Rig(page, {0: SAMPLER}, index=index)
    assert r.ask(8) == 408 and r.stock == [(PAGE, 8)]
    assert r.pages == 2 and r.index == index


def test_a_turn_comes_in_through_the_second_base(page):
    """The build before changed only the class's own entry, and on the unit the knobs did nothing."""
    r = Rig(page, {0: SAMPLER}, index=1)
    assert r.twist(3, 1) == 1 and r.mode == REC                     # through the second base: ours
    assert r.twist(2, 4, side=False) == 1 and r.dest == 4           # and through the class's own entry, should anything use it
    assert r.twist(9, 1) == r.turn_answer and r.turned == [(PAGE, EVENT)]      # LEVEL: stock gets the object's own address, not the base's
    assert not r.stray


# ---- the words MODE reads on this image ----------------------------------------------------------------

def test_mode_reads_mono_or_stereo_whatever_the_other_two_switches_say(page, stock3):
    """engine/knobtext.c built for this image. The screen image's own tests are in tests/test_screen.py."""
    r = Rig(page, {0: SAMPLER})
    mode_text = mm.UI_TABLE + 0x14 + mm.UI_STRIDE * mm.R_MODE
    def text(value):
        r.mc.call(r.syms["knob_text"], mode_text, value << 8, HEAP + 0xf000)
        return r.cstr(HEAP + 0xf000)
    assert [text(v) for v in range(8)] == ["MONO", "STEREO"] * 4
    assert text(9) == "9"                                           # past the knob's range: the number, as before
    rec = mm.SAMP_RECORDS + 0x34 * 5
    assert int.from_bytes(page[0][mm.off(rec + 0xc):mm.off(rec + 0x10)], "big") == 0x0700      # the knob's range: 0..7


