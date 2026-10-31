/* Main CPU (section 3, OS 1.42 only): the long image, 128 steps as two patterns played as one.
 *
 * Patterns 1..64 are long, 65..128 are only their tails. Stock plays from a queue of 24-byte entries, (pattern data,
 * kit, ...), looping (docs/FINDINGS.md, "128 steps as two patterns played as one"). Every cue of a pattern goes
 * through the routine that sets that queue; ours calls it and then puts, after each entry of a head, an entry of its
 * tail with the head's kit. So n plays, then n + 64, then n.
 *
 * The UI's kit is pointed at the playing pattern's own kit when the pattern changes (0x40019c84, by the number
 * 0x400c2154 gives). Ours gives the head's number while a tail plays with the head's kit, so a knob turned in the
 * second half is heard. A tail cued by hand plays with its own kit and is left as stock's. */
typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;
typedef signed char s8;

#define queue_set ((void (*)(u8 *, s32))0x4008c51c)          /* (list, count): stock's, copies them in */
#define playing_number ((s32 (*)(void *))0x400c2154)         /* (ignored) -> the playing pattern's number, 0..127 */
#define QUEUE ((u8 *)0x43bcc3bc)                             /* entries of 24 bytes */
#define QUEUE_COUNT (*(volatile s32 *)0x43bcc3b8)
#define QUEUE_MAX 2048
#define ENTRY 24
#define PATTERN_DATA 136076                                   /* a pattern's data, one after another */
#define PATTERN_NUMBER 136072                                 /* in it: the pattern's number */
#define PATTERNS 0x40a39b34u                                 /* pattern n's data at PATTERNS + 136076 n */
#define KITS 0x41ad6134u                                      /* kit n at KITS + 5656 n */
#define KIT_SIZE 5656
#define PLAYING_KIT (*(volatile u32 *)0x43bd843c)             /* the kit the sequencer plays from */
#define HALF 64

#define LONG __attribute__((section(".cave.l")))

LONG static s32 number_of(u32 data)
{
    return *(s32 *)(data + PATTERN_NUMBER);
}

/* a head's entry: its tail's data, or 0 */
LONG static u32 tail_of(const u8 *e)
{
    u32 data = *(const u32 *)e;
    s32 n;

    if (!data)
        return 0;
    n = number_of(data);
    if (n < 0 || n >= HALF)
        return 0;
    data += HALF * PATTERN_DATA;
    return number_of(data) == n + HALF ? data : 0;
}

LONG static void copy_entry(u8 *to, const u8 *from)
{
    u32 *t = (u32 *)to;
    const u32 *f = (const u32 *)from;
    int k;

    for (k = 0; k < ENTRY / 4; k++)
        t[k] = f[k];
}

__attribute__((section(".cave.l"), noinline)) void long_queue(u8 *list, s32 count)
{
    s32 n, extra, i, j;
    u32 tail;
    unsigned short sr;

    queue_set(list, count);
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    n = QUEUE_COUNT;
    extra = 0;
    for (i = 0; i < n; i++)
        if (tail_of(QUEUE + i * ENTRY))
            extra++;
    if (extra && n + extra <= QUEUE_MAX) {
        j = n + extra - 1;
        for (i = n - 1; i >= 0; i--) {
            tail = tail_of(QUEUE + i * ENTRY);
            if (tail) {
                copy_entry(QUEUE + j * ENTRY, QUEUE + i * ENTRY);
                *(u32 *)(QUEUE + j * ENTRY) = tail;
                j--;
            }
            if (j != i)
                copy_entry(QUEUE + j * ENTRY, QUEUE + i * ENTRY);
            j--;
        }
        QUEUE_COUNT = n + extra;
    }
    __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory");
}

__attribute__((section(".cave.l"), noinline)) s32 long_kitnum(void *any)
{
    s32 n = playing_number(any);

    if (n >= HALF && PLAYING_KIT == KITS + (u32)(n - HALF) * KIT_SIZE)
        return n - HALF;
    return n;
}

/* Live record asks the sequencer for a hit's step (0x4008dae6(time, track, out)): out[0] the nearer step, out[1] the
 * micro timing, out[2] the number of the pattern that step belongs to, the next one's when the next step is nearer at
 * a pattern's end. Stock drops out[2]: the trig is written later, by the main task (0x4001ecb6), into whatever
 * pattern plays by then. A hit just before step 65 went to n's step 1, one just before the loop's start to the
 * tail's. Here a hit whose pattern is of the playing pair carries its half in the step's byte (bit 6: a half is
 * given, bit 7: the tail; stock's step is 0..63), and the writer is pointed at that half of the pair playing. */
#define step_of_hit ((void (*)(u32, s32, s8 *))0x4008dae6)    /* (time, track, out) */
#define write_live ((void (*)(s32, s32, s32, s32, s32, s32, s32, s32, s32, s32))0x4001ecb6)
#define now_pattern ((u32 (*)(u32))0x40019000)               /* (manager) -> the selected pattern's object */
#define PATTERN_OBJECTS 13204                                 /* manager + 13204 + 1664 n */
#define PATTERN_OBJECT 1664
#define GIVEN 0x40
#define TAIL 0x80
#define SEAMRUN __attribute__((section(".cave.m")))

__attribute__((section(".cave.n"))) static s32 long_target = -1;     /* the run's last long */

