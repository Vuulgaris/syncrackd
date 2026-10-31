/* Main CPU (section 3, OS 1.42 only), the evtime image: a tool, not one to keep. The per-block routine's stretch of
 * events and knobs (from its first call to its wait for the audio CPU, 28.5 hundredths of a block on a heavy pattern
 * with the unit's USB audio streaming, 25.1 without) cut in five by four more readings of the profile's timer
 * (engine/prof.S), each in front of one of stock's calls in it.
 *
 * A call of stock's comes here in place of its routine: d0 is kept on the stack for three instructions and taken back
 * before the jump, so the routine finds every register and its arguments as the caller left them (the caller may
 * count on a register the routine leaves alone). The readings go where the interrupt's start put what it stopped: +
 * 16 its stack pointer, + 12 its PC, + 56 the last of its six stack longs, + 60 the running task. A call that was not
 * made this block leaves those. tools/prof_read.py knows the layout. */
#define TIMER 0xfc07000c
#define STR2(x) #x
#define STR(x) STR2(x)

        .section .cave.e,"ax"
        .globl  ev_lap1, ev_lap2, ev_lap3, ev_lap4

        .macro  lap at, to
        move.l  %d0,-(%sp)
        move.l  TIMER,%d0
        move.l  %d0,PROF_AT+\at
        move.l  (%sp)+,%d0
        jmp     \to
        .endm

ev_lap1: lap 16, 0x40115b68
ev_lap2: lap 12, 0x400041cc
ev_lap3: lap 56, 0x4010d7a2
ev_lap4: lap 60, 0x4011a4c0
