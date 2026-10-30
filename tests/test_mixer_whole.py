"""The main CPU's mixer run whole (section 3, OS 1.42): which sum goes where, and what it costs.

The real 0x4008f242 on marked track buffers. Not run: its five effect helpers (delay, reverb
and their set-up work on state made elsewhere) and the scale routine (the EMAC in integer
mode, which emu/ does not model); each is a return here, so nothing below reads a level
after the scale, only whether a place moves. Everything else is stock code as it is.
"""
import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

from emu.machine import Machine
from tools import mainmap as mm
from tools import fw

RTS = b"\x4e\x75"
PARAMS, STRUCTS, STRIDE = 0x80002000, 0x40700000, 142
OUT_FRAME = 0x80000000                      # the output frame, 8 slots of 32 frames, with the ring index at 0
SEND_PAIR_DONE = 0x4008f81a                 # after the first two kernel calls
CALLS = dict(k8=mm.MIX_KERNEL, k9=mm.MIX_KERNEL9, k10=mm.MIX_KERNEL10, copy=mm.MIX_COPY,
             gain=mm.MIX_GAIN, pan=mm.PAN_LAW, level=mm.MIX_LEVEL, scale=mm.MIX_SCALE)
COST = 20820                                # instructions a block; the three scale calls would add 3 x 187


@pytest.fixture(scope="module")
def sec3(official):
    assert official.version == "1.42"
    return official.section(3)


