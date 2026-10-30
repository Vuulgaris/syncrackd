/* Main CPU (section 3, OS 1.42 only): the scratch image. A take is on the drive before the project is saved, so a
 * power off does not lose it, and it is still a take that has not been saved. On request
 * 
 *
 * The room. After our sector of the banks (BANK_MARK_SECTOR, 196 MB) the drive is free up to 244 MB (mainmap.DRIVE_FREE):
 * one sector of ours, the table, then 47 places of 1 MB, a slot's size. A place holds a take as a slot does, header
 * first. The table says which slot each place holds (the slot + 1, 0 none) and for which bank. Nothing here reaches a
 * sector of the three banks' runs but scratch_commit, through the store as every save does.
 *
 * Writing (hold_body, a job on stock's runner, where the takes are written at a save). The main task's loop calls
 * scratch_poll at each message (engine/once.S). When the feed's long (MB_FED: its count and which tracks were fed) has
 * moved since the last job and has not moved since the message before, the takes have stopped: a job goes over the 64
 * slots as keep_takes does, writes each take the drive does not have into its place (the place the slot had, or a free
 * one), the header last and only if the take is still the length it had, then the table, then tells the audio CPU the
 * take is kept. So a take is asked for once, and a new take in the slot clears that mark as it always did. 47 places:
 * a 48th slot's take is not held, and is lost at a power off as before.
 *
 * Back at a start (back_body, the first job, once the audio CPU is up and the bank is known): every place the table
 * gives for the loaded bank is sent to its slot as the loader sends the drive's samples (KEEP_PUT, three sectors a
 * request), and counts as kept. The slot plays the take, not the bank's sample.
 *
 * A save (scratch_commit, from engine/keeptakes.c, before keep_takes and in the same job): each place is copied into its
 * slot of the bank, the first sector last, the store's table read again, and the table emptied. keep_takes then writes
 * what is newer. A load (scratch_drop, from load_keep before the slots are loaded): the slots the table gives are
 * loaded from the bank like the slots the phone changed, and the table emptied: LOAD PROJECT still goes back to the
 * project as it was saved.
 *
 * The buffers are in the block the boot stages the pool in, 2 MB in, past the loader's slot (engine/keeptakes.c, SLOT_AT):
 * every job is on the one worker, so no two use it at once. */
#include "sampler.h"

#define AUDIO_UP (*(const volatile u32 *)0x43bdd824)
#define sample_store ((void *(*)(void))0x4016f292)
#define store_read ((s32 (*)(void *, u32, u32, void *))0x401100d4)
#define store_write ((s32 (*)(void *, u32, u32, const void *, const void *, u32))0x40111628)
#define sample_scan ((void (*)(void *, u32))0x4011149e)
#define job_runner ((void *(*)(void))0x4016ec18)
#define job_start ((void (*)(void *, const char *, void *, void *))0x400bdc48)     /* (runner, name, what to do, what to call after) */

#define SECTOR 512
#define SLOT_SECTORS 2048
#define SLOT_SECTOR0 8192
#define HEADER 64
#define PATIENCE 4000000
#define SAMP 0x53414d50
#define SCR_TABLE (BANK_MARK_SECTOR + 1)
#define SCR_FIRST (BANK_MARK_SECTOR + 2)
#define SCR_PLACES 47               /* (499,712 - 401,410) / 2048 */
#define SCR_MAGIC 0x53435254u       /* SCRT */
#define STAGE ((u8 *)0x4d84f2c0)
#define SLOT_AT ((u32 *)(STAGE + 0x100000))
#define TABLE ((u32 *)(STAGE + 0x200000))   /* [0] the mark, [1] the bank, [2 + p] place p's slot + 1, [127] the mark's complement */
#define SEC (TABLE + SECTOR / 4)
#define BIG (3 * SECTOR)

