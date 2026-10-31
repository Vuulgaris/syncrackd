"""The scan image: the xcarry image with the hits found another way, in SD BASIC's room.



for the room.

A window is looked at by its loudest frame and its loudest step from one frame to the next, each with its own follower;
a hit is either past its follower by half again, by more than 42 dB under the slot's loudest; its step is its place
among the slot's hits by how sharp it is (engine/sampler.h, HITSCAN). Held here: the engine keeps the model's hits to
the frame, the step and the end; a quiet take has a loud one's hits; hats over a held bass are found (the switch
image's scan, run here too, does not find them); a held low note is one hit; DEL takes the hits in even shares.
Not held: how it sounds, and where the slices land by the maintainer's ear.
"""
import hashlib
import shutil

import numpy as np
import pytest

import test_hits as H
import test_switch as S
from tools import audiomap as m
from tools import build, build_engine

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SR = 48000


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), peak=True, scan=True)


@pytest.fixture(scope="module")
def switch(official):
    return build_engine.patched_image(official.section(7), peak=True)


def sharp(r):
    if r < 4:
        return r
    e = 2
    while r >> (e + 1):
        e += 1
    return 4 * e - 4 + (r >> (e - 2) & 3)


def model(x):
    """The scan as sampler.h has it: [(frame, step, end)]."""
    x = x.astype(np.int64)
    n = len(x)
    a, d = np.abs(x), np.abs(np.diff(x, prepend=0))
    peak, dpk = int(a.max()), int(d.max())
    least = max(peak >> 7, 8)
    env = envd = base = based = top = fall = 0
    gap, hits, bins = 32, [], []
    for i in range(0, n, 32):
        p, pd = int(a[i:i + 32].max()), int(d[i:i + 32].max())
        pd = pd * peak // dpk if dpk else 0
        if gap < 32:
            gap += 1
            if gap <= 3:
                bins[-1] = max(bins[-1], sharp(max(p - base if p > base else 0, pd - based if pd > based else 0)))
        elif len(hits) < 121:
            r = max(p - (env >> 8) if p << 8 > env + (env >> 1) else 0, pd - (envd >> 8) if pd << 8 > envd + (envd >> 1) else 0)
            if r > least:
                bins.append(sharp(r))
                hits.append([i, 0, i])
                base, based, top, fall, gap = env >> 8, envd >> 8, p, p, 0
        if top:
            fall -= fall >> 4
            fall, top = max(fall, p), max(top, p)
            if p >= top >> 4:
                at = min(i + 32, n)
                hits[-1][2] = hits[-1][0] + min((at - hits[-1][0] + 31) // 32, 0x3fff) * 32
            elif fall < top >> 4:
                top = 0
        env = max(env - (env >> 7), p << 8)
        envd = max(envd - (envd >> 7), pd << 8)
    above = [sum(c > b for c in bins) for b in bins]
    return [(f, 15 - k * 15 // len(hits), e) for (f, _, e), k in zip(hits, above)]


def hats_over_bass(seconds=1.0, seed=2):
    """A bass at -6 dB held the whole second, a hat at -20 dB every quarter."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = 16000 * np.sin(2 * np.pi * 50 * t)
    at = list(range(SR // 8, len(x), SR // 4))
    for k in at:
        j = np.arange(1200)
        x[k:k + 1200] += 3000 * np.exp(-j / 200) * rng.standard_normal(1200)
    return np.clip(x, -32768, 32767).astype(np.int16), at


def clicks(n=30):
    """n clicks over silence, each a dB quieter than the one before, a tenth of a second apart."""
    x = np.zeros(SR * 3 + 4800)
    j = np.arange(480)
    for i in range(n):
        x[4800 + i * 4800:4800 + i * 4800 + 480] = 20000 * 10 ** (-i / 20) * np.exp(-j / 60) * np.sin(2 * np.pi * 3000 * j / SR)
    return x.astype(np.int16)


@pytest.mark.parametrize("which", ["drums", "quiet", "static", "clicks"])
def test_the_scan_keeps_the_models_hits(engine, which):
    x = {"drums": lambda: H.drums(), "quiet": lambda: (H.drums() * 0.03).astype(np.int16),
         "static": lambda: hats_over_bass()[0], "clicks": clicks}[which]()
    got, done = S.scanned(engine, x)
    assert done == len(x) and got == model(x) and got
    print("scan, %s:" % which, len(got), "hits, steps", [s for _, s, _ in got])


@pytest.mark.parametrize("gain", [0.03, 0.01])                    # -30 and -40 dB
def test_a_quiet_take_has_a_loud_ones_hits(engine, gain):
    x = H.drums()
    loud = S.scanned(engine, x)[0]
    quiet = S.scanned(engine, (x.astype(np.float64) * gain).astype(np.int16))[0]
    assert [f for f, _, _ in quiet] == [f for f, _, _ in loud]


def test_hats_over_a_held_bass_are_found(engine, switch):
    x, at = hats_over_bass()
    got = [f for f, _, _ in S.scanned(engine, x)[0]]
    assert got[0] == 0 and all(any(0 <= k - f < 64 or 0 <= f - k < 64 for f in got) for k in at)
    assert len(got) == len(at) + 1                              # the bass's start and each hat, nothing else
    old = [f for f, _, _ in S.scanned(switch, x)[0]]
    assert len(old) <= 2                                        # the switch image's scan: the start, a hat at most
    print("scan: hats over a bass, found", len(got) - 1, "of", len(at), "where the switch image found", len(old) - 1)


@pytest.mark.parametrize("hz", [20, 30, 55])
def test_a_held_low_note_is_one_hit(engine, hz):
    x = (20000 * np.sin(2 * np.pi * hz * np.arange(SR) / SR)).astype(np.int16)
    assert [f for f, _, _ in S.scanned(engine, x)[0]] == [0]


def test_del_takes_the_hits_in_even_shares(engine):
    got = S.scanned(engine, clicks())[0]
    steps = [s for _, s, _ in got]
    assert len(got) == 30 and steps[0] == 15 and min(steps) >= 1
    assert all(a >= b for a, b in zip(steps, steps[1:]))       # louder clicks, sharper rises: never a lower step first
    passed = [sum(s >= 15 - ((dl - 1) * 15 >> 7) for s in steps) for dl in range(1, 128)]
    assert passed[0] <= 2 and passed[-1] == 30 and 12 <= passed[63] <= 18
    print("scan: hits DEL lets through at 1, 32, 64, 96, 127:", [passed[d - 1] for d in (1, 32, 64, 96, 127)])


def test_the_image(official_path, engine):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=46, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=45, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("e9fdaa32")      # the xcarry image, as it is
    assert built.section(3) == was.section(3)
    a7, b7 = built.section(7), was.section(7)
    assert a7 == engine[0]
    runs = [r for n, v in vars(m).items() if n.endswith("CAVES") for r in v.values()]
    table = [(t + 4 * m.SDB_ENGINE, t + 4 * m.SDB_ENGINE + 4) for t in (m.UPDATE_TABLE, m.RENDER_TABLE)]
    stray = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs + table)]
    assert stray == []
    for t in (m.UPDATE_TABLE, m.RENDER_TABLE):                  # a track on SD BASIC is handed SWARM's stand-ins
        assert m.u32(a7, t + 4 * m.SDB_ENGINE) == m.u32(a7, t + 4 * m.SWARM_ENGINE) != m.u32(b7, t + 4 * m.SDB_ENGINE)
    print("scan image", hashlib.sha256(raw).hexdigest())
