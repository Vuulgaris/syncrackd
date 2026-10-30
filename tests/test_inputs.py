"""Where the analog tracks and the external input reach the main CPU. Section 3, OS 1.42.

Static checks of the listing, plus the two copy routines run on marked data.
Nothing here says what the converters carry on hardware: the slot names come
from the factory test's own strings and from which track's parameters the
code applies to which buffer.
"""
import numpy as np
import pytest

from emu.machine import Machine
from tools import mainmap as mm
from tools import fw


@pytest.fixture(scope="module")
def sec3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main_cpu(sec3):
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x80000000, 0x10000)
    mc.write(mm.BASE, sec3)
    for a, b in ((mm.RX_UNPACK, mm.RX_UNPACK_END), (mm.FRAME_TO_INPUTS, mm.FRAME_TO_INPUTS_END)):
        mc.load_code(a, sec3[mm.off(a):mm.off(b)])
    mc.set_stack(0x407ff000, 0x40000100)
    return mc


def cstr(image, addr):
    o = mm.off(addr)
    return image[o:image.index(b"\0", o)].decode("ascii")


def test_a_dma_channel_fills_a_ring_from_the_serial_audio_port(sec3):
    assert mm.u32(sec3, 0x4000101a + 2) == mm.RX_RING           # move.l #ring,d0
    assert mm.u32(sec3, 0x40001030 + 2) == mm.RX_TCD + 0x10     # -> destination
    assert mm.u32(sec3, 0x40001036 + 2) == mm.RX_PORT           # move.l #port,d0
    assert mm.u32(sec3, 0x40001042 + 2) == mm.RX_TCD            # -> source
    assert (mm.RX_TCD - 0xfc045000) // 32 == 52
    assert sec3[mm.off(0x40001064):mm.off(0x40001066)] == bytes.fromhex("7220")       # 32 bytes a request: 8 slots
    assert mm.u32(sec3, 0x40001066 + 2) == mm.RX_TCD + 8
    assert sec3[mm.off(0x4000106c):mm.off(0x40001070)] == bytes.fromhex(fw.sx("0ee31ad56fd375b8"))   # 64 requests: 2 x 32 frames
    assert mm.u32(sec3, 0x4000107a + 2) == mm.RX_TCD + 0x14
    # the per-block routine finds the fresh half from the channel's write address
    assert mm.u32(sec3, 0x400a38f0 + 2) == mm.RX_TCD + 0x10
    assert mm.u32(sec3, 0x400a38f6 + 2) == mm.RX_RING


def test_the_block_routine_unpacks_the_ring_just_before_the_mixer(sec3):
    assert mm.u32(sec3, 0x400a4fd8 + 2) == mm.RX_UNPACK
    assert [mm.u32(sec3, a + 2) for a in (0x400a4fde, 0x400a4fe4, 0x400a4fea)] == [mm.FRAME, mm.INPUTS, mm.FRAME_TO_INPUTS]
    assert mm.u32(sec3, mm.MIX_CALL + 2) == mm.MIX
    assert 0x400a4fea < mm.MIX_CALL


def test_factory_test_names_the_receive_slots(sec3):
    names = [cstr(sec3, mm.u32(sec3, mm.ADC_NAMES + 4 * i)) for i in range(8)]
    assert names == ["VOICE_1", "VOICE_2", "VOICE_3", "VOICE_4", "FX_L", "FX_R", "EXT_IN_L", "EXT_IN_R"]
    assert mm.u32(sec3, 0x400a5840 + 2) == mm.ADC_NAMES


def test_mixer_takes_tracks_9_to_12_from_the_first_four_input_buffers(sec3):
    # per track gain loop, 12 tracks: 0..7 from TRACKS + 128 * i, 8..11 from INPUTS + 128 * (i - 8)
    assert mm.u32(sec3, 0x4008fe7a + 2) == mm.TRACKS
    assert mm.u32(sec3, 0x4008fe82 + 2) == mm.INPUTS - 8 * 128
    assert sec3[mm.off(0x4008fe9e):mm.off(0x4008fea2)] == bytes.fromhex(fw.sx("6dd6a109fad06b1a"))   # moveq #12,d0 ; cmp.l d2,d0


