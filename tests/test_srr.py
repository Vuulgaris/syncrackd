"""The srr image: the multi image with sample rate reduction, in MODE's parameter, which is freed for it.

The sound: every frame the player makes is held until a phase runs over (engine/stub.S, crush; the model is
emu/sampler_ref.py, Hold). The knob is MODE's record, a plain 0 to 127 again in the first page's sixth place.

What MODE held: a sampler track's REC and SRC are the track's own word on knob slot 24, signed. The main CPU's
per-block routine (engine/recword.S) reads it in the kit, makes it from an old pattern's MODE, and leaves in slot 24
of the block that is sent the mark of what the track is to do and its source under it. The audio CPU and the feed read
that and nothing of MODE.

SY SWARM's code is the room, and a track left on it plays nothing.

Held here: the hold is the model's, frame for frame, both sides by one phase, a note's start and a turn to 0 setting
the phase; with the knob at 0 the sound is the multi image's to the bit; a take is made by the mark alone; a track on
SY SWARM is silent and the tracks beside it are not touched; what the hold costs the interrupt; the per-block routine,
every case; the feed by the word that routine leaves; and both programs differ from the multi image only in their
declared places, the multi image still its own hash.

Not held, and only the unit can show it: that the kit the sound engine's side reads is what a pattern's save writes
(SRC after a save and a power cycle); that MODE's record is offered as an LFO's destination; what P reads.
"""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_feed as F
import test_multi as M
import test_pack as PK
import test_pagerec as P
from emu import sampler_ref as ref
from emu.engine import BLOCK, RET
from emu.machine import Machine
from test_meter import ALL
from test_quick import Folded
from test_recorder import STRIDE, frames, junk, make_block
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ON, OFF = 0x52, 0x29                    # REC's two marks, a step's lock and what the per-block routine leaves
SIG = mm.SRR_SIG
SWARM = 38


def signed(src, rec):
    return SIG | src << 8 | rec


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def srr(stock):
    return build_engine.patched_image(stock, srr=True)


@pytest.fixture(scope="module")
def multi(stock):
    return build_engine.patched_image(stock, multi=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=8)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def pool():
    """Eight stereo samples in the first eight places, and a mono one in a single slot."""
    rng = np.random.default_rng(1)
    out = {k: rng.integers(-30000, 30000, 6000).astype(np.int16) for k in range(16)}
    out[40] = rng.integers(-30000, 30000, 5001).astype(np.int16)
    return out


def right(e, t):
    return np.frombuffer(bytes(e.mc.read(m.STASH + 4 * BLOCK * t, 4 * BLOCK)), dtype=">i4").astype(np.int32)


# ---- the audio CPU: the hold ------------------------------------------------------------------------------------------

def longs(e, at):
    return np.frombuffer(bytes(e.mc.read(at, 4 * BLOCK)), dtype=">i4").astype(np.int64)


def held(built, knobs, place=0, track=0):
    """A note on one track, a knob value a block. -> [(block, what the hold was handed, what it left)]."""
    image, syms = built
    e = P.engine(built, pool=pool())
    e.set_slot(track, P.SAMPLE, PK.knob_of(place))
    calls, now = [], [0]
    last = syms["swarm_update"] - 2                 # the hold's rts

    def enter(uc, address, size, user):
        sp = e.mc.reg(15)
        h, l, r = (e.mc.r32(sp + 4 * k) for k in (1, 2, 3))
        calls.append({"block": now[0], "h": h, "l": l, "r": r, "step": e.mc.r32(h), "phase": e.mc.r32(h + 4),
                      "in": (longs(e, l), longs(e, r) if r else None)})

    def leave(uc, address, size, user):
        c = calls[-1]
        c["out"] = (longs(e, c["l"]), longs(e, c["r"]) if c["r"] else None)
        c["after"] = [e.mc.r32(c["h"] + 4 * k) for k in (1, 2, 3)]

    e.mc.uc.hook_add(UC_HOOK_CODE, enter, begin=syms["crush"], end=syms["crush"])
    e.mc.uc.hook_add(UC_HOOK_CODE, leave, begin=last, end=last)
    e.mc.uc.ctl_flush_tb()
    for b, k in enumerate(knobs):
        now[0] = b
        e.set_slot(track, P.MODE, k)
        e.block(1 << track if b == 0 else 0, 0)
    return calls


