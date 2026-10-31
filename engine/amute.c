/* Main CPU (section 3, OS 1.42 only): audio mute for the dry sound of the analog tracks (9..12). Sits in front of the
 * mixer link (engine/mixlink.c) in the chain that replaces the one call to the mixer.
 *
 * The dry sound of an analog voice never passes the mixer: it goes to the outputs through two level circuits, left
 * and right, that the main CPU steers. The per-block routine works their values out from the track's volume and pan
 * before it calls the mixer (0x4008ffc0: level times pan law, 0..65535, 0 is shut) and sends the whole control block
 * to the hardware after the mixer returns. In between, here, the two values of every muted analog track are set to 0,
 * which is what the track's own volume at 0 gives.
 *
 * Nothing is saved or put back: the routine works the block out again from the parameters every time. "Muted" is the
 * rule of the mixer link, which also shows the mixer a volume of 0 for these tracks and so cuts their sends. */
#include "sampler.h"

#define MUTES ((const u32 *)0x80003048)         /* [0] global mutes, [1] solos: a bit per track */
#define PATTERN_MUTES ((const u16 *)0x43bdd828)
#define CONTROL ((u16 *)0x80003160)             /* words 0..3 left level of voice 1..4, 5..8 right */
#define ANALOG_FIRST 8                          /* voice v belongs to track 8 + v */
#define ANALOG_VOICES 4
#define RIGHT 5

void *mix_link(void *a, void *b, u8 *params);   /* MIX_NEXT: the next in the chain, from its build */

#ifdef ALOCK
/* The alock image: this block's solos, worked out for all twelve tracks. A sampler track as the slock image has it;
 * an analog track as the mark its playing step left in slot 26 says, if it holds an analog machine. In a run of its
 * own: the analog mute's is full. */
#ifdef SOLOEND
#define SOLOS_RUN ".cave.e"     /* the soloend image: a run of its own (mainmap.CAVE_SOLOEND), the alock image's is full */
#else
#define SOLOS_RUN ".cave.t"
#endif
__attribute__((section(SOLOS_RUN), noinline)) static u32 solo_now(const u8 *params)
{
    u32 now = SOLO_WORD, v, d, slot;
#ifdef SOLOEND
    u32 gone = SOLO_GONE;
#endif

    for (v = 0; v < ANALOG_FIRST + ANALOG_VOICES; v++) {
        slot = K_SOLO;
#ifdef FAST
        /* The fast image: a track with no mark on its slot and no solo of its own changes nothing below, whatever its
         * machine: so only its byte is read. */
        d = (params - WORDS_BACK)[PARAMS_STRIDE * v + PARAM_KNOBS + 2 * (v >= N_TRACKS ? K_SOLO_ANALOG : K_SOLO)];
        if (d != SOLO_LOCK_ON && d != SOLO_LOCK_OFF && !(now >> v & 1))
            continue;
#endif
        if (v >= N_TRACKS) {
            if (!ANALOG_MACHINE(TRACK_TYPES[v]))
                continue;
            slot = K_SOLO_ANALOG;
        } else if (params[PARAMS_STRIDE * v + PARAM_TYPE] != MACHINE_TYPE) {
            now &= ~(1u << v);
            continue;
        }
        d = (params - WORDS_BACK)[PARAMS_STRIDE * v + PARAM_KNOBS + 2 * slot];
#ifdef SOLOEND
        if (gone >> v & 1)          /* the soloend image: a sampler step's lock is over once its note is (engine/hits.c) */
            continue;
#endif
        if (d == SOLO_LOCK_ON)
            now |= 1u << v;
        else if (d == SOLO_LOCK_OFF)
            now &= ~(1u << v);
    }
    SOLO_NOW = now;
    return now;
}
#endif

#ifdef XMUTE
/* The trig image: an analog track that holds the crossfade is heard through a global mute as it goes up, with no solo
 * on (engine/mixlink.c, XMUTE). Its word is made its crossfade's share squared, as stock's level word is, and its bit
 * of the mute is handed back to be cleared; the loop then turns it down by the others' crossfades as any track. In
 * the profile's run: the analog mute's and the solos' are full. With no crossfade who is 0, no analog track. */
