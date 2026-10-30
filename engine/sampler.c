/* Sampler engine for the Syntakt audio CPU, in Twinshot's place (machine type 44).
 *
 * One sample per voice, with start, length, loop, ping-pong, reverse, stereo
 * pairs and chained slots. A loop is the whole region: there is no loop point.
 * Behaviour is specified by the reference model emu/sampler_ref.py; tests hold
 * this code bit-identical to it.
 * Plain integer code: no EMAC, no libgcc, no data sections. (With QUICK the sums of
 * sixteen frames are made in the EMAC, in engine/stub.S: see sampler.h.)
 *
 * The code goes into two runs of stock functions that nothing references
 * (tools/audiomap.py CAVES). Stock Twinshot is left in place, unreached.
 *
 * Positions are 20.12 inside the current slot. A region [a, b) can span
 * several slots (chain); the "wall" is where travel ends in the current
 * direction: the far end of the region, or the end it started from on the
 * way back in ping-pong.
 */
#include "sampler.h"

#define CAVE(n) __attribute__((section(".cave." #n), noinline))
#ifdef FADE
#define XW w                /* the fade image: two small routines move to its fourth run, for room in the first */
#else
#define XW x
#endif
#define CAVE2(n) CAVE(n)
#ifdef HQ
/* The pitch image: the table takes the third run whole, and what was there, with the step after
 * the voice loop, moves to runs of its own. */
#define ZY t
#define ZR r
#define ZQ q
#define YP p
#else
#define ZY z
#define ZR z
#define ZQ z
#define YP y
#endif
#ifdef LIVE
#define YW w                /* the live images: one routine moves to the fourth run, for room in the second */
#else
#define YW y
#endif

#ifdef XFADE
/* The cross image: where its routines go, in the room the mode image's engine left. */
#define XO s
#define XM k
#define XG o
#define XT z
#define XK w
#endif
#ifdef TRIM
#undef XK
#define XK e                /* the trim image: the seam's routine grows, into the hits image's run */
#endif

#ifdef LEAN
#define YA a                /* the third build: one small routine moves to a run of the right channels', for room in the second */
#else
#define YA y
#endif
CAVE2(YA) static s32 slot_frames(u32 k)
{
    u32 n = k < N_SLOTS ? SLOT[k].frames : 0;
    return n > MAX_FRAMES ? MAX_FRAMES : n;
}

/* x * v / 32768 without a 64-bit product. x < 2^26, v < 2^15. */
CAVE2(XW) static u32 scale(u32 x, u32 v)
{
    return (((x >> 8) * v) >> 7) + (((x & 0xff) * v) >> 15);
}

#ifdef AUTO
#define HOME(s) ((s)->k)    /* the mode image: a note has one slot, and its second is a right channel or nothing */
/* The note's slot as the table has it now, and where travel in it ends. */
CAVE2(YW) static void enter(struct st *s, u32 k)
{
    s32 n = slot_frames(k);
    s32 wall_p = s->dir0 > 0 ? s->pa : s->pb;   /* on the way back: to where this pass began */

    if (s->dir == s->dir0)
        wall_p = s->dir0 > 0 ? s->pb : s->pa;
    s->frames = n;
    s->l = SLOT[k].data;
#ifdef PACK
    s->r = s->stereo && slot_frames(k + 1) == n ? SLOT[k + 1].data : 0;         /* and its place is no single slot */
#else
    s->r = slot_frames(k + 1) == n ? SLOT[k + 1].data : 0;      /* a stereo sample: both slots as long */
#endif
    s->bound = wall_p << 12;
}
#else
#define HOME(s) ((s)->kc)
/* Point the player at slot k and work out where travel in it ends. */
CAVE2(YW) static void enter(struct st *s, u32 k)
{
    s32 n = slot_frames(k);
    u32 wall_k = s->kc;
#ifdef LIVE
    s32 wall_p = s->dir0 > 0 ? s->pa : s->pb;   /* on the way back: to where this pass began */
#else
    s32 wall_p = s->pc;
#endif

    if (s->dir == s->dir0) {
        wall_k = s->dir0 > 0 ? s->kb : s->ka;
        wall_p = s->dir0 > 0 ? s->pb : s->pa;
    }
    s->k = k;
    s->frames = n;
    s->l = SLOT[k].data;
    s->r = (s->stereo && slot_frames(k + 1) >= n) ? SLOT[k + 1].data : 0;
    if (k != wall_k)
        wall_p = s->dir > 0 ? n : 0;
    s->bound = wall_p << 12;
}
#endif

#ifdef LIVE
/* A pass begins: where the knobs have the start now, as long as they have the region now, inside the slot. */
CAVE(u) static void pass(struct st *s)
{
#ifdef XFADE
    s->xnew = 1;                    /* and its seam is another */
#endif
    if (s->dir0 > 0) {
        s->pa = s->pc;
        s->pb = s->pa + s->span;
        if (s->pb > s->frames)
            s->pb = s->frames;
    } else {
        s->pb = s->pc;
        s->pa = s->pb - s->span;
        if (s->pa < 0)
            s->pa = 0;
    }
}
#endif

/* pos has passed bound: next slot of a chain, or the wall (stop, loop, turn). */
CAVE(y) static void edge(struct st *s)
{
    s32 wall = s->bound;
    s32 over = s->dir > 0 ? s->pos - wall : wall - s->pos;
#ifndef AUTO
    u32 wall_k = s->kc;

    if (s->dir == s->dir0)
        wall_k = s->dir0 > 0 ? s->kb : s->ka;
    if (s->k != wall_k) {
        if (s->dir > 0) {
            enter(s, s->k + s->stride);
            s->pos = over;
        } else {
            enter(s, s->k - s->stride);
            s->pos = (s->frames << 12) - over;
        }
        return;
    }
#endif
#ifdef LIVE
    if (s->dir == s->dir0 && s->mode == 0) {
        s->playing = 0;
        return;
    }
    /* a loop at its far end, or a ping-pong back where its pass began with the start moved since: the next pass */
    if (s->dir == s->dir0 ? s->mode == 1 : s->pc != (s->dir0 > 0 ? s->pa : s->pb)) {
#ifdef XFADE
        s32 to = s->pc << 12;

        s->dir = s->dir0;
        pass(s);
        s->fwall = s->mode == 1;
        enter(s, HOME(s));
        if (s->xuse == 2)
            to = XF(s)->to;                     /* through the blend: on from where it was made to lead, and no fade */
        else
            s->fstep = FADE_ONE / FADE_IN;      /* a cut: back up from wherever the fade out got to */
        s->pos = to + (s->dir > 0 ? over : -over);
        s->xuse = 0;
        return;
#else
        s->dir = s->dir0;
        pass(s);
        s->fwall = s->mode == 1;
        enter(s, HOME(s));
        s->pos = (s->pc << 12) + (s->dir > 0 ? over : -over);
        s->fstep = FADE_ONE / FADE_IN;          /* back up from wherever the fade out got to */
        return;
#endif
    }
#else
    if (s->dir == s->dir0) {
        if (s->mode == 0) {
            s->playing = 0;
            return;
        }
        if (s->mode == 1) {
            enter(s, HOME(s));
            s->pos = (s->pc << 12) + (s->dir > 0 ? over : -over);
#ifdef FADE
            s->fstep = FADE_ONE / FADE_IN;      /* back up from wherever the fade out got to */
#endif
            return;
        }
    }
#endif
    s->dir = -s->dir;
    enter(s, s->k);
    s->pos = s->dir > 0 ? wall + over : wall - 8192 - over;
}

/* 32 frames, linear interpolation. r is 0 for mono.
 * A block gets MAX_EDGES seams and turns, then the note stops: a loop of a few
 * frames played octaves up would otherwise turn several times a frame, at a
 * cost per block past the heaviest stock machine. */
#ifdef FADE
/* One frame's gain: a sample is 28 bits here, so 9 are dropped before the product and 3 after.
 * Only called while a fade is on: at FADE_ONE the frame is left exactly as it was. */
CAVE(w) static s32 faded(s32 x, s32 g)
{
    return ((x >> 9) * g) >> 3;
}

/* After a frame of a fade: move the gain. A fade in ends at FADE_ONE, a fade out stays at nothing. */
CAVE(w) static void fade_move(struct st *s)
{
    s32 g = s->fade + s->fstep;

    if (g >= FADE_ONE) {
        g = FADE_ONE;
        s->fstep = 0;
    }
    if (g < 0)
        g = 0;
    s->fade = g;
}
#endif

#ifdef HQ
/* The table's 33 rows from the 17 the image holds: row 32 - r is row r backwards. The middle row is
 * as it is stored: it adds up to an odd number, so it is not quite its own mirror. */
CAVE(t) void hq_init(void)
{
    const s16 *src = hq_rows;
#ifdef QUICK
    s32 *t = HQ_LONGS;
#else
    s16 *t = HQ_TABLE;
#endif
    u32 r, k;

#ifdef NARROW
/* The mode image on: the image holds a row's middle twelve numbers, the sum of twelve reads no others, and the
 * two at each end of a row of the copy are left as the memory has them. */
#define HQ_ENDS 2
#else
#define HQ_ENDS 0
#endif
    for (r = 0; r <= HQ_HALF; r++)
        for (k = HQ_ENDS; k < HQ_TAPS - HQ_ENDS; k++) {
#ifdef QUICK
            s32 v = HQ_COEF(*src++);
#else
            s16 v = *src++;
#endif

            t[HQ_TAPS * r + k] = v;
            if (r < HQ_HALF)
                t[HQ_TAPS * (2 * HQ_HALF - r) + HQ_TAPS - 1 - k] = v;
        }
    HQ_MADE = HQ_MAGIC;
}

#ifndef QUICK
/* Frame f/4096 past x[HQ_BEFORE], f not 0, from x[0] to x[15]: engine/stub.S. See sampler.h. */
s32 hq_mid(const s16 *x, u32 f);
#endif

#if MODE_CHAIN
#error "the frames around a slot's ends are written out once a note: a note must stay in one slot"
#endif
/* A note's start: the frames around both ends of its slot, written out with the end frame standing in
 * for what is past it, so that a frame within reach of an end is summed like any other. Each side:
 * frames -7 to 14, then frames n - 15 to n + 7. */
#ifdef LEAN
void hq_pads(struct st *s);     /* engine/stub.S: the same words for a third of the work. Eight notes on a step do this together */
#else
CAVE(s) static void hq_pads(struct st *s)
{
    s16 *w = HQ_PADS + 128 * (((u32)s & 0xffff) / 1800);
    const s16 *x = s->l;
    s32 n = s->frames, k, j;

    s->pad = w;
    do {
        for (k = 0; k < HQ_PAD_SIDE; k++) {
            j = k < HQ_PAD_END ? k - HQ_BEFORE : n - HQ_TAPS - HQ_PAD_END + 1 + k;
            *w++ = x[j < 0 ? 0 : j >= n ? n - 1 : j];
        }
        x = x == s->r ? 0 : s->r;
    } while (x);
}
#endif
#endif

#ifdef QUICK
/* hq_run, for a note whose right channel is not there (its slot has become the shorter since the block began):
 * that side is nothing, as it was. */
CAVE(y) static int run(struct st *s, s32 *l, s32 *r, int n, int end, s32 lo, u32 span)
{
    int m = hq_run(s, l, s->r ? r : 0, n, end, lo, span);

    if (r && !s->r)
        for (; n < m; n++)
            r[n] = 0;
    return m;
}

#ifdef LEAN
/* Frames n to m - 1 of the block, made at full level, taken through a fade that is on: each by the gain as it
 * stands, which then moves a step. What faded and fade_move make of them a frame at a time: engine/stub.S. */
void fade_run(struct st *s, s32 *l, s32 *r, int n, int m);
#endif

#ifdef XFADE
/* Is the pass still short of its seam's blend. */
CAVE2(XO) static int outside(const struct st *s)
{
    s32 d = XF(s)->zone - s->pos;

    return s->dir0 < 0 ? d <= 0 : d > 0;
}

/* A block begins. May a loop's pass go into its seam's blend in it: the blend is all written, no fade is on
 * (in a block of one the seam is not looked at again, and the blend may be another seam's), and the pass was
 * short of it when that was first so (it may have come to it since, at the block's very end). -> that, or that
 * it is in it. */
CAVE2(XM) static int seam(struct st *s)
{
    if (!s->playing || s->mode != 1)
        return 0;
    if (s->xuse != 2)
        s->xuse = s->xn >= XF_N && !s->fstep && (s->xuse || outside(s));
    return s->xuse;
}

/* Before a frame is made by itself: a pass that has reached its blend's frames goes into them. The note is
 * pointed at them in the sample's place, its place and its wall counted from the first of them, and none of them
 * taken for a frame near a slot's end. It stays so until the pass wraps (edge). (A run of frames stops short of
 * the blend, so the first frame in it is always one made by itself. Asked only of a pass that may go in.) */
CAVE2(XG) static void into(struct st *s)
{
    struct xf *x;
    s32 off;

    if (outside(s))
        return;
    x = XF(s);
    off = x->off;
    s->xuse = 2;
    s->l = x->l;
    if (s->r)
        s->r = x->r;
    s->frames = (s32)x;                             /* an address up there: more frames than any slot has */
    s->pos -= off;
    s->bound = x->wall - off;
}
#endif

