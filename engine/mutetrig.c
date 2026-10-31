/* Main CPU (section 3, OS 1.42 only): a muted track's trigs still fire. The
 * "mute" image only.
 *
 * 
 *
 *
 *
 * 
 *
 * Mute has two halves on our images. Stock's: in the per-block routine's event
 * loop, an event the sequencer made for a muted track is dropped (0x400a421a:
 * the global mutes, or all but the solos, then the pattern's mutes). Ours: the
 * mixer is shown a volume of 0 for a muted track and the analog voices' level
 * words are set to 0 (engine/mixlink.c, engine/amute.c). With ours in place
 * stock's is not needed to silence a track, and it is what makes a track come
 * back empty: the note that should be sounding was never started.
 *
 * So stock's test is skipped for a track that makes sound. The first two
 * instructions of it call the routine below. For a track that is a MIDI track
 * (a bit each in a word of the kit, the one the UI asks at 0x4000f5e0 and the
 * event loop itself at 0x400a432a) it does what the two instructions did and
 * goes back: a MIDI track has no audio to mute, so its mute stays stock's. For
 * any other track it goes straight to where the tests end up when the track is
 * not muted. The event then runs as on an unmuted track: the note starts, its
 * locks are applied, a take is recorded, and nothing is heard until the mute
 * comes off. The FX track's own test (0x400a3d5e) is left as it is.
 *
 * At the call: d2 the event's track (0..11), fp the routine's frame with the
 * mute mask at - 56, d0, d4, d7 and a2 in use by stock; d1 is the answer for a
 * MIDI track, a0 is free (stock loads it again at 0x400a427a).
 */
__asm__(".section .cave.r,\"ax\",@progbits\n"
        "        .globl mute_trig\n"
        "mute_trig:  movel 0x800030b8,%d1\n"        /* the kit the routine plays from */
        "            beqs 1f\n"                     /* none yet: stock's test */
        "            moveal %d1,%a0\n"
        "            mvsw %a0@(5456),%d1\n"         /* its MIDI tracks */
        "            btst %d2,%d1\n"
        "            bnes 1f\n"
        "            addql #4,%sp\n"                /* a track that makes sound: not muted, as far as events go */
        "            jmp 0x400a426a\n"
        "1:          movel %fp@(-56),%d1\n"         /* the two instructions that were at the call */
        "            asrl %d2,%d1\n"
        "            rts\n"
        "            .text\n");
