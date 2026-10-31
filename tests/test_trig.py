"""The trig image."""
import shutil

import numpy as np
import pytest

import test_apage as A
import test_gear as G
import test_hits as H
import test_xfade as X
from test_page import PAGE
from test_reclock import REC_KNOB
from test_soloknob import SOLO_KNOB
from tools import build, build_engine, build_main, uitable
from tools import audiomap as m
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

E, F = 5, 6  # the TRIG page's knobs, as a turn names them
HOLDER = 3


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=23)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, xfade=22)


# ---- the first page
# -------------------------------------------------------------------------------------------------

def test_strt_and_loop_len_and_srr_change_places_and_nothing_else_of_the_pages(main, before):
    new, old = uitable.pages(main[0]), uitable.pages(before[0])
    assert old[-1]["knobs"] == [497, 498, 499, 504, 501, 502, 500, 503]
    assert new[-1]["knobs"] == [497, 498, 501, 504, 499, 500, 502, 503]  # C LOOP, E STRT, F LEN, G SRR
    assert {k: v for k, v in new.items() if k != -1} == {k: v for k, v in old.items() if k != -1} and new[-1]["level"] == old[-1]["level"]
    rec = mm.SAMP_RECORDS
    assert main[0][mm.off(rec):mm.off(rec + 8 * 0x34)] == before[0][mm.off(rec):mm.off(rec + 8 * 0x34)]


# ---- the TRIG page
# --------------------------------------------------------------------------------------------------

def trig(built, track):
    """The page rig with the TRIG class's three methods and its turn going to ours, and TRIG's own played."""
    r = A.page(built, track)
    r.syms = dict(r.syms, syn_knob=built[1]["trig_knob"], syn_draw=built[1]["trig_draw"])
    r.entry = built[1]["trig_turn_side"], built[1]["trig_turn"]
    r.trig_stock = []
    r.stub(mm.TRIG_KNOB, lambda obj, knob: r.trig_stock.append(("knob", knob)) or 600 + knob)
    r.stub(mm.TRIG_DRAW, lambda obj, surface: r.trig_stock.append(("draw", obj)) or 0)
    r.stub(mm.TRIG_TURN, lambda obj, event: r.trig_stock.append(("turn", r.mc.r32(event + mm.EVENT_ID))) or 0x66)
    r.mc.uc.ctl_flush_tb()
    G.geared(r, [256, 256, -256, -256] * 4)
    return r


@pytest.mark.parametrize("track", [0, 5, 7])
def test_on_a_sampler_e_and_f_have_no_record_and_the_rest_are_stocks(main, track):
    r = trig(main, track)
    assert [r.ask(k) for k in range(8)] == [600, 601, 602, 603, 0, 0, 606, 607]
    assert r.trig_stock == [("knob", k) for k in (0, 1, 2, 3, 6, 7)]


@pytest.mark.parametrize("track", [9, 11])
def test_on_an_analog_track_every_knob_is_stocks(main, track):
    r = trig(main, track)
    assert [r.ask(k) for k in range(8)] == [600 + k for k in range(8)]
    r.show()
    assert r.texts == [] and r.trig_stock[-1] == ("draw", PAGE)
    for k in range(1, 9):
        assert G.twist(r, k, 1) == 0x66
    assert [t for t in r.trig_stock if t[0] == "turn"] == [("turn", k) for k in range(1, 9)]


def test_the_page_draws_stocks_then_solo_and_rec_in_the_fifth_and_sixth_places(main):
    r = trig(main, 2)
    texts = r.show()
    assert r.trig_stock == [("draw", PAGE)] and r.order == ["text"] * 4  # stock's first, then ours
    assert texts == [(33, 0, ""), (33, 12, "S OFF"), (59, 0, "REC"), (59, 12, "OFF")]


