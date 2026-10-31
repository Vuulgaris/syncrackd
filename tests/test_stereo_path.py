"""Phase 4: where the track buffers go after the voice loop, and where pan is applied."""
import numpy as np
import pytest

from emu import engine as E
from emu.emac import s32
from emu.machine import Machine
from emu.render import test_pool as make_pool
from tools import audiomap as m
from tools import mainmap as mm
from tools import params
from tools import fw

TWIN = 44
PAN, VOL, DELAY_SEND, REVERB_SEND = 47, 48, 45, 46


@pytest.fixture(scope="module")
def image(official):
    return official.section(7)


@pytest.fixture(scope="module")
def sec3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def descs(sec3):
    return params.machines(sec3, "1.42")


@pytest.fixture(scope="module")
def track_defaults(sec3):
    """Factory values of the digital tracks' Filter (47) and Amp (45) pages."""
    return {p.slot: p.default for p in params.load(sec3, "1.42") if p.type in (47, 45)}


def board(image, descs, track_defaults, notes=(60,) * 8):
    e = E.Board(image)
    e.load_pool(make_pool())
    for t in range(m.N_VOICES):
        e.set_defaults(t, TWIN, descs)
        e.set_note(t, notes[t])
        for slot, v in track_defaults.items():
            e.set_slot(t, slot, v)
        e.set_cutoff(t, 0x60000000)
    return e


# ---- audio CPU -------------------------------------------------------------

def test_pan_and_volume_are_ui_parameters_of_the_track(sec3):
    amp = {p.short: p.slot for p in params.load(sec3, "1.42") if p.type == 45}
    assert (amp["PAN"], amp["VOL"], amp["REV"]) == (PAN, VOL, REVERB_SEND)
    assert mm.P_PAN == 0x1c + 2 * PAN and mm.P_VOL == 0x1c + 2 * VOL
    assert mm.P_DELAY_SEND == 0x1c + 2 * DELAY_SEND and mm.P_REVERB_SEND == 0x1c + 2 * REVERB_SEND


