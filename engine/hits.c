/* Main CPU (section 3, OS 1.42 only): the hits image. A long sample's hits start the filter's envelope again.
 *
 * The on request
 * , and the control in the envelope
 * delay's place: "could replace env delay if it needs to i dont like tht contorl".
 *
 * The filter's envelope is this CPU's (docs/FINDINGS.md, "The filter's envelope is the main CPU's"): stock's
 * 0x400965a4 (the block's params, the trigs, the releases, the tracks it skips), once a block, eight tracks, called at
 * 0x400a4ccc. The call comes here. The sound engine has said, in the window's long at 0x5b4, how loud a hit each
 * track's playhead will reach in two blocks (four bits a track, 0 none, 1 to 15 in 3 dB steps up to -3 dB:
 * engine/sampler.h, HITS). On a sampler track DEL is that hit's threshold: 0 off, 1 the loudest only, 127 all of
 * them. A hit DEL lets through is a trig of the envelope's alone, in the argument this call hands it and nowhere
 * else: the amp, the LFOs and the sound engine are handed the trigs as they were.
 *
 * And on a sampler track stock is handed DEL at 0, so its envelope never waits: the word is put back after the call,
 * so that nothing else finds it changed. A lock of DEL, an LFO on it and a pattern's save are stock's, as for any
 * knob. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define HIT_BOX (*(const volatile u32 *)0x100005b4)
#define FILTER_ENV ((void (*)(u8 *, u32, u32, u32))0x400965a4)
#define STRIDE 142              /* a track's params in the block */
#define TYPE_WORD 62            /* the machine's type, a byte up, as stock writes it into the block just before */
#define DEL 90                  /* the Filter record's DEL, knob slot 31: its number in the high byte */
#define SAMPLER (44 << 8)

#ifdef SOLOEND
/* The soloend image. On request
 * . A step's solo lock stays in the lock block till the track's next trig; here the track's bit of solo_gone is
 * set at its note's release (the trig's LEN, or the key let go) and cleared at its next trig, and the solos
 * (engine/amute.c, solo_now) pass over a lock whose bit is set. Twelve bytes, first in the run: the long, then the
 * mark each sampler track had the block before. */
__asm__(".section .cave.o,\"ax\"\n"
        "        .globl solo_gone\n"
        "solo_gone:  .long 0, 0, 0\n"
        "            .text\n");
extern volatile u32 solo_gone[3];
#define SOLO_LAST ((volatile u8 *)&solo_gone[1])
#define SOLO_MARK(t) (((const volatile u8 *)0x800021b0)[STRIDE * (t) + 28 + 2 * 17])    /* the lock block's slot 17, high byte */
#endif

__attribute__((section(".cave.o"))) void hits_env(u8 *params, u32 trig, u32 release, u32 skip)
{
    u32 word = HIT_BOX, took = 0, t;
    u16 kept[8];
    u8 *p = params;

#ifdef SOLOEND
    {
        u32 gone = (solo_gone[0] | release) & ~trig;  /* a release and the next trig in one block: the new note's */

        for (t = 0; t < 8; t++)                     /* a mark not there the block before is a new lock, a trigless one too */
            if (SOLO_MARK(t) != SOLO_LAST[t]) {
                SOLO_LAST[t] = SOLO_MARK(t);
                gone &= ~(1u << t);
            }
        solo_gone[0] = gone & 0xff;                 /* the eight digital tracks only: an analog track's lock is as it was */
    }
#endif
    for (t = 0; t < 8; t++, p += STRIDE) {
        u32 del = p[DEL];

        if (*(const u16 *)(p + TYPE_WORD) != SAMPLER || !*(const u16 *)(p + DEL))
            continue;
        kept[t] = *(const u16 *)(p + DEL);
        *(u16 *)(p + DEL) = 0;
        took |= 1u << t;
        if (del && (word >> 4 * t & 15) >= 15 - ((del - 1) * 15 >> 7))
            trig |= 1u << t;
    }
    FILTER_ENV(params, trig, release, skip);
    for (t = 0, p = params; took; t++, p += STRIDE, took >>= 1)
        if (took & 1)
            *(u16 *)(p + DEL) = kept[t];
}

