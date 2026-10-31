/* Main CPU (section 3, OS 1.42 only): the phone image. Built with engine/keeptakes.c and engine/banks.c
 * (LOAD, BANKS, SAVE, PTN, PHONE), and in a run of its own.
 *
 * At LOAD PROJECT, before stock's load, the unit asks the phone which of the project's bank's slots it has
 * changed, waits for the answer, and then loads the project as before, with those slots (and only those)
 * sent to the audio CPU as well as the takes the load always restores. No phone, no answer, a timeout: the
 * load is stock's and ours as it was, a few seconds later at the most.
 *
 *   unit to phone  0x60  project number (2 x 7 bits), bank (0 to 2)
 *   phone to unit  0x62  "working": any frame of it renews the wait
 *   phone to unit  0x61  "done": ten bytes of 7 bits, the slots (0 to 63) it wrote, bit n % 7 of byte n / 7
 *
 * Every id is one the unit's parser does not know (docs/FINDINGS.md, "The file protocol, for the phone"), so
 * a frame of these is harmless on any image without this hook. The frames use the unit's own SysEx sink: it
 * exists once the unit has had any message, and until then there is no phone to ask.
 *
 * What stands behind it (docs/FINDINGS.md, "The phone image's two unknowns, read" and "designed"): the
 * kernel's wait and give on a three-word object, its timer table (a callback every 2^k ticks), the SysEx
 * entry's one jump. The phone writes with the ordinary write commands, and those go to the bank the drive
 * routines are pointed at, so the unit points them at the project's bank for the wait and puts them back
 * before stock's load, which then makes its own bank switch and loads every slot if there is one.
 */
#include "sampler.h"

#define sample_store ((void *(*)(void))0x4016f292)
#define store_read ((s32 (*)(void *, u32, u32, void *))0x401100d4)
#define scan_all ((void (*)(void *))0x401115ea)     /* (store): every slot's header into the store's table */
#define kwait ((void (*)(volatile u32 *))0x40001792)
#define kgive ((void (*)(volatile u32 *))0x400018d4)
#define timer_set ((void (*)(void (*)(void), u32))0x40002de8)
#define timer_cancel ((void (*)(void (*)(void)))0x40002ea4)
#define rpc_handle ((void (*)(const u8 *, u32, u32))0x40109d0c)
#define SINK ((void *)0x4449c51c)
#define SINK_MADE (*(volatile u32 *)0x4449c808)     /* not 0 once the unit has had a message */
#define CLOCK (*(volatile u32 *)0xfc07000c)         /* the first timer: about 132 MHz (docs/FINDINGS.md) */
#ifdef WIPE
u32 wipe_load(void *manager, void *project, void *progress);     /* the wipe image: the phone's empty slots, then the load */
#define load_keep wipe_load
#define keep_load ((u32 (*)(void *, void *, void *))LOAD_KEEP_AT)
#else
#define load_keep ((u32 (*)(void *, void *, void *))LOAD_KEEP_AT)
#endif

#define FIRST_WAIT 264000000u       /* about 2 s: the phone answers or there is none */
#define WORK_WAIT 528000000u        /* about 4 s since the phone last said it was working */

/* The ask image (-DSEEN): the phone has said 0x63 (or 0x65, 0x66) since the start. Any host's message makes the sink, so
 * without it every LOAD PROJECT after Transfer, slink or the viewer waited FIRST_WAIT for a phone that is not there. */
#ifdef SEEN
#define SEEN_VAR "        .globl phone_seen\nphone_seen:   .long 0\n"
#else
#define SEEN_VAR ""
#endif

/* The newproj image (-DNEWPROJ): the ask also says the project left, 2 x 7 bits, 0x3fff for one never saved. */
#ifdef NEWPROJ
#define FRAME_N 19
#define FRAME_TAIL "0, 0, 0, 0, 0x7f, 0x7f, 0xf7"
#else
#define FRAME_N 17
#define FRAME_TAIL "0, 0, 0, 0, 0xf7"
#endif
#ifdef WIPE
#define WIPE_VAR "        .globl wipe_on\nwipe_on:      .long 0\n"
#else
#define WIPE_VAR ""
#endif

