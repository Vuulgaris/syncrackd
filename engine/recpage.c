/* Main CPU (section 3, OS 1.42 only): the sampling page, a second page behind SYN
 * on a sampler track. The "page" image only.
 *
 * Every track key has a page object that holds a list of page numbers and the
 * index of the one showing; a second press of the key steps to the next (stock:
 * FLTR, AMP and LFO have two). One object serves SYN for all audio tracks, built
 * with a list of one, page 6. The build gives it the list below instead: page 6
 * twice, so nothing that reads the page number sees a number stock does not know.
 *
 * Three methods of the SYN page class go through here first:
 *
 *   syn_knob (+ 188, "which record is behind knob k"): sets the list's length
 *     from the track, two pages on a sampler and one on any other machine, and
 *     on a sampler's second page answers "no record" for each of the eight
 *     knobs. Stock then draws an empty box in the knob's place and its own knob
 *     routine leaves it alone. Knob 8 is LEVEL: it stays stock's on every page.
 *   syn_draw (+ 16): lets stock draw, then on the second page writes our places:
 *     a value in the box and a name under it, where stock puts a knob's.
 *   syn_turn (a turn of a knob): on the second page the eight knobs are ours.
 *     Anything else, LEVEL included, goes to stock. A turn does not come through
 *     the class's own table (+ 68) but through the table of a second base class
 *     at + 4 of the object, whose entry takes 4 off the object's address and
 *     jumps to the routine: syn_turn_side takes that entry's place. (Seen on the
 *     unit: with only + 68 changed the knobs did nothing.)
 *
 * What the page holds, for the track it is opened on:
 *   SRC   MAIN or EXT: what a take records.
 *   DEST  SMPL, or 01..32: the stereo sample the take goes to. SMPL is the one
 *         the track's own SMPL knob is on, so the take is heard by turning REC off.
 *   REC   OFF or ON. ON puts the track in record: a trig starts a take, the end
 *         of the note ends it, and the track is silent meanwhile.
 *   BANK  (built with BANKS, the bank image) A, B or C: the sample bank this
 *         project is saved with. Not a track's: the project's.
 *
 * REC and SRC are not ours to keep. They are two bits of the track's MODE
 * parameter (engine/sampler.h: 1 stereo, 2 in record, 4 from the external
 * input), read and changed through the stock methods, the ones the stock knob
 * routine uses. So they are saved with the pattern and can be locked to a step
 * like any knob: hold a trig and turn REC. (The maintainer, after a build that kept
 * REC in memory of ours: "we'll need to make it param lockable".) The MODE knob
 * on the first page is taken over for the same reason: it now switches the
 * stereo bit and nothing else, and reads MONO or STEREO.
 *
 * A turn changes one of two things, and stock's knob routine (0x4003b870, from
 * 0x4003ba42 on) has a method for each. While the keys of steps are held (the
 * object at + 108 keeps them as 64 bits at its + 344, and 0x400c3582 asks whether
 * any is inside the pattern) the turn is for those steps: the page's method at
 * + 156, which marks the keys object "edited" (0x400c2de0), takes the held steps
 * one by one, and tidies up (0x400c2ede). For each step it asks + 144 for the
 * step's lock; with one it moves it (+ 152), without it makes one at the track's
 * value (+ 148) and applies no change that time. With no step held the turn is
 * the track's own (+ 88). flip() below does the same with the same methods, but
 * works out each step's change from that step's own value, since ours is a
 * switch and not a count, and makes a new lock at the value wanted.
 *
 * (Stock asks one thing before those two: state 0x12 with the keys object
 * already "edited" sends the turn to + 96, which goes over every step with a
 * trig among the sixteen on show. What that is for was not found. Two builds
 * leaned on + 96 and on that test, and on the unit a held trig locked nothing:
 * the first never reached the track's value, the second left held steps alone.)
 *
 * A plain turn also gets stock's own pop-up, "name=value" (the maintainer missed
 * MODE's when the knob became ours).
 *
 * Built with RECLOCK (the reclock image) a step's REC is no longer a lock of
 * MODE. That locked the whole parameter, the stereo switch and the source with
 * it as they stood: the maintainer, "moving rec on the sampling page to param lock it
 * also param locks mode, and also mode is just getting param lock'd strangely".
 * A lock is kept for a knob slot of a track, 71 of them, with or without a
 * record (the holder's + 64, + 68 and + 72 look the record's slot up and go on
 * to three routines of the steps object that take the slot). So REC with a step
 * held makes, or takes away, a lock on slot 24, which no knob of a digital track
 * uses, at one of two values the sound engine and the feed know
 * (engine/sampler.h, REC_ON). It is taken away, not set, when the step is to do
 * what the track does: a lock is there only where a step differs. SRC is the
 * track's alone now. The MODE knob can still be locked: its lock carries the
 * track's REC and SRC bits, so a turn of the track's REC or SRC writes them into
 * every lock of MODE the track has (sync). And a track that is no sampler any
 * more loses what REC locks it has (strays): on any other digital machine the
 * slot is the envelope's hold flag.
 *
 * Built with METER (the meter image) SRC is a number and not a switch: MAIN, EXT,
 * T1..T12, FX, DELRV (engine/sampler.h, SRC_OF). It is still the track's alone and
 * still in MODE's value, so sync() carries it into MODE's locks as it did the
 * switch. And the page draws a level meter: a bar two dots high along the bottom of
 * the screen, under the lower row of places, which this page leaves empty. Its
 * length is the level the feed keeps (engine/recfeed.c) for the source this track
 * records, ten dots to every halving, full at the largest sample a take can hold;
 * a dot past its end marks that. Each drawing tells the feed which source, and
 * that the page is on show, and the feed asks for the next drawing.
 *
 * Built with SAVE (the save image) the fifth place, the first of the lower row, is
 * SAVE. It has no name under it, where the meter's bar is: its box reads SAVE, and a
 * turn to the right starts a save of the takes that are not on the drive yet, the
 * takes alone and not the project (engine/keeptakes.c, save_start). The box reads
 * BUSY while the job runs and DONE or FAIL after it; the meter's drawings bring the
 * word up to date. A turn to the left puts SAVE back.
 *
 * Built with PTN too (the ptn image) there is no SAVE: the takes are written when a whole pattern
 * is saved to the project. The fifth place is empty and its knob turns nothing; FAIL is written
 * where its value went after a save that did not get every take onto the drive, until one does.
 *
 * Built with FEED too (the feed image) FAIL is gone as well: the fifth place is empty whatever a save
 * did. On request. And a drawing asks which
 * step is held once where it asked three times.
 *
 * Built with AUTO (the mode image) MODE's lowest bit is no longer how a track plays: a sample is
 * mono or stereo by what its slots hold (engine/sampler.h). The bit says what a take is, and its
 * knob is here, with the other things a take is made by: the lower row's third place, MONO or STER.
 * The first page's sixth place is empty. It is the track's alone, like SRC, and is written into
 * every lock of MODE the track has with the other two.
 *
 * Built with PEAK (the same image, for now): the audio CPU's load in the lower row's last place,
 * P and the most of the last ten seconds or so in hundredths of a block, as the time image has it
 * (engine/sampler.h, TIMED). On request
 * .
 *
 * Built with STOPS (the stops image) a turn of SMPL on the first page is ours too: it stops only at
 * the places that are a sample, or the one free spot of either kind, by what the audio CPU says each
 * slot holds (engine/sampler.h, STOPS). The change is made the way stock's knob routine makes one,
 * through the page's own methods, as MODE's bits are above: the track's value and the pop-up, or
 * with steps held a lock a step, made at the track's value the first time and moved after, as
 * stock's own routine for a held step has it. While the audio CPU has not said, the turn is stock's.
 * The turn's two entries are the image's own (stops_turn, stops_turn_side), in two more runs, and hand
 * everything else to the routines below as they are.
 *
 * DEST has no bit to live in. It is kept for each of the eight tracks in 32
 * bytes the build adds to the end of the page object, not saved, and written to
 * struct recbox in the window shared with the audio CPU (engine/sampler.h), in
 * words, the marks last: the audio CPU reads it there when a take starts.
 *
 * The stock draw asks syn_knob for each knob before anything of ours runs, so
 * the list and the index are settled when syn_draw and syn_turn look at them.
 */
#define RECORDER
#define PAGE
#include "sampler.h"

struct page {                   /* a track page object: the fields used here */
    u8 other[104];
    void *mgr;                  /* + 104: the manager */
    void *keys;                 /* + 108: says whether steps are held or selected */
    u8 pad[4];
    void *tracks;               /* + 116: gives the active track */
    void *kit;                  /* + 120: gives a track's machine */
    u32 *first, *last;          /* + 124, + 128: the page numbers, as a vector's begin and end */
    u8 more[12];
    u32 index;                  /* + 144: the one showing */
};

struct event {                  /* a turn of a knob */
    u8 other[12];
    u32 id;                     /* 1..8 the eight knobs, 9 LEVEL */
    s32 steps;
};

struct state {                  /* ours: in the bytes the build adds after the object's own 0x1ac */
    u32 mark;                   /* MARK once the rest has been set: the memory comes as it is */
    u8 dest[8];                 /* track t's DEST: 0 SMPL, 1..32 a stereo sample */
};
#define STATE(p) ((struct state *)((u8 *)(p) + 0x1ac))
#define MARK 0x53414d33u

#define active_track ((u32 (*)(void *))0x4001ff74)
#define machine_of ((s32 (*)(void *, u32))0x4000f692)
#define stock_knob ((u32 (*)(struct page *, u32))0x40044c54)
#define stock_draw ((void (*)(struct page *, void *))0x40030b84)
#define stock_turn ((u32 (*)(struct page *, struct event *))0x40030070)
#define redraw ((void (*)(struct page *))0x400ffe22)
#define text ((void (*)(void *, void *, s32, s32, s32, const char *, ...))0x400f8bd0)
#define FONT ((void *)0x443db230)       /* the one stock writes a knob's name in */
#define FIVE ((const char *)0x4024e6be) /* "%.5s", stock's format for it */
#define CENTRED 2
/* and a change to it, the way the stock knob routine makes one. In the page's method table: */
#define GET 84                  /* (page, record, what STEP_ARG gave, or -1) -> the value in 8.8, without locks */
#define PLAIN 88                /* (page, record, change in 8.8, 0, a byte for its answer): the track's value */
#define STEP_LOCK 144           /* (page, step, record) -> the step's lock, negative: none */
#define STEP_MAKE 148           /* (page, step, record, value): a lock at that value */
#define STEP_MOVE 152           /* (page, step, record, change, 0, a byte for its answer): the lock moves */
#define STEP_ARG 164            /* (page, step) -> what GET is asked with for that step */
#define METHOD(o, n, type) (*(type *)(*(u8 **)(o) + (n)))
struct page;
typedef s32 (*get_fn)(struct page *, u32, s32);
typedef void (*plain_fn)(struct page *, u32, s32, u32, u8 *);
typedef s32 (*step_lock_fn)(struct page *, u32, u32);
typedef u32 (*step_make_fn)(struct page *, u32, u32, s32);
typedef u32 (*step_move_fn)(struct page *, u32, u32, s32, u32, u8 *);
typedef s32 (*step_arg_fn)(struct page *, u32);
#define HELD 344                /* in the keys object: 64 bits, the high long first, a step's bit set while its key is held */
#define editing ((void (*)(void *, u32))0x400c2de0)     /* (keys, 1): a turn has gone to held steps */
#define edited ((void (*)(void *))0x400c2ede)           /* (keys): and is done */
#define pattern ((void *(*)(void *))0x40019036)         /* (manager) -> the steps */
#define length ((u32 (*)(void *))0x40027f3a)            /* (steps) -> how many */
/* the pop-up a plain turn gets */
#define popups ((s32 (*)(void *))0x400205f8)            /* (tracks) -> 1: none are shown */
#define record_name ((const char *(*)(void *, u32))0x40012b24)   /* (anything, record) -> its short name */
#define text_for ((const char *(*)(u32, s32))0x4007bbe2)         /* (record, value) -> the value as the knob shows it */
#define popup ((void (*)(void *, const char *, const char *, const char *))0x400c347c)   /* (keys, format, ...) */
#define POPUP ((const char *)0x4024e714)                /* "%s=%s" */
#define R_MODE 502u             /* machine 44's MODE */
#define MODE_KNOB 5u            /* where MODE sits on the sampler's own page */
#ifdef RECLOCK
/* a lock by its knob slot, as the holder's methods end up: all of the steps object, the one length() takes */
#define lock_read ((s32 (*)(void *, u32, u32))0x4002740c)       /* (steps, step, slot) -> the lock, negative: none */
#define lock_make ((u32 (*)(void *, u32, u32, s32))0x40027fa2)  /* (steps, step, slot, value) */
#define lock_drop ((u32 (*)(void *, u32, u32))0x40027fe8)       /* (steps, step, slot): no lock */
#define has_trig ((u8 (*)(void *, u32))0x4002787c)              /* stock's two questions before it makes a lock, */
#define has_lock_trig ((u8 (*)(void *, u32))0x400278d8)
#define give_trig ((void (*)(void *, u32, u32))0x40029faa)      /* and what it does with a step that passes neither */
#define MIDI_MACHINE 35         /* what machine_of answers for a digital track that plays MIDI */
#endif

#ifdef GAINUP
/* The gainup image: the sampling page's places moved. On request
 * . The gain in D
 * (BANK's, empty since the pbank image), the peak and its PROF switch in E, STRC in G; F empty. The peak's knob is still
 * the one a turn of which is not geared. Older images name the places they had, so their bytes are as they were. */
#define GAIN_AT 3
#define STRC_AT 6
#define PEAK_AT 4
#else
#define GAIN_AT 5
#define STRC_AT 4
#define PEAK_AT 6
#endif

#define CAVE __attribute__((section(".cave.g"), noinline))
#define CAVE2 __attribute__((section(".cave.j"), noinline))    /* a second run: the first is full */
#ifdef METER
#define CAVE3 __attribute__((section(".cave.k"), noinline))    /* a third, for the meter and the sources */
#define rect ((void (*)(void *, s32, s32, s32, s32, s32))0x400f7fb6)    /* (surface, x0, y0, x1, y1, 1 set or 0 clear) */
#endif