__attribute__((section(".cave.y"), noinline)) static u32 heard(u32 top, u32 who)
{
    u16 *c = CONTROL + who - ANALOG_FIRST;

    if (who < ANALOG_FIRST || SOLO_NOW || !((MUTES[0] & ~(u32)*PATTERN_MUTES) >> who & 1))
        return 0;
    top *= top;
    c[0] = c[0] * top >> 14;        /* over 16,384, not 127 x 127: 0.14 dB under at the top, for room */
    c[RIGHT] = c[RIGHT] * top >> 14;
    return 1u << (who - ANALOG_FIRST);
}
#endif

#ifdef XKNOB
/* The xknob image: a sampler track's crossfade is its knob on slot 25, DEC's, stored upside down (127 is 0, so a
 * track made before, its DEC at 127 as stock leaves it, has none). Read every block from the block the mixer is
 * given, a lock and an LFO with it, into the eight numbers the mixer link and the analog mute go by.
 *
 * In the recorder's run: the analog mute's has room for the call only. */
__attribute__((section(".cave.r"), noinline)) static void xf_knobs(const u8 *params)
{
    u32 t, x;

    for (t = 0; t < N_TRACKS; t++) {
        const u8 *p = params + PARAMS_STRIDE * t;

        x = p[PARAM_KNOBS + 2 * K_DECAY];
        XFADES[t] = p[PARAM_TYPE] != MACHINE_TYPE || x >= XFADE_TOP ? 0 : XFADE_TOP - x;
    }
}
#endif

#ifdef FAST
/* The fast image: is there nothing for the analog mute and the mixer link to change this block? No solo (the knobs',
 * and no mark on a track's solo slot), no track muted by the global or the pattern's mutes, no sampler track's knob D
 * turned (slot 25 at 127 or past it), the analog tracks' crossfades 0. Then they would show stock's mixer the block
 * as it is and put back what they did not change: so the solos and the eight crossfades are left as solo_now and
 * xf_knobs would leave them (none), and the mixer is called straight away (stock's mixer writes nothing of the block:
 * tests/test_fast.py). In a run of its own. */
__attribute__((section(".cave.k"), noinline)) static u32 quiet(const u8 *params)
{
    const u8 *p = params, *q = params - WORDS_BACK;
    u32 v, d;

    if (SOLO_WORD || ((MUTES[0] | *PATTERN_MUTES) & ((1u << (ANALOG_FIRST + ANALOG_VOICES)) - 1)) || ((const u32 *)XFADES)[2])
        return 0;
    for (v = 0; v < N_TRACKS; v++, p += PARAMS_STRIDE, q += PARAMS_STRIDE) {
        d = q[PARAM_KNOBS + 2 * K_SOLO];
        if (d == SOLO_LOCK_ON || d == SOLO_LOCK_OFF)
            return 0;
        if (p[PARAM_TYPE] == MACHINE_TYPE && p[PARAM_KNOBS + 2 * K_DECAY] < XFADE_TOP)
            return 0;
    }
    for (; v < ANALOG_FIRST + ANALOG_VOICES; v++, q += PARAMS_STRIDE) {
        d = q[PARAM_KNOBS + 2 * K_SOLO_ANALOG];
        if (d == SOLO_LOCK_ON || d == SOLO_LOCK_OFF)
            return 0;
    }
    SOLO_NOW = 0;
    ((u32 *)XFADES)[0] = ((u32 *)XFADES)[1] = 0;
    return 1;
}
#endif

