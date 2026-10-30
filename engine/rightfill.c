/* Main CPU (section 3, OS 1.42 only): the right side of the eight digital tracks.
 * One-track stereo, the stereo image: engine/sampler.h (ONETRACK), docs/STEREO.md.
 *
 * Stock's mixer makes every sum twice, a left pass and a right pass, each handed
 * the eight track buffers the audio CPU sent (0x80003d50) and that side's gains.
 * In this image the four right-hand passes are handed RSET instead (seven
 * operands, tools/build_main.py). This routine fills it, once a block: for a
 * track the audio CPU has left a right channel for, that channel out of the
 * window; for every other track a copy of its one buffer, so that what the mixer
 * makes of it is what stock makes.
 *
 * It stands where stock waits for the track buffers to arrive, before it sends
 * the next block's knobs: the first place the left buffers are whole, and as
 * early as the right ones can be read. The audio CPU writes its right channels
 * just before it sends the left ones, so the two are a block of the same sound
 * for as long as stock's own exchange holds.
 *
 * The window is read a long at a time. The long that says which tracks have a
 * right channel is not believed unless its two low bytes agree: where it lies
 * has never been tried as shared memory, and if it does not answer every track
 * stays as it was, its left on both sides.
 *
 * While the audio CPU is down (the unit's start, and its restart after samples
 * are sent to the unit) the window is not read, and that long is set to 0. The
 * audio CPU clears what stock uses of the window when it starts and nothing
 * of ours, so without this the first block after a restart would be read with
 * the long of the last block before it, and whatever the halves hold by then.
 * The boot's own exchange uses the window's first words and its second half
 * of 2 KB: not this long. */
#include "sampler.h"

#define DMA_WAIT ((void (*)(void))0x400a20ae)   /* stock: until the transfer it started is over */
#define AUDIO_UP (*(volatile u32 *)0x43bdd824)  /* the audio CPU is running: stock tests it here too */
#define TRACKS ((const s32 *)0x80003d50)

/* Four longs a turn: this runs every block for all eight tracks. Each long of the window is read once. */
#ifdef PROBE_READONLY
/* A tool for one test, not kept (2026-10-17, the capture's lag, after the allright image lagged): every long read
 * twice, nothing written, so the time is at least the copies' and only the stores are gone. */
__attribute__((section(".cave.o"), noinline))
static s32 *take(s32 *to, const volatile u32 *from, u32 fours)
{
    u32 sum = 0, n, k;
    const volatile u32 *f;

    for (k = 0; k < 2; k++) {
        f = from;
        n = fours;
        do {
            sum += f[0];
            sum += f[1];
            sum += f[2];
            sum += f[3];
            f += 4;
        } while (--n);
    }
    __asm__ volatile("" : : "d"(sum));
    return to + 4 * fours;
}
#else
__attribute__((section(".cave.o"), noinline))
static s32 *take(s32 *to, const volatile u32 *from, u32 fours)
{
    do {
        *to++ = *from++;
        *to++ = *from++;
        *to++ = *from++;
        *to++ = *from++;
    } while (--fours);
    return to;
}
#endif

__attribute__((section(".cave.o")))
u32 right_fill(void)
{
    const u32 *left = (const u32 *)TRACKS;
#ifdef PROBE_ONCHIP
    s32 *to = (s32 *)0x80007800;        /* a tool for one test, not kept: the copies into on-chip memory nothing names */
#else
    s32 *to = RSET;
#endif
    u32 up, word, mask = 0, t;

    DMA_WAIT();
    up = AUDIO_UP;
#ifdef PROBE_NOCOPY
    /* A tool for one test, not kept (2026-10-17, the capture's lag): the window's long read, nothing copied. */
    if (up) {
        word = *RW_HEAD_MAIN;
        (void)word;
    }
    (void)left;
    (void)to;
    (void)mask;
    (void)t;
    return up;
#endif
#ifdef PROBE_NOWINDOW
    /* A tool for one test, not kept: the copies, the window not read (every track as having no right channel). */
    (void)word;
    if (up) {
    } else {
#else
    if (up) {
        word = *RW_HEAD_MAIN;
        if (word == RW_WORD(word))
            mask = word & 0xff;
    } else {
#endif
        *RW_HEAD_MAIN = 0;              /* a restart of the audio CPU is not to find the word of its last block here */
#ifdef STOPS
        *STOPS_MARK(0x10000000u) = 0;   /* the stops image: nor is what it said the slots hold believed until it has said it again */
#endif
    }
    for (t = 0; t < N_TRACKS; t++, left += BLOCK) {
        if (mask >> t & 1) {
            to = take(to, RW_HALF(0x10000000u, 2 * t), BLOCK / 8);
            to = take(to, RW_HALF(0x10000000u, 2 * t + 1), BLOCK / 8);
        } else {
            to = take(to, left, BLOCK / 4);
        }
    }
    return up;                          /* the test stock made here is made of this */
}
