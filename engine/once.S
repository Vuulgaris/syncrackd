| Main CPU (section 3, OS 1.42 only): REC's third setting, ONCE. The once image.
|
| 
| 
|
| A step's REC at ONCE is a lock on slot 24 at ONCE_WORD (engine/sampler.h; LOCK_ONCE here, and ONCE_SPENT is LOCK_SPENT). Its high byte is the mark
| of a step locked on, so stock plays it and the audio CPU, the feed and recword.S take it as one.
| What makes it once is here, in the routine of stock's that plays a step (0x4008b8fa, the track in d4
| and the step in d3 at both places below). That routine runs wherever a step is played, the
| sequencer's task and the UI's: nothing is called from here but stock's own next routine, and only
| words and bytes are stored.
|
| once_seq, for a step that has locks: stock's routine gathers them into the event, and then a lock at
| ONCE_WORD is made ONCE_SPENT in the pattern's table, a word that is no mark. The event has its copy:
| this pass records, to the track's next event as a step locked on does, and the next pass does not.
| The track's byte of once_vars + 8 says a spent lock is there; the main task takes it off with stock's
| routine for a lock removed by hand (once_loop, engine/onceclean.c).
|
| The track's own REC at ONCE is its byte of once_vars. The next step played on the track gets
| (slot 24, on) added to its event's locks, and the byte is cleared: once_seq where the step has locks,
| once_none where it has none. A step with a REC lock of its own that says on uses the byte up; one
| that says off leaves it for the next.
|
| Only a sampler's track: tracks 0 to 7 whose machine, in the block the audio CPU is sent, is type 44.
| On the others slot 24 is a knob or the hold flag, and a lock there is left alone.
    .section .cave.o,"ax"
    .globl  once_vars, once_seq, once_none, once_loop
once_vars:
    .fill   16,1,0
#ifdef HANDREC
    .pushsection .cave.b,"ax"
| The handrec image, its second build: first in the long image's run (nothing of this chain uses it), at places
| recword.S and recfeed.c are built to (mm.HAND_HOLD, mm.HAND_LEFT, mm.HAND_REC), before they are built. 
|
| the TRIG page's LEN. hand_hold: a bit a track whose take runs past its note's release
| (the feed puts it in the window's word at 0x802, high byte, and rec_all ignores that track's release). hand_left:
| a long a track, what is left of the take in the tempo's units (BPM x 120 a block, mm.TEMPO).
    .globl  hand_rec, hand_hold, hand_left
hand_hold:
    .long   0
hand_left:
    .fill   32,1,0
| From engine/recword.S, in place of its `btst #0,%d0` where slot 24 holds no lock's mark: d0 the track's own word, d2
| the track, a5 stock's trig mask of this block (a bit a track). Z clear: the track records. Keeps all but d1.
| Stopped, a track at ONCE records (the mark waits for the note); its note's block takes the ONCE (REC reads OFF) and
| holds the take for the TRIG page's LEN (the byte at the pattern's data + 1177 a track + 961, stock's table
| mm.LEN_TABLE of its lengths, as the step routine reads them); then the mark goes and the feed with it.
hand_rec:
    btst    #0,%d0
    bne.w   9f                      | REC on
    lea     -12(%sp),%sp
    movem.l %d0/%d3/%a0,(%sp)
    move.l  %d2,%d3
    lsl.l   #2,%d3
    lea     hand_left(%pc),%a0
    move.l  (%a0,%d3.l),%d1
    beq.w   2f                      | no take held
    sub.l   TEMPO,%d1               | a block of it
    bgt.w   1f
    clr.l   (%a0,%d3.l)             | its length is over: no mark, so the feed stops and the take with it
    lea     hand_hold(%pc),%a0
    move.l  (%a0),%d1
    bclr    %d2,%d1
    move.l  %d1,(%a0)
    moveq   #0,%d1
    bra.w   8f
1:  move.l  %d1,(%a0,%d3.l)
    bra.w   7f