#ifdef HITUI
/* The hitui image: on a sampler track the filter pages say what DEL is now. The maintainer, 2026-10-14, of the envelope's
 * picture: "the ui for the amp env just still shows the delyed env", and "build the draein and del name fix".
 *
 * Stock's filter page (class 0x401c9da0) draws FLTR1 (pages 7, 9, 11) and FLTR2 (page 10) with loops of their own,
 * not the base page's. Three places, each a call of ours:
 *   - FLTR2's loop takes a knob's name from the descriptors by its record (0x4004232e): DEL's record (0x3f) on a
 *     sampler track is named HITS (hit_short);
 *   - the base turn routine's pop-up, "%s=%s", takes the name from the knob's holder (0x4003bc28, where its two ways
 *     join): the same (hit_popname);
 *   - FLTR1's picture of the envelope asks DEL's value of the routine in a3 (0x4004268a): on a sampler track it is
 *     handed 0, and the picture has no delay (hit_deldraw).
 * DEL's knob on FLTR2 still shows its number, 0 to 127: the hits' threshold. Every other machine is stock's. */
#define active_track ((u32 (*)(void *))0x4001ff74)
#define machine_of ((int (*)(void *, u32))0x4000f692)
#define DESCRIPTORS 0x4022d83cu     /* 52 bytes a record, the short name's pointer at + 0x30 */
#define DEL_RECORD 0x3f

extern const char hits_name[];              /* "HITS", in the run with the code (below) */

__attribute__((section(".cave.o"), noinline)) static int on_sampler(u8 *page)
{
    return machine_of(*(void **)(page + 120), active_track(*(void **)(page + 116))) == 44;
}

__attribute__((section(".cave.o"))) const char *hit_name(u8 *page, u32 record, const char *name)
{
    return record == DEL_RECORD && on_sampler(page) ? hits_name : name;
}

__attribute__((section(".cave.o"))) const char *hit_short(u8 *page, u32 record)
{
    if (record >= 505)                          /* stock's: past the records, the first */
        record = 0;
    return hit_name(page, record, *(const char **)(DESCRIPTORS + 52 * record + 0x30));
}

__attribute__((section(".cave.o"))) u32 hit_shown(u8 *page, u32 record, u32 value)
{
    return record == DEL_RECORD && on_sampler(page) ? 0 : value;
}

__asm__(
"    .section .cave.o,\"ax\"\n"
"    .globl  hits_name\n"
"hits_name:\n"
#ifdef TRANS
"    .asciz  \"TRANS\"\n"
#else
"    .asciz  \"HITS\"\n"
#endif
"    .even\n"
"    .globl  hit_popname\n"
"hit_popname:\n"                        /* in place of: addq.l #8,%sp ; movea.l (%a2),%a0 ; move.l %d0,%d4. d0 the name, d2 the record, a2 the page */
"    move.l  %d0,-(%sp)\n"
"    move.l  %d2,-(%sp)\n"
"    move.l  %a2,-(%sp)\n"
#ifdef TRANS
"    jsr     hit_long\n"
#else
"    jsr     hit_name\n"
#endif
"    lea     12(%sp),%sp\n"
"    move.l  %d0,%d4\n"
"    movea.l (%sp)+,%a1\n"
"    addq.l  #8,%sp\n"
"    movea.l (%a2),%a0\n"
"    jmp     (%a1)\n"
"    .globl  hit_deldraw\n"
"hit_deldraw:\n"                        /* in place of: jsr (%a3) ; lea 24(%sp),%sp. Above the return: page, record, flag, then three more */
"    move.l  12(%sp),-(%sp)\n"
"    move.l  12(%sp),-(%sp)\n"
"    move.l  12(%sp),-(%sp)\n"
"    jsr     (%a3)\n"                   /* stock's: (page, record, flag) -> the value */
"    move.l  %d0,8(%sp)\n"
"    jsr     hit_shown\n"               /* (page, record, value) */
"    lea     12(%sp),%sp\n"
"    movea.l (%sp),%a1\n"
"    lea     28(%sp),%sp\n"
"    jmp     (%a1)\n"
);
#ifdef TRANS
/* The trans image: on a sampler track FLTR2 draws DEL's record as a plain knob named TRANS, TRANSIENT in the pop-up. The
 * on request
 * . A knob's picture and name are drawn by the page's + 180 (0x4003842c): with its last argument 0
 * it calls the record's graphic from the display table (DEL's and the analog page's 0x89: the delay's, 0x400706ac; a
 * plain knob's 0x400701b4, same arguments), with 1 none at all (the first build of this image: "no graphic at all");
 * the name under it is the descriptor's, by 0x40012b24 at 0x400385c6 (FLTR2's own name place, 0x4004232e, is for a knob
 * it greys out). So:
 *   - FLTR2's test of DEL (0x400424bc) jumps to del_knob, which keeps stock's way (0) and marks a sampler track's DEL;
 *   - the delay's graphic, at its start, draws a plain knob once when marked (del_gfx);
 *   - the name's call at 0x400385c6 goes through trans_label: TRANS on a sampler track's DEL.
 * In a run of its own (the hits' run is full). d0 is not read before it is set again past the test. */
