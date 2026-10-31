/* Main CPU (section 3, OS 1.42 only, with the larger slots): keeps takes.
 *
 * Replaces the two calls to the routine that saves a project to the +Drive, the ones behind SAVE PROJECT. It calls
 * that routine, and when the save went well it writes every take that is not on the drive yet into the take's two
 * sample slots. So this runs where stock itself is writing the drive, in the job that shows SAVING, and nowhere else.
 *
 * The take is in the audio CPU's memory. It is asked for 512 bytes at a time through the shared window (struct
 * keepbox, engine/sampler.h; the audio CPU's side is keep_step in engine/sampler.c), one drive sector a request. A
 * slot's first sector, with its header, is written last and only if the take is still the length it had: until then
 * the drive holds the old header.
 *
 * Nothing is kept here between calls. The audio CPU remembers which takes are on the drive.
 *
 * The window is read and written in words and longs only, as stock does.
 *
 * The samples go the other way through the same box, one piece a request (KEEP_PUT in engine/sampler.h). The drive is
 * only read.
 *
 * Built with BANKS too (the bank image, with engine/banks.c): a save also notes the project's bank, and a load of a
 * project on another bank loads every slot. The load's code then sits with the banks', for room.
 *
 * Built with SAVE too (the save image): the takes can be written without the project, from the sampling page.
 * save_start() hands stock's runner of jobs a job of ours, which calls keep_takes in the runner's worker, where SAVE
 * PROJECT's own job runs. A job is started with (the runner, a name, what to do, what to call after): the last two
 * are function objects of 16 bytes, 8 of storage, then a routine that copies or ends the storage, then the routine to
 * call. Stock copies one by calling its second routine with (to, from, 2) and ends one with (it, it, 3); ours keep
 * nothing in the storage, so there is nothing to do for either but copy 8 bytes. What a job does answers 0 when it
 * went well. SAVE_STATE (engine/sampler.h) says how ours is going; it is set by the job itself when it ends, so
 * nothing waits on the second object being called.
 *
 * Built with PTN too (the ptn image): the takes are also written when a whole pattern is saved to the project. The
 * two calls of stock's pattern save that the pattern menu's SAVE TO PROJ, WHOLE PATTERN ends in go to ptn_keep, which
 * calls stock's routine and, when that went well, starts the job above. Nothing is written where the pattern is
 * saved: a full take is seconds of drive writes, and that is the task the keys and the screen are served in. And on
 * this image a take that changed while it was written is left for the next save and the slots after it are still
 * written, where the run ended; the run still answers that not every take is on the drive.
 *
 * Built with SCRATCH too (the scratch image, engine/scratch.c): a save first copies the takes held on the drive into
 * the bank, and a load first has the slots they are in loaded from the bank. */
#include "sampler.h"

#ifdef SCRATCH
void scratch_commit(void);      /* engine/scratch.c */
void scratch_drop(void);
#endif
#ifdef EVICT
void scratch_forget(void);    /* engine/scratch.c */
#endif
#define AUDIO_UP (*(const volatile u32 *)0x43bdd824)
#define project_save ((u32 (*)(void *, void *, void *))0x4001a82e)
#define sample_store ((void *(*)(void))0x4016f292)
#define store_write ((s32 (*)(void *, u32, u32, const void *, const void *, u32))0x40111628)
#define sample_scan ((void (*)(void *, u32))0x4011149e)

#define SECTOR 512
#define SLOT_SECTORS 2048       /* the larger slots: 1 MB each */
#define SLOT_SECTOR0 8192
#define HEADER 64               /* 'SAMP', 0, frames, a name of 16, zeros */
#define PATIENCE 4000000        /* reads of the window before giving up; an answer takes one audio block */

#define CAVE __attribute__((section(".cave.k"), noinline))

#ifdef SAVE
/* The number first, where engine/sampler.h says it is; then the job's name. */
__asm__(".section .cave.k,\"ax\",@progbits\n"
        "save_state: .long 0\n"
        "save_name:  .asciz \"Take Save\"\n"
        "            .even\n"
        "            .text\n");