2:  move.l  SEQ_STATE,%d1
    subq.l  #1,%d1
    beq.w   8f                      | playing: the track's REC as it is
    lea     once_vars,%a0
    tst.b   (%a0,%d2.l)
    beq.w   8f                      | not at ONCE
    move.l  %a5,%d1
    btst    %d2,%d1
    beq.w   7f                      | at ONCE, no note yet: the mark waits for it
    clr.b   (%a0,%d2.l)             | its note: the ONCE is taken
    move.l  PATTERN_DATA,%d1
    beq.w   7f
    movea.l %d1,%a0
    move.l  %d2,%d1
    mulu.w  #1177,%d1
    adda.l  %d1,%a0
    mvz.b   961(%a0),%d1            | the TRIG page's LEN
    andi.l  #127,%d1
    lsl.l   #2,%d1
    lea     LEN_TABLE + 4,%a0       | (as the step routine indexes it: from + 4)
    move.l  (%a0,%d1.l),%d1         | its length
    lea     hand_left(%pc),%a0
    move.l  %d1,(%a0,%d3.l)
    lea     hand_hold(%pc),%a0
    move.l  (%a0),%d1
    bset    %d2,%d1
    move.l  %d1,(%a0)
7:  moveq   #1,%d1                  | Z clear: the mark
8:  movem.l (%sp),%d0/%d3/%a0
    lea     12(%sp),%sp
9:  rts
#ifdef FIRSTREC
| The firstrec image: at a start, on each sampler track whose record the start queues has a trig, the ONCE on that
| record's step spent (first_kept, below). The step's row is the pattern's data + 15301 + 9287 a track + 144 a step,
| as the step routine has it. Keeps all but a0.
    .globl  first_spend
first_spend:
    lea     -20(%sp),%sp
    movem.l %d0-%d2/%a1-%a2,(%sp)
    moveq   #0,%d2
1:  move.l  %d2,%d0
    mulu.w  #142,%d0
    movea.l %d0,%a0
    adda.l  #PARAM_SENT + 62,%a0
    mvz.w   (%a0),%d0
    cmpi.l  #44 << 8,%d0
    bne.s   8f                      | not a sampler's track
    move.l  %d2,%d0
    mulu.w  #80,%d0
    movea.l %d0,%a0
    adda.l  #PLACES,%a0
    tst.l   4(%a0)
    beq.s   8f                      | no trig queued
    lea     first_kept,%a1
    mvz.b   (%a1,%d2.l),%d1         | the step its record plays
    cmpi.l  #0xff,%d1
    beq.s   8f                      | a step with no locks
    move.l  PATTERN_DATA,%d0
    beq.s   8f
    movea.l %d0,%a2
    move.l  %d2,%d0
    mulu.w  #9287,%d0
    adda.l  %d0,%a2
    move.l  %d1,%d0
    mulu.w  #144,%d0
    adda.l  %d0,%a2
    lea     15301(%a2),%a2          | the step's row
    mvz.w   48(%a2),%d0
    cmpi.l  #LOCK_ONCE,%d0
    bne.s   8f
    move.w  #LOCK_SPENT,48(%a2)     | this pass records by the record's copy; the next does not
    lea     first_step,%a1
    move.b  %d1,(%a1,%d2.l)
    lea     first_late_v,%a1
    moveq   #1,%d0
    move.b  %d0,(%a1,%d2.l)
8:  addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d2,%d0
    bne.w   1b
    movem.l (%sp),%d0-%d2/%a1-%a2
    lea     20(%sp),%sp
    rts
#endif
    .popsection
#endif

| Z set: d4 is a sampler's track, and a1 its byte of once_vars. Uses d0.
once_track:
    moveq   #7,%d0
    cmp.l   %d4,%d0
    bcs.s   1f                      | an analog track: Z is clear
    lea     once_vars(%pc),%a1
    adda.l  %d4,%a1
    move.l  %d4,%d0
    mulu.w  #142,%d0
    add.l   #PARAM_SENT + 62,%d0
    movea.l %d0,%a0
    mvz.w   (%a0),%d0               | the machine's type, a byte up
    cmpi.l  #44 << 8,%d0
1:  rts

| In place of stock's `movel %fp,%sp@-` and its call of the routine that gathers a step's locks (six
| bytes). On the stack: the return, then stock's other five arguments, the track's table first. Stock
| pops six longs after the call, so the return address is left where the event was.
once_seq:
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    move.l  %fp,-(%sp)              | the event
    jsr     STEP_LOCKS
    lea     24(%sp),%sp
