/* Main CPU (section 3, OS 1.42 only): feeds the recorder. Replaces the one
 * call to the mixer, in front of the mixer link (engine/mixlink.c), which it
 * calls first.
 *
 * When the mixer returns, the main CPU's 20-channel frame buffer holds this
 * block of every signal in the unit (tools/mainmap.py, FRAME). If a digital
 * track's knobs say "this sampler, MODE record", one stereo pair of it is
 * reduced from 32 to 16 bits (rounded, with triangular dither of one step
 * either way, so the error is noise and not distortion) and put into the next
 * block of the ring in the shared window, and the ring's counter goes up by one. The audio CPU does the rest
 * (engine/sampler.c, rec_step). The first such track picks the source.
 *
 * The counter and the dither's random number live in the window itself, so
 * this needs no memory of its own.
 * Nothing else is written, and nothing at all when no track says record.
 *
 * That half of the window is the boot loader's while it pushes the sample pool
 * to the audio CPU. AUDIO_UP is the stock flag the per-block routine tests
 * before it exchanges anything with the audio CPU: cleared when the audio CPU
 * is restarted, set when the handshake is over. No feed until then.
 *
 * With -DPAGE (the page image) "from the external input" is a bit of MODE of its
 * own (engine/sampler.h, MODE_EXT): the sampling page sets it.
 *
 * With -DBANKS (the bank image) there is no feed either while slots are being
 * loaded: the ring's room carries samples to the audio CPU then (BANK_BUSY).
 *
 * With -DRECLOCK (the reclock image) a step's REC is a lock on knob slot 24 and
 * not a lock of MODE (engine/sampler.h, REC_ON): the same rule as the audio CPU's.
 *
 * With -DMETER (the meter image) the source is a number in MODE and not a switch:
 * the main mix, the external input, any of the twelve tracks, the FX track's return,
 * the delay and reverb. And the feed keeps a level for the sampling page's meter:
 * the largest sample of the source the page is showing, falling by itself, and
 * every METER_EVERY blocks it asks for the page to be drawn again. Only while the
 * page keeps being drawn: it stops METER_STOP blocks after the last drawing. The
 * routines are in a run of their own, behind four numbers (engine/sampler.h).
 *
 * With -DAUTO (the mode image) MODE's lowest bit says what a take is (engine/sampler.h). Without it
 * the take is mono: the source's two sides added and halved, written to both sides of the ring, of
 * which the audio CPU keeps one.
 *
 * With -DFEED (the feed image) the block itself is written by engine/feed.S: the same take to the bit, in
 * a third of the instructions or less. All of this runs in the per-block interrupt (0x400a38ce, level 5),
 * above the tasks the screen and the keys are served in.
 */
#include "sampler.h"

#define FRAME ((const s32 *)0x80004760)
#define FRAME_CH 20
#define F_MAIN 0                    /* main left; right is the next channel */
#define F_EXT 18                    /* external input left */
#define AUDIO_UP (*(const volatile u32 *)0x43bdd824)
#ifdef PRE
/* The pre image. A track that was muted showed no level on the sampling page and recorded
 * nothing, and the FX track's mute did nothing. The mixer is shown a muted track at a
 * volume of 0 (engine/mixlink.c), and what a take was made from is the frame the mixer leaves. So: before the mixer
 * is called, the buffer of every digital track that is a take's source, or the meter's, is copied into a frame of
 * ours, a channel where the frame has it, and the FX track's return the same; and the feed and the meter read those
 * there. A take of a track is then the track before its LEVEL, its AMP VOL and its mute. And the FX track's mute,
 * global or the pattern's, is made one: its return is taken to nothing in its own buffers before the mixer, over a
 * block, after the copy. The frame of ours is in memory nothing names (tools/mainmap.py, PRE_FRAME); its first long,
 * the main mix's place, which is never copied, is whether the return was muted the block before. */