def test_input_stage_uses_the_fx_track_parameters_on_buffers_6_and_7(sec3):
    # 0x4008ec34(inputs, params, ...): four voices with track 9..12 parameters, then one stereo pair
    assert mm.u32(sec3, 0x4008ec64 + 2) == 8 * 142 + 106
    assert mm.u32(sec3, 0x4008ecea + 2) == 128 * mm.IN_FX_L
    assert mm.u32(sec3, 0x4008ecf6 + 2) == 128 * mm.IN_FX_R
    assert mm.u32(sec3, 0x4008ecf0 + 2) == 12 * 142 + 140        # track 13 is the FX track


def marked_ring():
    """Slot s of frame n holds a 24-bit value that names both."""
    return np.array([[(s + 1) * 0x10000 + n for s in range(8)] for n in range(32)], dtype=np.int64)


@pytest.mark.parametrize("half", [0, 1])
def test_ring_slots_land_in_the_frame_and_then_in_the_input_buffers(main_cpu, half):
    mc = main_cpu
    ring = marked_ring()
    mc.write(mm.RX_RING, bytes(2048))
    mc.write(mm.RX_RING + 1024 * half, ring.astype(">i4").tobytes())
    mc.write(mm.FRAME, bytes(32 * 4 * mm.FRAME_CH))
    mc.emac.macsr = 0xA0
    mc.call(mm.RX_UNPACK, half, mm.FRAME)
    frame = np.frombuffer(mc.read(mm.FRAME, 32 * 4 * mm.FRAME_CH), dtype=">i4").reshape(32, mm.FRAME_CH).astype(np.int64)

    # the four plain pairs: negated, 24 bits moved up to 32
    for slot, ch in ((4, mm.F_FX_L), (5, mm.F_FX_R), (6, mm.F_EXT_L), (7, mm.F_EXT_R)):
        assert frame[:, ch].tolist() == (-(ring[:, slot] << 8)).tolist()
    # the four voices: negated too, with one fixed trim gain
    trim = 2 * 0x6bb2d604 / 2 ** 31
    for slot in range(4):
        want = -(ring[:, slot] << 8) * trim
        assert np.allclose(frame[:, mm.F_T9 + slot], want, rtol=0, atol=512)
    used = [mm.F_T9, mm.F_T9 + 1, mm.F_T9 + 2, mm.F_T9 + 3, mm.F_FX_L, mm.F_FX_R, mm.F_EXT_L, mm.F_EXT_R]
    assert not frame[:, [c for c in range(mm.FRAME_CH) if c not in used]].any()

    mc.write(mm.INPUTS, bytes(1024))
    mc.call(mm.FRAME_TO_INPUTS, mm.INPUTS, mm.FRAME)
    inputs = np.frombuffer(mc.read(mm.INPUTS, 1024), dtype=">i4").reshape(8, 32).astype(np.int64)
    for k in range(4):
        assert inputs[mm.IN_T9 + k].tolist() == frame[:, mm.F_T9 + k].tolist()
    assert inputs[mm.IN_EXT_L].tolist() == (-(ring[:, 6] << 8)).tolist()
    assert inputs[mm.IN_EXT_R].tolist() == (-(ring[:, 7] << 8)).tolist()
    assert inputs[mm.IN_FX_L].tolist() == (-(ring[:, 4] << 8)).tolist()
    assert inputs[mm.IN_FX_R].tolist() == (-(ring[:, 5] << 8)).tolist()


def test_mixer_leaves_all_twenty_channels_in_the_frame(sec3):
    # 0x4008febc..0x4008ff1a: digital tracks to channels 2..9, tracks 9..12 to 10..13, FX return to 14, 15.
    # Channels 18 and 19 are not written again: they keep the external input as unpacked from the ring.
    o = mm.off(0x4008febc)
    assert sec3[o:o + 4] == bytes.fromhex(fw.sx("5e9c057d99296b3b"))                       # move.l (a1),8(a0)
    assert mm.u32(sec3, 0x4008fea6 + 2) == mm.FRAME
    assert mm.u32(sec3, 0x4008feac + 2) == mm.TRACKS
    assert mm.u32(sec3, 0x4008feb2 + 2) == mm.INPUTS
    assert sec3[mm.off(0x4008feee):mm.off(0x4008ff10)] == bytes.fromhex(
        fw.sx("c055391517e047d5bdf0cf03da84d501ce2547a30987a50c6697ef26f034b5bcb0fa41743154"))
    # main bus to channels 0 and 1, the two send returns summed to 16 and 17
    assert mm.u32(sec3, 0x4008fbec + 2) == mm.FRAME
    assert mm.u32(sec3, 0x4008fc22 + 2) == mm.FRAME + 4 * mm.F_SENDS_L