#ifdef STAY
| The stay image. The routine that plays a step has two callers. The sequencer's (0x4008cf86) hands it 0 for the
| event's place. The other (0x4008c288, in 0x4008c128) hands it a place: it plays the step the sequencer is on, for
| one track or all, and stock runs it whenever a track of the pattern is changed (two listeners jump to it,
| 0x400179f2 and 0x40018ff6) and at a few keys. With the sequencer stopped the step it is on is the first. So a lock
| made at ONCE on the first step was spent by the change that made it, and the main task took it off: 
| And a track's own ONCE was
| used up by any change to the track. That caller is no play here: nothing of ours is done for it.
| The place is the step routine's fifth argument: 56 bytes of its frame, its return and four arguments above the
| return and the five longs stock has pushed here.
#ifdef FIRSTREC
| The firstrec image. A start plays the first step of the first pass by none of this: it queues the record this caller
| (the other one) built last for each track, at STOP or a listener's pass, its locks in the buffer its + 68 points at
| (docs/FINDINGS.md, the recprobe tool). That record carries a ONCE and records, and the ONCE was never spent there. So
| this caller's step and table are kept a track (first_keep), a start spends the ONCE on that step (first_spend), and
| the sequencer's own play of that step on the next pass has the main task take the spent lock off (first_late).
    tst.l   100(%sp)
    beq.s   2f
    move.l  4(%sp),%d0
    jsr     first_keep
    bra.s   9f
2:  jsr     first_late
#else
    tst.l   100(%sp)
    bne.s   9f
#endif
#endif
    bsr.s   once_track
    bne.s   9f
    move.l  %d3,%d0
    lsl.l   #4,%d0
    movea.l %d0,%a0
    lsl.l   #3,%d0
    adda.l  %d0,%a0                 | 144 bytes a step
    adda.l  4(%sp),%a0              | the step's row in the track's table
    mvz.w   48(%a0),%d0             | slot 24
    cmpi.l  #LOCK_ONCE,%d0
    bne.s   1f
    move.w  #LOCK_SPENT,48(%a0)     | played once: the word in the pattern is no mark from here on
    moveq   #1,%d0
    move.b  %d0,8(%a1)              | and the main task is to take it off
    bra.s   3f
1:  lsr.l   #8,%d0
    cmpi.l  #0x52,%d0               | REC_LOCK_ON: the step records by its own lock, and the track's ONCE is used up
    beq.s   3f
    cmpi.l  #0x29,%d0               | REC_LOCK_OFF: it does not, and the track's ONCE waits
    beq.s   9f
    tst.b   (%a1)
    beq.s   9f
    move.l  8(%fp),%d0              | the event's count of locks: 71 is all it has room for
    moveq   #70,%d1
    cmp.l   %d0,%d1
    bcs.s   9f
    lsl.l   #3,%d0
    lea     20(%fp,%d0.l),%a0
    move.l  #0x00185280,(%a0)        | one more: (slot 24, on), as the gathering routine writes one
    addq.l  #1,8(%fp)
3:  clr.b   (%a1)
9:  movea.l (%sp),%a0
    jmp     (%a0)

| In place of stock's `clrl %fp@(8)`, for a step with no locks (four bytes: a bsr.w, so this run is near it).
| d0, d1, a0 and a1 hold nothing of stock's here: the other way to where both go on is through a call.
once_none:
    clr.l   8(%fp)                  | stock's: no locks in the event
#ifdef STAY
#ifdef FIRSTREC
    tst.l   80(%sp)                 | the firstrec image: this caller's record is a step with no locks
    beq.s   2f
    moveq   #0,%d0
    jsr     first_keep
    bra.s   1f
2:  jsr     first_late
#else
    tst.l   80(%sp)                 | the stay image: the step routine's fifth argument, as above, from under one return
    bne.s   1f
#endif
#endif
    bsr.w   once_track
    bne.s   1f
    tst.b   (%a1)
    beq.s   1f
    clr.b   (%a1)
    lea     20(%fp),%a0
    move.l  #0x00185280,(%a0)        | (slot 24, on): its one lock
    addq.l  #1,8(%fp)
1:  rts

