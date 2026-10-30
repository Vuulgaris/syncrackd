/* EMAC hook in C. Same semantics as emu/emac.py, which stays the reference:
 * tests/test_emu_engine.py checks the two give bit-identical audio.
 *
 * Built by emu/native.py into build/. Unicorn functions are passed in as
 * pointers so this file links against nothing.
 */
#include <stddef.h>
#include <stdint.h>

typedef struct uc_struct uc_engine;
typedef size_t uc_hook;

typedef struct {
    int (*reg_read)(uc_engine *, int, void *);
    int (*reg_write)(uc_engine *, int, const void *);
    int (*mem_read)(uc_engine *, uint64_t, void *, uint64_t);
    int (*hook_add)(uc_engine *, uc_hook *, int, void *, void *, uint64_t, uint64_t, ...);
    int regid[16];              /* D0..D7, A0..A7 */
    int hook_code;
} uc_api;

typedef struct {
    int64_t acc[4];
    uint32_t macsr;
    uint32_t overflows;
    uint32_t fault;             /* address of an instruction in an unmodelled mode */
    uint32_t pad;
    uint64_t ops;               /* EMAC instructions run */
    uint64_t insns;             /* original instructions run, EMAC included */
} emac_state;

enum { K_MAC, K_STORE, K_LOAD, K_TO_MACSR, K_FROM_MACSR };

typedef struct {
    emac_state *st;
    uint32_t imm;
    int16_t d16;
    uint8_t kind, acc, rx, ry, rw, sub, clear, mode, areg, src_imm, src_reg;
} emac_insn;

/* One hook covers a whole code region. table[(addr - base) / 2] is NULL for
 * an ordinary instruction, SKIP for the NOPs inside a replaced EMAC
 * instruction, or the EMAC instruction to run. Unicorn walks its whole hook
 * list on every hooked instruction, so one hook per EMAC site is far slower. */
typedef struct {
    emac_state *st;
    const emac_insn **table;
    uint32_t base;
    uint32_t n;
} emac_region;

#define SKIP ((const emac_insn *)1)

#define OMC 0x80u
#define SU 0x40u
#define FI 0x20u
#define RT 0x10u
#define F_N 0x8u
#define F_Z 0x4u
#define F_V 0x2u
#define F_EV 0x1u
#define PAV0 0x100u
#define ACC_MAX (((int64_t)1 << 47) - 1)
#define ACC_MIN (-((int64_t)1 << 47))

static uc_api api;

void emac_setup(const uc_api *a) { api = *a; }

static uint32_t rd(uc_engine *uc, int r)
{
    uint32_t v = 0;
    api.reg_read(uc, api.regid[r], &v);
    return v;
}

static void wr(uc_engine *uc, int r, uint32_t v) { api.reg_write(uc, api.regid[r], &v); }

static void flags(emac_state *s, int n)
{
    int64_t a = s->acc[n];
    uint32_t f = s->macsr & ~(F_N | F_Z | F_V | F_EV);
    if (a < 0) f |= F_N;
    if (a == 0) f |= F_Z;
    if (a < -((int64_t)1 << 39) || a >= ((int64_t)1 << 39)) f |= F_EV;
    if (f & (PAV0 << n)) f |= F_V;
    s->macsr = f;
}

static void mac(emac_state *s, int n, uint32_t x, uint32_t y, int sub)
{
    uint32_t pav = PAV0 << n;
    if ((s->macsr & OMC) && (s->macsr & pav)) {
        s->macsr |= F_V;
        return;
    }
    /* floor((x * y) / 2^23); |x * y| <= 2^62 so the shift is safe in 64 bits */
    int64_t p = ((int64_t)(int32_t)x * (int64_t)(int32_t)y) >> 23;
    int64_t r = sub ? s->acc[n] - p : s->acc[n] + p;
    if (r < ACC_MIN || r > ACC_MAX) {
        s->overflows++;
        s->macsr |= pav;
        if (s->macsr & OMC)
            r = r > 0 ? 0x007FFFFFFF00LL : -0x008000000000LL;
        else
            r = (int64_t)((uint64_t)r << 16) >> 16;
    }
    s->acc[n] = r;
    flags(s, n);
}

static void run(uc_engine *uc, uint64_t address, const emac_insn *i)
{
    emac_state *s = i->st;
    s->ops++;
    if (i->kind == K_TO_MACSR) {
        s->macsr = (i->src_imm ? i->imm : rd(uc, i->src_reg)) & 0xFFF;
        return;
    }
    if (i->kind == K_FROM_MACSR) {
        wr(uc, i->rx, s->macsr);
        return;
    }
    if ((s->macsr & (FI | SU | RT)) != FI) {
        if (!s->fault) s->fault = (uint32_t)address;
        return;
    }
    switch (i->kind) {
    case K_MAC: {
        uint32_t x = rd(uc, i->rx), y = rd(uc, i->ry);
        if (i->mode) {
            uint32_t ea = rd(uc, 8 + i->areg);
            uint8_t b[4];
            if (i->mode == 4) {
                ea -= 4;
                wr(uc, 8 + i->areg, ea);
            } else if (i->mode == 5) {
                ea += (uint32_t)(int32_t)i->d16;
            }
            api.mem_read(uc, ea, b, 4);
            if (i->mode == 3) wr(uc, 8 + i->areg, ea + 4);
            wr(uc, i->rw, (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3]);
        }
        mac(s, i->acc, x, y, i->sub);
        break;
    }
    case K_STORE: {
        int64_t a = s->acc[i->acc];
        uint32_t v = (uint32_t)(a >> 8);
        if (s->macsr & OMC) {
            int64_t top = a >> 39;
            if (top != 0 && top != -1) v = a >= 0 ? 0x7FFFFFFFu : 0x80000000u;
        }
        if (i->clear) {
            s->acc[i->acc] = 0;
            s->macsr &= ~(PAV0 << i->acc);
        }
        wr(uc, i->rx, v);
        break;
    }
    case K_LOAD: {
        uint32_t v = i->src_imm ? i->imm : rd(uc, i->src_reg);
        s->acc[i->acc] = (int64_t)(int32_t)v * 256;
        s->macsr &= ~(PAV0 << i->acc);
        flags(s, i->acc);
        break;
    }
    }
}

void region_hook(uc_engine *uc, uint64_t address, uint32_t size, void *user)
{
    const emac_region *r = user;
    uint32_t k = ((uint32_t)address - r->base) >> 1;
    const emac_insn *i = k < r->n ? r->table[k] : NULL;
    (void)size;
    if (i == SKIP) return;
    r->st->insns++;
    if (i) run(uc, address, i);
}

int emac_install(uc_engine *uc, emac_region *r)
{
    uc_hook h;
    return api.hook_add(uc, &h, api.hook_code, (void *)region_hook, r,
                        (uint64_t)r->base, (uint64_t)r->base + 2 * (uint64_t)r->n - 1);
}
