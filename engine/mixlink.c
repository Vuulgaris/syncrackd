/* Main CPU (section 3, OS 1.42 only): what the mixer is shown, for the length
 * of one mixer call. Replaces the one call to the mixer.
 *
 * 1. Stereo link. For every track whose knobs say "this sampler, stereo", the
 *    next track's sends, volume, routing and level words are made equal to this
 *    track's and the two pans are forced hard left and hard right.
 * 2. Audio mute. A muted track, digital (1..8) or analog (9..12), is shown a
 *    volume of 0, so the mixer fades it out over the block: dry signal and
 *    sends. Stock mute only stops new trigs. The mixer takes all 12 levels
 *    from the same volume word. "Muted" is worked out the way the trig code
 *    at 0x400a39a0 and 0x400a421a does: the global mutes, or everything but
 *    the solo tracks when there is a solo, or the pattern's mutes. The
 *    right-hand track of a stereo pair is muted with its left and never by
 *    itself. The FX track is left alone.
 *
 * Everything is put back afterwards: the main CPU's own data is never left
 * changed. The rule for "linked" is the same one the audio CPU uses
 * (engine/sampler.c, sampler_post), read from the same parameters.
 *
 * With ONETRACK (the stereo image) a stereo sample keeps to its own track and
 * there is no link: the next track is its own again, with its own pan, and a
 * stereo track's pan is its balance. The mute is all that is left here.
 */
#include "sampler.h"

#ifdef MIXSPLIT
/* The mixtime image, a tool: stock's mixer is called through mix_timed, which reads the profile's timer before and after
 * it into two places of the profile's record (engine/prof.S): + 36, which the lap image read at the per-block routine's
 * first call, and + 56, the last of the stopped code's six stack longs. So the mixer stretch's 34.7 hundredths are
 * split into stock's mixer and our links around it (to a split of the mixer). In a run
 * of its own: this one has 2 bytes. */
void *mix_timed(void *, void *, u8 *);
#define MIXER mix_timed
__asm__(".section .cave.n,\"ax\",@progbits\n"
        "        .globl  mix_timed\n"
        "mix_timed:\n"
        "        move.l  0xfc07000c,%d1\n"            /* d1 and a1 are the caller's to lose */
        "        move.l  %d1," PROF_STR "+36\n"
        "        move.l  12(%sp),-(%sp)\n"
        "        move.l  12(%sp),-(%sp)\n"
        "        move.l  12(%sp),-(%sp)\n"
        "        jsr     0x4008f242\n"
        "        lea     12(%sp),%sp\n"
        "        move.l  0xfc07000c,%d1\n"            /* d0 is the mixer's answer: left as it is */
        "        move.l  %d1," PROF_STR "+56\n"
        "        rts\n"
        "        .text\n");
#else
#define MIXER ((void *(*)(void *, void *, u8 *))0x4008f242)
#endif
#define LEVEL2 ((u16 *)0x80004670)  /* a second word per track the mixer's gain uses */
#define P_FIRST 118                 /* delay send, reverb send, pan, volume, routing */
#define P_PAN 122
#define P_VOL 124
#define P_LAST 128
#define MUTES ((u32 *)0x80003048)   /* [0] global mutes, [1] solos: a bit per track */
#define PATTERN_MUTES ((u16 *)0x43bdd828)
#define MIX_TRACKS 12                /* the mixer's own loop: 8 digital, 4 analog */
#define PAN_LEFT 0
#define PAN_RIGHT (127 << 8)

struct saved {
    u16 pan;                        /* this track's pan */
    u16 level, level2;              /* the next track's level words */
    u8 next[P_LAST - P_FIRST];      /* the next track's mixer parameters */
};