#define CAVE __attribute__((section(".cave.s"), noinline))          /* six runs: mainmap.CAVE_SCRATCH to CAVE_SCRATCH6 */
#define CAVE_HOLD __attribute__((section(".cave.t"), noinline))
#define CAVE_BACK __attribute__((section(".cave.u"), noinline))
#define CAVE2 __attribute__((section(".cave.w"), noinline))
#define CAVE_LABEL __attribute__((section(".cave.x"), noinline))
#define CAVE_JOB __attribute__((section(".cave.y"), noinline))

/* Three numbers, first in the run: a job is running, the start's job has been handed over, the feed's long the last
 * job was started for. And the feed's long at the message before. */
__asm__(".section .cave.s,\"ax\"\n"
        "        .globl scr_vars\n"
        "scr_vars:   .long 0, 0, 0, 0\n"
        "hold_name:  .asciz \"Take Hold\"\n"
        "back_name:  .asciz \"Take Back\"\n"
        "            .balign 2\n"
        "            .text\n");
extern volatile u32 scr_vars[4];
extern const char hold_name[], back_name[];
#define SCR_BUSY scr_vars[0]
#define SCR_UP scr_vars[1]
#define SCR_FED scr_vars[2]
#define SCR_SEEN scr_vars[3]

/* One request through the keep box (engine/keeptakes.c, ask). 0 when the audio CPU does not answer. */
CAVE static u32 scr_ask(u32 slot, u32 off)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 req = (b->ack + 1) & 0xffff;
    u32 n = PATIENCE;

    b->slot = slot;
    b->off = off;
    b->req = req;
    while (b->ack != req)
        if (!--n)
            return 0;
    return 1;
}

CAVE static s32 scr_put(void *store, u32 sector, const void *from)
{
    u32 none[3];                /* an empty progress callback for the store's write */

    none[0] = none[1] = none[2] = 0;
    return store_write(store, sector, SECTOR, from, none, 0);
}

/* The table into TABLE. Answers 1 when the drive has one for the loaded bank; otherwise TABLE is an empty one for it. */
CAVE static u32 table(void *store)
{
    u32 *t = TABLE, j;

    if (!store_read(store, SCR_TABLE, SECTOR, t) && t[0] == SCR_MAGIC && t[127] == ~SCR_MAGIC && t[1] == BANK_NOW)
        return 1;
    for (j = 0; j < SECTOR / 4; j++)
        t[j] = 0;
    t[0] = SCR_MAGIC;
    t[1] = BANK_NOW;
    t[127] = ~SCR_MAGIC;
    return 0;
}

/* The table emptied, on the drive. */
CAVE static void table_clear(void *store)
{
    u32 p;

    for (p = 0; p < SCR_PLACES; p++)
        TABLE[2 + p] = 0;
    scr_put(store, SCR_TABLE, TABLE);
}

/* n longs of the keep box's answer into d. */
CAVE_LABEL static void scr_take(u32 *d, u32 n)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 j;

    for (j = 0; j < n; j++)
        d[j] = b->data[j];
}

/* A take's first sector, as keep_takes writes it: the header, TAKE nn L with nn the stereo sample from 1, then the
 * answer's first 448 bytes. */
CAVE_LABEL static void label(u32 *sec, u32 slot, u32 frames)
{
    u32 j = (slot >> 1) + 1;

    sec[0] = SAMP;
    sec[1] = 0;
    sec[2] = frames;
    sec[3] = 0x54414b45;
    sec[4] = 0x20303020 + ((j / 10) << 16) + ((j % 10) << 8);
    sec[5] = (slot & 1 ? 'R' : 'L') << 24;
    for (j = 6; j < HEADER / 4; j++)
        sec[j] = 0;
    scr_take(sec + HEADER / 4, (SECTOR - HEADER) / 4);
}

