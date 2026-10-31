| Replaces the audio interrupt's call to the voice loop (jsr at 0x40000a34). Runs the real voice loop, then
| sampler_post. The interrupt keeps the trig mask in d2 and the release mask in d4 for the later stages, so both are
| handed to sampler_post by reference and written back.
    .section .cave.y,"ax"
    .globl  sampler_hook
sampler_hook:
#ifdef HQ
    move.l  0x80000700,%d0          | the pitch image: has our table been made since the voices were last reset (HQ_MADE)
    cmpi.l  #HQ_MAGIC,%d0
    beq.s   1f
    jsr     hq_init
1:
#endif
#ifdef MULTI
    jsr     rec_all                 | the multi image: the takes have their blocks first, before the main CPU writes the next
#endif
    move.l  16(%sp),-(%sp)          | release mask trig mask params out
    move.l  16(%sp),-(%sp)
    move.l  16(%sp),-(%sp)
    move.l  16(%sp),-(%sp)
    jsr     0x40004324
    lea     16(%sp),%sp
    move.l  %d4,-(%sp)
    move.l  %d2,-(%sp)              | masks[0] = trig, masks[1] = release
    pea     (%sp)
    move.l  20(%sp),-(%sp)          | params out
    move.l  20(%sp),-(%sp)
    jsr     sampler_post
    lea     12(%sp),%sp
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%d4
#ifdef STOPS
    bra.w   stops_say               | the stops image: then sixteen slots more are said to the main CPU
#else
    rts
#endif
#if defined(HQ) && !defined(QUICK)
| s32 hq_mid(const s16 *x, u32 f): the frame f/4096 past x[7], from x[0] to x[15] and two rows of the table, the row
| for the top 5 bits of f and the next, blended by the low 7. engine/sampler.h.
    .section .cave.y,"ax"
    .globl  hq_mid
hq_mid:
    move.l  4(%sp),%a0
    move.l  8(%sp),%d1
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    move.l  %d1,%d4
    lsr.l   #7,%d1
    lsl.l   #5,%d1                  | 32 bytes a row
    add.l   #0x44060004,%d1
    move.l  %d1,%a1
    lea     32(%a1),%a2
    clr.l   %d0
    clr.l   %d1
    .rept   16
    move.w  (%a0)+,%d2
    move.w  %d2,%d3
    muls.w  (%a1)+,%d2
    add.l   %d2,%d0
    muls.w  (%a2)+,%d3
    add.l   %d3,%d1
    .endr
    sub.l   %d0,%d1
    asr.l   #7,%d1
    and.l   #127,%d4
    muls.l  %d4,%d1
    add.l   %d1,%d0
    cmp.l   #0x3fffffff,%d0         | held to 30 bits, then doubled
    ble.s   1f
    move.l  #0x3fffffff,%d0
1:  cmp.l   #-0x40000000,%d0
    bge.s   2f
    move.l  #-0x40000000,%d0
2:  add.l   %d0,%d0
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    rts
#endif
#ifdef QUICK
| int hq_run(struct st *s, s32 *l, s32 *r, int n, int end, s32 lo, u32 span): frames n to end - 1 of a block, for as
| long as the position is at or past lo and less than span past it.
|
| The sums are stock's kind: signed fractions, 32 bits by 32 into 48, which takes the top 40 bits of the product
| doubled. A frame at the top of a long times a table number shifted up 15 is the two multiplied, times 2^8, with
| nothing under the 40 bits: read back, an accumulator is the sum itself, as the integer sum was. The mode is set and
| put back as stock's own routines do, and every accumulator is left at 0. Every form of instruction here is one
| stock's own code runs.
    .equ    S_L, 0
    .equ    S_R, 4
    .equ    S_POS, 8
    .equ    S_FRAMES, 12
    .equ    S_INC, 24
    .equ    S_DIR, 28
    .equ    S_PAD, 72
    .equ    F_STEP, 0               | what the position moves by a frame frames - 15, or 0: frame i has all sixteen in
    .equ    F_WHOLE, 4              | the slot when i - 7 is under this
    .equ    F_MACSR, 8
    .equ    A_S, 60                 | past eleven registers and the return address
    .equ    A_L, 64
    .equ    A_R, 68
    .equ    A_N, 72
    .equ    A_END, 76
    .equ    A_LO, 80
    .equ    A_SPAN, 84
    .equ    HQ_LONGS, 0x44061000
#ifdef TWELVE
    .equ    HQ_SKIP, 2              | the sum of twelve: the outer two frames at each end are left out (their numbers are 0)
#else
    .equ    HQ_SKIP, 0
#endif
#ifdef SIX
    .equ    HQ_SKIP1, 4             | the six image: one channel sums eight places, the six and a nought at each end
    .equ    HQ_SKIP2, 5             | two channels sum the six
#elif defined(EIGHT)
    .equ    HQ_SKIP1, 4             | the eight image: frames i - 3 to i + 4, both ways
    .equ    HQ_SKIP2, 4
#else
    .equ    HQ_SKIP1, HQ_SKIP
    .equ    HQ_SKIP2, HQ_SKIP
#endif

#ifdef SLIM
| void hq_safe, the slim image's (engine/sampler.h, SLIM), from hq_run with its frame in a0 and the position in d5:
| how many frames on from this one are inside lo and span and have all sixteen in the slot, kept where n was. Those
| are made with neither test. Fewer is no harm: the rest are tested. d1 to d3 and d6 are hq_run's to lose here.
    .section .cave.e,"ax"
    .globl  hq_safe
    .globl  hq_rearm