def word(knob):
    return int(round(knob * 256)) & 0xffff


@pytest.mark.parametrize("place, knobs", [
    (0, [1] * 8), (0, [16] * 8), (0, [16.5] * 8), (0, [33] * 8), (0, [64] * 8), (0, [100] * 8), (0, [127] * 8),
    (0, [127.996] * 8),                                          # an LFO at the top: the longest hold, 255 frames and a half
    (0, [5, 9, 20, 47.3, 80, 111, 60, 3.2, 0.5]),               # a knob that moves a block at a time
    (0, [40, 40, 0, 0, 40, 40, 40]),                             # off in the middle: the next frame after is let through
    (40, [16] * 8), (40, [77.7] * 8),                            # a mono sample: one channel
])
def test_the_hold_is_the_models_frame_for_frame(srr, place, knobs):
    calls = held(srr, knobs, place)
    model, at = ref.Hold(), {c["block"]: c for c in calls}
    first = min(at)
    assert first <= 1                                           # the note starts in the interrupt of its trig, or the one after
    for b in range(first, len(knobs)):
        w = word(knobs[b])
        if not ref.srr_step(w):
            assert b not in at                                  # off: the routine is not run
            model.block(None, w)
            continue
        c = at[b]
        l, r = c["in"]
        assert (r is None) == (place >= PK.SINGLES)
        assert c["step"] == ref.srr_step(w)
        want = model.block(list(zip(l, r)) if r is not None else [(x,) for x in l], w, start=b == first)
        if b == first or not ref.srr_step(word(knobs[b - 1])):
            assert c["phase"] == 0xffffffff                     # a note's start, or back from off
        assert np.array_equal(c["out"][0], [x[0] for x in want])
        if r is not None:
            assert np.array_equal(c["out"][1], [x[1] for x in want])
            assert c["after"][2] == model.kept[1] & 0xffffffff
        assert c["after"][:2] == [model.phase, model.kept[0] & 0xffffffff]


