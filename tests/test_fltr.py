"""The fltr image: the xshare image with LFO.T and FLT.T on FLTR2's G and H, and the phone's load query."""
import shutil

import pytest

import test_phone as P
import test_trig as T
from test_page import HEAP, PAGE
from test_rpc import case_of
from tools import build, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

NUMBERS = HEAP + 0xa000  # the object's page numbers: FLTR1, FLTR2
LFO_T, FLT_T = 28, 27


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=28)


@pytest.fixture(scope="module")
def xshare(official):
    return build_main.patched_image(official.section(3), xfade=27)


def fltr(built, track, index=1):
    """The page rig with the filter class's + 188 going to ours, the filter's own played, and the object's pages FLTR1
    and FLTR2 with the one at index showing.
    """
    r = T.A.page(built, track, index=index)
    r.syms = dict(r.syms, syn_knob=built[1]["fltr_knob"])
    mc = r.mc
    mc.w32(NUMBERS, 9)
    mc.w32(NUMBERS + 4, 10)
    mc.w32(PAGE + mm.PAGE_LIST, NUMBERS)
    mc.w32(PAGE + mm.PAGE_LIST_END, NUMBERS + 8)
    r.stock = []
    r.stub(mm.FILTER_KNOB, lambda obj, knob: r.stock.append(knob) or 600 + knob)
    mc.uc.ctl_flush_tb()
    return r


# ---- FLTR2
# ----------------------------------------------------------------------------------------------------------

def test_the_two_records_are_lfo_t_and_flt_t(official):
    d, B = official.section(3), mm.BASE
    names = []
    for rec in (LFO_T, FLT_T):
        at = int.from_bytes(d[mm.off(0x4022d83c + 52 * rec + 0x30):][:4], "big")
        names.append(d[mm.off(at):mm.off(at) + 6].split(b"\0")[0].decode())
    assert names == ["LFO.T", "FLT.T"]


@pytest.mark.parametrize("track", [0, 5, 7])
def test_on_a_sampler_fltr2s_g_and_h_are_lfo_t_and_flt_t_and_the_rest_are_stocks(main, track):
    r = fltr(main, track)
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 604, 605, LFO_T, FLT_T]
    assert r.stock == list(range(6))


@pytest.mark.parametrize("track,index", [(2, 0), (9, 1), (11, 0), (10, 1)])
def test_fltr1_and_an_analog_track_are_stocks_in_every_place(main, track, index):
    r = fltr(main, track, index)
    assert [r.ask(k) for k in range(8)] == [600 + k for k in range(8)]


def test_the_trig_page_turns_them_by_the_base_turn_the_filter_page_has(official):
    d = official.section(3)
    at = lambda a, n: d[mm.off(a):mm.off(a) + n].hex()
    assert at(0x400415ec, 6) == fw.sx("863eafcc325360596c01")  # the TRIG page's turn: page 3 only is its own
    assert at(0x4004166e, 10) == fw.sx("ecd7a3f5ae621d2dce0ec806a20b")  # the rest go to the base turn
    assert int.from_bytes(d[mm.off(mm.FILTER_CLASS + mm.PAGE_TURN_METHOD):][:4], "big") == mm.FILTER_TURN == 0x4003b870


def test_only_the_filter_class_s_188_is_ours_and_the_trig_page_is_the_xshare_images(official, main, xshare):
    stock = official.section(3)
    for o in range(0, 0x100, 4):
        a = mm.off(mm.FILTER_CLASS + o)
        want = main[1]["fltr_knob"].to_bytes(4, "big") if o == mm.PAGE_KNOB_METHOD else stock[a:a + 4]
        assert main[0][a:a + 4] == want
    for a in (mm.FILTER_SIDE + mm.SYN_SIDE_TURN, mm.TRIG_SIDE + mm.SYN_SIDE_TURN) + tuple(mm.TRIG_CLASS + o for o in range(0, 0x100, 4)):
        assert main[0][mm.off(a):mm.off(a) + 4] == xshare[0][mm.off(a):mm.off(a) + 4]