/* The numbers, alone in a run of their own: the mask first, where engine/sampler.h says it is. */
__asm__(".section .cave.v,\"ax\",@progbits\n"
        "        .globl phone_mask, phone_sem, phone_start, phone_limit, phone_state, phone_answer\n"
        "phone_mask:   .long 0, 0\n"
        "phone_sem:    .long 0, 0, 0\n"
        "phone_start:  .long 0\n"
        "phone_limit:  .long 0\n"
        "phone_state:  .long 0\n"
        "phone_answer: .long 0\n"
        "        .globl phone_frame\n"
        "phone_frame:  .byte 0xf0, 0x00, 0x20, 0x3c, 0x10, 0x00, 0, 0, 1, 0, 0, 0x60, " FRAME_TAIL "\n"
        "        .even\n"
        SEEN_VAR
        WIPE_VAR
        "        .text\n");
extern volatile u8 phone_frame[FRAME_N];
extern volatile u32 phone_mask[2], phone_sem[3], phone_start, phone_limit, phone_state, phone_answer;
#ifdef SEEN
extern volatile u32 phone_seen;
#endif
#ifdef WIPE
void wipe_now(void);
#endif
#ifdef NEWPROJ
void left_is(s32 left);         /* the newproj image: the project left, into the ask's last two bytes */
#endif

/* Two runs: p, called directly; q, only reached by an address (the jump, the timer, a pointer): the runs
 * are further apart than a short call reaches. */
#define CAVE __attribute__((section(".cave.p"), noinline))
#define QAVE __attribute__((section(".cave.q"), noinline))

/* The bank a project was saved with, as banks.c's bank_loaded works it out, and nothing written. */
QAVE static u32 project_bank(void *store, u32 project, u32 now)
{
    u32 sec[512 / 4];
    const struct bankmark *m = (const struct bankmark *)sec;

    if (project >= 128 || store_read(store, BANK_MARK_SECTOR, 512, sec))
        return now;
    if (m->magic != BANK_MAGIC || m->magic2 != ~BANK_MAGIC)
        return 0;
    return m->of[project] < BANKS_N ? m->of[project] : 0;
}

/* Called by the timer task every 2^k ticks while the wait runs. */
QAVE static void tick(void)
{
    if (CLOCK - phone_start >= phone_limit)
        kgive(phone_sem);
}

CAVE static void ask(u32 project, u32 bank)
{
    void **vt = *(void ***)SINK;

    phone_frame[12] = project & 0x7f;
    phone_frame[13] = (project >> 7) & 0x7f;
    phone_frame[15] = bank & 0x7f;
    ((void (*)(void *, const volatile u8 *, u32))vt[4])(SINK, phone_frame, FRAME_N);
    ((void (*)(void *))vt[3])(SINK);
}