| In place of the main task's one wait for a message, (queue) -> the message: stock's wait, and when it has
| one, what the sequencer left for this task (engine/onceclean.c). Stock reads d0 alone after it.
once_loop:
    move.l  4(%sp),-(%sp)
    jsr     MAIN_WAIT
    move.l  %d0,(%sp)
#ifdef SCRATCH
| The scratch image: the takes held on the drive once the feed has stopped (engine/scratch.c).
    jsr     SCRATCH_POLL_AT
#endif
#ifdef NEXT
| The next image: a track whose DEST is NEXT holds a free place, and its SMPL goes to its take (engine/recpage.c).
    jsr     NEXT_POLL_AT
#endif
    lea     once_vars+8(%pc),%a0
    move.l  (%a0)+,%d0
    or.l    (%a0),%d0
#ifdef STAY
| The stay image: and the srr image's eight bytes (engine/recword.S), which say a track's old locks of MODE are to
| go. Until here they were looked at only when a ONCE had been spent: the old locks stayed, and went, with any lock
| of the reduction made since, at the first ONCE spent after. The routine is in a run of its own, for room here.
    lea     SRR_DIRTY_AT,%a0
    or.l    (%a0)+,%d0
    or.l    (%a0),%d0
    beq.s   1f
    jsr     once_clean
#else
    beq.s   1f
    bsr.w   once_clean
#endif
1:  move.l  (%sp)+,%d0
    rts

#ifdef HANDREC
| The handrec image. 
|
| While the sequencer is stopped, a track whose own REC is at ONCE (its byte
| of once_vars) sends REC's mark (engine/recword.S HANDREC), so a note played by hand records. A start takes every
| track's ONCE back: armed while stopped is for that, not for the first step the sequencer plays.
|
| In place of a start's `movel %d0,SEQ_STATE` (six bytes; 0x4008ad50 after MIDI 0xFA, and 0x4008b602): that store,
| and the eight bytes cleared, and any take held by hand let go. Keeps all but a0, which both places load next.
    .globl  hand_start
hand_start:
    move.l  %d0,SEQ_STATE
#ifdef FIRSTREC
    jsr     first_spend             | the firstrec image: the ONCE of the step each track's queued record plays
#endif
    lea     once_vars(%pc),%a0
    clr.l   (%a0)+
    clr.l   (%a0)
    lea     hand_hold,%a0           | and a take held by hand ends
    moveq   #9,%d0
1:  clr.l   (%a0)+
    subq.l  #1,%d0
    bne.s   1b
    moveq   #1,%d0                  | stock's d0 as it was: the state
    rts
#endif

#ifdef FIRSTREC
| The firstrec image's numbers and its two routines in the step routine (engine/once.S FIRSTREC, in once_seq).
| first_kept: a byte a track, the step of the record the other caller built last (0xff: a step with no locks).
| first_step: the step a start spent a ONCE on; first_late_v: 1 while that lock waits to be taken off.
    .globl  first_kept, first_step, first_late_v, first_keep, first_late
first_kept:
    .fill   8,1,0xff
first_step:
    .fill   8,1,0
first_late_v:
    .fill   8,1,0

| (d0 the track's table or 0, d3 the step, d4 the track). Uses d1, a0.
first_keep:
    moveq   #7,%d1
    cmp.l   %d4,%d1
    bcs.s   1f
    lea     first_kept(%pc),%a0
    moveq   #-1,%d1
    tst.l   %d0
    beq.s   2f
    move.l  %d3,%d1
2:  move.b  %d1,(%a0,%d4.l)
1:  rts

| The sequencer's play of step d3 on track d4: the step a start spent a ONCE on, played again, has the main task take
| the spent lock off (its event has it, no mark: nothing records, and nothing held from the first pass goes on).
| Uses d0, a0.
first_late:
    moveq   #7,%d0
    cmp.l   %d4,%d0
    bcs.s   1f
    lea     first_late_v(%pc),%a0
    tst.b   (%a0,%d4.l)
    beq.s   1f
    lea     first_step(%pc),%a0
    mvz.b   (%a0,%d4.l),%d0
    cmp.l   %d3,%d0
    bne.s   1f
    lea     first_late_v(%pc),%a0
    clr.b   (%a0,%d4.l)
    lea     once_vars + 8(%pc),%a0
    adda.l  %d4,%a0
    move.b  #1,(%a0)
1:  rts
#endif