def test_every_sixteen_of_the_knob_halves_the_rate():
    for n in range(1, 8):
        assert ref.srr_step(word(16 * n)) == 1 << (32 - n)       # a hold of 2, 4, 8 ... 128 frames, to the frame
    assert ref.srr_step(0) == 0 and ref.srr_step(15) == 0        # off, and under a sixteenth of a number still off
    steps = [ref.srr_step(w) for w in range(16, 0x8000)]
    assert all(a >= b for a, b in zip(steps, steps[1:])) and steps[-1] == (0xffffffff // 0xff80 + 1) << 8


def playing(built, knob, tune=64):
    """Eight stereo samples on eight tracks, one trig, eight blocks. -> the sound, both sides, and each block's cost."""
    e = P.engine(built, pool=pool())
    for t in range(8):
        e.set_slot(t, P.SAMPLE, PK.knob_of(t))
        e.set_slot(t, P.MODE, knob)
        e.set_slot(t, P.TUNE, tune)
    out, cost = [], []
    for b in range(8):
        was = e.mc.insns
        left = e.block(0xff if b == 0 else 0, 0)
        cost.append(e.mc.insns - was)
        out.append(np.concatenate([left] + [right(e, t)[None] for t in range(8)]))
    return np.concatenate(out, axis=1), cost


OFF_COST = 336          # instructions an interrupt of eight voices has more than the multi image's with the knob at 0: 42 a voice
MOST_COST = 2600        # and with every frame of eight stereo voices let through, the most the hold can ask


def test_at_0_the_sound_is_the_multi_images_and_what_the_hold_costs(srr, multi):
    was, base = playing(multi, 1)
    off, idle = playing(srr, 0)
    assert np.array_equal(off, was)                             # both sides of every track, to the bit
    least, low = playing(srr, 1 / 16)                           # a hold of a frame and a 256th: every frame of these blocks is let through
    assert np.array_equal(least, was)
    most, high = playing(srr, 127)
    assert not np.array_equal(most, was)
    assert [a - b for a, b in zip(idle, base)][3:] == [OFF_COST] * 5
    assert [a - b for a, b in zip(low, base)][3:] == [MOST_COST] * 5
    assert all(OFF_COST < a - b < MOST_COST for a, b in zip(high[3:], base[3:]))
    # for scale: stock's heaviest machine on eight tracks is 117,348 (CLAUDE.md, traps), so the most is 2.2 hundredths of it


def test_a_take_is_made_by_the_mark_alone(srr, multi):
    """REC's mark in slot 24, the source under it, and MODE holding an amount of the reduction: the multi image's take
    of the same blocks by MODE's bits. And with the other mark no take, whatever MODE holds."""
    track, place = 3, 5
    feed = M.noise((9, BLOCK, 2), 77)
    old = M.recorder(multi, {track: place}, P.REC | P.STEREO)
    new = M.recorder(srr, {track: place}, 0)
    new.set_slot(track, P.MODE, 100)
    new.set_slot(track, 24, ON + 7 / 256)
    for e in (old, new):
        e.block(1 << track, 0)
        for b, x in enumerate(feed):
            M.write(e, 100 + b, {track: x})
            e.block(0, (1 << track) if b == 8 else 0)
    assert [P.slot_entry(new, k) for k in range(64)] == [P.slot_entry(old, k) for k in range(64)]
    assert M.state(new, track) == M.state(old, track) and M.state(new, track)[2] > 0
    for s in (2 * place, 2 * place + 1):
        assert np.array_equal(M.taken(new, s, 10 * BLOCK), M.taken(old, s, 10 * BLOCK))
    none = M.recorder(srr, {track: place}, 0)
    none.set_slot(track, P.MODE, 3)                             # what said REC, stereo, on every image before
    none.set_slot(track, 24, OFF + 7 / 256)
    none.block(1 << track, 0)
    for b, x in enumerate(feed):
        M.write(none, 100 + b, {track: x})
        none.block(0, 0)
    assert M.state(none, track)[0] == 0 and M.state(none, track)[2] == 0


def test_a_track_left_on_swarm_plays_nothing_and_the_others_are_not_touched(srr, multi):
    """The first track, so that no stereo sample's right side is folded into its row. Its block is filled with
    something before every interrupt: the stand-in is what clears it."""
    outs, hits = [], []
    for built in (srr, multi):
        e = P.engine(built, pool=pool())
        for t in range(8):
            e.set_slot(t, P.SAMPLE, PK.knob_of(t))
        e.set_machine(0, SWARM)
        if built is srr:
            e.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, size, u: hits.append(a), begin=built[1]["swarm_render"], end=built[1]["swarm_render"])
            e.mc.uc.ctl_flush_tb()
        rows = []
        for b in range(6):
            e.mc.write(m.OUT_BUF, fw.sb("9f7cc770a4cd8734") * BLOCK)
            rows.append(e.block(0xff if b == 0 else 0, 0))
            if b:
                assert e.mc.r32(e.voice(0)) == m.SWARM_ENGINE
        outs.append(np.concatenate(rows[1:], axis=1))
    new, old = outs
    assert len(hits) == 5 and not new[0].any()                  # the stand-in ran, a block each, and left nothing
    assert np.array_equal(new[1:], old[1:]) and new[1:].any()


# ---- the main CPU: the per-block routine -----------------------------------------------------------------------------

SENT, WRITTEN, TYPES = mm.PARAM_SENT, mm.PARAM_SENT - 0x4198, 0x80002f50
KIT = 0x7f000000