def test_e_is_the_solo_and_f_is_rec_and_the_rest_go_to_stock(main):
    track = 4
    r = trig(main, track)
    for k in (1, 2, 3, 4, 7, 8):
        assert G.twist(r, k, 1) == 0x66
    assert [t for t in r.trig_stock if t[0] == "turn"] == [("turn", k) for k in (1, 2, 3, 4, 7, 8)]
    calls = G.geared(r, [256, -256, 256, -256])
    G.twist(r, E, 1)
    assert int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") == 1 << track and "SOLO" in [t[2] for t in r.show()]
    G.twist(r, E, -1)
    assert int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") == 0
    G.twist(r, F, 1)
    assert G.own(r, track) == mm.SRR_SIG | 1
    assert (59, 12, "ON") in r.show()
    G.twist(r, F, -1)
    assert G.own(r, track) == mm.SRR_SIG
    assert [c[1:4] for c in calls] == [(4, 1, mm.FEEL_PLAIN), (4, -1, mm.FEEL_PLAIN), (5, 1, mm.FEEL_PICKER), (5, -1, mm.FEEL_PICKER)]


def scene(r, knob, held, answers):
    """Turns of one knob with steps held, on a rig. -> what was locked and what the track's own say after."""
    G.geared(r, list(answers))
    r.hold(*held)
    for _ in answers:
        G.twist(r, knob, 1)
    return list(r.locked), int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big"), G.own(r, 1)


@pytest.mark.parametrize("held", [(), (0,), (3, 9)])
@pytest.mark.parametrize("answers", [(256,), (256, -256), (256, 256, 256), (-256,)])
def test_solo_and_rec_lock_as_the_phone_images_sampling_page_did(main, before, held, answers):
    assert scene(trig(main, 1), E, held, answers) == scene(A.page(before, 1), SOLO_KNOB, held, answers)
    assert scene(trig(main, 1), F, held, answers) == scene(A.page(before, 1), REC_KNOB, held, answers)


def test_the_sampling_pages_fifth_place_is_empty_and_its_knob_turns_nothing(main, before):
    r, old = A.page(main, 2), A.page(before, 2)
    G.geared(r, [256, 256])  # knob E still goes through stock's change, as every knob of the page
    G.geared(old, [256, 256])
    assert [t for t in r.show() if t[0] != 33] == [t for t in old.show() if t[0] != 33]
    assert [t for t in r.show() if t[0] == 33 and t[1] < 20] == []
    G.twist(r, SOLO_KNOB, 1)
    assert int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big") == 0
    assert G.twist(r, REC_KNOB, 1) == 1 and G.own(r, 2) == mm.SRR_SIG | 1  # REC stays


# ---- the crossfade through a global mute
# ----------------------------------------------------------------------------

def rig(built):
    r = X.Rig(*built, entry="mix_amute")
    r.mc.map(0x7fffd000, 0x3000)
    return r


@pytest.fixture(scope="module")
def mix(main):
    return rig(main)


@pytest.fixture(scope="module")
def old(before):
    return rig(before)


def xf_at(t, x):
    return [x if k == t else 0 for k in range(12)]


@pytest.mark.parametrize("x", [1, 40, 127])
@pytest.mark.parametrize("holder", [0, HOLDER, 7])
def test_a_globally_muted_digital_holder_comes_in_with_its_crossfade(mix, old, holder, x):
    xf = xf_at(holder, x)
    shown, levels, vols, was = X.mixed(mix, xf=xf, mutes=1 << holder)
    want, want_levels = X.law(vols, was, xf)
    want[holder] = vols[holder] * x // 127
    assert shown == want and levels == want_levels
    a, b = X.mixed(mix, xf=xf, mutes=1 << holder | 1 << 5), X.mixed(old, xf=xf, mutes=1 << holder | 1 << 5)
    assert a[0][5] == 0 == b[0][5] and a[0][holder] == want[holder] and b[0][holder] == 0  # another muted track stays muted


@pytest.mark.parametrize("holder", [8, 10])
def test_a_globally_muted_analog_holder_comes_in_with_its_crossfade_squared(mix, holder):
    x = 90
    shown, levels, vols, was = X.mixed(mix, xf=xf_at(holder, x), mutes=1 << holder)
    v = holder - 8
    assert levels[v] == was[v] * x * x >> 14 and levels[v + 4] == was[v + 4] * x * x >> 14
    assert shown[holder] == vols[holder] * x // 127