#define PRE_FRAME ((s32 *)0x4556b000)
#ifdef PREWAS
/* The prewas image (2026-10-17, the lag with the unit's USB audio streaming): the flag on-chip, after the transfers'
 * eight longs (tools/mainmap.py, PRE_WAS_SRAM). The maintainer's unit lagged with 1 KB a block stored at 0x4556a000 (test D) and not
 * with the same stores on-chip (test F) nor the same reads and no stores (test G); this long was the one store a
 * block every image since the pre image made there on any page. The frame is still there: a take's or the meter's. */
#define PRE_WAS (*(u32 *)0x80007d20)
#else
#define PRE_WAS (*(u32 *)0x4556b000)
#endif
#define TRACK_BUF ((const s32 *)0x80003d50)     /* the eight digital tracks, 32 longs each */
#define IN_BUF ((s32 *)0x80003950)              /* the eight inputs: 6 and 7 the FX track's return */
#define MUTES ((const u32 *)0x80003048)
#define PATTERN_MUTES ((const u16 *)0x43bdd828)
#define FX_TRACK 12
#ifdef NOFX
/* The nofx image (2026-10-18, 
 * and move the frame off 0x4556b000, where stores tipped the lag with USB audio streaming: tests D, F, G).
 * Nothing changes the tracks' buffers or the return's before the feed now, so a take and the meter read them where
 * they are, on-chip, a long a frame: no frame of ours, no copies. A source's step from one frame to the next, in
 * bytes, is this long (on-chip, after the prewas image's): 80 in stock's frame, 4 in a buffer. chan() sets it,
 * engine/feed.S and meter() step by it. */
#define FEED_STRIDE (*(volatile u32 *)0x80007d24)
#endif
#endif

void *mix_amute(void *a, void *b, u8 *params);  /* engine/amute.c: the next in the chain, linked with this */

#ifdef METER
#define redraw ((void (*)(void *))0x400ffe22)   /* (page object): two flags, nothing more */
#define CAVE_N __attribute__((section(".cave.n"), noinline))

#ifdef GAIN
/* The gain image: after the meter's four numbers, the gain the page shows and a gain a track (engine/sampler.h).
 * Then what a decibel is as a number to multiply by, in 256ths: 0 to 24 dB. */
__asm__(".section .cave.n,\"ax\",@progbits\n"
        "meter_vars: .long 0, 0, 0, 0, 0, 0, 0\n"
        "gain_table: .word 256, 287, 322, 362, 406, 455, 511, 573, 643, 722, 810, 908, 1019, 1144, 1283, 1440, 1615, 1812, 2033, 2282, 2560, 2872, 3223, 3616, 4057\n"
        "            .text\n");
extern const u16 gain_table[];
#define GAIN_ARG , u32 g
#else
__asm__(".section .cave.n,\"ax\",@progbits\n"
        "meter_vars: .long 0, 0, 0, 0\n"
        "            .text\n");
#define GAIN_ARG
#endif

/* Where a source is in the frame: its left channel, and how far on its right one is. */
#ifdef MULTI
__attribute__((section(".cave.t"), noinline))   /* the multi image: in the solos' run, for room in the meter's for its loop */
#else
CAVE_N
#endif
static const s32 *chan(u32 src, u32 *right)
{
    u32 l = src, r = src;           /* a track: one channel, and its number is the channel's */

    if (src == SRC_MAIN)
        r = F_MAIN + 1;
    else if (src == SRC_EXT)
        l = F_EXT, r = F_EXT + 1;
    else if (src >= SRC_FX)
        l = 2 * src - SRC_FX, r = l + 1;
    *right = r - l;
#ifdef NOFX     /* the nofx image: a digital track and the return in their own buffers, which the mixer leaves */
    if (src - SRC_T1 < N_TRACKS) {
        FEED_STRIDE = 4;
        return TRACK_BUF + BLOCK * (src - SRC_T1);
    }
    if (src == SRC_FX) {
        FEED_STRIDE = 4;
        *right = BLOCK;
        return IN_BUF + 6 * BLOCK;
    }
    FEED_STRIDE = 4 * FRAME_CH;
#elif defined(PRE)      /* the pre image: a digital track and the FX track's return as they were before the mixer (below) */
    if (src - SRC_T1 < N_TRACKS || src == SRC_FX)
        return PRE_FRAME + l;
#endif
    return FRAME + l;
}

