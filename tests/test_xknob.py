"""The xknob image: the box image with the crossfade on the first page's knob D, in DEC's place and on its slot.

On request


.

On slot 25 the crossfade is kept with the pattern's kit, locks to a step and takes an LFO, as DEC did. It is stored
upside down, 127 less the slot's value, so a track made before (DEC at 127, stock's default) has none. The analog mute
reads it every block (engine/amute.c, XKNOB) into the eight numbers the mixer link and itself go by; the sampler no
longer reads DEC, a note always holds; a turn of D goes to stock's routine the other way round and takes the other
sampler tracks' crossfades and the analog tracks' away; D reads XF0 to XF127 and its picture is drawn again the right
way up. The sampling page's knob G is empty.

Held here by running the routines. Not held: that the kit is kept slot for slot with the pattern (the srr image's REC
word, kept the same way, is his evidence), how D's picture looks, how the knob feels turned the other way round.
"""
import shutil

import numpy as np
import pytest

import test_apage as A
import test_gear as G
import test_mainpatch as M
import test_pagerec as P
import test_xfade as X
from test_page import EVENT, HEAP, PAGE, SURFACE
from tools import build, build_engine, build_main
from tools import audiomap as m
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

DEC, D, G_KNOB = 25, 4, 7                           # the slot; knob D and knob G as a turn names them
ARC, BLIT, R_DEC = 0x400701b4, 0x400f8f70, 504
STRIDE, KNOBS = 142, 28
TOP = 127


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=26)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, xfade=25)