__attribute__((section(".cave.m")))
void *mix_link(void *a, void *b, u8 *params)
{
#ifndef ONETRACK
    struct saved sv[N_TRACKS - 1];
    u16 *level = (u16 *)params;     /* one word per track at the head of the block */
    u32 k;
#endif
    u32 linked = 0, mute;
#ifdef SOLOKNOB
    u32 solo;
#endif
#ifdef XFADE
    u32 top = 0, next = 0, who = 0; /* the largest of the eight crossfades, whose it is, and the largest of the others */
#endif
#ifdef XMUTE
    u32 heard = 0;                  /* the trig image: the track holding the crossfade, heard through its global mute */
#endif
    u16 vol[MIX_TRACKS];
    void *result;
    int i;

#ifndef ONETRACK
    for (i = 0; i < N_TRACKS - 1; i++) {
        u8 *p = params + PARAMS_STRIDE * i;
        u8 *q = p + PARAMS_STRIDE;

        if (p[PARAM_TYPE] != MACHINE_TYPE || !STEREO(p[PARAM_KNOBS + 2 * K_MODE]))
            continue;
        linked |= 1u << i;
        sv[i].pan = *(u16 *)(p + P_PAN);
        sv[i].level = level[i + 1];
        sv[i].level2 = LEVEL2[i + 1];
        for (k = 0; k < P_LAST - P_FIRST; k++) {
            sv[i].next[k] = q[P_FIRST + k];
            q[P_FIRST + k] = p[P_FIRST + k];
        }
        *(u16 *)(p + P_PAN) = PAN_LEFT;
        *(u16 *)(q + P_PAN) = PAN_RIGHT;
        level[i + 1] = level[i];
        LEVEL2[i + 1] = LEVEL2[i];
    }
#endif

#ifdef SOLOKNOB
    /* The soloknob image: a solo is the sampling page's (SOLO_WORD, engine/sampler.h). With any, every track
     * that has none is silenced and no mute counts. A track that is no sampler any more has no knob to take
     * its solo off, so it has none: its bit is cleared here. */
    mute = solo = SOLO_WORD;
    for (i = 0; i < N_TRACKS; i++)
        if (params[PARAMS_STRIDE * i + PARAM_TYPE] != MACHINE_TYPE)
            mute &= ~(1u << i);
#ifdef APAGE        /* the apage image: an analog track has the page and its knob, so its solo is kept */
    mute &= (1u << MIX_TRACKS) - 1;
#else
    mute &= (1u << N_TRACKS) - 1;
#endif
    if (mute != solo)
        SOLO_WORD = mute;
#ifdef SLOCK        /* the slock image: this block's solos, a step's own among them (engine/amute.c, which runs first) */
    mute = SOLO_NOW;
#endif
    mute = mute ? ~mute : MUTES[0] | *PATTERN_MUTES;
#else
    mute = (MUTES[1] ? ~MUTES[1] : MUTES[0]) | *PATTERN_MUTES;
#endif
#ifdef XFADE
    /* The xfade image: a crossfade is the sampling page's too (XFADES, engine/sampler.h), a number a sampler
     * track. A track is turned down by the largest of the other tracks' numbers: the largest of all, and for the
     * track that holds it the next one. A track that is no sampler any more has no knob, so its number is 0. */
    if (XFADE_ANY)
#ifdef APAGE        /* the apage image: twelve numbers, and an analog track is never without its knob */
        for (i = 0; i < MIX_TRACKS; i++) {
            u32 x = XFADES[i];

            if (x && i < N_TRACKS && params[PARAMS_STRIDE * i + PARAM_TYPE] != MACHINE_TYPE)
#else
        for (i = 0; i < N_TRACKS; i++) {
            u32 x = XFADES[i];

            if (x && params[PARAMS_STRIDE * i + PARAM_TYPE] != MACHINE_TYPE)
#endif
                XFADES[i] = x = 0;
            if (x > top) {
                next = top;
                top = x;
                who = i;
            } else if (x > next)
                next = x;
        }
#endif
#ifdef XMUTE
    /* The trig image: with no solo on, the track that holds the crossfade comes in as it goes up even when it is muted
     * by the global mutes (not the pattern's), at its crossfade's share of its volume. 
     * */
    if (top && !SOLO_NOW && (MUTES[0] & ~(u32)*PATTERN_MUTES) >> who & 1) {
        heard = 1u << who;
        mute &= ~heard;
    }
#endif
    for (i = 0; i < MIX_TRACKS; i++) {
        u16 *v = (u16 *)(params + PARAMS_STRIDE * i + P_VOL);

        if (linked & (1u << i))                 /* the next track follows this one */
            mute = (mute & ~(2u << i)) | ((mute << 1) & (2u << i));
        vol[i] = *v;
        if (mute & (1u << i))
            *v = 0;
#ifdef XMUTE
        else if (heard & (1u << i))
            *v = BY_TOP((u32)*v * top);
#endif
#ifdef XFADE
        else if (top) {                         /* its volume, as far down as the others' crossfade says: 0 at the top */
            u32 x = (u32)i == who ? next : top;

            if (x)
                *v = BY_TOP((u32)*v * (XFADE_TOP - x));
        }
#endif
    }

    result = MIXER(a, b, params);

    for (i = 0; i < MIX_TRACKS; i++)
        *(u16 *)(params + PARAMS_STRIDE * i + P_VOL) = vol[i];
#ifndef ONETRACK
    for (i = N_TRACKS - 2; i >= 0; i--) {       /* undo in reverse, so overlapping pairs restore exactly */
        u8 *p = params + PARAMS_STRIDE * i;
        u8 *q = p + PARAMS_STRIDE;

        if (!(linked & (1u << i)))
            continue;
        LEVEL2[i + 1] = sv[i].level2;
        level[i + 1] = sv[i].level;
        for (k = 0; k < P_LAST - P_FIRST; k++)
            q[P_FIRST + k] = sv[i].next[k];
        *(u16 *)(p + P_PAN) = sv[i].pan;
    }
#endif
    return result;
}