/* 32 frames. What play below makes, frame for frame: see sampler.h, QUICK. */
CAVE(y) static void play(struct st *s, s32 *l, s32 *r)
{
    int n = 0;
    int tries = MAX_EDGES;
    s32 near = s->fwall && s->span >= s->inc >> 2 ? FADE_OUT * s->inc : 0;
#ifdef XFADE
    int live;

    if (seam(s))
        near = 0;                       /* the blend is the seam: no dip before it */
    live = near || s->fstep || s->fade != FADE_ONE;
#else
    int live = near || s->fstep || s->fade != FADE_ONE;
#endif

    while (n < BLOCK) {
        if (!s->playing) {
            l[n] = 0;
            if (r)
                r[n] = 0;
            n++;
            continue;
        }
#ifdef LEAN
        /* A run under a fade, too: up to the frame whose step reaches the wall, and no further than a fade in
         * lasts. (The second build made every frame of a fade one at a time: a block of them was half as much
         * work again as a block without, and tracks that start or turn together are in theirs together.) */
        int fading = live && s->fstep && s->fade != FADE_ONE;
#else
#define fading 0
#endif

        if (!live || fading || (!s->fstep && s->fade == FADE_ONE)) {
            /* the frames whose step ends short of the wall, and of where the fade out before a cut begins */
            s32 a = 0, b = 0x7fffffff, margin = fading ? 0 : near;
            int end = BLOCK, m;
#ifdef XFADE
            s32 wall = s->bound;

            if (s->xuse == 1)
                wall = XF(s)->zone;     /* and short of the blend's frames: they are gone into a frame at a time */
            if (s->dir > 0)
                b = wall - margin - s->inc;
            else
                a = wall + s->inc + (margin ? margin + 1 : 0);
#else

            if (s->dir > 0)
                b = s->bound - margin - s->inc;
            else
                a = s->bound + s->inc + (margin ? margin + 1 : 0);
#endif
            if (fading && s->fstep > 0 && (m = n + (FADE_ONE - s->fade + s->fstep - 1) / s->fstep) < end)
                end = m;
            if (b > a) {
                m = run(s, l, r, n, end, a, (u32)b - (u32)a);
#ifdef LEAN
                if (fading)
                    fade_run(s, l, r, n, m);
#endif
                n = m;
                if (n == BLOCK)
                    break;
                if (fading && !s->fstep)
                    continue;           /* the fade in is over */
            }
        }
#ifdef XFADE
        if (s->xuse == 1)
            into(s);                    /* at its seam's blend: this frame is the first from it */
#endif
        run(s, l, r, n, n + 1, (s32)0x80000000, ~0u);   /* this frame wherever it is, then what follows it */
        if (live && s->fade != FADE_ONE) {
            l[n] = faded(l[n] >> 4, s->fade) << 4;
            if (r)
                r[n] = faded(r[n] >> 4, s->fade) << 4;
        }
        while (s->dir > 0 ? s->pos >= s->bound : s->pos < s->bound) {
            if (!tries--)
                s->playing = 0;
            else
                edge(s);
            if (!s->playing)
                break;
        }
        if (live) {
            if (s->fstep)
                fade_move(s);
            else if (near && (s->dir > 0 ? s->bound - s->pos : s->pos - s->bound) <= near)
                s->fstep = -(FADE_ONE / FADE_OUT);      /* the wall is near: down to it */
        }
        n++;
    }
}
#else
CAVE(y) static void play(struct st *s, s32 *l, s32 *r)
{
    int n;
    int tries = MAX_EDGES;
#ifdef FADE
    /* the fade out starts this far from the wall, if the wall is a cut and the region is long enough for it */
    s32 near = s->fwall && s->span >= s->inc >> 2 ? FADE_OUT * s->inc : 0;
    int live = near || s->fstep || s->fade != FADE_ONE;     /* is there a fade to look after in this block at all */
#endif

    for (n = 0; n < BLOCK; n++) {
        s32 a = 0, b = 0;

        if (s->playing) {
            s32 i = s->pos >> 12;
            s32 f = s->pos & 0xfff;
#ifdef HQ
            if (!f) {                               /* a frame of the sample itself */
                a = s->l[i] * 65536;
                if (r && s->r)
                    b = s->r[i] * 65536;
            } else if (i >= HQ_BEFORE && i + HQ_TAPS - HQ_BEFORE <= s->frames) {     /* all sixteen are in the slot */
                a = hq_mid(s->l + i - HQ_BEFORE, (u32)f);
                if (r && s->r)
                    b = hq_mid(s->r + i - HQ_BEFORE, (u32)f);
            } else {                                /* within reach of an end: from what the note's start wrote out */
                const s16 *w = s->pad + (i < HQ_BEFORE ? i : HQ_PAD_END + HQ_REACH + i - s->frames);

                a = hq_mid(w, (u32)f);
                if (r && s->r)
                    b = hq_mid(w + HQ_PAD_SIDE, (u32)f);
            }
#else
            s32 j = i + 1 < s->frames ? i + 1 : i;

            a = (s->l[i] * (4096 - f) + s->l[j] * f) << 4;
            if (r && s->r)
                b = (s->r[i] * (4096 - f) + s->r[j] * f) << 4;
#endif
#ifdef FADE
            if (live && s->fade != FADE_ONE) {
                a = faded(a >> 4, s->fade) << 4;
                b = faded(b >> 4, s->fade) << 4;
            }
#endif
            s->pos += s->dir > 0 ? s->inc : -s->inc;
            while (s->dir > 0 ? s->pos >= s->bound : s->pos < s->bound) {
                if (!tries--)
                    s->playing = 0;
                else
                    edge(s);
                if (!s->playing)
                    break;
            }
#ifdef FADE
            if (live) {
                if (s->fstep)
                    fade_move(s);
                else if (near && (s->dir > 0 ? s->bound - s->pos : s->pos - s->bound) <= near)
                    s->fstep = -(FADE_ONE / FADE_OUT);      /* the wall is near: down to it */
            }
#endif
        }
        l[n] = a;
        if (r)
            r[n] = b;
    }
}
#endif

#ifndef AUTO
/* Frame x of the chain starting at slot k -> (slot, frame in slot). */
CAVE2(XW) static u32 locate(u32 k, u32 last, u32 stride, s32 *x, int end)
{
    for (;;) {
        s32 n = slot_frames(k);

        if (*x < n || k >= last || (end && *x == n))
            return k;
        *x -= n;
        k += stride;
    }
}
#endif

#ifdef PAGE
/* Where the sampling page sends a track's takes (struct recbox): a stereo sample
 * from 0, or DEST_SMPL, which is also the answer while the box is not set up. */
CAVE2(ZY) static u32 dest_of(u32 track)
{
    const volatile struct recbox *b = REC_AUDIO;

    if (b->mark != REC_MARK || b->mark2 != ~REC_MARK)
        return DEST_SMPL;
    return b->dest[track];
}
#define TAKE_ARG , u32 dest
#else
#define TAKE_ARG
#endif

#ifdef FADE
/* A note starts. in: it starts inside the sample. out: its far end is inside the sample. */
CAVE(w) static void fade_on(struct st *s, int in, int out, s32 span)
{
    s->fade = in ? 0 : FADE_ONE;
    s->fstep = in ? FADE_ONE / FADE_IN : 0;
    s->span = span;
#ifdef TAIL
    (void)out;
    s->fwall = s->mode < 2;                     /* the tail image: a one-shot's far end is a cut wherever it is */
#else
    s->fwall = s->mode == 1 || (s->mode == 0 && out);
#endif
#ifdef LIVE
    s->duck = 0;
#endif
#ifdef XFADE
    s->xall = 1;                                /* no blend is written for this note yet, it is in none, and its seam is to be worked out */
#endif
}
#endif

#ifdef SOFT
/* The soft image: a note that starts on a frame that is not near nothing is faded in as one that starts inside the
 * sample is. s->pos is the note's first frame. See sampler.h. */
CAVE(d) static void soft(struct st *s)
{
    s32 i = s->pos >> 12, x = s->l[i], y = s->r ? s->r[i] : 0;

    if (x < 0)
        x = -x;
    if (y < 0)
        y = -y;
    if ((x > SOFT_MIN || y > SOFT_MIN) && !s->fstep) {
        s->fade = 0;
        s->fstep = FADE_ONE / FADE_IN;
    }
}
#endif

#ifdef LIVE
/* The region the knobs say right now, of a slot of `total` frames: its first frame, and the one past its last in *b. */
CAVE(w) static s32 region(const struct st *s, const u8 *p, s32 total, s32 *b)
{
    u32 len16 = *(const u16 *)(p + 2 * K_LENGTH);
#ifdef FLOOR
    if (len16 < LEN_MIN)
        len16 = LEN_MIN;
#endif
#ifdef LIVE_STRT
    s32 a = scale(total, *(const u16 *)(p + 2 * K_START));
    (void)s;
#else
    s32 a = scale(total, s->strt);              /* the start is the note's own */
    (void)p;
#endif

    *b = len16 >= 127 << 8 ? total : a + (s32)scale(total - a, len16);
    return a;
}

/* After the pass or the place played from has been moved: where travel ends now, and whether that is a cut. */
CAVE(u) static void walls(struct st *s)
{
    int rev = s->dir0 < 0;
    s32 began = rev ? s->pb : s->pa;

#ifdef XFADE
    s->xnew = 1;
#endif
    if (s->duck) {                                  /* it was done at nothing: up again */
        s->duck = 0;
        s->fstep = FADE_ONE / FADE_IN;
    }
#ifdef TAIL
    s->fwall = s->mode < 2 || (s->dir != s->dir0 && s->pc != began);
#else
    s->fwall = s->mode == 1 || (s->mode == 0 ? (rev ? s->pa > 0 : s->pb < s->frames) : s->dir != s->dir0 && s->pc != began);
#endif
    s->bound = (s->dir != s->dir0 ? began : rev ? s->pa : s->pb) << 12;
    if (s->fstep < 0 && (s->dir > 0 ? s->bound - s->pos : s->pos - s->bound) > FADE_OUT * s->inc)
        s->fstep = FADE_ONE / FADE_IN;              /* a fade out before a wall that has moved away */
}

/* The knobs while the note plays: once a block, when no note starts in it. See sampler.h. */
#ifdef SLSCRUB
static s32 slice_region(const struct st *s, const u8 *p, s32 total, s32 *b);
#endif

CAVE(v) static void live(struct st *s, const u8 *p)
{
    s32 total = s->frames;
#ifdef SLSCRUB
    s32 b, a = slice_region(s, p, total, &b);       /* the slscrub image: a slice's region as its note's start had it */
#else
    s32 b, a = region(s, p, total, &b);
#endif
    int rev = s->dir0 < 0;
    s32 from = rev ? b : a;                         /* where the knobs have a pass begin now */
    s32 span = b - a;
    s32 began = rev ? s->pb : s->pa;                /* where this pass began */
    s32 end = rev ? began - span : b == total ? total : began + span;       /* and where it ends: as far on as the knobs
                                                     * have the region long, or at the sample's end when they have it go there */
    s32 at = s->pos >> 12;
    int caught;

#ifdef XFADE
    if (s->xuse == 2)                               /* a pass inside its blend: the knobs wait until it is through */
        return;
#endif
    if (span < 4 || (from == s->pc && span == s->span && !s->duck && (s->mode != 2 || from == began)))
        return;
    if (end < 0)
        end = 0;
    if (end > total)
        end = total;
    caught = s->dir == s->dir0 && (rev ? at < end : at >= end);     /* the far end is behind the place played from */
    if (s->duck ? s->fade : caught && (s->mode == 0 || (s->mode == 1 && span >= s->inc >> 2))) {
        s->duck = 1;                                /* down first, with the pass as it was */
        s->fstep = -(FADE_ONE / FADE_OUT);
        return;
    }
    s->pc = from;
    s->span = span;
    if (rev)
        s->pa = end;
    else
        s->pb = end;
    if (caught) {
        if (s->mode == 2)
            s->dir = -s->dir;                       /* a ping-pong turns where it is */
        else if (s->mode == 0)
            s->playing = 0;
        else {                                      /* a loop: its next pass, now */
            pass(s);
            s->pos = (rev ? s->pb - 1 : s->pa) << 12;
        }
    }
    walls(s);
}
#endif

#ifdef XFADE
/* XF_STEP frames more of the seam's blend, both channels (engine/stub.S). */
void bake(struct st *s, struct xf *x);

#ifdef TRIM
/* The trim image: what x's blend is made from, as the voice's note has it now. Never 0. See sampler.h, TRIM. */
CAVE(e) static u32 blend_key(const struct st *s, const struct xf *x)
{
    s32 at = x->off >> 12, d = (x->to - x->wall) >> 12, j;
    const s16 *l = s->l + at, *r = s->r ? s->r + at : 0;
    u32 k = TRIM_FORMAT ^ (u32)s->l ^ (u32)s->r * 3 ^ (u32)s->frames * 5 ^ (u32)(s32)s->dir0 * 7;

    for (j = 0; j < XF_N; j += XF_N / 8) {
        k = k * 31 + (u16)l[j];
        k = k * 31 + (u16)l[j + d];
        if (r) {
            k = k * 31 + (u16)r[j];
            k = k * 31 + (u16)r[j + d];
        }
    }
    return k ? k : 1;
}
#endif

/* The seam a loop has now: its wall and the place it leads to, as positions. If they are not the ones the blend
 * was begun for, it is begun again; and eight frames more of it are written, until it is all there. */
CAVE2(XK) static void xset(struct st *s, struct xf *x, s32 w, s32 c)
{
#ifdef TRIM
    if (!s->xn && x->wall == w && x->to == c && x->key == blend_key(s, x)) {
        s->xn = XF_N;                               /* a note's start, and the blend written for its seam is still so */
        return;
    }
#endif
    if (!s->xn || x->wall != w || x->to != c) {
#ifdef TRIM
        x->key = 0;                                 /* not believed until it is all written again */
#endif
        x->wall = w;
        x->to = c;
        c = (XF_W + XF_FAR) << 12;                  /* the first frame written, and where a pass goes in, from the wall */
        if (s->dir0 < 0) {
            c = XF_NEAR << 12;
            w += (2 * XF_REACH) << 12;
        }
        x->zone = w - (XF_REACH << 12);
        x->off = x->wall - c;
        s->xn = 0;
    }
    if (s->xn < XF_N)
#ifdef TRIM
    {
        bake(s, x);
        if (s->xn >= XF_N)
            x->key = blend_key(s, x);
    }
#else
        bake(s, x);
#endif
}

/* Once a block, after the knobs, while a loop plays: where its seam is, and more of its blend. See sampler.h.
 * With the blend all written, or nothing found to blend with, and neither the pass nor the knobs moved since
 * (xnew: pass and walls say so), there is nothing to work out. */