class Mixer:
    def __init__(self, sec3):
        mc = self.mc = Machine()
        for base, size in ((0x40000000, 0x800000), (0x80000000, 0x10000), (0x43bd0000, 0x10000),
                           (0x454e0000, 0x10000), (0x45540000, 0x10000), (0xfc000000, 0x100000)):
            mc.map(base, size)
        mc.write(mm.BASE, sec3)
        for a, b in ((mm.MIX_GAIN, mm.MIX_GAIN_END), (mm.MIX_GAIN2, mm.MIX_KERNEL_END), (mm.MIX_COPY, mm.MIX_END),
                     (mm.MIX_LEVEL, 0x4008ff8a), (mm.PAN_HELPER, mm.PAN_END),
                     (0x400955f8, 0x40095608),          # two accessors
                     (0x40097b08, 0x40097b22)):         # a level curve
            mc.load_code(a, sec3[mm.off(a):mm.off(b)])
        mc.set_stack(0x407ff000, 0x40000100)
        for a in mm.MIX_EFFECTS + (mm.MIX_SCALE,):
            mc.write(a, RTS)
        mc.w32(0x800030b8, STRUCTS)                     # the kit: 291 bytes a track, byte 205 the level curve
        mc.write(STRUCTS, bytes(291 * 12))
        mc.write(0x454e4c18, (0x7fffffff).to_bytes(4, "big") * 16)   # what 0x4008ee30 leaves there with its source off
        mc.write(mm.LEVEL2, (127 << 8).to_bytes(2, "big") * 16)
        self.snaps, self.calls = {}, {}
        mc.uc.hook_add(UC_HOOK_CODE, self._snap, ("send", mm.BUS_L), begin=SEND_PAIR_DONE, end=SEND_PAIR_DONE)
        mc.uc.hook_add(UC_HOOK_CODE, self._snap, ("dry", mm.BUS_DRY_L), begin=mm.MIX_DRY_DONE, end=mm.MIX_DRY_DONE)
        for name, addr in CALLS.items():
            mc.uc.hook_add(UC_HOOK_CODE, self._call, name, begin=addr, end=addr)
        mc.uc.ctl_flush_tb()

    def _snap(self, uc, address, size, user):
        name, bus = user
        self.snaps[name] = np.frombuffer(self.mc.read(bus, 256), dtype=">i4").reshape(32, 2).astype(np.int64)

    def _call(self, uc, address, size, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def run(self, tracks, pan=0, delay=0, reverb=0, blocks=6):
        """The same block several times, so the ramped gains arrive. -> (instructions of the last, output frame)."""
        mc = self.mc
        b = bytearray(0x800)
        for t in range(12):
            p = STRIDE * t
            b[2 * t:2 * t + 2] = (100 << 8).to_bytes(2, "big")          # the level words at the block's head
            b[p + 62] = 44 if t < 8 else 0
            for at, v in ((mm.P_DELAY_SEND, delay), (mm.P_REVERB_SEND, reverb), (mm.P_PAN, pan), (mm.P_VOL, 100)):
                b[p + at:p + at + 2] = (v << 8).to_bytes(2, "big")
        for k in range(blocks):
            mc.write(PARAMS, bytes(b))
            mc.write(mm.TRACKS, np.asarray(tracks).astype(">i4").tobytes())
            mc.write(mm.INPUTS, bytes(1024))
            self.calls = {}
            mc.emac.macsr = 0x20
            start = mc.insns
            assert mc.call(mm.MIX, 0, 0, PARAMS) == mm.BUS_L
        out = np.frombuffer(mc.read(OUT_FRAME, 1024), dtype=">i4").reshape(32, 8)
        return mc.insns - start, [k for k in range(8) if out[:, k].any()]


def one_track(seed=3):
    tracks = np.zeros((8, 32), dtype=np.int64)
    tracks[0] = np.random.default_rng(seed).integers(-2 ** 26, 2 ** 26, 32)
    return tracks


def test_the_dry_mix_is_at_dad0_and_dbd0_is_the_delay_send(sec3):
    """One track, panned hard left. With its sends at 0 the bus at 0x8000dbd0 stays silent."""
    tracks = one_track()
    dry = Mixer(sec3)
    cost, slots = dry.run(tracks)
    assert not dry.snaps["send"].any()                               # nothing on the bus the notes called the main one
    left, right = dry.snaps["dry"][:, 0], dry.snaps["dry"][:, 1]
    assert left.any() and not right.any()                            # hard left: the right side exactly empty
    assert np.corrcoef(left, tracks[0])[0, 1] > 0.999999
    assert slots == [7]                                              # the left side of the output frame
    assert Mixer(sec3).run(tracks, pan=127)[1] == [2]                # hard right is slot 2

    delay = Mixer(sec3)
    delay.run(tracks, delay=127)
    assert delay.snaps["send"][:, 0].any() and not delay.snaps["send"][:, 1].any()
    assert np.array_equal(delay.snaps["dry"], dry.snaps["dry"])      # the send takes nothing from the dry mix

    reverb = Mixer(sec3)
    reverb.run(tracks, reverb=127)
    assert not reverb.snaps["send"].any()                            # after the first pair: the reverb's sum comes later
    assert np.array_equal(reverb.snaps["dry"], dry.snaps["dry"])


def test_fourteen_kernel_passes_a_block(sec3):
    mx = Mixer(sec3)
    mx.run(one_track())
    assert mx.calls == dict(k8=8, k9=2, k10=4, copy=6, gain=24, pan=14, level=12, scale=3)


def test_a_kernel_replaces_its_destination(sec3):
    """So a sum cannot be added to a bus by one more pass: it needs a buffer of its own."""
    mx = Mixer(sec3)
    mc = mx.mc
    mc.write(mm.TRACKS, np.random.default_rng(1).integers(-2 ** 27, 2 ** 27, (8, 32)).astype(">i4").tobytes())
    gains, incs, dest = 0x80006000, 0x80006100, 0x80006200
    got = []
    for fill in (b"\0\0\0\0", fw.sb("9f7cc770a4cd8734")):
        mc.write(gains, np.full(8, -(2 ** 29), dtype=">i4").tobytes())
        mc.write(incs, np.full(8, 4096, dtype=">i4").tobytes())
        mc.write(dest, fill * 64)
        mc.emac.macsr = 0xA0
        start = mc.insns
        mc.call(mm.MIX_KERNEL, dest, mm.TRACKS, gains, incs)
        assert mc.insns - start == 686
        got.append(np.frombuffer(mc.read(dest, 256), dtype=">i4").reshape(32, 2))
    assert np.array_equal(got[0][:, 0], got[1][:, 0]) and got[0][:, 0].any()
    assert (got[1][:, 1] == 0x12345678).all()                        # the other side is not touched
    after = np.frombuffer(mc.read(gains, 32), dtype=">i4")
    assert (after == -(2 ** 29) + 32 * 4096).all()                   # the ramped gains are written back


def test_what_the_mixer_costs_without_its_effects(sec3):
    """The same count whatever plays: nothing in the mixer's own work depends on the sound."""
    busy = np.random.default_rng(5).integers(-2 ** 26, 2 ** 26, (8, 32))
    counts = [Mixer(sec3).run(t, pan=64, delay=d, reverb=d)[0]
              for t, d in ((np.zeros((8, 32), dtype=np.int64), 0), (busy, 0), (busy, 100))]
    assert all(abs(c - COST) <= 2 for c in counts)
