"""The Syntakt audio engine (section 7) running its real voice loop.

Boot is replayed the way 0x400004bc and 0x40000512 do it, voices are set up
the way 0x40000fd6 does it, then the real 0x40004324 is called once per
32-frame block. No UI, sequencer, track filter, mixer or effects: this is
the per-track machine output, 32-bit mono, before everything downstream.
"""
import wave

import numpy as np

from tools import audiomap as m

from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

from .machine import Machine

RATE = 48000
BLOCK = 32
RET = 0x40000100              # below the image: mapped, never executed
AFTER_VOICE_INIT = 0x40001860  # clears the state of the stages after the voice loop

# The audio interrupt, for the whole per-block path (Phase 4)
ISR = 0x40000934
ISR_RTE = 0x40000b1e          # Unicorn cannot run RTE; the interrupt is run up to it
HOST = 0x0                    # window shared with the main CPU, audio CPU view
HOST_SIZE = 0x1b0             # parameter block in
HOST_AUDIO = 0x1b0            # 8 track buffers out
HOST_MIRROR = 0x80008000      # where the interrupt copies the block
TCD47 = 0xfc0455e0            # eDMA channel 47 descriptor
DMA_START = 0xfc04401e
# return addresses in the interrupt, after each stage that touches the track buffers
STAGE_ENDS = {"voice_loop": 0x40000a3a, "gain": 0x40000a4c, "drive": 0x40000a60,
              "filter": 0x40000aa4, "amp": 0x40000ac2}
# parameter block layout, per track: (host offset, stride, [param offsets])
HOST_FIELDS = ((160, 8, (82, 86, 102, 104)), (224, 14, (108, 110, 112, 114, 116, 128, 130)))


class Engine:
    def __init__(self, image, loop_entry=m.VOICE_LOOP):
        """loop_entry: what block() calls. The stock voice loop, or a hook with the
        same arguments (the sampler's, which also runs its post step)."""
        self.image = bytes(image)
        self.loop_entry = loop_entry
        mc = self.mc = Machine()
        mc.map(0x40000000, m.STACK_TOP - 0x40000000)
        mc.map(m.SRAM, m.SRAM_END - m.SRAM)
        mc.write(m.BASE, self.image)
        mc.load_code(m.BASE + 4, self.image[4:m.off(m.CODE_END)])
        if len(self.image) > m.off(m.IMAGE_END):     # the back image: what the start's copy puts at m.FAR (tests/test_back.py runs it)
            mc.load_code(m.FAR, self.image[m.off(m.IMAGE_END):])
        mc.set_stack(m.STACK_TOP - 0x100, RET)
        self._boot()
        self._init_voices()

    def _boot(self):
        mc, img = self.mc, self.image
        lo, hi = m.SRAM_LO_SRC, m.SRAM_HI_SRC
        mc.write(m.SRAM, img[m.off(lo[0]):m.off(lo[1])])
        mc.write(m.SRAM_HI, img[m.off(hi[0]):m.off(hi[1])])
        # BSS starts inside the image; everything above it is still zero
        mc.write(m.BSS[0], bytes(m.IMAGE_END - m.BSS[0]))

    def _init_voices(self):
        mc = self.mc
        for i in range(m.N_VOICES):
            mc.call(m.NOISE_SEED)
            mc.w32(self.voice(i) + 0x56c, m.VOICE_TMP + 0x30 * i)
            mc.call(m.VOICE_RESET, self.voice(i))
        mc.call(m.SLOT_BUILD)
        mc.call(AFTER_VOICE_INIT)

    # addresses
    def voice(self, track):
        return m.VOICES + m.VOICE_SIZE * track

    def params(self, track):
        return m.PARAM_BUF + m.PARAM_STRIDE * track

    # control, in UI units
    def set_machine(self, track, mtype):
        self.mc.write(self.params(track) + m.PARAM_TYPE, bytes((mtype,)))

    def set_slot(self, track, slot, value):
        """Knob slot (8.8). value is the UI number, fractions allowed."""
        v = int(round(value * 256)) & 0xFFFF
        self.mc.write(self.params(track) + m.PARAM_KNOBS + 2 * slot, v.to_bytes(2, "big"))

    def set_defaults(self, track, mtype, params):
        """Select a machine with factory knob settings. params: tools.params.machines()."""
        self.set_machine(track, mtype)
        for slot in range(18, 27):
            self.set_slot(track, slot, 0)
        for p in params[mtype]:
            self.set_slot(track, p.slot, p.default)

    def set_note(self, track, note):
        self.mc.w32(m.PMOD + 4 * track, int(round(note * 65536)))

    def load_pool(self, slots):
        """slots: {slot: int16 array}. Writes the pool and rebuilds the slot table."""
        blob = bytearray()
        for s in range(m.SLOTS):
            x = np.asarray(slots.get(s, ()), dtype=">i2")
            blob += len(x).to_bytes(4, "big") + x.tobytes()
        if len(blob) > m.POOL_SIZE:
            raise ValueError("pool overflow")
        self.mc.write(m.POOL, bytes(blob))
        self.mc.call(m.SLOT_BUILD)

    # audio
    def block(self, trig=0, release=0):
        """Run the voice loop once. Returns int32 array (8 tracks, 32 frames)."""
        self.mc.call(self.loop_entry, m.OUT_BUF, m.PARAM_BUF, trig, release)
        raw = self.mc.read(m.OUT_BUF, m.N_VOICES * m.OUT_STRIDE)
        return np.frombuffer(raw, dtype=">i4").reshape(m.N_VOICES, BLOCK).astype(np.int32)

    def render(self, blocks, trig=0, release_at=None):
        """Trig on the first block, optional release, return (8, frames) int32."""
        out = []
        for b in range(blocks):
            out.append(self.block(trig if b == 0 else 0, trig if b == release_at else 0))
        return np.concatenate(out, axis=1)

    def player(self, track, which):
        """Twinshot sample player state (which: 0 or 1) as a dict."""
        a = self.voice(track) + (m.TWIN_PLAYER_A, m.TWIN_PLAYER_B)[which]
        names = ("ptr", "next_ptr", "pos", "len", "next_len", "playing", "inc", "reverse", "loop")
        return {n: self.mc.r32(a + 4 * k) for k, n in enumerate(names)}


