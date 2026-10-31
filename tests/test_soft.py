"""The soft image: the prof image with a note that starts on a loud frame faded in.

worse with
one source than with several. A take begins wherever its source was, and a note at STRT 0 began on its first frame at
once. A note whose first frame is past SOFT_MIN, on either side, is faded in over FADE_IN frames, as a note that
starts inside the sample always was (engine/sampler.c, soft).

Held here: a sample that begins near nothing sounds as it does on the srr image's engine, to the bit; one that begins
loud comes up from nothing over 64 frames and is the srr image's sound from there on; a loud right side alone is
enough; the limit itself; and the image differs from the prof image only in SY SWARM's room and the sampler's runs.

Not held, and only the unit can show it: that the click is gone by the maintainer's ear, and that a hit is not dulled.
"""
import hashlib
import shutil

import numpy as np
import pytest

import test_pack as PK
import test_pagerec as P
import test_srr as S
from emu.engine import BLOCK
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SOFT_MIN, FADE_IN = 128, 64


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def soft(stock):
    return build_engine.patched_image(stock, soft=True)


@pytest.fixture(scope="module")
def srr(stock):
    return build_engine.patched_image(stock, srr=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def pool(left, right):
    """A stereo sample in the first place whose two sides begin with the frames given."""
    rng = np.random.default_rng(7)
    l, r = (rng.integers(-30000, 30000, 6000).astype(np.int16) for _ in range(2))
    l[0], r[0] = left, right
    return {0: l, 1: r}


def played(built, left, right):
    """One note on the first track at STRT 0, six blocks. -> the track's two sides from the note's first block on."""
    e = P.engine(built, pool=pool(left, right))
    e.set_slot(0, P.SAMPLE, PK.knob_of(0))
    e.set_slot(0, P.MODE, 0)
    e.set_slot(0, P.TUNE, 64)
    out = []
    for b in range(6):
        rows = e.block(1 if b == 0 else 0, 0)
        out.append(np.stack([rows[0], S.right(e, 0)]).astype(np.int64))
    out = np.concatenate(out, axis=1)
    return out


def start(sound):
    return int(np.flatnonzero(np.abs(sound).sum(axis=0))[0]) // BLOCK * BLOCK


@pytest.mark.parametrize("left, right", [(0, 0), (SOFT_MIN, -SOFT_MIN), (-90, 17)])
def test_a_sample_that_begins_near_nothing_is_not_touched(soft, srr, left, right):
    assert np.array_equal(played(soft, left, right), played(srr, left, right))


@pytest.mark.parametrize("left, right", [(20000, 15000), (-20000, 0), (0, 9000), (SOFT_MIN + 1, 0), (0, -SOFT_MIN - 1)])
def test_a_sample_that_begins_loud_comes_up_from_nothing(soft, srr, left, right):
    was, now = played(srr, 20000, 15000), played(soft, left, right)
    plain = played(srr, left, right)
    at = start(plain)
    assert np.array_equal(now[:, :at], plain[:, :at])
    assert np.array_equal(now[:, at + FADE_IN:], plain[:, at + FADE_IN:]) and now[:, at + FADE_IN:].any()
    ramp, full = now[:, at:at + FADE_IN], plain[:, at:at + FADE_IN]
    assert not ramp[:, 0].any()                                 # from nothing
    assert (np.abs(ramp) <= np.abs(full)).all() and (np.abs(ramp[:, 1:]) < np.abs(full[:, 1:]))[full[:, 1:] != 0].all()
    big = np.abs(full) > 1 << 20                                # where there is enough to say how much: a line, a 64th a frame
    gain = ramp[big] / full[big]
    line = np.broadcast_to(np.arange(FADE_IN) / FADE_IN, full.shape)[big]
    assert np.allclose(gain, line, atol=0.002)
    assert was.shape == now.shape


def test_the_image(official_path, official, soft, srr):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=12)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=11)
    assert hashlib.sha256(was_raw).hexdigest().startswith("f0a8d804")      # the prof image is still itself
    assert built.section(3) == was.section(3)                               # the main CPU's program is the prof image's
    seven, last = built.section(7), was.section(7)
    assert seven == soft[0] != last == srr[0] and len(seven) == len(last)
    runs = [r for caves in (m.CAVES, m.REC_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.PITCH_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                            m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES) for r in caves.values()]
    tables = [(t + 4 * m.SWARM_ENGINE, t + 4 * m.SWARM_ENGINE + 8) for t in (m.UPDATE_TABLE, m.RENDER_TABLE)]
    assert not [k for k in range(len(seven)) if seven[k] != last[k] and not any(m.off(a) <= k < m.off(b) for a, b in runs + tables)]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
