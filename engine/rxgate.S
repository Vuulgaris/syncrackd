/* Main CPU (section 3, OS 1.42 only), the rxoff image: stock's receive of the host's USB audio is not run while the
 * unit is sending its own USB audio to the host (a capture), and the block of USB audio in is silence then.
 *
 * A host runs the device's output with its input, so silent packets come in either way, and for each (about five a
 * block) stock hands the receive descriptor back to the chip's own USB controller and sends a word of rate feedback,
 * each through 0x40005d72, which waits on the controller's registers (0xfc0b0140, bit 14, up to 1,000 tries).
 *
 * The call at 0x400a3a52 comes here. 0x405d40e4 is what 0x40003fee, stock's send of the unit's USB audio, tests
 * first: not 0 while the host takes the unit's audio. Then the 32 frames at 0x45512000 are cleared, by stock's own
 * clear (0x40115b68, (where, bytes)), as 0x400041cc clears what no packet brought. Else stock's routine, as it was.
 * Packets that came in meanwhile wait in its list, done, and are taken and their descriptors handed back at its next
 * call. */
#define SENDING 0x405d40e4

        .section .cave.x,"ax"
#ifdef CAPTURE
/* The rxcap image: the receive is not run only while the phone has said a capture is on, as well.
 *
 * the phone says when it captures. Its frames (engine/phone.c, CAPTURE): 0x65 on, 0x66 off. The word is first in the
 * run, where the phone's code finds it by the run's address. When the unit sends nothing (the host's stream stopped:
 * a phone unplugged in a capture) the word is cleared, so it cannot keep USB audio in off after. */
        .globl  rx_capture, rx_gate
rx_capture:
        .long   0
rx_gate:
        tst.l   SENDING
        bne.s   2f
        clr.l   rx_capture
        jmp     0x400041cc
2:      tst.l   rx_capture
        bne.s   1f
        jmp     0x400041cc
#else
        .globl  rx_gate
rx_gate:
        tst.l   SENDING
        bne.s   1f
        jmp     0x400041cc
#endif
1:      move.l  8(%sp),%d0              /* frames */
        lsl.l   #3,%d0                  /* two longs a frame */
        move.l  %d0,-(%sp)
        move.l  8(%sp),-(%sp)           /* where: the first argument, one long further down now */
        jsr     0x40115b68
        addq.l  #8,%sp
        rts