__asm__(".section .cave.g,\"ax\",@progbits\n"
        "            .globl syn_pages\n"
        "syn_pages:  .long 6, 6\n"
        "w_src:      .asciz \"SRC\"\n"
        "w_dest:     .asciz \"DEST\"\n"
        "w_main:     .asciz \"MAIN\"\n"
        "w_ext:      .asciz \"EXT\"\n"
        "w_rec:      .asciz \"REC\"\n"
        "w_off:      .asciz \"OFF\"\n"
        "w_on:       .asciz \"ON\"\n"
        "w_smpl:     .asciz \"SMPL\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_src[], w_dest[], w_main[], w_ext[], w_rec[], w_off[], w_on[], w_smpl[];
#ifdef METER
__asm__(".section .cave.k,\"ax\",@progbits\n"
        "w_srcs:     .asciz \"MAIN\\0\"\n"       /* rows of 6: the sources that are not a track */
        "            .asciz \"EXT\\0\\0\"\n"
        "            .asciz \"FX\\0\\0\\0\"\n"
        "            .asciz \"DELRV\"\n"
        "            .text\n");
extern const char w_srcs[];
#endif
#ifdef SOLOKNOB
/* The soloknob image: the fifth place is the track's solo, and its value says what it is. */
__asm__(".section .cave.g,\"ax\",@progbits\n"
        "w_solo:     .asciz \"SOLO\"\n"
        "            .asciz \"S OFF\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_solo[];
#endif
#ifdef ONCE
/* The once image: REC's third setting. */
__asm__(".section .cave.k,\"ax\",@progbits\n"
        "w_once:     .asciz \"ONCE\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_once[];
#endif
#ifdef FEED
/* The feed image: the fifth place says nothing at all, FAIL neither. No word of SAVE's four is left. */
#elif defined(PTN)
/* The ptn image: the takes are written when a whole pattern is saved to the project (engine/keeptakes.c,
 * ptn_keep), and SAVE is gone from the page. One word is left of its four. */
__asm__(".section .cave.k,\"ax\",@progbits\n"
        "w_fail:     .asciz \"FAIL\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_fail[];
#elif defined(SAVE)
__asm__(".section .cave.k,\"ax\",@progbits\n"
        "w_save:     .asciz \"SAVE\"\n"                 /* rows of 5: SAVE_STATE's four values */
        "            .asciz \"BUSY\"\n"
        "            .asciz \"DONE\"\n"
        "            .asciz \"FAIL\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_save[];
#define save_start ((void (*)(void))SAVE_START)        /* engine/keeptakes.c, linked before this */
#endif
#ifdef BANKS
/* The bank image: a fourth place, BANK. It turns the bank this project is to be saved with
 * (BANK_WANT, engine/banks.c) and nothing else: a bank is loaded when a project is, and only then.
 * It reads the loaded bank, A, B or C, and with another one chosen, the two: A>B. */
__asm__(".section .cave.g,\"ax\",@progbits\n"
        "w_bank:     .asciz \"BANK\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_bank[];
#endif

/* The active track if it holds the sampler (0..7: it is a digital machine), or -1. */
CAVE static s32 sampler(struct page *p)
{
    u32 t = active_track(p->tracks);

    return machine_of(p->kit, t) == MACHINE_TYPE ? (s32)(t & 7) : -1;
}

CAVE u32 syn_knob(struct page *p, u32 knob)
{
    u32 s = sampler(p) >= 0;

    p->last = p->first + 1 + s;
    if (!s)
        p->index = 0;
#if defined(SRR)
    else if (p->index && knob < 8)      /* the srr image: the first page's sixth place is the reduction, stock's own knob of MODE's record */
        return 0;
#elif defined(AUTO)
    else if (knob < 8 && (p->index || knob == MODE_KNOB))   /* and MODE has left the first page */
        return 0;
#else
    else if (p->index && knob < 8)
        return 0;
#endif
    return stock_knob(p, knob);
}

#ifdef NEXT
/* The next image (engine/recpage.c, its end): DEST is SMPL or NEXT, and knob C the track's KIND. */
#define CAVE_NX __attribute__((section(".cave.nx1"), noinline))      /* the poll */
#define CAVE_NX2 __attribute__((section(".cave.nx2"), noinline))     /* the page's two places and KIND's turn */
#define CAVE_NX3 __attribute__((section(".cave.nx3"), noinline))     /* the pass over the places */
#define CAVE_NX4 __attribute__((section(".cave.nx4"), noinline))     /* DEST to the box, and a track's KIND */
#define CAVE_NX5 __attribute__((section(".cave.nx5"), noinline))     /* the slots taken */
CAVE_NX4 static void next_tell(volatile struct recbox *b, const u8 *dest);
CAVE_NX2 static void next_places(void *surface, const struct state *s, u32 t);
CAVE_NX2 static void next_kind(u32 t, s32 steps);
#ifdef SKIND
#define CAVE_KS __attribute__((section(".cave.ks"), noinline))
#ifdef DESTNUM
CAVE_KS static u32 dest_moved(u32 d, s32 turn, u32 t);
#endif
CAVE_NX4 static u32 nx_mono(u32 t);
CAVE_KS static u32 kind_stops(u8 *m, u32 t);
#endif
#endif

/* The destinations to where the audio CPU reads them. The marks go last: until
 * both are there, it does not look at the rest. */
CAVE static void tell(const struct state *s)
{
    volatile struct recbox *b = REC_MAIN;
    u32 t;

#ifdef NEXT
    (void)t;
    next_tell(b, s->dest);              /* the next image: a NEXT track's free place */
#else
    for (t = 0; t < 8; t++)
        b->dest[t] = s->dest[t] ? s->dest[t] - 1u : DEST_SMPL;
#endif
    b->mark = REC_MARK;
    b->mark2 = ~REC_MARK;
}

CAVE static struct state *state(struct page *p)
{
    struct state *s = STATE(p);
    u32 t;

    if (s->mark != MARK) {
        s->mark = MARK;
        for (t = 0; t < 8; t++)
            s->dest[t] = 0;
        tell(s);
    }
    return s;
}

/* The next step whose key is held, from `from` on and inside the pattern, or -1. */
CAVE2 static s32 held(struct page *p, u32 from)
{
    const u32 *bits = (const u32 *)((const u8 *)p->keys + HELD);
    u32 n = length(pattern(p->mgr));

    for (; from < n && from < 64; from++)
        if (bits[from < 32] >> (from & 31) & 1)
            return (s32)from;
    return -1;
}

#ifdef SRR
/* The srr image: MODE's parameter is the reduction, and the track's REC and SRC are its own word on knob slot 24
 * (engine/sampler.h, SRR), read and written where the sound engine's side reads the kit. Here that word is made
 * MODE's old number, so the page reads the two as it did: 1 (a take at a stereo place is stereo), REC in bit 1, SRC
 * from bit 2. They are the track's alone: a step has no lock of them, and a step's REC is its lock on slot 24. A
 * word that is not signed yet reads as REC off and the main mix; the per-block routine signs it within a block. */
#define CAVE9 __attribute__((section(".cave.u"), noinline))     /* a ninth run, for these three */
CAVE9 static s32 value(struct page *p, s32 step, s32 *lock)
{
    s32 t = sampler(p);
    u32 w = t >= 0 && KIT ? OWN_WORDS(t)[K_REC] : 0;

    (void)step;
    *lock = -1;
    return SRR_SIGNED(w) ? (s32)((SRR_SRC(w) << 2 | SRR_REC(w) << 1 | MODE_STEREO) << 8) : MODE_STEREO << 8;
}

/* And back: MODE's old number, 8.8, to the track's word. */
CAVE9 static void own_put(struct page *p, s32 v)
{
    s32 t = sampler(p);
    u32 m = (u32)v >> 8;

    if (t >= 0 && KIT)
#if defined(NEXT)
        OWN_WORDS(t)[K_REC] = SRR_WORD(SRC_OF(m) & 15u, m >> 1 & 1u)     /* the next image: and KIND stays as it was */
                              | (SRR_SIGNED(OWN_WORDS(t)[K_REC]) ? OWN_WORDS(t)[K_REC] & (SRR_KEYS | SRR_STR | SRR_LOCK | SRR_KIND) : 0);
#elif defined(LOCK)
        OWN_WORDS(t)[K_REC] = SRR_WORD(SRC_OF(m) & 15u, m >> 1 & 1u)     /* the lock image: KEYS's three bits stay as they were */
                              | (SRR_SIGNED(OWN_WORDS(t)[K_REC]) ? OWN_WORDS(t)[K_REC] & (SRR_KEYS | SRR_STR | SRR_LOCK) : 0);
#elif defined(STRETCH)
        OWN_WORDS(t)[K_REC] = SRR_WORD(SRC_OF(m) & 15u, m >> 1 & 1u)     /* the stretch image: KEYS's two bits stay as they were */
                              | (SRR_SIGNED(OWN_WORDS(t)[K_REC]) ? OWN_WORDS(t)[K_REC] & (SRR_KEYS | SRR_STR) : 0);
#elif defined(SLICE)
        OWN_WORDS(t)[K_REC] = SRR_WORD(SRC_OF(m) & 15u, m >> 1 & 1u)     /* the slice image: KEYS stays as it was */
                              | (SRR_SIGNED(OWN_WORDS(t)[K_REC]) ? OWN_WORDS(t)[K_REC] & SRR_KEYS : 0);
#else
        OWN_WORDS(t)[K_REC] = SRR_WORD(SRC_OF(m) & 15u, m >> 1 & 1u);
#endif
}

/* A digital track that holds another machine now: the word the sampler signed goes. */
CAVE9 static void own_clear(u32 t)
{
    if (KIT && SRR_SIGNED(OWN_WORDS(t)[K_REC]))
        OWN_WORDS(t)[K_REC] = 0;
}
#else
/* MODE in 8.8 at a step, and the step's lock or a negative number (step -1: the track's value). */
CAVE2 static s32 value(struct page *p, s32 step, s32 *lock)
{
    s32 v = -1, arg = -1;

    if (step >= 0) {
        v = METHOD(p, STEP_LOCK, step_lock_fn)(p, (u32)step, R_MODE);
        arg = METHOD(p, STEP_ARG, step_arg_fn)(p, (u32)step);
    }
    *lock = v;
    return v < 0 ? METHOD(p, GET, get_fn)(p, R_MODE, arg) : v;
}
#endif

#ifndef FEED    /* (the feed image: the drawing asks for the held step once, and for MODE there with it) */
/* MODE as the page shows it: the first held step's while steps are held, the track's otherwise. */
CAVE2 u32 mode(struct page *p)
{
    s32 lock;

    return (u32)value(p, held(p, 0), &lock) >> 8;
}
#endif

#ifdef RECLOCK
#ifndef ONCE    /* (the once image: once_turn, below, with REC's third setting) */
/* REC on the held steps, from `step` on: a lock on slot 24 where the step is not to do as the track does, none where it is. */
CAVE2 static void rec_steps(struct page *p, s32 step, s32 turn)
{
    void *steps = pattern(p->mgr);
    s32 lock;
    int own = ((u32)value(p, -1, &lock) >> 8 & MODE_REC) != 0;

    editing(p->keys, 1);
    for (; step >= 0; step = held(p, (u32)step + 1)) {
        if ((turn > 0) == own) {
            if (lock_read(steps, (u32)step, K_REC) >= 0)
                lock_drop(steps, (u32)step, K_REC);
            continue;
        }
        if (!has_trig(steps, (u32)step) && !has_lock_trig(steps, (u32)step))
            give_trig(steps, (u32)step, 1);
        lock_make(steps, (u32)step, K_REC, REC_WORD(turn > 0 ? REC_LOCK_ON : REC_LOCK_OFF));
    }
    edited(p->keys);
}
#endif

#ifndef SRR     /* (the srr image: MODE's locks are the reduction's, and nothing of REC or SRC is in them) */
/* The track's REC and SRC bits, as they now are in `own`, into every lock of MODE the track has. */
CAVE static void sync(struct page *p, s32 own)
{
#ifdef AUTO
    s32 keep = (MODE_STEREO | MODE_REC | MODE_SRC) << 8, lock;
#elif defined(METER)
    s32 keep = (MODE_REC | MODE_SRC) << 8, lock;
#else
    s32 keep = (MODE_REC | MODE_EXT) << 8, lock;
#endif
    u8 answer = 0;
    u32 step;

    for (step = 0; step < 64; step++) {
        lock = METHOD(p, STEP_LOCK, step_lock_fn)(p, step, R_MODE);
        if (lock >= 0 && ((lock ^ own) & keep))
            METHOD(p, STEP_MOVE, step_move_fn)(p, step, R_MODE, (own & keep) - (lock & keep), 0, &answer);
    }
}
#endif

/* A digital track that holds another machine now: the REC locks it was left with go. */
#ifdef SAVE
CAVE3 static void strays(struct page *p)    /* in the third run: the first is full again */
#else
CAVE static void strays(struct page *p)
#endif
{
    u32 t = active_track(p->tracks), step, mark;
    void *steps;

    if (t > 7 || machine_of(p->kit, t) == MIDI_MACHINE)     /* an analog track's slot 24, and a MIDI track's, is a knob */
        return;
    steps = pattern(p->mgr);
    for (step = 0; step < 64; step++) {
        mark = (u32)lock_read(steps, step, K_REC) >> 8;
        if (mark == REC_LOCK_ON || mark == REC_LOCK_OFF)
            lock_drop(steps, step, K_REC);
    }
#ifdef SRR
    own_clear(t);                       /* the srr image: and the word the sampler signed there, so a sampler put back starts with REC off */
#endif
}
#endif

/* Switch one bit of MODE on (a turn to the right) or off (to the left): on every held step, or on
 * the track when none is held. name, off and on are for the pop-up; no name: MODE's own, as stock
 * shows it. */
CAVE2 void flip(struct page *p, u32 bit, s32 turn, const char *name, const char *off, const char *on)
{
    s32 mask = (s32)(bit << 8), lock, v, want, step = held(p, 0);
    u8 answer = 0;

    if (!turn)
        return;
#ifdef AUTO
    step = -1;                          /* every bit of MODE is the track's now */
#elif defined(RECLOCK)
    if (bit != MODE_STEREO)             /* REC and SRC here are the track's: a step's REC is rec_steps' */
        step = -1;
#endif
    if (step < 0) {
        v = value(p, -1, &lock);
        want = turn > 0 ? v | mask : v & ~mask;
        if (want == v)
            return;
#ifdef SRR
        (void)answer;
        own_put(p, want);
#else
        METHOD(p, PLAIN, plain_fn)(p, R_MODE, want - v, 0, &answer);
#ifdef AUTO
        sync(p, want);
#elif defined(RECLOCK)
        if (bit != MODE_STEREO)
            sync(p, want);
#endif
#endif
        if (popups(p->tracks) != 1)
            popup(p->keys, POPUP, name ? name : record_name(0, R_MODE),
                  name ? (want & mask ? on : off) : text_for(R_MODE, want));
        return;
    }
    editing(p->keys, 1);
    for (; step >= 0; step = held(p, (u32)step + 1)) {
        v = value(p, step, &lock);
        want = turn > 0 ? v | mask : v & ~mask;
        if (want == v)
            continue;
        if (lock < 0)
            METHOD(p, STEP_MAKE, step_make_fn)(p, (u32)step, R_MODE, want);
        else
            METHOD(p, STEP_MOVE, step_move_fn)(p, (u32)step, R_MODE, want - v, 0, &answer);
    }
    edited(p->keys);
}

#ifdef METER
CAVE2 static u32 moved(u32 v, s32 steps, u32 top);

/* A source's name, five letters at most. */
CAVE3 static void src_name(char *out, u32 src)
{
    const char *w = w_srcs + 6 * (src < SRC_T1 ? src : src - SRC_FX + SRC_T1);
    u32 t = src - SRC_T1 + 1;

    if (src >= SRC_T1 && src < SRC_FX) {
        *out++ = 'T';
        if (t > 9)
            *out++ = '1';
        *out++ = '0' + t % 10;
        *out = 0;
        return;
    }
    while ((*out++ = *w++))
        ;
}

/* A turn of SRC: the track's source moves, a step of the knob a source, and stops at either end. */
CAVE3 static void src_turn(struct page *p, s32 turn)
{
    s32 lock, v = value(p, -1, &lock), want;
    u8 answer = 0;
    char n[6];

    want = (v & ~(s32)(MODE_SRC << 8)) | (s32)(moved(SRC_OF((u32)v >> 8), turn, SRC_TOP) << 10);
    if (want == v)
        return;
#ifdef SRR
    (void)answer;
    own_put(p, want);
#else
    METHOD(p, PLAIN, plain_fn)(p, R_MODE, want - v, 0, &answer);
    sync(p, want);
#endif
    if (popups(p->tracks) != 1) {
        src_name(n, SRC_OF((u32)want >> 8));
        popup(p->keys, POPUP, w_src, n);
    }
}

/* The meter: tell the feed what to watch and that the page is on show, then the bar. A level's
 * place is 16 times the number of its highest bit plus its next four bits, so 16 to a halving,
 * and 8 places are 5 dots. */
CAVE3 static void bar(struct page *p, void *surface, u32 src)
{
    u32 v, e, u;
    s32 dots;

    if (METER_QUIET >= METER_STOP)      /* back on show: what the level was then is nothing now */
        METER_LEVEL = 0;
    METER_SRC = src;
    METER_QUIET = 0;
    METER_PAGE = p;
    v = METER_LEVEL & 0x7fff;
    for (e = 0; v >> (e + 1); e++)
        ;
    u = 16 * e + ((v << 4 >> e) & 15);
    dots = ((s32)(5 * u) - 363) / 8;
    rect(surface, BAR_X, 0, BAR_X + BAR_W - 1, 1, 0);
    if (dots > 0)
        rect(surface, BAR_X, 0, BAR_X + dots - 1, 1, 1);
    rect(surface, BAR_X + BAR_W + 1, 0, BAR_X + BAR_W + 1, 2, 1);
}
#endif

#ifdef FEED
/* The feed image: nothing is drawn in the fifth place, whatever the save's number says. */
#elif defined(PTN)
/* The ptn image: the fifth place is empty, whether the takes are being written or are on the drive, and
 * its knob turns nothing. Where its value went it reads FAIL after a pattern's save whose job did not
 * get every take onto the drive, until one's does. */
CAVE3 static void save_place(void *surface)
{
    if (SAVE_STATE == SAVE_FAIL)
        text(surface, FONT, 33, 12, CENTRED, FIVE, w_fail);
}
#elif defined(SAVE)
/* SAVE's box: the word for how the save is going, where a value goes in the fifth place. */
CAVE3 static void save_place(void *surface)
{
    text(surface, FONT, 33, 12, CENTRED, FIVE, w_save + 5 * (SAVE_STATE & 3));
}

/* A turn of SAVE: to the right a save starts, to the left the word is SAVE again. */
CAVE3 static void save_turn(s32 turn)
{
    if (turn > 0)
        save_start();
    else if (turn < 0 && SAVE_STATE != SAVE_BUSY)
        SAVE_STATE = SAVE_IDLE;
}
#endif

#ifdef GAIN
#define CAVE4 __attribute__((section(".cave.l"), noinline))    /* a fourth run: the third is full too */
static void place(void *surface, u32 k, const char *name, const char *value);

/* The gain image: the record gain of the track the page is opened on, where a value goes in the lower
 * row's second place: 0dB, +1dB to +24dB. No name under it: the meter's bar is there, and the value says
 * what it is. Each drawing tells the meter which gain to show the level with. */
CAVE4 static void gain_place(void *surface, u32 t)
{
    char n[6], *o = n;
    u32 g = REC_GAINS[t];

    METER_GAIN = g;
    if (g)
        *o++ = '+';
    if (g > 9)
        *o++ = '0' + g / 10;
    *o++ = '0' + g % 10;
    *o++ = 'd';
    *o++ = 'B';
    *o = 0;
    place(surface, GAIN_AT, o, n);
}
#endif

#if defined(AUTO) && !defined(XFADE)     /* (the xfade image: the third place is the track's crossfade) */
/* The mode image: what a take is, where a value goes in the lower row's third place. And, while PEAK
 * is built in, the audio CPU's load in its fourth: a letter and three figures, which the audio CPU
 * hands over as a long (engine/sampler.h, TIMED). No names: the meter's bar is there. */
__asm__(".section .cave.l,\"ax\",@progbits\n"
        "w_take:     .asciz \"MONO\"\n"           /* rows of 5 */
        "            .asciz \"STER\"\n"
        "            .text\n");
extern const char w_take[];

CAVE4 static void take_place(void *surface, u32 m)
{
    const char *w = w_take + 5 * (m & MODE_STEREO);
#ifdef PEAK
    u32 n[2];

    n[0] = (TIMED_BOX[1] & 0x1f0f0f0f) | 0x40303030;        /* whatever is there, it is a letter and three figures */
    n[1] = 0;
    place(surface, 7, (const char *)(n + 1), (const char *)n);
#endif
    place(surface, 6, w + 4, w);
}
#endif

#ifdef XFADE
/* The xfade image: the track's crossfade where a value goes in the lower row's third place, XF0 to XF127. No name
 * under it, so the value says what it is. And, while PEAK is built in, the audio CPU's load in the fourth, as the
 * mode image has it. */
#ifdef GFADE
/* The gfade image. On request
 * .
 * The eight numbers hold the one crossfade in the place of the track that last turned it, the rest 0: the mixer's
 * rule (the largest of the other tracks' numbers) is as it was. Every sampling page shows it and turns it. */
__attribute__((section(".cave.q"), noinline)) static u32 xfade_now(void)
{
    u32 i, x, top = 0;

#ifdef APAGE        /* the apage image: twelve, the analog tracks' after the eight */
    for (i = 0; i < 12; i++)
#else
    for (i = 0; i < 8; i++)
#endif
        if ((x = XFADES[i]) > top)
            top = x;
    return top;
}
#endif

#ifdef PROF
/* The prof image: the profile of the main CPU (engine/prof.S) is in every image from here on, and is off until the
 * sampling page's last knob is turned to the right. While it is on, a track whose SRC is the last source takes the
 * profile's record in place of the sends. Not saved: off at every start. */
#define PROF_ON (*(volatile u32 *)PROF_ON_AT)
#endif

#if defined(PEAK) && defined(DMA)
/* The dma image: the audio CPU's load as before, and its letter is how the right channels come (engine/rightdma.c).
 * C: the transfers are being checked against the CPU's reads. H: by the transfers. X: they were given up, and the
 * CPU reads as it did. In the sixth run: the fourth has two bytes left. */
__attribute__((section(".cave.q"), noinline)) static void load_place(void *surface)
{
    u32 w[2];

    w[0] = (TIMED_BOX[1] & 0x000f0f0f) | 0x00303030 | (0x584843u >> 8 * *(const u32 *)0x80007d10) << 24;
#ifdef PROF
    if (PROF_ON)                        /* the prof image: the profile is on, by this box's knob, and the box says so */
        w[0] = 0x50524f46;              /* "PROF" */
#endif
    w[1] = 0;
#ifdef SLICE
    place(surface, PEAK_AT, (const char *)(w + 1), (const char *)w);       /* the slice image: in G's place, H is KEYS */
#else
    place(surface, 7, (const char *)(w + 1), (const char *)w);
#endif
}
#endif

#ifdef SLICE
/* The slice image: knob H is the track's KEYS, CHRO (stock: the keys play the sample's pitch) or SLCE (they play its
 * slices), bit 1 of the track's own word on slot 24 (engine/sampler.h, SLICE). Kept with the kit; not lockable. A
 * word not signed yet is left alone: the per-block routine signs it within a block. */
#define CAVE_SLICE __attribute__((section(".cave.d"), noinline))
__asm__(".section .cave.d,\"ax\",@progbits\n"
        "w_keys:     .asciz \"KEYS\"\n"
        "w_chro:     .asciz \"CHRO\"\n"
        "w_slce:     .asciz \"SLCE\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_keys[], w_chro[], w_slce[];

#if defined(STSW)
/* The stsw image: KEYS is CHRO or SLCE again, and the stretch is knob E's own switch (stsw_turn). The maintainer,
 * 2026-10-23: "instead of having the four key options, wouldn't it be nice if there were just the two and then
 * stretch on and off", and "yes, build it lockable". A word the lock image's fifth build left with bit 4 loses it. */
#define CAVE_STSW __attribute__((section(".cave.e"), noinline))
CAVE_STSW static void keys_turn(u32 t, s32 steps)
{
    u32 w;

    if (!KIT || !steps || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    OWN_WORDS(t)[K_REC] = (w & ~(SRR_KEYS | SRR_LOCK)) | (steps > 0 ? SRR_KEYS : 0);
}

CAVE_STSW static void keys_place(void *surface, u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0;

    place(surface, 7, w_keys, SRR_SIGNED(w) && (w & SRR_KEYS) ? w_slce : w_chro);
}
#elif defined(LOCK)
/* The lock image: KEYS is CHRO, SLCE, CHST or SLST, the last two stretched (bit 3; engine/sampler.h, LOCK); PORT is the
 * lock. Its first five builds had CHLK and SLLK too (bit 4). A step of the knob a setting, in that order. */
#undef CAVE_SLICE
#define CAVE_SLICE __attribute__((section(".cave.i"), noinline))
__asm__(".section .cave.o,\"ax\",@progbits\n"        /* the names in a run of their own (mainmap.CAVE_LOCK2) */
        "w_chst:     .asciz \"CHST\"\n"
        "w_slst:     .asciz \"SLST\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_chst[], w_slst[];

CAVE_SLICE static void keys_turn(u32 t, s32 steps)
{
    u32 w;
    s32 k;

    if (!KIT || !steps || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    k = (w & SRR_KEYS ? 1 : 0) + (w & SRR_STR ? 2 : 0) + (steps > 0 ? 1 : -1);
    k = k < 0 ? 0 : k > 3 ? 3 : k;      /* the sixth build, on request: PORT is the snap, CHLK and SLLK
                                         * are gone, and a word that had the lock loses it here */
    OWN_WORDS(t)[K_REC] = (w & ~(SRR_KEYS | SRR_STR | SRR_LOCK)) | (k & 1 ? SRR_KEYS : 0) | (k >= 2 ? SRR_STR : 0);
    if (k >= 2 && !(w & SRR_STR))
        OWN_WORDS(t)[K_SPEED] = 64 << 8;    /* into a stretch: SPD at the note's own speed, so nothing moves until it is turned */
}

__attribute__((section(".cave.o"), noinline)) static void keys_place(void *surface, u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0;

    if (!SRR_SIGNED(w))
        w = 0;
    place(surface, 7, w_keys, w & SRR_STR ? (w & SRR_KEYS ? w_slst : w_chst) : w & SRR_KEYS ? w_slce : w_chro);
}
#elif defined(STRETCH)
/* The stretch image: KEYS is CHRO, SLCE, CHST or SLST, the last two stretched (bit 3, SRR_STR; engine/sampler.h,
 * STRETCH). A step of the knob a setting, in that order. In a run of its own (mainmap.CAVE_STRETCH). */
#undef CAVE_SLICE
#define CAVE_SLICE __attribute__((section(".cave.i"), noinline))
__asm__(".section .cave.i,\"ax\",@progbits\n"
        "w_chst:     .asciz \"CHST\"\n"
        "w_slst:     .asciz \"SLST\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_chst[], w_slst[];

CAVE_SLICE static void keys_turn(u32 t, s32 steps)
{
    u32 w;
    s32 k;

    if (!KIT || !steps || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    k = (w & SRR_KEYS ? 1 : 0) + (w & SRR_STR ? 2 : 0) + (steps > 0 ? 1 : -1);
    k = k < 0 ? 0 : k > 3 ? 3 : k;
    OWN_WORDS(t)[K_REC] = (w & ~(SRR_KEYS | SRR_STR)) | (k & 1 ? SRR_KEYS : 0) | (k & 2 ? SRR_STR : 0);
    if (k & 2 && !(w & SRR_STR))
        OWN_WORDS(t)[K_SPEED] = 64 << 8;    /* into a stretch: SPD at the note's own speed, so nothing moves until it is turned */
}

CAVE_SLICE static void keys_place(void *surface, u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0;

    if (!SRR_SIGNED(w))
        w = 0;
    place(surface, 7, w_keys, w & SRR_STR ? (w & SRR_KEYS ? w_slst : w_chst) : w & SRR_KEYS ? w_slce : w_chro);
}
#else
CAVE_SLICE static void keys_turn(u32 t, s32 steps)
{
    u32 w;

    if (!KIT || !steps || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    OWN_WORDS(t)[K_REC] = steps > 0 ? w | SRR_KEYS : w & ~SRR_KEYS;
}

CAVE_SLICE static void keys_place(void *surface, u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0;

    place(surface, 7, w_keys, SRR_SIGNED(w) && (w & SRR_KEYS) ? w_slce : w_chro);
}
#endif
#endif

CAVE4 static void xfade_place(void *surface, u32 t)
{
    char n[6], *o = n;
#ifdef GFADE
    u32 x = xfade_now();

    (void)t;
#else
    u32 x = XFADES[t];
#endif
#if defined(AXF)
    /* the axf image: no peak here; the analog tracks' page puts it in H itself (apage_draw), where G was both */
#elif defined(PEAK) && defined(DMA)
    load_place(surface);
#elif defined(PEAK)
    u32 w[2];

    w[0] = (TIMED_BOX[1] & 0x1f0f0f0f) | 0x40303030;        /* whatever is there, it is a letter and three figures */
    w[1] = 0;
    place(surface, 7, (const char *)(w + 1), (const char *)w);
#endif
    *o++ = 'X';
    *o++ = 'F';
    if (x > 99)
        *o++ = '0' + x / 100;
    if (x > 9)
        *o++ = '0' + x / 10 % 10;
    *o++ = '0' + x % 10;
    *o = 0;
    place(surface, 6, o, n);
}
#endif

#ifdef TIMED
/* The time image: the audio CPU's load, as it measured it (engine/sampler.h, TIMED). A letter and
 * three figures, which the audio CPU hands over as a long, where a value goes in the lower row:
 * in its second place and in its third. */
static void place(void *surface, u32 k, const char *name, const char *value);

CAVE3 static void figure(void *surface, u32 k, u32 word)
{
    u32 n[2];

    n[0] = (word & 0x1f0f0f0f) | 0x40303030;    /* whatever is there, it is a letter and three figures */
    n[1] = 0;
    place(surface, k, (const char *)(n + 1), (const char *)n);     /* no name: the bar is where a name would be */
}

/* What the audio CPU says, as it wrote it out: C and the longest stretch of its last 256 blocks in
 * hundredths of a block, then P and the most that has been in the last 5 to 11 seconds. */
CAVE static void timed(void *surface)
{
    figure(surface, 5, TIMED_BOX[0]);
    figure(surface, 6, TIMED_BOX[1]);
}
#endif

#ifdef PROBE
/* The probe image, to see on the unit where a step's REC is lost: two numbers on the lower row,
 * after SAVE. Slot 24 of the track in the block a trig's locks are written into, then the same
 * word in the block the audio CPU is sent and the feed reads. While a step locked on plays, both
 * read 5280. */
#define PROBE_WORDS ((const u8 *)0x800021b0)
#define PROBE_SENT 0x4198                           /* from that block to the one 0x400979ca builds, 0x80006348 */

CAVE3 static void hex4(void *surface, s32 x, u32 v)
{
    char n[5];
    s32 i;

    n[4] = 0;
    for (i = 3; i >= 0; i--, v >>= 4) {
        u32 d = v & 15;

        n[i] = d + (d > 9 ? 'A' - 10 : '0');
    }
    text(surface, FONT, x, 12, CENTRED, FIVE, n);
}

CAVE static void probe(void *surface, u32 t)
{
    const u8 *w = PROBE_WORDS + PARAMS_STRIDE * t + PARAM_KNOBS + 2 * K_REC;

    hex4(surface, 59, *(const u16 *)w);
    hex4(surface, 85, *(const u16 *)(w + PROBE_SENT));
}
#endif

#ifdef PROBE17
/* The probe17 image, a tool: why a trigless step's solo is not heard. The fifth place, empty since the trig image,
 * shows slot 17 of the track in the block a trig's locks are written into (0x800021b0; 3580 a step locked to solo,
 * 1A80 one locked off), and the sixth this block's solos (SOLO_NOW, a bit a track, track 1 the lowest). */
__attribute__((section(".cave.d"), noinline)) static void hex_n(char *n, u32 v, s32 digits)
{
    s32 i;

    n[digits] = 0;
    for (i = digits - 1; i >= 0; i--, v >>= 4) {
        u32 d = v & 15;

        n[i] = d + (d > 9 ? 'A' - 10 : '0');
    }
}

__attribute__((section(".cave.d"), noinline)) static void probe17(void *surface, u32 t)
{
    char n[5], m[4], w_s17[4] = { 'S', '1', '7', 0 }, w_now[4] = { 'N', 'O', 'W', 0 };

    hex_n(n, *(const u16 *)((const u8 *)0x800021b0 + PARAMS_STRIDE * t + PARAM_KNOBS + 2 * K_SOLO), 4);
    place(surface, 4, w_s17, n);
    hex_n(m, SOLO_NOW & 0xfff, 3);
    place(surface, 5, w_now, m);
}
#endif

#ifdef SLOTPROBE
/* The slotprobe image, a tool: whether knob slots 0, 55 and 70, which no record names, hold a step's lock (for the
 * substep hits, docs/FINDINGS.md). With a step held, knob G to the right makes a lock on each, 1080, 1180 and 1280,
 * and to the left takes them off. Places D, F and G show the held step's three locks (FFFF none), or with no step
 * held the words at slots 0 and 55 of the block a trig's locks are written into (0x800021b0) and at slot 70's place
 * there, which is past the track's 142 bytes. */
#endif
#if defined(SLOTPROBE) || defined(TUNEPROBE)
__attribute__((section(".cave.d"), noinline)) static void sp_hex(char *n, u32 v)
{
    s32 i;

    n[4] = 0;
    for (i = 3; i >= 0; i--, v >>= 4) {
        u32 d = v & 15;

        n[i] = d + (d > 9 ? 'A' - 10 : '0');
    }
}
#endif
#ifdef SLOTPROBE

__attribute__((section(".cave.b"), noinline)) static void slotprobe_turn(struct page *p, s32 turn)
{
    void *steps = pattern(p->mgr);
    s32 step;
    u32 i, slot;

    editing(p->keys, 1);
    for (step = held(p, 0); step >= 0; step = held(p, (u32)step + 1)) {
        if (turn > 0 && !has_trig(steps, (u32)step) && !has_lock_trig(steps, (u32)step))
            give_trig(steps, (u32)step, 1);
        for (i = 0, slot = 0; i < 3; slot = 55 + 15 * i++)
            if (turn > 0)
                lock_make(steps, (u32)step, slot, (s32)((0x10 + i) << 8 | 0x80));
            else if (lock_read(steps, (u32)step, slot) >= 0)
                lock_drop(steps, (u32)step, slot);
    }
    edited(p->keys);
}

__attribute__((section(".cave.a"), noinline)) static void slotprobe_place(struct page *p, void *surface, u32 t)
{
    char n[5], w[4];
    s32 step = held(p, 0), v;
    u32 i, slot;

    for (i = 0; i < 3; i++) {
        slot = i ? 40 + 15 * i : 0;
        if (step >= 0) {
            v = lock_read(pattern(p->mgr), (u32)step, slot);
            sp_hex(n, v < 0 ? 0xffff : (u32)v);
            w[0] = 'L';
        } else {
            sp_hex(n, *(const volatile u16 *)((const u8 *)0x800021b0 + PARAMS_STRIDE * t + PARAM_KNOBS + 2 * slot));
            w[0] = 'B';
        }
        w[1] = '0' + slot / 10;
        w[2] = '0' + slot % 10;
        w[3] = 0;
        place(surface, i ? 4 + i : 3, w, n);
    }
}
#endif

#ifdef TUNEPROBE
/* The tuneprobe image, a tool: what a held turn of the sampler's TUNE does on the unit, for the tune image's third
 * build, a held turn there "still the same as stock" (+4 a click) while its table entry reads as built (the probe's
 * first build: C 0003, F 5EB8, S 0001, the maintainer's word). Stock's page knob routine's call of the change routine (0x4003b9b6)
 * goes through tp_change, which keeps what it was given and what it gave back. Places D, F and G: N the ticks it was
 * given (hex, low half), P its calls (high byte), the held flag and the knob, R the change it gave back (8.8: 0100 is
 * 1, 0400 is 4). */
__asm__(".section .cave.a,\"ax\"\n"
        "tp_vars:    .long 0, 0, 0, 0\n"
        "            .text\n");
extern volatile u32 tp_vars[4];
#define change_routine ((s32 (*)(void *, u32, s32, void *, u32))0x400f6a96)

__attribute__((section(".cave.a"), noinline)) s32 tp_change(void *ticks, u32 knob, s32 steps, void *feel, u32 held)
{
    s32 r = change_routine(ticks, knob, steps, feel, held);

    tp_vars[0] = (u32)steps;
    tp_vars[1] = ((tp_vars[1] + 0x100u) & 0xff00u) | (held & 1u) << 4 | (knob & 15u);
    tp_vars[2] = (u32)r;
    return r;
}

__attribute__((section(".cave.a"), noinline)) static void tuneprobe_place(void *surface)
{
    char n[5], w[2];

    w[1] = 0;
    sp_hex(n, tp_vars[0]);
    w[0] = 'N';
    place(surface, 3, w, n);
    sp_hex(n, tp_vars[1]);
    w[0] = 'P';
    place(surface, 5, w, n);
    sp_hex(n, tp_vars[2]);
    w[0] = 'R';
    place(surface, 6, w, n);
}
#endif

/* Place k as stock lays the eight out: four across, 26 apart, knobs 0..3 in the row at 27
 * and 4..7 in the row at 0; the name on that line, the value where the picture would be. */
CAVE static void place(void *surface, u32 k, const char *name, const char *value)
{
    s32 x = 33 + 26 * (k & 3);
    s32 y = k < 4 ? 27 : 0;

    text(surface, FONT, x, y, CENTRED, FIVE, name);
    text(surface, FONT, x, y + 12, CENTRED, FIVE, value);
}

#ifdef ONCE
/* The once image. What REC reads: a held step's own lock on slot 24, ONCE, ON or OFF; with no step held, or a held
 * step whose slot holds no mark, the track's own: ON by its bit of MODE (`m`), else ONCE by its byte, else OFF. */
CAVE2 static const char *rec_says(struct page *p, s32 step, u32 m)
{
    u32 d = step >= 0 ? (u32)lock_read(pattern(p->mgr), (u32)step, K_REC) : 0;

    if (d == ONCE_WORD)
        return w_once;
    d >>= 8;
    if (d == REC_LOCK_ON)
        return w_on;
    if (d == REC_LOCK_OFF)
        return w_off;
    return m & MODE_REC ? w_on : ONCE_ARM[sampler(p)] ? w_once : w_off;
}
#endif

#ifdef SLOCK
/* The slock image: a sampler track's solo can be locked to a step. (The on request
 * .)
 * A lock on knob slot 17 at one of two marks (engine/sampler.h, SLOCK), made and removed as REC's is on slot 24: a
 * step has one only where it is not to do as the track does. With a step held knob E turns the step's, and the place
 * says the first held step's. In an eighth run of code. */
#ifdef ALOCK    /* the alock image: an analog track's lock is on slot 26 (engine/sampler.h, ALOCK) */
#define SOLO_SLOT(t) ((t) < 8 ? K_SOLO : K_SOLO_ANALOG)
#else
#define SOLO_SLOT(t) K_SOLO
#endif
#ifdef STSW
static void stsw_lock(void *pat, u32 step, u32 slot, s32 word, u32 mask);
#endif
__attribute__((section(".cave.s"), noinline)) static void solo_steps(struct page *p, u32 t, s32 turn)
{
    void *steps = pattern(p->mgr);
    s32 step = held(p, 0);
    int own = SOLO_WORD >> t & 1;

    editing(p->keys, 1);
    for (; step >= 0; step = held(p, (u32)step + 1)) {
#ifdef TLSOLO
        /* the tlsolo image: a held step always takes the lock it is turned to, off too where the track's own is off.
         * A trigless step's lock holds until the track's next trig, so an earlier one's ON is undone only by an OFF.
         * (The on request.) */
        (void)own;
#else
        if ((turn > 0) == own) {
            if (lock_read(steps, (u32)step, SOLO_SLOT(t)) >= 0)
                lock_drop(steps, (u32)step, SOLO_SLOT(t));
            continue;
        }
#endif
        if (!has_trig(steps, (u32)step) && !has_lock_trig(steps, (u32)step))
            give_trig(steps, (u32)step, 1);
#ifdef STSW
        stsw_lock(steps, (u32)step, SOLO_SLOT(t), REC_WORD(turn > 0 ? SOLO_LOCK_ON : SOLO_LOCK_OFF), 0xff00);   /* the stsw image: a stretch's mark stays */
#else
        lock_make(steps, (u32)step, SOLO_SLOT(t), REC_WORD(turn > 0 ? SOLO_LOCK_ON : SOLO_LOCK_OFF));
#endif
    }
    edited(p->keys);
}

__attribute__((section(".cave.s"), noinline)) static const char *solo_says(struct page *p, u32 t)
{
    s32 step = held(p, 0);
    u32 on = SOLO_WORD >> t & 1, d;

    if (step >= 0) {
        d = (u32)lock_read(pattern(p->mgr), (u32)step, SOLO_SLOT(t)) >> 8;
        if (d == SOLO_LOCK_ON)
            on = 1;
        if (d == SOLO_LOCK_OFF)
            on = 0;
    }
    return on ? w_solo : w_solo + 5;
}
#endif

#ifdef STSW
/* The stsw image: knob E of the sampling page is the stretch, the track's (bit 3 of its word, SRR_STR) or, with a step
 * held, the step's: a lock on slot 17's low byte (engine/sampler.h, STSW), the solo's mark kept in its high byte. A
 * held step always takes the lock it is turned to, as the solo's does (TLSOLO). */
__asm__(".section .cave.e,\"ax\",@progbits\n"
        "w_strc:     .asciz \"STRC\"\n"
        "            .even\n"
        "            .text\n");
extern const char w_strc[];

/* A lock of slot's: word's bits under mask, and the rest the lock's as it was, if it was one (for the solo's high
 * byte, its low byte only where that is a stretch's mark); word's own rest if not. */
CAVE_STSW static void stsw_lock(void *pat, u32 step, u32 slot, s32 word, u32 mask)
{
    s32 old = lock_read(pat, step, slot);

    if (old >= 0 && (mask == 0xff || STR_MARKED(old)))
        word = (word & (s32)mask) | (old & ~(s32)mask & 0xffff);
    lock_make(pat, step, slot, word);
}

__attribute__((section(".cave.m"), noinline)) static void stsw_turn(struct page *p, u32 t, s32 turn)
{
    void *pat;
    s32 step = held(p, 0);
    u32 w;

    if (!turn || !KIT || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    if (step < 0) {
        if (turn > 0 && !(w & SRR_STR))
            OWN_WORDS(t)[K_SPEED] = 64 << 8;    /* into a stretch: SPD at the note's own speed, so nothing moves until it is turned */
        OWN_WORDS(t)[K_REC] = turn > 0 ? w | SRR_STR : w & ~SRR_STR;
        return;
    }
    pat = pattern(p->mgr);
    editing(p->keys, 1);
    for (; step >= 0; step = held(p, (u32)step + 1)) {
        if (!has_trig(pat, (u32)step) && !has_lock_trig(pat, (u32)step))
            give_trig(pat, (u32)step, 1);
        stsw_lock(pat, (u32)step, K_SOLO, (s32)(STR_NO_SOLO << 8 | (turn > 0 ? STR_LOCK_ON : STR_LOCK_OFF)), 0xff);
    }
    edited(p->keys);
}

CAVE_STSW static void stsw_place(struct page *p, void *surface, u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0, on = SRR_SIGNED(w) && (w & SRR_STR);
    s32 step = held(p, 0), d;

    if (step >= 0 && (d = lock_read(pattern(p->mgr), (u32)step, K_SOLO)) >= 0 && STR_MARKED(d))
        on = (d & 0xff) == STR_LOCK_ON;
    place(surface, STRC_AT, w_strc, on ? w_on : w_off);
}
#endif

#ifdef XKNOB
/* The xknob image: the crossfade is knob D of the sampler's own page, in DEC's place and on its slot (25), so it is
 * kept with the pattern's kit and takes a lock and an LFO; the sampler no longer reads DEC (engine/sampler.c). Its value
 * is stored upside down, the crossfade 127 less the slot's, so a track made before (its DEC at 127, as stock makes it)
 * has none: engine/amute.c, XKNOB, reads it so every block. Here: a turn of D goes to stock's routine the other way
 * round, and the other sampler tracks' crossfades and the analog tracks' are taken away (on request
 * ); stock draws D's place, and its picture is drawn again, the right way up, over an eraser of its size. Its
 * text is engine/knobtext.c's. The drawing in the tenth run; the turn and the clearing in two runs of their own. On request
 *  */
#define XF_KNOB_D 3u                    /* knob D of the first page: record 504 */
#define R_DEC 504u
#define arc ((void (*)(void *, s32, void *, s32, s32))0x400701b4)     /* a plain knob's picture: (object, value 8.8, surface, x, y) */
#define xf_blit ((void (*)(void *, const void *, s32, s32, u32))0x400f8f70)
#define CAVE10 __attribute__((section(".cave.v"), noinline))

#ifdef XFIX
/* The xfix image (2026-10-18, the maintainer's word: "if you move it on one track and then move it on another track will get stuck and
 * won't get below that number ... and can't be brought down after that"): a track's kit word was taken away and its live
 * one left. What the analog mute reads every block is the live word (0x800021b0, slot 25 of the track's 142 bytes), and
 * stock puts the kit's into it only at the track's next trig (0x400a321a), so a track with no trig kept its old crossfade,
 * and the largest of the twelve, the pattern's, could not go below it. The live word goes with the kit's now; stock's
 * filter (0x400979ca) takes the block there over about 60 ms. */
#define LIVE_WORDS(t) ((volatile u16 *)(0x800021b0u + PARAMS_STRIDE * (t) + PARAM_KNOBS))
#endif

__attribute__((section(".cave.f"), noinline)) static void xf_clear(struct page *p, u32 keep)     /* in a fifteenth run */
{
    u32 u;

    if (!KIT)
        return;
    for (u = 0; u < 8; u++)
        if (u != keep && machine_of(p->kit, u) == MACHINE_TYPE)
#ifdef XFIX
        {
            OWN_WORDS(u)[K_DECAY] = XFADE_TOP << 8;
            LIVE_WORDS(u)[K_DECAY] = XFADE_TOP << 8;
        }
#else
            OWN_WORDS(u)[K_DECAY] = XFADE_TOP << 8;
#endif
    if (keep < 8)
        ((volatile u32 *)XFADES)[2] = 0;    /* the four analog tracks' */
}

#ifdef XSHARE
/* The xshare image: the pattern's one crossfade is the largest of the twelve numbers, which the analog mute makes
 * every block from the sampler tracks' knob D and the analog tracks' own (engine/amute.c, XKNOB). */
static u32 xfade_now(void);
#define xf_shared xfade_now

/* The xshare image: with no step held the knob is the pattern's: the track turning it takes the crossfade as it stands,
 * then turns it, and the others' go (on request
 * ). With steps held it locks them and nothing else. */
#ifdef XCONT
/* The xcont image (2026-10-19, the maintainer's word on the xfix image: "it snaps back now on a diff channel but now it snaps all the
 * way back to 0, it should just be continuous from where it was"): the amount a turn takes was the analog mute's, made
 * from the filtered block (about 60 ms behind), so with the old holder's word now cleared at once, the largest dipped
 * while the two crossed and each tick of the turn began again from the dip, down to 0. Taken here from the words the
 * block is filtered from (0x800021b0), which the clear and stock's store set at once: the first tick takes the holder's
 * amount, the rest go on from the turning track's own. A sampler track by its type in the block it was sent (+ 62). */
__attribute__((section(".cave.d"), noinline)) static u32 xf_live(void)
{
    u32 u, x, top = 0;

    for (u = 0; u < 8; u++) {
        if (*((const volatile u8 *)0x80006348u + PARAMS_STRIDE * u + 62u) != MACHINE_TYPE)
            continue;
        x = LIVE_WORDS(u)[K_DECAY] >> 8;
        x = x >= XFADE_TOP ? 0 : XFADE_TOP - x;
        if (x > top)
            top = x;
    }
    for (u = 8; u < 12; u++)
        if (XFADES[u] > top)
            top = XFADES[u];
    return top;
}

#ifdef XCARRY
/* The xcarry image (2026-10-19, the maintainer's word on the xcont image: "no it sitll anaps back"): the turn's own value is the page's
 * (stock's turn, 0x4003b870, adds its change through the page's method at + 96 to what the page holds), not the kit's
 * word written here, so the turning track began from its own old number. The amount is given to the track through the
 * page's own method (PLAIN, as MODE's bits were before the srr image), so stock's turn goes on from it. */
__attribute__((section(".cave.h"), noinline)) static void xf_carry(struct page *p)
{
    s32 v = METHOD(p, GET, get_fn)(p, R_DEC, -1), want = (s32)((XFADE_TOP - xf_live()) << 8);
    u8 answer;

    if (v >= 0 && want != v)
        METHOD(p, PLAIN, plain_fn)(p, R_DEC, want - v, 0, &answer);
}
#else
__attribute__((section(".cave.h"), noinline)) static void xf_take(u32 t)     /* in a sixteenth run */
{
    if (KIT)
        OWN_WORDS(t)[K_DECAY] = (XFADE_TOP - xf_live()) << 8;
}
#endif
#else
__attribute__((section(".cave.h"), noinline)) static void xf_take(u32 t)     /* in a sixteenth run */
{
    if (KIT)
        OWN_WORDS(t)[K_DECAY] = (XFADE_TOP - xf_shared()) << 8;
}
#endif

__attribute__((section(".cave.w"), noinline)) static u32 xf_turn(struct page *p, struct event *e, u32 t)  /* in a fourteenth */
{
    u32 r, own = held(p, 0) < 0;

    if (own)
#ifdef XCARRY
        xf_carry(p);
#else
        xf_take(t);
#endif
    e->steps = -e->steps;
    r = stock_turn(p, e);
    e->steps = -e->steps;
    if (own)
        xf_clear(p, t);
    return r;
}
#else
__attribute__((section(".cave.w"), noinline)) static u32 xf_turn(struct page *p, struct event *e, u32 t)  /* in a fourteenth */
{
    u32 r;

    e->steps = -e->steps;
    r = stock_turn(p, e);
    e->steps = -e->steps;
    xf_clear(p, t);
    return r;
}
#endif

CAVE10 static void xf_draw(struct page *p, void *surface)
{
    s32 step = held(p, 0), v = -1;

    if (step >= 0)
        v = METHOD(p, STEP_LOCK, step_lock_fn)(p, (u32)step, R_DEC);
#ifdef XSHARE
    if (v < 0)                          /* the xshare image: no lock, the pattern's crossfade */
        v = (s32)((XFADE_TOP - xf_shared()) << 8);
#endif
    if (v < 0)
        v = METHOD(p, GET, get_fn)(p, R_DEC, -1);
    if (v > (s32)(XFADE_TOP << 8))
        v = XFADE_TOP << 8;
    xf_blit(surface, (const void *)ERASER2, 24 + 26 * 3, 34, 0);
    arc(0, (s32)(XFADE_TOP << 8) - v, surface, 24 + 26 * 3, 34);
}
#endif

CAVE void syn_draw(struct page *p, void *surface)
{
    struct state *s;
#ifdef METER
    char n[6];
#else
    char n[4];
#endif
    s32 t;
    u32 d, m;
#ifdef PBANK
    (void)d;                            /* (the pbank image: BANK, its one use on this image, is in the PROJECT menu) */
#endif
#ifdef FEED
    s32 lock;
    u32 take;
#endif
#ifdef ONCE
    const char *says;
#endif

    stock_draw(p, surface);
    t = sampler(p);
#ifdef RECLOCK
    if (t < 0)
        strays(p);
#endif
#ifdef XKNOB
    if (!p->index && t >= 0)            /* the xknob image: knob D's picture the right way up */
        xf_draw(p, surface);
#endif
    if (!p->index || t < 0)
        return;
    s = state(p);
#ifdef FEED
    /* The feed image: the first held step is asked for once a drawing. It was asked for three times, a pass over
     * the pattern's steps each, and MODE was read twice: the same drawing. */
    t = held(p, 0);
    m = take = (u32)value(p, t, &lock) >> 8;
#ifdef ONCE
    says = rec_says(p, t, m);           /* the once image: REC's three words, a held step's own or the track's */
#else
    if (t >= 0) {                       /* a held step's own REC */
        d = (u32)lock_read(pattern(p->mgr), (u32)t, K_REC) >> 8;
        if (d == REC_LOCK_ON)
            m |= MODE_REC;
        if (d == REC_LOCK_OFF)
            m &= ~MODE_REC;
    }
#endif
    t = sampler(p);
#else
    m = mode(p);
#ifdef RECLOCK
    if ((t = held(p, 0)) >= 0) {        /* a held step's own REC */
        d = (u32)lock_read(pattern(p->mgr), (u32)t, K_REC) >> 8;
        if (d == REC_LOCK_ON)
            m |= MODE_REC;
        if (d == REC_LOCK_OFF)
            m &= ~MODE_REC;
    }
    t = sampler(p);
#endif
#endif
#ifdef TIMED
    timed(surface);
#endif
#ifdef METER
    src_name(n, SRC_OF(m));
    place(surface, 0, w_src, n);
    bar(p, surface, SRC_OF(m));
#else
    place(surface, 0, w_src, m & MODE_EXT ? w_ext : w_main);
#endif
#ifdef NEXT
    (void)says;
    next_places(surface, s, (u32)t);    /* the next image: DEST SMPL or NEXT, and C the track's KIND (REC is the TRIG page's) */
#else
    d = s->dest[t];
    n[0] = '0' + d / 10;
    n[1] = '0' + d % 10;
    n[2] = 0;
    place(surface, 1, w_dest, d ? n : w_smpl);
#ifdef ONCE
    place(surface, 2, w_rec, says);
#else
    place(surface, 2, w_rec, m & MODE_REC ? w_on : w_off);
#endif
#endif
#if defined(BANKS) && !defined(SLOTPROBE) && !defined(PBANK) && !defined(TUNEPROBE)     /* (the slotprobe image: D, F and G show its three slots; the pbank image: BANK is in the PROJECT menu) */
    d = BANK_NOW < BANKS_N ? BANK_NOW : 0;
    m = BANK_WANT < BANKS_N ? BANK_WANT : d;
    n[0] = 'A' + d;
    n[1] = m == d ? 0 : '>';
    n[2] = 'A' + m;
    n[3] = 0;
    place(surface, 3, w_bank, n);
#endif
#if defined(SAVE) && !defined(FEED)      /* (the feed image: the fifth place is empty, always) */
    save_place(surface);
#endif
#if defined(TRIGPAGE)
    /* the trig image: the solo is on the TRIG page, and the fifth place here is empty */
#ifdef STSW
    stsw_place(p, surface, (u32)t);     /* the stsw image: the stretch's switch */
#endif
#elif defined(SLOCK)
    place(surface, 4, w_solo + 4, solo_says(p, (u32)t));                         /* the slock image: a held step's own, or the track's */
#elif defined(SOLOKNOB)
    place(surface, 4, w_solo + 4, SOLO_WORD >> t & 1 ? w_solo : w_solo + 5);     /* the soloknob image: SOLO, or S OFF */
#endif
#if defined(GAIN) && !defined(SLOTPROBE) && !defined(TUNEPROBE)
    gain_place(surface, (u32)t);
#elif defined(GAIN)
    (void)gain_place;
#endif
#if defined(XKNOB)
    (void)take;                         /* the xknob image: the crossfade is the first page's knob D, and the third place is empty */
#if defined(FLTRPAGE) && !defined(SLOTPROBE) && !defined(TUNEPROBE)
    load_place(surface);                /* the fltr image: the audio CPU's peak in the last place again (the xknob image lost it with the crossfade's place) */
#endif
#ifdef SLICE
    keys_place(surface, (u32)t);        /* the slice image: KEYS in the last place, the peak in G's */
#endif
#elif defined(XFADE)
    (void)take;                         /* the xfade image: what a take is has no place, and the third is the crossfade */
    xfade_place(surface, (u32)t);
#elif defined(FEED)
    take_place(surface, take);
#elif defined(AUTO)
    take_place(surface, mode(p));
#endif
#ifdef PROBE
    probe(surface, (u32)t);
#endif
#ifdef PROBE17
    probe17(surface, (u32)t);
#endif
#ifdef SLOTPROBE
    slotprobe_place(p, surface, (u32)t);
#endif
#ifdef TUNEPROBE
    tuneprobe_place(surface);
#endif
}

#ifdef RECLOCK
#define CAVE_MOVED CAVE2        /* the first run is full again */
#else
#define CAVE_MOVED CAVE
#endif
CAVE_MOVED static u32 moved(u32 v, s32 steps, u32 top)
{
    s32 n = (s32)v + steps;

    return n < 0 ? 0 : n > (s32)top ? top : (u32)n;
}

#ifdef ONCE
/* The once image. A turn of REC through its three settings, 0 off, 1 on, 2 once: on every held step, or with none
 * held on the track.
 *
 * The track's: on is its bit of MODE as before, with the pop-up; once is its byte of ONCE_ARM with the bit off
 * (engine/once.S plays it), said in the pop-up in OFF's place.
 *
 * A step's: a lock on slot 24, there only where the step is not to do as the track does, as before; but ONCE on a
 * step is always a lock of its own, at ONCE_WORD. A step whose slot holds no mark reads as the track does. */
CAVE3 static void once_own(struct page *p, u32 track, u32 own, s32 turn)
{
    u32 want = moved(own, turn, 2);
    const char *off = want == 2 ? w_once : w_off;

    if (want == own)
        return;
    ONCE_ARM[track] = want == 2;
    if ((want == 1) != (own == 1))
        flip(p, MODE_REC, want == 1 ? 1 : -1, w_rec, off, w_on);
    else if (popups(p->tracks) != 1)
        popup(p->keys, POPUP, w_rec, off);
}

CAVE2 static void once_turn(struct page *p, u32 track, s32 turn)
{
    void *steps = pattern(p->mgr);
    s32 step = held(p, 0), lock;
    u32 own, want, w;

    if (!turn)
        return;
    own = (u32)value(p, -1, &lock) >> 8 & MODE_REC ? 1 : ONCE_ARM[track] ? 2 : 0;
    if (step < 0) {
        once_own(p, track, own, turn);
        return;
    }
    editing(p->keys, 1);
    for (; step >= 0; step = held(p, (u32)step + 1)) {
        w = (u32)lock_read(steps, (u32)step, K_REC);
        want = moved(w == ONCE_WORD ? 2 : w >> 8 == REC_LOCK_ON ? 1 : w >> 8 == REC_LOCK_OFF ? 0 : own, turn, 2);
        if (want == own && want != 2) {
            if ((s32)w >= 0)
                lock_drop(steps, (u32)step, K_REC);
            continue;
        }
        if (!has_trig(steps, (u32)step) && !has_lock_trig(steps, (u32)step))
            give_trig(steps, (u32)step, 1);
        lock_make(steps, (u32)step, K_REC, want == 2 ? (s32)ONCE_WORD : REC_WORD(want ? REC_LOCK_ON : REC_LOCK_OFF));
    }
    edited(p->keys);
}
#endif

#ifdef APAGE
/* The apage image: the analog tracks have the second page too, for the two things on it that are every track's:
 * the solo on knob E and the crossfade on knob G. (The on request
 * .) The six other places are empty and their knobs turn nothing. In a seventh run of code: the
 * class's three methods come here first and go on to the sampler's own for every other track.
 * The crossfade is twelve numbers now, three longs: a turn writes the track's own long first and clears the two
 * others after, so the per-block routine never finds all twelve at 0 on the way. */
#define CAVE7 __attribute__((section(".cave.r"), noinline))
CAVE7 static void xfade_turn(u32 t, s32 steps)
{
    volatile u32 *w = (volatile u32 *)XFADES;
    u32 x = moved(xfade_now(), steps, XFADE_TOP) << (8 * (3 - (t & 3))), own = t >> 2, i;

    w[own] = x;
    for (i = 0; i < 3; i++)
        if (i != own)
            w[i] = 0;
}

/* The active track if it is an analog one, 8..11, or -1. */
CAVE7 static s32 analog(struct page *p)
{
    u32 t = active_track(p->tracks);

    return t >= 8 && t < 12 ? (s32)t : -1;
}
#endif

#ifdef GEAR
/* The gear image: the page's knobs turn as stock's own do. On request
 *
 * . Until here a turn's every tick moved a knob of ours a whole step.
 *
 * Stock's knob routine (0x4003b870) makes a turn's change in three calls, and a stock page whose knobs are whole
 * numbers and no records makes the same three (0x40049730): the event's steps, times a coarse number while the knob
 * is pushed in; whether it is pushed in; and the change, 8.8, from a routine that counts a knob's ticks in the page
 * object (+ 148 of this class's, 20 bytes a knob), lets a step through every so many, and makes a fast turn go
 * further, all by a "feel" that is built at a start. Then that page takes the whole part, towards nought.
 * The same here, in the same object: the plain knob's feel for the page's knobs (pushed in: four times), and for SMPL
 * the feel and the eight that stock gave Twinshot's sample picker. The crossfade's knob is not touched. */
#define knob_steps ((s32 (*)(struct event *, s32, s32))0x400f6866)       /* (event, fine, coarse) -> the steps, times coarse when the knob is pushed in */
#define knob_pushed ((u8 (*)(struct event *))0x400f6884)
#define knob_change ((s32 (*)(void *, u32, s32, const void *, u32))0x400f6a96)   /* (the page's ticks, knob, steps, a feel, pushed) -> the change, 8.8 */
#define TURN_STATE 148
#define FEEL_PLAIN ((const void *)0x443db178)
#define FEEL_PICKER ((const void *)0x443db140)
__attribute__((section(".cave.v"), noinline))        /* a tenth run: the ninth is full */
static s32 gear(struct page *p, struct event *e, u32 k, const void *feel, s32 coarse)
{
    return knob_change((u8 *)p + TURN_STATE, k, knob_steps(e, 1, coarse), feel, knob_pushed(e)) / 256;
}
#endif

CAVE u32 syn_turn(struct page *p, struct event *e)
{
    u32 k = e->id - 1;
    struct state *s;
    s32 t;
#ifdef GEAR
    struct event geared;
#endif

    if (k > 7 || (t = sampler(p)) < 0)
        return stock_turn(p, e);
#ifdef GEAR
    if (p->index && k != PEAK_AT) {     /* the gear image: every knob of the page but the crossfade's, as a plain knob of stock's */
        /* (its second build: SRC and REC are picked from a list and have the picker's feel, six ticks a step, a pause
         * after each and no speeding up, where a plain knob has three and speeds up. The maintainer, with the first on his
         * unit: "its better now but src moves too fast ztill and rec too") */
        geared.steps = gear(p, e, k, k == 0 || k == 2 ? FEEL_PICKER : FEEL_PLAIN, 4);
        e = &geared;
    }
#endif
    if (!p->index) {                    /* the first page: MODE is ours, a switch between MONO and STEREO */
#ifdef SRR
#ifdef XKNOB
        if (k == XF_KNOB_D)             /* the xknob image: the crossfade, its value upside down, and one track's at a time */
            return xf_turn(p, e, (u32)t);
#endif
        return stock_turn(p, e);        /* the srr image: every knob of the first page is stock's, the reduction's too */
#endif
        if (k != MODE_KNOB)
            return stock_turn(p, e);
#ifndef AUTO                            /* (the mode image: its place there is empty, and a turn of it is nothing) */
        flip(p, MODE_STEREO, e->steps, 0, 0, 0);
#endif
    } else if (k == 0) {
#ifdef METER
        src_turn(p, e->steps);
#else
        flip(p, MODE_EXT, e->steps, w_src, w_main, w_ext);
#endif
    } else if (k == 1) {
        s = state(p);
#if defined(DESTNUM)
        /* the destnum image: SMPL, or a place's number again. On request
         *  */
        s->dest[t] = (u8)dest_moved(s->dest[t], e->steps, (u32)t);
#elif defined(ONEDEST)
        /* the onedest image: a take goes to SMPL's place, always. On request
         *
         * . A turn of B puts every track back on SMPL, NEXT left from before too */
        for (u32 i = 0; i < 8; i++)
            s->dest[i] = 0;
#elif defined(NEXT)
        if (e->steps)                   /* the next image: SMPL to the left, NEXT to the right */
            s->dest[t] = e->steps > 0;
#elif defined(PACK)
        s->dest[t] = moved(s->dest[t], e->steps, N_SLOTS);      /* the pack image: 33 to 64 are the single slots of those numbers */
#else
        s->dest[t] = moved(s->dest[t], e->steps, N_SLOTS / 2);
#endif
        tell(s);
    } else if (k == 2) {
#if defined(NEXT)
        next_kind((u32)t, e->steps);    /* the next image: knob C is the track's KIND, STER to the left, MONO to the right */
#ifdef DESTNUM
        s = state(p);                   /* the destnum image: a DEST of the other kind back to SMPL */
        if (s->dest[t] && (s->dest[t] > SINGLES) != nx_mono((u32)t)) {
            s->dest[t] = 0;
            tell(s);
        }
#endif
#elif defined(BOX)
        once_turn(p, (u32)t, e->steps > 0 ? 2 : e->steps < 0 ? -2 : 0);     /* the box image: OFF or ONCE, never ON */
#elif defined(ONCE)
        once_turn(p, (u32)t, e->steps);
#else
#ifdef RECLOCK
        if (e->steps && held(p, 0) >= 0)
            rec_steps(p, held(p, 0), e->steps);
        else
#endif
        flip(p, MODE_REC, e->steps, w_rec, w_off, w_on);
#endif
#if defined(BANKS) && !defined(PBANK)     /* (the pbank image: D turns nothing) */
    } else if (k == 3) {
        BANK_WANT = moved(BANK_WANT < BANKS_N ? BANK_WANT : 0, e->steps, BANKS_N - 1);
#endif
#if defined(SAVE) && !defined(PTN)       /* (the ptn image: the fifth place is empty, and a turn of its knob is nothing) */
    } else if (k == 4) {
        save_turn(e->steps);
#endif
#if defined(SOLOKNOB) && !defined(TRIGPAGE)     /* (the trig image: the solo is on the TRIG page) */
    } else if (k == 4) {                /* knob E: the track's solo, on to the right and off to the left */
#ifdef SLOCK
        if (e->steps && held(p, 0) >= 0)    /* the slock image: with a step held, the step's */
            solo_steps(p, (u32)t, e->steps);
        else
#endif
        if (e->steps > 0)
            SOLO_WORD |= 1u << t;
        else if (e->steps < 0)
            SOLO_WORD &= ~(1u << t);
#endif
#ifdef GAIN
    } else if (k == GAIN_AT) {          /* knob F: the track's record gain, a decibel a step (the gainup image: D) */
        REC_GAINS[t] = moved(REC_GAINS[t], e->steps, GAIN_TOP);
#endif
#if defined(AUTO) && !defined(XFADE)
    } else if (k == 6) {                /* knob G: what the track's takes are, MONO or STEREO */
        flip(p, MODE_STEREO, e->steps, 0, 0, 0);
#endif
#if defined(XFADE) && !defined(XKNOB)     /* (the xknob image: the crossfade is the first page's knob D) */
    } else if (k == 6) {                /* knob G: the track's crossfade, 0 to 127: the other tracks go down as it goes up */
#ifdef GFADE
        /* the gfade image: one crossfade for the unit. The track that turns it holds it and the rest are cleared after,
         * so the per-block routine never finds all eight at 0 on the way */
#ifdef APAGE
        xfade_turn((u32)t, e->steps);   /* the apage image: three longs, in its own routine */
#else
        volatile u32 *w = (volatile u32 *)XFADES;
        u32 x = moved(xfade_now(), e->steps, XFADE_TOP) << (8 * (3 - (t & 3)));

        w[t >> 2] = x;                  /* the track's own long first: its three neighbours go with it */
        w[1 - (t >> 2)] = 0;            /* then the other four */
#endif
#else
        XFADES[t] = moved(XFADES[t], e->steps, XFADE_TOP);
#endif
#endif
#ifdef STSW
    } else if (k == STRC_AT) {          /* the stsw image: knob E is the stretch (the gainup image: G) */
        stsw_turn(p, (u32)t, e->steps);
#endif
#ifdef SLICE
    } else if (k == 7) {                /* the slice image: knob H is KEYS */
        keys_turn((u32)t, e->steps);
    } else if (k == PEAK_AT) {          /* and G the profile's switch, with the peak (the gainup image: E) */
#ifdef SLOTPROBE
        if (held(p, 0) >= 0)            /* the slotprobe image: with a step held, G makes or takes off its three locks */
            slotprobe_turn(p, e->steps);
        else
#endif
        if (e->steps > 0)
            PROF_ON = 1;
        else if (e->steps < 0)
            PROF_ON = 0;
#elif defined(PROF)
    } else if (k == 7) {                /* knob H: the profile, on to the right and off to the left (engine/prof.S) */
        if (e->steps > 0)
            PROF_ON = 1;
        else if (e->steps < 0)
            PROF_ON = 0;
#endif
    }
    redraw(p);
    return 1;                           /* what the stock routine answers for a knob it has dealt with */
}

/* The way a turn really arrives: as a call on the object's second base, 4 bytes in. */
CAVE u32 syn_turn_side(void *listener, struct event *e)
{
    return syn_turn((struct page *)((u8 *)listener - 4), e);
}

#ifdef STOPS
/* The stops image: SMPL on the first page stops only at real samples and one free spot of each kind
 * (engine/sampler.h, STOPS). In a fifth run of code and a sixth: no run that is left holds all of it. */
#define CAVE5 __attribute__((section(".cave.n"), noinline))
#define CAVE6 __attribute__((section(".cave.q"), noinline))
#define R_SMPL 498u             /* machine 44's SMPL */
#define SMPL_KNOB 1u            /* where it sits on the sampler's own page */
#define AUDIO_UP (*(const volatile u32 *)0x43bdd824)    /* stock's: the audio CPU is running */
#define SHARED 0x10000000u      /* the window, as the main CPU names it */
/* The places the knob stops at, a byte a place, 64 of them: 0 to 31 the stereo places, 32 to 63 the single
 * slots. -> 0: the audio CPU has not said what the slots hold, or nothing in the bank is a stop, and nothing is
 * to be made of s.
 *   - a stereo place that holds a sample: its first slot is not empty, and in the back half, where a
 *     slot can be a single one's, not odd;
 *   - the lowest stereo place that is free: both its slots empty;
 *   - a single slot that holds a mono sample: its length is odd, and more than one frame. (One frame is
 *     what the mode and cross images left in a mono take's second slot, and such takes are on the drive:
 *     it is no sample and no free slot);
 *   - the highest single slot that is free: empty, and no second half of a stereo place that holds an
 *     even sample.
 * What a slot holds, as the audio CPU says it: 0 empty, 1 even, 2 one frame, 3 odd and more. */
CAVE6 static u32 stops(u8 *s)
{
    const volatile u32 *from = STOPS_LONG(SHARED, 0);
    u8 k[N_SLOTS], *to = k;
    u32 n, x, is, free, any = 0;

    if (!AUDIO_UP || *STOPS_MARK(SHARED) != STOPS_OK)
        return 0;
    for (n = 0; n < 4; n++) {
        if (n == 2)
            from = STOPS_LONG(SHARED, 2);
        for (x = *from++, is = 16; is--; x <<= 2)
            *to++ = x >> 30;
    }
    if (*STOPS_MARK(SHARED) != STOPS_OK)
        return 0;
    for (free = 1, n = 0; n < N_SLOTS / 2; n++) {
        x = k[2 * n];
        is = x ? n < N_SLOTS / 4 || x == 1 : free && !k[2 * n + 1];
        s[n] = is;
        any |= is;
        if (!x && is)
            free = 0;
    }
    for (free = 1, n = N_SLOTS; n-- > N_SLOTS / 2;) {
        x = k[n];
        is = x ? x == 3 : free && !(n & 1 && k[n - 1] == 1);
        s[n] = is;
        any |= is;
        if (!x && is)
            free = 0;
    }
    return any;                         /* (a bank with no stop at all: the knob is stock's, and not stuck) */
}

/* Where a turn of so many steps takes SMPL from value v (0 to 127: 64 up forward, 63 down reversed, the
 * place's number counted from the middle either way): that many stops on, or as many as there are. */
CAVE6 static s32 travel(const u8 *s, s32 v, s32 turn)
{
    s32 at = v, d = turn > 0 ? 1 : -1;

    while (turn && (at += d) >= 0 && at < 2 * N_SLOTS)
        if (s[at >= N_SLOTS ? at - N_SLOTS : N_SLOTS - 1 - at]) {
            v = at;
            turn -= d;
        }
    return v;
}

/* A turn of SMPL. -> 0: the audio CPU has not said, and nothing is done: the turn is stock's. */
CAVE5 static u32 smpl_turn(struct page *p, s32 turn)
{
    s32 step = held(p, 0), v, change;
    u8 answer = 0;
    u8 m[N_SLOTS];

    if (!stops(m))
        return 0;
#ifdef SKIND
    if (!kind_stops(m, (u32)sampler(p)))   /* the kind image: only the stops of the track's KIND */
        return 0;
#endif
    if (!turn)
        return 1;
    if (step < 0) {                     /* the track's own value, and stock's pop-up */
        v = METHOD(p, GET, get_fn)(p, R_SMPL, -1);
        change = (travel(m, v >> 8, turn) - (v >> 8)) << 8;
        if (change)
            METHOD(p, PLAIN, plain_fn)(p, R_SMPL, change, 0, &answer);
        if (popups(p->tracks) != 1)
            popup(p->keys, POPUP, record_name(0, R_SMPL), text_for(R_SMPL, v + change));
        return 1;
    }
    editing(p->keys, 1);                /* held steps, as stock's routine for one has it */
    for (; step >= 0; step = held(p, (u32)step + 1)) {
        v = METHOD(p, STEP_LOCK, step_lock_fn)(p, (u32)step, R_SMPL);
        if (v < 0) {                    /* no lock yet: one at the track's value, and no change this time */
            METHOD(p, STEP_MAKE, step_make_fn)(p, (u32)step, R_SMPL,
                                               METHOD(p, GET, get_fn)(p, R_SMPL, METHOD(p, STEP_ARG, step_arg_fn)(p, (u32)step)));
            continue;
        }
        change = (travel(m, v >> 8, turn) - (v >> 8)) << 8;
        if (change)
            METHOD(p, STEP_MOVE, step_move_fn)(p, (u32)step, R_SMPL, change, 0, &answer);
    }
    edited(p->keys);
    return 1;
}

/* A turn of a knob, before the routines above see it: SMPL on a sampler's first page.
 * Two things stock's knob routine (0x4003b870) does with a turn are kept:
 *   - a knob pushed in while it is turned (the event's byte at + 20) counts its coarse step for each click, and
 *     SMPL's is 8 where its fine one is 1 (the record's template, 0x401d6b74): eight stops a click here;
 *   - with key 1 held (0x40102f40(1): FUNC, by what the routine does with it) the change is the record's own
 *     jump, which for a sample is to the same number on the knob's other half, forward to reversed or back.
 *     That turn is left to stock: the mirror of a stop is a stop. */
#define key_held ((u32 (*)(u32))0x40102f40)
#define KEY_JUMP 1u
#define PUSHED(e) (((const u8 *)(e))[20])
#define COARSE 8

CAVE6 u32 stops_turn(struct page *p, struct event *e)
{
    if (e->id == SMPL_KNOB + 1 && sampler(p) >= 0 && !p->index && !key_held(KEY_JUMP)
#ifdef GEAR
        && smpl_turn(p, gear(p, e, SMPL_KNOB, FEEL_PICKER, COARSE))) {      /* the gear image: SMPL's stops by the sample picker's feel */
#else
        && smpl_turn(p, PUSHED(e) ? COARSE * e->steps : e->steps)) {
#endif
        redraw(p);
        return 1;
    }
    return syn_turn(p, e);
}

CAVE5 u32 stops_turn_side(void *listener, struct event *e)
{
    return stops_turn((struct page *)((u8 *)listener - 4), e);
}
#endif

#ifdef APAGE
u32 stops_turn(struct page *p, struct event *e);

CAVE7 u32 apage_knob(struct page *p, u32 knob)
{
    if (analog(p) < 0)
        return syn_knob(p, knob);
    p->last = p->first + 2;             /* two pages, and on the second no knob is stock's */
    return p->index && knob < 8 ? 0 : stock_knob(p, knob);
}

#ifdef AXF
/* The axf image: on the analog tracks' page the peak in H's place, which is empty there. load_place puts it in G's since
 * the slice image, and xfade_place drew it there with the crossfade over it: the maintainer, 2026-10-26, "crossfade's text is
 * garbled. It looks like there are two things getting printed over at once". */
CAVE7 static void peak_h(void *surface)
{
    u32 w[2];

    w[0] = (TIMED_BOX[1] & 0x000f0f0f) | 0x00303030 | (0x584843u >> 8 * *(const u32 *)0x80007d10) << 24;
    if (PROF_ON)
        w[0] = 0x50524f46;              /* "PROF" */
    w[1] = 0;
    place(surface, 7, (const char *)(w + 1), (const char *)w);
}
#endif

CAVE7 void apage_draw(struct page *p, void *surface)
{
    s32 t = analog(p);

    if (t < 0 || !p->index) {
        syn_draw(p, surface);
        return;
    }
    stock_draw(p, surface);
#if defined(ATRIG)  /* the atrig image: the solo is on the TRIG page */
#elif defined(ALOCK)        /* the alock image: a held step's own, or the track's */
    place(surface, 4, w_solo + 4, solo_says(p, (u32)t));
#else
    place(surface, 4, w_solo + 4, SOLO_WORD >> t & 1 ? w_solo : w_solo + 5);
#endif
    xfade_place(surface, (u32)t);
#ifdef AXF
    peak_h(surface);
#endif
}

CAVE7 u32 apage_turn(struct page *p, struct event *e)
{
    u32 k = e->id - 1;
    s32 t = analog(p);

    if (t < 0 || !p->index || k > 7)
        return stops_turn(p, e);
#ifdef GEAR
    struct event geared;

    if (k == 4) {                       /* the gear image: the solo here as on a sampler's page */
        geared.steps = gear(p, e, k, FEEL_PLAIN, 4);
        e = &geared;
    }
#endif
#ifdef ATRIG
    if (k == 4) {                       /* the atrig image: the solo is on the TRIG page, and E here turns nothing */
    } else
#endif
    if (k == 4) {
#ifdef ALOCK        /* the alock image: with a step held the step's, on a track that holds an analog machine */
        if (e->steps && held(p, 0) >= 0 && ANALOG_MACHINE(machine_of(p->kit, (u32)t)))
            solo_steps(p, (u32)t, e->steps);
        else
#endif
        if (e->steps > 0)
            SOLO_WORD |= 1u << t;
        else if (e->steps < 0)
            SOLO_WORD &= ~(1u << t);
    } else if (k == 6) {
        xfade_turn((u32)t, e->steps);
#ifdef XKNOB
        xf_clear(p, 8);                 /* the xknob image: an analog track's crossfade takes every sampler track's away */
#endif
    }
    redraw(p);
    return 1;
}

CAVE7 u32 apage_turn_side(void *listener, struct event *e)
{
    return apage_turn((struct page *)((u8 *)listener - 4), e);
}
#endif

#ifdef TRIGPAGE
/* The trig image: on a sampler track the TRIG page's fifth and sixth places, LFO.T and FLT.T, are the track's SOLO and
 * REC, as they were on the sampling page (which keeps REC, and has no SOLO now). On request
 *
 *
 * . LFO.T and FLT.T keep what a trig holds (on, as stock makes one); they are not
 * shown or turned there. Every other track has stock's page. The TRIG class's three methods come here first, and its
 * second base's turn; the object's fields used are the base class's, as the SYN object's. In an eleventh run and a
 * twelfth. */
#define CAVE11 __attribute__((section(".cave.x"), noinline))
#define CAVE12 __attribute__((section(".cave.z"), noinline))     /* and a twelfth, for the turn */
#define trig_stock_knob ((u32 (*)(struct page *, u32))0x40040eb8)
#define trig_stock_draw ((void (*)(struct page *, void *))0x40041076)
#define trig_stock_turn ((u32 (*)(struct page *, struct event *))0x400415d0)
#define TRIG_SOLO 4u                    /* knob E, LFO.T's place */
#define TRIG_REC 5u                     /* knob F, FLT.T's place */
#ifdef EUCL
/* The eucl image: SOLO and REC only on the TRIG page's first page (1 or 2), not on its third, the euclidean one (records
 * 457 to 464, E and F 460 and 461), which the same object shows on a second press. On request
 * . The page showing as FLTR2's
 * test reads it (+ 124, + 144). */
#ifdef ATRIG
/* The atrig image: and on an analog track's TRIG page (page 1: NOTE VEL LEN PROB LFO.T FLT.T PTIM PORT, list
 * 0x401c826c; a digital track's is page 2) the track, 8 to 11, for SOLO in LFO.T's place; its F stays FLT.T (TRIG_OURS).
 * The on request
 * . Its first build took page 26 (list 0x401c8214, the third set, not the
 * analog tracks'): on the unit stock's pages, "still showing LFO.T on the trig page". In the apage image's run (.cave.r). */
__attribute__((section(".cave.r"), noinline)) static s32 trig_sampler(struct page *p)
{
    s32 t;

    return p->first[p->index] == 3 ? -1 : (t = analog(p)) >= 0 ? t : sampler(p);
}
#define TRIG_OURS(k, t) ((k) == TRIG_SOLO || ((k) == TRIG_REC && (t) < 8))
#else
__attribute__((section(".cave.x"), noinline)) static s32 trig_sampler(struct page *p)
{
    return p->first[p->index] == 3 ? -1 : sampler(p);
}
#endif
#else
#define trig_sampler(p) sampler(p)
#endif

CAVE11 u32 trig_knob(struct page *p, u32 knob)
{
#ifdef ATRIG
    s32 t = trig_sampler(p);

    if (t >= 0 && TRIG_OURS(knob, (u32)t))
        return 0;
#else
    if ((knob == TRIG_SOLO || knob == TRIG_REC) && trig_sampler(p) >= 0)
        return 0;
#endif                       /* no record: stock leaves the place empty and its knob turns nothing */
    return trig_stock_knob(p, knob);
}

#ifdef SWITCH
/* The switch image: the two places drawn as LFO.T and FLT.T are, a ball in an oval (on request
 *
 * ). Their picture is one routine of stock's, frame value >> 8 of the switch's strip, at the
 * place's x + 1 and y + 4; the place's x and y as stock's draw hands them on (0x4003a244: x 24 + 26 a column, y 7 on
 * the lower row), read, not run on stock. REC's ONCE has no frame of a switch: it is the word, as on the sampling page. */
#define switch_pic ((void (*)(void *, u32, void *, s32, s32))0x400703da)

#ifdef BOX
/* The box image: the dotted box stock draws in a place with no record (a 17 x 17 picture at 0x444e00b4, at the place's
 * x 25 + 26 a column and y 7 on the lower row) is wiped before the switch is drawn, by a picture of ours of the same
 * size whose bits are 0 under stock's own mask of that box (ERASER, put there by the build: tools/build_main.py, BOX).
 * The on request. And REC is OFF or ONCE: ONCE is the switch on. */
#define blit ((void (*)(void *, const void *, s32, s32, u32))0x400f8f70)
#endif

/* in a thirteenth run */
__attribute__((section(".cave.y"), noinline)) static void trig_switch(void *surface, u32 k, const char *name, const char *says, u32 on)
{
#ifdef BOX
    blit(surface, (const void *)ERASER, 25 + 26 * (s32)(k & 3), 7, 0);
#endif
    place(surface, k, name, says);
    if (!*says)
        switch_pic(0, on << 8, surface, 24 + 26 * (s32)(k & 3), 7);
}

CAVE11 void trig_draw(struct page *p, void *surface)
{
    s32 t, step, lock;
    const char *says;

    trig_stock_draw(p, surface);
    if ((t = trig_sampler(p)) < 0)
        return;
    trig_switch(surface, TRIG_SOLO, w_solo, w_solo + 4, solo_says(p, (u32)t) == w_solo);
#ifdef ATRIG
    if (t >= 8)                         /* an analog track: no REC, F is NOT2 */
        return;
#endif
    step = held(p, 0);
    says = rec_says(p, step, (u32)value(p, step, &lock) >> 8);
#ifdef BOX
    trig_switch(surface, TRIG_REC, w_rec, w_solo + 4, says != w_off);       /* ONCE (or an old ON) is the switch on */
#else
    trig_switch(surface, TRIG_REC, w_rec, says == w_once ? says : w_solo + 4, says == w_on);
#endif
}
#else
CAVE11 void trig_draw(struct page *p, void *surface)
{
    s32 t, step, lock;

    trig_stock_draw(p, surface);
    if ((t = trig_sampler(p)) < 0)
        return;
    place(surface, TRIG_SOLO, w_solo + 4, solo_says(p, (u32)t));
    step = held(p, 0);
    place(surface, TRIG_REC, w_rec, rec_says(p, step, (u32)value(p, step, &lock) >> 8));
}
#endif

CAVE12 u32 trig_turn(struct page *p, struct event *e)
{
    u32 k = e->id - 1;
    s32 t = trig_sampler(p);
    struct event geared;

#ifdef ATRIG
    if (t < 0 || !TRIG_OURS(k, (u32)t))
#else
    if (t < 0 || (k != TRIG_SOLO && k != TRIG_REC))
#endif
        return trig_stock_turn(p, e);
    geared.steps = gear(p, e, k, k == TRIG_REC ? FEEL_PICKER : FEEL_PLAIN, 4);     /* as on the sampling page */
    if (k == TRIG_REC)
#ifdef BOX
        once_turn(p, (u32)t, geared.steps > 0 ? 2 : geared.steps < 0 ? -2 : 0);    /* the box image: OFF or ONCE, never ON */
#else
        once_turn(p, (u32)t, geared.steps);
#endif
    else if (geared.steps && held(p, 0) >= 0)
        solo_steps(p, (u32)t, geared.steps);
    else if (geared.steps > 0)
        SOLO_WORD |= 1u << t;
    else if (geared.steps < 0)
        SOLO_WORD &= ~(1u << t);
    redraw(p);
    return 1;
}

CAVE11 u32 trig_turn_side(void *listener, struct event *e)
{
    return trig_turn((struct page *)((u8 *)listener - 4), e);
}

#ifdef FLTRPAGE
/* The fltr image: on a sampler track LFO.T and FLT.T (records 28 and 27, the trig flags the TRIG page's E and F held
 * before the trig image) are FLTR2's empty G and H (on request
 * ). Only the record is ours: the filter page's
 * draw and the base class's turn are stock's, and stock's TRIG page turns the two by that same base turn (its own turn
 * routine, 0x400415d0, goes there for every page but its third). FLTR2 is page 10 of the filter object's two (the page
 * numbers at + 124, the one showing at + 144, as its + 136 reads them). The filter class's + 188 comes here first. */
#define fltr_stock_knob ((u32 (*)(struct page *, u32))0x400420d4)

__attribute__((section(".cave.d"), noinline)) u32 fltr_knob(struct page *p, u32 knob)     /* in a run of its own */
{
    if ((knob == 6 || knob == 7) && p->first[p->index] == 10 && sampler(p) >= 0)
        return knob == 6 ? 28 : 27;     /* G LFO.T, H FLT.T: E and F on the TRIG page, in that order */
#ifdef ATRIG
    if (knob == 6 && p->first[p->index] == 8)
        return 28;                      /* the atrig image: an analog track's FLTR2 (page 8, list 0x401c8260; the base's draw), G LFO.T */
#endif
    return fltr_stock_knob(p, knob);
}

/* And drawn as switches: FLTR2's draw loop (0x40042264) hands each knob's picture routine (the page's + 180) a last
 * argument of 1, a knob's picture, for every record but DEL, FENR and two of the analog page's, which get 0, the record's
 * own picture (FENR's switch); stock's TRIG page hands 0 for all (0x4003a244). Its test of FENR (0x400424c8, 12 bytes:
 * moveb #69,%d1 ; cmpl %d2,%d1 ; bnew 0x400423f0 ; bras 0x400424c2) jumps here, and FLT.T and LFO.T go the way FENR
 * goes. d1 is left 69, as stock leaves it. On request
 * . Only FLTR2 on a sampler track shows records 27 and 28 (fltr_knob). */
__asm__(".section .cave.d,\"ax\",@progbits\n"
        "        .globl fltr_flat\n"
        "fltr_flat:\n"
        "        moveq   #69,%d1\n"
        "        cmp.l   %d2,%d1\n"
        "        beq.s   1f\n"
        "        cmpi.l  #27,%d2\n"
        "        beq.s   1f\n"
        "        cmpi.l  #28,%d2\n"
        "        beq.s   1f\n"
        "        jmp     0x400423f0\n"             /* a knob's picture */
        "1:      jmp     0x400424c2\n"             /* the record's own */
        "        .text\n");
#endif
#endif

#ifdef NEXT
/* The next image, on request
 *
 *
 * .
 * DEST is SMPL (a take goes where SMPL is, as before) or NEXT. Knob C is the track's KIND, STER or MONO: bit 6 of its own
 * word on slot 24 (engine/sampler.h, SRR_KIND), kept with the kit, no lock. A track on NEXT holds a free place of its
 * KIND, STER the lowest free stereo place, MONO the highest free single slot, as SMPL's stops find them (engine/sampler.h,
 * STOPS), and none another track holds; the box sends its takes there. When the stops say its place holds something,
 * the track's SMPL is put on it, forward or reversed as it was, and the track holds the next free one. No free place:
 * DEST_SMPL, a take where SMPL is. All in the main task, at each message (engine/once.S, once_loop), and past a test of
 * two longs only while some track is on NEXT; the slots are gone over only when the stops' four longs change, or a
 * DEST or KIND does. While the audio CPU is down (a start, samples sent) nothing held is believed. */
struct nx {
    u32 seen[4];                /* the stops' four longs as last gone over */
    u32 dirty;                  /* a DEST or a KIND changed, or nothing is believed: go over the slots */
    u8 on[8];                   /* track t's DEST is NEXT */
    u8 at[8];                   /* the place it holds, from 1; 0 none */
};
__asm__(".section .cave.nx1,\"ax\"\n"
        "        .globl next_vars\n"
        "next_vars:  .long 0, 0, 0, 0, 1, 0, 0, 0, 0\n"
        "            .text\n"
        ".section .cave.nx2,\"ax\"\n"
        "w_next:     .asciz \"NEXT\"\n"
        "w_kind:     .asciz \"KIND\"\n"
        "w_ster:     .asciz \"STER\"\n"
        "w_mono:     .asciz \"MONO\"\n"
        "            .even\n"
        "            .text\n");
extern struct nx next_vars;
extern const char w_next[], w_kind[], w_ster[], w_mono[];
#define NX (&next_vars)
#define NX_TYPE(t) (((const volatile u8 *)0x80006348)[PARAMS_STRIDE * (t) + PARAM_TYPE])    /* the track's machine, in the block the audio CPU is sent (engine/recword.S reads it there) */

CAVE_NX4 static u32 nx_mono(u32 t)
{
    u32 w = KIT ? OWN_WORDS(t)[K_REC] : 0;

    return SRR_SIGNED(w) && (w & SRR_KIND);
}

/* Track t's take is at place p: its SMPL to it, the way it was turned (64 up forward, 63 down reversed). */
CAVE_NX4 static void nx_smpl(u32 t, u32 p)
{
    volatile u16 *w = &OWN_WORDS(t)[K_SAMPLE];

    *w = ((*w >> 8) < 64 ? 63 - p : 64 + p) << 8;
}

/* Each track's DEST to the box: a NEXT track's place, or DEST_SMPL. */
CAVE_NX4 static void nx_box(volatile struct recbox *b)
{
    u32 t;

    for (t = 0; t < 8; t++)
        b->dest[t] = NX->on[t] && NX->at[t] ? NX->at[t] - 1u : DEST_SMPL;
}

CAVE_NX4 static void next_tell(volatile struct recbox *b, const u8 *dest)
{
    u32 t;

#ifdef DESTNUM
    for (t = 0; t < 8; t++) {           /* the destnum image: a number, never NEXT */
        NX->on[t] = 0;
        b->dest[t] = dest[t] ? dest[t] - 1u : DEST_SMPL;
    }
#else
    for (t = 0; t < 8; t++)
        if (!(NX->on[t] = dest[t] != 0))
            NX->at[t] = 0;
    nx_box(b);
    NX->dirty = 1;
#endif
}

CAVE_NX2 static void next_places(void *surface, const struct state *s, u32 t)
{
#if defined(DESTNUM)
    char n[3];
    u32 d = s->dest[t];

    n[0] = '0' + d / 10;                /* the destnum image: SMPL or the place's number */
    n[1] = '0' + d % 10;
    n[2] = 0;
    place(surface, 1, w_dest, d ? n : w_smpl);
#elif defined(ONEDEST)
    (void)s;
    place(surface, 1, w_dest, w_smpl);  /* the onedest image: SMPL, always */
#else
    place(surface, 1, w_dest, s->dest[t] ? w_next : w_smpl);
#endif
    place(surface, 2, w_kind, nx_mono(t) ? w_mono : w_ster);
}

CAVE_NX2 static void next_kind(u32 t, s32 steps)
{
    u32 w;

    if (!KIT || !steps || !SRR_SIGNED(w = OWN_WORDS(t)[K_REC]))
        return;
    OWN_WORDS(t)[K_REC] = steps > 0 ? w | SRR_KIND : w & ~SRR_KIND;
    NX->dirty = 1;
}

/* What slot n holds, as the audio CPU says it in the stops' four longs (l): 0 empty, 1 even, 2 one frame, 3 odd and more. */
#define NX_SLOT(l, n) ((l)[(n) >> 4] >> (30 - 2 * ((n) & 15)) & 3)

/* The slots have changed, or a DEST or a KIND has: the places held, still free or their take there, and a free one for
 * each NEXT track that has none. Place p is 0..31 stereo, its slots 2p and 2p + 1, or 32..63 a single slot; it is free
 * when its slots are, as stops() reads them: a slot is taken when it holds anything, or is the second half of a stereo
 * sample, or a track holds it. */
CAVE_NX5 static void nx_used(const u32 *l, u8 *used)
{
    u32 a;

    for (a = 0; a < N_SLOTS; a++)
        used[a] = NX_SLOT(l, a) || (a & 1 && NX_SLOT(l, a - 1) == 1);
}

/* The first free place of a kind, from 1 (STER the lowest, MONO the highest), or 0. */
CAVE_NX5 static u32 nx_find(const u8 *used, u32 mono)
{
    u32 v, p, a;

    for (v = 0; v < N_SLOTS / 2; v++) {
        p = mono ? N_SLOTS - 1 - v : v;
        a = p < N_SLOTS / 2 ? 2 * p : p;
        if (!used[a] && !used[a + (p < N_SLOTS / 2)])
            return p + 1;
    }
    return 0;
}

CAVE_NX3 static void nx_pass(const u32 *l)
{
    u8 used[N_SLOTS];
    u32 t, p, x, a, c;

    nx_used(l, used);
    for (c = 0; c < 2; c++)             /* the places held first, then a free one for each that has none */
        for (t = 0; t < 8; t++) {
            if (!NX->on[t] || NX_TYPE(t) != MACHINE_TYPE)
                continue;
            x = nx_mono(t);
            if (c == 0) {
                if (!(p = NX->at[t]))
                    continue;
                p--;
                NX->at[t] = 0;
                if ((p >= N_SLOTS / 2) != x)
                    continue;
                a = p < N_SLOTS / 2 ? 2 * p : p;
                if (used[a] || used[a + (p < N_SLOTS / 2)]) {
                    nx_smpl(t, p);      /* its take is there */
                    continue;
                }
            } else {
                if (NX->at[t] || !(p = nx_find(used, x)))
                    continue;
                p--;
                a = p < N_SLOTS / 2 ? 2 * p : p;
            }
            used[a] = used[a + (p < N_SLOTS / 2)] = 1;
            NX->at[t] = p + 1;
        }
    nx_box(REC_MAIN);
}

CAVE_NX void next_poll(void)
{
    const volatile u32 *from;
    u32 l[4], t, n, change = 0;

    if (!(((const u32 *)NX->on)[0] | ((const u32 *)NX->on)[1]))
        return;
    if (!AUDIO_UP || *STOPS_MARK(SHARED) != STOPS_OK || !KIT) {
        for (t = 0; t < 8; t++)         /* nothing of before is believed */
            NX->at[t] = 0;
        NX->dirty = 1;
        return;
    }
    for (from = STOPS_LONG(SHARED, 0), n = 0; n < 4; n++) {
        if (n == 2)
            from = STOPS_LONG(SHARED, 2);
        change |= (l[n] = *from++) ^ NX->seen[n];
    }
    if ((!change && !NX->dirty) || *STOPS_MARK(SHARED) != STOPS_OK)
        return;
    for (n = 0; n < 4; n++)
        NX->seen[n] = l[n];
    NX->dirty = 0;
    nx_pass(l);
}
#endif

#ifdef SKIND
/* The kind image (on the pbank image), the maintainer, 2026-10-26, of "SMPL follows KIND": "1 soinds like a nice fix", then "go". SMPL on the first
 * page stops only at the places of the track's KIND (the next image, above): STER the stereo places that hold a sample and
 * the lowest free one, MONO the single slots that hold one and the highest free one. A number keeps its meaning: a pattern,
 * a lock or an LFO on the other kind still plays it, and the knob goes from there to the nearest stop of the track's kind.
 * m: stops()'s 64, 0..31 the stereo places, 32..63 the single slots. -> 0: none of that kind, and the turn is stock's. */
CAVE_KS static u32 kind_stops(u8 *m, u32 t)
{
    u32 n, mono = nx_mono(t), any = 0;

    for (n = 0; n < N_SLOTS; n++)
        if ((n >= N_SLOTS / 2) != mono)
            m[n] = 0;
        else
            any |= m[n];
    return any;
}

#ifdef DESTNUM
/* The destnum image: DEST's stops are SMPL's by the track's KIND (the samples of that kind and its free place), after
 * SMPL itself; with no word from the audio CPU yet, it does not move. 0 SMPL, 1..32 the stereo places, 33..64 the single
 * slots. A number the knob no longer stops at goes to the nearest stop that way. */
CAVE_KS static u32 dest_moved(u32 d, s32 turn, u32 t)
{
    u8 m[N_SLOTS];
    s32 at = (s32)d, dir = turn > 0 ? 1 : -1;

    if (!stops(m))
        return d;
    kind_stops(m, t);
    while (turn && (at += dir) >= 0 && at <= N_SLOTS)
        if (!at || m[at - 1]) {
            d = (u32)at;
            turn -= dir;
        }
    return d;
}
#endif
#endif