class Word:
    """engine/recword.S alone: the block that is sent, the words a trig's locks are written into, stock's eight
    machines, and a kit where stock keeps its address."""

    def __init__(self, image, syms):
        mc = self.mc = Machine()
        lo, hi = mm.CAVE_SRR
        mc.map(0x40000000, 0x1000)
        mc.map(lo & ~0xfff, 0x1000)
        mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        mc.map(0x80000000, 0x10000)
        mc.map(KIT, 0x1000)
        mc.set_stack(0x8000ff00, RET)
        self.entry = syms["rec_word"]
        assert syms["srr_dirty"] == mm.SRR_DIRTY == lo and self.entry == lo + 8

    def run(self, t, own, mode=0x2a00, lock=None, mtype=44, flag=1, kit=KIT):
        """Track t: its own word on slot 24 and its MODE in the kit, and a step's lock where the locks are written,
        or the track's own word there as stock loads it. -> everything after."""
        mc = self.mc
        rng = np.random.default_rng(t)
        sent, written, sound = SENT + 142 * t, WRITTEN + 142 * t, KIT + mm.KIT_TRACK * t + mm.KIT_WORDS
        mc.write(SENT, bytes(rng.integers(0, 256, 142 * 8, dtype=np.uint8)))
        mc.write(WRITTEN, bytes(rng.integers(0, 256, 142 * 8, dtype=np.uint8)))
        mc.write(KIT, bytes(rng.integers(0, 256, 0x1000, dtype=np.uint8)))
        mc.write(TYPES, bytes(8))
        mc.write(mm.SRR_DIRTY, bytes(8))
        mc.write(sent + 62, bytes((mtype, 0)))
        mc.write(sound + 48, own.to_bytes(2, "big"))
        mc.write(sound + 46, mode.to_bytes(2, "big"))
        mc.write(written + 76, (own if lock is None else lock).to_bytes(2, "big"))
        mc.write(written + 74, mode.to_bytes(2, "big"))
        mc.write(sent + 74, mode.to_bytes(2, "big"))
        mc.w32(mm.KIT_POINTER, kit)
        before = [bytes(mc.read(a, n)) for a, n in ((SENT, 142 * 8), (WRITTEN, 142 * 8), (KIT, 0x1000))]
        for n, v in ((0, flag), (1, 0x11111111), (2, 0x22222222), (8, sent), (9, TYPES + t + 1)):
            mc.set_reg(n, v)
        was = mc.insns
        mc.call(self.entry)
        after = [bytes(mc.read(a, n)) for a, n in ((SENT, 142 * 8), (WRITTEN, 142 * 8), (KIT, 0x1000))]
        assert [mc.reg(n) for n in (1, 2, 8, 9)] == [0x11111111, 0x22222222, sent + 142, TYPES + t + 1]
        r16 = lambda a: int.from_bytes(mc.read(a, 2), "big")
        changed = [[k for k in range(len(x)) if x[k] != y[k]] for x, y in zip(before, after)]
        return {"sent": r16(sent + 76), "sent mode": r16(sent + 74), "written mode": r16(written + 74), "own": r16(sound + 48),
                "kit mode": r16(sound + 46), "dirty": bytes(mc.read(mm.SRR_DIRTY, 8)), "cost": mc.insns - was,
                "changed": [[k - 142 * t for k in changed[0]], [k - 142 * t for k in changed[1]],
                            [k - (mm.KIT_TRACK * t + mm.KIT_WORDS) for k in changed[2]]]}


@pytest.fixture(scope="module")
def routine(main):
    return Word(*main)


@pytest.mark.parametrize("t", range(8))
def test_a_signed_word_is_sent_as_its_mark_and_its_source(routine, t):
    for src in (0, 1, 9, 15):
        for rec in (0, 1):
            got = routine.run(t, signed(src, rec))
            assert got["sent"] == (ON if rec else OFF) << 8 | src
            assert got["changed"] == [[76, 77], [], []] and got["dirty"] == bytes(8)    # slot 24 of the block, nothing else
            assert got["sent mode"] == got["kit mode"] == 0x2a00                        # MODE is the reduction's: not touched


