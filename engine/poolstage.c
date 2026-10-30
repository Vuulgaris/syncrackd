/* Main CPU (section 3, OS 1.42 only): builds the audio CPU's sample pool at boot.
 * Takes the place of the stock routine at 0x40082334, in its own bytes. Larger
 * slots image only.
 *
 * The pool is built in one block of main CPU memory and then handed over in
 * 2 KB chunks by stock code: a marker byte, 4 bytes of length, then for each
 * of the 64 slots its frame count and its samples. Stock read each slot into
 * a buffer of one slot's size and copied it over, with no check on the total,
 * because 64 stock slots cannot fill the block. With slots of 1 MB they can:
 * the audio CPU's program is staged right behind it. So this one
 *   - reads each slot straight to its place, through the stock reader;
 *   - gives a slot that no longer fits a count of 0, as stock does for an
 *     empty or unreadable one. It stays on the drive, it is just not loaded;
 *   - never uses more of the block than stock could at its fullest.
 */
#include "sampler.h"

#define STAGE ((u8 *)0x4d84f2c0)
#define SLOTS 64
/* what 64 full stock slots come to after the marker and the length: 64 x (4 + 524,224) */
#define ROOM (SLOTS * (4u + 0x7ffc0u))
/* (slot, header out, buffer, offset, most) -> 0, or a negative error. Copies most
 * bytes at the most; the header says how many frames there are. */
#define sample_read ((s32 (*)(u32, void *, u8 *, u32, u32))0x401133ce)

struct header {
    u32 magic, unused, frames;
    u8 rest[52];
};

__attribute__((section(".cave.p")))
void pool_stage(void)
{
    u8 *rec = STAGE + 5;
    u32 used = 0, slot;
    struct header h;

    STAGE[0] = 0xaa;
    for (slot = 0; slot < SLOTS; slot++) {
        u32 room = ROOM - used - 4 * (SLOTS - slot);    /* the counts still to come keep their place */
        u32 frames = 0;

        if (sample_read(slot, &h, rec + used + 4, 0, room) == 0 && 2 * h.frames <= room)
            frames = h.frames;
        *(u32 *)(rec + used) = frames;
        used += 4 + 2 * frames;
    }
    *(u32 *)(STAGE + 1) = used;
}