extern const char save_name[];
#define KEEP_T u32
#define KEEP_END(v) return (v)
#else
#define KEEP_T void
#define KEEP_END(v) return
#endif

/* One request. 0 when the audio CPU does not answer. */
CAVE static u32 ask(u32 slot, u32 off)
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

/* The answer's first n longs into a sector buffer. Longs: the window is not read a byte at a time. */
CAVE static void take(u32 *d, u32 n)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 j;

    for (j = 0; j < n; j++)
        d[j] = b->data[j];
}

/* With SAVE it answers: 0 when every take that was not on the drive now is, or there was none. */
CAVE static KEEP_T keep_takes(void)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 sec[SECTOR / 4];
    u32 none[3];                /* an empty progress callback for the store's write */
    void *store;
    u32 slot;
#ifdef PTN
    u32 left = 0;               /* a take was left for the next save */
#endif

    if (!AUDIO_UP)
        KEEP_END(1);
    store = sample_store();
    none[0] = none[1] = none[2] = 0;
    for (slot = 0; slot < N_SLOTS; slot++) {
        u32 first = SLOT_SECTOR0 + SLOT_SECTORS * slot;
        u32 frames, off, sector, j;

        if (!ask(slot, 0))
            KEEP_END(1);
        frames = b->frames;
        if (!frames)
            continue;
        sector = first;
        for (off = SECTOR - HEADER; off < 2 * frames; off += SECTOR) {
            if (!ask(slot, off))
                KEEP_END(1);
            take(sec, SECTOR / 4);
            if (store_write(store, ++sector, SECTOR, sec, none, 0))
                KEEP_END(1);
        }
#ifdef PTN
        if (!ask(slot, 0))
            KEEP_END(1);
        if (b->frames != frames) {                      /* a take that changed under us waits for the next save: on to the next slot */
            left = 1;
            continue;
        }
#else
        if (!ask(slot, 0) || b->frames != frames)       /* a take that changed under us waits for the next save */
            KEEP_END(1);
#endif
        sec[0] = 0x53414d50;                            /* SAMP */
        sec[1] = 0;
        sec[2] = frames;
        sec[3] = 0x54414b45;                            /* TAKE nn L, nn the stereo sample from 1 */
        j = (slot >> 1) + 1;
        sec[4] = 0x20303020 + ((j / 10) << 16) + ((j % 10) << 8);
        sec[5] = (slot & 1 ? 'R' : 'L') << 24;
        for (j = 6; j < HEADER / 4; j++)
            sec[j] = 0;
        take(sec + HEADER / 4, (SECTOR - HEADER) / 4);
        if (store_write(store, first, SECTOR, sec, none, 0))
            KEEP_END(1);
        sample_scan(store, slot);
        ask(slot, KEEP_DONE);
    }
#ifdef PTN
    KEEP_END(left);
#else
    KEEP_END(0);
#endif
}

#ifdef SAVE
#define job_runner ((void *(*)(void))0x4016ec18)
#define job_start ((void (*)(void *, const char *, void *, void *))0x400bdc48)     /* (runner, name, what to do, what to call after) */

struct fn {                     /* a function object as stock's code lays one out */
    u32 store[2];
    u32 (*manage)(u32 *to, const u32 *from, u32 what);
    void *call;
};

/* What stock asks of a function object's storage: 1 where it is, 2 a copy, 3 its end, 0 its type. */
CAVE static u32 fn_manage(u32 *to, const u32 *from, u32 what)
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

/* The job: the takes, and how it went. */
CAVE static u32 save_body(const u32 *storage)
{
#ifdef SCRATCH
    u32 failed;

    scratch_commit();                       /* the scratch image: the held takes into the bank first, then what is newer */
    failed = keep_takes();
#else
    u32 failed = keep_takes();
#endif

    (void)storage;
    SAVE_STATE = failed ? SAVE_FAIL : SAVE_DONE;
    return failed;
}