| From hq_mid2, two channels, a frame tested and found inside the slot while there was no stretch (a run begun within
| reach of the slot's start, or one whose stretch ran out with frames still inside): the stretch again, from the frame
| after it. d0 and d4 are kept; d1 to d3 and d6 are hq_safe's to lose.
hq_rearm:
    lea     4(%sp),%a0              | hq_run's frame, past the return
    add.l   F_STEP(%a0),%d5
    bsr.s   hq_safe
    sub.l   F_STEP(%a0),%d5
    rts
hq_safe:
    moveq   #0,%d6                  | none, unless it is worked out
    moveq   #2,%d2
    cmp.l   %d2,%d7
    ble.s   8f                      | not for a run of a frame or two: a seam's, a wall's
    move.l  F_STEP(%a0),%d1
    beq.s   8f
    move.l  %d5,%d2
    sub.l   A_LO(%a0),%d2           | how far past lo
    cmp.l   A_SPAN(%a0),%d2
    bcc.s   8f
    moveq   #-1,%d3                 | a step that lands on the sample's own frames only: nothing is summed, no bound
    move.l  %d1,%d6                 | from the slot
    andi.l  #0xfff,%d6
    beq.s   2f
    move.l  %d5,%d3
    asr.l   #8,%d3
    asr.l   #4,%d3
    subq.l  #7,%d3
    moveq   #0,%d6
    cmp.l   F_WHOLE(%a0),%d3
    bcc.s   8f
2:  tst.l   %d1
    bmi.s   5f
    move.l  A_SPAN(%a0),%d6         | going up: (span - past - 1) / step frames after this one inside lo and span,
    sub.l   %d2,%d6
    subq.l  #1,%d6
    divu.l  %d1,%d6
    addq.l  #1,%d3
    beq.s   7f
    move.l  F_WHOLE(%a0),%d3        | and ((whole + 7) << 12 - pos - 1) / step with all sixteen
    addq.l  #7,%d3
    moveq   #12,%d2
    lsl.l   %d2,%d3
    sub.l   %d5,%d3
    subq.l  #1,%d3
    divu.l  %d1,%d3
    bra.s   6f
5:  neg.l   %d1                     | going down: past / -step, and (pos - (7 << 12)) / -step
    move.l  %d2,%d6
    divu.l  %d1,%d6
    addq.l  #1,%d3
    beq.s   7f
    move.l  %d5,%d3
    sub.l   #7 << 12,%d3
    divu.l  %d1,%d3
6:  cmp.l   %d3,%d6
    bls.s   7f
    move.l  %d3,%d6
7:  addq.l  #1,%d6                  | and this one
8:  move.l  %d6,A_N(%a0)
    rts
#endif

| The two rows' sums in d0 and d1: the second blended in by t, held to 30 bits and doubled.
.macro  HQ_SUM out, t
    sub.l   %d0,%d1
    asr.l   #7,%d1
    muls.l  \t,%d1
    add.l   %d1,%d0
    add.l   %d0,%d0
    bvc.s   9f
    jsr     hq_hold
9:  move.l  %d0,(\out)+
.endm

| One channel. d5 the position, d7 frames to go, a3 where they go, a6 the note. Four frames a turn of the sum.
    .section .cave.y,"ax"
    .globl  hq_one
hq_one:
    move.l  %d5,%d0
    sub.l   A_LO(%sp),%d0
    cmp.l   A_SPAN(%sp),%d0
    bcc.s   hq_done1
    move.l  %d5,%d0
    asr.l   #8,%d0
    asr.l   #4,%d0                  | the frame
    move.l  %d5,%d6
    and.l   #0xfff,%d6              | and how far past it
    bne.s   hq_mid1
    movea.l S_L(%a6),%a0            | a frame of the sample itself
    mvz.w   (%a0,%d0.l*2),%d1
    swap    %d1
    move.l  %d1,(%a3)+
hq_next1:
    add.l   F_STEP(%sp),%d5
    subq.l  #1,%d7
    bne.s   hq_one
hq_done1:
    jmp     hq_out
hq_mid1:
    move.l  %d0,%d1
    subq.l  #7,%d1
    movea.l S_L(%a6),%a0
    cmp.l   F_WHOLE(%sp),%d1
    bcs.s   1f
    movea.l S_PAD(%a6),%a0          | before frame 7 or within 8 of the last: from what the note's start wrote out
    moveq   #7,%d1
    cmp.l   %d1,%d0
    blt.s   2f
    sub.l   S_FRAMES(%a6),%d0
    moveq   #30,%d1                 | HQ_PAD_END + HQ_REACH
    add.l   %d1,%d0
2:  addq.l  #7,%d0
1:  lea     2*HQ_SKIP1-14(%a0,%d0.l*2),%a0
    move.l  %d6,%d1
    lsr.l   #7,%d1
    lsl.l   #6,%d1                  | 64 bytes a row
    add.l   #HQ_LONGS+4*HQ_SKIP1,%d1
    movea.l %d1,%a1
    lea     64(%a1),%a2
    and.l   #127,%d6                | what the next row is blended in by
    move.l  (%a1)+,%d3
    move.l  (%a2)+,%d4
    moveq   #4-HQ_SKIP1/2,%d0
3:
    .rept   4
    mvz.w   (%a0)+,%d2
    swap    %d2
    mac.l   %d2,%d3,(%a1)+,%d3,%acc0
    mac.l   %d2,%d4,(%a2)+,%d4,%acc1
    .endr
    subq.l  #1,%d0
    bne.s   3b
    movclr.l %acc0,%d0
    movclr.l %acc1,%d1
    HQ_SUM  %a3, %d6
    bra.w   hq_next1

| Two channels, sharing the numbers. A frame of the sample is taken as a long, the one after it in the low half, which
| is cleared: the next of each side is fetched by a multiply of this one, into the other of two registers. d0/d1 the
| left's and d2/d3 the right's, a2 and d6 the two rows' numbers, d4 how far past the frame.
.macro  HQ_TAP k, l, r, nl, nr
    mac.l   \l,%a2,2*\k+2(%a0),\nl,%acc0
    mac.l   \r,%a2,4*\k+4(%a1),%a2,%acc2
    mac.l   \l,%d6,2*\k+2(%a4),\nr,%acc1
    mac.l   \r,%d6,4*\k+68(%a1),%d6,%acc3
#ifndef TRIM
    clr.w   \nl
    clr.w   \nr
#endif
.endm

    .section .cave.k,"ax"
    .globl  hq_run
hq_run:
    lea     -56(%sp),%sp
    movem.l %d2-%d7/%a2-%a6,12(%sp)
    move.l  %macsr,%d0
    move.l  %d0,F_MACSR(%sp)
    move.l  #0xa0,%macsr            | signed fractions, as the voice loop has it
    movea.l A_S(%sp),%a6
    move.l  S_INC(%a6),%d0
    tst.b   S_DIR(%a6)
    bgt.s   1f
    neg.l   %d0
1:  move.l  %d0,F_STEP(%sp)
    moveq   #15,%d1
    move.l  S_FRAMES(%a6),%d0
    sub.l   %d1,%d0
    bgt.s   1f
    moveq   #0,%d0
1:  move.l  %d0,F_WHOLE(%sp)
    move.l  S_POS(%a6),%d5
    move.l  A_N(%sp),%d0
    move.l  A_END(%sp),%d7
    sub.l   %d0,%d7                 | frames to make
    lsl.l   #2,%d0
    movea.l A_L(%sp),%a3
    adda.l  %d0,%a3
    moveq   #0,%d1
    move.l  %d1,%acc0
    move.l  %d1,%acc1
    move.l  A_R(%sp),%d1
    bne.s   1f
    jmp     hq_one
1:  movea.l %d1,%a5
    adda.l  %d0,%a5
#ifdef SLIM
    movea.l %sp,%a0                 | the slim image: the frames of the stretch (hq_safe), kept where n was; two channels only
    jsr     hq_safe
#endif
    moveq   #0,%d1
    move.l  %d1,%acc2
    move.l  %d1,%acc3
hq_two:
#ifdef SLIM
    subq.l  #1,A_N(%sp)             | the slim image: a frame of the stretch, neither test
    bmi.s   hq_test2
    move.l  %d5,%d0
    asr.l   #8,%d0
    asr.l   #4,%d0
    move.l  %d5,%d4
    and.l   #0xfff,%d4
    bne.w   hq_slot2
    bra.s   hq_own2
hq_test2:
#endif
    move.l  %d5,%d0
    sub.l   A_LO(%sp),%d0
    cmp.l   A_SPAN(%sp),%d0
    bcc.w   hq_out
    move.l  %d5,%d0
    asr.l   #8,%d0
    asr.l   #4,%d0                  | the frame
    move.l  %d5,%d4
    and.l   #0xfff,%d4              | and how far past it
    bne.s   hq_mid2
#ifdef SLIM
hq_own2:
#endif
    movea.l S_L(%a6),%a0            | a frame of the sample itself
    mvz.w   (%a0,%d0.l*2),%d1
    swap    %d1
    move.l  %d1,(%a3)+
    movea.l S_R(%a6),%a0
    mvz.w   (%a0,%d0.l*2),%d1
    swap    %d1
    move.l  %d1,(%a5)+
hq_next2:
    add.l   F_STEP(%sp),%d5
    subq.l  #1,%d7
    bne.s   hq_two
hq_out:
    move.l  %d5,S_POS(%a6)
    move.l  A_END(%sp),%d0
    sub.l   %d7,%d0
    move.l  F_MACSR(%sp),%d1
    move.l  %d1,%macsr
    movem.l 12(%sp),%d2-%d7/%a2-%a6
    lea     56(%sp),%sp
    rts
hq_hold:                            | twice the sum did not fit: it came out below nothing when it was above
    tst.l   %d0
    bmi.s   1f
    move.l  #0x80000000,%d0
    rts
1:  move.l  #0x7ffffffe,%d0
    rts
hq_mid2:
    move.l  %d0,%d1
    subq.l  #7,%d1
    cmp.l   F_WHOLE(%sp),%d1
    bcc.w   hq_ends2
#ifdef SLIM
    jsr     hq_rearm                | the slim image: a frame inside the slot with no stretch, the stretch again
hq_slot2:
#endif
    movea.l S_L(%a6),%a0
    lea     -14(%a0,%d0.l*2),%a0
    movea.l S_R(%a6),%a4
    lea     -14(%a4,%d0.l*2),%a4
hq_table2:
    move.l  %d4,%d1
    lsr.l   #7,%d1
    lsl.l   #6,%d1                  | 64 bytes a row, the next row after it
    add.l   #HQ_LONGS,%d1
    movea.l %d1,%a1
    and.l   #127,%d4                | what the next row is blended in by
#ifdef TRIM
    move.l  2*HQ_SKIP2(%a0),%d0     | the trim image: the frame after it in the low half, as every tap has it
    move.l  2*HQ_SKIP2(%a4),%d2
#else
    mvz.w   2*HQ_SKIP(%a0),%d0
    swap    %d0
    mvz.w   2*HQ_SKIP(%a4),%d2
    swap    %d2
#endif
    movea.l 4*HQ_SKIP2(%a1),%a2
    move.l  4*HQ_SKIP2+64(%a1),%d6
#ifdef SIX
    HQ_TAP  5, %d0, %d2, %d1, %d3   | the six image: frames i - 2 to i + 3
    HQ_TAP  6, %d1, %d3, %d0, %d2
    HQ_TAP  7, %d0, %d2, %d1, %d3
    HQ_TAP  8, %d1, %d3, %d0, %d2
    HQ_TAP  9, %d0, %d2, %d1, %d3
#elif defined(EIGHT)
    HQ_TAP  4, %d0, %d2, %d1, %d3   | the eight image: frames i - 3 to i + 4
    HQ_TAP  5, %d1, %d3, %d0, %d2
    HQ_TAP  6, %d0, %d2, %d1, %d3
    HQ_TAP  7, %d1, %d3, %d0, %d2
    HQ_TAP  8, %d0, %d2, %d1, %d3
    HQ_TAP  9, %d1, %d3, %d0, %d2
    HQ_TAP  10, %d0, %d2, %d1, %d3
#else
#ifndef TWELVE
    HQ_TAP  0, %d0, %d2, %d1, %d3
    HQ_TAP  1, %d1, %d3, %d0, %d2
#endif
    HQ_TAP  2, %d0, %d2, %d1, %d3
    HQ_TAP  3, %d1, %d3, %d0, %d2
    HQ_TAP  4, %d0, %d2, %d1, %d3
    HQ_TAP  5, %d1, %d3, %d0, %d2
    HQ_TAP  6, %d0, %d2, %d1, %d3
    HQ_TAP  7, %d1, %d3, %d0, %d2
    HQ_TAP  8, %d0, %d2, %d1, %d3
    HQ_TAP  9, %d1, %d3, %d0, %d2
    HQ_TAP  10, %d0, %d2, %d1, %d3
    HQ_TAP  11, %d1, %d3, %d0, %d2
    HQ_TAP  12, %d0, %d2, %d1, %d3
#ifndef TWELVE
    HQ_TAP  13, %d1, %d3, %d0, %d2
    HQ_TAP  14, %d0, %d2, %d1, %d3
#endif
#endif
    mac.l   %d1,%a2,%acc0           | the last: nothing after it to fetch
    mac.l   %d3,%a2,%acc2
    mac.l   %d1,%d6,%acc1
    mac.l   %d3,%d6,%acc3
    movclr.l %acc0,%d0
    movclr.l %acc1,%d1
    HQ_SUM  %a3, %d4
    movclr.l %acc2,%d0
    movclr.l %acc3,%d1
    HQ_SUM  %a5, %d4
#ifdef SLIM
    add.l   F_STEP(%sp),%d5         | the slim image: on to the next frame here, not by a branch
    subq.l  #1,%d7
    bne.w   hq_two
    bra.w   hq_out
#else
    bra.w   hq_next2
#endif
hq_ends2:                           | before frame 7 or within 8 of the last: from what the note's start wrote out
    movea.l S_PAD(%a6),%a0
    moveq   #7,%d1
    cmp.l   %d1,%d0
    blt.s   1f
    sub.l   S_FRAMES(%a6),%d0
    moveq   #30,%d1                 | HQ_PAD_END + HQ_REACH
    add.l   %d1,%d0
1:  lea     (%a0,%d0.l*2),%a0
    lea     90(%a0),%a4             | HQ_PAD_SIDE words on: the right's
    bra.w   hq_table2
#endif
#ifdef ONETRACK
| const u8 seed_runs[]: a track's part of stock's memory of the two filters (engine/sampler.c, seed). Seven runs of
| longs: where the first track's begins, in longs from 0x80008550, and how many a track.
    .section .cave.b,"ax"
    .globl  seed_runs
seed_runs:
    .byte   4, 1                    | 0x80008560: the type 0x80008580: a sum 0x80008740: coefficients 0x80008840:
    .byte   12, 1                   | levels 0x800088a0: the first filter's sums 0x800088e0 0x80008920: the second
    .byte   124, 8                  | filter's sums
    .byte   188, 3
    .byte   212, 2
    .byte   228, 1
    .byte   244, 2
#endif
#ifdef LEAN
| void voice_out(s32 *voice, s32 *out, s32 *right): a note's channels from Twinshot's scratch buffers to the track's
| buffer (and the right's, when right is not 0), through the envelope's level and the voice's gain. What stock's two
| routines make of them, 0x400045a0 and then 0x400049f4 with its second layer at nothing, which the sampler called
| once a channel: a frame times the level, read back, times the gain, read back, the level and the gain each moved a
| step a frame. Here both channels are done in one pass over the block, and the two ramps once. Where Twinshot's
| second layer is not at nothing (another machine's leavings, before the sampler's first note), stock's own two
| routines are called as they were.
    .section .cave.m,"ax"
    .globl  voice_out
    .equ    V_GAIN, 8
    .equ    V_GAIN_2, 12
    .equ    V_CUR, 24
    .equ    V_CUR_2, 28
    .equ    V_TRIG, 52
    .equ    V_START, 56
    .equ    V_TARGET, 976
    .equ    V_LEVEL, 980
    .equ    V_ATTACK, 1000
    .equ    SCRATCH_L, 0x80008c60
    .equ    SCRATCH_R, 0x80008d84
voice_out:
    lea     -36(%sp),%sp
    movem.l %d2-%d7/%a2-%a4,(%sp)
    movea.l 40(%sp),%a0
    movea.l 44(%sp),%a2
    movea.l 48(%sp),%a3
    move.l  V_GAIN_2(%a0),%d0
    or.l    V_CUR_2(%a0),%d0
    bne.w   voice_slow
    tst.l   V_TRIG(%a0)             | as stock's first routine begins: a trig fades the old note out,
    beq.s   1f
    clr.l   V_TARGET(%a0)
    bra.s   2f
1:  tst.l   V_START(%a0)
    beq.s   2f
    move.l  #0x80000000,%d0         | and a note with no attack starts at its level
    cmp.l   V_ATTACK(%a0),%d0
    bne.s   2f
    move.l  V_TARGET(%a0),V_LEVEL(%a0)
2:  move.l  V_TARGET(%a0),%d3
    move.l  V_LEVEL(%a0),%d4
    move.l  %d3,V_LEVEL(%a0)        | where each is when the block is over
    sub.l   %d4,%d3
    sats.l  %d3
    asr.l   #5,%d3                  | the level's step
    move.l  V_GAIN(%a0),%d5
    move.l  V_CUR(%a0),%d6
    move.l  %d5,V_CUR(%a0)
    sub.l   %d6,%d5
    asr.l   #5,%d5                  | the gain's
    lea     SCRATCH_L,%a1
    move.l  (%a1)+,%d1
    moveq   #32,%d7
    move.l  %a3,%d0
    bne.s   voice_two
3:  msac.l  %d4,%d1,(%a1)+,%d1,%acc0
    movclr.l %acc0,%d2
    mac.l   %d6,%d2,%acc0
    movclr.l %acc0,%d2
    move.l  %d2,(%a2)+
    add.l   %d3,%d4
    sats.l  %d4
    add.l   %d5,%d6
    subq.l  #1,%d7
    bne.s   3b
voice_done:
    movem.l (%sp),%d2-%d7/%a2-%a4
    lea     36(%sp),%sp
    rts
voice_two:
    lea     SCRATCH_R,%a4
    move.l  (%a4)+,%d0
4:  msac.l  %d4,%d1,(%a1)+,%d1,%acc0
    movclr.l %acc0,%d2
    mac.l   %d6,%d2,%acc0
    movclr.l %acc0,%d2
    move.l  %d2,(%a2)+
    msac.l  %d4,%d0,(%a4)+,%d0,%acc0
    movclr.l %acc0,%d2
    mac.l   %d6,%d2,%acc0
    movclr.l %acc0,%d2
    move.l  %d2,(%a3)+
    add.l   %d3,%d4
    sats.l  %d4
    add.l   %d5,%d6
    subq.l  #1,%d7
    bne.s   4b
    bra.s   voice_done
voice_slow:                         | stock's two routines, a channel at a time, the right from where the left began
    move.l  V_LEVEL(%a0),%d2
    move.l  V_CUR(%a0),%d3
    movea.l %a0,%a4
    move.l  #SCRATCH_L,%d4
    move.l  %a2,%d5
5:  move.l  %a4,-(%sp)
    move.l  %d4,-(%sp)
    jsr     0x400045a0
    addq.l  #8,%sp
    move.l  %a4,-(%sp)
    pea     voice_layers(%pc)
    move.l  %d5,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d4,-(%sp)
    jsr     0x400049f4
    lea     20(%sp),%sp
    move.l  %a3,%d5
    beq.s   voice_done
    suba.l  %a3,%a3
    move.l  %d2,V_LEVEL(%a4)
    move.l  %d3,V_CUR(%a4)
    move.l  #SCRATCH_R,%d4
    bra.s   5b
voice_layers:
    .long   0, 1

    .section .cave.b,"ax"
#ifndef ALLRIGHT        /* the allright image: send_all, below, in its place */
| void send(u32 mask): the right channels of the tracks of the mask to the window, two halves of sixteen longs a track
| (engine/sampler.h, RW_HALF): nine halves from 0x5c0, then seven from 0xe40. Longs, as everything there.
    .globl  send
send:
    move.l  4(%sp),%d0
    lea     0x44050000,%a0          | the right channels, waiting
    lea     0x5c0,%a1
    moveq   #0,%d1                  | the half
1:  btst    #0,%d0
    beq.s   3f
    .rept   16
    move.l  (%a0)+,(%a1)+
    .endr
2:  addq.l  #1,%d1
    btst    #0,%d1
    bne.s   4f
    lsr.l   #1,%d0                  | two halves done: the next track
4:  cmpi.l  #9,%d1
    bne.s   5f
    lea     0xe40,%a1               | the second stretch
5:  cmpi.l  #16,%d1
    bne.s   1b
    rts
3:  lea     64(%a0),%a0             | not this track's: past it
    lea     64(%a1),%a1
    bra.s   2b
#endif

#ifdef ALLRIGHT
| void send_all(void): the allright image. Nine halves from 0x5c0, then seven from 0xe40, sixteen longs each.
    .globl  send_all
send_all:
    move.l  0x44050400,%d0          | the stereo tracks (R_MASK) their right channels, waiting
    lea     0x44050000,%a0
    move.l  %a2,-(%sp)
    move.l  %a3,-(%sp)
    lea     0x80003840,%a2          | every track's left, where stock's last stage leaves it and its transfer takes it
    lea     0x5c0,%a1
    moveq   #0,%d1                  | the half a mono track's own buffer
1:  move.l  %a2,%a3
    btst    #0,%d0
    beq.s   2f
    move.l  %a0,%a3                 | a stereo track's right channel
2:  .rept   16
    move.l  (%a3)+,(%a1)+
    .endr
    lea     64(%a0),%a0
    lea     64(%a2),%a2
    addq.l  #1,%d1
    btst    #0,%d1
    bne.s   4f
    lsr.l   #1,%d0                  | two halves done: the next track
4:  cmpi.l  #9,%d1
    bne.s   5f
    lea     0xe40,%a1               | the second stretch
5:  cmpi.l  #16,%d1
    bne.s   1b
    move.l  (%sp)+,%a3
    move.l  (%sp)+,%a2
    rts
#endif

| void longs(u32 *to, const u32 *from, u32 n): n longs, four a turn while there are four.
    .section .cave.k,"ax"
    .globl  longs
longs:
    movea.l 4(%sp),%a0
    movea.l 8(%sp),%a1
    move.l  12(%sp),%d0
1:  subq.l  #4,%d0
    bcs.s   2f
    move.l  (%a1)+,(%a0)+
    move.l  (%a1)+,(%a0)+
    move.l  (%a1)+,(%a0)+
    move.l  (%a1)+,(%a0)+
    bra.s   1b
2:  addq.l  #4,%d0
    beq.s   4f
3:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.s   3b
4:  rts

| void hq_pads(struct st *s): at a note's start, the frames around both ends of its slot written out for the sums, the
| end frame standing in for what is past it (engine/sampler.h, HQ): 45 words a side, frames -7 to 14 and then n - 15
| to n + 7, into the voice's 128 words of free memory. What the pitch image's routine writes, which asked of every
| word where it lay: here the first frame seven times, as many of the first fifteen as the slot has, the last frame
| for the rest; the first for those before the slot's last fifteen, those, and the last eight times.
    .section .cave.s,"ax"
    .globl  hq_pads
hq_pads:
    lea     -28(%sp),%sp
    movem.l %d2-%d6/%a2-%a3,(%sp)
    movea.l 32(%sp),%a1
    move.l  %a1,%d0
    and.l   #0xffff,%d0
    move.l  #1800,%d1
    divu.l  %d1,%d0                 | the voice
    lsl.l   #8,%d0
    add.l   #0x44060800,%d0         | HQ_PADS
    movea.l %d0,%a0
    move.l  %d0,S_PAD(%a1)
    move.l  S_FRAMES(%a1),%d2
    ble.s   8f
    moveq   #15,%d3
    cmp.l   %d2,%d3
    ble.s   1f
    move.l  %d2,%d3                 | how many of fifteen the slot has
1:  moveq   #15,%d4
    sub.l   %d3,%d4                 | and how many it has not
    movea.l S_L(%a1),%a2
2:  move.w  (%a2),%d0               | the first frame, and the last
    move.w  -2(%a2,%d2.l*2),%d1
    moveq   #7,%d5
    move.l  %d0,%d6
    bsr.s   hq_same
    movea.l %a2,%a3
    bsr.s   hq_copy
    move.l  %d4,%d5
    move.l  %d1,%d6
    bsr.s   hq_same
    move.l  %d4,%d5
    move.l  %d0,%d6
    bsr.s   hq_same
    move.l  %d2,%d5
    sub.l   %d3,%d5
    lea     (%a2,%d5.l*2),%a3
    bsr.s   hq_copy
    moveq   #8,%d5
    move.l  %d1,%d6
    bsr.s   hq_same
    move.l  S_R(%a1),%d0            | the right's, if there is one and it is another
    beq.s   8f
    cmpa.l  %d0,%a2
    beq.s   8f
    movea.l %d0,%a2
    bra.s   2b
8:  movem.l (%sp),%d2-%d6/%a2-%a3
    lea     28(%sp),%sp
    rts
hq_same:                            | d5 words of d6
    subq.l  #1,%d5
    bmi.s   9f
    move.w  %d6,(%a0)+
    bra.s   hq_same
9:  rts
hq_copy:                            | d3 words from a3
    move.l  %d3,%d5
1:  move.w  (%a3)+,(%a0)+
    subq.l  #1,%d5
    bne.s   1b
    rts

#ifdef TRIM
| void fade_run(struct st *s, s32 *l, s32 *r, int n, int m), the trim image's (engine/sampler.h, TRIM): the frames the
| one below makes, to the bit. A frame is (x >> 13) times twice the gain with its lowest four bits cleared, which is
| (x >> 13) times the gain, 3 dropped, 4 put back. The gain moves a step a frame with no test up to the frame after
| which it is held, worked out once: (4095 - gain) / step frames on going up, gain / -step going down. Held, it is
| 4096 with the step 0, or 0 with the step as it was.
    .section .cave.e,"ax"
    .globl  fade_run
fade_run:
    lea     -28(%sp),%sp
    movem.l %d2-%d7/%a2,(%sp)
    move.l  44(%sp),%d0
    move.l  48(%sp),%d1
    sub.l   %d0,%d1                 | frames
    ble.s   9f
    lsl.l   #2,%d0
    movea.l 36(%sp),%a0
    adda.l  %d0,%a0
    move.l  40(%sp),%d3
    beq.s   1f
    add.l   %d0,%d3
1:  movea.l %d3,%a2                 | the right's, or 0
    movea.l 32(%sp),%a1
    mvs.w   60(%a1),%d2             | the gain its step frames before it is held: with no step, all of them
    mvs.w   62(%a1),%d3
    move.l  %d1,%d4
    move.l  %d3,%d0
    beq.s   3f
    bgt.s   2f
    neg.l   %d0
    move.l  %d2,%d4                 | down: gain / -step
    bra.s   4f
2:  move.l  #4095,%d4
    sub.l   %d2,%d4                 | up: (4095 - gain) / step
4:  bge.s   7f
    moveq   #0,%d4                  | a gain already where it is held: the first frame is the last before it
7:  divu.l  %d0,%d4
    addq.l  #1,%d4                  | and the one after which it is
    cmp.l   %d1,%d4
    bls.s   3f
    move.l  %d1,%d4
3:  sub.l   %d4,%d1                 | frames at the held gain
    add.l   %d2,%d2
    add.l   %d3,%d3                 | twice the gain and its step
    moveq   #13,%d5
    moveq   #-16,%d6
    move.l  %d3,%d7
    bsr.s   fade_frames
    cmp.l   #8192,%d2               | held: up, at 4096 and the step 0; down, at 0
    blt.s   5f
    move.l  #8192,%d2
    moveq   #0,%d3
5:  tst.l   %d2
    bge.s   6f
    moveq   #0,%d2
6:  move.l  %d1,%d4
    moveq   #0,%d7
    bsr.s   fade_frames
    asr.l   #1,%d2
    asr.l   #1,%d3
    move.w  %d2,60(%a1)
    move.w  %d3,62(%a1)
9:  movem.l (%sp),%d2-%d7/%a2
    lea     28(%sp),%sp
    rts

| d4 frames from a0, and from a2 when it is not 0, at twice the gain in d2, which moves by d7 a frame.
fade_frames:
    tst.l   %d4
    beq.s   3f
    move.l  %a2,%d0
    beq.s   2f
1:  move.l  (%a0),%d0
    asr.l   %d5,%d0
    muls.l  %d2,%d0
    and.l   %d6,%d0
    move.l  %d0,(%a0)+
    move.l  (%a2),%d0
    asr.l   %d5,%d0
    muls.l  %d2,%d0
    and.l   %d6,%d0
    move.l  %d0,(%a2)+
    add.l   %d7,%d2
    subq.l  #1,%d4
    bne.s   1b
    rts
2:  move.l  (%a0),%d0
    asr.l   %d5,%d0
    muls.l  %d2,%d0
    and.l   %d6,%d0
    move.l  %d0,(%a0)+
    add.l   %d7,%d2
    subq.l  #1,%d4
    bne.s   2b
3:  rts
#else
| void fade_run(struct st *s, s32 *l, s32 *r, int n, int m): frames n to m - 1 through the fade that is on. A frame is
| 28 bits here: 13 dropped, times the gain (0 to 4096), 3 dropped, 4 put back, as engine/sampler.c's faded has it.
| Then the gain moves its step: at 4096 it stays and the step is 0, and it does not go under 0 (fade_move).
    .section .cave.m,"ax"
    .globl  fade_run
fade_run:
    lea     -12(%sp),%sp
    movem.l %d2-%d3/%a2,(%sp)
    movea.l 16(%sp),%a1
    move.l  28(%sp),%d0
    move.l  32(%sp),%d1
    sub.l   %d0,%d1                 | frames
    ble.s   6f
    lsl.l   #2,%d0
    movea.l 20(%sp),%a0
    adda.l  %d0,%a0
    move.l  24(%sp),%d3
    beq.s   1f
    add.l   %d0,%d3
1:  movea.l %d3,%a2                 | the right's, or 0 the gain its step
    mvs.w   60(%a1),%d2
    mvs.w   62(%a1),%d3
2:  move.l  (%a0),%d0
    asr.l   #8,%d0
    asr.l   #5,%d0
    muls.l  %d2,%d0
    asr.l   #3,%d0
    lsl.l   #4,%d0
    move.l  %d0,(%a0)+
    move.l  %a2,%d0
    beq.s   3f
    move.l  (%a2),%d0
    asr.l   #8,%d0
    asr.l   #5,%d0
    muls.l  %d2,%d0
    asr.l   #3,%d0
    lsl.l   #4,%d0
    move.l  %d0,(%a2)+
3:  add.l   %d3,%d2
    cmp.l   #4096,%d2
    blt.s   4f
    move.l  #4096,%d2
    moveq   #0,%d3
4:  tst.l   %d2
    bge.s   5f
    moveq   #0,%d2
5:  subq.l  #1,%d1
    bne.s   2b
    move.w  %d2,60(%a1)
    move.w  %d3,62(%a1)
6:  movem.l (%sp),%d2-%d3/%a2
    lea     12(%sp),%sp
    rts
#endif

| void swap(u32 *a, u32 n): n longs of stock's memory exchanged with the copy of its shape, 0xc4048000 on
| (engine/sampler.h, SHADOW). Six a turn while there are six.
    .section .cave.x,"ax"
    .globl  swap
swap:
    movea.l 4(%sp),%a0
    move.l  8(%sp),%d0
    lea     -44(%sp),%sp
    movem.l %d2-%d7/%a2-%a6,(%sp)
    movea.l %a0,%a1
    adda.l  #0xc4048000,%a1
1:  subq.l  #6,%d0
    bcs.s   2f
    movem.l (%a0),%d1-%d6
    movem.l (%a1),%d7/%a2-%a6
    movem.l %d1-%d6,(%a1)
    movem.l %d7/%a2-%a6,(%a0)
    lea     24(%a0),%a0
    lea     24(%a1),%a1
    bra.s   1b
2:  addq.l  #6,%d0
    beq.s   4f
3:  move.l  (%a0),%d1
    move.l  (%a1),(%a0)+
    move.l  %d1,(%a1)+
    subq.l  #1,%d0
    bne.s   3b
4:  movem.l (%sp),%d2-%d7/%a2-%a6
    lea     44(%sp),%sp
    rts
#endif
#ifdef XFADE
| The cross image: a loop's end blended into its start (engine/sampler.h, XFADE).
|
| void bake(struct st *s, struct xf *x): eight frames more of the seam's blend, both channels, from the frame the
| voice's count says. A frame of the blend is a frame of the pass, and over it by so many 256ths the frame as far from
| the place the seam leads to: 0 for the frames the pass comes in by, a 256th more a frame through the 256 before its
| wall, all of it from there on. Frames from outside a slot are read where they count for nothing.
    .equ    S_DIR0, 29
    .equ    S_XN, 84
    .equ    X_WALL, 0
    .equ    X_TO, 4
    .equ    X_OFF, 12
    .equ    X_L, 16
    .equ    XF_N, 352
    .equ    XF_FAR, 80
    .equ    XF_TURN, 272            | 256 + 16: where a blend played backwards is all of it, counted from its first frame
    .section .cave.x,"ax"
    .globl  bake
bake:
    lea     -28(%sp),%sp
    movem.l %d2-%d6/%a2-%a3,(%sp)
    movea.l 32(%sp),%a1
    movea.l 36(%sp),%a0
    mvz.w   S_XN(%a1),%d0           | frames written
    move.l  X_TO(%a0),%d5
    sub.l   X_WALL(%a0),%d5
    asr.l   #8,%d5
    asr.l   #3,%d5                  | bytes from a frame to the one it is blended with
    move.l  X_OFF(%a0),%d1
    asr.l   #8,%d1
    asr.l   #3,%d1
    add.l   %d0,%d1
    add.l   %d0,%d1                 | bytes from the slot's start to the frame to write where it goes: the right's is
    lea     X_L(%a0,%d0.l*2),%a0    | 2 * XF_N on
    move.l  %d0,%d2
    moveq   #XF_FAR,%d3
    sub.l   %d3,%d2                 | the gain, and what it moves by a frame
    moveq   #1,%d3
    tst.b   S_DIR0(%a1)
    bgt.s   1f
    neg.l   %d2                     | backwards: it comes down from all of it
    add.l   #XF_TURN-XF_FAR,%d2
    moveq   #-1,%d3
1:  addq.l  #8,%d0
    move.w  %d0,S_XN(%a1)
    movea.l S_L(%a1),%a2
    adda.l  %d1,%a2
    move.l  S_R(%a1),%d0
    beq.s   2f
    add.l   %d1,%d0
2:  movea.l %d0,%a3                 | the right's frames, or 0
    moveq   #8,%d1
3:  move.l  %d2,%d4                 | the gain, held to 0 and 256
    bge.s   4f
    moveq   #0,%d4
4:  cmp.l   #256,%d4
    ble.s   5f
    move.l  #256,%d4
5:  mvs.w   (%a2)+,%d0
    mvs.w   -2(%a2,%d5.l),%d6
    sub.l   %d0,%d6
    muls.l  %d4,%d6
    asr.l   #8,%d6
    add.l   %d6,%d0
    move.w  %d0,(%a0)
    move.l  %a3,%d0
    beq.s   6f
    mvs.w   (%a3)+,%d0
    mvs.w   -2(%a3,%d5.l),%d6
    sub.l   %d0,%d6
    muls.l  %d4,%d6
    asr.l   #8,%d6
    add.l   %d6,%d0
    move.w  %d0,2*XF_N(%a0)
6:  addq.l  #2,%a0
    add.l   %d3,%d2
    subq.l  #1,%d1
    bne.s   3b
    movem.l (%sp),%d2-%d6/%a2-%a3
    lea     28(%sp),%sp
    rts
#endif
#if defined(PACK) && !defined(MULTI)
| The pack image: single slots at the back (engine/sampler.h, PACK).
|
| void rec_step(struct st *s, u32 release): one block of a running take, as engine/sampler.c has it for the images
| before, written out here because the compiler's is 60 bytes more than the run holds. Every block of the ring not
| taken yet, in order, into the slot's buffer; more than a ring behind, a note let go, or a buffer that is full, and
| the take ends. A stereo place's take puts the ring's two sides in the slot's buffer and the next one's, and the next
| slot's line of the table says as long, or one frame for a mono take. A single slot's take is half of the two sides
| added, in its own buffer, and the next slot's buffer and line are not touched.
    .equ    S_LINK, 49              | what the take is: 0 mono, 1 stereo, below nothing a single slot's
    .equ    S_REC, 51
    .equ    S_RK, 52
    .equ    S_RSEQ, 54
    .equ    S_RPOS, 56
    .equ    MB_SEQ, 0x800           | the ring's count, in the window its eight blocks of 32 frames, left, right, ...
    .equ    MB_RING, 0x810          | the table: frames, then where
    .equ    SLOTS, 0x4404f754
    .equ    REC_BUFS, 0x44080000
    .equ    REC_STRIDE, 0xf0000     | bytes from a slot's buffer to the next frames a buffer holds
    .equ    REC_MAX, 0x78000
    .section .cave.r,"ax"
    .globl  rec_step
rec_step:
    lea     -28(%sp),%sp
    movem.l %d2-%d6/%a2-%a3,(%sp)
    movea.l 32(%sp),%a1
    mvz.b   S_RK(%a1),%d2
    move.l  S_RPOS(%a1),%d3         | frames taken
    mvz.w   MB_SEQ.w,%d4
    mvz.w   S_RSEQ(%a1),%d0
    sub.l   %d0,%d4
    mvz.w   %d4,%d4                 | blocks waiting
    move.l  #REC_STRIDE,%d5
    move.l  %d2,%d0
    mulu.l  %d5,%d0
    add.l   #REC_BUFS,%d0
    movea.l %d0,%a2                 | the slot's buffer
    moveq   #8,%d0
    cmp.l   %d4,%d0
    bcs.s   6f                      | more than the ring holds: the take ends and nothing is skipped
1:  tst.l   %d4
    beq.s   5f
    cmp.l   #REC_MAX,%d3
    bcc.s   6f                      | full
    subq.l  #1,%d4
    move.w  S_RSEQ(%a1),%d0
    addq.l  #1,%d0
    move.w  %d0,S_RSEQ(%a1)
    moveq   #7,%d1
    and.l   %d1,%d0
    lsl.l   #7,%d0
    movea.l %d0,%a0
    lea     MB_RING(%a0),%a0        | the next block of the ring where the take has got to
    lea     (%a2,%d3.l*2),%a3
    moveq   #32,%d6
    add.l   %d6,%d3
    tst.b   S_LINK(%a1)
    bmi.s   3f
2:  move.w  (%a0)+,(%a3)
    move.w  (%a0)+,(%a3,%d5.l)      | the next slot's buffer
    addq.l  #2,%a3
    subq.l  #1,%d6
    bne.s   2b
    bra.s   1b
3:  mvs.w   (%a0)+,%d0              | a single slot: half of the two sides
    mvs.w   (%a0)+,%d1
    add.l   %d1,%d0
    asr.l   #1,%d0
    move.w  %d0,(%a3)+
    subq.l  #1,%d6
    bne.s   3b
    bra.s   1b
5:  tst.l   36(%sp)                 | the note was let go
    bne.s   6f
    cmp.l   #REC_MAX,%d3
    bcs.s   7f
6:  clr.b   S_REC(%a1)
7:  move.l  %d3,S_RPOS(%a1)
    lsl.l   #3,%d2
    add.l   #SLOTS,%d2
    movea.l %d2,%a0                 | the slot's line of the table
    move.l  %d3,%d0
    tst.b   S_LINK(%a1)
#ifdef STOPS
    bmi.s   10f                     | a single slot's take leaves the next slot's line as it is
    bne.s   8f
    moveq   #2,%d0                  | a mono take: the next slot is not as long, so it is no right channel, and not odd,
                                    | so it is no single slot's sample either (TAKE_ONE, engine/sampler.h, STOPS)
#else
    bmi.s   9f                      | a single slot's take leaves the next slot's line as it is
    bne.s   8f
    moveq   #1,%d0                  | a mono take: the next slot is not as long, so it is no right channel (TAKE_ONE)
#endif
8:  move.l  %d0,8(%a0)
    add.l   %a2,%d5
    move.l  %d5,12(%a0)
9:  move.l  %d3,(%a0)
    move.l  %a2,4(%a0)
    movem.l (%sp),%d2-%d6/%a2-%a3
    lea     28(%sp),%sp
    rts
#ifdef STOPS
10: subq.l  #1,%d3                  | the stops image: a single slot's take is a frame short of its whole blocks, so
    bcc.s   9b                      | its length is odd from its first block on, which is what says it is one. (The
    moveq   #0,%d3                  | voice's own count of frames is as it was; and no frames are none.)
    bra.s   9b
#endif
#endif
#ifdef MULTI
| The multi image: a block a track (engine/sampler.h, MULTI).
|
| void rec_all(void): a block of every running take, before the voice loop. Called by sampler_hook alone, with the
| release mask in d4 as the interrupt keeps it. The window's long at 0x800 is the main CPU's count and, under it, a
| bit a track whose block it wrote with that count. A voice that is the sampler's and has a take running, whose count
| is not the one it saw last and whose bit is set, takes its track's block, the 32 frames at 0x810 + 128 t: a stereo
| place's take the two sides into the slot's buffer and the next one's, a single slot's half of the two added. A note
| let go or a full buffer ends the take, and the table's lines are written, all as the stops image's rec_step has
| them. The lines are written in the stops image's run of rec_step's caller (rec_line), for room.
    .equ    S_LINK, 49              | what the take is: 0 mono, 1 stereo, below nothing a single slot's
    .equ    S_REC, 51
    .equ    S_RK, 52
    .equ    S_RSEQ, 54
    .equ    S_RPOS, 56
    .equ    S_VOICE, 1712           | a voice's sampler state in the voice
    .equ    V_STRIDE, 1800
    .equ    MB_SEQ, 0x800           | the count, and the bits under it eight blocks of 32 frames, left, right, ...: a
    .equ    MB_RING, 0x810          | track's each the table: frames, then where
    .equ    SLOTS, 0x4404f754
    .equ    REC_BUFS, 0x44080000
    .equ    REC_STRIDE, 0xf0000     | bytes from a slot's buffer to the next frames a buffer holds
    .equ    REC_MAX, 0x78000
    .section .cave.r,"ax"
    .globl  rec_all
rec_all:
    lea     -36(%sp),%sp
    movem.l %d2-%d7/%a2-%a3/%a5,(%sp)
    move.l  %d4,%d7                 | the notes let go, this track's the lowest bit the count the blocks written with
    mvz.w   MB_SEQ.w,%d4            | it, this track's the lowest bit
    mvz.w   MB_SEQ+2.w,%d6
#ifdef HANDREC
| The handrec image: the word's high byte is the main CPU's tracks whose take runs past its note's release (a note
| played by hand, held for the TRIG page's LEN: engine/once.S, hand_rec). Their releases end nothing; the feed's
| stopping does.
    move.l  %d6,%d0
    lsr.l   #8,%d0
    not.l   %d0
    and.l   %d0,%d7
#endif
    move.l  #REC_STRIDE,%d5
    lea     MB_RING.w,%a0
    lea     0x80000000+S_VOICE,%a1
1:  movea.l %a0,%a5                 | this track's block and the next one's
    lea     128(%a0),%a0
    moveq   #11,%d0
    cmp.l   -S_VOICE(%a1),%d0       | the voice is the sampler's (V_ENGINE, ENGINE_ID)
    bne.s   9f
    tst.b   S_REC(%a1)
    beq.s   9f
    mvz.b   S_RK(%a1),%d2
    move.l  %d2,%d0
    mulu.l  %d5,%d0
    add.l   #REC_BUFS,%d0
    movea.l %d0,%a2                 | the slot's buffer frames taken
    move.l  S_RPOS(%a1),%d3
    mvz.w   S_RSEQ(%a1),%d0
    move.w  %d4,S_RSEQ(%a1)
    cmp.l   %d0,%d4
    beq.s   5f                      | nothing written since this take looked
    btst    #0,%d6
    beq.s   5f                      | or not this track's block
    cmp.l   #REC_MAX,%d3
    bcc.s   6f                      | full: nothing past the buffer's end, whatever the count of frames says where the
    lea     (%a2,%d3.l*2),%a3       | take has got to
    moveq   #32,%d0
    add.l   %d0,%d3
    tst.b   S_LINK(%a1)
    bmi.s   3f
2:  move.w  (%a5)+,(%a3)
    move.w  (%a5)+,(%a3,%d5.l)      | the next slot's buffer
    addq.l  #2,%a3
    cmpa.l  %a0,%a5
    bne.s   2b
    bra.s   5f
3:  mvs.w   (%a5)+,%d0              | a single slot: half of the two sides
    mvs.w   (%a5)+,%d1
    add.l   %d1,%d0
    asr.l   #1,%d0
    move.w  %d0,(%a3)+
    cmpa.l  %a0,%a5
    bne.s   3b
5:  btst    #0,%d7                  | the note was let go
    bne.s   6f
    cmp.l   #REC_MAX,%d3
    bcs.s   7f
6:  clr.b   S_REC(%a1)
7:  move.l  %d3,S_RPOS(%a1)
    jsr     rec_line
9:  lsr.l   #1,%d6
    lsr.l   #1,%d7
    lea     V_STRIDE(%a1),%a1
    cmpa.l  #MB_RING+1024,%a0
    bne.w   1b
    movem.l (%sp),%d2-%d7/%a2-%a3/%a5
    lea     36(%sp),%sp
    rts
| The slot's line of the table, and the next slot's: d2 the slot, d3 the take's frames, a2 its buffer, d5 the bytes to
| the next slot's buffer, a1 the voice's state. A mono take leaves 2 frames in the next slot's line, so it is no right
| channel and no single slot's sample (TAKE_ONE); a single slot's take leaves that line as it is, and is a frame short
| of its whole blocks, so its length is odd from its first block on.
    .section .cave.p,"ax"
    .globl  rec_line
rec_line:
    lsl.l   #3,%d2
    add.l   #SLOTS,%d2
    movea.l %d2,%a3                 | the slot's line of the table
    move.l  %d3,%d0
    tst.b   S_LINK(%a1)
    bmi.s   3f
    bne.s   1f
    moveq   #2,%d0
1:  move.l  %d0,8(%a3)
    lea     (%a2,%d5.l),%a5
    move.l  %a5,12(%a3)
2:  move.l  %d3,(%a3)
    move.l  %a2,4(%a3)
    rts
3:  subq.l  #1,%d3
    bcc.s   2b
    moveq   #0,%d3
    bra.s   2b
#endif
#ifdef STOPS
| The stops image: what every slot holds, said to the main CPU (engine/sampler.h, STOPS). Called at the end of every
| block, after the takes have had theirs. Sixteen slots a block, by a count of blocks in free memory that may be any
| number at a start: two bits a slot into one long, the first slot's the highest, a slot's length's lowest bit and
| then whether anything is left without it. The long goes to its place in the window, and the mark is moved up a byte
| with 0xa5 under it: it reads right after four blocks, when all four longs are written. In two runs: neither has room
| for all of it.
    .equ    ST_COUNT, 0x44050a18
    .equ    ST_MARK, 0x5bc
    .equ    ST_SLOTS, 0x4404f754    | the table: frames, then where
    .section .cave.q,"ax"
    .globl  stops_say
stops_say:
    lea     ST_COUNT,%a0
    addq.l  #1,(%a0)
    moveq   #3,%d0
    and.l   (%a0),%d0               | which sixteen where their long goes
    movea.w stops_at(%pc,%d0.l*2),%a0
    lsl.l   #7,%d0
    add.l   #ST_SLOTS,%d0
    movea.l %d0,%a1                 | their lines of the table a bit that falls out of the long's top after the
    moveq   #1,%d1                  | sixteenth slot
    bra.w   stops_bits
stops_at:
    .word   0x808, 0x80c, 0xe38, 0xe3c
    .section .cave.p,"ax"
stops_bits:
    move.l  (%a1),%d0
    addq.l  #8,%a1
    lsr.l   #1,%d0                  | the lowest bit of the length,
    addx.l  %d1,%d1
    neg.l   %d0                     | and whether the rest is anything
    addx.l  %d1,%d1
    bcc.s   stops_bits
    move.l  %d1,(%a0)
    move.l  ST_MARK.w,%d0
    lsl.l   #8,%d0
    move.b  #0xa5,%d0
    move.l  %d0,ST_MARK.w
    rts
#endif
#ifdef TIMED
| Stock starts the second of the chip's timers counting at its start (0x40000dec: its clock on, then its mode word 3,
| which is run free on the bus clock) and never reads or names it again. Its count is read here where the interrupt
| calls the voice loop and where its last stage comes back: nearly all of an interrupt lies between. Every 256 blocks
| the longest of those is put to the window as hundredths of a block (a block being the 256th of the 256 gaps from one
| interrupt to the next), and after it the most that has been in the last 32 to 64 such lots, 5 to 11 seconds.
    .equ    T_COUNT, 0xfc07400c     | the second timer's count free memory: this interrupt's start, the longest, the
    .equ    T_STATE, 0x44050a00     | gaps' sum, blocks, the most of this stretch of lots and of the one before. The
    .equ    T_BOX, 0x5b4            | window, after the right channels' long
#ifdef PACK
    .section .cave.i,"ax"           | (the pack image: beside the routine's last part, for room where a note starts)
#else
    .section .cave.x,"ax"           | in the room the render left: Twinshot's other run has not room for all three
#endif
    .globl  timed_hook
timed_hook:                         | in place of sampler_hook in the interrupt's call of the voice loop
    move.l  T_COUNT,%d0
    lea     T_STATE,%a0
    move.l  (%a0),%d1
    move.l  %d0,(%a0)
    sub.l   %d1,%d0                 | since the interrupt before: a block, when all is well
    add.l   %d0,8(%a0)
    jmp     sampler_hook
    .section .cave.m,"ax"
    .globl  timed_amp
timed_amp:                          | in place of sampler_amp in the interrupt's call of its last stage
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    jsr     sampler_amp
    lea     20(%sp),%sp
    move.l  T_COUNT,%d0
    lea     T_STATE,%a0
    sub.l   (%a0),%d0               | since this interrupt called the voice loop
    cmp.l   4(%a0),%d0
    bls.s   1f
    move.l  %d0,4(%a0)              | the longest of this lot
1:  addq.l  #1,12(%a0)
    tst.b   15(%a0)
    beq.s   2f
    rts
2:  jmp     timed_lot
    .section .cave.n,"ax"           | the rest in two of the small runs nothing reaches: there is room nowhere else
timed_lot:                          | 256 blocks: the longest as hundredths of a block
    move.l  4(%a0),%d0
    moveq   #100,%d1
    mulu.l  %d1,%d0
    move.l  8(%a0),%d1
    lsr.l   #8,%d1
    beq.s   2f                      | a timer that does not count: nothing to divide by, and 0 is said
    divu.l  %d1,%d0
    cmp.l   #999,%d0
    bls.s   3f
2:  move.l  #999,%d0
    tst.l   %d1
    bne.s   3f
    moveq   #0,%d0
3:  clr.l   4(%a0)
    clr.l   8(%a0)
    move.l  16(%a0),%d1             | the most of this stretch
    cmp.l   %d1,%d0
    bls.s   4f
    move.l  %d0,%d1
4:  move.l  %d1,16(%a0)
    move.l  20(%a0),%a1             | and of the one before
    cmp.l   %a1,%d1
    bcc.s   6f
    move.l  %a1,%d1
6:  cmp.l   #999,%d1                | (that memory comes as it is at a start: for the first seconds it may say 999)
    bls.s   7f
    move.l  #999,%d1
7:  jmp     timed_say
    .section .cave.i,"ax"
timed_say:                          | d0 and d1 as text, to the window
    move.l  %d1,-(%sp)
    move.l  #0x43303030,%d1         | C and three figures, as the page writes them
    bsr.s   timed_text
#ifndef HITS
    move.l  %d1,T_BOX               | (the hits image: the long is the hits' now, engine/sampler.h)
#endif
    move.l  (%sp)+,%d0
    move.l  #0x50303030,%d1         | P
    bsr.s   timed_text
    move.l  %d1,T_BOX+4
    move.l  12(%a0),%d0
    and.l   #0x1f00,%d0
    bne.s   5f
    move.l  16(%a0),20(%a0)         | 32 lots: this stretch is the one before now
    clr.l   16(%a0)
5:  rts
timed_text:                         | a number up to 999 in d0 -> its three figures added to the long in d1
    move.l  %d2,-(%sp)
    move.l  %d3,-(%sp)
    moveq   #10,%d2
    remu.l  %d2,%d3:%d0
    divu.l  %d2,%d0
    add.l   %d3,%d1
    remu.l  %d2,%d3:%d0
    divu.l  %d2,%d0
    lsl.l   #8,%d3
    add.l   %d3,%d1
    swap    %d0
    add.l   %d0,%d1
    move.l  (%sp)+,%d3
    move.l  (%sp)+,%d2
    rts
#endif
#ifdef SRR
| The srr image: sample rate reduction (engine/sampler.h, SRR). In SY SWARM's room.
|
| crush(h, l, r): the block's 32 frames at l, and at r unless it is 0, held. h: the step, the phase, the two frames
| held. A frame at which the phase runs over is let through and kept; every other one is the frame kept. Five
| instructions a frame held and six a frame let through; with a right channel six and eight.
    .section .cave.d,"ax"
    .globl  crush
crush:
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    movea.l 20(%sp),%a1             | h the left the right, or 0 the step the phase the left's frame, held
    movea.l 24(%sp),%a0
    movea.l 28(%sp),%a2
    move.l  (%a1)+,%d2
    move.l  (%a1)+,%d1
    move.l  (%a1)+,%d0
    moveq   #32,%d4
    move.l  %a2,%d3
    beq.s   3f
    move.l  (%a1),%d3               | the right's
1:  add.l   %d2,%d1
    bcc.s   2f
    move.l  (%a0),%d0
    move.l  (%a2),%d3
2:  move.l  %d0,(%a0)+
    move.l  %d3,(%a2)+
    subq.l  #1,%d4
    bne.s   1b
    move.l  %d3,(%a1)
    bra.s   5f
3:  add.l   %d2,%d1
    bcc.s   4f
    move.l  (%a0),%d0
4:  move.l  %d0,(%a0)+
    subq.l  #1,%d4
    bne.s   3b
5:  move.l  %d0,-(%a1)
    move.l  %d1,-(%a1)
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    rts

| SY SWARM is gone: its code is this room. A track left on it plays nothing: an update that does nothing and a render
| that fills the track's block with nothing. Engine 10's two table entries.
    .globl  swarm_update
    .globl  swarm_render
swarm_update:
    rts
swarm_render:
    movea.l 4(%sp),%a0
    moveq   #32,%d0
1:  clr.l   (%a0)+
    subq.l  #1,%d0
    bne.s   1b
    rts
#endif

#ifdef BACK
| The back image: our code that was in SY SWARM's, SY TOY's and SY BITS's and SD BASIC's runs (caves d, e, g) is
| linked at FAR_DST and carried past section 7's end (FAR_SRC), which the start's BSS clear would wipe. Called in
| place of the start's two calls (0x400010b4): stock's copy of its SRAM data, then ours, then stock's clear. All
| before the cache is set (0x400010d0), so nothing is flushed. Their runs and their engines are stock's again.
    .section .cave.x,"ax"
    .globl  far_load
    .globl  far_copy
far_load:
    jsr     0x400004bc
    bsr.s   far_copy
    jmp     0x40000512
far_copy:
    lea     FAR_SRC,%a0
    lea     FAR_DST,%a1
    move.l  #FAR_LONGS,%d0
1:  move.l  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.s   1b
    rts
#endif