def test_audio_cpu_never_receives_pan_volume_or_sends(image):
    """Fill the whole incoming block with a marker; see which track parameters arrive."""
    e = E.Board(image)
    mc = e.mc
    mc.write(m.PARAM_BUF, bytes(m.PARAM_STRIDE * m.N_VOICES))
    block = bytearray(b"\x5a" * E.HOST_SIZE)
    block[0x180:0x184] = bytes(4)  # no trigs
    e.host_block = lambda trig=0, release=0: bytes(block)
    e.interrupt()
    p = mc.read(m.PARAM_BUF, m.PARAM_STRIDE)
    written = {o for o in range(m.PARAM_STRIDE) if p[o]}
    slots = sorted({(o - 0x1c) // 2 for o in written if o >= 0x40})
    assert slots == list(range(18, 28)) + [29, 37, 38, 40, 41, 42, 43, 44, 50, 51]
    assert written - {62, 63} == {0x1c + 2 * s + k for s in slots for k in (0, 1)}
    for slot in (PAN, VOL, DELAY_SEND, REVERB_SEND):
        assert slot not in slots


def test_audio_cpu_hands_over_eight_mono_buffers(image, descs, track_defaults):
    e = board(image, descs, track_defaults)
    for b in range(4):
        out = e.interrupt(0x01 if b == 0 else 0)
    assert e.dma() == (m.OUT_BUF, E.HOST + E.HOST_AUDIO, m.N_VOICES * m.OUT_STRIDE)
    assert np.array_equal(out, e.stages["amp"])  # the DMA carries the final track buffers
    assert e.stages["voice_loop"][0].any() and out[0].any() and not out[1:].any()
    # the block in and the audio out are the whole shared area init clears
    assert E.HOST_SIZE + m.N_VOICES * m.OUT_STRIDE == 0x5b0 == m.u32(image, 0x40000e98) & 0xFFFF  # pea 0x5b0, the memset at init


def test_dma_static_fields_are_what_init_programs(image):
    # 0x40001020: movea.w #0x0404,a0 (ATTR); moveq #16 -> SOFF, NBYTES, DOFF
    assert image[m.off(0x40001020):m.off(0x40001026)] == bytes.fromhex(fw.sx("4137670c09cee47569da"))
    assert image[m.off(0x40001032):m.off(0x40001034)] == bytes.fromhex("7210")
    for insn, reg in ((0x40001034, E.TCD47 + 4), (0x4000103a, E.TCD47 + 6),
                      (0x40001040, E.TCD47 + 8), (0x40001046, E.TCD47 + 0x16)):
        assert m.u32(image, insn + 2) == reg


def test_tracks_do_not_bleed_into_each_other(image, descs, track_defaults):
    """Track 0 through the post stages is bit-identical whether or not track 1 plays."""
    def run(trig):
        e = board(image, descs, track_defaults, notes=(60, 67, 60, 60, 60, 60, 60, 60))
        stages = []
        for b in range(12):
            e.interrupt(trig if b == 0 else 0)
            stages.append(dict(e.stages))
        return stages
    alone, both = run(0x01), run(0x03)
    for name in ("voice_loop", "gain", "drive", "filter", "amp"):
        a = np.concatenate([s[name] for s in alone], axis=1)
        b = np.concatenate([s[name] for s in both], axis=1)
        assert a[0].any(), name
        assert np.array_equal(a[0], b[0]), name  # track 0 unchanged by track 1
        assert b[1].any() and not a[1].any(), name
        assert not b[2:].any(), name  # nothing leaks into the other tracks


# ---- main CPU (section 3, OS 1.42) -----------------------------------------

def test_main_cpu_copies_the_track_buffers_out_of_the_window(sec3):
    assert mm.u16(sec3, mm.DMA_SETUP + 2) == 0xDE40  # 64 iterations, linked to itself
    assert mm.u32(sec3, 0x400a4802 + 2) == mm.TRACKS  # lea TRACKS,a2
    assert mm.u32(sec3, 0x400a4808 + 2) == E.TCD47 + 0x10  # -> destination
    assert mm.u32(sec3, 0x400a480e + 2) == mm.SHARED_AUDIO  # movea.l #window+0x1b0,a3
    assert mm.u32(sec3, 0x400a4814 + 2) == E.TCD47  # -> source
    assert mm.u32(sec3, 0x400a482c + 2) == E.DMA_START
    assert mm.u32(sec3, 0x40082fe8 + 2) == mm.SHARED_CHUNK  # boot sample chunks go here


def test_main_cpu_mixer_reads_pan_and_volume_and_calls_the_pan_law(sec3):
    assert sec3[mm.off(0x4008f2b6):mm.off(0x4008f2ba)] == bytes.fromhex(fw.sx("5a114ec6aad1a0a8"))  # mvs.w 124(a3),d7
    assert sec3[mm.off(0x4008f2f8):mm.off(0x4008f2fc)] == bytes.fromhex(fw.sx("995e1e2b3ec8bebc"))  # mvs.w 122(a3),d7
    assert mm.u32(sec3, 0x4008f300 + 2) == mm.PAN_LAW
    assert mm.u16(sec3, 0x4008f3fe + 2) == mm.P_DELAY_SEND
    assert mm.u16(sec3, 0x4008f402 + 2) == mm.P_REVERB_SEND
    # two passes of the mix kernel over the DMA'd track buffers: left, then right. These two are the delay send's sum;
    # the dry mix is another pair of passes, with the same pan gains (tests/test_mixer_whole.py)
    assert [mm.u32(sec3, a + 2) for a in (0x4008f7ea, 0x4008f7f0, 0x4008f7f6)] == [mm.GAIN_L, mm.TRACKS, mm.BUS_L]
    assert [mm.u32(sec3, a + 2) for a in (0x4008f806, 0x4008f80c, 0x4008f812)] == [mm.GAIN_R, mm.TRACKS, mm.BUS_R]
    assert 0x4008f7fc + 2 + int.from_bytes(sec3[mm.off(0x4008f7fe):mm.off(0x4008f800)], "big", signed=True) == mm.MIX_KERNEL


@pytest.fixture(scope="module")
def main_cpu(sec3):
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x80000000, 0x10000)
    mc.write(mm.BASE, sec3)
    for a, b in ((mm.PAN_HELPER, mm.PAN_END), (mm.MIX_KERNEL, mm.MIX_KERNEL_END)):
        mc.load_code(a, sec3[mm.off(a):mm.off(b)])
    mc.set_stack(0x407ff000, 0x40000100)
    return mc


def pan_gains(mc, pan):
    mc.emac.macsr = 0x20
    left = s32(mc.call(mm.PAN_LAW, pan * 256))
    return -left / 2 ** 31, -s32(mc.reg(1)) / 2 ** 31


def test_pan_law_isolates_hard_panned_tracks(main_cpu):
    left = pan_gains(main_cpu, 0)
    right = pan_gains(main_cpu, 127)
    assert left == (1.0, 0.0)  # hard left: nothing at all on the right bus
    assert right[1] == 1.0 and 0 <= right[0] <= 4 / 2 ** 31  # hard right: 4 lsb on the left
    centre = pan_gains(main_cpu, 64)
    assert centre == pytest.approx((0.75, 0.75), abs=1e-8)  # parabolic sine: 0.75, not 0.707
    gains = [pan_gains(main_cpu, pan) for pan in range(128)]
    lefts, rights = [g[0] for g in gains], [g[1] for g in gains]
    assert lefts == sorted(lefts, reverse=True) and rights == sorted(rights)
    assert all(0 <= g <= 1 for g in lefts + rights)


def test_mix_kernel_sums_mono_tracks_into_one_side_of_the_stereo_bus(main_cpu):
    mc = main_cpu
    rng = np.random.default_rng(1)
    tracks = rng.integers(-2 ** 27, 2 ** 27, size=(8, 32), dtype=np.int64)
    gains = [-(2 ** 31) + 1, -(2 ** 30), 0, -(2 ** 29), 0, 0, -123456789, -(2 ** 28)]
    mc.write(mm.TRACKS, tracks.astype(">i4").tobytes())
    g_addr, inc_addr = 0x80006000, 0x80006100
    mc.write(g_addr, np.array(gains, dtype=">i4").tobytes())
    mc.write(inc_addr, bytes(32))
    mc.write(mm.BUS_L, bytes(8 * 32))
    mc.emac.macsr = 0xA0
    mc.call(mm.MIX_KERNEL, mm.BUS_L, mm.TRACKS, g_addr, inc_addr)
    bus = np.frombuffer(mc.read(mm.BUS_L, 8 * 32), dtype=">i4").reshape(32, 2)
    want = []
    for n in range(32):
        acc = 0
        for k in range(8):
            acc -= (gains[k] * int(tracks[k, n])) >> 23  # MSAC of a negative gain
        want.append(max(-2 ** 31, min(2 ** 31 - 1, acc >> 8)))
    assert bus[:, 0].tolist() == want
    assert not bus[:, 1].any()  # the other side is left alone


def test_two_hard_panned_tracks_come_out_as_left_and_right(main_cpu):
    """Pan law gains fed to the real mix kernel: track 0 hard left, track 1 hard right."""
    mc = main_cpu
    rng = np.random.default_rng(2)
    tracks = np.zeros((8, 32), dtype=np.int64)
    tracks[0] = rng.integers(-2 ** 28, 2 ** 28, 32)
    tracks[1] = rng.integers(-2 ** 28, 2 ** 28, 32)
    mc.write(mm.TRACKS, tracks.astype(">i4").tobytes())
    sides = []
    for side, bus in ((0, mm.BUS_L), (1, mm.BUS_R)):
        gains = [0] * 8
        for t, pan in ((0, 0), (1, 127)):
            mc.emac.macsr = 0x20
            g = (mc.call(mm.PAN_LAW, pan * 256), mc.reg(1))[side]
            gains[t] = s32(g)
        mc.write(0x80006000, np.array(gains, dtype=">i4").tobytes())
        mc.write(0x80006100, bytes(32))
        mc.write(mm.BUS_L, bytes(8 * 32))
        mc.emac.macsr = 0xA0
        mc.call(mm.MIX_KERNEL, bus, mm.TRACKS, 0x80006000, 0x80006100)
        sides.append(np.frombuffer(mc.read(mm.BUS_L, 8 * 32), dtype=">i4").reshape(32, 2)[:, side].astype(np.int64))
    left, right = sides
    # unity gain on its own side, the other track absent, within 1 lsb of 32 bits
    assert np.abs(left - tracks[0]).max() <= 1
    assert np.abs(right - tracks[1]).max() <= 1