__attribute__((section(".cave.a")))
void *mix_amute(void *a, void *b, u8 *params)
{
#ifdef FAST
    if (quiet(params))
        return ((__typeof__(&mix_link))MIX_FAST)(a, b, params);
#endif
#if defined(ALOCK)
    u32 mute = solo_now(params);
    u32 v;

    mute = (mute ? ~mute : MUTES[0] | *PATTERN_MUTES) >> ANALOG_FIRST;
#elif defined(SLOCK)
    /* The slock image: a sampler track's solo may be a step's own, a lock on slot 17 (engine/sampler.h, SLOCK). This
     * block's solos: the knobs' long, without a digital track that is no sampler, and with every sampler track as the
     * mark its playing step left says. Kept for the mixer link, which this routine calls. */
    u32 mute = SOLO_WORD, d;
    u32 v;

    for (v = 0; v < N_TRACKS; v++)
        if (params[PARAMS_STRIDE * v + PARAM_TYPE] != MACHINE_TYPE)
            mute &= ~(1u << v);
        else if ((d = (params - WORDS_BACK)[PARAMS_STRIDE * v + PARAM_KNOBS + 2 * K_SOLO]) == SOLO_LOCK_ON)
            mute |= 1u << v;
        else if (d == SOLO_LOCK_OFF)
            mute &= ~(1u << v);
    SOLO_NOW = mute;
    mute = (mute ? ~mute : MUTES[0] | *PATTERN_MUTES) >> ANALOG_FIRST;
#elif defined(SOLOKNOB)     /* (the soloknob image: a solo is the sampling page's, and with any no mute counts; engine/mixlink.c) */
    u32 mute = (SOLO_WORD ? ~SOLO_WORD : MUTES[0] | *PATTERN_MUTES) >> ANALOG_FIRST;
#else
    u32 mute = ((MUTES[1] ? ~MUTES[1] : MUTES[0]) | *PATTERN_MUTES) >> ANALOG_FIRST;
#endif
#ifndef SLOCK
    u32 v;
#endif
#ifdef XKNOB
    xf_knobs(params);
#endif
#ifdef APAGE
    /* The apage image: an analog track has the crossfade's knob too (twelve numbers, XFADES), so its voice is turned
     * down by the largest of the other eleven: the largest of all, and for the track that holds it the next one. */
    u32 top = 0, next = 0, who = 0, x;

    if (XFADE_ANY) {
        for (v = 0; v < ANALOG_FIRST + ANALOG_VOICES; v++)
            if ((x = XFADES[v]) > top) {
                next = top;
                top = x;
                who = v;
            } else if (x > next) {
                next = x;
            }
    }
#ifdef XMUTE
    mute &= ~heard(top, who);
#endif
    for (v = 0; v < ANALOG_VOICES; v++) {
        x = ANALOG_FIRST + v == who ? next : top;
        x = (XFADE_TOP - x) * (XFADE_TOP - x);
        if (mute & (1u << v)) {
            CONTROL[v] = 0;
            CONTROL[RIGHT + v] = 0;
        } else if (x != XFADE_TOP * XFADE_TOP) {
            CONTROL[v] = BY_TOP2((u32)CONTROL[v] * x);
            CONTROL[RIGHT + v] = BY_TOP2((u32)CONTROL[RIGHT + v] * x);
        }
    }
#elif defined(XFADE)
    /* The xfade image: an analog track has no crossfade of its own, so it is turned down by the largest of the eight
     * (XFADES, engine/sampler.h). Stock makes a level word of the volume squared (0x40090084), so the word is made
     * (127 - x) / 127 squared of what it was: what the volume the mixer link shows would have given. */
    u32 top = 0, x;

    if (XFADE_ANY)
        for (v = 0; v < N_TRACKS; v++)
            if ((x = XFADES[v]) > top)
                top = x;
    top = (XFADE_TOP - top) * (XFADE_TOP - top);
    for (v = 0; v < ANALOG_VOICES; v++)
        if (mute & (1u << v)) {
            CONTROL[v] = 0;
            CONTROL[RIGHT + v] = 0;
        } else if (top != XFADE_TOP * XFADE_TOP) {
            CONTROL[v] = BY_TOP2((u32)CONTROL[v] * top);
            CONTROL[RIGHT + v] = BY_TOP2((u32)CONTROL[RIGHT + v] * top);
        }
#else

    for (v = 0; v < ANALOG_VOICES; v++)
        if (mute & (1u << v)) {
            CONTROL[v] = 0;
            CONTROL[RIGHT + v] = 0;
        }
#endif
    return ((__typeof__(&mix_link))MIX_NEXT)(a, b, params);
}
