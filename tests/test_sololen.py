"""The sololen image: a solo lock, trig or trigless, digital or analog, held for its step's LEN."""
import shutil

import pytest

import test_firstrec as F
import test_once as O
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ON, OFF = 0x3580, 0x1a40  # the solo's two marks, in the high byte
TEMPO = 14400  # 120 BPM, BPM x 120 a block
TRACK_LEN = mm.TRIG_LEN_OWN


@pytest.fixture(scope="module")
def main(official):
    assert official.version == "1.42"
    return build_main.patched_image(official.section(3), xfade=83)


@pytest.fixture(scope="module")
def table(official):
    s, at = official.section(3), mm.LEN_TABLE - mm.BASE + 4
    return [int.from_bytes(s[at + 4 * k:at + 4 * k + 4], "big") for k in range(128)]


def rig(main, track, machines=None):
    r = O.page(main, track=track, machines=machines)
    for lo in (mm.SEQ_STATE & ~0xfff, mm.SEQ_PLACES & ~0xfff, mm.PATTERN_DATA & ~0xfff):
        try:
            r.mc.map(lo, 0x1000)
        except Exception:
            pass
    for t in range(13):
        r.mc.write(mm.SEQ_PLACES + 80 * t, bytes(80))
    for lo in range(O.DATA & ~0xfff, O.DATA + 1177 * 12 + 0x1000, 0x1000):  # the trig settings, under the lock table
        try:
            r.mc.map(lo, 0x1000)
        except Exception:
            pass
    r.mc.w32(mm.PATTERN_DATA, O.DATA)
    r.mc.w32(mm.TEMPO, TEMPO)
    r.mc.w32(mm.SOLO_GONE, 0xfff)
    for t in range(12):
        lens(r, t, own=0xff, track_len=14)
    return r


def lens(r, t, step=None, own=0xff, track_len=None):
    at = O.DATA + 1177 * t
    if step is None:
        r.mc.write(at + 192, bytes([own]) * 64)
    else:
        r.mc.write(at + 192 + step, bytes([own]))
    if track_len is not None:
        r.mc.write(at + TRACK_LEN, bytes([track_len]))


def slot(track):
    return 17 if track < 8 else 26


def left(r):
    raw = bytes(r.mc.read(r.syms["solo_left"], 48))
    return [int.from_bytes(raw[4 * t:4 * t + 4], "big") for t in range(12)]


def pend(r):
    raw = bytes(r.mc.read(r.syms["solo_pend"], 48))
    return [int.from_bytes(raw[4 * t:4 * t + 4], "big") for t in range(12)]


def bits(r, name):
    return r.mc.r32(r.syms[name] if name in r.syms else name)


def gone(r):
    return r.mc.r32(mm.SOLO_GONE)


def tick(r, n=1):
    for _ in range(n):
        r.mc.call(r.syms["solo_tick"])