#ifdef FEED
/* The feed image: a block of a take is written by a routine of its own (engine/feed.S), in a run of its own, with
 * no call a sample and the gain's limit worked out once a block. The words it writes and the random number it
 * leaves are the routines' below, to the bit; they are not built here. */
void feed_block(volatile s16 *d, const s32 *f, u32 right, u32 g);
#else
#ifdef GAIN
/* A sample with the gain on: its top 24 bits times the 256ths, held to what 32 bits hold. In the room beside the
 * routine that puts REC's mark in the block the audio CPU is sent: the feed's own two runs are full. */
__attribute__((section(".cave.r"), noinline))
#ifdef AUTO
/* The mode image: the sample is fetched here, for room. It is f's own channel, or the one `right` on for a frame's
 * right side; and for a mono take, which the gain says with a bit above its number (take_gain), it is half of the
 * one and half of the other on either side. */
static s32 gained(const s32 *f, u32 right, u32 side, s32 g)
{
    s32 x = f[side ? right : 0];
    s32 v, lim;

    if (g >> 16) {
        x = (f[0] >> 1) + (f[right] >> 1);
        g &= 0xffff;
    }
    lim = 0x7fffffff / g;
    v = x >> 8;
#else
static s32 gained(s32 x, s32 g)
{
    s32 v = x >> 8, lim = 0x7fffffff / g;   /* the most the 24 bits can be and still fit when multiplied */
#endif

    if (g == 256)                           /* 0 dB: nothing is touched, the feed as it was */
        return x;
    return v > lim ? 0x7fffffff : v < -lim ? (s32)0x80000000 : v * g;
}
#endif

/* One block into a ring block, as below, from two channels of the frame. In the room after the analog mute. */
__attribute__((section(".cave.a"), noinline))
static void feed_block(volatile s16 *d, const s32 *f, u32 right GAIN_ARG)
{
    u32 rnd = MB_MAIN->rnd;
    u32 n;

    for (n = 0; n < 2 * BLOCK; n++) {
#ifdef AUTO
        s32 x = gained(f, right, n & 1, (s32)g);
#else
        s32 x = n & 1 ? f[right] : f[0];
#endif
        u32 a = rnd * 1664525u + 1013904223u;
        s32 y;

#if defined(GAIN) && !defined(AUTO)
        x = gained(x, (s32)g);
#endif

        rnd = a * 1664525u + 1013904223u;
        y = (x >> 16) + ((s32)((x & 0xffff) + 0x8000 + (a >> 16) - (rnd >> 16)) >> 16);
        if (y > 32767)
            y = 32767;
        if (y < -32768)
            y = -32768;
        *d++ = y;
        if (n & 1)
            f += FRAME_CH;
    }
    MB_MAIN->rnd = rnd;
}
#endif

#ifdef GAIN
#ifdef AUTO
__attribute__((section(".cave.a"), noinline))   /* the mode image: after the feed's conversion, for room in the feed's own run */
#else
CAVE_N
#endif
static u32 gain_of(u32 db)
{
    return gain_table[db > GAIN_TOP ? GAIN_TOP : db];
}
#ifdef AUTO
/* A take's gain, and above its number a bit that says the take is mono: MODE's lowest bit is not set. */
__attribute__((section(".cave.r"), noinline))
static u32 take_gain(u32 db, u32 m)
{
    return gain_of(db) | (m & MODE_STEREO ? 0 : 0x10000);
}
#endif
#endif

/* The meter's level for this block, and a drawing asked for when one is due. */
CAVE_N static void meter(void)
{
    void *page = METER_PAGE;
    u32 quiet = METER_QUIET, src = METER_SRC, right, n, top = 0, level;
    const s32 *f;

    if (!page || quiet >= METER_STOP)
        return;
    METER_QUIET = ++quiet;
    f = chan(src > SRC_TOP ? SRC_MAIN : src, &right);
#ifdef NOFX
    for (n = 0; n < BLOCK; n++, f = (const s32 *)((const u8 *)f + FEED_STRIDE)) {
#else
    for (n = 0; n < BLOCK; n++, f += FRAME_CH) {
#endif
        s32 x = f[0], y = f[right];

        x ^= x >> 31;               /* its size, one less for a negative one */
        y ^= y >> 31;
        if ((u32)x > top)
            top = (u32)x;
        if ((u32)y > top)
            top = (u32)y;
    }
    top >>= 16;
#ifdef GAIN
    top = top * gain_of(METER_GAIN) >> 8;   /* with the gain on: what a take would hold */
    if (top > 32767)
        top = 32767;
#endif
    level = METER_LEVEL;
    if (level)
        level -= (level >> METER_FALL) + 1;
    if (top > level)
        level = top;
    METER_LEVEL = level;
    if (quiet % METER_EVERY == 0)
        redraw(page);
}

#if defined(PRE)
/* The pre image: the prof image's feed, with its sources taken before the mixer (the top of this file). */
#define PROF_TIMER (*(volatile u32 *)0xfc07000cu)
#define SRC_PROF SRC_SENDS
extern volatile u32 prof_vars[];
extern volatile u32 prof_on;
void prof_block(volatile s16 *d);

#ifndef NOFX
/* The sources a take or the meter asks for, a bit a channel of the frame: 2 to 9 the digital tracks, 14 and 15 the
 * FX track's return. */
__attribute__((section(".cave.y"), noinline)) static u32 pre_need(u32 need, u32 src)
{
    if (src == SRC_FX)
        need |= 3u << SRC_FX;
    else if (src - SRC_T1 < N_TRACKS)
        need |= 1u << src;
    return need;
}

/* Those channels, out of their buffers into the frame of ours; then the FX track's mute. */
__attribute__((section(".cave.p"), noinline)) static void pre_take(u32 need, u32 muted)
{
    u32 c, n, was = PRE_WAS;

    for (c = SRC_T1; c <= SRC_FX + 1; c++) {
        if (need & 1u << c) {
            const s32 *f = c < SRC_T1 + N_TRACKS ? TRACK_BUF + BLOCK * (c - SRC_T1) : IN_BUF + BLOCK * (c - 8);
            s32 *d = PRE_FRAME + c;

            for (n = 0; n < BLOCK; n++, d += FRAME_CH)
                *d = *f++;
        }
    }
    if (muted | was) {                  /* down over a block, nothing while it lasts, up over a block */
        s32 *x = IN_BUF + 6 * BLOCK;

        for (n = 0; n < 2 * BLOCK; n++) {
            s32 k = n & (BLOCK - 1);

            x[n] = (x[n] >> 5) * (muted ? was ? 0 : BLOCK - 1 - k : k + 1);
        }
    }
    PRE_WAS = muted;
}
#endif

__attribute__((section(".cave.y"), noinline)) void *mix_rec(void *a, void *b, u8 *params)
{
    void *result;
    u8 *p = params;
    u32 i, right, fed = 0, rec = 0, need = 0;

    prof_vars[5] = PROF_TIMER;
    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, p += PARAMS_STRIDE) {
        if (p[PARAM_TYPE] == MACHINE_TYPE && p[PARAM_KNOBS + 2 * K_REC] == REC_LOCK_ON) {
            rec |= 1u << i;
#ifndef NOFX
            need = pre_need(need, p[PARAM_KNOBS + 2 * K_REC + 1] & 15u);
#endif
        }
    }
    if (METER_PAGE && METER_QUIET < METER_STOP)
#ifdef NOFX
        (void)need;
#else
        need = pre_need(need, METER_SRC);
    pre_take(need, ((MUTES[0] | *PATTERN_MUTES) >> FX_TRACK) & 1u);
#endif
    result = mix_amute(a, b, params);
    prof_vars[6] = PROF_TIMER;
    for (i = 0; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
        if (rec & 1u << i) {
            u32 src = params[PARAM_KNOBS + 2 * K_REC + 1] & 15u;

            if (src == SRC_PROF && prof_on) {
                prof_block(MB_MAIN->ring[i]);
            } else {
                const s32 *f = chan(src, &right);

                feed_block(MB_MAIN->ring[i], f, right, take_gain(REC_GAINS[i], MODE_STEREO));
            }
            fed |= 1u << i;
        }
    }
    if (fed)
#ifdef HANDREC
        MB_FED(0x10000000u) = (u32)(u16)(MB_MAIN->seq + 1) << 16 | fed | (*(volatile u32 *)HAND_HOLD & 0xffu) << 8;   /* the handrec image: takes held past their release (engine/once.S) */
#else
        MB_FED(0x10000000u) = (u32)(u16)(MB_MAIN->seq + 1) << 16 | fed;
#endif
    meter();
    prof_vars[7] = PROF_TIMER;
    return result;
}
#elif defined(PROF)
/* The prof image, a tool: the srr image's feed, with the count read at three places (engine/prof.S, the record) and the
 * last source, SENDS, the record itself in place of sound: the same 32 words to both sides, no gain and no dither. */
#define PROF_TIMER (*(volatile u32 *)0xfc07000cu)
#define SRC_PROF SRC_SENDS
extern volatile u32 prof_vars[];
extern volatile u32 prof_on;        /* not 0: the last source is the record. 0: it is the sends, as on every image before */
void prof_block(volatile s16 *d);

__attribute__((section(".cave.y"), noinline)) void *mix_rec(void *a, void *b, u8 *params)
{
    void *result;
    u32 i, right, fed = 0;

    prof_vars[5] = PROF_TIMER;
    result = mix_amute(a, b, params);
    prof_vars[6] = PROF_TIMER;
    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
        if (params[PARAM_TYPE] == MACHINE_TYPE && params[PARAM_KNOBS + 2 * K_REC] == REC_LOCK_ON) {
            u32 src = params[PARAM_KNOBS + 2 * K_REC + 1] & 15u;

            if (src == SRC_PROF && prof_on) {
                prof_block(MB_MAIN->ring[i]);
            } else {
                const s32 *f = chan(src, &right);

                feed_block(MB_MAIN->ring[i], f, right, take_gain(REC_GAINS[i], MODE_STEREO));
            }
            fed |= 1u << i;
        }
    }
    if (fed)
        MB_FED(0x10000000u) = (u32)(u16)(MB_MAIN->seq + 1) << 16 | fed;
    meter();
    prof_vars[7] = PROF_TIMER;
    return result;
}
#elif defined(SRR)
/* The srr image: the multi image's feed, but a track's REC and SRC are not MODE's bits. engine/recword.S has left, in
 * slot 24 of the block that is sent, the mark of what the track is to do and the track's source under it
 * (engine/sampler.h, SRR). A take at a stereo place is stereo. */
