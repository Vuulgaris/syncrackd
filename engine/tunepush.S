| The tune image (level 68): a pushed turn of every machine's TUNE moves it 1 a click. 
|
| How far a turn moves is the record's feel's (READ and
| run in emulation: 0x400f6a96 gives back, for every so many ticks, a step of the feel's third long, the pushed one's for a
| pushed turn: 4 in the plain feel 0x443db178 and the picker's 0x443db140); the record's second long (0x400f6866) only
| multiplies the ticks. So the second build, which made that long the first, changed nothing heard.
| Here: stock's flag clear and copy of record 431's entry (0x40192d58), the sampler's TUNE and the last TUNE the start-up
| fills, call this instead: it does both as they were, then gives every TUNE record in tune_list (offsets of their
| entries from 0x41ba0a24, made by the build) a copy of its own feel with a pushed step of 1 (tune_feels, written by the
| build from stock's numbers: stock builds its feels after this runs, so a copy made here is empty) and, for a pushed
| turn's multiplier, that feel's pushed ticks a step, so a pushed click is one step: 1. A record turned the other way (a
| negative unpushed multiplier) gets it negative. Run once, in the start-up, with stock's three arguments on the stack.

        .section .cave.t,"ax"
        .globl  tune_entry
tune_entry:
        clr.l   0x41ba9790              | record 431's flags, as stock's clrl
        move.l  12(%sp),-(%sp)          | 16
        move.l  12(%sp),-(%sp)          | the plain knob's sixteen bytes
        move.l  12(%sp),-(%sp)          | the entry's + 4
        jsr     (%a3)                   | stock's copy, as stock's jsr
        lea     12(%sp),%sp
        move.l  %a2,-(%sp)
        lea     tune_list,%a0
1:      moveq   #0,%d0
        move.w  (%a0)+,%d0
        add.l   #0x41ba0a24,%d0
        move.l  %d0,%a1                 | the record's entry: + 4 unpushed, + 8 pushed, + 16 its feel
        move.l  16(%a1),%d1             | stock's feel
        lea     tune_feels,%a2
2:      cmp.l   (%a2),%d1               | its copy (the build's, made from stock's numbers: stock builds its feels after this)
        beq.s   5f
        lea     32(%a2),%a2
        cmpa.l  #tune_feels_end,%a2
        bne.s   2b
        bra.s   7f                      | (a feel with no copy: left as stock's)
5:      lea     4(%a2),%a2
        move.l  %a2,16(%a1)             | its feel ours
        move.l  20(%a2),%d0             | a pushed turn's ticks a step
        tst.l   4(%a1)
        bpl.s   6f
        neg.l   %d0                     | turned the other way
6:      move.l  %d0,8(%a1)
7:        cmpa.l  #tune_end,%a0
        bne.s   1b
        move.l  (%sp)+,%a2
        rts