@pytest.mark.parametrize("track, word", [(0, ON), (5, OFF), (7, ON), (8, ON), (11, OFF)])
@pytest.mark.parametrize("own", [0xff, 3, 30])
def test_a_solo_lock_is_held_for_its_steps_len_then_passed_over(main, table, track, word, own):
    r = rig(main, track)
    step = 6
    lens(r, track, step, own=own, track_len=14)
    r.lay(step, word, slot=slot(track))
    assert (slot(track), word) in F.play(r, step, 0, track)
    length = table[14 if own == 0xff else own]
    assert left(r) == [length if t == track else 0 for t in range(12)]
    assert bits(r, "solo_run") == 1 << track and gone(r) == 0xfff & ~(1 << track)
    blocks = -(-length // TEMPO)
    tick(r, blocks - 1)
    assert gone(r) == 0xfff & ~(1 << track) and left(r)[track] == length - (blocks - 1) * TEMPO
    tick(r)
    assert gone(r) == 0xfff and left(r) == [0] * 12 and bits(r, "solo_run") == 0


def test_len_inf_holds_it(main, table):
    r = rig(main, 2)
    assert table[127] == 0
    lens(r, 2, 4, own=127)
    r.lay(4, ON, slot=17)
    F.play(r, 4, 0, 2)
    tick(r, 500)
    assert gone(r) == 0xfff & ~(1 << 2) and left(r) == [0] * 12 and bits(r, "solo_run") == 0


def test_the_next_solo_step_starts_the_count_again_and_another_track_counts_on_its_own(main, table):
    r = rig(main, 3)
    for step in (0, 1):
        r.lay(step, ON, slot=17)
    r.lay(0, OFF, slot=26, track=9)
    F.play(r, 0, 0, 3)
    F.play(r, 0, 0, 9)
    tick(r, 100)
    F.play(r, 1, 0, 3)  # the same mark a step on: still a new count
    assert left(r)[3] == table[14] and left(r)[9] == table[14] - 100 * TEMPO
    tick(r, 88)
    assert gone(r) >> 9 & 1 and not gone(r) >> 3 & 1
    tick(r, 100)
    assert gone(r) == 0xfff


@pytest.mark.parametrize("case", ["no solo lock", "not a sampler", "a mark of no solo", "the FX track"])
def test_a_step_with_no_solo_lock_leaves_it_all(main, case):
    track = {"not a sampler": 1, "the FX track": 12}.get(case, 4)
    r = rig(main, track, machines={1: O.OTHER} if case == "not a sampler" else None)
    if case == "no solo lock":
        r.lay(2, O.ON)  # REC's lock, slot 24
    else:
        r.lay(2, 0x4400 if case == "a mark of no solo" else ON, slot=17)
    F.play(r, 2, 0, track)
    assert left(r) == [0] * 12 and bits(r, "solo_run") == 0 and gone(r) == 0xfff


def test_a_start_counts_the_step_it_queues(main, table):
    r = rig(main, 6)
    lens(r, 6, 0, own=5)
    r.lay(0, ON, slot=17)
    r.lay(0, ON, slot=26, track=10)
    F.play(r, 0, F.place(6), 6)  # STOP's pass: nothing counts yet
    F.play(r, 0, F.place(10), 10)
    assert left(r) == [0] * 12 and gone(r) == 0xfff
    assert pend(r)[6] == table[5] and pend(r)[10] == table[14] and bits(r, "solo_pmask") == 1 << 6 | 1 << 10
    F.play(r, 3, F.place(10), 10)  # a listener's pass over a step with no locks
    assert bits(r, "solo_pmask") == 1 << 6
    F.start(r, [])
    assert left(r) == [table[5] if t == 6 else 0 for t in range(12)]
    assert bits(r, "solo_run") == 1 << 6 and gone(r) == 0xfff & ~(1 << 6)


def test_a_block_with_nothing_counting_costs_two(main):
    r = rig(main, 0)
    assert r.counted(lambda: tick(r))[1] <= 4


def test_the_image(official_path, main):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=83)[2]
    was = build.build(official_path, log=quiet, xfade=82)[2]
    assert new.section(7) == was.section(7) and new.section(3) == main[0]
    n, o = new.section(3), was.section(3)
    spans = [mm.CAVE_ONCE, mm.CAVE_LONG, mm.CAVE_HITS, mm.CAVE_SOLOLEN, (mm.STEP_LOCKS_PUSH, mm.STEP_LOCKS_PUSH + 6),
             (mm.STEP_NO_LOCKS, mm.STEP_NO_LOCKS + 4), (mm.MAIN_LOOP_WAIT, mm.MAIN_LOOP_WAIT + 6),
             (mm.FILTER_ENV_CALL + 2, mm.FILTER_ENV_CALL + 6), (mm.FLTR2_NAME, mm.FLTR2_NAME + 28), mm.CAVE_TRANS] + [(a, a + 6) for a in mm.SEQ_STARTS]
    assert [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not any(lo <= mm.BASE + k < hi for lo, hi in spans)] == []
    hits = n[mm.CAVE_HITS[0] - mm.BASE:mm.CAVE_HITS[1] - mm.BASE]
    assert bytes.fromhex("4eb9") + main[1]["solo_tick"].to_bytes(4, "big") in hits or main[1]["solo_tick"].to_bytes(4, "big") in hits