CAVE_N void *mix_rec(void *a, void *b, u8 *params)
{
    void *result = mix_amute(a, b, params);
    u32 i, right, fed = 0;

    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
        if (params[PARAM_TYPE] == MACHINE_TYPE && params[PARAM_KNOBS + 2 * K_REC] == REC_LOCK_ON) {
            const s32 *f = chan(params[PARAM_KNOBS + 2 * K_REC + 1] & 15u, &right);

            feed_block(MB_MAIN->ring[i], f, right, take_gain(REC_GAINS[i], MODE_STEREO));
            fed |= 1u << i;
        }
    }
    if (fed)
        MB_FED(0x10000000u) = (u32)(u16)(MB_MAIN->seq + 1) << 16 | fed;
    meter();
    return result;
}
#elif defined(MULTI)
/* The multi image: every track that says record is fed, its own source's block into its own block of the window
 * (engine/sampler.h, MULTI). The count and the bits of the blocks written with it are one long, written last. */
CAVE_N void *mix_rec(void *a, void *b, u8 *params)
{
    void *result = mix_amute(a, b, params);
    u32 i, right, fed = 0;

    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
        u32 m = params[PARAM_KNOBS + 2 * K_MODE];

        if (params[PARAM_TYPE] == MACHINE_TYPE && REC_ON(m, params[PARAM_KNOBS + 2 * K_REC])) {
            const s32 *f = chan(SRC_OF(m), &right);

            feed_block(MB_MAIN->ring[i], f, right, take_gain(REC_GAINS[i], m));
            fed |= 1u << i;
        }
    }
    if (fed)
        MB_FED(0x10000000u) = (u32)(u16)(MB_MAIN->seq + 1) << 16 | fed;
    meter();
    return result;
}
#else
CAVE_N void *mix_rec(void *a, void *b, u8 *params)
{
    void *result = mix_amute(a, b, params);
    u32 i, right;
    const s32 *f;

    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
        u32 m = params[PARAM_KNOBS + 2 * K_MODE];

        if (params[PARAM_TYPE] == MACHINE_TYPE && REC_ON(m, params[PARAM_KNOBS + 2 * K_REC])) {
            u32 seq = (MB_MAIN->seq + 1) & 0xffff;

            f = chan(SRC_OF(m), &right);
#ifdef AUTO
            feed_block(MB_MAIN->ring[seq % MB_BLOCKS], f, right, take_gain(REC_GAINS[i], m));
#elif defined(GAIN)
            feed_block(MB_MAIN->ring[seq % MB_BLOCKS], f, right, gain_of(REC_GAINS[i]));
#else
            feed_block(MB_MAIN->ring[seq % MB_BLOCKS], f, right);
#endif
            MB_MAIN->seq = seq;
            break;
        }
    }
    meter();
    return result;
}
#endif
#else

