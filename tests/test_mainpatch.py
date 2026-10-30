"""Phase 7: the main CPU patches (section 3, OS 1.42): knob descriptors and the mixer link."""
import glob
import re
import shutil
import subprocess

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

from emu.emac import s32
from emu.machine import Machine, boundaries
from tools import build, build_main, fw, params, uitable
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STRIDE, TRACKS = 142, 12
P_TYPE, P_MODE, P_FIRST, P_PAN, P_VOL, P_LAST = 62, 28 + 2 * 23, 118, 122, 124, 128


@pytest.fixture(scope="module")
def stock(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def patched(stock):
    return build_main.patched_image(stock)


# ---- knob descriptors ----------------------------------------------------------------

def test_descriptors_read_back_as_the_sampler(stock, patched):
    image, _ = patched
    got = {p.slot: (p.short, p.long, p.min, p.max, p.default)
           for p in params.load(image, "1.42") if p.type == 44}
    assert got == {
        18: ("TUNE", "Tune", 40, 88, 64),
        19: ("SMPL", "Sample", 0, 127, 64),
        20: ("STRT", "Start", 0, 127, 0),
        21: ("LEN", "Length", 0, 127, 127),
        22: ("LOOP", "Loop", 0, 2, 0),
        23: ("MODE", "Mode", 0, 5, 0),
        26: ("OVER", "Overdrive", 0, 127, 0),
        25: ("DEC", "Decay", 0, 127, 127),
    }
    others = lambda img: [p for p in params.load(img, "1.42") if p.type != 44]
    assert others(image) == others(stock)


def test_shared_strings_are_left_alone(stock, patched):
    image, _ = patched
    for addr, text in ((0x40254315, b"TUN1"), (0x40254324, b"TUN2"), (0x4025436e, b"DEC1"),
                       (0x4024ec84, b"MIX"), (0x4025407f, b"Mix"), (0x402545c4, b"SAMP")):
        assert stock[mm.off(addr):mm.off(addr) + len(text) + 1] == text + b"\0"
        assert image[mm.off(addr):mm.off(addr) + len(text) + 1] == text + b"\0"
    for addr, old, new in build_main.REWRITE:
        assert stock.count(build_main.be32(addr)) == 1           # only a Twinshot record points here
        assert len(new) <= len(old)


def test_descriptor_patch_alone_changes_only_data_tables(stock):
    buf = bytearray(stock)
    for p in build_main.descriptor_patches(stock):
        buf[p.offset:p.offset + len(p.new)] = p.new
    changed = [mm.BASE + i for i in range(len(stock)) if stock[i] != buf[i]]
    assert changed and min(changed) >= 0x40233d30 and max(changed) < 0x40254600
    assert len(changed) < 60


# ---- how the knobs are shown ---------------------------------------------------------

SAMP = dict(zip(("TUNE", "SMPL", "STRT", "LEN", "LOOP", "MODE", "OVER", "DEC"), range(mm.SAMP_FIRST, mm.SAMP_FIRST + 8)))


@pytest.fixture(scope="module")
def shown(stock, patched):
    return uitable.table(stock), uitable.table(patched[0])


def test_display_table_is_indexed_by_descriptor_record(stock):
    code = stock[mm.off(mm.UI_ENTRY):mm.off(mm.UI_ENTRY) + 0x1e]
    assert build_main.be32(mm.UI_COUNT) in code                   # cmpil #505
    assert bytes((0x72, mm.UI_STRIDE)) in code                    # moveq #84,%d1
    assert build_main.be32(mm.UI_TABLE) in code                   # addil #table
    assert mm.SAMP_RECORDS == mm.UI_RECORDS + 0x34 * mm.SAMP_FIRST
    first, count = params.TABLES["1.42"][1]
    assert first + 0x34 * count == mm.UI_RECORDS + 0x34 * mm.UI_COUNT


def test_stock_display_agrees_with_what_the_owner_saw(shown):
    """Hardware log 2026-10-04: FLT1 and MIX read -64..+63, SMP2 reads -64 at the left end."""
    stock_table, _ = shown
    assert sum("text" in e for e in stock_table) > 495
    text = lambda name: stock_table[SAMP[name]]["text"]["target"]
    assert text("STRT") == text("LEN") == mm.TEXT_MINUS_64        # value minus 64
    assert text("SMPL") == text("MODE") == mm.TEXT_SLOT           # slot number, reversed below 64
    assert text("TUNE") == text("LOOP") == mm.TEXT_TUNE
    assert text("OVER") == mm.TEXT_PLAIN


def test_sampler_knobs_are_shown_as_plain_numbers(stock, shown):
    stock_table, new = shown
    assert [k for k in range(mm.UI_COUNT) if stock_table[k] != new[k]] == [SAMP[n] for n in ("STRT", "LEN", "LOOP", "MODE")]
    for name in ("STRT", "LEN", "LOOP", "MODE"):
        was, e = stock_table[SAMP[name]], new[SAMP[name]]
        assert e["text"]["object"] == mm.OBJ_TEXT_PLAIN and e["text"]["target"] == mm.TEXT_PLAIN
        assert e["graphic"]["object"] == mm.OBJ_GFX_PLAIN
        assert e["step"]["object"] == mm.OBJ_STEP_PLAIN
        assert (e["flags"], e["template"], e.get("f3")) == (was["flags"], was["template"], was.get("f3"))
    for name in ("TUNE", "SMPL", "OVER", "DEC"):
        assert new[SAMP[name]] == stock_table[SAMP[name]]


def test_display_patches_only_swap_objects_of_the_same_kind(stock, shown):
    """Each new object is one stock knobs already use in that same field, copied by that same routine,
    and it exists before the patched instruction runs."""
    stock_table, _ = shown
    stores, _ = uitable.walk(stock)
    fields = {"text": mm.OBJ_TEXT_PLAIN, "graphic": mm.OBJ_GFX_PLAIN, "step": mm.OBJ_STEP_PLAIN}
    users = {f: [e[f] for e in stock_table if f in e and e[f]["object"] == obj] for f, obj in fields.items()}
    assert all(len(u) >= 40 for u in users.values())
    sites = {}
    for e in stock_table[SAMP["STRT"]:SAMP["MODE"] + 1]:
        for f in fields:
            sites[e[f]["site"]] = (f, e[f])
    assert len(build_main.DISPLAY) == 10
    for addr, opcode, old, new, _ in build_main.DISPLAY:
        f, was = sites[addr]
        assert mm.UI_INIT[0] < addr < mm.UI_INIT[1]
        assert was["object"] == old and new == fields[f]
        assert {u["copy"] for u in users[f]} == {was["copy"]}
        built_at = stores[new + 0xc][1]
        assert built_at < addr
        assert stock[mm.off(addr):mm.off(addr) + 2] == opcode


# ---- the cave ------------------------------------------------------------------------

def test_main_cpu_caves_are_unreferenced(stock):
    """The mixer link's cave, the recorder image's (three unused mix kernel variants) and the analog mute's."""
    caves = ((mm.CAVE, 2), (mm.CAVE_REC, 3), (mm.CAVE_AMUTE, 1))  # (range, whole functions in it)
    n = len(stock) // 4 * 4
    for shift in (0, 2):                                         # every 32-bit value at an even offset
        v = np.frombuffer(stock[shift:shift + (n - 4)], dtype=">u4")
        for (lo, hi), _ in caves:
            assert not np.any((v >= lo) & (v < hi))
    listing = boundaries(stock, mm.BASE)
    for (lo, hi), functions in caves:
        inside = [(a, t) for a, _, t in listing if lo <= a < hi]
        assert inside[0][0] == lo and inside[-1][1].startswith("rts")
        assert sum(t.startswith("rts") for _, t in inside) == functions
        prev = [t for a, _, t in listing if lo - 2 <= a < lo]
        assert prev and prev[-1].startswith("rts")               # nothing falls into it
    for addr, _, text in listing:
        if addr >= 0x40400000:
            continue
        outside = [(lo, hi) for (lo, hi), _ in caves if not lo <= addr < hi]
        for x in re.findall(r"0x([0-9a-f]{8})\b", text):
            assert not any(lo <= int(x, 16) < hi for lo, hi in outside), hex(addr)
        t = re.match(r"jmp %pc@\(0x([0-9a-f]{8}),%d[0-7]", text)  # switch tables: 16-bit offsets
        if t:
            base = int(t.group(1), 16)
            for k in range(512):
                o = mm.off(base) + 2 * k
                target = base + int.from_bytes(stock[o:o + 2], "big", signed=True)
                if not base - 0x4000 <= target < base + 0x8000 or target & 1:
                    break
                assert not any(lo <= target < hi for lo, hi in outside), hex(addr)
    # the recorder's cave sits between the kernel the mixer calls and the copy helper it calls
    assert mm.CAVE_REC == (mm.MIX_KERNEL_END, 0x4008f22c)
    assert mm.u32(stock, 0x4008f8fe)  >> 16 == 0x4bfa and 0x4008f900 + int.from_bytes(stock[mm.off(0x4008f900):mm.off(0x4008f902)], "big", signed=True) == 0x4008f22c


# ---- the mixer link, with the mixer stubbed -----------------------------------------------

PARAMS = 0x80002000
CONTROL_BYTES = 80                                           # the level, cutoff and tune words of the control block
STUB = bytes.fromhex("203c8000dbd04e75")                     # move.l #0x8000dbd0,d0 ; rts


class Rig:
    def __init__(self, image, syms, entry="mix_link"):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x80000000, 0x10000)
        mc.map(mm.PATTERN_MUTES & ~0xffff, 0x10000)
        mc.write(mm.BASE, image)
        mc.write(mm.MIX, STUB)                               # test only: the real mixer is not run
        for a, b in ((mm.PAN_HELPER, mm.PAN_END), mm.CAVE, mm.CAVE_AMUTE, (mm.MIX_GAIN, mm.MIX_GAIN_END)):
            mc.load_code(a, image[mm.off(a):mm.off(b)])
        mc.set_stack(0x407ff000, 0x40000100)
        self.entry = syms[entry]
        self.seen = None
        mc.uc.hook_add(UC_HOOK_CODE, self._at_mixer, begin=mm.MIX, end=mm.MIX)
        mc.uc.ctl_flush_tb()

    def _at_mixer(self, uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        self.seen = dict(args=[self.mc.r32(sp + 4 * k) for k in (1, 2, 3)],
                         params=self.mc.read(PARAMS, 0x800), level2=self.mc.read(mm.LEVEL2, 32),
                         control=self.mc.read(mm.CONTROL, CONTROL_BYTES))

    def run(self, block, level2, mutes=0, solos=0, pattern=0):
        self.mc.write(PARAMS, block)
        self.mc.write(mm.LEVEL2, level2)
        self.mc.write(mm.MUTES, mutes.to_bytes(4, "big") + solos.to_bytes(4, "big"))
        self.mc.write(mm.PATTERN_MUTES, pattern.to_bytes(2, "big"))
        ret = self.mc.call(self.entry, 0x11111111, 0x22222222, PARAMS)
        return ret, self.mc.read(PARAMS, 0x800), self.mc.read(mm.LEVEL2, 32)


def make_block(machines, modes, seed=1):
    rng = np.random.default_rng(seed)
    b = bytearray(rng.integers(0, 256, 0x800, dtype=np.uint8).tobytes())
    for t in range(TRACKS):
        b[STRIDE * t + P_TYPE] = machines[t]
        b[STRIDE * t + P_MODE] = modes[t]
    return bytes(b), rng.integers(0, 256, 32, dtype=np.uint8).tobytes()


@pytest.fixture(scope="module")
def rig(patched):
    return Rig(*patched)


def test_mixer_sees_a_linked_pair_and_everything_is_put_back(rig):
    machines = [44, 0, 4, 44, 6, 44, 38, 44, 9, 10, 11, 12]
    modes = [1, 0, 1, 5, 0, 0, 1, 1, 0, 0, 0, 0]     # linked: 0->1 and 3->4. Not: 2, 5, 6 (wrong machine or mode), 7 (last)
    block, level2 = make_block(machines, modes)
    ret, after, level2_after = rig.run(block, level2)
    assert ret == 0x8000DBD0                           # the mixer's return value comes back
    assert rig.seen["args"] == [0x11111111, 0x22222222, PARAMS]
    assert after == block and level2_after == level2   # nothing is left changed

    want = bytearray(block)
    want_l2 = bytearray(level2)
    for left in (0, 3):
        p, q = STRIDE * left, STRIDE * (left + 1)
        want[q + P_FIRST:q + P_LAST] = want[p + P_FIRST:p + P_LAST]
        want[p + P_PAN:p + P_PAN + 2] = (0).to_bytes(2, "big")
        want[q + P_PAN:q + P_PAN + 2] = (127 << 8).to_bytes(2, "big")
        want[2 * (left + 1):2 * (left + 1) + 2] = want[2 * left:2 * left + 2]
        want_l2[2 * (left + 1):2 * (left + 1) + 2] = want_l2[2 * left:2 * left + 2]
    assert rig.seen["params"] == bytes(want)
    assert rig.seen["level2"] == bytes(want_l2)


def test_no_sampler_no_change(rig):
    block, level2 = make_block([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [1] * 12, seed=2)
    ret, after, level2_after = rig.run(block, level2)
    assert rig.seen["params"] == block and rig.seen["level2"] == level2
    assert after == block and level2_after == level2
    # the sampler, never stereo on 1..8: mono, the two record modes, chained mono, and those again with higher bits set
    for seed, modes in ((3, [0, 2, 3, 4, 6, 7, 8, 0x7e, 0, 1, 1, 5]), (9, [3, 2, 0, 4, 0x80, 0xfb, 0xfc, 2, 1, 1, 1, 1])):
        block, level2 = make_block([44] * 12, modes, seed=seed)
        rig.run(block, level2)
        assert rig.seen["params"] == block


def test_overlapping_pairs_restore_exactly(rig):
    block, level2 = make_block([44] * 12, [1, 5, 1, 5, 9, 1, 0xfd, 1, 1, 1, 1, 1], seed=4)   # every digital track says stereo
    ret, after, level2_after = rig.run(block, level2)
    assert after == block and level2_after == level2
    seen = rig.seen["params"]
    pans = [int.from_bytes(seen[STRIDE * t + P_PAN:][:2], "big") for t in range(8)]
    assert pans == [0] * 7 + [127 << 8]            # a chain of "left" tracks; only the last is a pure right
    assert seen[STRIDE * 8:] == block[STRIDE * 8:]                 # the analog tracks are never touched


# ---- audio mute -----------------------------------------------------------------------------

def vols(params):
    return [int.from_bytes(params[STRIDE * t + P_VOL:][:2], "big") for t in range(12)]


def muted_tracks(rig, block, level2, **state):
    """Run one mixer call; -> the tracks the mixer was shown at volume 0. Checks nothing else moved."""
    ret, after, level2_after = rig.run(block, level2, **state)
    assert after == block and level2_after == level2               # everything is put back
    seen, before = rig.seen["params"], vols(block)
    out = [t for t in range(12) if vols(seen)[t] == 0 and before[t] != 0]
    assert all(vols(seen)[t] == before[t] for t in range(12) if t not in out)
    quiet = bytearray(seen)
    for t in out:
        quiet[STRIDE * t + P_VOL:STRIDE * t + P_VOL + 2] = block[STRIDE * t + P_VOL:][:2]
    assert bytes(quiet) == block and rig.seen["level2"] == level2  # the volume word is the only thing changed
    return out


def test_mixer_takes_all_twelve_levels_from_the_same_volume_word(stock):
    """Why the analog tracks can be muted the same way: one loop, 12 tracks, one read of params + 124."""
    assert stock[mm.off(0x4008f2b6):mm.off(0x4008f2ba)] == bytes.fromhex(fw.sx("5a114ec6aad1a0a8"))     # mvs.w 124(a3),d7
    assert stock[mm.off(0x4008f4e0):mm.off(0x4008f4ec)] == bytes.fromhex(fw.sx("4e1f632227f717988a92b5f9ac251e50"))
    back = 0x4008f4ee + int.from_bytes(stock[mm.off(0x4008f4ee):mm.off(0x4008f4f0)], "big", signed=True)
    assert back == 0x4008f296 < 0x4008f2b6                       # the loop: 12 tracks, 142 bytes a track


def test_a_muted_track_is_shown_volume_zero(rig):
    block, level2 = make_block([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [0] * 12, seed=6)
    assert 0 not in vols(block)
    assert muted_tracks(rig, block, level2) == []
    assert muted_tracks(rig, block, level2, mutes=0b0000_0010_0010) == [1, 5]
    assert muted_tracks(rig, block, level2, pattern=0b1000_0001) == [0, 7]
    assert muted_tracks(rig, block, level2, mutes=0b10, pattern=0b100) == [1, 2]
    assert muted_tracks(rig, block, level2, mutes=0b0110_0000_0000) == [9, 10]         # analog tracks 10 and 11
    assert muted_tracks(rig, block, level2, pattern=0b1001_0000_0000) == [8, 11]
    assert muted_tracks(rig, block, level2, mutes=0x1000, pattern=0x1000) == []        # the FX track: not ours
    assert muted_tracks(rig, block, level2, mutes=0xffffffff) == list(range(12))


def test_solo_mutes_every_other_track_the_way_the_trig_code_does(rig):
    block, level2 = make_block([0] * 12, [0] * 12, seed=7)
    others = [t for t in range(12) if t != 2]
    assert muted_tracks(rig, block, level2, solos=0b100) == others
    assert muted_tracks(rig, block, level2, solos=0b100, mutes=0b100) == others                   # solo wins over mute
    assert muted_tracks(rig, block, level2, solos=0b100, pattern=0b100) == list(range(12))        # pattern mute still counts
    assert muted_tracks(rig, block, level2, solos=1 << 9) == [t for t in range(12) if t != 9]     # an analog track solo
    assert muted_tracks(rig, block, level2, solos=1 << 12) == list(range(12))                     # an FX track solo


def test_a_stereo_pair_is_muted_by_its_left_track_only(rig):
    machines, modes = [44, 0, 44, 0, 0, 0, 0, 0, 8, 9, 10, 11], [1, 0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0]     # pairs 0+1 and 2+3
    block, level2 = make_block(machines, modes, seed=8)
    ret, after, level2_after = rig.run(block, level2, mutes=0b0001)        # left of the first pair
    assert after == block and level2_after == level2
    assert [t for t in range(8) if vols(rig.seen["params"])[t] == 0] == [0, 1]
    rig.run(block, level2, mutes=0b1010)                                   # only the right-hand tracks
    seen = vols(rig.seen["params"])
    assert seen[1] == seen[0] != 0 and seen[3] == seen[2] != 0             # not muted: they follow their left
    rig.run(block, level2, pattern=0b0100, mutes=0b0010)
    assert [t for t in range(8) if vols(rig.seen["params"])[t] == 0] == [2, 3]
    ret, after, level2_after = rig.run(block, level2, solos=0b0001)        # solo the left of a pair: both stay
    assert [t for t in range(8) if vols(rig.seen["params"])[t] == 0] == [2, 3, 4, 5, 6, 7]
    assert after == block and level2_after == level2


# ---- the analog tracks' dry sound ----------------------------------------------------------------

@pytest.fixture(scope="module")
def arig(patched):
    return Rig(*patched, entry="mix_amute")


def shut_voices(arig, **state):
    """One mixer call through the analog mute; -> the analog voices whose two level words were set to 0.
    Checks that nothing else in the control block moved and that the mixer saw it already done."""
    block, level2 = make_block([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [0] * 12, seed=11)
    rng = np.random.default_rng(12)
    before = rng.integers(1, 256, CONTROL_BYTES, dtype=np.uint8).tobytes()      # no zero bytes: every word is open
    arig.mc.write(mm.CONTROL, before)
    ret, after, level2_after = arig.run(block, level2, **state)
    assert ret == 0x8000DBD0 and after == block and level2_after == level2
    got = arig.mc.read(mm.CONTROL, CONTROL_BYTES)
    assert arig.seen["control"] == got                             # done before the mixer runs, sent after it
    word = lambda b, k: b[2 * k:2 * k + 2]
    out = [v for v in range(4) if word(got, v) == b"\0\0"]
    want = bytearray(before)
    for v in out:
        want[2 * v:2 * v + 2] = want[10 + 2 * v:12 + 2 * v] = b"\0\0"  # left and right, nothing else
    assert got == bytes(want)
    return out


def test_a_muted_analog_track_has_both_its_level_controls_shut(arig):
    assert shut_voices(arig) == []
    assert shut_voices(arig, mutes=1 << 8) == [0]
    assert shut_voices(arig, mutes=1 << 11) == [3]
    assert shut_voices(arig, pattern=0b0110 << 8) == [1, 2]
    assert shut_voices(arig, mutes=1 << 9, pattern=1 << 10) == [1, 2]
    assert shut_voices(arig, mutes=0xffffffff) == [0, 1, 2, 3]     # the external input's two words stay as they are
    assert shut_voices(arig, mutes=0x10ff, pattern=0x10ff) == []   # digital and FX track mutes: not here


def test_solo_shuts_the_other_analog_tracks(arig):
    assert shut_voices(arig, solos=0b100) == [0, 1, 2, 3]          # a digital track solo
    assert shut_voices(arig, solos=1 << 9) == [0, 2, 3]
    assert shut_voices(arig, solos=(1 << 9) | (1 << 11)) == [0, 2]
    assert shut_voices(arig, solos=1 << 9, pattern=1 << 9) == [0, 1, 2, 3]     # a pattern mute still counts
    assert shut_voices(arig, solos=1 << 9, mutes=1 << 9) == [0, 2, 3]          # solo wins over mute


def test_analog_mute_hands_the_mixer_link_everything_unchanged(patched):
    """Same mixer call with and without the analog mute in front: the mixer is shown the same thing."""
    machines = [44, 0, 4, 44, 6, 44, 38, 44, 9, 10, 11, 12]
    block, level2 = make_block(machines, [1, 0, 1, 5, 0, 0, 1, 1, 0, 0, 0, 0], seed=13)
    seen = []
    for entry in ("mix_link", "mix_amute"):
        r = Rig(*patched, entry=entry)
        r.mc.write(mm.CONTROL, bytes(CONTROL_BYTES))
        r.run(block, level2, mutes=0b1001_0100_0010, pattern=0b10)
        seen.append({k: v for k, v in r.seen.items() if k != "control"})
    assert seen[0] == seen[1] and seen[0]["params"] != block


def test_where_the_dry_analog_levels_come_from(stock, patched):
    """Read from the listing: the block is filled before the mixer call, sent after it, and not named in between."""
    image, syms = patched
    assert mm.u32(image, mm.MIX_CALL + 2) == syms["mix_amute"] == mm.CAVE_AMUTE[0]
    be = build_main.be32
    assert stock[mm.off(mm.CONTROL_FILL):mm.off(mm.CONTROL_FILL) + 6] == b"\x48\x79" + be(mm.CONTROL)
    assert mm.CONTROL_FILL < mm.MIX_CALL < mm.CONTROL_SEND
    assert stock[mm.off(mm.CONTROL_SEND):mm.off(mm.CONTROL_SEND) + 6] == b"\x48\x79" + be(mm.CONTROL)
    assert stock[mm.off(mm.CONTROL_SEND) + 14:mm.off(mm.CONTROL_SEND) + 20] == b"\x4e\xb9" + be(0x401021b4)
    assert be(mm.CONTROL) not in stock[mm.off(mm.MIX_CALL):mm.off(mm.CONTROL_SEND)]
    # the per-voice routine: volume is params + 106 + 18, right-hand words start at block + 10,
    # both values are capped at 65535 and stored as words
    o = mm.off(0x40090060)
    assert stock[o:o + 8] == bytes.fromhex(fw.sx("857da3fa8395f7c7ebe4ea7c"))
    assert stock[mm.off(0x4008ffe6):mm.off(0x4008ffea)] == bytes.fromhex(fw.sx("b38047952cdbfb70"))     # lea 106(a0,d1),a3
    assert stock[mm.off(0x4009018a):mm.off(0x4009018c)] == bytes.fromhex("3081")         # move.w d1,(a0): left
    assert stock[mm.off(0x400901a0):mm.off(0x400901a2)] == bytes.fromhex("3280")         # move.w d0,(a1): right
    assert list(stock[mm.off(mm.VOICE_TRACK):mm.off(mm.VOICE_TRACK) + 4]) == [8, 9, 10, 11]
    assert mm.CAVE_AMUTE[1] == mm.PAN_HELPER


def test_volume_zero_is_silence_in_the_real_gain_function(rig):
    """The mixer's own gain function, run as it is: volume 0 gives gain 0 whatever the other inputs."""
    def gain(level, level2, vol, curve):
        rig.mc.emac.macsr = 0x20                       # signed fractional, as the mixer runs
        return rig.mc.call(mm.MIX_GAIN, level, level2, vol, curve)
    assert gain(127 << 8, 127 << 8, 100 << 8, 0) != 0
    for level, level2, curve in ((127 << 8, 127 << 8, 0), (0x7fff, 0x7fff, 3), (64 << 8, 1 << 8, 1), (1, 0x7f00, 2)):
        assert gain(level, level2, 0, curve) == 0


def test_mute_state_is_read_where_the_stock_code_reads_it(stock):
    """The three addresses, as operands of the stock trig code."""
    assert stock[mm.off(mm.MUTE_READ):][:6] == b"\x26\x39" + build_main.be32(mm.MUTES)
    assert stock[mm.off(mm.MUTE_READ) + 8:][:6] == b"\x20\x39" + build_main.be32(mm.SOLOS)
    assert stock[mm.off(mm.MUTE_TEST):][:6] == b"\x7f\xf9" + build_main.be32(mm.PATTERN_MUTES)
    assert mm.SOLOS == mm.MUTES + 4


def test_linked_pair_through_the_real_pan_law(rig):
    """The pans the mixer will read, fed to the main CPU's own pan law."""
    block, level2 = make_block([44, 0] + [0] * 10, [1] + [0] * 11, seed=5)
    rig.run(block, level2)
    mc = rig.mc
    gains = []
    for t in (0, 1):
        pan = int.from_bytes(rig.seen["params"][STRIDE * t + P_PAN:][:2], "big")
        mc.emac.macsr = 0x20
        left = -s32(mc.call(mm.PAN_LAW, pan)) / 2 ** 31
        gains.append((left, -s32(mc.reg(1)) / 2 ** 31))
    assert gains[0] == (1.0, 0.0)
    assert gains[1][1] == 1.0 and gains[1][0] < 1e-8


def test_mixer_call_site(stock, patched):
    image, syms = patched
    assert stock[mm.off(mm.MIX_CALL):mm.off(mm.MIX_CALL) + 6] == b"\x4e\xb9" + build_main.be32(mm.MIX)
    # the chain: call site -> analog mute -> mixer link -> mixer
    assert image[mm.off(mm.MIX_CALL):mm.off(mm.MIX_CALL) + 6] == b"\x4e\xb9" + build_main.be32(syms["mix_amute"])
    assert stock.count(b"\x4e\xb9" + build_main.be32(mm.MIX)) == 1       # the mixer has one caller
    lo, hi = mm.CAVE
    assert lo <= syms["mix_link"] < hi
    lo, hi = mm.CAVE_AMUTE
    assert lo <= syms["mix_amute"] < hi
    assert image[mm.off(lo):mm.off(hi)].count(build_main.be32(syms["mix_link"])) == 1
    assert image[mm.off(mm.CAVE[0]):mm.off(mm.CAVE[1])].count(build_main.be32(mm.MIX)) == 1


# ---- the full image -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def full(official_path):
    return build.build(official_path, log=lambda s: None, full=True)


def test_full_image_changes_only_declared_regions_of_3_and_7(full, official, patched):
    raw, _, built, regions, _ = full
    assert sorted(regions) == [3, 7]
    assert built.section(3) == patched[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    a, b = official.section(3), built.section(3)
    declared = set()
    for start, end in regions[3]:
        declared |= set(range(start, end))
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    assert changed and changed <= declared
    assert fw.Image(raw).section(3) == patched[0]          # survives the compressed round trip


def test_full_image_keeps_bootstrap_and_updater(full, official):
    _, _, built, _, _ = full
    for sid in (2, 4):
        assert built.container.by_id(sid).stored == official.container.by_id(sid).stored


def test_independent_tool_accepts_the_full_image(full, tmp_path):
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("no host C compiler")
    exe = tmp_path / "eft"
    subprocess.run([cc, "-O2", "-o", str(exe)] + sorted(glob.glob("third_party/elektron-firmware-tool/*.c")),
                   check=True, capture_output=True)
    p = tmp_path / "full.syx"
    p.write_bytes(full[0])
    report = subprocess.run([str(exe), "-i", str(p), "-v"], check=True, capture_output=True, text=True).stdout
    assert "MISMATCH" not in report
    subprocess.run([str(exe), "-i", str(p), "-o", str(tmp_path / "secs")], check=True, capture_output=True)
    got = {int(f.name.split("_")[1]): f.read_bytes() for f in (tmp_path / "secs").iterdir()}
    assert got[3] == full[2].section(3) and got[7] == full[2].section(7)
    for sid in (1, 2, 4, 5, 6, 8):
        assert fw.sha256(got[sid]) == fw.SECTION_SHA256["1.42"][sid]