CAVE2(XT) static void xstep(struct st *s)
{
    s32 c = s->pc, before = c, wall = s->pb, after = s->frames - wall, e = XF_W;

    if (s->xuse == 2 || s->mode != 1)
        return;
    if (s->span < s->inc >> 2) {                    /* a loop too short to be faded at all, at this pitch: no blend */
        s->xnew = 1;
        goto none;
    }
    if (s->fstep || (!s->xnew && (!s->xn || s->xn == XF_N)))    /* not in the blocks of a fade, which are work enough; and
                                                     * not when nothing has moved and no blend is half written */
        return;
    s->xnew = 0;
    if (s->dir0 < 0) {                              /* played backwards: before its start is above it */
        before = s->frames - c;
        wall = after = s->pa;
        e = -XF_W;
    }
    if (before >= XF_W)
        e = 0;                                      /* what lies before the place a pass begins, as it is played */
    else if (after < XF_W)                          /* or what lies after the place it ends, the seam that far on; or nothing */
        goto none;
    xset(s, XF(s), (wall + e) << 12, (c + e) << 12);
    return;
none:
    s->xn = 0;
}
#endif

#ifdef RECLOCK
/* Is the track in record, by the knobs at p: the step's own REC if it has one, or the track's. In the third run: the first is full. */
CAVE2(ZY) static u32 rec_on(const u8 *p)
{
    return REC_ON(p[2 * K_MODE], p[2 * K_REC]);
}
#endif

#ifdef SLICE
/* The slice image: the region of a note on a track whose keys play slices, as the slice and STRT and LEN have it.
 * -> 0 when the note is not one (a plain note: the caller works it out). In SY TOY's and SY BITS's run. See sampler.h, SLICE. */
CAVE(e) static int slice_cut(const struct st *s, u32 k, s32 total, u32 len16, const u8 *p, s32 *pa, s32 *pb)
{
    const struct slc *c = SLC(((u32)s - (u32)ST(VOICE(0))) / 1800u);
    const struct hits *h = HITS_AT(k);
    s32 n = h->n, i, o, e;

    if (!c->on)
        return 0;
    if (h->data != SLOT[k].data || h->frames != total || h->done != total || n > HIT_MAX)
        n = 0;                          /* no list of this sample's, or not through it yet */
    i = c->off % (n ? n : SLICE_EVEN);
    if (i < 0)
        i += n ? n : SLICE_EVEN;
    if (n) {
        o = i ? HIT_AT(h->hit[i]) : 0;
        e = i + 1 < n ? HIT_AT(h->hit[i + 1]) : total;
    } else {
        o = (total * i) >> 4;
        e = (total * (i + 1)) >> 4;
    }
    o += scale(e - o, *(const u16 *)(p + 2 * K_START));
    *pa = o;
#ifdef RING
    /* The ring image: LEN is the share of what is left from the slice's start to the sample's end, as on a whole
     * sample, so a slice can ring on past the next one (on request
     * ). STRT stays inside the slice. */
    *pb = len16 >= 127 << 8 ? total : o + (s32)scale(total - o, len16);
#else
    *pb = len16 >= 127 << 8 ? e : o + (s32)scale(e - o, len16);
#endif
    return 1;
}
#endif

#ifdef SLSCRUB
/* The slscrub image: region() for a note that plays a slice, as slice_cut has it at the note's start; region()'s own
 * otherwise. Past section 7's end (cave f). See sampler.h, SLSCRUB. */
#ifdef TRAP
CAVE_TRAP static s32 slice_region(const struct st *s, const u8 *p, s32 total, s32 *b)   /* the trap image: in CY ALLOY's room */
#else
__attribute__((section(".cave.f"), noinline)) static s32 slice_region(const struct st *s, const u8 *p, s32 total, s32 *b)
#endif
{
    u32 len16 = *(const u16 *)(p + 2 * K_LENGTH);
    s32 a;

    if (len16 < LEN_MIN)
        len16 = LEN_MIN;
    if (slice_cut(s, s->k, total, len16, p, &a, b))
        return a;
    return region(s, p, total, b);
}
#endif

/* Latch the knobs and start. */
CAVE(x) static void note_on(struct st *s, const u8 *p TAKE_ARG)
{
    s32 v = (s8)p[2 * K_SAMPLE] - 64;
#ifdef SRR
    u32 m = MODE_STEREO;                /* the srr image: MODE's parameter is the reduction, and a take at a stereo place is stereo */
#else
    u32 m = p[2 * K_MODE];
#endif
    u32 play = p[2 * K_LOOP] & LOOP_PLAY;
    u32 len16 = *(const u16 *)(p + 2 * K_LENGTH);
#ifdef AUTO
#define stride 2u
#else
    u32 stride = STEREO(m) ? 2 : 1;
#endif
#ifdef RECLOCK
    u32 taking = rec_on(p);
#else
#define taking (m & MODE_REC)
#endif
    u32 first, last;
    s32 total, a, b;
    int rev = v < 0;

    if (rev)
        v = ~v;
    if (v > N_SLOTS - 1)
        v = N_SLOTS - 1;
#ifdef FLOOR
    if (len16 < LEN_MIN)
        len16 = LEN_MIN;
#endif
#ifdef PACK
    (void)stride;
    if (taking && dest < N_SLOTS)       /* a take: to the page's place, if it names one */
        v = dest;
    s->stereo = v < SINGLES;            /* past the 32 stereo samples: a slot of the back half by its own number */
    if (s->stereo)
        v <<= 1;
#else
#ifdef PAGE
    if (taking && dest < N_SLOTS / 2)   /* a take: to the page's stereo sample, if it names one */
        v = dest;
#endif
#ifdef AUTO
    (void)stride;                       /* SAMPLE counts the 32 samples, whatever MODE says */
#elif defined(RECLOCK)
    if (PAIRS(m) || taking)             /* a take is a stereo sample too when only the step says record */
#else
    if (PAIRS(m))                       /* stereo sample v: past 31 there is none, and nothing plays */
#endif
        v <<= 1;
#endif
    first = last = v;
    total = slot_frames(first);
    if (m & MODE_CHAIN)
        while (slot_frames(last + stride)) {
            last += stride;
            total += slot_frames(last);
        }

    s->playing = 0;
#ifdef RECORDER
#ifdef PACK
    if (taking) {                       /* a take starts with the block that is waiting; the track is silent */
        s->rk = first;
        s->rpos = 0;
        s->rseq = MB_AUDIO->seq - 1;
        s->rec = 1;                     /* every place is somewhere */
        s->link = TAKE_SINGLE;          /* what the take is: a single slot's, */
        KEPT[first] = 0;                /* (a new take is not on the drive) */
        if (s->stereo) {
            s->link = m & MODE_STEREO;  /* or in a stereo place both sides, or one */
            KEPT[first + 1] = 0;
        }
        return;
    }
#else
    if (taking) {                       /* a take starts with the block that is waiting; the track is silent */
        s->rk = first;
        s->rpos = 0;
        s->rseq = MB_AUDIO->seq - 1;
        s->rec = first < N_SLOTS;       /* past the last stereo sample there is nowhere to record */
#ifdef AUTO
        s->link = m & MODE_STEREO;      /* what the take is: both sides, or one */
#endif
#ifdef KEEP
        if (s->rec)
            KEPT[first] = KEPT[first + 1] = 0;          /* a new take is not on the drive */
#endif
        return;
    }
#endif
#endif
    s->mode = play == 3 ? 2 : play;
#ifndef AUTO
    s->stereo = stride - 1;
    s->stride = stride;
#endif
    s->dir0 = s->dir = rev ? -1 : 1;

#ifdef SLICE
    if (!slice_cut(s, first, total, len16, p, &a, &b)) {
#endif
    a = scale(total, *(const u16 *)(p + 2 * K_START));
    b = len16 >= 127 << 8 ? total : a + (s32)scale(total - a, len16);
#ifdef SLICE
    }
#endif
    if (b - a < 2)
        return;
    if (b - a < 4)
        s->mode = 0;
#ifdef FADE
    fade_on(s, rev ? b < total : a > 0, rev ? a > 0 : b < total, b - a);
#endif
#ifdef LIVE
    s->strt = *(const u16 *)(p + 2 * K_START);
#endif

#ifdef AUTO
    (void)last;
    s->k = first;
    s->pa = a;
    s->pb = b;
    s->pc = rev ? b : a;                /* a loop goes back to where the note started */
    enter(s, first);
    s->pos = (rev ? b - 1 : a) << 12;
#ifdef SOFT
    soft(s);
#endif
#else
    s->ka = locate(first, last, stride, &a, 0);
    s->pa = a;
    s->kb = locate(first, last, stride, &b, 1);
    s->pb = b;
    s->kc = rev ? s->kb : s->ka;        /* a loop goes back to where the note started */
    s->pc = rev ? s->pb : s->pa;
    if (rev) {
        enter(s, s->kb);
        s->pos = (s->pb - 1) << 12;
    } else {
        enter(s, s->ka);
        s->pos = s->pa << 12;
    }
#endif
#ifdef HQ
    hq_pads(s);
#endif
    s->playing = 1;
}
#undef taking
#undef stride

#ifdef SRR
/* The srr image: the update and the render are in SY SWARM's room (engine/sampler.h, SRR), and the hold's step is
 * worked out here, a block's worth: the knob's word to a length in 256ths of a frame, and 2^32 over it. */
#define CAVE_UR CAVE(d)
CAVE(d) static void srr_step(s32 *voice, const u8 *p)
{
    struct srr *h = SRR_ST(((u32)voice - (u32)VOICE(0)) / 1800u);
    u32 w = *(const u16 *)(p + 2 * K_MODE);
    u32 len = (256 + (w >> 4 & 255)) << (w >> 12 & 7);

    h->step = len > 256 ? (0xffffffffu / len + 1) << 8 : 0;
    if (!h->step || voice[V_START])
        h->phase = 0xffffffffu;         /* off, or a note's start: the next frame is let through */
}
#else
#define CAVE_UR CAVE(x)
#endif

#ifdef STRETCH
/* The stretch image: sampler.h, STRETCH. In the room past section 7's end (cave f); a track's state in the zeros at
 * that room's end, which the start's copy writes every start (STR_BASE). */
#define STR(t) ((struct str *)(STR_BASE + 32u * (t)))
#ifdef LOCK
#define LCK(t) ((struct lck *)(STR_BASE + 256u + 4u * (t)))   /* the lock image: after the tracks' struct str, in the zeros too */
#endif
#define CAVE_STR __attribute__((section(".cave.f"), noinline))
#ifdef GRAIN
#define GRN(t) ((struct grn *)(GRAIN_BASE + 16u * (t)))     /* the grain image: past the far room's copy */
#define CAVE_GRN __attribute__((section(".cave.j"), noinline))   /* and its code after the lock image's state */
#ifdef SPREAD
#define GRS(t) ((struct grs *)(GRAIN_BASE + 0x400u + 512u * (t)))  /* the spread image: a track's look, past the grain image's */
#endif
#endif

