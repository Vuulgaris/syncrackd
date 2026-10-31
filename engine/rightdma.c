/* Main CPU (section 3, OS 1.42 only): the right side of the eight digital tracks, moved out of the
 * window by the transfer controller. The dma image; it takes the place of engine/rightfill.c, which
 * the images before it keep.
 *
 * What was wrong: a stereo track's right channel was read out of the window by the CPU, 64 slow bus
 * cycles a track a block, inside the per-block interrupt. With stereo samples playing the screen and
 * the knobs lagged; with mono ones they did not (the maintainer's comparison, docs/FINDINGS.md).
 *
 * Stock moves its own eight buffers with channel 47 of the controller: sixteen bytes a turn, a turn
 * linked to the next by the channel's own number, started by a write of that number, and done when
 * bit 7 of the channel's last word is set. Two channels of ours are set as stock sets its own and
 * move the window's two stretches of right channels the same way. They are of group 0, which every
 * other group goes before: a transfer of stock's waits for a turn of ours at most.
 *
 * A transfer may not land in the program's memory by its cached address, so the second set of
 * buffers is in on-chip memory here, after what the startup copies to its first half: cleared at
 * every start, named by nothing in the file.
 *
 * Three places. The per-block routine's first call: the long that says which tracks have a right
 * channel is read and the transfers are started, as early as a block allows. The audio CPU wrote
 * them at the end of the block before and is a block's work from writing the next. The last call
 * before the mixer's: the transfers are waited for, and every track without a right channel is
 * given a copy of its left, which stock's own transfer has brought by then. And between the two,
 * where the images before read the right channels: nothing, unless the transfers were given up.
 *
 * Nothing here can be run before it is on the unit: emulation has no transfer controller. So the
 * routine does not believe its transfers until it has seen them. From a start, for GOOD_BLOCKS
 * blocks, the CPU reads all sixteen halves too and the two are compared; the sound is the CPU's.
 * After that the transfers alone are used. BAD_BLOCKS blocks that differ, or a wait that does not
 * end, and they are given up until the next start: the CPU reads, where and as rightfill.c does.
 * Which of the three it is, the sampling page says (engine/recpage.c, DMA). */
#include "sampler.h"

#define DMA_WAIT ((void (*)(void))0x400a20ae)   /* stock: until the transfer it started is over */
#define AUDIO_UP (*(volatile u32 *)0x43bdd824)  /* the audio CPU is running: stock tests it here too */
#define TRACKS ((const u32 *)0x80003d50)
#define WINDOW 0x10000000u
#define SCRATCH ((u32 *)0x80007400)             /* the sixteen halves as the CPU read them, while they are compared */
#define RIGHT ((u32 *)0x80007800)               /* the second set */
#define STATE ((u32 *)0x80007d00)
enum { S_MASK, S_ARMED, S_GOOD, S_BAD, S_MODE, S_SET, S_POLLS, S_WHY };
enum { CHECK, TRUSTED, DEAD };
#define GOOD_BLOCKS 1500                        /* a second */
#define BAD_BLOCKS 16
#define POLL_LIMIT 20000                        /* far past the time a transfer has: one late block, and never again */

#define CH_A 12                                 /* halves 0 to 8, from 0x5c0 */
#define CH_B 13                                 /* halves 9 to 15, from 0xe40 */
#define TCD(ch) (0xfc045000u + 32u * (ch))
#define L(a) (*(volatile u32 *)(a))
#define W(a) (*(volatile u16 *)(a))
#define B(a) (*(volatile u8 *)(a))
#define DONE(ch) (W(TCD(ch) + 0x1e) & 0x80)

#define CAVE __attribute__((section(".cave.o")))

#ifdef LAP
/* The lap image, a tool: five more readings of the profile's timer (engine/prof.S), in the record's places for the
 * first five longs of the stopped stack, which the interrupt's start has filled by then: at the per-block routine's
 * first call, on either side of stock's wait for the audio CPU's buffers, and on either side of our last call
 * before the mixer. tools/prof_read.py sees them for what they are. */
#define LAP_AT(k) (*(volatile u32 *)(PROF_AT + 36u + 4u * (k)) = *(volatile u32 *)0xfc07000cu)
#define LAP_STR2(x) #x
#define LAP_STR(x) LAP_STR2(x)
/* The four on either side of the two calls, in front of them: stock's wait is called here and again in right_mid,
 * where it has nothing left to wait for. */
__asm__(".section .cave.q,\"ax\",@progbits\n"
        "    .globl right_mid_lap\n"
        "right_mid_lap:\n"
        "    move.l  0xfc07000c,%d0\n"
        "    move.l  %d0," LAP_STR(PROF_AT) "+40\n"
        "    jsr     0x400a20ae\n"
        "    move.l  0xfc07000c,%d0\n"
        "    move.l  %d0," LAP_STR(PROF_AT) "+44\n"
        "    jmp     right_mid\n"
        "    .globl right_ready_lap\n"
        "right_ready_lap:\n"
        "    move.l  0xfc07000c,%d0\n"
        "    move.l  %d0," LAP_STR(PROF_AT) "+48\n"
        "    jsr     right_end\n"
        "    move.l  0xfc07000c,%d0\n"
        "    move.l  %d0," LAP_STR(PROF_AT) "+52\n"
        "    jmp     0x4009580c\n"
        "    .text\n");
