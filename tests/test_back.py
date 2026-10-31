"""The back image (engine/stub.S, BACK): the atrig image with SY SWARM, SY TOY, SY BITS and SD BASIC back as stock's."""

import shutil

import numpy as np
import pytest

import test_norm as N
import test_pagerec as P
import test_slim as S
from emu.engine import Engine
from emu.machine import Machine
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TOY, BITS, SWARM, SD_BASIC = 36, 37, 38, 1
RUNS = (m.SRR_CAVES["d"], m.HITS_CAVES["e"], m.SCAN_CAVES["g"])


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def norm(stock):
    return build_engine.patched_image(stock, norm=True)


@pytest.fixture(scope="module")
def back(stock):
    return build_engine.patched_image(stock, back=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def test_their_runs_and_engines_are_stocks(stock, back):
    b = back[0]
    for lo, hi in RUNS:
        assert b[m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
    for engine in (m.SDB_ENGINE, m.TOY_ENGINE, m.BITS_ENGINE, m.SWARM_ENGINE):
        for t in (m.UPDATE_TABLE, m.RENDER_TABLE):
            assert m.u32(b, t + 4 * engine) == m.u32(stock, t + 4 * engine)


def test_the_start_calls_far_load_and_it_calls_stocks_two(stock, back):
    b, syms = back
    at = m.off(m.START_CALLS)
    assert stock[at:at + 8] == bytes.fromhex(fw.sx("313de459f85fa891d09dc73e"))
    assert b[at:at + 8] == b"\x4e\xb9" + syms["far_load"].to_bytes(4, "big") + b"\x4e\x71"
    f = m.off(syms["far_load"])
    assert b[f:f + 6] == bytes.fromhex("4eb9400004bc")
    assert b[f + 8:f + 14] == bytes.fromhex("4ef940000512")
    assert m.FAR >= m.REC_BASE + 65 * m.REC_STRIDE and m.FAR + m.FAR_BYTES <= m.STACK_TOP - 0x100000 and not m.BSS[0] <= m.FAR < m.BSS[1]


def test_the_copy_puts_the_far_code_where_it_is_linked(stock, back):
    b, syms = back
    assert len(b) == len(stock) + m.FAR_BYTES and m.BASE + len(stock) == m.IMAGE_END
    mc = Machine()
    mc.map(0x40000000, m.STACK_TOP - 0x40000000)
    mc.write(m.BASE, b)
    mc.set_stack(m.STACK_TOP - 0x100, 0x40000000)
    mc.call(syms["far_copy"])
    assert mc.read(m.FAR, m.FAR_BYTES) == b[len(stock):]
    for name, (lo, hi) in m.BACK_CAVES.items():
        assert any(lo <= a < hi for a in syms.values()), name


@pytest.mark.parametrize("case", [dict(note=55.25), dict(note=62.0, mono=True), dict(note=58.5, back=True, length=90)])
def test_the_sound_and_hits_are_norms(norm, back, official, case):
    factory = S.factory.__wrapped__(official)
    a = S.render(norm[0], factory, blocks=200, **case)
    b = S.render(back[0], factory, blocks=200, **case)
    assert np.array_equal(a[1], b[1]) and np.array_equal(a[2], b[2]) and a[1].any()


def test_srr_is_norms(norm, back, official):
    factory = S.factory.__wrapped__(official)
    outs = []
    for image in (norm, back):
        r = Rig(image[0])
        rng = np.random.default_rng(5)
        r.load_pool({k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
        S.T.samplers(r, factory, loop=1)
        for t in range(8):
            r.set_slot(t, SAMPLE, 64 + t % 3)
            r.set_slot(t, START, 0)
            r.set_slot(t, LENGTH, 127)
            r.set_slot(t, 23, 20 + 13 * t)  # SRR, MODE's slot
            r.set_note(t, 60)
        r.block(0, 0)
        outs.append(np.concatenate([r.block(0xff if k == 0 else 0, 0)[2] for k in range(60)], axis=1))
    assert np.array_equal(*outs) and outs[0].any()


def test_a_normalized_take_is_norms(official_path, back):
    _, _, was, _, wsyms = build.build(official_path, log=lambda s: None, xfade=50)
    got = []
    for built in ((was.section(7), wsyms), back):
        e = N.rec(built, 2, 5)
        k, n, _ = N.take(e, built, 2, N.sine(20, 800, 3))
        N.settle(e, built, n // N.STEP + 2)
        got.append((n, N.taken(e, k, n).copy(), N.taken(e, k + 1, n).copy()))
    assert got[0][0] == got[1][0] and np.array_equal(got[0][1], got[1][1]) and np.array_equal(got[0][2], got[1][2])


@pytest.mark.parametrize("machine", [SWARM, TOY, BITS, SD_BASIC])
def test_a_restored_machine_plays_as_on_stock(stock, back, machine):
    """Stock's voice loop on each image: the machine's code, its table entries and the routines it shares."""
    outs = []
    for e in (Engine(stock), Engine(back[0])):
        for t in range(8):
            e.set_machine(t, machine)
            e.set_note(t, 48 + 5 * t)
            for s in range(17, 27):
                e.set_slot(t, s, 40 + 7 * (s - 17))
        rows = [e.block(0xff if b == 0 else 0, 0) for b in range(40)]
        outs.append(np.concatenate(rows, axis=1))
    assert np.array_equal(*outs) and outs[0].any()


def test_the_image(official_path, back):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=52, prof=True)
    _, _, was, _, _ = build.build(official_path, log=quiet, xfade=51, prof=True)
    assert built.section(3) == was.section(3) and built.section(7) == back[0]
