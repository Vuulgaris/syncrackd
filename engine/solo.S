| Main CPU (section 3, OS 1.42 only): the purple pattern mutes as solos. The solo image.
|
| A pattern's mutes are a word in its settings, a bit a track: bits 0..11 the twelve tracks, bit 12 the FX track. The
| UI reads and writes that word, and it is what is saved. What makes sound goes by two copies of it: the per-block
| routine's (PATTERN_MUTES: stock's trig test for a MIDI track and for the FX track, and our mixer link and analog
| mute, which silence a track) and the MIDI engine's. Each copy has two writers, a routine of twelve bytes the UI
| calls and a store in the engine's own message loop.
|
| Here all four store, in place of the word, the tracks its solos silence: with any of bits 0..11 set, those twelve
| bits turned over; with none, the word as it is. Bit 12 is never touched and never counts. So every reader goes on as
| it was, a track with its bit set in the pattern is the one that is heard, and the pattern's own word stays what the
| keys set. A global mute is a word of its own and still mutes.
|
| And the keys: the routine that colours the twelve track keys asks, of a pattern or of a song row, "is this track's
| bit set", and lights the key when it is not. It is given "is this track silenced by a solo" in its place (solo_key,
| solo_key_row), and so is the one draw that asks the same of a pattern. The routine a key press toggles a bit through
| still reads the bit itself.
|
| Registers: the two routines are called as stock's were, with d0 dead after them at all six calls (docs/FINDINGS.md)
| and a0 stock's own; the two stores use d0 alone, which the next instruction that runs loads at both places. solo_key
| is called as stock's (pattern, track) is, and uses what that uses.
    .section .cave.s,"ax"
    .globl  solo_set, solo_msg, solo_set_midi, solo_msg_midi, solo_word, solo_key, solo_key_row

solo_set:                           | (word), in place of stock's routine stock's own a0: the pattern's word, in place
    lea     6(%sp),%a0              | of stock's store
solo_msg:
    mvz.w   (%a0),%d0
    bsr.s   solo_word
    move.w  %d0,PATTERN_MUTES
    rts

solo_set_midi:                      | the same two for the MIDI engine's copy
    lea     6(%sp),%a0
solo_msg_midi:
    mvz.w   (%a0),%d0
    bsr.s   solo_word
    move.w  %d0,MIDI_PATTERN_MUTES
    rts

solo_word:                          | d0's low word, a pattern's mutes -> the tracks its solos silence. d0 alone the
    lsl.l   #4,%d0                  | twelve tracks' bits are the low word's upper twelve
    tst.w   %d0
    beq.s   1f                      | no solo: nothing is silenced the tracks that are not soloed
    eori.l  #0xfff0,%d0
1:  lsr.l   #4,%d0
    rts

solo_key:                           | (pattern, track) -> 1 when a solo of the pattern silences the track
    move.l  4(%sp),%a0
    move.l  %a0,-(%sp)
    move.l  (%a0),%a0
    move.l  PATTERN_SETTINGS(%a0),%a0
    jsr     (%a0)                   | the pattern's settings, as stock's own routine asks for them
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   2f                      | none: 0, as stock answers
    move.l  %d0,%a0
    mvz.w   16(%a0),%d0             | its word of mutes
    bsr.s   solo_word
    move.l  8(%sp),%d1
1:  lsr.l   %d1,%d0                 | the track's bit: for track 12, the FX track's own mute as it was
    moveq   #1,%d1
    and.l   %d1,%d0
2:  rts

solo_key_row:                       | d0: a song row's word, d2: the track -> d0 the same answer. d1 is the caller's to load
    bsr.s   solo_word
    move.l  %d2,%d1
    bra.s   1b