CAVE static void save_done(void)
{
}

/* From the sampling page: start a save of the takes, unless one is running. */
CAVE void save_start(void)
{
    struct fn body, done;

    if (SAVE_STATE == SAVE_BUSY)
        return;
    SAVE_STATE = SAVE_BUSY;
    body.store[0] = body.store[1] = done.store[0] = done.store[1] = 0;
    body.manage = done.manage = fn_manage;
    body.call = save_body;
    done.call = save_done;
    job_start(job_runner(), save_name, &body, &done);
}
#endif

#ifdef BANKS
void bank_saved(u32 project);
u32 bank_loaded(u32 project);
#define LCAVE __attribute__((section(".cave.b"), noinline))
#else
#define LCAVE CAVE
#endif

CAVE u32 save_keep(void *manager, void *project, void *progress)
{
    u32 ok = project_save(manager, project, progress);

    if (ok & 0xff) {
#ifdef SCRATCH
        scratch_commit();
#endif
        keep_takes();
#ifdef BANKS
        bank_saved((u32)project);
#endif
    }
    return ok;
}

#ifdef PTN
/* The ptn image: in the place of stock's pattern save, where a whole pattern is saved to the project. Stock's routine
 * first, with what it was given; its answer is a byte, and the rest of the long is whatever was there. Then the job
 * that writes the takes, which says itself when one is running. */
#define pattern_save ((u32 (*)(void *, u32, u32, u32, u32))0x4001a8d2)     /* (manager, to the temp area, pattern, sequence, kit) */

CAVE u32 ptn_keep(void *manager, u32 temp, u32 pattern, u32 seq, u32 kit)
{
    u32 ok = pattern_save(manager, temp, pattern, seq, kit);

    if (ok & 0xff)
        save_start();
    return ok;
}
#endif

#ifdef LOAD
#define project_load ((u32 (*)(void *, void *, void *))0x4001d6fe)
#define store_read ((s32 (*)(void *, u32, u32, void *))0x401100d4)

#ifndef BANKS
/* The slots that hold a take the drive does not have get the drive's samples back. */
CAVE static void load_slots(void)
{
    volatile struct keepbox *b = KEEP_MAIN;
    u32 sec[SECTOR / 4];
    void *store;
    u32 slot;

    if (!AUDIO_UP)
        return;
    store = sample_store();
    for (slot = 0; slot < N_SLOTS; slot++) {
        u32 sector = SLOT_SECTOR0 + SLOT_SECTORS * slot;
        const u32 *from = sec + HEADER / 4;     /* the first sector: the header, then 448 bytes of samples */
        u32 bytes = 0, off = 0, n = SECTOR - HEADER, j;

        if (!ask(slot, 0))
            return;
        if (!b->frames)                         /* no take, or one the drive has */
            continue;
        if (store_read(store, sector, SECTOR, sec))
            return;
        if (sec[0] == 0x53414d50)               /* SAMP: a slot with nothing in it is loaded as that */
            bytes = 2 * (sec[2] > REC_MAX ? REC_MAX : sec[2]);
        while (off < bytes) {                   /* a sector of the drive a request */
            for (j = 0; j < n / 4; j++)
                b->data[j] = from[j];
            if (!ask(slot | KEEP_PUT, off))
                return;
            off += n;
            n = SECTOR;
            from = sec;
            if (off < bytes && store_read(store, ++sector, SECTOR, sec))
                return;
        }
        b->data[0] = bytes / 2;
        if (!ask(slot | KEEP_PUT, KEEP_DONE))
            return;
    }
}

