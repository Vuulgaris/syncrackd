/* Main CPU (section 3, OS 1.42 only): what SMPL, LOOP and MODE read on screen.
 * The "screen" image only.
 *
 * A knob's value is turned into text by a function object in the display table
 * (tools/uitable.py), called as (the object, the value in 8.8, where to write).
 * Stock has one for the sample selectors: it shows the name of the slot the knob
 * is on, or NO SAMPLE. It does not know MODE, so with a stereo sample on slots
 * 2n-1 and 2n it shows slot n.
 *
 * knob_text takes that function's place in its object, and the build points
 * LOOP's and MODE's text at the same object. Which knob it is asked about it
 * reads from the object's address: the copy in the table's entry for the record.
 *
 *   SMPL  when MODE counts stereo samples (PAIRS): the name of the left slot,
 *         2n-1, through the stock function, without a last " L", "_L", "-L" or
 *         ".L". Past 32 there is no stereo sample: NO SAMPLE. Otherwise stock's
 *         text, untouched.
 *   LOOP  OFF, FWD, PING.
 *   MODE  MONO, STEREO, REC MAIN, REC EXT, CHAIN, ST CHAIN.
 *         Built with PAGE (the page image), where MODE's value is three switches
 *         and record and its source have knobs on the sampling page: MONO or
 *         STEREO, from the value's lowest bit, whatever the others say.
 *         Built with METER too (the meter image), where the source is a number
 *         in the same value: the same two words, up to 63.
 *
 * MODE is read the way the page reads any knob it draws: the manager's routine
 * gives the object that holds the active track's values, and that object's
 * method gives the value (the page's own getter, 0x40037f40 on, does the same
 * with the record it is drawing).
 *
 * An object that is not one of the table's, or a value out of range, gets what
 * stock would have shown: the slot's name, or the number.
 *
 * Built with AUTO (the mode image) SMPL always counts the 32 samples, whatever MODE
 * says: a sample is mono or stereo by what its slots hold (engine/sampler.h), and a
 * mono one is its first slot. MODE has no knob on the first page there.
 *
 * Built with PACK (the pack image) SMPL past 32 is no longer nothing: 33 to 64 are the
 * slots of those numbers, each a mono sample, and read the slot's own name, whole.
 */
#define RECORDER
#include "sampler.h"

#define TEXT0 0x41ba0a38u           /* the display table's first text object: the table + 0x14 */
#define STRIDE 84u
#define R_SMPL 498u                 /* descriptor records of machine 44 */
#define R_LOOP 501u
#define R_MODE 502u
#define R_DEC 504u                  /* the xknob image: the crossfade's */
#define manager ((void *(*)(void))0x4016e9c8)
#define holder ((void *(*)(void *, u32, s32))0x4001c422)    /* (manager, record, track; -1 the active one) */
#define VALUE 40                    /* in a holder's method table: (holder, record) -> the value, 8.8 */
#define slot_text ((void (*)(void *, s32, char *))0x4007ba80)

#define CAVE __attribute__((section(".cave.t"), noinline))

/* The words, in the cave with the code: rows of 10 for MODE, rows of 5 for LOOP. */
__asm__(".section .cave.t,\"ax\",@progbits\n"
        "mode_words: .asciz \"MONO\\0\\0\\0\\0\\0\"\n"
        "            .asciz \"STEREO\\0\\0\\0\"\n"
        "            .asciz \"REC MAIN\\0\"\n"
        "            .asciz \"REC EXT\\0\\0\"\n"
        "            .asciz \"CHAIN\\0\\0\\0\\0\"\n"
        "            .asciz \"ST CHAIN\\0\"\n"
        "loop_words: .asciz \"OFF\\0\"\n"
        "            .asciz \"FWD\\0\"\n"
        "            .asciz \"PING\"\n"
        "no_sample:  .asciz \"NO SAMPLE\"\n"
        "            .even\n"
        "            .text\n");
