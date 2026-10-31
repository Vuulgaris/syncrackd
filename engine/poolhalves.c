/* Main CPU (section 3, OS 1.42 only): the audio CPU's sample pool, sent in two halves. The "double" image only; it
 * takes the place of engine/poolstage.c.
 *
 * The pool is a stream: for each of the 64 slots its frame count and its samples. Stock builds all of it in one block
 * of main CPU memory (a marker byte, 4 bytes of length, the stream) and a task hands it to the audio CPU in 2 KB
 * chunks, numbered. The block is 32 MB and there is no second one, but the audio CPU's pool is 64 MB and it puts each
 * chunk where its number says.
 *
 * So the block holds one half of the stream at a time:
 * - pool_stage, which stock calls once before the exchange, fills it with the
 * first half and writes the whole stream's length, so the sender counts all
 * the chunks;
 * - pool_chunk is called by the sender for every chunk in place of its own
 * "block + 5 + (index << 11)". From chunk HALF_CHUNKS on it answers with the
 * chunk's place in the second half, and fills the block with that half first.
 *
 * Which half the block holds is its marker byte: stock's 0xaa for the first, 0xab for the second. Nothing in the
 * program reads that byte. If the exchange starts again from chunk 0 the first half is staged again.
 *
 * A pool of no more than one half never leaves the first path: the block is what engine/poolstage.c builds and every
 * chunk comes from where stock took it.
 *
 * The refill reads up to 32 MB from the drive while the exchange stands still, and a stock timer calls a timeout when
 * its count of ticks without progress passes 18. The count is cleared here after every piece of at most 16 KB.
 *
 * Each half is no more of the block than stock could use at its fullest, in whole chunks. A slot that does not fit in
 * two halves gets a count of 0. */
#include "sampler.h"

#define STAGE ((u8 *)0x4d84f2c0)
#define SLOTS 64
#define CHUNK 2048u
#define HALF_CHUNKS 16382u                  /* 64 x (4 + 524,224) bytes, what stock could stage, in whole chunks */
#define HALF (HALF_CHUNKS * CHUNK)
#define CAP (2 * HALF)                      /* under the audio CPU's 64 MB */
#define PIECE 0x4000u                       /* most read from the drive between two clearings of the stall count */
#define FIRST 0xaa
#define INDEX (*(const volatile u32 *)0x41bbf424)   /* the chunk the sender is about to send */
#define STALL (*(volatile u32 *)0x41bbf3bc)
#define header_read ((s32 (*)(u32, void *))0x401132ec)
#define sample_read ((s32 (*)(u32, void *, u8 *, u32, u32))0x401133ce)

struct header { u32 magic, unused, frames; u8 rest[52]; };

/* Fill the block with the stream's bytes [part * HALF, part * HALF + HALF). Returns the whole stream's length. Both
 * halves size every slot the same way, from its header: the drive does not change while the unit boots. */
__attribute__((section(".cave.h"), noinline))
static u32 stage(u32 part)
{
    u32 lo = part * HALF, hi = lo + HALF;
    u32 base = (u32)STAGE + 5 - lo;         /* stream byte x goes to base + x */
    u32 pos = 0, slot;
    struct header h;

    for (slot = 0; slot < SLOTS; slot++) {
        u32 room = CAP - pos - 4 * (SLOTS - slot);
        u32 bytes = 0, a, b, k;

        STALL = 0;
        if (header_read(slot, &h) == 0 && 2 * h.frames <= room)
            bytes = 2 * h.frames;
        for (k = 0; k < 4; k++)             /* the count: any of its four bytes may be in this half */
            if (pos + k >= lo && pos + k < hi)
                *(u8 *)(base + pos + k) = (bytes >> 1) >> (24 - 8 * k);
        a = pos + 4;
        b = a + bytes;
        pos = b;
        if (a < lo)
            a = lo;
        if (b > hi)
            b = hi;
        while (a < b) {                     /* the samples that fall in this half, a piece at a time */
            u32 n = b - a > PIECE ? PIECE : b - a;

            sample_read(slot, &h, (u8 *)(base + a), a - (pos - bytes), n);
            STALL = 0;
            a += n;
        }
    }
    STAGE[0] = FIRST + part;
    return pos;
}

/* Where stock's pool builder was: called once, before the exchange starts. */
__attribute__((section(".cave.p")))
void pool_stage(void)
{
    u32 total = stage(0);

    *(u32 *)(STAGE + 1) = total;
}

/* For the sender: the address of the chunk it is about to send. */
__attribute__((section(".cave.h")))
u32 pool_chunk(void)
{
    u32 i = INDEX;
    u32 part = i >= HALF_CHUNKS;

    if (STAGE[0] != FIRST + part)
        stage(part);
    return (u32)STAGE + 5 + ((i - part * HALF_CHUNKS) << 11);
}