/* 4096 times 2^(i/32): SPD's step within a doubling */
#ifdef SPREAD
__asm__(".section .cave.j,\"ax\",@progbits\n"        /* the spread image: in cave j, for room in cave f */
#else
__asm__(".section .cave.f,\"ax\",@progbits\n"
#endif
        "str_steps: .short 4096,4185,4277,4371,4467,4565,4665,4767,4871,4978,5087,5199,5313,5429,5548,5670\n"
        "           .short 5793,5920,6050,6183,6318,6457,6598,6743,6891,7042,7196,7354,7515,7680,7848,8020\n"
        "           .text\n");
extern const u16 str_steps[32];

/* Frame x of a channel at a 20.12 place, made from the two around it, 64 times a sample; 0 outside the slot. */
static inline __attribute__((always_inline)) s32 str_tap(const s16 *x, s32 frames, s32 pos)
{
    s32 i = pos >> 12, f = pos & 0xfff;

    if ((u32)i >= (u32)(frames - 1))
        return 0;
    return (x[i] * (4096 - f) + x[i + 1] * f) >> 6;
}

#ifndef GRAIN                               /* the grain image: grain_birth in its place */
/* Head h starts again: at the place, moved by up to STR_W frames to where it lines up best with the other head. */
CAVE_STR static void str_birth(const struct st *s, struct str *g, u32 h)
{
    s32 at = s->pos >> 12, q = g->hpos[h ^ 1] >> 12, d = s->dir > 0 ? STR_K : -STR_K;
    s32 lo = at - STR_W, hi = at + STR_W, span = d * (STR_N - 1), best = 0, o, k;
    s32 least = 0x7fffffff;
    const s16 *x = s->l;

    if (lo < 0 || hi >= s->frames || lo + span < 0 || hi + span >= s->frames
        || q < 0 || q >= s->frames || q + span < 0 || q + span >= s->frames || g->age[h ^ 1] >= STR_G)
        o = 0;                              /* too near an end to look, or the other head is not sounding */
    else {
        for (o = -STR_W; o <= STR_W; o += STR_K) {      /* the least of the differences: a loud stretch is no better a match */
            s32 sum = 0;

            for (k = 0; k < STR_N; k++) {
                s32 v = x[at + o + d * k] - x[q + d * k];

                sum += v < 0 ? -v : v;
            }
            if (sum < least) {
                least = sum;
                best = o;
            }
        }
        o = best;
    }
    g->hpos[h] = s->pos + (o << 12);
    g->age[h] = 0;
    g->hdir[h] = s->dir;
}
#endif

/* After the block's update: a note's start latches whether it is stretched; a stretched note's place moves at SPD. */
CAVE_STR static void str_update(s32 *voice, struct st *s, const u8 *p, u32 t)
{
    struct str *g = STR(t);
    s32 e;

    if (voice[V_START]) {
        u32 skew = STR_SKEW * t % (STR_G / 2);

        g->on = (p[2 * K_REC + 1] & STR_BIT) != 0;
        g->hpos[0] = g->hpos[1] = s->pos;
        g->hdir[0] = g->hdir[1] = s->dir;
        g->age[0] = STR_G / 2 + skew;       /* the one at the top of its triangle, the other on its way up: both read the note's first frames */
        g->age[1] = skew;
        g->fin = 0;
        g->tail = 0;
        g->spd = 64;
#ifdef GRAIN
        GRN(t)->hold = 0;                   /* the grain image: no lock yet */
        GRN(t)->floor = 0;
#ifdef SPREAD
        GRN(t)->look = 0;                   /* the spread image: no look under way */
#endif
#endif
    }
    if (!g->on)
        return;
#ifdef SCRUB
    if (s->duck) {                          /* the scrub image: live() waits for play()'s fade to reach nothing, which a
                                             * stretched note never runs; its heads are its fade, so it goes on next block */
        s->fade = 0;
        g->tail = 1;                        /* and a one-shot it stops goes down over a block, as at its end */
    }
#endif
#ifdef LOCK
    {
        struct lck *k = LCK(t);
        u32 hb = p[2 * K_REC], tag = LOCK_TAG(p[2 * K_REC + 1]), base = 4096, fps, n, f, locked = 0;

        if (hb & 0x80) {                    /* the lock image: what this block carries, by its tag; with REC on, as it last was */
            if (tag == 0)
                g->spd = hb & 0x7f;
            else if (tag == 1)
                k->lo = hb & 0x7f;
            else if (tag == 2)
                k->hi = hb & 0x7f;
            else
                k->on = hb & 3;             /* bit 0 KEYS's lock, bit 1 PORT's snap */
        }
        g->pinc = (u32)s->inc;
        fps = 2 * ((u32)k->hi << 7 | k->lo);
        f = (u32)s->span;
        if (k->on && fps >= 500 && f) {     /* the region stretched to the power of two of steps nearest its length */
            for (n = 1; n < 4096 && n * fps * 181 < f * 128; n <<= 1)
                ;
            base = (f << 12) / (n * fps);
            locked = 1;
        }
        e = locked && k->on & 2 ? 0 : (s32)g->spd - 64;     /* PORT on: on the tempo, whatever SPD says */
        base = base * str_steps[e & 31] >> 12;
        s->inc = e >= 0 ? base << (e >> 5) : base >> ((31 - e) >> 5);
    }
#else
    if (p[2 * K_REC] & 0x80)                /* SPD, where REC's mark is while REC is off; with REC on, as it last was */
        g->spd = p[2 * K_REC] & 0x7f;
    g->pinc = (u32)s->inc;
    e = (s32)g->spd - 64;
    s->inc = e >= 0 ? str_steps[e & 31] << (e >> 5) : str_steps[e & 31] >> ((31 - e) >> 5);
#endif
}

#ifdef GRAIN
/* The grain image: sampler.h, GRAIN. A track's state is past the far room's copy, made at each note's start. */
#define GRN_WIDE ((u32 *)(GRAIN_BASE + 128u))   /* the last track that played a block, and the wide looks in this one */
#define GRN_GRID ((s32 *)(GRAIN_BASE + 136u))   /* the wide look's low-passed frames: the place's, then the other head's */

/* lo and hi, candidates c of a look whose frames reach c + span, and ext past the last: inside the slot. */
CAVE_GRN static void grain_reach(s32 *lo, s32 *hi, s32 span, s32 ext, s32 frames)
{
    if (span > 0) {
        if (*lo < 0)
            *lo = 0;
        if (*hi > frames - 1 - span - ext)
            *hi = frames - 1 - span - ext;
    } else {
        if (*lo < -span)
            *lo = -span;
        if (*hi > frames - 1 - ext)
            *hi = frames - 1 - ext;
    }
}

/* The least summed difference of STR_N frames STR_K apart (d: STR_K a step, signed) from c to the other head's at q.
 * Stops once it is past `least`. */
CAVE_GRN static s32 grain_diff(const s16 *x, s32 c, s32 q, s32 d, s32 least)
{
    s32 sum = 0, k;

    for (k = 0; k < STR_N && sum < least; k++) {
        s32 v = x[c + d * k] - x[q + d * k];

        sum += v < 0 ? -v : v;
    }
    return sum;
}

#ifdef SPREAD
/* The spread image: sampler.h, SPREAD. A head's next birth, in blocks: 0 now. In the hold, head 1 is born as it ends
 * and head 0 half a grain after. */
static inline __attribute__((always_inline)) s32 grain_until(const struct str *g, const struct grn *c, u32 h)
{
    if (c->hold)
        return h ? c->hold : c->hold + (STR_G - (s32)g->age[0]) / BLOCK;
    return g->age[h] >= STR_G ? 0 : (STR_G - (s32)g->age[h]) / BLOCK;
}

/* The bounds a lock sets on where a head born with the place at p (20.12) may start, going forward: grain_birth's. */
static inline __attribute__((always_inline)) void grain_bounds(const struct st *s, const struct str *g, const struct grn *c,
                                  s32 p, s32 *lo, s32 *hi)
{
    *lo = -0x7ffffff;
    *hi = 0x7ffffff;
    if (s->dir > 0) {
        *lo = c->floor;
        if (c->lim > p) {
            u32 life = (u32)(c->lim - p) / (u32)s->inc;

            if (life > STR_G)
                life = STR_G;
            *hi = ((c->lim - (s32)(life * g->pinc)) >> 12) - 1;
        }
    }
    if (*hi < *lo)
        *lo = *hi;
}

/* A block begins: a slice of the look for the next birth. Up to STR_LEAD blocks before it the place and the other
 * head are foreseen where they will be then, the bounds made and the low-passed frames written (k->gr); then STR_SK
 * candidates a block, the coarse look's and then the fine one's around its best. Foreseen at the other head's own
 * place, or reading nothing, it lines up as it is. */
CAVE_STR static void grain_step(const struct st *s, const struct str *g, struct grn *c, struct grs *k)
{
    s32 u0 = grain_until(g, c, 0), u1 = grain_until(g, c, 1), d = s->dir > 0 ? 1 : -1, u, i, j, e, f = s->frames;
    u32 h = u1 < u0;
    const s16 *x = s->l;
    s32 *gr = k->gr, *ref = gr + k->n + STR_SN;     /* the other head's frames, after the place's */

    u = h ? u1 : u0;
    if ((u32)(u - 1) >= STR_LEAD)           /* 1 to STR_LEAD blocks from it */
        return;
    if (!c->look || k->h != h) {
        s32 p = s->pos + u * BLOCK * s->inc, at = p >> 12, sl, sh, ql, qh, sum = 0;
        u32 *w = GRN_WIDE;

        if (w[1] >= STR_WIDE)               /* one look begun a block for all tracks (notes trigged together): the next */
            return;
        w[1]++;
        s32 q = (g->hpos[h ^ 1] + (g->hdir[h ^ 1] > 0 ? 1 : -1) * u * BLOCK * (s32)g->pinc) >> 12;

        c->look = 1;
        k->h = h;
        k->at = at;
        k->q = q;
        grain_bounds(s, g, c, p, &k->lo, &k->hi);
        k->best = at < k->lo ? k->lo : at > k->hi ? k->hi : at;
        k->fine = 1;                        /* done, as the place itself: j past any n */
        k->j = 0x7fff;
        if (q == at)
            return;                         /* the other head is where the place is: it lines up as it is */
        sl = at - STR_SW > k->lo ? at - STR_SW : k->lo;
        sh = at + STR_SW < k->hi ? at + STR_SW : k->hi;
        grain_reach(&sl, &sh, d * STR_GS * (STR_SN - 1), 3 * STR_K, f);
        ql = qh = q;
        grain_reach(&ql, &qh, d * STR_GS * (STR_SN - 1), 3 * STR_K, f);
        if (sl > sh || ql != q || qh != q) {
            k->fine = 0;                    /* no coarse look: straight to the fine one */
            return;
        }
        k->c0 = sl;
        k->n = (sh - sl) / STR_GS;
        sl = d > 0 ? sl : sl - STR_GS * (STR_SN - 1);
        for (j = 0; j < k->n + 2 * STR_SN; j++) {   /* the place's frames, then the other head's, backward its last first */
            const s16 *y = x + (j < k->n + STR_SN ? sl + STR_GS * j : q + d * STR_GS * (d > 0 ? j - k->n - STR_SN : k->n + 2 * STR_SN - 1 - j));

            gr[j] = y[0] + y[STR_K] + y[2 * STR_K] + y[3 * STR_K];
            if (j >= k->n + STR_SN)
                sum += gr[j] < 0 ? -gr[j] : gr[j];
        }
        k->least = sum ? 0x7fffffff : 0;    /* the other head reading nothing: every candidate ties */
        k->j = 0;
        k->fine = 0;
        return;
    }
    if (k->j <= k->n && k->least) {         /* a slice of the look */
        for (e = k->j + STR_SK; k->j < e && k->j <= k->n && k->least; k->j++) {
            s32 at = k->fine ? k->c0 + k->j : k->c0 + STR_GS * k->j, sum = 0;

            if (k->fine)
                sum = grain_diff(x, at, k->q, d * STR_K, k->least);
            else
                for (i = 0; i < STR_SN && sum < k->least; i++) {
                    s32 v = gr[k->j + i] - ref[i];

                    sum += v < 0 ? -v : v;
                }
            if (sum < k->least) {
                k->least = sum;
                k->best = at;
            }
        }
        return;
    }
    if (!k->fine) {                         /* the fine look: STR_GF either side of the coarse best, the place itself first */
        s32 fl = k->best - STR_GF > k->lo ? k->best - STR_GF : k->lo, fh = k->best + STR_GF < k->hi ? k->best + STR_GF : k->hi;
        s32 ql = k->q, qh = k->q;

        k->fine = 1;
        grain_reach(&fl, &fh, d * STR_K * (STR_N - 1), 0, f);
        grain_reach(&ql, &qh, d * STR_K * (STR_N - 1), 0, f);
        if (fl > fh || ql != k->q || qh != k->q)
            return;
        k->best = fl <= k->at && k->at <= fh ? k->at : k->best < fl ? fl : k->best > fh ? fh : k->best;
        k->least = grain_diff(x, k->best, k->q, d * STR_K, 0x7fffffff);
        k->c0 = fl;
        k->n = fh - fl;
        k->j = 0;
    }
}

/* Head h starts again (str_birth's place): where the look has it so far (a look cut short by the birth, its best yet),
 * moved as far as the other head is from where it was foreseen; with no look, or the place gone elsewhere since (a
 * wrap, a knob), at the place. Where SRR's code is, past section 7's end (cave d). */
__attribute__((section(".cave.d"), noinline)) static void grain_born(const struct st *s, struct str *g, struct grn *c, struct grs *k, u32 h)
{
    s32 at = s->pos >> 12, dq = (g->hpos[h ^ 1] >> 12) - k->q, da = at - k->at, best = at;

    if (c->look && k->h == h && dq <= 32 && dq >= -32 && da <= 64 && da >= -64)
        best = k->best + dq;
    c->look = 0;
    g->hpos[h] = s->pos + ((best - at) << 12);
    g->age[h] = 0;
    g->hdir[h] = s->dir;
}
#else
/* A head h starts again (str_birth's place). The wide look, STR_WIDE a block for all tracks: STR_GW frames either side
 * of the place every STR_GS on frames summed four STR_K apart (a low-pass), STR_GN of them; then STR_GF either side
 * of its best (or of the place, past STR_WIDE) a frame at a time. Going forward, no head starts before c->floor, nor
 * where it would read up to the next lock point (c->lim) before the place reaches it. */
CAVE_STR static void grain_birth(const struct st *s, struct str *g, struct grn *c, u32 h)
{
    s32 at = s->pos >> 12, q = g->hpos[h ^ 1] >> 12, f = s->frames, d = s->dir > 0 ? 1 : -1;
    s32 lo = -0x7ffffff, hi = 0x7ffffff, best, least, i, j, k, sl, sh, ql, qh;
    const s16 *x = s->l;
    u32 *w = GRN_WIDE;

    if (d > 0) {
        lo = c->floor;
        if (c->lim > s->pos) {              /* none: 0x7fffffff, and hi is past any slot */
            u32 life = (u32)(c->lim - s->pos) / (u32)s->inc;

            if (life > STR_G)
                life = STR_G;
            hi = ((c->lim - (s32)(life * g->pinc)) >> 12) - 1;
        }
    }
    if (hi < lo)                            /* lock points too near for the stretch: not up to the next */
        lo = hi;
    best = at < lo ? lo : at > hi ? hi : at;
    if (g->age[h ^ 1] >= STR_G)             /* the other head is not sounding */
        goto done;
    sl = best - STR_GF;
    sh = best + STR_GF;
    if (w[1] < STR_WIDE) {
        s32 *gr = GRN_GRID, *ref = gr + 2 * STR_GW / STR_GS + STR_GN, n, b0;

        sl = at - STR_GW > lo ? at - STR_GW : lo;
        sh = at + STR_GW < hi ? at + STR_GW : hi;
        grain_reach(&sl, &sh, d * STR_GS * (STR_GN - 1), 3 * STR_K, f);
        ql = qh = q;
        grain_reach(&ql, &qh, d * STR_GS * (STR_GN - 1), 3 * STR_K, f);
        if (sl <= sh && ql == q && qh == q) {
            b0 = d > 0 ? sl : sl - STR_GS * (STR_GN - 1);
            n = (sh - sl) / STR_GS;
            for (j = 0; j < n + STR_GN; j++) {
                const s16 *y = x + b0 + STR_GS * j;

                gr[j] = y[0] + y[STR_K] + y[2 * STR_K] + y[3 * STR_K];
            }
            for (k = 0; k < STR_GN; k++) {  /* in the grid's order: backward, its last first */
                const s16 *y = x + q + d * STR_GS * k;

                ref[d > 0 ? k : STR_GN - 1 - k] = y[0] + y[STR_K] + y[2 * STR_K] + y[3 * STR_K];
            }
            least = 0x7fffffff;
            for (i = -1; i <= n; i++) {     /* the one nearest the place first, kept on a tie (silence ties every one) */
                s32 sum = 0;

                j = i >= 0 ? i : at <= sl ? 0 : (at - sl + STR_GS / 2) / STR_GS > n ? n : (at - sl + STR_GS / 2) / STR_GS;

                for (k = 0; k < STR_GN && sum < least; k++) {
                    s32 v = gr[j + k] - ref[k];

                    sum += v < 0 ? -v : v;
                }
                if (sum < least) {
                    least = sum;
                    best = sl + STR_GS * j;
                }
            }
            w[1]++;
        }
        sl = best - STR_GF;
        sh = best + STR_GF;
    }
    if (sl < lo)
        sl = lo;
    if (sh > hi)
        sh = hi;
    grain_reach(&sl, &sh, d * STR_K * (STR_N - 1), 0, f);
    ql = qh = q;
    grain_reach(&ql, &qh, d * STR_K * (STR_N - 1), 0, f);
    if (sl <= sh && ql == q && qh == q) {   /* the fine look; its middle first, kept on a tie */
        best = sl <= at && at <= sh ? at : best < sl ? sl : best > sh ? sh : best;
        least = grain_diff(x, best, q, d * STR_K, 0x7fffffff);
        for (j = sl; j <= sh && least; j++) {
            s32 sum = grain_diff(x, j, q, d * STR_K, least);

            if (sum < least) {
                least = sum;
                best = j;
            }
        }
    }
done:
    g->hpos[h] = s->pos + ((best - at) << 12);
    g->age[h] = 0;
    g->hdir[h] = s->dir;
}

#endif

/* A block begins: the next lock point on the place's way forward (a hit of the slot's list, or a loop's wall) into
 * c->lim, and -> 1 when the place reaches it more than a block and at most two from now: the new head's place is then
 * in c->newp, where it reaches what the place does then. Also: the start of a block for the wide looks' count. */
CAVE_GRN static int grain_look(const struct st *s, const struct str *g, struct grn *c, u32 t)
{
    u32 *w = GRN_WIDE;
    s32 p = s->pos, i = s->inc, lim = 0x7fffffff, n, at = p >> 12;
    const struct hits *h = HITS_AT(s->k);
    int wall = 0;

    if (t <= w[0])
        w[1] = 0;
    w[0] = t;
    c->lim = lim;
    if (at < c->floor - STR_FLOOR)          /* the place went back behind the last lock: its floor is gone */
        c->floor = 0;
    if (!s->playing || s->dir < 0 || i <= 0)
        return 0;
    if (h->data == SLOT[s->k].data && h->frames == s->frames && h->done == s->frames && h->n <= HIT_MAX && h->n) {
        s32 a = 0, b = h->n;                /* the first hit past the place */

        while (a < b) {
            s32 mid = (a + b) >> 1;

            if (HIT_AT(h->hit[mid]) <= at)
                a = mid + 1;
            else
                b = mid;
        }
        if (a < h->n)
            lim = HIT_AT(h->hit[a]) << 12;
    }
    if (s->mode == 1 && s->dir0 > 0 && s->bound <= lim) {
        lim = s->bound;
        wall = 1;
    }
    c->lim = lim;
    if (lim == 0x7fffffff)
        return 0;
    n = (s32)((u32)(lim - p + i - 1) / (u32)i);
    if (n <= BLOCK || n > 2 * BLOCK)
        return 0;
    p += n * i;                             /* where the place is then */
    if (wall)
        p += (s->pc << 12) - s->bound;      /* over the wall: the next pass, from where the knobs have it */
    c->newp = p - n * (s32)g->pinc;
    c->floor = (p >> 12) + STR_FLOOR;
    return 1;
}

/* A lock's block: the two heads go down to nothing and the new one comes up from it; then it is head 0, alone at
 * the top of its triangle for STR_HOLD frames, and head 1 waits. */
CAVE_GRN static void grain_add(const s16 *x, s32 f, s32 p, s32 d, s32 *o)
{
    s32 n;

    for (n = 0; n < BLOCK; n++)
#ifdef TRAP
        o[n] = (o[n] >> 5) * (BLOCK - n) + ((x ? str_tap(x, f, p + n * d) : 0) * ((STR_X / BLOCK) * n) << STR_SH);
#else
        o[n] = (o[n] >> 5) * (BLOCK - n) + ((x ? str_tap(x, f, p + n * d) : 0) * ((STR_G / 2 / BLOCK) * n) << 1);
#endif
}

/* A lock's block, after the two heads have made it: they go down to nothing over it and the new one comes up from
 * nothing; then it is head 0, alone at the top of its triangle for STR_HOLD frames, and head 1 waits. */
CAVE_GRN static void grain_lock(const struct st *s, struct str *g, struct grn *c, s32 *l, s32 *r)
{
    s32 d = s->dir > 0 ? (s32)g->pinc : -(s32)g->pinc;

    grain_add(s->l, s->frames, c->newp, d, l);
    if (r)
        grain_add(s->r, s->frames, c->newp, d, r);
    g->hpos[0] = g->hpos[1] = c->newp + BLOCK * d;
    g->hdir[0] = g->hdir[1] = s->dir;
    g->age[0] = STR_G / 2;
    g->age[1] = STR_G;
    c->hold = STR_HOLD / BLOCK;
}
#endif

/* 32 frames of a stretched note: what play() makes of a note that is not. A head starts again only at a block's
 * start (STR_G, its half and every track's skew are whole blocks), so in a block each head's weight is a straight
 * line, up or down by one a frame; and it is known at the block's start whether both heads stay inside the slot,
 * so the frames are made without a test of their own. */
static inline __attribute__((always_inline)) s32 str_two(const s16 *x, s32 p)
{
    s32 i = p >> 12, f = p & 0xfff;

    return (x[i] * (4096 - f) + x[i + 1] * f) >> 6;
}

#ifdef TRAP
/* The trap image: a head's weight at age a, and its step a frame (*v). */
CAVE_TRAP static s32 str_w(u32 a, s32 *v)
{
    if (a < STR_X) {
        *v = 1;
        return (s32)a;
    }
    if (a < STR_G / 2) {
        *v = 0;
        return STR_X;
    }
    if (a < STR_G / 2 + STR_X) {
        *v = -1;
        return STR_G / 2 + STR_X - (s32)a;
    }
    *v = 0;
    return 0;
}

/* The trap image: a block made by one head, the other nothing, both heads inside the slot. */
CAVE_TRAP static void str_one(const s16 *xl, const s16 *xr, s32 p, s32 d, s32 w, s32 v, s32 *l, s32 *r)
{
    int n;

    if (xr)
        for (n = 0; n < BLOCK; n++) {
            l[n] = (str_two(xl, p) * w) << STR_SH;
            r[n] = (str_two(xr, p) * w) << STR_SH;
            p += d;
            w += v;
        }
    else
        for (n = 0; n < BLOCK; n++) {
            l[n] = (str_two(xl, p) * w) << STR_SH;
            p += d;
            w += v;
        }
}
#endif

CAVE_STR static void str_play(struct st *s, struct str *g, s32 *l, s32 *r)
{
    s32 pa, pb, da, db, wa, wb, va, vb, last;
    int n, h, tries = MAX_EDGES;
    const s16 *xl = s->l, *xr = r ? s->r : 0;
#ifdef GRAIN
    struct grn *c;
    u32 t;
    int lock;
#endif

    if (!s->playing && !g->tail) {
        for (n = 0; n < BLOCK; n++) {
            l[n] = 0;
            if (r)
                r[n] = 0;
        }
        return;
    }
#ifdef GRAIN
    t = ((u32)g - STR_BASE) >> 5;
    c = GRN(t);
    lock = grain_look(s, g, c, t);
#ifdef SPREAD
    if (lock)
        c->look = 0;                        /* the spread image: a look foreseen without the lock is no good */
    else if (s->playing)
        grain_step(s, g, c, GRS(t));
#endif
    if (!lock && !c->hold)
#endif
    for (h = 0; h < 2; h++)
        if (g->age[h] >= STR_G && s->playing)
#ifdef SPREAD
            grain_born(s, g, c, GRS(t), (u32)h);
#elif defined(GRAIN)
            grain_birth(s, g, c, (u32)h);
#else
            str_birth(s, g, (u32)h);
#endif
    pa = g->hpos[0];
    pb = g->hpos[1];
    da = g->hdir[0] > 0 ? (s32)g->pinc : -(s32)g->pinc;
    db = g->hdir[1] > 0 ? (s32)g->pinc : -(s32)g->pinc;
#ifdef TRAP
    wa = str_w(g->age[0], &va);
    wb = str_w(g->age[1], &vb);
#else
    wa = g->age[0] >= STR_G ? 0 : g->age[0] < STR_G / 2 ? (s32)g->age[0] : STR_G - (s32)g->age[0];
    wb = g->age[1] >= STR_G ? 0 : g->age[1] < STR_G / 2 ? (s32)g->age[1] : STR_G - (s32)g->age[1];
    va = g->age[0] >= STR_G ? 0 : g->age[0] < STR_G / 2 ? 1 : -1;
    vb = g->age[1] >= STR_G ? 0 : g->age[1] < STR_G / 2 ? 1 : -1;
#endif
#ifdef GRAIN
    if (c->hold)
        va = 0;                             /* the lock's head alone at the top */
#endif
    last = s->frames - 1;
    if ((u32)(pa >> 12) < (u32)last && (u32)((pa + (BLOCK - 1) * da) >> 12) < (u32)last
        && (u32)(pb >> 12) < (u32)last && (u32)((pb + (BLOCK - 1) * db) >> 12) < (u32)last) {
#ifdef TRAP
        if (!(wa | va) || !(wb | vb)) {     /* the trap image: one head is nothing all block, the other alone */
            if (wa | va)
                str_one(xl, xr, pa, da, wa, va, l, r);
            else
                str_one(xl, xr, pb, db, wb, vb, l, r);
            pa += BLOCK * da;
            pb += BLOCK * db;
        } else
#endif
        if (xr)
            for (n = 0; n < BLOCK; n++) {
                l[n] = (str_two(xl, pa) * wa + str_two(xl, pb) * wb) << STR_SH;
                r[n] = (str_two(xr, pa) * wa + str_two(xr, pb) * wb) << STR_SH;
                pa += da;
                pb += db;
                wa += va;
                wb += vb;
            }
        else
            for (n = 0; n < BLOCK; n++) {
                l[n] = (str_two(xl, pa) * wa + str_two(xl, pb) * wb) << STR_SH;
                pa += da;
                pb += db;
                wa += va;
                wb += vb;
            }
    } else                                  /* within reach of an end: a frame outside the slot is nothing */
        for (n = 0; n < BLOCK; n++) {
            l[n] = (str_tap(xl, s->frames, pa) * wa + str_tap(xl, s->frames, pb) * wb) << STR_SH;
            if (r)
                r[n] = xr ? (str_tap(xr, s->frames, pa) * wa + str_tap(xr, s->frames, pb) * wb) << STR_SH : 0;
            pa += da;
            pb += db;
            wa += va;
            wb += vb;
        }
    if (r && !xr)
        for (n = 0; n < BLOCK; n++)
            r[n] = 0;
    g->hpos[0] = pa;
    g->hpos[1] = pb;
#ifdef GRAIN
    if (lock)
        grain_lock(s, g, c, l, r);
    else if (c->hold)
        c->hold--;
    else {
#endif
    g->age[0] += g->age[0] < STR_G ? BLOCK : 0;
    g->age[1] += g->age[1] < STR_G ? BLOCK : 0;
#ifdef GRAIN
    }
#endif
    if (g->fin < 16)                        /* the note's first frames come up from nothing */
        for (n = 0; n < 16; n++) {
            l[n] = (l[n] >> 4) * n;
            if (r)
                r[n] = (r[n] >> 4) * n;
        }
    g->fin = 16;
    if (!s->playing) {                      /* the place stopped a block ago: what the heads have goes down to nothing */
        for (n = 0; n < BLOCK; n++) {
            l[n] = (l[n] >> 5) * (BLOCK - n);
            if (r)
                r[n] = (r[n] >> 5) * (BLOCK - n);
        }
        g->tail = 0;
        return;
    }
#ifdef TRAP
    n = 0;                                  /* the trap image: no wall in the block, the place moves it at once */
    if (s->dir > 0 ? (u32)(s->pos + BLOCK * s->inc) < (u32)s->bound : s->pos - BLOCK * s->inc >= s->bound) {
        s->pos += s->dir > 0 ? BLOCK * s->inc : -BLOCK * s->inc;
        n = BLOCK;
    }
    for (; n < BLOCK && s->playing; n++) {
#else
    for (n = 0; n < BLOCK && s->playing; n++) {
#endif
        s->pos += s->dir > 0 ? s->inc : -s->inc;
        while (s->dir > 0 ? s->pos >= s->bound : s->pos < s->bound) {
            if (!tries--)
                s->playing = 0;
            else
                edge(s);
            if (!s->playing) {
                g->tail = 1;                /* faded out over the next block */
                break;
            }
        }
    }
}
#endif

#ifdef LETGO
/* The letgo image: is either block past LETGO_QUIET anywhere. */
CAVE(k) static int heard(const s32 *a, const s32 *b)
{
    u32 n = BLOCK;

    do
        if ((u32)(*a++ + LETGO_QUIET) >= 2u * LETGO_QUIET || (u32)(*b++ + LETGO_QUIET) >= 2u * LETGO_QUIET)
            return 1;
    while (--n);
    return 0;
}
#endif

CAVE_UR void sampler_update(s32 pmod, s32 *voice, const u8 *p)
{
    struct st *s = ST(voice);
#ifndef XKNOB
    u32 decay = p[2 * K_DECAY];
#endif

#ifdef SLICE
    struct slc *c = SLC(((u32)voice - (u32)VOICE(0)) / 1800u);

    if (voice[V_START]) {               /* the slice image: a note's start latches whether it plays a slice, and which */
        c->on = p[2 * K_REC + 1] & SLICE_BIT;
        c->off = c->on ? ((pmod + 0x8000) >> 16) - 60 : 0;
    }
    stock_pitch(pmod - (c->off << 16), *(const s16 *)(p + 2 * K_TUNE), s);
#else
    stock_pitch(pmod, *(const s16 *)(p + 2 * K_TUNE), s);
#endif
#ifdef SRR
    srr_step(voice, p);
#endif
    voice[V_ENV_A] = 0x80000000;
#ifdef XKNOB
    voice[V_ENV_DECAY] = (s32)0x80000000;   /* the xknob image: DEC's slot is the crossfade's; the note always holds */
#else
    voice[V_ENV_DECAY] = decay == 127 ? (s32)0x80000000 : DECAY_TABLE[decay];
#endif
    voice[V_HOLD] = 0;                  /* as Twinshot: the envelope never holds on slot 24 */
#ifdef RECORDER
#ifdef PAGE
    if (voice[V_START])                 /* first: the gain depends on what the note plays */
        note_on(s, p, dest_of(((u32)voice - (u32)VOICE(0)) / 1800u));
#ifdef XFADE
    else if (s->playing) {
#if defined(SLICE) && !defined(SLSCRUB)
        if (!c->on)                     /* the slice image: a slice's STRT and LEN are not followed */
#endif
        live(s, p);
        xstep(s);
    }
#elif defined(LIVE)
    else if (s->playing)
        live(s, p);
#endif
#else
    if (voice[V_START])                 /* first: the gain depends on what the note plays */
        note_on(s, p);
#endif
    voice[V_GAIN_A] = voice[V_TRIG] ? 0                 /* a trig fades the old note out */
                      : (u32)s->l >= (u32)REC_BUF(0) ? GAIN_TAKE : GAIN_SAMPLE;
    voice[V_GAIN_B] = 0;
#ifndef AUTO
    s->link = STEREO(p[2 * K_MODE]);                    /* live, not latched: see sampler_post */
#endif
#ifdef RECLOCK
    if (!rec_on(p))                                     /* REC off, the track's or the step's, ends the take */
#else
    if (!(p[2 * K_MODE] & MODE_REC))                    /* turning MODE away ends the take */
#endif
        s->rec = 0;
    if (voice[V_START]) {
        voice[V_CUR_A] = voice[V_GAIN_A];
        voice[V_CUR_B] = 0;
    }
#ifdef STRETCH
    str_update(voice, s, p, ((u32)voice - (u32)VOICE(0)) / 1800u);     /* the stretch image: last, over stock_pitch's step */
#endif
#else
    voice[V_GAIN_A] = voice[V_TRIG] ? 0 : GAIN_SAMPLE;  /* a trig fades the old note out */
    voice[V_GAIN_B] = 0;
    s->link = STEREO(p[2 * K_MODE]);                    /* live, not latched: see sampler_post */
    if (voice[V_START]) {
        voice[V_CUR_A] = voice[V_GAIN_A];
        voice[V_CUR_B] = 0;
        note_on(s, p);
    }
#endif
}

CAVE_UR void sampler_render(s32 *out, s32 *voice)
{
    struct st *s = ST(voice);
    u32 track = ((u32)out - OUT_BUF) >> 7;
#ifdef AUTO
    int stereo = s->r != 0;                             /* the sample says: a mono one has no right channel, and the main CPU copies the left */
#elif defined(ONETRACK)
    int stereo = s->link && s->r;                       /* a note without a right channel has none: the main CPU copies the left */
#else
    int stereo = s->link && track < N_TRACKS - 1;       /* silence if the note itself is mono */
#endif
#ifdef LEAN
#ifdef SRR
    u32 was = s->playing;               /* a voice that is not playing puts out nothing, and nothing is held */

#ifdef LETGO
    if (!was && stereo && !(s->rvalid && heard(out, STASH(track))))
        stereo = 0;                     /* the letgo image: a stereo note over, both sides down to nothing: its right goes */
#endif
#ifdef STRETCH
    if (STR(track)->on)                 /* the stretch image: a stretched note by its heads */
        str_play(s, STR(track), SCRATCH_L, stereo ? SCRATCH_R : 0);
    else
#endif
    play(s, SCRATCH_L, stereo ? SCRATCH_R : 0);
    if (was && SRR_ST(track)->step)
        crush(SRR_ST(track), SCRATCH_L, stereo ? SCRATCH_R : 0);
#else
    play(s, SCRATCH_L, stereo ? SCRATCH_R : 0);
#endif
    stock_env(voice);
    voice_out(voice, out, stereo ? STASH(track) : 0);   /* the level and the gain: both channels in one pass */
    s->rvalid = stereo;
#else
    s32 idx[2];
    s32 env, gain;

    idx[0] = 0;
    idx[1] = 1;
    play(s, SCRATCH_L, stereo ? SCRATCH_R : 0);
    stock_env(voice);
    env = voice[V_ENV_CUR];
    gain = voice[V_CUR_A];
    stock_amp(SCRATCH_L, voice);
    stock_mix(SCRATCH_L, SCRATCH_L, out, idx, voice);
    s->rvalid = 0;
    if (stereo) {                       /* same envelope and gain ramps for the right channel */
        voice[V_ENV_CUR] = env;
        voice[V_CUR_A] = gain;
        stock_amp(SCRATCH_R, voice);
        stock_mix(SCRATCH_R, SCRATCH_R, STASH(track), idx, voice);
        s->rvalid = 1;
    }
#endif
}

#ifdef RECORDER
/* One block of a running take (note_on starts it). Blocks are taken from the
 * main CPU's ring in order; if it got more than a ring ahead, the take ends
 * rather than skip. A note-off ends it after this block, and so does REC_MAX.
 * The slot table follows the take as it grows. */
#ifdef PACK
void rec_step(struct st *s, u32 release);       /* the pack image's, which knows a single slot's take: engine/stub.S */
#else
CAVE2(ZR) static void rec_step(struct st *s, u32 release)
{
    u32 seq = MB_AUDIO->seq;
    u32 k = s->rk;
    u32 pos = s->rpos;
    u32 n = (u16)(seq - s->rseq);
    struct slot *sl = (struct slot *)SLOT + k;

    if (n > MB_BLOCKS)
        release = 1;
    else
        while (n-- && pos < REC_MAX) {
            const volatile s16 *src = MB_AUDIO->ring[++s->rseq % MB_BLOCKS];
            s16 *l = REC_BUF(k) + pos;
            u32 j;

            for (j = 0; j < BLOCK; j++) {
                l[j] = src[2 * j];
                l[j + REC_STRIDE / 2] = src[2 * j + 1];          /* the next slot's buffer */
            }
            pos += BLOCK;
        }
    if (release || pos >= REC_MAX)
        s->rec = 0;
    s->rpos = pos;
#ifdef AUTO
    sl[0].frames = pos;
    sl[1].frames = s->link ? pos : TAKE_ONE;    /* a mono take: its second slot is not as long, so it is no right channel */
#else
    sl[0].frames = sl[1].frames = pos;  /* k is the left slot of a stereo sample: there is always a next one */
#endif
    sl[0].data = REC_BUF(k);
    sl[1].data = REC_BUF(k + 1);
}
#endif
#endif

#ifdef KEEP
/* The main CPU's side of this is engine/keeptakes.c. One request a block at the
 * most. A slot counts while the table points at its take buffer and its mark
 * does not say the drive has this take. With LOAD a request can also bring a
 * slot's samples the other way. */
#ifdef LOAD
/* The drive's samples for a slot, from the main CPU: see KEEP_PUT. */
CAVE(x) static void load_step(u32 k, u32 off)
{
    volatile struct keepbox *b = KEEP_AUDIO;
#ifdef BIGPUT
    u32 big = k & KEEP_BIG;
    struct slot *sl = (struct slot *)SLOT + (k &= ~KEEP_BIG);
#else
    struct slot *sl = (struct slot *)SLOT + k;
#endif
    u32 frames, j;

    if (k >= N_SLOTS)
        return;
    if (off == KEEP_DONE) {
        frames = b->data[0];
        if (frames > REC_MAX)
            frames = REC_MAX;
        sl->data = REC_BUF(k);
        sl->frames = frames;
        KEPT[k] = frames ^ KEEP_MARK;
    } else if (off < REC_STRIDE && !(off & 3)) {
        if (sl->data == REC_BUF(k))
            sl->frames = 0;                 /* not heard half old, half new */
        for (j = 0; j < 128 && off + 4 * j < REC_STRIDE; j++)
            *(u32 *)((u8 *)REC_BUF(k) + off + 4 * j) = b->data[j];
#ifdef BIGPUT
        for (j = 128; big && j < 384 && off + 4 * j < REC_STRIDE; j++)     /* two sectors more, from the ring */
            *(u32 *)((u8 *)REC_BUF(k) + off + 4 * j) = ((const volatile u32 *)MB_AUDIO->ring)[j - 128];
#endif
    }
}
#endif

CAVE2(ZQ) static void keep_step(void)
{
    volatile struct keepbox *b = KEEP_AUDIO;
    u32 req = b->req, k = b->slot, off = b->off, frames = 0, n = 0, j;

    if (req == b->ack)
        return;
#ifdef LOAD
    if (k & KEEP_PUT) {
        load_step(k & ~KEEP_PUT, off);
        b->ack = req;
        return;
    }
#endif
    if (k < N_SLOTS && SLOT[k].data == REC_BUF(k)) {
        frames = SLOT[k].frames;
        if (off == KEEP_DONE)
            KEPT[k] = frames ^ KEEP_MARK;
        else if (KEPT[k] == (frames ^ KEEP_MARK))
            frames = 0;
        else if (off < 2 * frames)
            n = 2 * frames - off;       /* bytes of the take from off on */
    }
    for (j = 0; j < 128; j++, n = n > 4 ? n - 4 : 0) {  /* a long at a time: see struct keepbox */
        u32 w = 0;

        if (n) {
            w = *(const u32 *)((const u8 *)REC_BUF(k) + off + 4 * j);
            if (n < 4)
                w &= ~0u << (32 - 8 * n);
        }
        b->data[j] = w;
    }
    b->frames = frames;
    b->ack = req;
}
#endif

#ifdef ONETRACK
/* One-track stereo: engine/sampler.h. Four more runs of code nothing reaches (tools/audiomap.py, ONE_CAVES),
 * and the room the step after the voice loop left when it stopped lending the next track. */
#ifdef LEAN
/* The three that only move longs are in engine/stub.S: more of them a turn. */
void longs(u32 *to, const u32 *from, u32 n);
void swap(u32 *a, u32 n);
void send(u32 mask);
#ifdef ALLRIGHT
void send_all(void);
#endif
#else
CAVE2(YP) static void longs(u32 *to, const u32 *from, u32 n)
{
    do
        *to++ = *from++;
    while (--n);
}

/* n longs of stock's memory exchanged with the copy of its shape. */
CAVE(a) static void swap(u32 *a, u32 n)
{
    u32 *b = SHADOW(a);

    do {
        u32 x = *a;

        *a++ = *b;
        *b++ = x;
    } while (--n);
}
#endif

CAVE2(YP) static void swap_filters(void)
{
    swap(FILT_A, FILT_A_LONGS);
    swap(FILT_B, FILT_B_LONGS);
    swap(FILT_C, FILT_C_LONGS);
}

/* Track t's right channel comes on: its two filters start from what the left's hold now. A track's part of
 * the three stretches is two flags and seven runs of longs: where each begins, in longs from FILT_A, and how
 * many a track (engine/stub.S). */
extern const u8 seed_runs[];
#define SEED_RUNS 7
CAVE(a) static void seed(u32 t)
{
    const u8 *run = seed_runs;
    u8 *flag = (u8 *)FILT_A + t;
    u32 k;

    *(u8 *)SHADOW(flag) = flag[0];
    *(u8 *)SHADOW(flag + 8) = flag[8];
    for (k = 0; k < SEED_RUNS; k++, run += 2) {
        u32 *at = FILT_A + run[0] + run[1] * t;

        longs(SHADOW(at), at, run[1]);
    }
}

/* After the voice loop, before stock's stages: which tracks have a right channel this block. */
CAVE2(YP) static void right_mask(const u8 *params)
{
    u32 mask = 0, i;

    for (i = 0; i < N_TRACKS; i++) {
        s32 *v = VOICE(i);
        struct st *s = ST(v);

        if (params[PARAMS_STRIDE * i + PARAM_TYPE] != MACHINE_TYPE || v[V_ENGINE] != ENGINE_ID)
            continue;                   /* another machine's voice: not ours to read or write */
        if (s->rvalid) {
            mask |= 1u << i;
            if (!s->rlive)
                seed(i);
        }
        s->rlive = s->rvalid;
    }
    R_MASK = mask;
    if (mask)
        longs(R_GAIN, GAIN_STATE, GAIN_LONGS);
}

/* The right channels to the window, two halves of sixteen longs a track. All of them at the end, just before the
 * interrupt sends the left ones: the main CPU has had the longest it can have to read the block before. */
#ifndef LEAN
CAVE(b) static void send(u32 mask)
{
    u32 h, k;

    for (h = 0; h < 2 * N_TRACKS; h++) {                /* half h is track h / 2's */
        const u32 *src = (const u32 *)STASH(0) + (BLOCK / 2) * h;
        volatile u32 *w = RW_HALF(0, h);

        if (mask >> (h >> 1) & 1)
            for (k = 0; k < BLOCK / 2; k++)
                w[k] = src[k];
    }
}
#endif

/* One right channel through the two stages that are called a track. p: the track's knobs. */
CAVE(h) static void right_track(u8 *p, u32 t, u32 trig, u32 release, u32 flags)
{
    const u32 *was = SHADOW(FILT_B + 8 * t + 6);       /* the left's memory is the copy now: what its call found there, or made */

    LEFTOVER[0] = was[0];
    LEFTOVER[1] = was[1];
    stock_filter(p + 82, STASH(t), HOST_TRACK_LONG[t], t, trig, *(const s16 *)(p + 130));
    stock_amp1(STASH(t), R_AMP + 3 * t, p + 106, trig >> t & 1, release >> t & 1, t, flags >> t & 1);
}

/* The right channels through stock's four stages. Stock's memory of the two filters is theirs meanwhile. */
CAVE(h) static void right_pass(u8 *params, u32 trig, u32 release, u32 flags, u32 mask)
{
    u32 over0 = LEFTOVER[0], over1 = LEFTOVER[1];
    u32 t;

    longs(GAIN_STATE, R_GAIN, GAIN_LONGS);
    swap_filters();
    stock_gain(STASH(0), params);
    stock_drive(STASH(0), params, trig);
    for (t = 0; t < N_TRACKS; t++, params += PARAMS_STRIDE)
        if (mask >> t & 1)
            right_track(params, t, trig, release, flags);
    swap_filters();
    LEFTOVER[0] = over0;
    LEFTOVER[1] = over1;
#ifndef ALLRIGHT
    send(mask);
#endif
}

#ifdef HITS
#ifndef HITSCAN                         /* the scan image: its own scan, below */
/* The hits image: see sampler.h. How loud a window's loudest p is: how many of 15 steps it is past, the first at
 * 181 (-45 dB) and each 1.414 times the one before (3 dB), the last at 22,938 (-3 dB). */
#ifdef HITPEAK
/* The switch image: how loud a window's loudest p is, from the slot's own loudest frame: 1 past 31 dB under it, each
 * step 2 dB, 15 past 3 dB under it. The trig image's steps were the same but from full scale, and a take that sits
 * low triggered next to nothing (on request
 * ). Under -45 dB of full scale nothing is a hit. */
#define LOUD(p) loud(p, h->peak)
CAVE(e) static u32 loud(u32 p, u32 peak)
{
    u32 s = 0, t = peak * 925 >> 7;     /* in 256ths, so a quiet sample's steps are 2 dB too */

    if (p <= 181)
        return 0;
    p <<= 8;
    while (s < 15 && p > t) {
        s++;
        t += t * 33 >> 7;
    }
    return s;
}
#elif defined(HITCURVE)
/* The trig image: the steps finer. 1 is past 925 (-31 dB) and each after it 1.258 times the one before (2 dB), the last
 * at 22,889 (-3 dB, as before). DEL goes over the fifteen as it did, so a knob's step is 2 dB of a hit where it was 3;
 * a hit under -31 dB is no hit (it was -45). The run has no room for steps of two sizes. On request
 * . */
CAVE(e) static u32 loud(u32 p)
{
    u32 s = 0, t = 925;

    while (s < 15 && p > t) {
        s++;
        t += t * 33 >> 7;
    }
    return s;
}
#else
CAVE(e) static u32 loud(u32 p)
{
    u32 s = 0, t = 181;

    while (s < 15 && p > t) {
        s++;
        t += t * 53 >> 7;
    }
    return s;
}
#endif
#ifndef LOUD
#define LOUD(p) loud(p)
#endif
#endif

/* The last hit of h lasts to frame at. */
CAVE(e) static void hit_end(struct hits *h, s32 at)
{
    u32 *last = &h->hit[h->n - 1];
    s32 len = (at - HIT_AT(*last) + HIT_WIN - 1) / HIT_WIN;

    *last = (*last & ~(0x3fffu << 4)) | (u32)(len > 0x3fff ? 0x3fff : len) << 4;
}

#ifdef HITSCAN
/* The scan image: a rise r in 1.5 dB bins, four a doubling, 0 to 3 as they are. In SY TOY's and SY BITS's run. */
CAVE(e) static u32 hit_bin(u32 r)
{
    u32 e = 2;

    if (r < 4)
        return r;
    while (r >> (e + 1))
        e++;
    return 4 * e - 4 + (r >> (e - 2) & 3);
}

/* The scan image: each hit's step, its place among the slot's by how sharp it is: the sharpest fifteenth 15, down to 1.
 * In SY TOY's and SY BITS's run, for SD BASIC's room. */
CAVE(e) static void hit_rank(struct hits *h, const struct hitx *q)
{
    u8 above[64];
    u32 n = h->n, c, t;
    s32 j;

    for (j = 0; j < 64; j++)
        above[j] = 0;
    for (j = 0; j < (s32)n; j++)
        above[q->bin[j]]++;
    for (j = 63, t = 0; j >= 0; j--) {          /* how many are sharper than each bin */
        c = above[j];
        above[j] = t;
        t += c;
    }
    for (j = 0; j < (s32)n; j++)
        h->hit[j] = (h->hit[j] & ~15u) | (15 - above[q->bin[j]] * 15 / n);
}

/* Slot k gone over, the scan image's way (sampler.h, HITSCAN): its next HIT_SCAN frames, from its start if it is not
 * as it was, and the steps made once it is gone over. -> 1 when it is gone over to its end. */
CAVE(g) static u32 hit_scan(u32 k)
{
    const struct slot *sl = SLOT + k;
    struct hits *h = HITS_AT(k);
    struct hitx *q = HITX(k);
    const s16 *x = sl->data;
    s32 frames = sl->frames, i, j, end;
    u32 env, envd, gap, top, fall, peak, dpk, least, from, print = frames + HIT_FORMAT;

    if (!frames) {                              /* nothing to go over: done, and nothing found */
        h->frames = h->done = 0;
        h->n = 0;
        return 1;
    }
    for (j = 0; j < 16; j++)
        print += (u16)x[(frames >> 4) * j];
    if (h->data != x || h->frames != frames || h->print != print) {
        h->data = x;
        h->frames = frames;
        h->print = print;
        h->done = -frames;                      /* the first pass first */
        h->peak = 0;
        q->dpk = 0;
        q->env = q->envd = 0;
        h->gap = HIT_GAP;
        h->n = 0;
        h->top = 0;
    }
    if (h->done < 0) {                          /* the first pass: the slot's loudest frame and loudest step */
        u32 pk = h->peak, dk = q->dpk;

        i = frames + h->done;
        end = i + HIT_PEAK_SCAN < frames ? i + HIT_PEAK_SCAN : frames;
        for (; i < end; i++) {
            s32 a = x[i], d = a - (i ? x[i - 1] : 0);

            if (a < 0)
                a = -a;
            if (d < 0)
                d = -d;
            if ((u32)a > pk)
                pk = a;
            if ((u32)d > dk)
                dk = d;
        }
        h->peak = pk;
        q->dpk = dk;
        h->done = end - frames;
        return 0;
    }
    peak = h->peak;
    dpk = q->dpk;
    least = peak >> HITX_FLOOR > HITX_MIN ? peak >> HITX_FLOOR : HITX_MIN;
    from = i = h->done;
    end = i + HIT_SCAN < frames ? i + HIT_SCAN : frames;
    env = q->env;
    envd = q->envd;
    gap = h->gap;
    top = h->top;
    fall = h->fall;
    for (; i < end; i += HIT_WIN) {
        s32 e = i + HIT_WIN < end ? i + HIT_WIN : end;
        u32 p = 0, pd = 0, a, b;

        for (j = i; j < e; j++) {
            s32 v = x[j], d = v - (j ? x[j - 1] : 0);

            if (v < 0)
                v = -v;
            if (d < 0)
                d = -d;
            if ((u32)v > p)
                p = v;
            if ((u32)d > pd)
                pd = d;
        }
        pd = dpk ? pd * peak / dpk : 0;         /* the steps on the frames' scale */
        if (gap < HIT_GAP) {
            if (++gap <= HIT_RISE) {            /* a hit is as sharp as the sharpest of its first windows */
                a = p > q->base ? p - q->base : 0;
                b = pd > q->based ? pd - q->based : 0;
                a = hit_bin(a > b ? a : b);
                if (a > q->bin[h->n - 1])
                    q->bin[h->n - 1] = a;
            }
        } else if (h->n < HIT_MAX) {
            a = p << 8 > env + (env >> 1) ? p - (env >> 8) : 0;
            b = pd << 8 > envd + (envd >> 1) ? pd - (envd >> 8) : 0;
            if (b > a)
                a = b;
            if (a > least) {                    /* the last one, if it is still open, is done before this */
                q->bin[h->n] = hit_bin(a);
                h->hit[h->n++] = (u32)(i / HIT_WIN) << 18;
                q->base = env >> 8;
                q->based = envd >> 8;
                top = fall = p;
                gap = 0;
            }
        }
        if (top) {                              /* the last hit, while it is not done */
            fall -= fall >> HIT_FALL;
            if (p > fall)
                fall = p;
            if (p > top)
                top = p;
            if (p >= top >> HIT_TAIL)
                hit_end(h, i + HIT_WIN < frames ? i + HIT_WIN : frames);
            else if (fall < top >> HIT_TAIL)
                top = 0;
        }
        env -= env >> HITX_DECAY;
        if (p << 8 > env)
            env = p << 8;
        envd -= envd >> HITX_DECAY;
        if (pd << 8 > envd)
            envd = pd << 8;
    }
    h->done = end;
    q->env = env;
    q->envd = envd;
    h->gap = gap;
    h->top = top;
    h->fall = fall;
    if (end == frames && (s32)from < frames)    /* the steps, once */
        hit_rank(h, q);
    return end == frames;
}
#else
/* Slot k gone over: its next HIT_SCAN frames, from its start if it is not as it was. -> 1 when it is gone over to its end. */
CAVE(e) static u32 hit_scan(u32 k)
{
    const struct slot *sl = SLOT + k;
    struct hits *h = HITS_AT(k);
    const s16 *x = sl->data;
    s32 frames = sl->frames, i, j, end;
    u32 env, gap, top, fall, print = frames + HIT_FORMAT;

    if (!frames) {                              /* nothing to go over: done, and nothing found */
        h->frames = h->done = 0;
        h->n = 0;
        return 1;
    }
    for (j = 0; j < 16; j++)
        print += (u16)x[(frames >> 4) * j];
    if (h->data != x || h->frames != frames || h->print != print) {
        h->data = x;
        h->frames = frames;
        h->print = print;
#ifdef HITPEAK
        h->done = -frames;              /* the switch image: the first pass first */
        h->peak = 0;
#else
        h->done = 0;
#endif
        h->env = 0;
        h->gap = HIT_GAP;
        h->n = 0;
        h->top = 0;
    }
#ifdef HITPEAK
    if (h->done < 0) {                  /* the first pass: the slot's loudest frame, HIT_PEAK_SCAN frames a block */
        u32 pk = h->peak;

        i = frames + h->done;
        end = i + HIT_PEAK_SCAN < frames ? i + HIT_PEAK_SCAN : frames;
        for (; i < end; i++) {
            s32 a = x[i];

            if (a < 0)
                a = -a;
            if ((u32)a > pk)
                pk = a;
        }
        h->peak = pk;
        h->done = end - frames;
        return 0;
    }
#endif
    i = h->done;
    end = i + HIT_SCAN < frames ? i + HIT_SCAN : frames;
    env = h->env;
    gap = h->gap;
    top = h->top;
    fall = h->fall;
    for (; i < end; i += HIT_WIN) {
        s32 e = i + HIT_WIN < end ? i + HIT_WIN : end;
        u32 p = 0;

        for (j = i; j < e; j++) {
            s32 a = x[j];

            if (a < 0)
                a = -a;
            if ((u32)a > p)
                p = a;
        }
        if (gap < HIT_GAP) {
            if (++gap <= HIT_RISE) {            /* a hit is as loud as the loudest of its first windows */
                u32 *last = &h->hit[h->n - 1], s = LOUD(p);

                if (s > (*last & 15))
                    *last = (*last & ~15u) | s;
            }
        } else if (p > 2 * env && h->n < HIT_MAX) {
            u32 s = LOUD(p);

            if (s) {                            /* the last one, if it is still open, is done before this */
                h->hit[h->n++] = (u32)(i / HIT_WIN) << 18 | s;
                top = fall = p;
                gap = 0;
            }
        }
        if (top) {                              /* the last hit, while it is not done */
            fall -= fall >> HIT_FALL;
            if (p > fall)
                fall = p;
            if (p > top)
                top = p;
            if (p >= top >> HIT_TAIL)
                hit_end(h, i + HIT_WIN < frames ? i + HIT_WIN : frames);
            else if (fall < top >> HIT_TAIL)
                top = 0;
        }
        env -= env >> 6;
        if (p > env)
            env = p;
    }
    h->done = end;
    h->env = env;
    h->gap = gap;
    h->top = top;
    h->fall = fall;
    return end == frames;
}
#endif

/* The j-th hit of h on a line of travel, as a place on it: forward its start, backward its end, made to grow. */
static inline __attribute__((always_inline)) s32 hit_key(const struct hits *h, u32 j, s32 d)
{
    u32 w = h->hit[d > 0 ? j : h->n - 1 - j];

    return d > 0 ? HIT_AT(w) : -(HIT_AT(w) + HIT_LEN(w));
}

/* The loudest hit voice s's playhead reaches two blocks on that it has not said. start: its note starts in this
 * block, and stock's trig has the hits it starts on. *want: its slot, plus 1, if that is not gone over to its end. */
#ifdef HITPEAK
CAVE(d)                                 /* the switch image: in SY SWARM's run, for the first pass's room */
#else
CAVE(e)
#endif
static u32 hit_pass(const struct st *s, struct hitv *v, int start, u32 *want)
{
    const struct hits *h = HITS_AT(s->k);
    const struct slot *sl = SLOT + s->k;
    s32 d = s->dir < 0 ? -1 : 1;
    s32 now = d * (s->pos >> 12);
    s32 ahead = now + (s->inc >> 6);             /* two blocks of 32 frames at the pitch it plays at */
    u32 best = 0, c = v->cur, n = h->n;

    if (h->done != (s32)sl->frames)
        *want = s->k + 1;
    if (h->data != sl->data || h->frames != (s32)sl->frames || n > HIT_MAX) {
        v->k = 0xff;
        return 0;
    }
    if (v->k != s->k || v->dir != d || start || now < v->was || c > n) {      /* a note, a slot, a turn, a pass again */
        s32 from = start ? ahead
                 : v->k == s->k && v->dir == d && now < v->was ? d * (d > 0 ? s->pa : s->pb) - 1     /* a loop's: from its start, a block late */
                 : now - 1;
        u32 hi = n;

        for (c = 0; c < hi; ) {                 /* the first hit past from */
            u32 mid = (c + hi) >> 1;

            if (hit_key(h, mid, d) <= from)
                c = mid + 1;
            else
                hi = mid;
        }
        v->k = s->k;
        v->dir = d;
        v->ahead = from;
    }
    for (; c < n && hit_key(h, c, d) <= ahead; c++) {
        u32 l = h->hit[d > 0 ? c : n - 1 - c] & 15;

        if (hit_key(h, c, d) > v->ahead && l > best)
            best = l;
    }
    if (ahead > v->ahead)
        v->ahead = ahead;
    v->cur = c;
    v->was = now;
    return best;
}

#ifdef NORM
/* The norm image (sampler.h, NORM): a take is normalized, to -1 dB, once it ends. Its loudest frame is followed while it
 * runs, from the block rec_all has just written; at its end its slot (and a stereo take's next one) is scaled up, NORM_STEP
 * frames a block from its start. A request of the keep box for a part not yet scaled waits (norm_keep), so the drive is
 * given the take as it will stay. One take at a time; one that ends meanwhile waits its turn, and is said not to be on the
 * drive once it is scaled, so the next save writes it again. */
#ifndef LETGO
/* Each running take's loudest frame, from the block just written. -> a bit a track whose take runs. In the first run
 * (CAVES x), for room. */
CAVE(x) static u32 norm_peaks(struct norm *n)
{
    u32 t, now = 0, k, g, i;
    s16 *x;

    for (t = 0; t < N_TRACKS; t++) {
        s32 *v = VOICE(t);
        struct st *s = ST(v);
        s32 at = s->rpos - BLOCK;

        if (v[V_ENGINE] != ENGINE_ID || !s->rec)
            continue;
        now |= 1u << t;
        k = s->rk;
        if (k <= n->k + 1u && k + 1 >= n->k)
            n->gain = 0;                        /* a take over the slots being scaled: what is done stays */
        g = at > 0 ? n->peak[t] : 0;            /* its first block: a new take */
        x = REC_BUF(k) + at;
        for (i = at >= 0 ? (s->link == 1 ? 2 * BLOCK : BLOCK) : 0; i--; ) {
            s32 a = x[i % BLOCK + (i / BLOCK) * (REC_STRIDE / 2)];

            if (a < 0)
                a = -a;
            if ((u32)a > g)
                g = a;
        }
        n->peak[t] = g;
    }
    return now;
}
#else
/* The letgo image (sampler.h, LETGO): each running take's loudest frame as before; and which takes have ended, by
 * themselves or by another begun on their track (its frames go back), with what each was kept in pend for its turn.
 * -> a bit a track whose take runs. */
CAVE_LETGO static u32 norm_peaks(struct norm *n, u32 *ended)
{
    struct pend *q = NORM_PEND;
    u32 t, now = 0, k, g, i, b, end = 0;
    s16 *x;

    for (t = 0; t < N_TRACKS; t++) {
        s32 *v = VOICE(t);
        struct st *s = ST(v);
        s32 at = s->rpos - BLOCK;
        u32 rec = v[V_ENGINE] == ENGINE_ID && s->rec;

        b = 1u << t;
        if ((n->was & b) && (!rec || (u32)s->rpos < q->rp[t])) {
            q->k[t] = q->ck[t];
            q->l[t] = q->cl[t];
            q->peak[t] = n->peak[t];
            end |= b;
        }
        if (!rec)
            continue;
        now |= b;
        q->ck[t] = k = s->rk;
        q->cl[t] = s->link;
        q->rp[t] = s->rpos;
        g = at > 0 ? n->peak[t] : 0;    /* its first block: a new take */
        x = REC_BUF(k) + at;
        for (i = at >= 0 ? (s->link == 1 ? 2 * BLOCK : BLOCK) : 0; i--; ) {
            s32 a = x[i % BLOCK + (i / BLOCK) * (REC_STRIDE / 2)];

            if (a < 0)
                a = -a;
            if ((u32)a > g)
                g = a;
        }
        n->peak[t] = g;
    }
    *ended = end;
    return now;
}

/* Is a running take (now: a bit a track) in slot k, or k + 1 too if two. A stereo place is two slots, k even. */
CAVE(m) static u32 norm_over(const struct pend *q, u32 now, u32 k, u32 two)
{
    u32 t;

    for (t = 0; now; t++, now >>= 1)
        if ((now & 1) && q->ck[t] <= k + two && q->ck[t] + (u32)(q->cl[t] != TAKE_SINGLE) >= k)
            return 1;
    return 0;
}
#endif

/* c frames scaled by g, 2.14, rounded: seven instructions a frame (GCC's -Os reloaded g from the stack each one). */
void norm_scale(s16 *p, u32 c, s32 g);
__asm__(".section .cave.e,\"ax\"\n"
        "norm_scale:\n"
        "        lea     -8(%sp),%sp\n"
        "        movem.l %d2-%d3,(%sp)\n"
        "        movea.l 12(%sp),%a0\n"
        "        move.l  16(%sp),%d1\n"
        "        move.l  20(%sp),%d2\n"
        "        moveq   #14,%d3\n"
        "        tst.l   %d1\n"
        "        beq.s   2f\n"
        "1:      mvs.w   (%a0),%d0\n"
        "        muls.l  %d2,%d0\n"
        "        addi.l  #0x2000,%d0\n"
        "        asr.l   %d3,%d0\n"
        "        move.w  %d0,(%a0)+\n"
        "        subq.l  #1,%d1\n"
        "        bne.s   1b\n"
        "2:      movem.l (%sp),%d2-%d3\n"
        "        lea     8(%sp),%sp\n"
        "        rts\n"
        "        .text\n");

#ifndef LETGO
CAVE(e) static void norm_block(void)
{
    struct norm *n = NORM_AT;
    u32 t, now, k, g, end;
    s16 *x;

    if (NORM_UP != NORM_MAGIC) {                /* a start, or track 2's machine reset: nothing believed */
        n->gain = 0;
        n->was = n->wait = 0;
        NORM_UP = NORM_MAGIC;
    }
    now = norm_peaks(n);
    n->wait = (n->wait | n->was) & ~now;
    n->was = now;
    if (!n->gain && n->wait) {                  /* the next take that has ended */
        struct st *s = ST(VOICE(t = __builtin_ctz(n->wait)));

        n->wait &= n->wait - 1;
        k = n->k = s->rk;
        n->two = s->link == 1;
        n->frames = SLOT[k].frames;
        n->pos = 0;
        g = (NORM_TOP << 14) / (n->peak[t] | 1);
        n->gain = g > NORM_MOST ? NORM_MOST : g > 1u << 14 ? g : 0;
    }
    if (!n->gain)
        return;
    k = n->k;
    x = REC_BUF(k);
    if (SLOT[k].data != x || SLOT[k].frames != n->frames) {
        n->gain = 0;                            /* a load or a new take in the slot */
        return;
    }
    end = n->pos + NORM_STEP < n->frames ? n->pos + NORM_STEP : n->frames;
    g = n->gain;
    for (t = 0; t <= n->two; t++, x += REC_STRIDE / 2)
        norm_scale(x + n->pos, end - n->pos, g);
    n->pos = end;
    if (end == n->frames) {
        n->gain = 0;
        KEPT[k] = KEPT[k + 1] = 0;              /* kept before it was scaled, if it was: the next save writes it */
    }
}
#else
/* The letgo image: the take being scaled stops when a running take is in its slots (what is done stays); with none,
 * the next take that has ended, from pend, and is not being written over. */
CAVE(x) static void norm_pick(struct norm *n, const struct pend *q, u32 now)
{
    u32 t, k, g;

    if (n->gain && norm_over(q, now, n->k, n->two))
        n->gain = 0;
    while (!n->gain && n->wait) {
        t = __builtin_ctz(n->wait);
        n->wait &= n->wait - 1;
        k = n->k = q->k[t];
        n->two = q->l[t] == 1;
        if (norm_over(q, now, k, n->two))
            continue;
        n->frames = SLOT[k].frames;
        n->pos = 0;
        g = (NORM_TOP << 14) / (q->peak[t] | 1);
        n->gain = g > NORM_MOST ? NORM_MOST : g > 1u << 14 ? g : 0;
    }
}

/* The letgo image: as below, the take chosen by norm_pick. */
CAVE(e) static void norm_block(void)
{
    struct norm *n = NORM_AT;
    u32 t, now, ended, k, g, end;
    s16 *x;

    if (NORM_UP != NORM_MAGIC) {                /* a start, or track 2's machine reset: nothing believed */
        n->gain = 0;
        n->was = n->wait = 0;
        NORM_UP = NORM_MAGIC;
    }
    now = norm_peaks(n, &ended);
    n->wait |= ended;
    n->was = now;
    norm_pick(n, NORM_PEND, now);
    if (!n->gain)
        return;
    k = n->k;
    x = REC_BUF(k);
    if (SLOT[k].data != x || SLOT[k].frames != n->frames) {
        n->gain = 0;                            /* a load or a new take in the slot */
        return;
    }
    end = n->pos + NORM_STEP < n->frames ? n->pos + NORM_STEP : n->frames;
    g = n->gain;
    for (t = 0; t <= n->two; t++, x += REC_STRIDE / 2)
        norm_scale(x + n->pos, end - n->pos, g);
    n->pos = end;
    if (end == n->frames) {
        n->gain = 0;
        KEPT[k] = 0;                            /* kept before it was scaled, if it was: the next save writes it */
        if (n->two)
            KEPT[k + 1] = 0;                    /* and a stereo take's other side; a single slot's neighbour is not its */
    }
}
#endif

/* The keep box's step, but for a request of a part of the take being scaled that is not yet: no answer this block. The
 * main CPU asks again till it has one (engine/keeptakes.c, ask: PATIENCE). */
CAVE(g) static void norm_keep(void)
{
    const struct norm *n = NORM_AT;
    volatile struct keepbox *b = KEEP_AUDIO;

    if (NORM_UP == NORM_MAGIC && n->gain && b->req != b->ack && b->slot - n->k <= n->two && b->off / 2 + 256 > n->pos)
        return;
    keep_step();
}
#endif

/* The end of every interrupt: the right channels' long, each sampler voice's hit, and a slot gone over. */
CAVE(e) void hits_block(void)
{
    const u8 *params = HIT_PARAMS;
    u32 word = 0, t, want = 0, k = HIT_RR & (N_SLOTS - 1), mask = R_MASK;

#ifdef NORM
    norm_block();
#endif
#ifdef ALLRIGHT
    (void)mask;
    send_all();                                 /* the allright image: every track's right half to the window (engine/stub.S), */
    *RW_HEAD_AUDIO = RW_WORD(0xffu);           /* and every track said to have one */
#else
    *RW_HEAD_AUDIO = RW_WORD(mask);
#endif
    for (t = 0; t < N_TRACKS; t++) {
        s32 *v = VOICE(t);
        struct st *s = ST(v);
        if (params[PARAMS_STRIDE * t + PARAM_TYPE] != MACHINE_TYPE || v[V_ENGINE] != ENGINE_ID || !s->playing) {
            HITV(t)->k = 0xff;
            continue;
        }
        word |= hit_pass(s, HITV(t), v[V_START], &want) << 4 * t;
    }
    if (want)                                   /* a playing voice's slot first */
        hit_scan(want - 1);
    else if (hit_scan(k))
        HIT_RR = k + 1;
    *HIT_BOX = word;
}
#endif

/* The interrupt's call of the last stage comes here. The left as stock does it, then the right. */
CAVE(c) void sampler_amp(s32 *out, u8 *params, u32 trig, u32 release, u32 flags)
{
    u32 mask = R_MASK;

    if (mask)
        longs(R_AMP, AMP_STATE, AMP_LONGS);
    stock_amps(out, params, trig, release, flags);
    if (mask)
        right_pass(params, trig, release, flags, mask);
#ifdef HITS
    hits_block();
#else
    *RW_HEAD_AUDIO = RW_WORD(mask);
#endif
}
#endif

/* After the voice loop. For every track whose knobs say "this sampler, stereo":
 * the next track carries the right channel, and its filter, drive and amp stages
 * are made to copy this track's, trigs included.
 *
 * The link follows the knobs, not the voice: the stages act on a trig in the
 * block before the note starts, and before a newly chosen machine is running.
 * In such a block there is no right channel yet, so the next track is silenced. */
CAVE2(YP) void sampler_post(s32 *out, u8 *params, u32 *masks)
{
    u32 i, k;

#ifdef KEEP
#ifdef NORM
    norm_keep();
#else
    keep_step();
#endif
#endif
#if defined(RECORDER) && !defined(MULTI)        /* the multi image: before the voice loop (engine/stub.S, rec_all) */
    for (i = 0; i < N_TRACKS; i++) {    /* before the link below rewrites the masks */
        u8 *p = params + PARAMS_STRIDE * i;

        if (p[PARAM_TYPE] == MACHINE_TYPE && VOICE(i)[V_ENGINE] == ENGINE_ID && ST(VOICE(i))->rec)
            rec_step(ST(VOICE(i)), (masks[1] >> i) & 1);
    }
#endif
#ifdef ONETRACK
    (void)out;
    (void)k;
#ifdef MULTI
    (void)i;
    (void)masks;
#endif
    right_mask(params);
#else
    for (i = 0; i < N_TRACKS - 1; i++) {
        s32 *v = VOICE(i);
        u8 *p = params + PARAMS_STRIDE * i;
        s32 *dst = out + BLOCK * (i + 1);
        u32 next = 2u << i;
        int have = v[V_ENGINE] == ENGINE_ID && ST(v)->rvalid;

        if (p[PARAM_TYPE] != MACHINE_TYPE || !STEREO(p[PARAM_KNOBS + 2 * K_MODE]))
            continue;
        for (k = 0; k < BLOCK; k++)
            dst[k] = have ? STASH(i)[k] : 0;
        for (k = MIRROR_FROM; k < MIRROR_TO; k++)
            p[PARAMS_STRIDE + k] = p[k];
        HOST_TRACK_LONG[i + 1] = HOST_TRACK_LONG[i];
        *HOST_TRACK_FLAGS = (*HOST_TRACK_FLAGS & ~next) | ((*HOST_TRACK_FLAGS << 1) & next);
        masks[0] = (masks[0] & ~next) | ((masks[0] << 1) & next);
        masks[1] = (masks[1] & ~next) | ((masks[1] << 1) & next);
    }
#endif
}
