"""The audio CPU's whole interrupt, stopped at three places: what the stereo image's tests are built on.

A Rig is emu.engine.Board with pauses after the voice loop, before the interrupt's call of its
last stage and after it. A stock one can be fed any signal in place of what the voices made, so
that "what stock makes of this signal on a track" can be asked for and held against.
"""
import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC

from emu import engine as E
from tools import audiomap as m

AFTER_VOICES, AMP_CALL, AFTER_AMP = 0x40000a3a, m.ISR_AMP_CALL, m.ISR_AMP_CALL + 6
PAUSES = (AFTER_VOICES, AMP_CALL, AFTER_AMP)
STASH = m.STASH
# knob slots the audio CPU is sent for its four stages, and the most each goes to
STAGE_KNOBS = {26: 127, 27: 7, 29: 127, 37: 127, 38: 127, 40: 127, 41: 127, 42: 127, 43: 127, 44: 127, 50: 1, 51: 1}


class Rig(E.Board):
    def __init__(self, image):
        super().__init__(image)
        self.resume = None
        for a in PAUSES:
            self.mc.uc.hook_add(UC_HOOK_CODE, self._pause, None, begin=a, end=a)
        self.mc.uc.ctl_flush_tb()
        self.cost = {}

    def _pause(self, uc, address, size, user):
        if self.resume == address:
            self.resume = None
        else:
            uc.emu_stop()

    def go(self, start, stop):
        """From one pause to the next. A pause is a hook that stops, so that a run can begin on one."""
        mc = self.mc
        self.resume = start if start in PAUSES else None
        before = mc.insns
        mc.uc.emu_start(start, 0)
        pc = mc.uc.reg_read(UC_M68K_REG_PC)
        assert pc == stop, "from %#x: stopped at %#x, not %#x" % (start, pc, stop)
        assert not (mc.native and mc.emac.state.fault)
        self.cost[stop] = mc.insns - before

    def stage_knobs(self, rng, tracks=range(8)):
        """Every knob of the four stages somewhere else, and the two things the main CPU works out for them."""
        for t in tracks:
            for slot, top in STAGE_KNOBS.items():
                self.set_slot(t, slot, int(rng.integers(0, top + 1)))
            self.set_cutoff(t, int(rng.integers(0, 0x7f000000)))
        self.extra[0x1a8 - 0x170] = int(rng.integers(0, 256))

    def tracks(self, addr):
        return self._tracks(addr)

    def block(self, trig=0, release=0, feed=None):
        """One interrupt. feed: 8 x 32 in place of what the voices made.
        -> (the voices' buffers, the right channels waiting, the left after the last stage)"""
        mc = self.mc
        mc.write(E.HOST, self.host_block(trig, release))
        mc.write(E.TCD47 + 0x1e, b"\x00\x80")
        mc.uc.reg_write(UC_M68K_REG_A7, m.STACK_TOP - 0x100)
        self.go(E.ISR, AFTER_VOICES)
        if feed is not None:
            mc.write(m.OUT_BUF, np.asarray(feed).astype(">i4").tobytes())
        voices, waiting = self.tracks(m.OUT_BUF), self.tracks(STASH)
        self.go(AFTER_VOICES, AMP_CALL)
        self.go(AMP_CALL, AFTER_AMP)
        left = self.tracks(m.OUT_BUF)
        self.go(AFTER_AMP, E.ISR_RTE)
        return voices, waiting, left

    # what the stereo image leaves in the window
    def word(self):
        return self.mc.r32(m.RW_HEAD)

    def mask(self):
        w = self.word()
        assert w == m.rw_word(w & 0xff), hex(w)
        return w & 0xff

    def right(self, t):
        """Track t's right channel as the main CPU would read it: two halves."""
        raw = b"".join(self.mc.read(m.rw_half(h), 64) for h in (2 * t, 2 * t + 1))
        return np.frombuffer(raw, dtype=">i4").astype(np.int32)


def stock_of(image, script, feeds):
    """What stock's four stages make of `feeds` (blocks x 8 x 32) on its eight tracks, the knobs and trigs
    those of `script`: a list of (set-up routine or None, trig, release) a block."""
    r = Rig(image)
    out = []
    for (prepare, trig, release), feed in zip(script, feeds):
        if prepare:
            prepare(r)
        out.append(r.block(trig, release, feed)[2])
    return np.array(out)
