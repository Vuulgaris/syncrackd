/* Main CPU (section 3, OS 1.42 only), the prof image: a tool, not one to keep. Where the main CPU's time goes, asked
 * of the unit, which is the only thing that can say.
 *
 * A record of 32 words is kept here and made afresh every block. A sampler track whose SRC is the last source (SENDS
 * on the page: it is the profile on this image) is fed the record in place of sound, the same words to both sides, so
 * a take of any kind holds it word for word. Saved and brought off with Transfer, tools/prof_read.py reads it.
 * Nothing here talks to anything.
 *
 * The clock is the chip's first timer's count (0xfc07000c). Stock reads it for a wait of its own (0x400a596a: two
 * readings, their difference against 1,319,999,999), so it counts and goes round at 32 bits. What a count is in
 * seconds is not needed: every number the reader gives is one count over another.
 *
 * The record, big end first, a long two words:
 * 0  word  0x5052
 * 2  word  the interrupts counted
 * 4  long  the count at the interrupt's start
 * 8  long  the top of what the chip put on the stack: its format and vector, and the SR of what was stopped
 * 12  long  where it was stopped (its PC)
 * 16  long  its stack pointer
 * 20  long  the count at the mixer's call (engine/recfeed.c, mix_rec)
 * 24  long  the count when the mixer and every link of ours before it has come back
 * 28  long  the count when the takes are fed and the meter is done: the block before's
 * 32  long  the count at the interrupt's end: the block before's
 * 36        six longs from the top of the stopped code's stack: its callers are among them
 * 60  long  the running task's control block: the long stock's task switch (0x40000410) saves the registers
 * through and stores the next task's in (0x454e49a8). Nothing of stock's runs in user mode (no
 * instruction below the code's end names the other stack pointer), so the stopped code's stack is the
 * one the frame is on.
 *
 * The interrupt. Stock's per-block routine (0x400a38ce, vector 191) is not asked for by its vector's long: stock
 * compares that long with the routine's address (0x400a376a), so the long is left alone. The routine's first two
 * instructions are a jump to prof_irq, which does them itself and goes on at the third. To have the end as well,
 * prof_irq puts a second frame under stock's routine: its rte comes to prof_exit at the same level, which reads the
 * count and does the real rte. The frame's SR is the one the routine runs with, read, not assumed.
 *
 * Nothing is saved on the stack before the frame is read: two longs after the record hold d0 and a0. The interrupt
 * does not come while it runs, so one place is enough. */
#define TIMER   0xfc07000c
#define STOCK   0x400a38d6              /* the routine's third instruction */
#define TASK    0x454e49a8

        .section .cave.y,"ax"
        .globl  prof_vars, prof_irq, prof_exit, prof_block

prof_vars:
        .word   0x5052, 0
        .fill   15, 4, 0
prof_keep:
        .long   0, 0
/* Kept in every image from here on, so the profile is always at hand; the last source is the sends again unless this
 * long is set: the sampling page's last knob sets it, and its box reads PROF while it is (engine/recpage.c). 0 at
 * every start. */
        .globl  prof_on
prof_on:
        .long   0

prof_irq:
        move.l  %d0,prof_keep
        move.l  %a0,prof_keep+4
        lea     prof_vars,%a0
        move.l  TIMER,%d0
        move.l  %d0,4(%a0)
        mvz.w   2(%a0),%d0
        addq.l  #1,%d0
        move.w  %d0,2(%a0)
        move.l  (%sp),8(%a0)            | format, vector, SR PC
        move.l  4(%sp),12(%a0)
        moveq   #8,%d0
        add.l   %sp,%d0
        move.l  %d0,16(%a0)             | its stack pointer: the frame is two longs
        move.l  8(%sp),36(%a0)
        move.l  12(%sp),40(%a0)
        move.l  16(%sp),44(%a0)
        move.l  20(%sp),48(%a0)
        move.l  24(%sp),52(%a0)
        move.l  28(%sp),56(%a0)
        move.l  TASK,%d0
        move.l  %d0,60(%a0)
        move.l  #prof_exit,-(%sp)       | a frame of ours: stock's rte comes to prof_exit
        move.w  %sr,%d0
        mvz.w   %d0,%d0
        or.l    #0x40000000,%d0         | format 4: the stack is on a long, as the chip left it
        move.l  %d0,-(%sp)
        move.l  prof_keep,%d0
        movea.l prof_keep+4,%a0
        link.w  %fp,#-164               | stock's first two instructions
        movem.l %d0-%d7/%a0-%a5,(%sp)
        jmp     STOCK

#ifdef CUT
/* In the copies' run (the profile's has 12 bytes). */
        .section .cave.p,"ax"
        .globl  prof_gate
prof_gate:
        tst.l   prof_on
        jeq     1f
        jmp     prof_irq
1:      link.w  %fp,#-164
        movem.l %d0-%d7/%a0-%a5,(%sp)
        jmp     STOCK
        .section .cave.y,"ax"
#endif

prof_exit:
        move.l  %d0,prof_keep
        move.l  TIMER,%d0
        move.l  %d0,prof_vars+32
        move.l  prof_keep,%d0
        rte

/* void prof_block(volatile s16 *d): the record into a block of the window, 64 words, each of the record's twice
 * (left, right). The window stores words: a word a write, in order. */
prof_block:
        movea.l 4(%sp),%a0
        lea     prof_vars,%a1
        moveq   #32,%d0
1:      move.w  (%a1)+,%d1
        move.w  %d1,(%a0)+
        move.w  %d1,(%a0)+
        subq.l  #1,%d0
        jne     1b
        rts