extern const char mode_words[], loop_words[], no_sample[];

CAVE static void put(char *out, const char *s)
{
    while ((*out++ = *s++))
        ;
}

#if !defined(AUTO) || defined(XSHARE)   /* (the mode image: SMPL always counts the 32 samples, and MODE is not asked) */
/* The active track's value for a record, as the page would draw it. */
CAVE static s32 knob(u32 record)
{
    void *h = holder(manager(), record, -1);

    if (!h)
        return 0;
    return (*(s32 (**)(void *, u32))(*(u8 **)h + VALUE))(h, record);
}
#endif

#ifdef XSHARE
#ifndef XFADES                      /* (sampler.h has these behind other images' names) */
#define XFADES ((volatile u8 *)0x400a292c)
#endif
#ifndef XFADE_TOP
#define XFADE_TOP 127u
#endif
/* The xshare image: the pattern's one crossfade, as every track's knob D shows it: the largest of the twelve numbers,
 * which the analog mute makes every block from the sampler tracks' knob D and the analog tracks' own. */
CAVE static u32 xf_shared(void)
{
    u32 t, x = 0;

    for (t = 0; t < 12; t++)
        if (XFADES[t] > x)
            x = XFADES[t];
    return x;
}
#endif

CAVE void knob_text(void *object, s32 value, char *out)
{
    u32 at = (u32)object - TEXT0;
    u32 record = at % STRIDE ? R_SMPL : at / STRIDE;
    u32 v = (u32)value >> 8;

#ifdef XKNOB
    if (record == R_DEC) {                  /* the xknob image: the crossfade, 127 less DEC's slot (engine/recpage.c) */
        char *o = out;

#ifdef XSHARE
        if ((u32)knob(R_DEC) >> 8 == v)     /* the track's own, not a held step's lock: the pattern's crossfade */
            v = XFADE_TOP - xf_shared();
#endif
        v = v >= 127 ? 0 : 127 - v;
        *o++ = 'X';
        *o++ = 'F';
        if (v > 99)
            *o++ = '0' + v / 100;
        if (v > 9)
            *o++ = '0' + v / 10 % 10;
        *o++ = '0' + v % 10;
        *o = 0;
        return;
    }
#endif
#if defined(METER)
    if (record == R_MODE && v < 64) {       /* the meter image: the source is a number above the two switches */
        put(out, mode_words + 10 * (v & 1));
#elif defined(PAGE)
    if (record == R_MODE && v < 8) {
        put(out, mode_words + 10 * (v & 1));
#else
    if (record == R_MODE && v < 6) {
        put(out, mode_words + 10 * v);
#endif
    } else if (record == R_LOOP && v < 3) {
        put(out, loop_words + 5 * v);
    } else if (record == R_MODE || record == R_LOOP) {
        char *o = out;                      /* not a value the knob can have: the number */

        v &= 0xff;
        if (v > 99)
            *o++ = '0' + v / 100;
        if (v > 9)
            *o++ = '0' + v / 10 % 10;
        *o++ = '0' + v % 10;
        *o = 0;
    } else if (PAIRS((u32)knob(R_MODE) >> 8)) {
        u32 n = v > 63 ? v - 63 : 64 - v;   /* 1..64, as stock counts either half of the knob */
        char *e = out;

        if (n > N_SLOTS / 2) {
#ifdef PACK
            slot_text(object, (s32)((n + 63) << 8), out);   /* the pack image: a single slot of the back half, by its own number, and its name whole */
#else
            put(out, no_sample);
#endif
            return;
        }
        slot_text(object, (s32)((2 * n + 62) << 8), out);   /* the value that is slot 2n-1 in mono */
        while (*e)
            e++;
        if (e - out > 2 && (e[-1] | 0x20) == 'l'
            && (e[-2] == ' ' || e[-2] == '_' || e[-2] == '-' || e[-2] == '.'))
            e[-2] = 0;
    } else {
        slot_text(object, value, out);
    }
}