#else
#define LAP_AT(k) ((void)0)
#endif

/* The two places: ours, then what stock called there, with the stack as stock left it. */
__asm__(".section .cave.o,\"ax\",@progbits\n"
        "    .globl right_start\n"
        "right_start:\n"
        "    jsr     right_begin\n"
        "    jmp     0x4010222a\n"
        "    .globl right_ready\n"
        "right_ready:\n"
        "    jsr     right_end\n"
        "    jmp     0x4009580c\n"
        "    .text\n");

/* Four longs a turn. Each long of the window is read once. */
CAVE __attribute__((noinline)) static u32 *take(u32 *to, const volatile u32 *from, u32 fours)
{
    do {
        *to++ = *from++;
        *to++ = *from++;
        *to++ = *from++;
        *to++ = *from++;
    } while (--fours);
    return to;
}

/* The halves of the tracks of the mask, by the CPU. */
CAVE __attribute__((noinline)) static void by_cpu(u32 mask)
{
    u32 t;

    for (t = 0; t < N_TRACKS; t++)
        if (mask >> t & 1) {
            take(RIGHT + BLOCK * t, RW_HALF(WINDOW, 2 * t), BLOCK / 8);
            take(RIGHT + BLOCK * t + BLOCK / 2, RW_HALF(WINDOW, 2 * t + 1), BLOCK / 8);
        }
}

/* A channel's standing words, as stock writes channel 47's and in its order: nothing added to either
 * address after the last turn, sixteen bytes a turn read and written as sixteen, both addresses
 * sixteen on a turn, and nothing asked for at the end. First: no request line starts it. */
CAVE __attribute__((noinline)) static void set_up(u32 ch)
{
    u32 t = TCD(ch);

    B(0xfc044019) = ch;
    L(t + 0x18) = 0;
    L(t + 0x0c) = 0;
    W(t + 0x04) = 0x0404;
    W(t + 0x06) = 16;
    L(t + 0x08) = 16;
    W(t + 0x16) = 16;
    W(t + 0x1e) = 0;
}

/* A transfer, as stock starts one: to, from, the turns twice with the link to itself, the start. Before
 * them the last word is written 0 again, as it was when the channel was set: the controller takes "done"
 * away when the channel's turn comes, which for a channel of the lowest group may be after stock's, and
 * the wait is not to find the "done" of the block before. */
CAVE __attribute__((noinline)) static void start(u32 ch, u32 from, u32 *to, u32 turns)
{
    u32 t = TCD(ch), n = 0x8000u | ch << 9 | turns;

    W(t + 0x1e) = 0;
    L(t + 0x10) = (u32)to;
    L(t + 0x00) = from;
    W(t + 0x14) = n;
    W(t + 0x1c) = n;
    B(0xfc04401e) = ch;
}

/* The per-block routine's first call. */
CAVE void right_begin(void)
{
    u32 *st = STATE;
    u32 word, mask = 0, mode, armed = 1, h;

    LAP_AT(0);
    st[S_ARMED] = 0;
    mode = st[S_MODE];
    if (!AUDIO_UP || mode == DEAD)              /* given up: the CPU reads, where the images before read (right_mid) */
        return;
    word = *RW_HEAD_MAIN;
    if (word == RW_WORD(word))
        mask = word & 0xff;
    st[S_MASK] = mask;
    if (!st[S_SET]) {
        set_up(CH_A);
        set_up(CH_B);
        st[S_SET] = 1;
    }
    if (mode == CHECK) {                        /* all sixteen by the CPU, and a mark where a transfer has to write */
        take(take(SCRATCH, RW_HALF(WINDOW, 0), 9 * BLOCK / 8), RW_HALF(WINDOW, 9), 7 * BLOCK / 8);
        for (h = 0; h < 2 * N_TRACKS; h++)
            RIGHT[(BLOCK / 2) * h] = 0x5a5a5a00u + h;
        mask = 0xff;
    }
    if (mask & 0x1f) {
        start(CH_A, WINDOW + 0x5c0, RIGHT, 36);
        armed |= 2;
    }
    if (mask & 0xf0) {
        start(CH_B, WINDOW + 0xe40, RIGHT + 9 * BLOCK / 2, 28);
        armed |= 4;
    }
    st[S_ARMED] = armed;
}

/* Where stock waits for the left buffers, before it sends the next block's knobs: stock's wait, and the
 * answer to what stock tested there, as in the images before (engine/rightfill.c). And with the transfers
 * given up, the long and the right channels by the CPU, here, where those images read them. */
