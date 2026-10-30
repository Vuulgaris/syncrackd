/* The mirror image (-DMIRROR): the screen to a viewer over USB, as SysEx, for video. The maintainer, 2026-10-26, of a
 * video with the unit's screen drawn clean in a window above the footage: "Can we try option one?" (the screen's
 * frames streamed off the unit, drawn big by a viewer, the viewer's window put over the camera).
 *
 * The panel (READ, docs/FINDINGS.md, "The mirror image"): the UI draws onto a surface over a 1,024-byte buffer, a
 * column of 64 dots in 8 bytes, 128 columns; 0x4011391a sends the panel the bytes of *0x402d7110 that changed from
 * *0x402d7114, swaps the two pointers (after it 0x402d7114 is the frame on the panel, 0x402d7110 the other) and hands
 * back the other, the buffer to draw the next one in. Stock's own getter of the panel's frame reads 0x402d7114
 * (0x40113a20). The mirror image's first build sent *0x402d7110: the next frame's buffer, not the panel's. The UI's routine at 0x4000a1xx asks 0x4010095c whether anything is to be drawn, and draws
 * and sends only then, through a4, loaded at 0x4000a22c.
 *
 * Here: the send goes through mirror_paint, which marks a frame as new; the asking goes through mirror_tick, which
 * sends the frame shown when one is new, the viewer has asked, and a frame's time has passed since the last. So the
 * last frame of a fast turn goes too, at the next asking. A frame is sent only while the viewer's last 0x67 is less
 * than 3 s old (engine/phone.c, MIRROR): a viewer that goes away stops it.
 *
 *   viewer to unit  0x67  on, renewed: a byte, frames a second (0: 15)
 *   viewer to unit  0x68  off
 *   unit to viewer  0x69  a frame: f0 00 20 3c 10 00, 00 00 01 00 00, 69, a count (7 bits), the 1,024 bytes 7 to a
 *                         group (a byte of their high bits, bit 6 the first's, then their low 7 bits; the last group 2),
 *                         f7: 1,185 bytes. Byte 8 c + p is column c's dots 8 p up to 8 p + 7, most significant bit
 *                         first: dot y (0 the panel's bottom row) is bit 7 - y % 8 of byte 8 c + y / 8, as emu/screen.py
 *                         reads the surface.
 *
 * The frame is written into the unit's own SysEx sink as stock's answers are (engine/phone.c, ask): from the UI's
 * task, so a frame and an answer of the MIDI task's can mix if both run at once. The viewer does no file transfers
 * while it mirrors. */
#include "sampler.h"

#define MAVE __attribute__((section(".cave.m"), noinline))
#define NAVE __attribute__((section(".cave.n"), noinline))
#define OAVE __attribute__((section(".cave.o"), noinline))

#define paint ((u32 (*)(void))0x4011391a)                   /* stock's: the frame drawn to the panel; -> the buffer to draw next in */
#define dirty ((u32 (*)(void *))0x4010095c)                 /* stock's: (the UI's + 64) -> anything to draw, in the low byte */
#define SHOWN (*(const u8 *const volatile *)0x402d7114)    /* the frame on the panel, after paint (stock's 0x40113a20) */
#define SINK ((void *)0x4449c51c)
#define SINK_MADE (*(volatile u32 *)0x4449c808)             /* not 0 once the unit has had a message */
#define CLOCK (*(volatile u32 *)0xfc07000c)                 /* the first timer: about 132 MHz */
#define ASK_LIFE (3u * 132000000u)
#define FRAME 1024u

struct mirror {
    u32 on;                     /* the viewer asked (engine/phone.c) */
    u32 asked;                  /* CLOCK at its last 0x67 */
    u32 period;                 /* ticks between frames */
    u32 last;                   /* CLOCK at the last frame sent */
    u32 fresh;                  /* a frame was drawn since */
    u32 count;
};
__asm__(".section .cave.m,\"ax\"\n"
        "        .globl mirror_vars\n"
        "mirror_vars:  .long 0, 0, 8800000, 0, 0, 0\n"
        "mirror_head:  .byte 0xf0, 0x00, 0x20, 0x3c, 0x10, 0x00, 0, 0, 1, 0, 0, 0x69\n"
        "              .even\n"
        "              .text\n");
extern volatile struct mirror mirror_vars;
extern const u8 mirror_head[12];
#define M mirror_vars

typedef void (*put_fn)(void *, const u8 *, u32);

/* The frame's bytes from i on, packed 7 to a group into b, eight groups (56 bytes, 64 packed) or to the end: -> the
 * packed bytes. In a third run. */
OAVE static u32 mirror_pack(u8 *b, const u8 *f, u32 i)
{
    u32 n, g, k, hi;

    for (n = 0; n < 64 && i < FRAME; n += g + 1, i += g) {
        g = FRAME - i < 7 ? FRAME - i : 7;
        for (hi = 0, k = 0; k < g; k++) {
            hi |= (u32)(f[i + k] >> 7) << (6 - k);
            b[n + 1 + k] = f[i + k] & 0x7f;
        }
        b[n] = hi;
    }
    return n;
}

#ifdef PIECES
/* The sink image (-DPIECES): stock's put (0x40105f24) copies into the sink's 144 bytes (+ 20, its size at + 532, how
 * many it has at + 8) and sends them when they are full (+ 12: 0x40105eb4), but copies what is left of that call from
 * the call's start again, not from where it was. The first build's 64-byte writes crossed a send at the stream's byte
 * 144, 288 and so on: the rest of that piece came out as its own start again. So a write here never crosses one. */
