/* Main CPU (section 3, OS 1.42 only), the feed image: one block of a take into the ring, in the place of
 * engine/recfeed.c's feed_block and its routine for a sample with the gain on (gained). The same words into the
 * window, the same random numbers and the same number left for the next block, to the bit: what a take holds does
 * not change. Why: that feed runs inside the per-block interrupt, above every task, and was a call a sample and,
 * with a gain, a hardware divide a sample. Here there is no call, the limit of a gain is worked out once a block,
 * and what a take is (stereo or mono, with a gain or without) is chosen before the loop: four loops.
 *
 *     void feed_block(volatile s16 *d, const s32 *f, u32 right, u32 g)
 *
 * d: the ring's block, 64 words, left, right, left, ... f: the source's left channel in the frame's first frame,
 * its right one `right` longs on (0: a track, one channel). g: the gain in 256ths (256: 0 dB), and a bit above the
 * low word for a mono take, both sides then half of the one channel and half of the other (take_gain).
 *
 * A sample x goes from 32 bits to 16 as it did: with a the random number after the one kept and r the one after a,
 * the top half of x + 0x8000 + (a >> 16) - (r >> 16), held to 16 bits. recfeed.c adds the two halves apart and
 * holds the sum to 16 bits after; here the sum is made in 32 bits and held to 32 bits (sats), and its top half is
 * taken. That is the same number: taking the top half never turns two numbers around, so holding before or after
 * it is one thing, and the ends of 32 bits have the ends of 16 as their top halves. The stock mixer holds its own
 * sums this way (addl, satsl).
 *
 * With a gain, x is its top 24 bits times g when that fits, and else the end of 32 bits on its side: the limit is
 * 0x7fffffff / g, as recfeed.c has it, once.
 *
 * The window stores 16-bit words: it is written a word a sample, in order, and the random number is one long read
 * and one long written, as before. Nothing else is read or written there.
 */
#define RND     0x10000804              /* MB_MAIN->rnd (engine/sampler.h) */
#define STEP    80                      /* a frame: 20 longs */

/* x in d3 to the next word of the block. d0: the random number. d6, a6: what it is multiplied by and what is
 * added. a4: half a step. Uses d1, d2. */
.macro  to_word
        mulu.l  %d6,%d0
        add.l   %a6,%d0                 | a
        move.l  %d0,%d1
        mulu.l  %d6,%d0
        add.l   %a6,%d0                 | r, and the number kept
        clr.w   %d1
        swap    %d1                     | a >> 16
        move.l  %d0,%d2
        clr.w   %d2
        swap    %d2                     | r >> 16
        sub.l   %d2,%d1
        add.l   %a4,%d1
        add.l   %d1,%d3
        sats    %d3                     | held to 32 bits
        swap    %d3
        move.w  %d3,(%a0)+              | its top half
.endm

/* x in d3 with the gain on. d5: the 256ths. a3: the limit, a5: the limit below nought. */
.macro  gain_on over, under, back
        asr.l   #8,%d3                  | its top 24 bits
        cmp.l   %a3,%d3
        jgt     \over
        cmp.l   %a5,%d3
        jlt     \under
        muls.l  %d5,%d3
\back:
.endm

.macro  gain_ends over, under, back
\over:  move.l  #0x7fffffff,%d3
        jra     \back
\under: move.l  #0x80000000,%d3
        jra     \back
.endm

/* The source's two channels of a frame, each halved, added: into d3 */
.macro  halves
        move.l  (%a1),%d4
        asr.l   #1,%d4
        move.l  (%a1,%a2.l*4),%d3
        asr.l   #1,%d3
        add.l   %d4,%d3
.endm

/* A frame done: the next one, and again until the block is full. d7: the block's end. */
.macro  next_frame again
#ifdef NOFX
        adda.l  0x80007d24,%a1          | the nofx image: the source's step, 80 or 4 (engine/recfeed.c, FEED_STRIDE)
#else
        lea     STEP(%a1),%a1
#endif
        cmp.l   %a0,%d7
        jne     \again
.endm

        .section .cave.f,"ax"
        .globl  feed_block

feed_block:
        lea     -44(%sp),%sp
        movem.l %d2-%d7/%a2-%a6,(%sp)
        movem.l 48(%sp),%a0-%a3         | d, f, right, g
        move.l  %a3,%d4
        move.l  #1664525,%d6
        move.l  #1013904223,%a6
        move.l  #0x8000,%a4
        lea     128(%a0),%a5
        move.l  %a5,%d7
        move.l  RND,%d0
        mvz.w   %d4,%d5                 | the 256ths; d4 is not the same with the bit that says mono
        cmp.l   #256,%d5
        jeq     flat                    | 0 dB: nothing is touched
        move.l  #0x7fffffff,%d1
        divs.l  %d5,%d1                 | the most the 24 bits can be and still fit when multiplied
        move.l  %d1,%a3
        neg.l   %d1
        move.l  %d1,%a5
        cmp.l   %d5,%d4
        jne     mono_gain

1:      move.l  (%a1),%d3               | stereo, with a gain
        gain_on over1, under1, back1
        to_word
        move.l  (%a1,%a2.l*4),%d3
        gain_on over2, under2, back2
        to_word
        next_frame 1b
        jra     done
        gain_ends over1, under1, back1
        gain_ends over2, under2, back2

mono_gain:
        halves
        gain_on over3, under3, back3
        move.l  %d3,%d4
        to_word
        move.l  %d4,%d3
        to_word
        next_frame mono_gain
        jra     done
        gain_ends over3, under3, back3

flat:   cmp.l   %d5,%d4
        jne     mono

2:      move.l  (%a1),%d3               | stereo
        to_word
        move.l  (%a1,%a2.l*4),%d3
        to_word
        next_frame 2b
        jra     done

mono:   halves
        move.l  %d3,%d4
        to_word
        move.l  %d4,%d3
        to_word
        next_frame mono

done:   move.l  %d0,RND
        movem.l (%sp),%d2-%d7/%a2-%a6
        lea     44(%sp),%sp
        rts
