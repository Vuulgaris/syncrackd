/* Main CPU (section 3, OS 1.42 only): three sample banks. The "bank" image only.
 *
 * 
 *
 * 
 *
 * The drive. Stock keeps the 64 sample slots in one run of sectors (with the
 * larger slots: 8192 to 139,263) and nothing after it up to 244 MB. Here there
 * are three such runs one after the other, and everything in the program that
 * reads, writes or erases a sector goes through one of three routines, named in
 * 21 places and no other. Those 21 are pointed at the three short routines
 * below, which move a sector of the first run to the same place in the run of
 * the bank that is loaded, and leave every other sector alone. So the scan that
 * reads the slots' names, the boot's pool builder, Transfer's route, keeping
 * takes and the loader all work on the loaded bank without knowing of it, and
 * nothing here can reach a sector outside the three runs.
 *
 * Which bank. BANK_NOW (engine/sampler.h) is the bank that is loaded. It starts
 * as "not known" (any number past 2). The first time a sample sector is asked for, bank_start reads
 * our one sector after the third run: it holds the bank that was loaded last,
 * and for each of the 128 projects the bank it was saved with. A drive without
 * that sector is on bank 0, which is where the samples always were, and so is a
 * project the sector knows nothing of: every project made before this image.
 *
 * A project. BANK_WANT is the bank the project in memory is to have; the
 * sampling page's BANK place turns it and nothing else. Saving the project
 * writes it down for that project (bank_saved, called from engine/keeptakes.c).
 * Loading a project that was saved with another bank than the loaded one makes
 * that bank the loaded one, writes that down, has stock read the 64 slots' names
 * again, and answers "load every slot" to the loader (bank_loaded). A bank is
 * changed at no other moment.
 */
#include "sampler.h"

#define drive_read ((s32 (*)(u32, u32, void *))0x4010f612)
#define sample_store ((void *(*)(void))0x4016f292)
#define store_read ((s32 (*)(void *, u32, u32, void *))0x401100d4)
#define store_write ((s32 (*)(void *, u32, u32, const void *, const void *, u32))0x40111628)
#define scan_all ((void (*)(void *))0x401115ea)     /* (store): every slot's header into the store's table */

#define CAVE __attribute__((section(".cave.b"), noinline))

/* The numbers, alone in a run of their own so that their place is fixed, and the sector
 * bank_start reads into: it runs in whatever task asks for a sample sector first. */
__asm__(".section .cave.v,\"ax\",@progbits\n"
        "        .globl bank_now, bank_want, bank_busy\n"
        "bank_now:   .long 0xffffffff\n"
        "bank_want:  .long 0\n"
        "bank_busy:  .long 0\n"
        "        .section .cave.b,\"ax\",@progbits\n"
        "        .globl bank_read, bank_write, bank_erase, bank_buf\n"
        /* The three ways in. Each has the sector as its first argument: it is moved if it is a
         * sample's, and the stock routine is jumped to with everything else as it came. */
        "bank_read:  bsrs bank_map\n"
        "            jmp 0x4010f612\n"
        "bank_write: bsrs bank_map\n"
        "            jmp 0x4010f7f8\n"
        "bank_erase: bsrs bank_map\n"
        "            jmp 0x4010f52a\n"
        "bank_map:   movel %sp@(8),%d0\n"
        "            subil #8192,%d0\n"             /* BANK_FIRST */
        "            cmpil #131072,%d0\n"           /* BANK_SECTORS */
        "            bccs 2f\n"                     /* not a sample's sector */
        "            movel bank_now,%d0\n"
        "            moveq #2,%d1\n"
        "            cmpl %d0,%d1\n"
        "            bccs 1f\n"                     /* 0, 1 or 2 */
        "            jsr bank_start\n"
        "1:          swap %d0\n"                    /* times 65,536 */
        "            addl %d0,%d0\n"                /* times 131,072 */
        "            addl %d0,%sp@(8)\n"
        "2:          rts\n"
        "            .balign 4\n"
        "bank_buf:   .space 512\n"
        "            .text\n");
extern u32 bank_buf[];

/* The bank the sector says is loaded, or 0. */
CAVE static u32 loaded(const struct bankmark *m)
{
    return m->magic == BANK_MAGIC && m->magic2 == ~BANK_MAGIC && m->now < BANKS_N ? m->now : 0;
}

/* The first sample sector is asked for: which bank? When the drive does not read, the answer is 0
 * and the next sample sector asks again, three times in all: after that the first bank it is, so
 * that a sector that cannot be read does not cost a failed read before every other one. */
CAVE u32 bank_start(void)
{
    u32 now;

    if (drive_read(BANK_MARK_SECTOR, 512, bank_buf)) {
        now = BANK_NOW;
        BANK_NOW = now > 0xfffffffdu ? now - 1 : 0;
        return 0;
    }
    now = loaded((const struct bankmark *)bank_buf);
    BANK_WANT = now;
    BANK_NOW = now;
    return now;
}

/* Our sector into m, made new if the drive has none. 0 when the drive does not read. */
CAVE static u32 mark(void *store, struct bankmark *m)
{
    u32 k, now = BANK_NOW < BANKS_N ? BANK_NOW : 0;

    if (store_read(store, BANK_MARK_SECTOR, 512, m))
        return 0;
    if (m->magic != BANK_MAGIC || m->magic2 != ~BANK_MAGIC) {
        for (k = 0; k < 512 / 4; k++)
            ((u32 *)m)[k] = 0xffffffff;         /* no project has a bank */
        m->magic = BANK_MAGIC;
        m->magic2 = ~BANK_MAGIC;
    }
    m->now = now;
    return 1;
}

CAVE static void write(void *store, const struct bankmark *m)
{
    u32 none[3];                                /* an empty progress callback, as in engine/keeptakes.c */

    none[0] = none[1] = none[2] = 0;
    store_write(store, BANK_MARK_SECTOR, 512, m, none, 0);
}

/* The project has just been saved: its bank is the one the page says. Written only if it is news. */
CAVE void bank_saved(u32 project)
{
    u32 sec[512 / 4];
    struct bankmark *m = (struct bankmark *)sec;
    void *store = sample_store();
    u32 want = BANK_WANT < BANKS_N ? BANK_WANT : 0;

    if (project >= 128 || !mark(store, m) || m->of[project] == want)
        return;
    m->of[project] = (u8)want;
    write(store, m);
}

/* The project has just been loaded. If its bank is not the loaded one, it is from here on, and the
 * answer is 1: every slot has to be loaded. A project the sector does not know is on bank 0. */
CAVE u32 bank_loaded(u32 project)
{
    u32 sec[512 / 4];
    struct bankmark *m = (struct bankmark *)sec;
    void *store = sample_store();
    u32 now = BANK_NOW < BANKS_N ? BANK_NOW : 0, want;

    BANK_WANT = now;
    if (project >= 128 || !mark(store, m))
        return 0;
    want = m->of[project] < BANKS_N ? m->of[project] : 0;
    if (want == now)
        return 0;
    m->now = want;
    write(store, m);                            /* first: a boot from here on loads this bank */
    BANK_WANT = want;
    BANK_NOW = want;
    scan_all(store);
    return 1;
}