SEAMRUN __attribute__((noinline)) void long_when(u32 time, s32 track, s8 *out)
{
    s32 to, now;

    step_of_hit(time, track, out);
    to = (u8)out[2];
    now = playing_number(0);
    if (out[0] >= 0 && out[0] < HALF && to < 2 * HALF && now >= 0 && to % HALF == now % HALF)
        out[0] = (s8)(out[0] | GIVEN | (to >= HALF ? TAIL : 0));
}

SEAMRUN __attribute__((noinline)) void long_rec(s32 manager, s32 track, s32 a, s32 b, s32 c, s32 step, s32 micro, s32 d, s32 e, s32 f)
{
    s32 v = step & 0xff, now;

    if (v & GIVEN) {
        now = playing_number(0);
        if (now >= 0)
            long_target = now % HALF + (v & TAIL ? HALF : 0);
        step = v & (HALF - 1);
    }
    write_live(manager, track, a, b, c, step, micro, d, e, f);
    long_target = -1;
}

LONG __attribute__((noinline)) u32 long_now(u32 manager)
{
    if (long_target >= 0)
        return manager + PATTERN_OBJECTS + (u32)long_target * PATTERN_OBJECT;
    return now_pattern(manager);
}

LONG __attribute__((noinline)) s32 long_num(void *any)
{
    return long_target >= 0 ? long_target : playing_number(any);
}

/* Stock's clear (0x4001f7c0) and paste (0x4001fa0e) take a list of pattern numbers, a vector (begin, end). Ours give
 * stock the list with each head's tail after it, so the undo, the clear, the paste and the message take the tails
 * too. Stock's copy (0x4001e2a8) keeps one pattern and its kit; ours keeps the tail's data beside it, and a paste
 * puts that on each head's tail where stock had put the head's, its number its own. A copy of a tail, or of anything
 * that is not a head, forgets the kept tail: pasting it is stock's. */
#define clear_patterns ((void (*)(u32, s32 **, s32, s32, s32))0x4001f7c0)    /* (manager, list, sequence, kit, undo) */
#define paste_patterns ((void (*)(u32, s32 **, s32))0x4001fa0e)              /* (manager, list, undo) */
#define copy_pattern ((u32 (*)(u32, s32))0x4001e2a8)                         /* (manager, n) -> a byte, true when copied */
#define allocate ((u8 *(*)(u32))0x4010394c)
#define copy_bytes ((void (*)(void *, const void *, u32))0x4011613c)       /* (to, from, count) */
#define EDITRUN __attribute__((section(".cave.p")))
#define LIST_MAX 256

typedef struct { u8 *data; s32 from; } kept_t;
__attribute__((section(".cave.q"))) static kept_t kept = { 0, -1 };     /* the run's last two longs */

/* list -> list with the tails, in buf; the vector's begin and end */
EDITRUN __attribute__((noinline)) static void with_tails(s32 **list, s32 *buf, s32 **v)
{
    s32 *p, n = 0, k, t;

    for (p = list[0]; p < list[1] && n < LIST_MAX; p++)
        buf[n++] = *p;
    for (p = list[0]; p < list[1] && n < LIST_MAX; p++) {
        if (*p < 0 || *p >= HALF)
            continue;
        t = *p + HALF;
        for (k = 0; k < n && buf[k] != t; k++)
            ;
        if (k == n)
            buf[n++] = t;
    }
    v[0] = buf;
    v[1] = buf + n;
    v[2] = buf + n;
}

EDITRUN __attribute__((noinline)) void long_clear(u32 manager, s32 **list, s32 seq, s32 kit, s32 undo)
{
    s32 buf[LIST_MAX], *v[3];

    with_tails(list, buf, v);
    clear_patterns(manager, v, seq, kit, undo);
}

EDITRUN __attribute__((noinline)) u32 long_copy(u32 manager, s32 n)
{
    u32 r = copy_pattern(manager, n);

    kept.from = -1;
    if ((r & 0xff) && n >= 0 && n < HALF) {
        if (!kept.data)
            kept.data = allocate(PATTERN_DATA);
        if (kept.data) {
            copy_bytes(kept.data, (const void *)(PATTERNS + (u32)(n + HALF) * PATTERN_DATA), PATTERN_DATA);
            kept.from = n;
        }
    }
    return r;
}

__attribute__((section(".cave.r"), noinline)) void long_paste(u32 manager, s32 **list, s32 undo)
{
    s32 buf[LIST_MAX], *v[3], *p, t;
    u32 obj;

    if (kept.from < 0) {
        paste_patterns(manager, list, undo);
        return;
    }
    with_tails(list, buf, v);
    paste_patterns(manager, v, undo);
    for (p = list[0]; p < list[1]; p++) {
        if (*p < 0 || *p >= HALF)
            continue;
        t = *p + HALF;
        copy_bytes((void *)(PATTERNS + (u32)t * PATTERN_DATA), kept.data, PATTERN_DATA);
        *(s32 *)(PATTERNS + (u32)t * PATTERN_DATA + PATTERN_NUMBER) = t;
        obj = manager + PATTERN_OBJECTS + (u32)t * PATTERN_OBJECT;
        (*(void (**)(u32, s32))(*(u32 *)obj + 16))(obj, 0);       /* the pattern's own "changed", as stock's paste calls it */
    }
}