# ---- the mixer: the crossfade from slot 25 ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mix(main):
    r = X.Rig(*main, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    return r


@pytest.fixture(scope="module")
def old(before):
    r = X.Rig(*before, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    return r


def mixed(rig, decs, machines=X.MACHINES, seed=6, xf=None, **state):
    """One mixer call with each digital track's slot 25 at decs[t]. -> (the volumes the mixer is shown, the analog
    level words as sent, the twelve numbers after, the volumes and level words as they were)."""
    block, level2 = M.make_block(machines, [0] * 12, seed=seed)
    block = bytearray(block)
    for t, d in enumerate(decs):
        block[STRIDE * t + KNOBS + 2 * DEC:STRIDE * t + KNOBS + 2 * DEC + 2] = (d << 8).to_bytes(2, "big")
    block = bytes(block)
    was = np.random.default_rng(seed + 6).integers(1, 256, M.CONTROL_BYTES, dtype=np.uint8).tobytes()
    rig.mc.write(mm.CONTROL, was)
    rig.mc.write(mm.XFADES, bytes(xf or [0] * 12))
    ret, after, _ = rig.run(block, level2, **state)
    assert ret == 0x8000DBD0 and after == block
    words = lambda b: [int.from_bytes(b[2 * k:2 * k + 2], "big") for k in range(10)]
    got = bytes(rig.mc.read(mm.CONTROL, M.CONTROL_BYTES))
    return (M.vols(rig.seen["params"]), [words(got)[k] for k in X.LEVELS], list(rig.mc.read(mm.XFADES, 12)),
            M.vols(block), [words(was)[k] for k in X.LEVELS])


@pytest.mark.parametrize("x", [1, 64, 127])
@pytest.mark.parametrize("holder", [0, 5])
def test_a_tracks_slot_25_is_its_crossfade_upside_down(mix, holder, x):
    decs = [TOP] * 8
    decs[holder] = TOP - x
    shown, levels, xf, vols, was = mixed(mix, decs)
    assert xf == [x if t == holder else 0 for t in range(8)] + [0] * 4
    assert (shown, levels) == X.law(vols, was, xf)


def test_an_old_project_dec_at_127_everywhere_has_no_crossfade(mix, old):
    a = mixed(mix, [TOP] * 8)
    assert a[2] == [0] * 12 and a[0] == a[3]
    b = mixed(old, [TOP] * 8)
    assert a[:2] == b[:2]                                       # the box image's mixer with no crossfade


def test_a_track_that_is_no_sampler_has_none_whatever_its_slot_holds(mix):
    machines = list(X.MACHINES)
    machines[2] = 3
    assert mixed(mix, [0] * 8, machines=machines)[2][2] == 0


def test_the_analog_tracks_numbers_are_theirs(mix):
    shown, levels, xf, vols, was = mixed(mix, [TOP] * 8, xf=[0] * 9 + [70, 0, 0])
    assert xf[9] == 70 and (shown, levels) == X.law(vols, was, xf)


# ---- the sampler: DEC no longer read ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), xknob=True)


@pytest.mark.parametrize("dec", [0, 30, 127])
def test_a_note_always_holds(engine, dec):
    e = P.engine(engine, pool={0: (np.arange(9600) % 300 * 50).astype(np.int16)})
    e.set_slot(0, P.SAMPLE, 64)
    e.set_slot(0, DEC, dec)
    for b in range(3):
        e.block(1 if b == 0 else 0, 0)
    assert e.mc.r32(e.voice(0) + 4 * 252) == 0x80000000


# ---- the first page's knob D --------------------------------------------------------------------------------------------

def kit_dec(r, t):
    return int.from_bytes(r.mc.read(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * DEC, 2), "big")


def first(built, track, machines=None):
    r = A.page(built, track, index=0)
    if machines:
        r.machines = machines
    G.geared(r)
    for t in range(8):
        r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * DEC, (40 << 8).to_bytes(2, "big"))
    r.seen_steps = []
    r.stub(mm.SYN_TURN, lambda obj, event: r.seen_steps.append(r.mc.r32(event + mm.EVENT_STEPS)) or 0x77)
    r.arcs, r.blits = [], []
    r.stub(ARC, lambda obj, value, surface, x, y: r.arcs.append((value, x, y)) or 0)
    r.stub(BLIT, lambda surface, pic, x, y, mode: r.blits.append((pic, x, y)) or 0)
    r.mc.uc.ctl_flush_tb()
    return r


def test_d_turns_stock_s_way_the_other_way_round_and_takes_the_others_away(main):
    track = 2
    machines = {t: 44 for t in range(8)}
    machines[6] = 3                                             # a track on another machine: its slot 25 is its own knob
    r = first(main, track, machines)
    r.mc.write(mm.XFADES + 8, bytes([0, 50, 0, 0]))
    assert G.twist(r, D, 5) == 0x77 and r.seen_steps == [-5 & 0xffffffff]
    assert [kit_dec(r, t) for t in range(8)] == [TOP << 8 if t not in (track, 6) else 40 << 8 for t in range(8)]
    assert list(r.mc.read(mm.XFADES + 8, 4)) == [0, 0, 0, 0]
    assert r.mc.r32(EVENT + mm.EVENT_STEPS) == 5                # the event as it came
    for k in (1, 3, 5, 6, 7, 8):
        G.twist(r, k, 1)
    assert r.seen_steps[1:] == [1] * 6                          # every other knob of the page as stock has it (SMPL, B, is the stops image's)


def test_d_is_drawn_the_right_way_up_over_an_eraser(main):
    r = first(main, 1)
    r.value = lambda holder, record: (100 << 8) if record == R_DEC else r.mode << 8
    r.show()
    assert r.blits == [(mm.CAVE_TRIG4[0] + 28, 102, 34)] and r.arcs == [((TOP - 100) << 8, 102, 34)]
    lo = mm.CAVE_TRIG4[0] + 28
    assert main[0][mm.off(lo):mm.off(lo) + 24] == bytes(4) + (19).to_bytes(4, "big") + (17).to_bytes(4, "big") + bytes(4) + \
        (lo - 4).to_bytes(4, "big") + mm.DOTTED_MASK.to_bytes(4, "big")


def test_off_a_sampler_the_first_page_is_stocks(main):
    r = first(main, 9)
    r.show()
    assert r.arcs == [] and r.blits == []
    G.twist(r, D, 3)
    assert r.seen_steps == [3]


@pytest.mark.parametrize("dec,text", [(127, "XF0"), (126, "XF1"), (27, "XF100"), (0, "XF127")])
def test_d_reads_xf_and_the_crossfade(main, dec, text):
    image, syms = main
    mc = X.Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(HEAP, 0x10000)
    mc.write(mm.BASE, image)
    mc.set_stack(HEAP + 0x8000, 0x40000100)
    obj = 0x41ba0a38 + 84 * R_DEC
    mc.map(obj & ~0xfff, 0x2000)
    mc.call(syms["knob_text"], obj, dec << 8, HEAP + 0x100)
    raw = bytes(mc.read(HEAP + 0x100, 8))
    assert raw[:raw.index(0)].decode() == text


def test_d_is_named_xfade(main):
    image = main[0]
    rec = mm.SAMP_RECORDS + 0x34 * 7
    name = lambda field: (lambda a: image[mm.off(a):image.index(b"\0", mm.off(a))].decode())(mm.u32(image, rec + field))
    assert (name(0x30), name(0x28)) == ("XFADE", "Crossfade") and mm.u32(image, rec + 4) == DEC


# ---- the sampling page and the analog tracks' page --------------------------------------------------------------------

def test_the_sampling_pages_g_is_empty(main):
    r = A.page(main, 3)
    G.geared(r, [256])
    texts = r.show()
    assert not [t for t in texts if t[0] == 85 and t[1] in (0, 12) and t[2]]     # knob G's place, the lower row
    assert G.twist(r, G_KNOB, 4) == 1 and list(r.mc.read(mm.XFADES, 8)) == [0] * 8


def test_an_analog_tracks_crossfade_takes_the_samplers_away(main):
    r = A.page(main, 10)
    r.machines = {t: 44 for t in range(8)}
    r.machines.update({t: t for t in range(8, 12)})
    G.geared(r)
    for t in range(8):
        r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * DEC, (20 << 8).to_bytes(2, "big"))
    G.twist(r, G_KNOB, 30)
    assert A.xf12(r)[10] == 30 and [kit_dec(r, t) for t in range(8)] == [TOP << 8] * 8


# ---- the image ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=26)
    was = build.build(official_path, log=quiet, xfade=25)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    rec = mm.SAMP_RECORDS + 0x34 * 7
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3, mm.CAVE_TRIG4, mm.CAVE_XKNOB, mm.CAVE_XKNOB2,
             mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_PROF, mm.CAVE_TEXT, (mm.MIX_CALL + 2, mm.MIX_CALL + 6), (mm.TRIG_MUTE + 2, mm.TRIG_MUTE + 6),
             (mm.TRIG_CLASS, mm.TRIG_CLASS + 0x100), (mm.TRIG_SIDE + 8, mm.TRIG_SIDE + 12), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100),
             (mm.SYN_SIDE + 8, mm.SYN_SIDE + 12), (mm.SYN_BUILD, mm.SYN_BUILD + 0x20), (rec + 0x28, rec + 0x34),
             (0x40194444, 0x40194448), (0x40194456, 0x4019445a), (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6)]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    a7, b7 = built.section(7), was.section(7)
    diff7 = [k for k in range(len(a7)) if a7[k] != b7[k]]
    assert diff7 and len(diff7) < 600                           # the sampler's update: DEC not read; its run's code moved up
    print("xknob image", __import__("hashlib").sha256(raw).hexdigest(), "section 7 bytes changed", len(diff7))