@pytest.mark.parametrize("lock, rec", [(0x5280, 1), (0x2980, 0), (0x52c0, 1), (0x6bc0, None), (0x0001, None), (0x7f00, None)])
def test_a_steps_lock_wins_and_anything_else_there_leaves_the_tracks(routine, lock, rec):
    """REC locked on, locked off, locked ONCE; a ONCE that is spent, stock's hold flag and a number: no mark."""
    for own_rec in (0, 1):
        got = routine.run(5, signed(11, own_rec), lock=lock)
        assert got["sent"] == (ON if (own_rec if rec is None else rec) else OFF) << 8 | 11
        assert got["own"] == signed(11, own_rec) and got["changed"][1:] == [[], []]


@pytest.mark.parametrize("own", [0, 1, 0x0100, 0x7f00, 0x1234, 0x40a6, 0x50a4, 0xffff])
@pytest.mark.parametrize("mode, src, rec", [(0, 0, 0), (1, 0, 0), (3, 0, 1), (2, 0, 1), (1 | 13 << 2, 13, 0), (3 | 15 << 2, 15, 1), (0x7f, 15, 1)])
def test_an_old_patterns_word_is_made_from_mode_signed_and_mode_put_at_0(routine, own, mode, src, rec):
    got = routine.run(6, own, mode=mode << 8 | 0x33)
    assert got["own"] == signed(src, rec) and got["kit mode"] == 0
    assert got["sent mode"] == got["written mode"] == 0                 # this block's reduction, and where the locks are written
    assert got["sent"] == (ON if rec else OFF) << 8 | src
    assert got["dirty"] == bytes((0, 0, 0, 0, 0, 0, 1, 0))             # the main task: this track's old locks of MODE go
    assert got["changed"][0] in ([74, 75, 76, 77], [74, 76, 77], [75, 76, 77], [76, 77]) and set(got["changed"][2]) <= {46, 47, 48, 49}
    again = routine.run(6, got["own"], mode=0x1000)                    # and the next block it is a signed word
    assert again["own"] == got["own"] and again["kit mode"] == 0x1000 and again["dirty"] == bytes(8)


def test_another_machine_keeps_stocks_flag_and_nothing_is_read_without_a_kit(routine):
    for flag in (0, 1):
        got = routine.run(2, signed(4, 1), mtype=4, flag=flag)
        assert got["sent"] == flag and got["changed"][1:] == [[], []] and got["dirty"] == bytes(8)
        got = routine.run(2, 0x1234, mode=0x0300, flag=flag, kit=0)
        assert got["sent"] == flag and got["changed"][1:] == [[], []] and got["dirty"] == bytes(8)


COSTS = (6, 38, 52)     # instructions a track a block: another machine's, a sampler's, and once an old pattern's


def test_what_the_routine_costs(routine):
    assert (routine.run(1, 0, mtype=4)["cost"], max(routine.run(1, signed(3, r), lock=k)["cost"] for r in (0, 1) for k in (None, 0x5280, 0x2980)),
            routine.run(1, 0, mode=0x0700)["cost"]) == COSTS


# ---- the main CPU: the feed, by the word the routine leaves ------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return M.Feed(*main)


def fed(rig, words, modes, gains, seed=3, seq=0x0105):
    rig.reset(gains=gains)
    rig.window = []
    window, frame = junk(seq), frames(seed=seed)
    b = bytearray(make_block(ALL, [modes.get(t, 0) for t in range(12)]))
    for t in range(8):
        b[STRIDE * t + F.P_REC:STRIDE * t + F.P_REC + 2] = words.get(t, OFF << 8).to_bytes(2, "big")
    ret, after = rig.run(bytes(b), frame, window)
    assert all(size in (2, 4) for _, _, size, _ in rig.window)      # the window stores words: never a byte
    return window, frame, after


