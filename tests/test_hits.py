"""The hits image: the lap image with a long sample's hits starting the filter's envelope again, as a trig of its own."""
import hashlib
import shutil

import numpy as np
import pytest

import test_pack as PK
import test_pagerec as P
from emu.machine import Machine
from test_quick import ST, Folded
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SR, LOOP = 48000, 22
GAP, RISE, TAIL, FALL, MOST = 32, 3, 4, 4, 122


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def hits(stock):
    return build_engine.patched_image(stock, hits=True)


@pytest.fixture(scope="module")
def tail(stock):
    return build_engine.patched_image(stock, tail=True)  # the lap image's section 7


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


# ---- the model
# ------------------------------------------------------------------------------------------------------

def loud(p):
    s, t = 0, 181
    while s < 15 and p > t:
        s, t = s + 1, t + (t * 53 >> 7)
    return s


def model(x):
    """What the scan is to keep of a slot: [(first frame, how loud, the end of its last loud window)]."""
    env, gap, top, fall, out = 0, GAP, 0, 0, []
    for i in range(0, len(x), 32):
        p = int(np.abs(x[i:i + 32].astype(np.int32)).max())
        if gap < GAP:
            gap += 1
            if gap <= RISE and loud(p) > out[-1][1]:
                out[-1][1] = loud(p)
        elif p > 2 * env and len(out) < MOST and loud(p):
            out.append([i, loud(p), i])
            top = fall = p
            gap = 0
        if top:
            fall -= fall >> FALL
            fall, top = max(fall, p), max(top, p)
            if p >= top >> TAIL:
                at = min(i + 32, len(x))
                out[-1][2] = out[-1][0] + min(-(-(at - out[-1][0]) // 32), 0x3fff) * 32
            elif fall < top >> TAIL:
                top = 0
        env -= env >> 6
        env = max(env, p)
    return [tuple(h) for h in out]


def bursts(n=9600, at=((0, 20000), (4800, 6000))):
    """Silence with a hit that dies away in about 300 frames at each place."""
    x = np.zeros(n, np.int16)
    for k, a in at:
        x[k:k + 600] = (a * np.exp(-np.arange(600) / 100) * np.sin(np.arange(600))).astype(np.int16)
    return x


def drums(seconds=1.0, seed=1):
    """Kicks every half second, a hat between, over a bass at -21 dB."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 3000 * np.sin(2 * np.pi * 55 * t)
    for k in range(0, n, SR // 2):
        j = np.arange(min(SR // 4, n - k))
        x[k:k + len(j)] += 20000 * np.exp(-j / 2400) * np.sin(2 * np.pi * (60 + 200 * np.exp(-j / 300)) * j / SR)
    for k in range(SR // 4, n, SR // 2):
        j = np.arange(min(2400, n - k))
        x[k:k + len(j)] += 4000 * np.exp(-j / 300) * rng.standard_normal(len(j))
    return np.clip(x, -32768, 32767).astype(np.int16)


# ---- the audio CPU
# --------------------------------------------------------------------------------------------------

def kept(e, k):
    mc, at = e.mc, m.HITS_STORE + m.HITS_BYTES * k
    n = mc.read(at + 19, 1)[0]
    return [((w >> 18) * 32, w & 15, ((w >> 18) + (w >> 4 & 0x3fff)) * 32) for w in (mc.r32(at + 24 + 4 * i) for i in range(n))], mc.r32(at + 12)


def s32(v):
    return v - (1 << 32) if v >> 31 else v


def notes(built, x, blocks, knobs=None):
    """Slots 0 and 1 hold x, gone over before a note of it on track 0. -> the engine, and a row a block."""
    image, syms = built
    e = P.engine(built, pool={0: x, 1: x})
    for slot, v in {P.SAMPLE: PK.knob_of(0), P.MODE: 0, P.TUNE: 64, P.LENGTH: 127, **(knobs or {})}.items():
        e.set_slot(0, slot, v)
    for _ in range(len(x) // 128 + 2):
        e.mc.call(syms["hits_block"])
    rows, st = [], e.voice(0) + ST
    for b in range(blocks):
        e.block(1 if b == 0 else 0, 0)
        e.mc.call(syms["hits_block"])
        rows.append(dict(word=e.mc.r32(m.HIT_BOX), now=s32(e.mc.r32(st + 8)) >> 12, inc=e.mc.r32(st + 24),
                         dir=s32(e.mc.r32(st + 28)) >> 24, pa=s32(e.mc.r32(st + 36))))
    return e, rows


def test_the_scan_keeps_the_models_hits(hits):
    x, bass = drums(), (16000 * np.sin(2 * np.pi * 30 * np.arange(SR) / SR)).astype(np.int16)
    e = P.engine(hits, pool={0: x, 1: x, 6: bass, 7: bass})
    for _ in range(4 * (SR // 128 + 2) + 8):  # no voice plays: the slots in turn, 0 to 7
        e.mc.call(hits[1]["hits_block"])
    assert kept(e, 6)[1] == SR
    got, done = kept(e, 0)
    assert done == len(x) and got == model(x)
    assert [f for f, _, _ in got] == [0, 12000, 24000, 36000]  # every kick and hat, at its own window
    assert [s for _, s, _ in got] == [14, 13, 14, 12]  # kicks at -6 dB, hats at -9 and -12
    assert all(a < b <= c for (a, _, b), (c, _, _) in zip(got, got[1:] + [(SR, 0, 0)]))  # each ends before the next
    assert kept(e, 6)[0] == model(bass) and len(model(bass)) == 1  # a bass line has its start and nothing else
    e = P.engine(hits, pool={0: bursts()})
    for _ in range(80):
        e.mc.call(hits[1]["hits_block"])
    got = kept(e, 0)[0]
    assert got == model(bursts())
    print("hits: ends of the two bursts", [(f, end) for f, _, end in got], "and of the drums", [(f, end) for f, _, end in model(x)])


def test_a_slot_that_changes_is_gone_over_again(hits):
    x, y = drums(seed=1), drums(seed=2)[::-1].copy()
    e = P.engine(hits, pool={0: x})
    call = lambda n: [e.mc.call(hits[1]["hits_block"]) for _ in range(n)]
    call(SR // 128 + 2)
    assert kept(e, 0)[0] == model(x)
    ptr = e.mc.r32(m.SLOT_PTR)
    e.mc.write(ptr, y.astype(">i2").tobytes())  # the same place and length, other frames: a print tells
    call(64 + SR // 128 + 2)
    assert kept(e, 0)[0] == model(y) != model(x)


def test_a_list_left_by_another_build_is_not_believed(hits):
    x = drums()
    image, syms = hits
    e = P.engine(hits, pool={0: x, 1: x})
    for slot, v in {P.SAMPLE: PK.knob_of(0), P.MODE: 0, P.TUNE: 64, P.LENGTH: 127}.items():
        e.set_slot(0, slot, v)
    ptr, n = e.mc.r32(m.SLOT_PTR), len(x)
    old = [(f << 8 | s) for f, s, _ in model(x)]
    for k in (0, 1):
        print_ = (n + sum(int(np.uint16(x[(n >> 4) * j])) for j in range(16))) & 0xffffffff
        at = m.HITS_STORE + m.HITS_BYTES * k
        e.mc.write(at, b"".join(v.to_bytes(4, "big") for v in (e.mc.r32(m.SLOT_PTR + 8 * k), n, print_, n))
                   + (5000).to_bytes(2, "big") + bytes((GAP, len(old))) + b"".join(w.to_bytes(4, "big") for w in old))
    assert e.mc.r32(m.SLOT_PTR + 8) and ptr
    rows, st = [], e.voice(0) + ST
    for b in range(int(n / 32) + 20):
        e.block(1 if b == 0 else 0, 0)
        e.mc.call(syms["hits_block"])
        rows.append(dict(word=e.mc.r32(m.HIT_BOX), now=s32(e.mc.r32(st + 8)) >> 12, inc=e.mc.r32(st + 24),
                         dir=s32(e.mc.r32(st + 28)) >> 24))
    assert kept(e, 0)[0] == model(x)  # gone over again
    assert said(rows) and said(rows) == expected(rows, model(x))[:len(said(rows))]


def said(rows, start=0):
    """[(block, how loud)] a voice says."""
    return [(b, r["word"] & 15) for b, r in enumerate(rows) if b >= start and r["word"] & 15]


def expected(rows, found):
    """[(block, how loud)] a one-shot is to say: a hit's start reached going forward, its end going backward, two blocks
    on, and not one its note starts on.
    """
    want, reach = [], None
    for b, r in enumerate(rows):
        d = r["dir"]
        if not d:  # the trig's block: the note starts in the next
            continue
        ahead = d * r["now"] + (r["inc"] >> 6)
        if reach is not None:
            s = max([v for f, v, end in found if reach < (f if d > 0 else -end) <= ahead], default=0)
            if s:
                want.append((b, s))
            reach = max(reach, ahead)
        else:
            reach = ahead
    return want


@pytest.mark.parametrize("tune", [64, 76, 57])
def test_a_voice_says_each_hit_once_two_blocks_before_it(hits, tune):
    x, rate = drums(), 2 ** ((tune - 64) / 12)
    e, rows = notes(hits, x, int(len(x) / 32 / rate) + 20, {P.TUNE: tune})
    found = model(x)
    want = expected(rows, found)
    assert said(rows) == want and len(want) == len(found) - 1  # the note's own start is stock's trig's
    assert all(r["word"] >> 4 == 0 for r in rows)  # nothing on a track that plays nothing
    assert abs((rows[5]["inc"] >> 6) - 64 * rate) <= 1  # two blocks on, at the pitch it plays at


@pytest.mark.parametrize("tune", [64, 76])
def test_backward_a_hit_is_said_where_its_sound_comes_up_out_of_the_quiet(hits, tune):
    x = bursts()
    e, rows = notes(hits, x, int(len(x) / 32 / 2 ** ((tune - 64) / 12)) + 20, {P.SAMPLE: PK.knob_of(0, reverse=True), P.TUNE: tune})
    assert rows[3]["dir"] < 0 and rows[3]["now"] > 9000
    found = model(x)
    want = expected(rows, found)
    assert said(rows) == want and [s for _, s in want] == [found[1][1], found[0][1]]  # the second hit first
    for (b, _), (_, _, end) in zip(want, found[::-1]):
        assert rows[b - 1]["now"] - 64 * 2 ** ((tune - 64) / 12) > end - 2 and rows[b]["now"] - (rows[b]["inc"] >> 6) <= end


def test_a_loop_says_its_start_again_after_each_turn(hits):
    x = bursts()
    e, rows = notes(hits, x, 1400, {LOOP: 1})
    turns = [b for b in range(1, len(rows)) if rows[b]["now"] < rows[b - 1]["now"]]
    assert len(turns) == 4 and all(rows[b]["pa"] == 0 for b in turns)
    got = said(rows)
    assert [b for b, s in got if s == model(x)[0][1]] == turns  # the loop's start, in the block it begins again in
    middle = [b for b, s in got if s == model(x)[1][1]]
    assert len(middle) == 5 and all(rows[b]["now"] + 64 >= 4800 > rows[b - 1]["now"] + 64 for b in middle)


@pytest.mark.parametrize("machine", [36, 37])
def test_a_track_on_sy_toy_or_sy_bits_plays_nothing(hits, tail, machine):
    out = []
    for built in (hits, tail):
        e = P.engine(built)
        e.set_machine(0, machine)
        out.append(np.concatenate([e.block(1 if b == 0 else 0, 0)[0] for b in range(40)]))
    assert not out[0].any() and np.abs(out[1]).max() > 1 << 16  # the lap image's still sounds


def whole(image, factory, blocks, note):
    """Eight stereo samples on eight tracks looping, through the whole interrupt, a trig in the second block. -> each
    block's cost, the window's two longs after it, and the sound: the left after the last stage, the right channels as
    the main CPU reads them.
    """
    from stereo_rig import Rig
    from test_stereo import pool, samplers
    r = Rig(image)
    r.load_pool(pool())
    samplers(r, factory, loop=1, mode=0)
    for t in range(8):
        r.set_slot(t, P.SAMPLE, 64 + t % 3)
        r.set_note(t, note)
    cost, box, sound = [], [], []
    for b in range(blocks):
        _, _, left = r.block(0xff if b == 1 else 0, 0)
        cost.append(sum(r.cost.values()))
        box.append((r.mc.r32(m.HIT_BOX), r.mc.r32(m.HIT_BOX + 4)))
        sound.append(np.concatenate([left] + [r.right(t)[None] for t in range(8)]))
    return cost, box, np.concatenate(sound, axis=1)


@pytest.fixture(scope="module")
def factory(official):
    from tools import params
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


def test_the_sound_is_the_lap_images_the_long_holds_the_hits_and_what_they_cost(hits, tail, factory):
    from test_stereo import SWARM
    costs = {}
    for note in (60, 55.25):
        n = 270 if note == 60 else 40  # the time image's routine says P every 256 blocks
        costs["hits", note], box, sound = whole(hits[0], factory, n, note)
        costs["tail", note], _, was = whole(tail[0], factory, n, note)
        assert np.array_equal(sound, was) and np.abs(sound).max() > 1 << 20
        assert all(w >> 24 != 0x43 for w, _ in box)  # never the time image's C
        assert note != 60 or box[-1][1] >> 24 == 0x50  # and P where it was, said
    more = {note: [a - b for a, b in zip(costs["hits", note], costs["tail", note])] for note in (60, 55.25)}
    worst = max(max(v[2:]) for v in more.values())
    heaviest = max(costs["hits", 55.25][2:])
    print("hits: more an interrupt, at 60 the most %d, steady %d; pitched the most %d, steady %d; heaviest %d of %d"
          % (max(more[60][2:]), more[60][-1], max(more[55.25][2:]), more[55.25][-1], heaviest, SWARM))
    assert worst < 4000 and heaviest < SWARM


# ---- the main CPU
# ---------------------------------------------------------------------------------------------------

PARAMS, ENV = 0x80006348, 0x43bdd09c
ATK, DEC, SUS, REL = 10, 64, 0, 64


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=16)


def envelope(main, tracks, word=0, trig=0, ours=True):
    """tracks: (machine, DEL, FENR) for the eight, each in its decay. -> the envelopes, the block after, the cost."""
    image, syms = main
    mc = Machine()
    mc.map(0x40000000, (len(image) + 0x400 + 0xffff) & ~0xffff)
    mc.write(mm.BASE, image)
    for lo, hi in (mm.CAVE_HITS, (mm.FILTER_ENV, mm.FILTER_ENV + 0x122)):
        mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
    mc.map(0x10000000, 0x2000)
    mc.map(0x43bd0000, 0x10000)
    mc.map(0x80000000, 0x10000)
    mc.map(0x7ff00000, 0x10000)
    mc.set_stack(0x7ff0f000, 0x7ff00000)
    mc.w32(mm.HIT_BOX_MAIN, word)
    for t, (machine, dl, fenr) in enumerate(tracks):
        p = PARAMS + 142 * t
        for at, v in ((62, machine), (90, dl), (92, ATK), (94, DEC), (96, SUS), (98, REL), (100, fenr)):
            mc.write(p + at, (v << 8).to_bytes(2, "big"))
        if not ours and machine == 44:
            mc.write(p + 90, bytes(2))  # stock's own, handed DEL at 0
        mc.w32(ENV + 12 * t, 1)
        mc.w32(ENV + 12 * t + 4, 0x90000000 + 0x1000000 * t)
    block = mc.read(PARAMS, 142 * 8)
    mc.emac.macsr = 0x20
    n = mc.insns
    mc.call(syms["hits_env"] if ours else mm.FILTER_ENV, PARAMS, trig, 0, 0)
    after = mc.read(PARAMS, 142 * 8)
    if ours:
        assert after == block
    return [tuple(mc.r32(ENV + 12 * t + 4 * i) for i in range(3)) for t in range(8)], mc.insns - n


def threshold(dl):
    return 15 - ((dl - 1) * 15 >> 7)


TRACKS = [(44, 1, 0), (44, 40, 0), (44, 64, 1), (44, 127, 0), (44, 0, 0), (44, 90, 1), (4, 40, 0), (4, 40, 0)]


def test_a_hit_del_lets_through_is_stocks_trig_with_del_at_0_on_that_track_alone(main):
    nib = [15, 9, 8, 1, 15, 0, 15, 7]
    word = sum(n << 4 * t for t, n in enumerate(nib))
    want = sum(1 << t for t, (machine, dl, _) in enumerate(TRACKS) if machine == 44 and dl and nib[t] and nib[t] >= threshold(dl))
    assert want == 0b1101
    ours, cost = envelope(main, TRACKS, word)
    theirs, stock = envelope(main, TRACKS, trig=want, ours=False)
    assert ours == theirs
    assert [s for s, _, _ in ours] == [2, 1, 2, 2, 1, 1, 1, 1]  # the attack again on 0, 2 and 3, and nothing else moved
    assert ours[2][1] == 0 and ours[0][1] != 0  # FENR on: from nothing. Off: from where it was
    print("hits: the main CPU's call %d instructions, stock's own %d" % (cost, stock))
    assert cost - stock < 300  # 252 here: six sampler tracks with DEL, the feed was 4,000 to 5,000


def test_del_1_takes_the_loudest_only_and_127_every_hit():
    assert [threshold(d) for d in (1, 9, 10, 17, 64, 120, 127)] == [15, 15, 14, 14, 8, 2, 1]  # a step every 8 or 9
    assert all(threshold(a) >= threshold(b) for a, b in zip(range(1, 127), range(2, 128)))


def test_a_trig_of_stocks_on_a_sampler_track_never_waits_and_another_machines_does(main):
    ours, _ = envelope(main, TRACKS, trig=0xff)
    assert [s for s, _, _ in ours] == [2, 2, 2, 2, 2, 2, 3, 3]  # the delay's state on the two that are no sampler
    both, _ = envelope(main, TRACKS, word=0xffffffff, trig=0xff)
    assert both == ours  # a hit with stock's trig is stock's trig


# ---- the image
# ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, hits):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=16, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=15, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("0d5e8cf6")  # the lap image, as it is
    new, old = built.section(3), was.section(3)
    spans = [mm.CAVE_HITS, (mm.FILTER_ENV_CALL + 2, mm.FILTER_ENV_CALL + 6)]
    assert not [k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert new[mm.off(mm.FILTER_ENV_CALL):][:6] == b"\x4e\xb9" + syms["hits_env"].to_bytes(4, "big")
    seven, last = built.section(7), was.section(7)
    assert seven == hits[0] and len(seven) == len(last)
    runs = [r for caves in (m.CAVES, m.REC_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.PITCH_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                            m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES, m.HITS_CAVES) for r in caves.values()]
    runs += [(table + 4 * m.TOY_ENGINE, table + 4 * m.TWIN_ENGINE + 4) for table in (m.UPDATE_TABLE, m.RENDER_TABLE)]  # their pointers into the runs
    runs += [(m.ISR_VOICE_LOOP_CALL + 2, m.ISR_VOICE_LOOP_CALL + 6), (m.ISR_AMP_CALL + 2, m.ISR_AMP_CALL + 6)]
    assert not [k for k in range(len(seven)) if seven[k] != last[k] and not any(m.off(a) <= k < m.off(b) for a, b in runs)]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