CAVE u32 load_keep(void *manager, void *project, void *progress)
{
    u32 ok = project_load(manager, project, progress);

    if (ok & 0xff)
        load_slots();
    return ok;
}
#else
/* The bank image's load. So here a slot is read from the drive in two reads, into the block the boot stages the pool
 * in (32 MB, idle once the unit is up; a megabyte in, clear of the boot's own first bytes, and its mark is cleared so
 * that a boot exchange that ever ran again would stage afresh), and sent three sectors a request: one in the box, two
 * in the recorder's ring, which the feed keeps out of while BANK_BUSY says so (engine/recfeed.c).
 *
 * all: every slot, as the drive has it now. Otherwise the slots that hold a take the drive does not have.
 *
 * The LOADING screen's bar is moved a slot at a time, through the routine stock's own load moves it with (0x401758e8:
 * the job's progress object, done, of how many; nothing if the object's third long is 0), so that a full bank, which
 * still takes most of a minute, is seen to be going. */
#define progress_step ((void (*)(void *, u32, u32))0x401758e8)
#define STAGE ((u8 *)0x4d84f2c0)
#ifdef STREAM
/* The stream image's numbers: the slots the phone has written since a load and asked for (0x6B), its job queued or
 * running, and a reload under way. */
__asm__(".section .cave.c,\"ax\",@progbits\n"
        "        .balign 4\n"
        "        .globl stream_bits, stream_busy, stream_now\n"
        "stream_bits:  .long 0, 0\n"
        "stream_busy:  .long 0\n"
        "stream_now:   .long 0\n"
        "stream_name:  .asciz \"Sample Load\"\n"
        "        .balign 2\n"
        "        .text\n");
extern volatile u32 stream_bits[2], stream_busy, stream_now;
extern const char stream_name[];
#endif
#define SLOT_AT ((u32 *)(STAGE + 0x100000))
#define BIG (3 * SECTOR)

LCAVE static u32 put(u32 slot, u32 off)     /* ask() is too far for a short call from this run */
{
    return ask(slot, off);
}

LCAVE static void load_slots(u32 all, void *progress)
{
    volatile struct keepbox *b = KEEP_MAIN;
    volatile u32 *ring = (volatile u32 *)MB_MAIN->ring;
    void *store;
    u32 slot;

    if (!AUDIO_UP)
        return;
    store = sample_store();
    BANK_BUSY = 1;
    for (slot = 0; slot < N_SLOTS; slot++) {
        u32 sector = SLOT_SECTOR0 + SLOT_SECTORS * slot;
        const u32 *from = SLOT_AT + HEADER / 4;
        u32 bytes = 0, off, j;

        if (progress && ((const u32 *)progress)[2])
            progress_step(progress, slot + 1, N_SLOTS);
        if (!all) {
#ifdef PHONE
            if (!(PHONE_MASK[slot >> 5] & (1u << (slot & 31)))) {      /* the phone changed it: load it */
#endif
#ifdef STREAM
            if (stream_now)                     /* the stream image's reload: the phone's slots alone */
                continue;
#endif
            if (!put(slot, 0))
                break;
            if (!b->frames)                     /* no take, or one the drive has */
                continue;
#ifdef PHONE
            }
#endif
        }
        STAGE[0] = 0;
        if (store_read(store, sector, SECTOR, SLOT_AT))
            break;
        if (SLOT_AT[0] == 0x53414d50)           /* SAMP: a slot with nothing in it is loaded as that */
            bytes = 2 * (SLOT_AT[2] > REC_MAX ? REC_MAX : SLOT_AT[2]);
        if (bytes > SECTOR - HEADER             /* the rest of it in one read, in whole sectors */
            && store_read(store, sector + 1, (bytes + HEADER - 1) / SECTOR * SECTOR, SLOT_AT + SECTOR / 4))
            break;
        for (off = 0; off < bytes; off += BIG, from += BIG / 4) {
            for (j = 0; j < SECTOR / 4; j++)
                b->data[j] = from[j];
            for (j = 0; j < 2 * SECTOR / 4; j++)
                ring[j] = from[SECTOR / 4 + j];
            if (!put(slot | KEEP_PUT | KEEP_BIG, off))
                goto out;
        }
        b->data[0] = bytes / 2;
        if (!put(slot | KEEP_PUT, KEEP_DONE))
            break;
    }
out:
    BANK_BUSY = 0;
}