class Board(Engine):
    """Engine plus the shared window and peripheral space, to run the real interrupt.

    Knobs are set as on Engine; interrupt() packs them into the parameter block
    the main CPU would send, runs 0x40000934, and returns what the audio CPU
    hands back: the 8 track buffers after its filter and amp stages.
    self.stages holds the track buffers after each stage of the last interrupt.
    """

    def __init__(self, image):
        super().__init__(image)
        self.mc.map(HOST, 0x2000)
        self.mc.map(0xfc000000, 0x100000)
        self.mc.map(0xec090000, 0x10000)
        self.extra = bytearray(HOST_SIZE - 0x170)   # block bytes 0x170.. that are not knobs
        # the main CPU's side of the knobs: what goes into the block every interrupt,
        # whatever the audio CPU does to its own copy in between
        self.host_params = bytearray(m.PARAM_STRIDE * m.N_VOICES)
        self.host_pmod = bytearray(4 * m.N_VOICES)
        self.mc.set_exits([RET, ISR_RTE])
        self.stages = {}
        for name, addr in STAGE_ENDS.items():
            self.mc.uc.hook_add(UC_HOOK_CODE, self._stage_hook, name, begin=addr, end=addr)
        self.mc.uc.ctl_flush_tb()

    def _tracks(self, addr):
        raw = self.mc.read(addr, m.N_VOICES * m.OUT_STRIDE)
        return np.frombuffer(raw, dtype=">i4").reshape(m.N_VOICES, BLOCK).astype(np.int32)

    def _stage_hook(self, uc, address, size, name):
        self.stages[name] = self._tracks(m.OUT_BUF)
        # static fields of the DMA descriptor, as init sets them at 0x40001020..0x40001046:
        # 16-byte transfers, source and destination step 16, 16 bytes per request
        self.mc.write(TCD47 + 4, (0x0404).to_bytes(2, "big") + (16).to_bytes(2, "big"))
        self.mc.w32(TCD47 + 8, 16)
        self.mc.write(TCD47 + 0x16, (16).to_bytes(2, "big"))

    def set_machine(self, track, mtype):
        self.host_params[m.PARAM_STRIDE * track + m.PARAM_TYPE] = mtype

    def set_slot(self, track, slot, value):
        v = int(round(value * 256)) & 0xFFFF
        o = m.PARAM_STRIDE * track + m.PARAM_KNOBS + 2 * slot
        self.host_params[o:o + 2] = v.to_bytes(2, "big")

    def set_note(self, track, note):
        self.host_pmod[4 * track:4 * track + 4] = (int(round(note * 65536)) & 0xFFFFFFFF).to_bytes(4, "big")

    def set_cutoff(self, track, value):
        """Per-track 32-bit word at block offset 0x188, passed to the filter stage."""
        at = 0x188 - 0x170 + 4 * track
        self.extra[at:at + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")

    def host_block(self, trig=0, release=0):
        b = bytearray(HOST_SIZE)
        for t in range(m.N_VOICES):
            p = self.host_params[m.PARAM_STRIDE * t:m.PARAM_STRIDE * (t + 1)]
            b[20 * t:20 * t + 20] = p[62:82]
            for base, stride, offs in HOST_FIELDS:
                for k, o in enumerate(offs):
                    at = base + stride * t + 2 * k
                    b[at:at + 2] = p[o:o + 2]
        b[0x150:0x170] = self.host_pmod
        b[0x170:] = self.extra
        b[0x180], b[0x181] = trig, release
        return bytes(b)

    def interrupt(self, trig=0, release=0):
        mc = self.mc
        mc.write(HOST, self.host_block(trig, release))
        mc.write(TCD47 + 0x1e, b"\x00\x80")          # DONE, so the wait for the last DMA falls through
        mc.uc.reg_write(UC_M68K_REG_A7, m.STACK_TOP - 0x100)
        mc.run(ISR, ISR_RTE)
        src, dst, n = self.dma()
        mc.write(dst, mc.read(src, n))                 # what the DMA would do
        return self._tracks(HOST + HOST_AUDIO)

    def dma(self):
        """(source, destination, bytes) of the transfer the interrupt starts on channel 47."""
        mc = self.mc
        if mc.read(DMA_START, 1)[0] != 47:
            raise RuntimeError("channel 47 was not started")
        citer = int.from_bytes(mc.read(TCD47 + 0x14, 2), "big")   # bit 15 links, low 9 bits count
        return mc.r32(TCD47), mc.r32(TCD47 + 0x10), (citer & 0x1FF) * mc.r32(TCD47 + 8)


def write_wav(path, x, rate=RATE):
    """Mono int32 to 32-bit PCM WAV."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(4)
        w.setframerate(rate)
        w.writeframes(np.asarray(x, dtype="<i4").tobytes())