/* The job: every take the drive does not have, into a place. */
CAVE_HOLD static u32 hold_body(const u32 *storage)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 *t = TABLE, *sec = SEC;
    void *store;
    u32 slot;

    (void)storage;
    if (!AUDIO_UP || BANK_NOW >= BANKS_N)
        goto out;
    store = sample_store();
    table(store);
    for (slot = 0; slot < N_SLOTS; slot++) {
        u32 frames, off, first, sector, p, at = SCR_PLACES;

        if (!scr_ask(slot, 0))
            break;
        frames = b->frames;
        if (!frames)
            continue;
        for (p = 0; p < SCR_PLACES; p++) {
            if (t[2 + p] == slot + 1)
                break;
            if (!t[2 + p] && at == SCR_PLACES)
                at = p;
        }
        if (p < SCR_PLACES) {                           /* the slot's place: not believed while it is written over */
            t[2 + p] = 0;
            if (scr_put(store, SCR_TABLE, t))
                break;
        } else if ((p = at) == SCR_PLACES)
            continue;                                   /* no place left */
        first = sector = SCR_FIRST + SLOT_SECTORS * p;
        for (off = SECTOR - HEADER; off < 2 * frames; off += SECTOR) {
            if (!scr_ask(slot, off))
                goto out;
            scr_take(sec, SECTOR / 4);
            if (scr_put(store, ++sector, sec))
                goto out;
        }
        if (!scr_ask(slot, 0))
            break;
        if (b->frames != frames)                        /* still growing: the next job */
            continue;
        label(sec, slot, frames);
        if (scr_put(store, first, sec))
            break;
        t[2 + p] = slot + 1;
        if (scr_put(store, SCR_TABLE, t))
            break;
        scr_ask(slot, KEEP_DONE);
    }
out:
    SCR_BUSY = 0;
    return 0;
}

/* A place's take into SLOT_AT, header first. Answers its bytes of samples, or ~0 when the drive does not read. */
CAVE_BACK static u32 place_read(void *store, u32 p)
{
    u32 sector = SCR_FIRST + SLOT_SECTORS * p, bytes = 0;

    STAGE[0] = 0;
    if (store_read(store, sector, SECTOR, SLOT_AT))
        return ~0u;
    if (SLOT_AT[0] == SAMP)
        bytes = 2 * (SLOT_AT[2] > REC_MAX ? REC_MAX : SLOT_AT[2]);
    if (bytes > SECTOR - HEADER && store_read(store, sector + 1, (bytes + HEADER - 1) / SECTOR * SECTOR, SLOT_AT + SECTOR / 4))
        return ~0u;
    return bytes;
}

/* The start's job: each place back in its slot, as the loader does it (engine/keeptakes.c, load_slots). */
CAVE_BACK static u32 back_body(const u32 *storage)
{
    volatile struct keepbox *b = KEEP_MAIN;
    volatile u32 *ring = (volatile u32 *)MB_MAIN->ring;
    void *store;
    u32 p;

    (void)storage;
    if (!AUDIO_UP || BANK_NOW >= BANKS_N)
        goto out;
    store = sample_store();
    if (!table(store))
        goto out;
    BANK_BUSY = 1;
    for (p = 0; p < SCR_PLACES; p++) {
        u32 slot = TABLE[2 + p] - 1, bytes, off, j;
        const u32 *from = SLOT_AT + HEADER / 4;

        if (slot >= N_SLOTS)
            continue;
        if ((bytes = place_read(store, p)) == ~0u)
            break;
        for (off = 0; off < bytes; off += BIG, from += BIG / 4) {
            for (j = 0; j < SECTOR / 4; j++)
                b->data[j] = from[j];
            for (j = 0; j < 2 * SECTOR / 4; j++)
                ring[j] = from[SECTOR / 4 + j];
            if (!scr_ask(slot | KEEP_PUT | KEEP_BIG, off))
                goto busy;
        }
        b->data[0] = bytes / 2;
        if (!scr_ask(slot | KEEP_PUT, KEEP_DONE))
            break;
    }
busy:
    BANK_BUSY = 0;
out:
    SCR_BUSY = 0;
    return 0;
}