@pytest.mark.parametrize("takes", [{0: 0}, {3: 1, 6: 9}, {1: 15, 2: 14, 4: 2, 7: 13}, {t: (5 * t + 1) % 16 for t in range(8)}])
def test_every_track_with_the_mark_is_fed_its_own_source_whatever_mode_holds(rig, takes):
    words = {t: ON << 8 | n for t, n in takes.items()}
    words.update({t: OFF << 8 | 7 for t in range(8) if t not in takes})
    modes = {t: (2, 3, 0x7f, 0, 0x2b, 6, 1, 0x40)[t] for t in range(8)}       # REC's old bit on some, an amount on others
    window, frame, after = fed(rig, words, modes, M.GAINS, seed=3 + len(takes))
    assert after == M.want(window, frame, {t: (n, True) for t, n in takes.items()}, M.GAINS)


def test_with_no_mark_nothing_is_written_though_mode_says_rec_as_it_did(rig):
    window, frame, after = fed(rig, {}, {t: 3 for t in range(8)}, M.GAINS)
    assert after == M.want(window, frame, {}, M.GAINS)


# ---- the image --------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, main, srr, multi):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=8)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=7)
    assert hashlib.sha256(was_raw).hexdigest().startswith("eceba3b3")      # the multi image is still the one on the unit
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and len(new) == len(old)
    record = mm.SAMP_RECORDS + 52 * 5
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE9, mm.CAVE_METER,
             mm.CAVE_ONCE, mm.CAVE_REC, mm.CAVE_SRR, (record, record + 52), (0x402545ec, 0x402545fa)]
    stray = [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    # three operands: the trig test's and the hold flag's calls of routines that moved, and the object that writes MODE's number.
    # And the second build's one byte: MODE's entry of the display table is given the plain knob's behaviour
    assert all(mm.TRIG_MUTE + 2 <= a < mm.TRIG_MUTE + 6 or mm.HOLD_WRITE + 2 <= a < mm.HOLD_WRITE + 6 or 0x401943aa <= a < 0x401943ae
               or a == build_main.SRR_KNOB + 1 for a in stray) and 4 <= len(stray) <= 13
    assert new[mm.off(build_main.SRR_KNOB):][:2] == old[mm.off(0x401942fa):][:2] == bytes.fromhex("2f0d")      # as LEN's entry
    assert old[mm.off(build_main.SRR_KNOB):][:2] == bytes.fromhex("2f04")
    assert new[mm.off(mm.HOLD_WRITE):][:6] == b"\x4e\xb9" + syms["rec_word"].to_bytes(4, "big")
    assert new[mm.off(0x402545ec):][:14] == b"Rate Red\0SRR\0\0"
    assert new[mm.off(record + 4):][:16] == bytes.fromhex(fw.sx("3d2f55ae171a147a0ddd746bbbffbd8ab90ae3ec"))     # slot 23, 0 to 127, off
    seven, last = built.section(7), was.section(7)
    assert seven == srr[0] != last == multi[0] and len(seven) == len(last)
    runs = [r for caves in (m.CAVES, m.REC_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.PITCH_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                            m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES) for r in caves.values()]
    tables = [(t + 4 * m.SWARM_ENGINE, t + 4 * m.SWARM_ENGINE + 8) for t in (m.UPDATE_TABLE, m.RENDER_TABLE)]   # engines 10 and 11, each table
    assert not [k for k in range(len(seven)) if seven[k] != last[k] and not any(m.off(a) <= k < m.off(b) for a, b in runs + tables)]
    for t, name in ((m.UPDATE_TABLE, "swarm_update"), (m.RENDER_TABLE, "swarm_render")):
        assert m.u32(seven, t + 4 * m.SWARM_ENGINE) == srr[1][name] and m.SRR_CAVES["d"][0] <= srr[1][name] < m.SRR_CAVES["d"][1]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
