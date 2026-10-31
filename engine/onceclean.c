/* Main CPU (section 3, OS 1.42 only): the once image's part that runs in the main task.
 *
 * A step locked to record once is spent where the sequencer plays it (engine/once.S): its word in the pattern's table
 * is made one that says nothing, and the track's byte of ONCE_DIRTY is set. The lock itself is taken off here, by
 * stock's routine for a lock removed by hand, so the step's count of locks, the track's "this slot has a lock" byte
 * and the pattern's listeners go as they do then.
 *
 * It is called from the main task's loop when a message has come, before the message is dealt with (once_loop). That
 * task hands a key's or a knob's message to the UI's objects, so a lock is changed here from the task that changes
 * locks by hand. Nothing is taken off between two messages; until then the spent lock is a lock that says nothing.
 *
 * The pattern is the selected one. A spent lock in a pattern that is not selected any more stays as it is: it says
 * nothing, and a turn of REC with its step held takes it off. */
#define RECORDER
#define ONCE
#include "sampler.h"

#define manager ((void *(*)(void))0x4016e9c8)
#define now_pattern ((void *(*)(void *))0x40019000)             /* (manager) -> the selected pattern */
#define steps_of ((void *(*)(void *, u32))0x40015fae)           /* (that, track) -> the track's steps */
#define lock_read ((s32 (*)(void *, u32, u32))0x4002740c)       /* (steps, step, slot) -> the lock, negative: none */
#define lock_drop ((u32 (*)(void *, u32, u32))0x40027fe8)       /* (steps, step, slot): no lock */

#ifdef STAY
#define CLEAN_RUN ".cave.e"         /* the stay image: in a run of its own, for room in the first */
#else
#define CLEAN_RUN ".cave.o"
#endif
__attribute__((section(CLEAN_RUN), noinline)) void once_clean(void)
{
    void *steps;
    u32 t, step;

    for (t = 0; t < 8; t++) {
        if (!ONCE_DIRTY[t])
            continue;
        ONCE_DIRTY[t] = 0;
        steps = steps_of(now_pattern(manager()), t);
        for (step = 0; step < 64; step++)
            if (lock_read(steps, step, K_REC) == (s32)ONCE_SPENT)
                lock_drop(steps, step, K_REC);
    }
#ifdef SRR
    /* The srr image: a track whose word on slot 24 was just made from MODE's bits (engine/recword.S) is an old
     * pattern's. Its locks of MODE were locks of those bits, and would be played as amounts of the reduction: they
     * go, in the selected pattern, the same way. */
    for (t = 0; t < 8; t++) {
        if (!SRR_DIRTY[t])
            continue;
        SRR_DIRTY[t] = 0;
        steps = steps_of(now_pattern(manager()), t);
        for (step = 0; step < 64; step++)
            if (lock_read(steps, step, K_MODE) >= 0)
                lock_drop(steps, step, K_MODE);
    }
#endif
}
