/* Main CPU (section 3, OS 1.42 only): the pbank image. 
 * one entry that moves to the next bank each time it is chosen, and the bank still
 * loads only with a project, as before (engine/banks.c). In a run of its own.
 *
 * The PROJECT menu is stock's list page, built once at the start by 0x401855d4(menu): three entries, each 0x54 bytes
 * from the heap, made by 0x400fa84c(item, name, action, icon, last, -1, 8) and added by 0x400fa082(menu, item). Each of
 * the four is stock's function object, 16 bytes: the data, a long, the manager (data, from, op), the call. The list asks
 * an entry's name each time it draws it (0x400fa5d2, a string returned through a0), runs its action when chosen
 * (0x400fa638), and leaves out an icon whose manager is 0 (0x400fa610). The menu redraws by its page at + 56
 * (0x400ffe22, as the list's own scroll does at 0x400ff42a). docs/FINDINGS.md, "The bank in the PROJECT menu".
 *
 * The constructor's end (0x401858b2, its restore) comes here: a fourth entry, SAMPLE BANK and the loaded bank, A>B with
 * another chosen, as the sampling page's BANK read. Our two calls take nothing from their function objects, so they use
 * the manager of stock's LOAD PROJECT name (0x401852d4), which makes a byte for a copy and frees it, whatever it holds. */
#include "sampler.h"

#define item_alloc ((void *(*)(u32))0x4010394c)
#define item_new ((void (*)(void *, const struct fn *, const struct fn *, const struct fn *, const struct fn *, s32, s32))0x400fa84c)
#define menu_add ((void (*)(void *, void *))0x400fa082)
#define redraw ((void (*)(void *))0x400ffe22)
#define MENU_PAGE 56                /* the menu's page, inside it */

#define CAVE __attribute__((section(".cave.pb"), noinline))

struct fn { const void *data; u32 pad; const void *manager; const void *call; };

void bank_hook(void);
void bank_name(void);
void bank_pick(void);

__asm__(".section .cave.pb,\"ax\",@progbits\n"
        "        .globl bank_hook, bank_name, bank_menu, w_sbank\n"
        "bank_menu:  .long 0\n"
        /* the entry's text, its last three places made again before each drawing (bank_text) */
        "w_sbank:    .asciz \"SAMPLE BANK A>B\"\n"
        "        .even\n"
        /* the three function objects the entry is made from, read by stock's copies only */
        "        .globl fn_name, fn_pick, fn_none\n"
        "fn_name:    .long 0, 0, 0x401852d4, bank_name\n"
        "fn_pick:    .long 0, 0, 0x401852d4, bank_pick\n"
        "fn_none:    .long 0, 0, 0, 0\n"
        /* the constructor's end: d0 kept, then stock's restore and return as they were */
        "bank_hook:\n"
        "        move.l  %d0,-(%sp)\n"
        "        move.l  %a2,-(%sp)\n"
        "        jsr     bank_add\n"
        "        addq.l  #4,%sp\n"
        "        move.l  (%sp)+,%d0\n"
        "        movem.l (24,%sp),%d2-%d6/%a2-%a6\n"
        "        lea     (128,%sp),%sp\n"
        "        rts\n"
        /* (a0: the string to make) -> d0 the same, as stock's LOAD PROJECT name (0x401851d8): a string of the text,
         * by stock's constructor (0x401bf31e(string, text, allocator)) */
        "bank_name:\n"
        "        link.w  %fp,#-8\n"
        "        move.l  %a0,(-4,%fp)\n"
        "        jsr     bank_text\n"
        "        pea     (-5,%fp)\n"
        "        pea     w_sbank\n"
        "        move.l  (-4,%fp),-(%sp)\n"
        "        jsr     0x401bf31e\n"
        "        move.l  (-4,%fp),%d0\n"
        "        unlk    %fp\n"
        "        rts\n"
        "        .text\n");
extern void *volatile bank_menu;
extern char w_sbank[16];
extern const struct fn fn_name, fn_pick, fn_none;

/* SAMPLE BANK A, or A>B with B chosen to be saved with the project */
void CAVE bank_text(void)
{
    u32 d = BANK_NOW < BANKS_N ? BANK_NOW : 0;
    u32 m = BANK_WANT < BANKS_N ? BANK_WANT : d;

    w_sbank[12] = 'A' + d;
    w_sbank[13] = m == d ? 0 : '>';
    w_sbank[14] = 'A' + m;
}

/* chosen: the next bank, after C the first, and the menu drawn again. Nothing is loaded. */
void CAVE bank_pick(void)
{
    u32 d = BANK_NOW < BANKS_N ? BANK_NOW : 0;
    u32 m = BANK_WANT < BANKS_N ? BANK_WANT : d;

    BANK_WANT = m + 1 < BANKS_N ? m + 1 : 0;
    if (bank_menu)
        redraw((u8 *)bank_menu + MENU_PAGE);
}

void CAVE bank_add(void *menu)
{
    void *item = item_alloc(0x54);

    bank_menu = menu;
    item_new(item, &fn_name, &fn_pick, &fn_none, &fn_none, -1, 8);
    menu_add(menu, item);
}