LCAVE u32 load_keep(void *manager, void *project, void *progress)
{
    u32 ok = project_load(manager, project, progress);

#ifdef SCRATCH
    if (ok & 0xff) {
        scratch_drop();                     /* the scratch image: before the bank can change */
        load_slots(bank_loaded((u32)project), progress);
    }
#else
    if (ok & 0xff)
        load_slots(bank_loaded((u32)project), progress);
#endif
    return ok;
}

#ifdef NEWPROJ
/* The newproj image: NEW PROJECT has no project to load. The slots the phone names, as LOAD PROJECT loads them, and
 * the held takes dropped as a load drops them (engine/phone.c, fresh_make). */
LCAVE void new_slots(void)
{
#ifdef SCRATCH
    scratch_drop();
#endif
    load_slots(0, 0);
}
#endif

#ifdef STREAM
/* Now the phone empties at the load every slot that is not the project's (0x6A), and once the load is done writes the
 * project's samples, saying each slot written with 0x6B (engine/phone.c). Each is loaded here as the load loads the
 * phone's (the phone's mask: no load waits on it while this job runs, the one worker), by a job on stock's runner,
 * one slot after another as they come; a slot that holds a take the drive does not have keeps it. The two sides meet
 * only in stream_bits, set and cleared by one instruction each. */
#define AAVE __attribute__((section(".cave.a"), noinline))
#define CCAVE __attribute__((section(".cave.c"), noinline))

AAVE static u32 stream_body(const u32 *storage)
{
#ifdef EVICT
    u32 lo, hi;
#else
    volatile struct keepbox *b = KEEP_MAIN;
    u32 lo, hi, slot;
#endif

    (void)storage;
    for (;;) {
        lo = stream_bits[0];
        hi = stream_bits[1];
        __asm__ volatile("and.l %1,%0" : "+m"(stream_bits[0]) : "d"(~lo));
        __asm__ volatile("and.l %1,%0" : "+m"(stream_bits[1]) : "d"(~hi));
        if (lo | hi) {
            PHONE_MASK[0] = lo;
            PHONE_MASK[1] = hi;
#ifdef EVICT
            scratch_forget();               /* the evict image: the phone's sample over a take not saved, its held copy gone */
#else
            for (slot = 0; slot < N_SLOTS && AUDIO_UP; slot++)
                if ((PHONE_MASK[slot >> 5] & (1u << (slot & 31))) && put(slot, 0) && b->frames)
                    PHONE_MASK[slot >> 5] &= ~(1u << (slot & 31));      /* a take not saved: kept */
#endif
            stream_now = 1;
            load_slots(0, 0);
            stream_now = 0;
            PHONE_MASK[0] = PHONE_MASK[1] = 0;
            continue;
        }
        stream_busy = 0;                    /* then once more: a 0x6B between the look and here started no job */
        if (!(stream_bits[0] | stream_bits[1]))
            return 0;
        stream_busy = 1;
    }
}

/* From the SysEx entry (engine/phone.c), 0x6B: the slots, and a job to load them unless one is queued or running. */
CCAVE void stream_add(u32 lo, u32 hi)
{
    struct fn body, done;

    __asm__ volatile("or.l %1,%0" : "+m"(stream_bits[0]) : "d"(lo));
    __asm__ volatile("or.l %1,%0" : "+m"(stream_bits[1]) : "d"(hi));
    if (stream_busy || !(lo | hi))
        return;
    stream_busy = 1;
    body.store[0] = body.store[1] = done.store[0] = done.store[1] = 0;
    body.manage = done.manage = fn_manage;
    body.call = stream_body;
    done.call = save_done;
    job_start(job_runner(), stream_name, &body, &done);
}
#endif
#endif
#endif