/* One block: 32 frames of one stereo pair of the frame buffer into a ring block,
 * left, right, left, ... Each sample goes from 32 bits to 16: add half a step
 * and the difference of two random 16-bit numbers, keep the top half, stop at
 * the ends of the range. Lives in the room left after the analog mute. */
__attribute__((section(".cave.a"), noinline))
static void feed_block(volatile s16 *d, const s32 *f)
{
    u32 rnd = MB_MAIN->rnd;
    u32 n;

    for (n = 0; n < 2 * BLOCK; n++) {
        s32 x = f[n & 1];
        u32 a = rnd * 1664525u + 1013904223u;
        s32 y;

        rnd = a * 1664525u + 1013904223u;
        y = (x >> 16) + ((s32)((x & 0xffff) + 0x8000 + (a >> 16) - (rnd >> 16)) >> 16);
        if (y > 32767)
            y = 32767;
        if (y < -32768)
            y = -32768;
        *d++ = y;
        if (n & 1)
            f += FRAME_CH;
    }
    MB_MAIN->rnd = rnd;
}

__attribute__((section(".cave.r")))
void *mix_rec(void *a, void *b, u8 *params)
{
    void *result = mix_amute(a, b, params);
    u32 i;

#ifdef BANKS
    for (i = AUDIO_UP && !BANK_BUSY ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
#else
    for (i = AUDIO_UP ? 0 : N_TRACKS; i < N_TRACKS; i++, params += PARAMS_STRIDE) {
#endif
        u32 m = params[PARAM_KNOBS + 2 * K_MODE];

        if (params[PARAM_TYPE] == MACHINE_TYPE && REC_ON(m, params[PARAM_KNOBS + 2 * K_REC])) {
            u32 seq = (MB_MAIN->seq + 1) & 0xffff;

            feed_block(MB_MAIN->ring[seq % MB_BLOCKS], FRAME + (REC_EXT(m) ? F_EXT : F_MAIN));
            MB_MAIN->seq = seq;
            break;
        }
    }
    return result;
}
#endif