__attribute__((section(".cave.p"))) u32 right_mid(void)
{
    u32 *st = STATE;
    u32 up, word, mask = 0;

    DMA_WAIT();
    up = AUDIO_UP;
    if (up && st[S_MODE] == DEAD) {
        word = *RW_HEAD_MAIN;
        if (word == RW_WORD(word))
            mask = word & 0xff;
        st[S_MASK] = mask;
        st[S_ARMED] = 1;
        by_cpu(mask);
    }
    return up;
}

#ifdef MOVEM
/* The copy image: every track with no right channel is given a copy of its left by eight longs a move (movem), four
 * moves each way a track, where take() moved one long at a time in a loop (32 loads, 32 stores and the loop's own: about
 * 90 instructions a track, about 750 a block with eight mono tracks). 
 * In a run of its own: (mask, left, to). */
void mono_copy(u32 mask, const u32 *left, u32 *to);
__asm__(".section .cave.c,\"ax\",@progbits\n"
        "    .globl mono_copy\n"
        "mono_copy:\n"
        "    lea     -32(%sp),%sp\n"
        "    movem.l %d2-%d7/%a2-%a3,(%sp)\n"
        "    move.l  36(%sp),%d1\n"            /* the tracks with a right channel: a bit a track */
        "    move.l  40(%sp),%a0\n"            /* the left buffers */
        "    move.l  44(%sp),%a1\n"            /* the right ones */
        "    moveq   #8,%d0\n"
        "    move.l  %d0,%a2\n"                /* eight tracks */
        "1:  btst    #0,%d1\n"
        "    bne.s   2f\n"
        "    movem.l (%a0),%d0/%d2-%d7/%a3\n"
        "    movem.l %d0/%d2-%d7/%a3,(%a1)\n"
        "    movem.l 32(%a0),%d0/%d2-%d7/%a3\n"
        "    movem.l %d0/%d2-%d7/%a3,32(%a1)\n"
        "    movem.l 64(%a0),%d0/%d2-%d7/%a3\n"
        "    movem.l %d0/%d2-%d7/%a3,64(%a1)\n"
        "    movem.l 96(%a0),%d0/%d2-%d7/%a3\n"
        "    movem.l %d0/%d2-%d7/%a3,96(%a1)\n"
        "2:  lea     128(%a0),%a0\n"
        "    lea     128(%a1),%a1\n"
        "    lsr.l   #1,%d1\n"
        "    move.l  %a2,%d0\n"
        "    subq.l  #1,%d0\n"
        "    move.l  %d0,%a2\n"
        "    bne.s   1b\n"
        "    movem.l (%sp),%d2-%d7/%a2-%a3\n"
        "    lea     32(%sp),%sp\n"
        "    rts\n"
        "    .text\n");
#endif

/* The last call before the mixer's. In a run of its own: the first is 712 bytes. */
__attribute__((section(".cave.p"))) void right_end(void)
{
    u32 *st = STATE;
    u32 armed = st[S_ARMED], was = st[S_MODE], mode = was, mask = 0, n = 0, bad = 0, t, k;
    const u32 *left = TRACKS;
    u32 *to = RIGHT;

    st[S_ARMED] = 0;
    if (armed) {
        mask = st[S_MASK];
        if (armed & 6) {
            while ((armed & 2 && !DONE(CH_A)) || (armed & 4 && !DONE(CH_B)))
                if (++n == POLL_LIMIT) {
                    mode = DEAD;
                    st[S_WHY] = 1 + was;        /* 1: a wait did not end while they were checked. 2: after */
                    break;
                }
            if (n > st[S_POLLS])
                st[S_POLLS] = n;
        }
        if (was == CHECK) {
            for (k = 0; k < 2 * N_TRACKS * (BLOCK / 2); k++)
                if (RIGHT[k] != SCRATCH[k]) {
                    RIGHT[k] = SCRATCH[k];
                    bad = 1;
                }
            if (mode != DEAD) {
                if (bad) {
                    if (++st[S_BAD] == BAD_BLOCKS) {
                        mode = DEAD;
                        st[S_WHY] = 3;          /* 3: what they brought was not what the CPU read */
                    }
                } else if (++st[S_GOOD] == GOOD_BLOCKS) {
                    mode = TRUSTED;
                }
            }
        } else if (mode != was) {               /* given up in this block: its right channels by the CPU, late, this once */
            by_cpu(mask);
        }
        st[S_MODE] = mode;
    } else if (!AUDIO_UP) {
        *RW_HEAD_MAIN = 0;                      /* a restart of the audio CPU is not to find the word of its last block here */
        *STOPS_MARK(WINDOW) = 0;                /* nor is what it said the slots hold believed until it has said it again */
    }
#ifdef MOVEM
    (void)t;
    mono_copy(mask, left, to);
#else
    for (t = 0; t < N_TRACKS; t++, left += BLOCK, to += BLOCK)
        if (!(mask >> t & 1))
            take(to, left, BLOCK / 4);
#endif
}
