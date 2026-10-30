"""Phase 3: the real section 7 voice loop in the emulator. Needs the official file."""
import numpy as np
import pytest

from emu import engine as engine_mod
from emu import native
from emu.engine import BLOCK, RATE, Engine
from emu.machine import Machine
from emu.render import pitch, test_pool as make_pool
from tools import audiomap as m
from tools import params

SWARM, TWIN, SD_VINTAGE, TOY = 38, 44, 6, 36


@pytest.fixture(scope="module")
def image(official):
    return official.section(7)


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


def solo(image, descs, mtype, note=60, pool=None, use_native=True):
    """Machine under test on track 0; the rest on Twinshot, which is cheap and silent."""
    if use_native:
        e = Engine(image)
    else:
        real = engine_mod.Machine
        engine_mod.Machine = lambda: real(use_native=False)
        try:
            e = Engine(image)
        finally:
            engine_mod.Machine = real
    if pool:
        e.load_pool(pool)
    for t in range(m.N_VOICES):
        e.set_defaults(t, mtype if t == 0 else TWIN, descs)
        e.set_note(t, note)
    return e


def knob(descs, mtype, short):
    return next(p.slot for p in descs[mtype] if p.short == short)


def test_descriptors_match_what_the_code_reads(descs):
    assert sorted(descs) == sorted(m.TYPE_OF_ENGINE)
    sdv = {p.short: (p.slot, p.min, p.max, p.default) for p in descs[SD_VINTAGE]}
    # as published in Modded-Cycles note 16 for OS 1.41
    assert sdv == {"TUNE": (18, 40, 88, 64), "INHM": (19, 0, 127, 0), "FCMP": (20, 0, 127, 110),
                   "SWEP": (21, 0, 127, 74), "MENV": (22, 0, 127, 80), "PNCH": (23, 0, 1, 0),
                   "DEC": (25, 0, 127, 33), "OVER": (26, 0, 127, 0)}
    twin = {p.short: (p.slot, p.default) for p in descs[TWIN]}
    assert twin == {"TUN1": (18, 64), "SMP1": (19, 64), "FLT1": (20, 64), "MIX": (21, 64),
                    "TUN2": (22, 64), "SMP2": (23, 65), "DEC1": (25, 127), "OVER": (26, 0)}
    for ps in descs.values():
        assert {p.slot for p in ps} <= set(range(18, 27))


def test_python_boot_matches_the_real_boot_code(image):
    mc = Machine()
    mc.map(0x40000000, 0x100000)
    mc.map(m.SRAM, m.SRAM_END - m.SRAM)
    mc.write(m.BASE, image)
    mc.set_stack(0x400ff000, 0x40000100)
    mc.call(0x400004bc)
    real = mc.read(m.SRAM, m.SRAM_END - m.SRAM)
    e = Engine.__new__(Engine)
    e.image, e.mc = bytes(image), Machine()
    e.mc.map(0x40000000, 0x100000)
    e.mc.map(m.SRAM, m.SRAM_END - m.SRAM)
    e.mc.write(m.BASE, image)
    e._boot()
    assert e.mc.read(m.SRAM, m.SRAM_END - m.SRAM) == real
    assert not any(e.mc.read(m.BSS[0], m.IMAGE_END - m.BSS[0]))


def test_all_emac_sites_taken_over(image):
    e = Engine(image)
    assert len(e.mc.emac_sites) == 839


@pytest.mark.parametrize("mtype", [SWARM, 7, TWIN])
def test_native_hook_is_bit_identical_to_the_python_model(image, descs, mtype):
    if native.lib() is None:
        pytest.skip("no host compiler")
    out = []
    for use_native in (True, False):
        e = solo(image, descs, mtype, pool=make_pool(), use_native=use_native)
        x = e.render(6, trig=0x01)
        out.append((x, e.mc.emac.acc, e.mc.emac.macsr, e.mc.insns, e.mc.emac_ops))
    assert np.array_equal(out[0][0], out[1][0])
    assert out[0][1:] == out[1][1:]
    assert out[0][0][0].any()


def test_render_is_deterministic(image, descs):
    a = solo(image, descs, SD_VINTAGE).render(30, trig=0x01)
    b = solo(image, descs, SD_VINTAGE).render(30, trig=0x01)
    assert np.array_equal(a, b)


@pytest.mark.parametrize("mtype", m.TYPE_OF_ENGINE)
def test_every_stock_machine_sounds_and_emac_never_overflows(image, descs, mtype):
    e = solo(image, descs, mtype, pool=make_pool())
    x = e.render(40, trig=0x01)
    assert not x[0, :BLOCK].any()             # the note starts on the block after the trig
    assert x[0, BLOCK:].any()
    assert not x[1:].any()                    # untrigged tracks stay silent
    assert e.mc.emac.overflows == 0           # the unverified 48-bit saturation path never ran
    assert e.mc.emac.macsr & 0xF0 == 0x20     # MACSR as the loop leaves it


