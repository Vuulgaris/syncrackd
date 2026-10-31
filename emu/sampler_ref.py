"""Reference model of the sampler engine (engine/sampler.c). This is the spec.

Pure Python integers, written for clarity. tests/test_sampler.py holds the compiled engine, running in the real voice
loop, bit-identical to this.

Knobs (UI units, fractions allowed; the engine sees them as 8.8):
SAMPLE  64..127 plays number v-64 forward, 63..0 plays number 63-v in reverse.
In mono the number is a slot. In stereo it is a stereo sample: number n
is slots 2n (left) and 2n+1 (right), and past 31 there is nothing.
START   0..127   where the region begins, as a fraction of the whole sample
LENGTH  0..127   how much of what is left to play; 127 is all of it
LOOP    0 one-shot, 1 loop, 2 ping-pong (the low two bits, 3 is ping-pong too)
MODE    0 mono, 1 stereo; +4 chain. 2 and 3 are the recorder's: here they play as mono
Stereo: slot n is left, slot n+1 right (so chains step by two slots).
Chain: consecutive non-empty slots play as one long sample.
A loop is the whole region: it goes back to where the note started.

Player(pool, fade=True) is the fade image's engine (engine/sampler.h, FADE): where the sound is cut into, it is faded
and not switched. A note that starts inside the sample fades in over FADE_IN frames; a one-shot that ends inside the
sample fades out over the FADE_OUT frames before its end; a forward loop fades out before its seam and in after it,
the seam staying where it was. Nothing else changes: a frame at full gain is the frame the plain engine puts out.

Player(pool, fade=True, live=True) is the live image's engine (engine/sampler.h, LIVE and LIVE_STRT): LENGTH and START
act while the note plays. With strt=False it is the len image's: LENGTH alone, START the note's own. move(start,
length) is what the engine does once a block in which no note starts. A note is a row of passes: a pass begins at a
place and is as long as the knobs have the region, counted from where it began. LENGTH moves the playing pass's far
end at once. A loop's next pass begins where the knobs have the start by then, and nothing is done to the pass that is
playing; a ping-pong takes the new start when it is back where its pass began. The far end come in behind the place
played from: a loop's next pass begins now and a one-shot is over, between a fade out and a fade in when the region is
long enough to have fades at its seam; a ping-pong turns where it is. A block in which the knobs have not moved is the
fade engine's.

Player(..., hq=True) is the pitch image's engine (engine/sampler.h, HQ): a frame between two of the sample's is no
longer on the line between them. It is the sum of 16 frames around it, each times a number from a table of a windowed
sinc (tools/sinctable.py): the row for the top 5 bits of the fraction and the next row, blended by the low 7. On a
frame of the sample itself, fraction 0, it is that frame as before. Past either end of the slot the end frame stands
in.

Player(..., auto=True) is the mode image's engine (engine/sampler.h, AUTO): MODE no longer says how a track plays.
SAMPLE always counts the 32 samples, number n in slots 2n and 2n + 1, and a sample is stereo when its second slot
holds exactly as many frames as its first, mono when it does not.

Player(..., pack=True) is the pack image's (PACK; it is auto too): SAMPLE's 64 values are 64 places. The first 32 are
the stereo samples as above. The other 32 are the slots 32 to 63 by their own number, each a mono sample whatever the
slot after it holds.

Player(..., xfade=True) is the cross image's (XFADE; it is auto too): a forward or backward loop's end is blended into
its start where the fade image dipped. The last XF_W frames of the sample a pass plays are those frames going down as
the XF_W frames before the place the next pass begins come up, so the pass ends on the very frame the next begins
after, and nothing is switched. With nothing before the start to blend with (STRT at 0), the seam is XF_W frames later
on both sides: the pass runs on past its end into what follows it there, as the frames after the start come up under
it, and the next pass begins XF_W frames in. A loop is as long as it was either way. With neither (a loop of the whole
sample) the dip stays. The blended frames are written out ahead, XF_STEP a block, from the block after the note starts
or the seam's two places last moved, and not in a block a fade is on in: a seam reached before they are all there dips
as it did. A pass that has gone into its blend is left alone by the knobs until it is through.
"""
N_SLOTS = 64
MAX_FRAMES = 0x7FF00  # 255 short of the stock clamp: room for one pitch step, see sampler.h
BLOCK = 32
MAX_EDGES = 40  # seams and turns a block may take before the note stops, see sampler.h
MODE_KIND, MODE_STEREO, MODE_CHAIN = 3, 1, 4
FADE_ONE, FADE_IN, FADE_OUT = 4096, 64, 128
LEN_MIN = 3 << 8  # the floor image: the least LENGTH, 8.8
HQ_TAPS, HQ_BEFORE = 16, 7  # the pitch image: frames in the sum, and how many of them come before frame i
HQ_TOP = (1 << 30) - 1  # the sum is held to this either way before it is doubled
# The cross image: frames blended; frames written out after them, on the side the seam leads to, and before them, on
# the side the pass comes from (8 for the sums and the most a frame's step can be); frames written a block.
XF_W, XF_NEAR, XF_FAR, XF_STEP = 256, 16, 80, 8
XF_N = XF_FAR + XF_W + XF_NEAR
XF_REACH = XF_W + XF_FAR - 8  # frames before its wall a pass goes into its blend


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def knob(value):
    """UI value -> the 16-bit 8.8 word the engine reads."""
    return int(round(value * 256)) & 0xFFFF