@pytest.mark.parametrize("which", ["stock", "fltr"])
def test_fltr2_draws_flt_t_and_lfo_t_as_their_own_picture_as_fenr_and_every_other_record_as_stock(official, main, which):
    """FLTR2's loop from its test of BASE (0x400423e4) on: to 0x400424c2 the record's own picture (the last argument 0),
    to 0x400423f0 a knob's (1). Run as it is, with the record in d2.
    """
    from emu.machine import Machine
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_PC

    image = official.section(3) if which == "stock" else main[0]
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.write(mm.BASE, image)
    mc.map(0x41000000, 0x10000)
    mc.set_exits([0x400423f0, 0x400424c2])
    seen = {}
    for rec in range(0, 0x100):
        mc.uc.reg_write(UC_M68K_REG_D2, rec)
        mc.uc.reg_write(UC_M68K_REG_A7, 0x41008000)
        mc.uc.emu_start(0x400423e4, 0, count=40)
        seen[rec] = (mc.uc.reg_read(UC_M68K_REG_PC), mc.uc.reg_read(UC_M68K_REG_D1))
    own = sorted(r for r, (pc, _) in seen.items() if pc == 0x400424c2)
    assert own == ([LFO_T - 1, LFO_T] if which == "fltr" else []) + [0x3f, 0x45, 0x89, 0x8e]
    assert all(pc in (0x400423f0, 0x400424c2) for pc, _ in seen.values())
    assert all(d1 == 69 for r, (_, d1) in seen.items() if 0x3f < r < 0x46 or r in (LFO_T - 1, LFO_T) and which == "fltr")


def test_the_sampling_page_shows_the_audio_cpus_peak_in_its_last_place_again(main, xshare):
    r, old = T.A.page(main, 2), T.A.page(xshare, 2)
    for q in (r, old):
        q.mc.map(0x80003000, 0x1000)  # the kit, which knob D's text reads (0x800030b8, 291 bytes a track)
    r.mc.write(0x100005b4, b"\x00\x00\x00\x00" + b"P085")
    new, was = r.show(), old.show()
    extra = [t for t in new if t not in was]
    assert [t for t in was if t not in new] == []
    assert [t[0] for t in extra] == [111, 111] and extra[0][2] == "" and len(extra[1][2]) == 4 and extra[1][2][1:].isdigit()


# ---- the load query
# -------------------------------------------------------------------------------------------------

def test_0x63_and_0x64_go_nowhere_in_stocks_parser(official):
    assert case_of(official.section(3), 0x63) == mm.RPC_NONE and case_of(official.section(3), 0x64) == mm.RPC_NONE


def reply(project, bank, n, b):
    return bytes([0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x64, project & 0x7f, project >> 7, 0, bank,
                  n & 0x7f, (n >> 7) & 0x7f, (n >> 14) & 0x7f, b & 0x7f, (b >> 7) & 0x7f, (b >> 14) & 0x7f, 0xf7])


MANAGER_OF, PROJECT_NOW = 0x4016e9c8, 0x40018c2c


def rig(built, now_project=-1, **kw):
    """test_phone's rig with stock's manager and its project's number played: the number the unit came up with."""
    r = P.Rig(built, **kw)
    r.asked = []
    r.stub(MANAGER_OF, lambda: r.asked.append("manager") or P.RAM + 0x900)
    r.stub(PROJECT_NOW, lambda m: r.asked.append(("project", m)) or now_project & 0xffffffff)
    r.mc.uc.ctl_flush_tb()
    return r


def ask(r, iface=2):
    data, n = r.frame(0x63, 0, 6)
    r.log.clear()
    r.mc.call(r.syms["knows_sysex"], data, n, iface)
    return data, n


def test_before_any_load_the_answer_is_no_project_and_the_start_is_the_timers_low_21_bits(main):
    r = rig(main)
    r.mc.w32(P.CLOCK, 0x12345678)
    ask(r)
    assert r.log == [("write", reply(0x3fff, 0, 0, 0x145678)), ("commit",)]
    r.mc.w32(P.CLOCK, 0x9abcdef0)
    ask(r)
    assert r.log[0] == ("write", reply(0x3fff, 0, 0, 0x145678))  # the same through the run


@pytest.mark.parametrize("project,bank", [(4, 2), (0, 0), (127, 1)])
def test_before_any_load_the_answer_is_the_project_the_unit_started_with_and_the_drives_bank(main, project, bank):
    r = rig(main, now_project=project, now=bank)
    r.mc.w32(P.CLOCK, 99)
    ask(r)
    assert r.log == [("write", reply(project, bank, 0, 99)), ("commit",)]
    assert r.asked == ["manager", ("project", P.RAM + 0x900)]