@pytest.mark.parametrize("note,hz", [(60, 261.63), (72, 523.25), (48, 130.81)])
def test_pitch_follows_the_note(image, descs, note, hz):
    x = solo(image, descs, TOY, note=note).render(260, trig=0x01)[0]
    assert pitch(x[BLOCK:BLOCK + 8192]) == pytest.approx(hz, rel=0.003)


def test_sd_vintage_agrees_with_published_measurements(image, descs):
    """Modded-Cycles note 16 measured the body at 133 / 264 / 529 Hz for notes 48 / 60 / 72."""
    for note, hz in ((48, 133), (60, 264), (72, 529)):
        x = solo(image, descs, SD_VINTAGE, note=note).render(200, trig=0x01)[0]
        assert pitch(x[2048:2048 + 4096]) == pytest.approx(hz, abs=3)


def test_twinshot_plays_the_pool_one_to_one(image, descs):
    pool = make_pool()
    e = solo(image, descs, TWIN, pool=pool)
    e.set_slot(0, knob(descs, TWIN, "MIX"), 0)            # sample 1 only
    x = e.render(40, trig=0x01)[0].astype(np.int64)
    a = e.player(0, 0)
    assert (a["inc"], a["len"] >> 12, a["playing"], a["reverse"]) == (4096, len(pool[0]), 1, 0)
    assert a["ptr"] == m.POOL + 4
    s = pool[0].astype(np.int64)
    y, ref = x[BLOCK + 1:BLOCK + 801], s[1:801]
    gain = np.dot(y, ref) / np.dot(ref, ref)
    assert gain == pytest.approx(2 ** 15, rel=0.002)       # int16 << 16, times the mix gain 0.5
    assert np.std(y - gain * ref) < 0.01 * np.std(y)


@pytest.mark.parametrize("note,inc", [(60, 4096), (72, 8192), (48, 2047), (67, 6136)])
def test_twinshot_pitch_increment(image, descs, note, inc):
    e = solo(image, descs, TWIN, note=note, pool=make_pool())
    e.render(3, trig=0x01)
    assert e.player(0, 0)["inc"] == inc


def test_twinshot_mix_and_sample_select(image, descs):
    def level(mix, hz):
        e = solo(image, descs, TWIN, pool=make_pool())
        e.set_slot(0, knob(descs, TWIN, "MIX"), mix)
        x = e.render(80, trig=0x01)[0][64:64 + 2048].astype(float)
        s = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        return s[int(round(hz * len(x) / RATE))]
    assert level(0, 1000) > 1e4 * level(0, 250)            # slot 0 only
    assert level(127, 250) > 1e4 * level(127, 1000)        # slot 1 only
    assert level(64, 1000) == pytest.approx(level(64, 250), rel=0.1)


def test_twinshot_reverse(image, descs):
    ramp = {0: (np.arange(3000) * 8).astype(np.int16)}     # rising ramp: direction is visible

    def run(smp1):
        e = solo(image, descs, TWIN, pool=ramp)
        e.set_slot(0, knob(descs, TWIN, "MIX"), 0)
        e.set_slot(0, knob(descs, TWIN, "SMP1"), smp1)
        x = e.render(30, trig=0x01)[0].astype(float)
        return x[BLOCK + 200:BLOCK + 700], e.player(0, 0)["reverse"]
    fwd, f_flag = run(64)
    rev, r_flag = run(63)
    assert (f_flag, r_flag) == (0, 1)
    assert np.polyfit(np.arange(500), fwd, 1)[0] > 0 > np.polyfit(np.arange(500), rev, 1)[0]


def test_instruction_budget(image, descs):
    """Steady-state instructions per 32-frame block, machine on all 8 tracks, all trigged."""
    steady = {}
    for mtype in m.TYPE_OF_ENGINE:
        e = Engine(image)
        if mtype == TWIN:
            e.load_pool(make_pool())
        for t in range(m.N_VOICES):
            e.set_defaults(t, mtype, descs)
            e.set_note(t, 60)
        counts = []
        for b in range(24):
            before = e.mc.insns
            e.block(0xFF if b == 0 else 0)
            counts.append(e.mc.insns - before)
        steady[mtype] = max(counts[3:])
        if mtype == SWARM:
            assert counts[1] == 93436                     # machine change and note-on, 8 voices
    assert max(steady, key=steady.get) == SWARM
    assert steady[SWARM] == 84044
    assert steady[TWIN] == 31060
