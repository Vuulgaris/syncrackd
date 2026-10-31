"""The tail image: the pre image with a one-shot faded out before its far end wherever that is."""
import hashlib
import shutil

import numpy as np
import pytest

import test_pack as PK
import test_pagerec as P
import test_srr as S
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

FADE_OUT, FRAMES, BLOCKS = 128, 1500, 52


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def tail(stock):
    return build_engine.patched_image(stock, tail=True)


@pytest.fixture(scope="module")
def soft(stock):
    return build_engine.patched_image(stock, soft=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def played(built, length=127, loop=0):
    """One note of a loud stereo sample of 1,500 frames. -> the track's two sides."""
    rng = np.random.default_rng(11)
    e = P.engine(built, pool={0: rng.integers(-30000, 30000, FRAMES).astype(np.int16), 1: rng.integers(-30000, 30000, FRAMES).astype(np.int16)})
    e.set_slot(0, P.SAMPLE, PK.knob_of(0))
    e.set_slot(0, P.MODE, 0)
    e.set_slot(0, P.TUNE, 64)
    e.set_slot(0, P.LENGTH, length)
    e.set_slot(0, 22, loop)  # LOOP: knob slot 22
    out = []
    for b in range(BLOCKS):
        rows = e.block(1 if b == 0 else 0, 0)
        out.append(np.stack([rows[0], S.right(e, 0)]).astype(np.int64))
    return np.concatenate(out, axis=1)


def test_a_one_shot_at_full_length_goes_down_to_nothing_before_its_end(tail, soft):
    was, now = played(soft), played(tail)
    end = int(np.flatnonzero(np.abs(was).sum(axis=0))[-1]) + 1  # the frame after the sample's last
    assert np.abs(was[:, end - 1]).max() > 1 << 20  # the soft image stops on a loud frame
    assert not was[:, end:].any() and not now[:, end:].any()
    assert np.array_equal(now[:, :end - FADE_OUT - 1], was[:, :end - FADE_OUT - 1])
    down, full = now[:, end - FADE_OUT:end], was[:, end - FADE_OUT:end]
    assert (np.abs(down) <= np.abs(full)).all() and not np.array_equal(down, full)
    big = np.abs(full) > 1 << 20
    gain = np.where(big, down / np.where(full == 0, 1, full), np.nan)
    line = np.nanmean(gain, axis=0)
    assert line[0] > 0.95 and line[-1] < 0.03 and (np.diff(line[~np.isnan(line)]) < 0.001).all()  # a line down, to a 128th or less


def test_with_len_short_of_all_and_in_a_loop_it_is_the_soft_images(tail, soft):
    assert np.array_equal(played(tail, length=100), played(soft, length=100))
    assert np.array_equal(played(tail, loop=1), played(soft, loop=1))


def test_the_image(official_path, official, tail, soft):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=14)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=13)
    assert hashlib.sha256(was_raw).hexdigest().startswith("ddb8ae7a")  # the pre image, as it is
    assert built.section(3) == was.section(3)
    seven, last = built.section(7), was.section(7)
    assert seven == tail[0] != last == soft[0] and len(seven) == len(last)
    runs = [r for caves in (m.CAVES, m.REC_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.PITCH_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                            m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES) for r in caves.values()]
    assert not [k for k in range(len(seven)) if seven[k] != last[k] and not any(m.off(a) <= k < m.off(b) for a, b in runs)]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