def scale(x, v):
    """x * v / 32768, the way the engine computes it."""
    return (((x >> 8) * v) >> 7) + (((x & 0xFF) * v) >> 15)


class Player:
    def __init__(self, pool, fade=False, live=False, strt=True, floor=False, hq=False, auto=False, xfade=False, pack=False):
        """pool: {slot: sequence of int16}."""
        self.auto = auto or xfade or pack
        self.pack = pack
        self.single = False
        self.xfades = xfade
        self.xn, self.xuse, self.xkey = 0, 0, (0, 0)  # frames of the blend written; 1 this block may go into it, 2 it is in it; the seam's wall and where it leads
        self.xl, self.xr = [0] * XF_N, [0] * XF_N
        self.hq = None
        if hq:  # the pitch image: the table the engine builds its copy of
            from tools import sinctable
            assert (sinctable.TAPS, sinctable.BEFORE) == (HQ_TAPS, HQ_BEFORE)
            self.hq = sinctable.rows12() if hq == 12 else sinctable.rows()  # hq=12: the table of twelve, the same sum
        self.floor = LEN_MIN if floor else 0  # the floor image: LENGTH is taken as no less
        self.pool = {k: [int(x) for x in v] for k, v in pool.items()}
        self.playing = False
        self.inc = 4096
        self.fades = fade
        self.lives = live and fade
        self.strts = strt  # START is followed too
        self.strt16 = 0
        self.fade, self.fstep, self.span, self.fwall = FADE_ONE, 0, 0, False
        self.duck = False
        self.r = None

    def frames(self, k):
        return min(len(self.pool.get(k, ())), MAX_FRAMES) if k < N_SLOTS else 0

    def _locate(self, k, last, x, end):
        while True:
            n = self.frames(k)
            if x < n or k >= last or (end and x == n):
                return k, x
            x -= n
            k += self.stride

    def note_on(self, sample=64, start=0, length=127, loop=0, mode=0):
        v = (knob(sample) >> 8) - 64
        m = knob(mode) >> 8
        play = (knob(loop) >> 8) & 3
        rev = v < 0
        if rev:
            v = -v - 1
        v = min(v, N_SLOTS - 1)
        self.stereo = self.auto or m & MODE_KIND == MODE_STEREO
        self.single = self.pack and v >= N_SLOTS // 2  # the pack image: a slot of the back half, by its own number
        self.stride = 2 if self.stereo else 1
        if self.stereo and not self.single:
            v *= 2
        self.xn = self.xuse = 0
        first = last = v
        total = self.frames(first)
        if m & MODE_CHAIN:
            while self.frames(last + self.stride):
                last += self.stride
                total += self.frames(last)
        self.playing = False
        self.mode = 2 if play == 3 else play
        self.dir0 = self.dir = -1 if rev else 1

        len16 = max(knob(length), self.floor)
        a = scale(total, knob(start))
        b = total if len16 >= 127 << 8 else a + scale(total - a, len16)
        if b - a < 2:
            return
        if b - a < 4:
            self.mode = 0
        if self.fades:
            cut_in = b < total if rev else a > 0  # the note starts inside the sample
            cut_out = a > 0 if rev else b < total  # its far end is inside the sample
            self.fade = 0 if cut_in else FADE_ONE
            self.fstep = FADE_ONE // FADE_IN if cut_in else 0
            self.span = b - a
            self.fwall = self.mode == 1 or (self.mode == 0 and cut_out)
            self.duck = False
        self.strt16 = knob(start)
        self.ka, self.pa = self._locate(first, last, a, False)
        self.kb, self.pb = self._locate(first, last, b, True)
        self.kc, self.pc = (self.kb, self.pb) if rev else (self.ka, self.pa)
        if rev:
            self._enter(self.kb)
            self.pos = (self.pb - 1) << 12
        else:
            self._enter(self.ka)
            self.pos = self.pa << 12
        self.playing = True

    def _wall(self):
        if self.dir == self.dir0:
            return (self.kb, self.pb) if self.dir0 > 0 else (self.ka, self.pa)
        if self.lives:
            return (self.ka, self.pa) if self.dir0 > 0 else (self.kb, self.pb)
        return self.kc, self.pc

    def _pass(self):
        """A pass begins: where the knobs have the start now, as long as they have the region now, inside the slot."""
        if self.dir0 > 0:
            self.pa = self.pc
            self.pb = min(self.pa + self.span, self.n)
        else:
            self.pb = self.pc
            self.pa = max(self.pb - self.span, 0)

    def _enter(self, k):
        n = self.frames(k)
        wall_k, wall_p = self._wall()
        self.k, self.n = k, n
        self.l = self.pool.get(k, ())
        if self.auto:  # a stereo sample: both slots as long, and its place no single slot
            self.r = self.pool.get(k + 1) if self.frames(k + 1) == n and not self.single else None
        else:
            self.r = self.pool.get(k + 1) if self.stereo and self.frames(k + 1) >= n else None
        if k != wall_k:
            wall_p = n if self.dir > 0 else 0
        self.bound = wall_p << 12

    def _edge(self):
        wall = self.bound
        over = self.pos - wall if self.dir > 0 else wall - self.pos
        wall_k, _ = self._wall()
        if self.k != wall_k:  # chain: the neighbouring slot
            if self.dir > 0:
                self._enter(self.k + self.stride)
                self.pos = over
            else:
                self._enter(self.k - self.stride)
                self.pos = (self.n << 12) - over
            return
        if self.lives:
            if self.dir == self.dir0 and self.mode == 0:
                self.playing = False
                return
            # a loop at its far end, or a ping-pong back where its pass began with the start moved since: the next
            # pass
            if self.mode == 1 if self.dir == self.dir0 else self.pc != (self.pa if self.dir0 > 0 else self.pb):
                self.dir = self.dir0
                self._pass()
                self.fwall = self.mode == 1
                self._enter(self.kc)
                if self.xuse == 2:  # through the blend: on from where it was made to lead, and no fade
                    self.pos = (self.xkey[1] << 12) + (over if self.dir > 0 else -over)
                else:
                    self.pos = (self.pc << 12) + (over if self.dir > 0 else -over)
                    self.fstep = FADE_ONE // FADE_IN
                self.xuse = 0
                return
        elif self.dir == self.dir0:
            if self.mode == 0:
                self.playing = False
                return
            if self.mode == 1:  # loop: keep the overshoot, so the period is exact
                self._enter(self.kc)
                self.pos = (self.pc << 12) + (over if self.dir > 0 else -over)
                if self.fades:
                    self.fstep = FADE_ONE // FADE_IN  # back up from wherever the fade out got to
                return
        self.dir = -self.dir  # ping-pong turn, reflected about the last frame
        self._enter(self.k)
        self.pos = wall + over if self.dir > 0 else wall - 8192 - over

    def move(self, start=0, length=127):
        """START and LENGTH as they are in a block in which no note starts."""
        if not (self.lives and self.playing):
            return
        if self.xuse == 2:  # a pass inside its blend: the knobs wait until it is through
            return
        self._knobs(start, length)
        if self.xfades and self.playing:
            self._xstep()

    def _zone(self):
        """Where the blend's frames begin, as a position: a pass is in them from there to its wall."""
        return (self.xkey[0] + (XF_REACH if self.dir0 < 0 else -XF_REACH)) << 12

    def _outside(self):
        return self.pos >= self._zone() if self.dir0 < 0 else self.pos < self._zone()

    def _first(self):
        """The frame of the sample the first of the blend's frames stands for."""
        return self.xkey[0] - (XF_NEAR if self.dir0 < 0 else XF_W + XF_FAR)

    def _xstep(self):
        """Once a block, after the knobs: the seam the loop has now, and XF_STEP frames more of its blend."""
        if self.mode != 1:
            return
        rev = self.dir0 < 0
        w, c, e = (self.pa if rev else self.pb), self.pc, 0
        if self.span < self.inc >> 2:  # a loop too short to be faded at all is left as it is
            self.xn = 0
            return
        if self.fstep:  # the blocks of a fade are work enough: the blend waits
            return
        ok = True
        if c + XF_W > self.n if rev else c < XF_W:  # nothing before the start to blend with: after the end, then
            e = -XF_W if rev else XF_W
            ok = ok and (w >= XF_W if rev else w + XF_W <= self.n)
        if not ok:
            self.xn = 0
            return
        key = (w + e, c + e)
        if not self.xn or key != self.xkey:
            self.xkey, self.xn = key, 0
        if self.xn >= XF_N:
            return
        w, c = key
        for k in range(self.xn, self.xn + XF_STEP):
            i = self._first() + k  # a frame of the pass, and the one it is blended with
            j = i - w + c
            g = min(max(XF_W + XF_NEAR - k if rev else k - XF_FAR, 0), XF_W)
            for x, out in ((self.l, self.xl), (self.r, self.xr)):
                if x is not None:  # (a frame from outside the slot counts for nothing where it is read)
                    a = x[i] if 0 <= i < len(x) else 0
                    b = x[j] if 0 <= j < len(x) else 0
                    assert (0 <= i < len(x) or g == XF_W) and (0 <= j < len(x) or g == 0)
                    out[k] = a + (((b - a) * g) >> 8)
        self.xn += XF_STEP

    def _knobs(self, start, length):
        len16 = max(knob(length), self.floor)
        total = self.n
        a = scale(total, knob(start) if self.strts else self.strt16)
        b = total if len16 >= 127 << 8 else a + scale(total - a, len16)
        rev = self.dir0 < 0
        start_ = b if rev else a  # where the knobs have a pass begin now
        span = b - a
        began = self.pb if rev else self.pa  # where this pass began
        # and where it ends: as far on as the knobs have the region long, or at the sample's end when they have it go
        # there
        end = began - span if rev else total if b == total else began + span
        at = self.pos >> 12
        if span < 4 or (start_ == self.pc and span == self.span and not self.duck and (self.mode != 2 or start_ == began)):
            return
        end = min(max(end, 0), total)
        caught = self.dir == self.dir0 and (at < end if rev else at >= end)  # the far end is behind the place played from
        if self.fade if self.duck else (caught and (self.mode == 0 or (self.mode == 1 and span >= self.inc >> 2))):
            self.duck = True  # down first, with the pass as it was
            self.fstep = -(FADE_ONE // FADE_OUT)
            return
        self.pc = start_
        self.span = span
        if rev:
            self.pa = end
        else:
            self.pb = end
        if caught:
            if self.mode == 2:
                self.dir = -self.dir  # a ping-pong turns where it is
            elif self.mode == 0:
                self.playing = False
            else:  # a loop: its next pass, now
                self._pass()
                self.pos = (self.pb - 1 if rev else self.pa) << 12
        began = self.pb if rev else self.pa
        if self.duck:  # it was done at nothing: up again
            self.duck = False
            self.fstep = FADE_ONE // FADE_IN
        self.fwall = self.mode == 1 or ((self.pa > 0 if rev else self.pb < total) if self.mode == 0
                                        else (self.dir != self.dir0 and self.pc != began))
        self.bound = (began if self.dir != self.dir0 else self.pa if rev else self.pb) << 12
        ahead = self.bound - self.pos if self.dir > 0 else self.pos - self.bound
        if self.fstep < 0 and ahead > FADE_OUT * self.inc:
            self.fstep = FADE_ONE // FADE_IN  # a fade out before a wall that has moved away

    def _fade_move(self):
        """After a frame of a fade: move the gain. A fade in ends at FADE_ONE, a fade out stays at nothing."""
        g = self.fade + self.fstep
        if g >= FADE_ONE:
            g, self.fstep = FADE_ONE, 0
        self.fade = max(g, 0)

    def _hq(self, x, i, f):
        """Frame i + f/4096 of x, at the level the line gave it: the frame times 65536."""
        if not f:
            return s32(x[i] << 16)
        r0, r1 = self.hq[f >> 7], self.hq[(f >> 7) + 1]
        d0 = d1 = 0
        for k in range(HQ_TAPS):
            v = x[min(max(i + k - HQ_BEFORE, 0), self.n - 1)]
            d0 = s32(d0 + v * r0[k])
            d1 = s32(d1 + v * r1[k])
        d0 = s32(d0 + (s32(d1 - d0) >> 7) * (f & 127))
        return s32(min(max(d0, -HQ_TOP - 1), HQ_TOP) << 1)

    def _hqz(self, x, i, f):
        """Frame i + f/4096 of the blend's frames: the same sum, and every frame of it is there."""
        if not f:
            return s32(x[i] << 16)
        r0, r1 = self.hq[f >> 7], self.hq[(f >> 7) + 1]
        d0 = d1 = 0
        for k in range(HQ_TAPS):
            v = x[i + k - HQ_BEFORE]
            d0 = s32(d0 + v * r0[k])
            d1 = s32(d1 + v * r1[k])
        d0 = s32(d0 + (s32(d1 - d0) >> 7) * (f & 127))
        return s32(min(max(d0, -HQ_TOP - 1), HQ_TOP) << 1)

    def block(self, stereo_out=True):
        """32 frames of raw player output: (left, right or None)."""
        left, right = [], []
        want_r = (self.r is not None if self.auto else self.stereo) and stereo_out
        tries = MAX_EDGES
        if self.xfades and self.playing and self.mode == 1 and self.xuse != 2:
            # may this block's pass go into the blend: it is all written, no fade is on (in a block of one the seam is
            # not worked out again, and the blend may be another seam's), and the pass was short of it when that was
            # first so (it may have come to it since, with the last frame of a block)
            self.xuse = int(self.xn >= XF_N and not self.fstep and bool(self.xuse or self._outside()))
        # the fade out starts this far from the wall, if the wall is a cut and the region is long enough for it
        near = FADE_OUT * self.inc if self.fades and self.fwall and self.span >= self.inc >> 2 else 0
        if self.xfades and self.xuse and self.playing and self.mode == 1:
            near = 0  # the blend is the seam: no dip before it
        live = self.fades and bool(near or self.fstep or self.fade != FADE_ONE)  # a fade to look after in this block at all
        for _ in range(BLOCK):
            a = b = 0
            if self.playing:
                i, f = self.pos >> 12, self.pos & 0xFFF
                if self.lives:
                    assert 0 <= i < self.n  # nothing is read from outside the slot
                j = i + 1 if i + 1 < self.n else i
                if self.xuse == 1 and not self._outside():
                    self.xuse = 2  # into the blend: from here to its wall its frames are played
                    self.bound = self.xkey[0] << 12
                if self.xuse == 2:
                    at = i - self._first()
                    a = self._hqz(self.xl, at, f)
                    if want_r and self.r is not None:
                        b = self._hqz(self.xr, at, f)
                elif self.hq:
                    a = self._hq(self.l, i, f)
                    if want_r and self.r is not None:
                        b = self._hq(self.r, i, f)
                else:
                    a = s32((self.l[i] * (4096 - f) + self.l[j] * f) << 4)
                    if want_r and self.r is not None:
                        b = s32((self.r[i] * (4096 - f) + self.r[j] * f) << 4)
                if live and self.fade != FADE_ONE:  # 28 bits of sample: 9 dropped before the product, 3 after
                    a = s32(((((a >> 4) >> 9) * self.fade) >> 3) << 4)
                    b = s32(((((b >> 4) >> 9) * self.fade) >> 3) << 4)
                self.pos += self.inc if self.dir > 0 else -self.inc
                while self.pos >= self.bound if self.dir > 0 else self.pos < self.bound:
                    if tries == 0:
                        self.playing = False
                    else:
                        tries -= 1
                        self._edge()
                    if not self.playing:
                        break
                if live:
                    if self.fstep:
                        self._fade_move()
                    elif near and (self.bound - self.pos if self.dir > 0 else self.pos - self.bound) <= near:
                        self.fstep = -(FADE_ONE // FADE_OUT)  # the wall is near: down to it
            left.append(a)
            right.append(b)
        return left, (right if want_r else None)


def tail(buf, trig=False):
    """What the stock amp and mix stages do to a player buffer, decay knob at 127.

    Steady state: the amp level is -1.0 (applied with MSAC, so unity) and the mix gain is 0.5. In a block with a trig
    both ramp to zero over the 32 frames, which fades the old note out before the new one starts.
    """
    level, level_step = -(1 << 31), 0
    gain, gain_step = 1 << 30, 0
    if trig:
        level_step = min((1 << 31) - 1, 0 - level) >> 5
        gain_step = (0 - gain) >> 5
    out = []
    for x in buf:
        y = (-((level * x) >> 23)) >> 8  # MSAC, then MOVCLR
        level = max(-(1 << 31), min((1 << 31) - 1, level + level_step))
        out.append(((y * gain) >> 23) >> 8)  # MAC, then MOVCLR
        gain += gain_step
    return out


# ---- the srr image: sample rate reduction (engine/sampler.h, SRR)
# ----------------------------------------------------

def srr_step(word):
    """The knob's 8.8 word -> what the hold's phase goes up by a frame, of 2^32. 0: off."""
    length = (256 + (word >> 4 & 255)) << (word >> 12 & 7)  # the hold's length, in 256ths of a frame
    return (0xFFFFFFFF // length + 1) << 8 if length > 256 else 0


class Hold:
    """A voice's hold: the frames the player made, a block at a time, each kept until the phase runs over."""

    def __init__(self):
        self.phase, self.kept = 0xFFFFFFFF, None

    def block(self, frames, word, start=False):
        """frames: (n, channels), or None in a block the voice does not play. -> the block as it is put out."""
        step = srr_step(word)
        if not step or start:
            self.phase = 0xFFFFFFFF  # off, or a note's start: the next frame is let through
        if not step or frames is None:
            return frames
        out = [None] * len(frames)
        for n, x in enumerate(frames):
            self.phase += step
            if self.phase >> 32:
                self.phase &= 0xFFFFFFFF
                self.kept = tuple(x)
            out[n] = self.kept
        return out