/* The call of stock's load in the Project Load job, (manager, project, progress). */
CAVE u32 phone_load(void *manager, void *project, void *progress)
{
    u32 ok;

#ifdef SEEN
    if (SINK_MADE && phone_seen) {
#else
    if (SINK_MADE) {
#endif
        u32 p = (u32)project, saved = BANK_NOW, bank = saved;
        void *store = sample_store();
        u32 (*volatile pb)(void *, u32, u32) = project_bank;       /* a run away: by its address */

        if (saved < BANKS_N)
            bank = pb(store, p, saved);
        phone_mask[0] = phone_mask[1] = 0;
        phone_answer = 0;
        phone_sem[0] = phone_sem[1] = phone_sem[2] = 0;
        if (saved < BANKS_N && bank != saved) {
            BANK_NOW = bank;                    /* the phone's reads and writes are this bank's */
            scan_all(store);
        }
        ask(p, bank);
        phone_start = CLOCK;
        phone_limit = FIRST_WAIT;
        phone_state = 1;
        timer_set(tick, 0x20);
        kwait(phone_sem);
        phone_state = 0;
        timer_cancel(tick);
        phone_sem[0] = 0;
        if (saved < BANKS_N && bank != saved) {
            BANK_NOW = saved;                   /* stock's load makes its own switch, and loads every slot */
            scan_all(store);
        }
    }
    ok = load_keep(manager, project, progress);
    phone_mask[0] = phone_mask[1] = 0;
    return ok;
}

/* The SysEx entry's one jump: (data past the header, its length, the interface). A frame of ours is
 * taken here and not handed on; anything else goes where it went. */
QAVE void phone_sysex(const u8 *data, u32 len, u32 iface)
{
    if (len >= 6 && (data[5] == 0x61 || data[5] == 0x62)) {
        if (phone_state) {
            if (data[5] == 0x62) {
                phone_start = CLOCK;
                phone_limit = WORK_WAIT;
            } else if (len >= 18) {
                u32 j, lo = 0, hi = 0;
                /* message bytes 5 to 14 are at 6, 7, 9 to 15 and 17 of the packed data (a high-bits byte leads each seven) */
                for (j = 0; j < 5; j++)
                    lo |= (u32)(data[j < 2 ? 6 + j : 7 + j] & 0x7f) << (7 * j);
                for (j = 0; j < 5; j++)
                    hi |= (u32)(data[j < 4 ? 12 + j : 17] & 0x7f) << (7 * j);
                phone_mask[0] = lo;
                phone_mask[1] = hi;
                phone_answer = 1;
                kgive(phone_sem);
            }
        }
        return;
    }
    rpc_handle(data, len, iface);
}

#ifdef KNOWS
/* The fltr image: the phone may ask which project the unit last loaded (asked for by the phone app, 2026-10-16),
 * so that a take is filed back into the right project's bank with no doubt about a load it did not see.
 *
 *   phone to unit  0x63  no arguments
 *   unit to phone  0x64  project (2 x 7 bits; 0x3fff: none since the start), its bank (0 to 2), the loads since the
 *                        start (3 x 7 bits), the start's id (3 x 7 bits)
 *
 * Before any load since the start (the count 0) the project is the one the unit started with, as SAVE PROJECT would
 * save to (`0x40018c2c`; `7f 7f` for one never saved), and the bank the drive's now: the start-up is not a load through
 * the Project Load job (2026-10-17: so the phone is told of the start-up too).
 *
 * Every load counts, a phone there or not: the load call and the SysEx entry's jump come here first, and go on to
 * the phone image's routines as they are. The start's id is the first timer's low 21 bits the first time one is
 * asked for (0 is made 1): nothing of this run is kept across a start (the image is loaded afresh), so it is 0 until
 * then. In a run of its own. */
#define RAVE __attribute__((section(".cave.r"), noinline))
#define manager_of ((void *(*)(void))0x4016e9c8)        /* stock's project manager, made at its first call long before */
#define project_now ((s32 (*)(void *))0x40018c2c)        /* (manager): the project's number, the byte at 0x40653441; -1 never saved */

__asm__(".section .cave.r,\"ax\",@progbits\n"
        "        .globl knows_project, knows_bank, knows_count, knows_boot, knows_frame\n"
        "knows_project: .long 0x3fff\n"
        "knows_bank:    .long 0\n"
        "knows_count:   .long 0\n"
        "knows_boot:    .long 0\n"
        "knows_frame:   .byte 0xf0, 0x00, 0x20, 0x3c, 0x10, 0x00, 0, 0, 1, 0, 0, 0x64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xf7\n"
        "        .even\n"
        "        .text\n");
extern volatile u8 knows_frame[23];
extern volatile u32 knows_project, knows_bank, knows_count, knows_boot;

RAVE static u32 knows_id(void)
{
    u32 c = CLOCK & 0x1fffff;

    if (!knows_boot)
        knows_boot = c ? c : 1;
    return knows_boot;
}

RAVE u32 knows_load(void *manager, void *project, void *progress)
{
    u32 p = (u32)project, bank = BANK_NOW;

    if (bank < BANKS_N)
        bank = project_bank(sample_store(), p, bank);
    knows_id();
    knows_project = p;
    knows_bank = bank;
    knows_count++;
    return phone_load(manager, project, progress);
}

RAVE void knows_sysex(const u8 *data, u32 len, u32 iface)
{
    void **vt;
    u32 p, n, b, bank;

#ifdef CAPTURE
    /* The rxcap image: the phone's capture on (0x65) and off (0x66), no arguments, nothing answered (engine/rxgate.S). */
    if (len >= 6 && (data[5] == 0x65 || data[5] == 0x66)) {
#ifdef SEEN
        phone_seen = 1;
#endif
        *(volatile u32 *)CAPTURE_AT = data[5] == 0x65;
        return;
    }
#endif
#ifdef MIRROR
    /* The mirror image: the viewer's on (0x67, renewed, a byte of frames a second) and off (0x68), nothing answered
     * (engine/mirror.c). Its first message makes the sink, as 0x63's does. */
    if (len >= 6 && (data[5] == 0x67 || data[5] == 0x68)) {
        volatile u32 *m = (volatile u32 *)MIRROR_AT;

        if (!SINK_MADE)
            rpc_handle(data, len, iface);
        m[1] = CLOCK;
        m[2] = 132000000u / (len >= 7 && data[6] ? data[6] : 15u);
        m[0] = data[5] == 0x67;
        return;
    }
#endif
    if (len < 6 || data[5] != 0x63) {
        phone_sysex(data, len, iface);
        return;
    }
#ifdef SEEN
    phone_seen = 1;
#endif
    if (!SINK_MADE)
        rpc_handle(data, len, iface);   /* the unit's first message: stock makes its sink, and answers as it does an id it does not know */
    if (!SINK_MADE)
        return;
    p = knows_project;
    n = knows_count;
    bank = knows_bank;
    if (!n) {                           /* nothing loaded since the start: the project it started with, and the drive's bank */
        s32 now = project_now(manager_of());

        p = now < 0 ? 0x3fff : (u32)now;
        bank = BANK_NOW;
    }
    b = knows_id();
    /* message bytes 5 to 13 are at 12, 13 and 15 to 21 of the frame (a high-bits byte, 0, leads each seven) */
    knows_frame[12] = p & 0x7f;
    knows_frame[13] = (p >> 7) & 0x7f;
    knows_frame[15] = bank & 0x7f;
    knows_frame[16] = n & 0x7f;
    knows_frame[17] = (n >> 7) & 0x7f;
    knows_frame[18] = (n >> 14) & 0x7f;
    knows_frame[19] = b & 0x7f;
    knows_frame[20] = (b >> 7) & 0x7f;
    knows_frame[21] = (b >> 14) & 0x7f;
    vt = *(void ***)SINK;
    ((void (*)(void *, const volatile u8 *, u32))vt[4])(SINK, knows_frame, 23);
    ((void (*)(void *))vt[3])(SINK);
}

#ifdef FRESH
/* The fresh image (on the destnum image): stock's Project Load job makes a project that is not there and saves it, and
 * never calls the load (0x4005bbfa: 0x4001d16a, then the save at 0x4005bc2c), so a new project never asked the phone and
 * A kept the project before's samples. 
 * 
 * Here the save goes as before; then the new project is a load: counted, and with a phone there asked as a load asks,
 * the ask's bank byte + 128 to say it is new (its bit in the high-bits byte before it), then loaded as LOAD PROJECT loads
 * it, with the slots the phone names. With no phone it is counted only, and nothing is loaded. */
#define save_keep ((u32 (*)(void *, void *, void *))SAVE_KEEP_AT)
#define FAVE __attribute__((section(".cave.f"), noinline))

FAVE u32 fresh_save(void *manager, void *project, void *progress)
{
    u32 ok = save_keep(manager, project, progress);

    if (ok & 0xff) {
#ifdef NEWPROJ
        u32 bank = BANK_NOW;            /* the newproj image: counted here, so the project left stays fresh_make's */

        if (bank < BANKS_N)
            bank = project_bank(sample_store(), (u32)project, bank);
        knows_id();
        knows_project = (u32)project;
        knows_bank = bank;
        knows_count++;
        if (SINK_MADE && phone_seen) {
            phone_frame[14] = 0x40;
            phone_load(manager, project, progress);
            phone_frame[14] = 0;
        }
#else
        if (SINK_MADE && phone_seen) {
            phone_frame[14] = 0x40;
            knows_load(manager, project, progress);
            phone_frame[14] = 0;
        } else {
            u32 bank = BANK_NOW;

            if (bank < BANKS_N)
                bank = project_bank(sample_store(), (u32)project, bank);
            knows_id();
            knows_project = (u32)project;
            knows_bank = bank;
            knows_count++;
        }
#endif
    }
    return ok;
}

#ifdef NEWPROJ
/* The newproj image (on the fresh image): NEW PROJECT is stock's Project Init job, which makes a project of no number
 * (0x40059fd6: 0x4001d16a with -1) and neither saves nor loads, so it never asked the phone. 
 * Both calls of the maker come
 * here: the project left read first (for the ask, fresh_save's too), then the maker; an empty slot's new project asks
 * after its save (fresh_save); NEW PROJECT is counted as a load of no project and, with the phone's hello, asks as a load
 * does (project 0x3fff, marked new), waits, and loads the slots the phone names (keeptakes.c, new_slots). */
#define project_make ((void (*)(void *, s32))0x4001d16a)
#define new_slots ((void (*)(void))NEW_SLOTS_AT)
#define GAVE __attribute__((section(".cave.g"), noinline))
#define HAVE __attribute__((section(".cave.h"), noinline))

HAVE void left_is(s32 left)
{
    u32 l = left < 0 ? 0x3fffu : (u32)left;

    phone_frame[16] = l & 0x7f;
    phone_frame[17] = (l >> 7) & 0x7f;
}

/* LOAD PROJECT: the project it leaves, then the load as the fltr image has it. */
HAVE u32 fresh_load(void *manager, void *project, void *progress)
{
    left_is(project_now(manager_of()));
    return knows_load(manager, project, progress);
}

GAVE void fresh_make(void *manager, s32 project)
{
    left_is(project_now(manager_of()));
    project_make(manager, project);
    if (project >= 0)
        return;
    knows_id();
    knows_project = 0x3fff;
    knows_bank = BANK_NOW;
    knows_count++;
    if (!(SINK_MADE && phone_seen))
        return;
    phone_mask[0] = phone_mask[1] = 0;
    phone_answer = 0;
    phone_sem[0] = phone_sem[1] = phone_sem[2] = 0;
    phone_frame[14] = 0x40;
    ask(0x3fff, BANK_NOW);
    phone_frame[14] = 0;
    phone_start = CLOCK;
    phone_limit = FIRST_WAIT;
    phone_state = 1;
    timer_set(tick, 0x20);
    kwait(phone_sem);
    phone_state = 0;
    timer_cancel(tick);
    phone_sem[0] = 0;
#ifdef WIPE
    wipe_now();
#endif
    new_slots();
    phone_mask[0] = phone_mask[1] = 0;
}
#endif

#ifdef WIPE
/* The wipe image (on the newproj image): on the unit the phone's writes and clears went unanswered while a project job
 * waited on it (the phone app's log, 2026-10-27: "no answer to dataClear", then "no answer to writeOpen" for every slot),
 * its reads served. 
 * So the phone, having read A into its banks, answers 0x6A with the slots to empty (the done frame's ten
 * bytes); the unit, in its job after the wait, writes each one's first sector over with zeros (its header: the loader,
 * the scan and the boot then take the slot as empty), only on the bank the phone was asked about, reads the slot
 * headers again, and loads those slots as LOAD PROJECT loads the phone's. */
#define store_write ((s32 (*)(void *, u32, u32, const void *, const void *, u32))0x40111628)
#define ZEROS ((u32 *)0x4d94f2c0)       /* keeptakes.c's SLOT_AT, the staging of a slot read: free outside a load */
#define IAVE __attribute__((section(".cave.i"), noinline))
#define JAVE __attribute__((section(".cave.j"), noinline))
extern volatile u32 wipe_on;

IAVE void wipe_now(void)
{
    void *store;
    u32 none[3], slot, j;

    if (!wipe_on)
        return;
    wipe_on = 0;
    if (BANK_NOW != phone_frame[15])
        return;
    store = sample_store();
    for (j = 0; j < 512 / 4; j++)
        ZEROS[j] = 0;
    none[0] = none[1] = none[2] = 0;
    for (slot = 0; slot < 64; slot++)
        if (phone_mask[slot >> 5] & (1u << (slot & 31)))
            store_write(store, 8192 + 2048 * slot, 512, ZEROS, none, 0);
    scan_all(store);
}

IAVE u32 wipe_load(void *manager, void *project, void *progress)
{
    wipe_now();
    return keep_load(manager, project, progress);
}

/* The SysEx entry: 0x6A while a project job waits is the phone's answer, the slots to empty; anything else as before. */
JAVE void wipe_sysex(const u8 *data, u32 len, u32 iface)
{
    if (len >= 18 && data[5] == 0x6a && phone_state) {
        u32 j, lo = 0, hi = 0;

        for (j = 0; j < 5; j++)
            lo |= (u32)(data[j < 2 ? 6 + j : 7 + j] & 0x7f) << (7 * j);
        for (j = 0; j < 5; j++)
            hi |= (u32)(data[j < 4 ? 12 + j : 17] & 0x7f) << (7 * j);
        phone_mask[0] = lo;
        phone_mask[1] = hi;
        wipe_on = 1;
        phone_answer = 1;
        kgive(phone_sem);
        return;
    }
    knows_sysex(data, len, iface);
}
#endif

#ifdef STREAM
/* The stream image (on the wipe image): the phone writes a project's samples once its load is done, and the unit loads
 * each slot it names (engine/keeptakes.c, stream_add). LOAD PROJECT, once the phone has answered it, ends by saying so:
 * the ask frame with 0x6C in its id's place, the project and bank as asked. 0x6B, at any time, is a slot list to load. */
#define stream_add ((void (*)(u32, u32))STREAM_ADD_AT)
#define LAVE __attribute__((section(".cave.l"), noinline))
#define MAVE __attribute__((section(".cave.m"), noinline))

MAVE u32 stream_load(void *manager, void *project, void *progress)
{
    u32 ok = fresh_load(manager, project, progress);

    if (phone_answer && (ok & 0xff)) {
        void **vt = *(void ***)SINK;

        phone_answer = 0;
        phone_frame[11] = 0x6c;
        ((void (*)(void *, const volatile u8 *, u32))vt[4])(SINK, phone_frame, FRAME_N);
        ((void (*)(void *))vt[3])(SINK);
        phone_frame[11] = 0x60;
    }
    return ok;
}

LAVE void stream_sysex(const u8 *data, u32 len, u32 iface)
{
    if (len >= 18 && data[5] == 0x6b) {
        u32 j, lo = 0, hi = 0;

        for (j = 0; j < 5; j++)
            lo |= (u32)(data[j < 2 ? 6 + j : 7 + j] & 0x7f) << (7 * j);
        for (j = 0; j < 5; j++)
            hi |= (u32)(data[j < 4 ? 12 + j : 17] & 0x7f) << (7 * j);
        stream_add(lo, hi);
        return;
    }
    wipe_sysex(data, len, iface);
}
#endif
#endif
#endif
