| Main CPU (section 3, OS 1.42 only): a step's REC reaches the audio CPU. From the meter image on,
| where the feed's run has room.
|
| Stock writes over slot 24 of every digital track in the block the audio CPU is sent and the feed
| reads, every block, after the block is built (0x400a4c3e on): 1 when the track's word at + 128
| is not 0 or its word at + 110 is past 0x7eff, 0 otherwise. It is the envelope's hold flag, the
| one the voice loop copies into the voice. So a lock on slot 24 got as far as the block a trig's
| locks are written into (0x800021b0) and no further. Seen on the maintainer's unit with the probe
| image: 5280 there, 0 or 1 in the block that is sent, and no take.
|
| The two instructions that store the flag and step to the next track call this. On a sampler
| track whose slot 24 holds one of REC's two marks where the locks are written, the mark goes
| into the block in the flag's place: the sampler's update clears the hold flag in any case, as
| Twinshot's does. Anything else there, and every other machine, keeps stock's flag.
|
| At the call: a0 the track's 142 bytes in the block that is sent, d0 the flag. Stock loads d0
| again before it reads it (0x400a4c46 in the loop, 0x400a4c80 after it).
#ifdef SRR
| The srr image (engine/sampler.h, SRR): MODE's parameter is the reduction, and a sampler track's REC and SRC are the
| track's own word on knob slot 24, signed. This routine reads that word where the sound engine's side reads the
| kit (stock keeps the kit's address at 0x800030b8; a track's 71 words are 291 bytes a track from + 62, as stock's
| own routine that puts a lock's slot back reads them, 0x400977d8 called at 0x400a470e), and leaves in the block
| what the track is to do: REC's mark in slot 24's high byte, the step's own if a lock's mark is where the locks
| are written and the track's otherwise, and the track's source in its low byte, for the feed.
|
| A word that is not signed is an old pattern's: it is made here from MODE's old bits (2 REC, 4 and up the source),
| signed, and MODE is put at 0 in the kit, in this block and where the locks are written. The track's byte of
| srr_dirty tells the main task to take the pattern's old locks of MODE off (engine/onceclean.c).
|
| In a run of its own, its eight bytes first. At the call a1 is one past the track's machine in stock's eight bytes
| (0x80002f50), which is the track.
    .section .cave.w,"ax"
    .globl  rec_word
    .globl  srr_dirty
srr_dirty:
    .long   0, 0
rec_word:
    move.w  %d0,76(%a0)             | stock's: the hold flag
    mvz.w   62(%a0),%d0             | the machine's type, a byte up, as stock has just written it
    cmpi.l  #44 << 8,%d0
    bne.w   9f
    move.l  0x800030b8,%d0          | the kit
    beq.w   9f
    lea     -12(%sp),%sp
    movem.l %d1-%d2/%a1,(%sp)
    move.l  %a1,%d2
    subi.l  #0x80002f51,%d2         | the track
    move.l  %d2,%d1
    mulu.w  #291,%d1
    add.l   %d0,%d1
    movea.l %d1,%a1                 | the track's sound in the kit: its words from + 62
    mvz.w   62+48(%a1),%d0          | slot 24, the track's own
    move.l  %d0,%d1
#if defined(NEXT)
    andi.l  #0xf0a4,%d1             | the next image: bit 6 is the track's KIND, and signed either way
#elif defined(LOCK)
    andi.l  #0xf0e4,%d1             | the lock image: bit 4 is KEYS's tempo lock, and signed either way
#elif defined(STRETCH)
    andi.l  #0xf0f4,%d1             | the stretch image: bit 3 is KEYS's stretch, and signed either way
#elif defined(SLICE)
    andi.l  #0xf0fc,%d1             | the slice image: bit 1 is KEYS, and signed either way
#else
    andi.l  #0xf0fe,%d1
#endif
    cmpi.l  #0x40a4,%d1             | SRR_SIG
    beq.s   3f
    mvz.b   62+46(%a1),%d0          | an old pattern's: MODE's number as it was
    move.l  %d0,%d1
    lsl.l   #6,%d1                  | the source, from bit 2, to bits 8 to 11
    andi.l  #0x0f00,%d1
    lsr.l   #1,%d0                  | REC, bit 1, to bit 0
    andi.l  #1,%d0
    or.l    %d1,%d0
    ori.l   #0x40a4,%d0
    move.w  %d0,62+48(%a1)          | signed, in the kit
    clr.w   62+46(%a1)              | MODE is the reduction now: off
    clr.w   74(%a0)                 | in this block as it is sent,
    clr.w   74-0x4198(%a0)          | and where a trig's locks are written
    lea     srr_dirty,%a1
    moveq   #1,%d1
    move.b  %d1,(%a1,%d2.l)         | the main task: this track's old locks of MODE go
3:  mvz.w   76-0x4198(%a0),%d1      | slot 24 where a trig's locks are written
    lsr.l   #8,%d1
    cmpi.l  #0x52,%d1               | REC_LOCK_ON: the step's own
    beq.s   5f
    cmpi.l  #0x29,%d1               | REC_LOCK_OFF
    beq.s   4f
#ifdef HANDREC
    jsr     HAND_REC                | the handrec image: the track's, or stopped and at ONCE (engine/once.S)
    bne.s   5f
#else
    btst    #0,%d0                  | no lock: the track's
    bne.s   5f
#endif
4:  moveq   #0x29,%d1
    bra.s   6f
5:  moveq   #0x52,%d1
6:  lsl.l   #8,%d1
#ifdef SLICE
    btst    #1,%d0                  | the slice image: KEYS, to bit 7 of the low byte (SLICE_BIT)
    beq.s   7f
    ori.l   #0x80,%d1
7:
#endif
#ifdef STRETCH
    btst    #3,%d0                  | the stretch image: KEYS's stretch, to bit 6 of the low byte (STR_BIT)
    beq.s   8f
    ori.l   #0x40,%d1
8:
#endif
#ifdef STSW
| The stsw image (engine/sampler.h, STSW): a step's stretch, slot 17's low byte where the locks are written, over the
| track's: 0xd5 (STR_LOCK_ON) on, 0xa9 (STR_LOCK_OFF) off, anything else the track's. Its high byte is the solo's.
    move.l  %d0,-(%sp)
    mvz.b   63-0x4198(%a0),%d0
    cmpi.l  #0xd5,%d0
    bne.s   11f
    ori.l   #0x40,%d1
11: cmpi.l  #0xa9,%d0
    bne.s   12f
    andi.l  #0xffffffbf,%d1
12: move.l  (%sp)+,%d0
#endif
    lsr.l   #8,%d0
    andi.l  #15,%d0                 | the track's source, under the mark
    or.l    %d0,%d1
#ifdef STRETCH
| Only slots 17 to 26 and a few of the filter's and amp's cross to the audio CPU whole (emu/engine.py, HOST_FIELDS),
| so SPD (PTIM's slot 52, the track's own in the kit) goes in the mark's place: with REC off on a stretched track the
| high byte is 0x80 and SPD, never REC_LOCK_ON, which is all anything asks of it. With REC on it stays the mark.
    btst    #6,%d1
#ifdef LOCK
    beq.w   10f                     | the lock image: farther now
#else
    beq.s   10f
#endif
    move.l  %d1,%d0
    lsr.l   #8,%d0
    cmpi.l  #0x29,%d0               | REC_LOCK_OFF
#ifdef LOCK
    bne.w   10f
#else
    bne.s   10f
#endif
    move.l  %d2,%d0
    mulu.w  #291,%d0
    add.l   0x800030b8,%d0          | the track's sound in the kit
    movea.l %d0,%a1
#ifdef LOCK
    jsr     lock_byte               | the lock image: SPD, the tempo or the lock, and its tag in the low byte
    ori.l   #0x80,%d0
#else
    mvz.b   62+104(%a1),%d0         | slot 52, SPD
    andi.l  #0x7f,%d0
    ori.l   #0x80,%d0
#endif
    lsl.l   #8,%d0
    andi.l  #0xff,%d1
    or.l    %d0,%d1
10:
#endif
    move.w  %d1,76(%a0)
    movem.l (%sp),%d1-%d2/%a1
    lea     12(%sp),%sp
9:  lea     142(%a0),%a0            | stock's: the next track
    rts
#ifdef LOCK
| The lock image (engine/sampler.h, LOCK), in a run of its own (mainmap.CAVE_LOCK): a stretched track's blocks, a
| byte a track, and at each one with REC off what its high byte carries, in turn: SPD, then a step's frames over 2 in
| two halves, then the lock; bits 4 and 5 of the low byte say which. At the call d1 the word, d2 the track, a1 the
| track's sound in the kit. -> d0 the seven bits, d1 with the tag.
    .section .cave.m,"ax"
    .globl  lock_tick
    .globl  lock_byte
lock_tick:
    .long   0, 0
lock_byte:
    move.l  %a0,-(%sp)              | the caller's: the track in the block that is sent
    lea     lock_tick,%a0
    adda.l  %d2,%a0
    mvz.b   (%a0),%d0
    addq.l  #1,%d0
    move.b  %d0,(%a0)
    movea.l (%sp)+,%a0
    andi.l  #3,%d0
    beq.s   11f
    lsl.l   #4,%d0
    or.l    %d0,%d1                 | the tag
    cmpi.l  #0x30,%d0
    bne.s   13f
    mvz.w   62+48(%a1),%d0          | 3: the lock, bit 4 of the track's own word, as bit 0
    lsr.l   #4,%d0
    andi.l  #1,%d0
    move.l  %d1,-(%sp)              | and PORT (slot 53: 63 off, 64 on) as bit 1: snapped to the tempo, SPD not heard
    mvz.b   62+106(%a1),%d1         | (the third build, the maintainer's word: "move the p time around and then just nap it back to
    cmpi.l  #64,%d1                 | the bpm with a switch")
    bcs.s   17f
    ori.l   #2,%d0
17: move.l  (%sp)+,%d1
    rts
13: move.l  0x402d7360,%d0          | the tempo, BPM times 120
    cmpi.l  #1000,%d0
    bcs.s   14f
    move.l  %d0,-(%sp)
    move.l  #43200000,%d0
    divu.l  (%sp)+,%d0              | a step's frames over 2
    btst    #5,%d1
    beq.s   15f
    lsr.l   #7,%d0                  | 2: the high half
15: andi.l  #0x7f,%d0
    rts
14: moveq   #0,%d0
    rts
11: mvz.w   62+104(%a1),%d0         | 0: slot 52, SPD, to the nearest whole number: what the knob shows (the
    addi.l  #0x80,%d0               | second build; the first took the whole part, so a knob shown at 64 could send 63)
    lsr.l   #8,%d0
    cmpi.l  #127,%d0
    bls.s   16f
    moveq   #127,%d0
16: rts

| The lock image's fourth and fifth builds: stock's portamento on a sampler track by KEYS (docs/FINDINGS.md, "Where
| stock's portamento is made"). In place of stock's `mvsw %a4@(134),%d0 ; cmpil #16383,%d0` at 0x4011a280, in the
| pitch routine 0x4011a1ac: PORT as stock loads it, or 0 (off) on a sampler track whose own word (the kit's slot 24,
| signed) has KEYS's stretch, compared as stock compares it, so stock's bgts after the call takes the flags. a4 the
| track in the block, d1 the track: both kept, a1 too. On request, then "cant oyu have
| portamento just worj when strethc is off" (PORT is the lock's snap there, read from the kit, not from here).
    .globl  port_gate
port_gate:
    mvs.w   134(%a4),%d0
    move.l  %d1,-(%sp)
    move.l  %a1,-(%sp)
    move.l  %d0,-(%sp)              | PORT, as stock has it
    mvz.b   62(%a4),%d0
    cmpi.l  #44,%d0
    bne.s   19f
    move.l  0x800030b8,%d0          | the kit
    beq.s   19f
    mulu.w  #291,%d1
    add.l   %d0,%d1
    movea.l %d1,%a1
    mvz.w   62+48(%a1),%d0          | the track's own word, slot 24
    move.l  %d0,%d1
#ifdef NEXT
    andi.l  #0xf0a4,%d1             | the next image: KIND's bit 6 too
#else
    andi.l  #0xf0e4,%d1
#endif
    cmpi.l  #0x40a4,%d1             | signed
    bne.s   19f
    move.l  #64 << 8,(%sp)          | the fifth build, the maintainer's word "portamentio should just be defacto off when stretched
    btst    #3,%d0                  | and n when not": not stretched, on whatever PORT is (PTIM its time, 0 none)
    beq.s   19f
    clr.l   (%sp)                   | stretched: off
19: move.l  (%sp)+,%d0
    movea.l (%sp)+,%a1
    move.l  (%sp)+,%d1
    cmpi.l  #16383,%d0
    rts
#endif
#else
    .section .cave.r,"ax"
    .globl  rec_word
rec_word:
    move.w  %d0,76(%a0)             | stock's: the hold flag
    mvz.w   62(%a0),%d0             | the machine's type, a byte up, as stock has just written it
    cmpi.l  #44 << 8,%d0
    bne.s   1f
#ifdef XFADE
    bset    #0,74(%a0)              | the xfade image: MODE has no knob, and MODE as it is sent says a stereo take
#endif
    mvz.w   76-0x4198(%a0),%d0      | slot 24 where a trig's locks are written: 0x4198 bytes back
    lsr.l   #8,%d0
    cmpi.l  #0x52,%d0               | REC_LOCK_ON
    beq.s   2f
    cmpi.l  #0x29,%d0               | REC_LOCK_OFF
    bne.s   1f
2:  move.w  76-0x4198(%a0),76(%a0)
1:  lea     142(%a0),%a0            | stock's: the next track
    rts
#endif