#define SINK_HAS (*(volatile u32 *)((u8 *)SINK + 8))
#define SINK_SIZE (*(volatile u32 *)((u8 *)SINK + 532))

__attribute__((section(".cave.p"), noinline)) static void mirror_put(put_fn put, const u8 *p, u32 n)
{
    u32 k;

    for (; n; p += k, n -= k) {
        k = SINK_SIZE - SINK_HAS;
        if (k == 0 || k > n)
            k = n;
        put(SINK, p, k);
    }
}

/* One frame to the viewer, in writes of 64 bytes at most, none crossing a send of the sink's. */
NAVE static void mirror_send(const u8 *f)
{
    void **vt = *(void ***)SINK;
    put_fn put = (put_fn)vt[4];
    u8 b[64];
    u32 i;

    mirror_put(put, mirror_head, sizeof mirror_head);
    b[0] = M.count++ & 0x7f;
    mirror_put(put, b, 1);
    for (i = 0; i < FRAME; i += 56)
        mirror_put(put, b, mirror_pack(b, f, i));
    b[0] = 0xf7;
    mirror_put(put, b, 1);
    ((void (*)(void *))vt[3])(SINK);
}
#else
/* One frame to the viewer, in writes of 64 bytes at most. */
NAVE static void mirror_send(const u8 *f)
{
    void **vt = *(void ***)SINK;
    put_fn put = (put_fn)vt[4];
    u8 b[64];
    u32 i;

    put(SINK, mirror_head, sizeof mirror_head);
    b[0] = M.count++ & 0x7f;
    put(SINK, b, 1);
    for (i = 0; i < FRAME; i += 56)
        put(SINK, b, mirror_pack(b, f, i));
    b[0] = 0xf7;
    put(SINK, b, 1);
    ((void (*)(void *))vt[3])(SINK);
}
#endif

#ifdef SHADOW
/* The shadow image (-DSHADOW): the frame sent is what reached the panel. On the unit the second build's frames
 * (*0x402d7114 at the asking) still had strokes at the dials where the panel was clean, so the buffers are not taken
 * at their word. Every 8 bytes stock's column sender (0x4011384c, the panel's only way in: the send, the whole frame
 * and the clear call it) is given are copied into a frame of ours, mirror_frame, from 1,024 bytes of stock's heap
 * taken at the viewer's first asking; then every byte of the frame paint compares against is turned over and a
 * draw asked for, so the next send rewrites the whole panel and the copy is whole from there on. */
#define ALLOC ((u8 *(*)(u32))0x40103952)                 /* stock's: the heap, where the UI's surfaces take theirs */

__asm__(".section .cave.o,\"ax\"\n"
        "        .globl mirror_frame\n"
        "mirror_frame:  .long 0\n"
        "        .globl mirror_cols\n"
        "mirror_cols:                            | at 0x4011384c: (column, page, 8 bytes)\n"
        "        move.l  mirror_frame,%d0\n"
        "        beq.s   2f\n"
        "        move.l  %d0,%a0\n"
        "        move.l  4(%sp),%d0\n"
        "        cmpi.l  #120,%d0\n"
        "        bhi.s   2f\n"
        "        lsl.l   #3,%d0\n"
        "        moveq   #7,%d1\n"
        "        and.l   8(%sp),%d1\n"
        "        add.l   %d1,%d0\n"
        "        adda.l  %d0,%a0\n"
        "        move.l  12(%sp),%a1\n"
        "        moveq   #8,%d1\n"
        "1:      move.b  (%a1)+,(%a0)\n"
        "        addq.l  #8,%a0\n"
        "        subq.l  #1,%d1\n"
        "        bne.s   1b\n"
        "2:      lea     -16(%sp),%sp            | stock's first two, then the rest of it\n"
        "        movem.l %d2-%d4/%a2,(%sp)\n"
        "        jmp     0x40113854\n"
        "        .text\n");
extern u8 *volatile mirror_frame;

/* At the viewer's first asking: the frame of ours taken and made, the whole panel to be sent again. */
MAVE static void mirror_prime(void *ui)
{
    u8 *f, *b;
    u32 k;

    if (!M.on || mirror_frame || !(f = ALLOC(FRAME)))
        return;
    b = (u8 *)SHOWN;
    for (k = 0; k < FRAME; k++) {
        f[k] = b[k];
        b[k] = ~b[k];
    }
    *((volatile u8 *)ui + 32) = 1;                          /* stock's own mark to draw (0x40100966) */
    mirror_frame = f;
}
#endif

/* In place of the UI's a4: stock's send to the panel, and the frame marked new. */
MAVE u32 mirror_paint(void)
{
    u32 r = paint();

    M.fresh = 1;
    return r;
}

/* In place of the UI's asking whether anything is to be drawn: stock's answer, after the frame shown is sent if it is
 * new and its time has come. */
MAVE u32 mirror_tick(void *ui)
{
#ifdef SHADOW
    mirror_prime(ui);
#endif
    u32 r = dirty(ui), now;

    if (M.on && M.fresh && SINK_MADE) {
        now = CLOCK;
        if (now - M.asked > ASK_LIFE)
            M.on = 0;
        else if (now - M.last >= M.period) {
            M.last = now;
            M.fresh = 0;
#ifdef SHADOW
            mirror_send(mirror_frame ? mirror_frame : SHOWN);
#else
            mirror_send(SHOWN);
#endif
        }
    }
    return r;
}