/* A save: each place into its slot of the bank, the first sector last. The table is emptied only when all went. */
CAVE2 void scratch_commit(void)
{
    void *store;
    u32 p;

    if (BANK_NOW >= BANKS_N)
        return;
    store = sample_store();
    if (!table(store))
        return;
    for (p = 0; p < SCR_PLACES; p++) {
        u32 slot = TABLE[2 + p] - 1, bytes, n, first = SLOT_SECTOR0 + SLOT_SECTORS * slot;

        if (slot >= N_SLOTS)
            continue;
        if ((bytes = place_read(store, p)) == ~0u)
            return;
        for (n = 1; n * SECTOR < bytes + HEADER; n++)
            if (scr_put(store, first + n, SLOT_AT + n * (SECTOR / 4)))
                return;
        if (scr_put(store, first, SLOT_AT))
            return;
        sample_scan(store, slot);
    }
    table_clear(store);
}

/* A load: the slots the table gives are loaded from the bank, and the table emptied. */
CAVE2 void scratch_drop(void)
{
    void *store;
    u32 p;

    if (BANK_NOW >= BANKS_N)
        return;
    store = sample_store();
    if (!table(store))
        return;
    for (p = 0; p < SCR_PLACES; p++) {
        u32 slot = TABLE[2 + p] - 1;

        if (slot < N_SLOTS)
            PHONE_MASK[slot >> 5] |= 1u << (slot & 31);
    }
    table_clear(store);
}

#ifdef EVICT
/* The evict image: the slots in the phone's mask, about to be loaded from the bank by the phone's reload (0x6B), lose
 * their places, so neither a save (scratch_commit) nor a start (back_body) brings a take the phone wrote over back. */
__attribute__((section(".cave.e"), noinline)) void scratch_forget(void)
{
    void *store;
    u32 p, slot, gone = 0;

    if (BANK_NOW >= BANKS_N)
        return;
    store = sample_store();
    if (!table(store))
        return;
    for (p = 0; p < SCR_PLACES; p++)
        if ((slot = TABLE[2 + p] - 1) < N_SLOTS && (PHONE_MASK[slot >> 5] & (1u << (slot & 31)))) {
            TABLE[2 + p] = 0;
            gone = 1;
        }
    if (gone)
        scr_put(store, SCR_TABLE, TABLE);
}
#endif

struct fn {                     /* a function object as stock's code lays one out (engine/keeptakes.c) */
    u32 store[2];
    u32 (*manage)(u32 *to, const u32 *from, u32 what);
    void *call;
};

CAVE_JOB static u32 fn_manage(u32 *to, const u32 *from, u32 what)
{
    if (what == 1)
        to[0] = (u32)from;
    else if (what == 2) {
        to[0] = from[0];
        to[1] = from[1];
    } else if (!what)
        to[0] = 0;
    return 0;
}

CAVE_JOB static void fn_done(void)
{
}

CAVE_JOB static void start(const char *name, void *body)
{
    struct fn what, done;

    SCR_BUSY = 1;
    what.store[0] = what.store[1] = done.store[0] = done.store[1] = 0;
    what.manage = done.manage = fn_manage;
    what.call = body;
    done.call = fn_done;
    job_start(job_runner(), name, &what, &done);
}

/* From the main task's loop, at each message (engine/once.S). */
CAVE_JOB void scratch_poll(void)
{
    u32 fed;

    if (!AUDIO_UP || SCR_BUSY || SAVE_STATE == SAVE_BUSY || BANK_NOW >= BANKS_N)
        return;
    fed = MB_FED(0x10000000u);
    if (!SCR_UP) {
        SCR_UP = 1;
        SCR_FED = SCR_SEEN = fed;
        start(back_name, back_body);
        return;
    }
    if (fed != SCR_SEEN) {                  /* still being fed, or just now */
        SCR_SEEN = fed;
        return;
    }
    if (fed == SCR_FED)
        return;
    SCR_FED = fed;
    start(hold_name, hold_body);
}