def test_a_start_at_a_timer_of_0_is_not_taken_for_none(main):
    r = rig(main)
    r.mc.w32(P.CLOCK, 0x00200000)
    ask(r)
    assert r.log[0] == ("write", reply(0x3fff, 0, 0, 1))


def test_every_load_counts_a_phone_there_or_not_and_goes_on_as_the_phone_image(main):
    r = rig(main, now_project=9, project_bank=2, now=0)
    r.mc.w32(P.SINK_MADE, 0)
    assert r.mc.call(r.syms["knows_load"], 0x1234, 5, 0x5678) == 7
    assert r.log == [("load", 0, 0x1234, 5, 0x5678)]  # no phone: stock's load straight away
    r.mc.w32(P.SINK_MADE, 1)
    r.log.clear()
    assert r.mc.call(r.syms["knows_load"], 0x1234, 5, 0x5678) == 7
    assert [e[0] for e in r.log] == ["scan", "write", "commit", "timer", "wait", "cancel", "scan", "load"]
    assert r.log[1][1] == bytes([0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x60, 5, 0, 0, 2, 0xf7])
    r.mc.w32(P.CLOCK, 0x1fffff)
    ask(r)
    assert r.log[0][1][12:19] == bytes([5, 0, 0, 2, 2, 0, 0])  # project 5, bank 2, two loads
    assert r.asked == []  # once a load is counted, the start-up's is not asked


def test_the_count_and_a_big_project_take_their_7_bit_bytes(main):
    r = rig(main)
    r.mc.w32(P.CLOCK, 7)
    r.mc.w32(r.syms["knows_count"], 300000)
    r.mc.w32(r.syms["knows_project"], 200)
    r.mc.w32(r.syms["knows_bank"], 1)
    ask(r)
    assert r.log == [("write", reply(200, 1, 300000, 7)), ("commit",)]


def test_with_no_sink_yet_0x63_goes_to_stock_and_nothing_is_written(main):
    r = rig(main)
    r.mc.w32(P.SINK_MADE, 0)
    data, n = ask(r, 4)
    assert r.log == [("handle", data, n, 4)]


def test_every_other_frame_goes_on_to_the_phone_images_entry(main):
    r = P.Rig(main)
    r.mc.w32(r.syms["phone_state"], 1)
    data, n = r.frame(0x61, 1 << 9)
    r.mc.call(r.syms["knows_sysex"], data, n, 2)
    assert r.log == [("give",)] and r.var("phone_mask") == 1 << 9
    data, n = r.frame(0x53, 0, 12)
    r.log.clear()
    r.mc.call(r.syms["knows_sysex"], data, n, 4)
    assert r.log == [("handle", data, n, 4)]
    data, n = r.frame(0x6, 0, 5)  # too short to be ours
    r.log.clear()
    r.mc.call(r.syms["knows_sysex"], data, n, 2)
    assert r.log == [("handle", data, n, 2)]


# ---- the image
# ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=28, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=27, prof=True)
    assert __import__("hashlib").sha256(was_raw).hexdigest().startswith("6d2c2faa")  # the xshare image, as it is
    new, old = built.section(3), was.section(3)
    assert new == main[0] and built.section(7) == was.section(7)
    spans = [mm.CAVE_FLTR, mm.CAVE_PHONE3, (mm.FILTER_CLASS + mm.PAGE_KNOB_METHOD, mm.FILTER_CLASS + mm.PAGE_KNOB_METHOD + 4),
             (mm.FLTR2_FLAT, mm.FLTR2_FLAT + 12), mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6,
             mm.CAVE_PAGE7, mm.CAVE_PAGE8, mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3, mm.CAVE_XKNOB,
             mm.CAVE_XKNOB2, mm.CAVE_XSHARE,
             (mm.SYSEX_IN_JMP + 2, mm.SYSEX_IN_JMP + 6), (mm.PROJECT_LOAD_CALL + 2, mm.PROJECT_LOAD_CALL + 6)]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    assert new[mm.off(mm.SYSEX_IN_JMP + 2):mm.off(mm.SYSEX_IN_JMP + 6)] == syms["knows_sysex"].to_bytes(4, "big")
    assert new[mm.off(mm.PROJECT_LOAD_CALL + 2):mm.off(mm.PROJECT_LOAD_CALL + 6)] == syms["knows_load"].to_bytes(4, "big")
    print("fltr image", __import__("hashlib").sha256(raw).hexdigest())