extern const char trans_long[];

__attribute__((section(".cave.o"))) const char *hit_long(u8 *page, u32 record, const char *name)
{
    return record == DEL_RECORD && on_sampler(page) ? trans_long : name;
}

__asm__(
"    .section .cave.t,\"ax\"\n"
"    .globl  trans_long\n"
"trans_long:\n"
"    .asciz  \"TRANSIENT\"\n"
"    .even\n"
"    .globl  trans_mark\n"
"trans_mark:\n"                          /* nonzero: the next delay graphic is a sampler track's DEL */
"    .word   0\n"
"    .globl  del_knob\n"
"del_knob:\n"                           /* in place of: moveq #63,%d0 ; cmpl %d2,%d0 ; bnes 0x400424c8. d2 the record, a2 the page */
"    moveq   #63,%d0\n"
"    cmp.l   %d2,%d0\n"
"    bne.s   2f\n"
"    pea     1.w\n"
"    move.l  %d2,-(%sp)\n"
"    move.l  %a2,-(%sp)\n"
"    jsr     hit_shown\n"               /* 0 on a sampler track */
"    lea     12(%sp),%sp\n"
"    tst.l   %d0\n"
"    seq     %d0\n"
"    move.w  %d0,trans_mark\n"
"    jmp     0x400424c2\n"              /* the record's own picture, stock's way */
"2:  jmp     0x400424c8\n"
"    .globl  del_gfx\n"
"del_gfx:\n"                            /* in place of: lea -12(%sp),%sp ; movem.l %d2-%d4,(%sp), the delay graphic's start */
"    tst.w   trans_mark\n"
"    beq.s   1f\n"
"    clr.w   trans_mark\n"
"    jmp     0x400701b4\n"              /* a plain knob's: (object, value 8.8, surface, x, y), as the delay's */
"1:  lea     -12(%sp),%sp\n"
"    movem.l %d2-%d4,(%sp)\n"
"    jmp     0x400706b4\n"
"    .globl  trans_label\n"
"trans_label:\n"                        /* in place of jsr 0x40012b24 (holder, record) -> the short name. a5 the page */
"    move.l  8(%sp),-(%sp)\n"
"    move.l  8(%sp),-(%sp)\n"
"    jsr     0x40012b24\n"
"    addq.l  #8,%sp\n"
"    move.l  %d0,-(%sp)\n"
"    move.l  12(%sp),-(%sp)\n"
"    move.l  %a5,-(%sp)\n"
"    jsr     hit_name\n"
"    lea     12(%sp),%sp\n"
"    rts\n"
);
#endif
#endif