@pytest.mark.parametrize("state", [dict(pattern=1 << HOLDER), dict(knob=1 << 6), dict()])
def test_a_pattern_mute_a_solo_or_no_mute_is_the_phone_images_mixer(mix, old, state):
    xf = xf_at(HOLDER, 64)
    mutes = 1 << HOLDER if state else 0
    assert X.mixed(mix, xf=xf, mutes=mutes, **state) == X.mixed(old, xf=xf, mutes=mutes, **state)


def test_with_no_crossfade_it_is_the_phone_images_mixer(mix, old):
    rng = np.random.default_rng(23)
    for k in range(12):
        state = dict(mutes=int(rng.integers(0, 0x2000)), pattern=int(rng.integers(0, 0x2000)), knob=int(rng.integers(0, 0x100)) if k % 3 == 0 else 0)
        assert X.mixed(mix, seed=k, xf=[0] * 12, **state) == X.mixed(old, seed=k, xf=[0] * 12, **state)


# ---- the hits' steps
# ------------------------------------------------------------------------------------------------

def loud(p):
    s, t = 0, 925
    while s < 15 and p > t:
        s, t = s + 1, t + (t * 33 >> 7)
    return s


def test_the_steps_are_2_db_from_minus_31_to_minus_3():
    t, ts = 925, []
    for _ in range(15):
        ts.append(t)
        t += t * 33 >> 7
    db = 20 * np.log10(np.array(ts) / 32768)
    assert round(db[0]) == -31 and round(db[-1]) == -3 and np.allclose(np.diff(db), 2, atol=0.02)


def test_the_scan_keeps_the_models_hits_by_the_new_steps(official, monkeypatch):
    monkeypatch.setattr(H, "loud", loud)
    built = build_engine.patched_image(official.section(7), curve=True)
    x = H.drums()
    e = H.P.engine(built, pool={0: x, 1: x})
    for _ in range(2 * (H.SR // 128 + 2) + 8):
        e.mc.call(built[1]["hits_block"])
    got, done = H.kept(e, 0)
    assert done == len(x) and got == H.model(x)
    monkeypatch.undo()
    print("trig: the drums' steps", [s for _, s, _ in got], "where the hits image's were", [s for _, s, _ in H.model(x)])


# ---- the image
# ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=23)
    was = build.build(official_path, log=quiet, xfade=22)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] and len(new) == len(old)
    for method, name in ((mm.PAGE_KNOB_METHOD, "trig_knob"), (mm.PAGE_DRAW_METHOD, "trig_draw"), (mm.PAGE_TURN_METHOD, "trig_turn")):
        assert mm.u32(new, mm.TRIG_CLASS + method) == syms[name]
    assert mm.u32(new, mm.TRIG_SIDE + mm.SYN_SIDE_TURN) == syms["trig_turn_side"]
    assert all(mm.CAVE_TRIG[0] <= syms[s] < mm.CAVE_TRIG[1] for s in ("trig_knob", "trig_draw", "trig_turn_side"))
    assert mm.CAVE_TRIG2[0] <= syms["trig_turn"] < mm.CAVE_TRIG2[1]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_PROF, mm.CAVE_METER, mm.CAVE_REC,
             (mm.MIX_CALL + 2, mm.MIX_CALL + 6),  # the recorder feed's code moved: the analog mute grew, the profile's run holds its helper
             (mm.TRIG_CLASS, mm.TRIG_CLASS + 0x100), (mm.TRIG_SIDE + 8, mm.TRIG_SIDE + 12)] + [(a + 2, a + 6) for a, *_ in build_main.FIRST_SWAP]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    a7, b7 = built.section(7), was.section(7)
    hits = [v for v in m.HITS_CAVES.values()]
    stray7 = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in hits)]
    assert stray7 == [] and a7 != b7
    print("trig image", __import__("hashlib").sha256(raw).hexdigest())
