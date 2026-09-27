/*
 * Smoothed goop: a display copy of the pollution mask, 3x3 tent-filtered.
 *
 * The gameplay mask (TPollutionLayer +0x54, the layer's tex0) is NEVER written.
 * When each layer loads, we allocate one block holding:
 *   - a copy of the model's ResTIMG array (J3DTexture +4);
 *   - an I8 texture the size of the mask, D = tent3x3(mask).
 * In the copy, the entry that pointed to the mask points to D, and the model's
 * J3DTexture is repointed at the copy. Materials (display list rebuilt on every
 * draw) therefore read D; gameplay (unk54, unk58, PollutionCount) keeps reading
 * the mask through its own pointers.
 *
 * Updating D:
 *   - the area marked by each stamp (TPollutionTexStamp::pushTask), recomputed
 *     for 8 passes (the GPU copies the mask back to RAM with some delay);
 *   - background refresh: 4 rows per pass, for any other writer;
 *   - "model" tasks (pushModelStampTask: Petey's vomit and drops, Gooper
 *     Blooper, Shadow Mario, polluters...): a square area around the stamp
 *     model, recomputed for 8 passes and renewed on every task (frame by frame
 *     while a puddle spreads). "Joint object" tasks (pushJointObjStampTask)
 *     are left to the background refresh.
 * Dolphin detects CPU-modified textures by sampling their data (the first word
 * is part of the sample): once per pass, the 2 low bits of texel (0,0) receive
 * a modulo-3 counter, which differs from pass to pass at 1, 2 or 4 substeps per
 * frame. A per-update toggle cancelled out when two updates landed in the same
 * frame (measured 2026-09-27: layer marked every frame, texel frozen, display
 * lagging by several seconds depending on where the water hit).
 *
 * Soft edge (optional): alpha stage 1 (APREV-0.5)x4, stage 2 clamp(+0.5),
 * blend SRCALPHA/INVSRCALPHA, alpha compare ref0 = 1 -- only if the material
 * has exactly the signature of the Bianco goop.
 *
 * Switches (bytes in RAM, 0 = enabled): cfg.no_smooth, cfg.no_soft,
 * cfg.no_model.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;

/* Game symbols; addresses supplied at link time. */
extern void initTexImage(void *layer, const char *name);
extern void TJointModel_perform(void *layer, u32 flags, void *gfx);
extern void DCStoreRange(void *p, u32 n);
extern void *JKRHeap_sCurrentHeap;

#define VT_TEVBLOCK4    0x803E0AB0u
#define VT_PEBLOCK_FULL 0x803E0968u

#define RD32(p) (*(volatile u32 *)(p))
#define RD16(p) (*(volatile u16 *)(p))
#define RD8(p)  (*(volatile u8 *)(p))

/* goop_cfg and goop_roots: code-cave area, zero at boot, outside the profile.
 * Each Slot lives at the head of the block allocated for its layer (level
 * heap), so it disappears with the level. A goop_roots pointer is only written
 * through after live(): a live pollution layer whose mask is ours. */
#define MAXL 16          /* Bianco (pink goop): 9 layers */
struct Slot {
    u8 *layer;          /* TPollutionLayer* */
    u8 *mask;           /* gameplay mask */
    u8 *disp;           /* smoothed copy */
    u8 *tex;            /* model's J3DTexture* */
    u8 *orig_arr;       /* original ResTIMG array */
    u8 *new_arr;        /* repointed copy */
    u16 w, h;
    u16 cursor;
    struct Rect { u16 x0, x1, y0, y1; u8 frames, pad; } z[2];
                        /* recomputed areas: [0] stamps, [1] model tasks */
    u8 idx;
    u8 soft_on;
    u8 nonce;           /* modulo-3 counter, written into texel (0,0) */
    u8 dl_tick;         /* frozen display lists checked every 16 passes */
};
struct Cfg {
    u32 magic;          /* 'GOOP' once initialised at least once */
    u8 no_smooth;
    u8 no_soft;
    u16 nlayers;
    u32 last_free;
    u32 last_need;
    u32 fails;
    u32 updates;
    u8 no_model;        /* +24: model-task areas */
};
extern struct Cfg goop_cfg;
extern struct Slot *goop_roots[MAXL];

static int is_layer_vt(u32 vt)
{
    return vt == 0x803C2160u || vt == 0x803C21BCu || vt == 0x803C2218u
        || vt == 0x803C1E90u || vt == 0x803C2274u || vt == 0x803C1EECu;
}

static struct Slot *live(struct Slot *s)
{
    if (!s || !s->layer || !is_layer_vt(RD32(s->layer)) || RD32(s->layer + 0x54) != (u32)s->mask)
        return 0;
    return s;
}

static inline u32 rowbase(u32 y, u32 tw) { return (y >> 2) * tw * 32 + ((y & 3) << 3); }
static inline u32 coloff(u32 x) { return ((x >> 3) << 5) + (x & 7); }

__attribute__((noinline)) static void smooth_rows(struct Slot *s, u32 y0, u32 y1, u32 xa, u32 xb)
{
    u16 v[520];
    u32 w = s->w, h = s->h, tw = w >> 3;
    const u8 *m = s->mask;
    u8 *d = s->disp;
    u32 xl = xa ? xa - 1 : 0, xr = (xb + 1 < w) ? xb + 1 : w - 1;
    for (u32 y = y0; y <= y1; ++y) {
        u32 ym = y ? y - 1 : 0, yp = (y + 1 < h) ? y + 1 : h - 1;
        u32 rm = rowbase(ym, tw), r0 = rowbase(y, tw), rp = rowbase(yp, tw);
        for (u32 x = xl; x <= xr; ++x) {
            u32 o = coloff(x);
            v[x] = (u16)(m[rm + o] + 2u * m[r0 + o] + m[rp + o]);
        }
        for (u32 x = xa; x <= xb; ++x) {
            u32 a = x ? v[x - 1] : v[x];
            u32 c = (x + 1 < w) ? v[x + 1] : v[x];
            d[r0 + coloff(x)] = (u8)((a + 2u * v[x] + c + 8u) >> 4);
        }
    }
    /* touched tile rows */
    u32 b0 = (y0 >> 2) * tw * 32, b1 = ((y1 >> 2) + 1) * tw * 32;
    DCStoreRange(d + b0, b1 - b0);
    goop_cfg.updates++;
}

/* Soft edge. Full BP words (id + 3 bytes). The TEV stages sit at +0x29 and
 * +0x31 in the block, unaligned: the Gekko (750) handles unaligned integer
 * accesses in hardware, and so does Dolphin. */
#define W32(p) (*(volatile u32 *)(p))
#define ST1_ORIG 0xC331FF80u
#define ST2_ORIG 0xC500FF80u
#define ST1_SOFT 0xC322FF80u   /* (APREV-0.5)x4, no clamp */
#define ST2_SOFT 0xC509FF80u   /* clamp(APREV+0.5) */
#define BL_ORIG  0x00010003u   /* NONE, ONE, ZERO, COPY */
#define BL_SOFT  0x01040503u   /* BLEND, SRCALPHA, INVSRCALPHA, COPY */

__attribute__((noinline)) static void set_soft(u8 *layer, int on)
{
    u8 *md = (u8 *)RD32(layer + 0x24);
    u32 n = RD16(md + 0x24);
    u8 **mats = (u8 **)RD32(md + 0x28);
    u32 s1 = on ? ST1_ORIG : ST1_SOFT, s2 = on ? ST2_ORIG : ST2_SOFT, bl = on ? BL_ORIG : BL_SOFT;
    for (u32 k = 0; k < n; ++k) {
        u8 *mat = mats[k];
        u8 *tev = (u8 *)RD32(mat + 0x28), *pe = (u8 *)RD32(mat + 0x30);
        if (RD32(tev) != VT_TEVBLOCK4 || RD32(pe) != VT_PEBLOCK_FULL)
            continue;
        if (W32(tev + 0x29) != s1 || W32(tev + 0x31) != s2 || W32(pe + 0x0C) != bl)
            continue;                        /* unknown signature: leave it alone */
        W32(tev + 0x29) = s1 ^ ST1_ORIG ^ ST1_SOFT;
        W32(tev + 0x31) = s2 ^ ST2_ORIG ^ ST2_SOFT;
        W32(pe + 0x0C) = bl ^ BL_ORIG ^ BL_SOFT;
        pe[0x0A] = on ? 1 : 128;
    }
}

/* Frozen display lists. Some layers (the large Bianco ground layers, pink goop:
 * measured 2026-09-27) have a locked J3DMatPacket (+0x10 bit 0): their display
 * list is built once and the texture address (BP 0x94, TX_IMAGE3 map0) is
 * frozen on the mask. Repointing the J3DTexture has no effect there, so we
 * rewrite that word, in both buffers of the J3DDisplayListObj, to the target
 * (smoothed copy or mask). J3DModel +0x80 packets (stride 0x48), packet +0x30
 * J3DDisplayListObj: +0 / +4 buffers.
 * The DL starts with the BP commands (5 bytes) for texture 0; measured on the
 * 2 affected layers: BP 0x94 at +5 in both buffers. Only that word is
 * rewritten, and only if it already holds the mask or copy address: any other
 * layout is left untouched. */
__attribute__((noinline)) static void patch_dl(struct Slot *s, u32 to)
{
    u8 *pk = (u8 *)RD32(RD32(s->layer + 0x28) + 0x80);   /* material 0 packet */
    if (!(RD32(pk + 0x10) & 1))
        return;
    u32 vm = 0x94000000u | (((u32)s->mask & 0x1FFFFFFF) >> 5);
    u32 vd = 0x94000000u | (((u32)s->disp & 0x1FFFFFFF) >> 5);
    u8 *dl = (u8 *)RD32(pk + 0x30);
    for (u32 b = 0; b < 8; b += 4) {
        u8 *q = (u8 *)RD32(dl + b) + 5;
        u32 v = W32(q + 1);                          /* unaligned: supported */
        if (q[0] == 0x61 && (v == vm || v == vd)) {
            W32(q + 1) = 0x94000000u | ((to & 0x1FFFFFFF) >> 5);
            __asm__ volatile("dcbst 0, %0" :: "r"(q) : "memory");   /* the GPU reads RAM */
        }
    }
}

typedef s32 (*fn_free)(void *);
typedef void *(*fn_alloc)(void *, u32, s32);

/* replaces "bl initTexImage" in TPollutionLayer::initJointModel (0x801A0EB8) */
void goop_init(u8 *layer, const char *name)
{
    initTexImage(layer, name);

    u32 idx = RD32(layer + 4);
    goop_cfg.magic = 0x474F4F50;
    int free_i = -1;
    for (u32 i = 0; i < MAXL; ++i) {
        struct Slot *o = goop_roots[i];
        /* layer 0 = new level: everything is stale; otherwise same layer or same index */
        if (idx == 0 || (o && (!live(o) || o->layer == layer || o->idx == idx)))
            goop_roots[i] = 0;
        if (!goop_roots[i] && free_i < 0)
            free_i = (int)i;
    }
    if (free_i < 0) { goop_cfg.fails++; return; }

    u8 *md = (u8 *)RD32(layer + 0x24);
    u8 *tex = (u8 *)RD32(md + 0xAC);
    u8 *mask = (u8 *)RD32(layer + 0x54);
    u8 *timg = (u8 *)RD32(layer + 0x58);
    u32 w = RD16(timg + 2), h = RD16(timg + 4);
    u32 n = RD16(tex);
    u8 *arr = (u8 *)RD32(tex + 4);
    if (RD8(timg) != 1 || w > 512 || h > 1024 || (w & 7) || (h & 3) || n == 0 || n > 16) {
        goop_cfg.fails++;
        return;
    }
    u32 hdr = 64 + ((n * 0x20 + 31) & ~31u);        /* Slot + ResTIMG copy */
    u32 need = hdr + w * h;
    void *heap = JKRHeap_sCurrentHeap;
    u32 *vt = *(u32 **)heap;
    s32 fr = ((fn_free)vt[36 / 4])(heap);
    goop_cfg.last_free = (u32)fr;
    goop_cfg.last_need = need;
    if (fr < 0 || (u32)fr < need + 0x80000) {  /* leave 512 KB to the level */
        goop_cfg.fails++;
        return;
    }
    u8 *blk = (u8 *)((fn_alloc)vt[12 / 4])(heap, need, 32);
    if (!blk) { goop_cfg.fails++; return; }

    struct Slot *s = (struct Slot *)blk;
    u8 *copy = blk + 64;
    u8 *disp = blk + hdr;
    for (u32 i = 0; i < n * 0x20; ++i)
        copy[i] = arr[i];
    for (u32 i = 0; i < n; ++i) {
        u8 *o = arr + i * 0x20, *c = copy + i * 0x20;
        u8 *data = o + RD32(o + 0x1C);
        u8 *tgt = (data == mask) ? disp : data;
        *(u32 *)(c + 0x1C) = (u32)(tgt - c);
        if (RD16(o + 0x0A))
            *(u32 *)(c + 0x0C) = (u32)((o + RD32(o + 0x0C)) - c);
    }
    s->layer = layer; s->mask = mask; s->disp = disp; s->tex = tex;
    s->orig_arr = arr; s->new_arr = copy; s->w = (u16)w; s->h = (u16)h;
    s->cursor = 0; s->z[0].frames = 0; s->z[1].frames = 0; s->idx = (u8)idx; s->soft_on = 0; s->dl_tick = 0;
    goop_roots[free_i] = s;
    goop_cfg.nlayers++;
    smooth_rows(s, 0, h - 1, 0, w - 1);
    DCStoreRange(blk, need);
}

/* replaces "bl TJointModel::perform" at the end of TPollutionLayer::perform (0x801A12C8) */
void goop_perform(u8 *layer, u32 flags, void *gfx)
{
    TJointModel_perform(layer, flags, gfx);
    if (!(flags & 1))
        return;
    struct Slot *s = 0;
    for (u32 i = 0; i < MAXL; ++i)
        if (goop_roots[i] && goop_roots[i]->layer == layer) { s = live(goop_roots[i]); break; }
    if (!s)
        return;
    u8 *cur = (u8 *)RD32(s->tex + 4);
    if (cur != s->orig_arr && cur != s->new_arr)     /* different model: leave it alone */
        return;
    int smooth = !goop_cfg.no_smooth;
    *(u32 *)(s->tex + 4) = (u32)(smooth ? s->new_arr : s->orig_arr);
    if ((s->dl_tick++ & 15) == 0)
        patch_dl(s, (u32)(smooth ? s->disp : s->mask));
    int soft = !goop_cfg.no_soft;
    if (soft != s->soft_on) { set_soft(layer, soft); s->soft_on = (u8)soft; }
    if (!smooth)
        return;
    for (u32 k = 0; k < 2; ++k) {
        struct Rect *z = &s->z[k];
        if (z->frames) {
            smooth_rows(s, z->y0, z->y1, z->x0, z->x1);
            --z->frames;
        }
    }
    u32 y0 = s->cursor, y1 = y0 + 3;
    if (y1 >= s->h) y1 = s->h - 1;
    smooth_rows(s, y0, y1, 0, s->w - 1);
    s->cursor = (u16)((y1 + 1 >= s->h) ? 0 : y1 + 1);
    s->nonce = (u8)(s->nonce >= 2 ? 0 : s->nonce + 1);
    s->disp[0] = (u8)((s->disp[0] & 0xFC) | s->nonce);
    DCStoreRange(s->disp, 32);
}

/* Area to recompute: square (cx, cy) +/- r, clamped to the layer, merged with
 * the current area if still active; recomputed for 8 passes. */
__attribute__((noinline)) static void mark_rect(struct Slot *s, struct Rect *z, s32 cx, s32 cy, s32 r)
{
    s32 xa = cx - r, xb = cx + r, ya = cy - r, yb = cy + r;
    if (xa < 0) xa = 0;
    if (ya < 0) ya = 0;
    if (xb >= s->w) xb = s->w - 1;
    if (yb >= s->h) yb = s->h - 1;
    if (xa > xb || ya > yb)
        return;
    if (z->frames == 0) { z->x0 = z->y0 = 0xFFFF; z->x1 = z->y1 = 0; }
    if ((u32)xa < z->x0) z->x0 = (u16)xa;
    if ((u32)xb > z->x1) z->x1 = (u16)xb;
    if ((u32)ya < z->y0) z->y0 = (u16)ya;
    if ((u32)yb > z->y1) z->y1 = (u16)yb;
    z->frames = 8;
}

static struct Slot *slot_of(u32 idx)
{
    for (u32 i = 0; i < MAXL; ++i) {
        struct Slot *s = live(goop_roots[i]);
        if (s && s->idx == (idx & 0xFF))
            return s;
    }
    return 0;
}

/* called by the trampoline on entry to TPollutionTexStamp::pushTask */
void goop_mark(u32 idx, u32 size, u32 x, u32 z)
{
    struct Slot *s = slot_of(idx);
    if (s)
        mark_rect(s, &s->z[0], x & 0xFFFF, z & 0xFFFF, (s32)(size & 0xFFFF) + 2);
}

/* Called by the pushModelStampTask trampoline. Square area centred on the
 * stamp model's translation (J3DModel +0x2C x, +0x4C z, scale +0x14), radius
 * 400 u x scale -- Petey's puddle measured at ~600 u for scale 2 (2026-09-27).
 * Area [1], separate from the stamp area, so two distant areas are never
 * merged. Integer arithmetic (fctiwz only): no float constants in memory. */
void goop_mark_model(u32 idx, u8 *model)
{
    struct Slot *s = slot_of(idx);
    if (!s || goop_cfg.no_model)
        return;
    float *b = (float *)(s->layer + 0x38);              /* x0, x1, z0, z1 */
    float *m = (float *)model;
    s32 x0 = (s32)b[0], dx = (s32)b[1] - x0;
    s32 z0 = (s32)b[2], dz = (s32)b[3] - z0;
    if (dx <= 0 || dz <= 0)
        return;
    float sc = m[0x14 / 4];
    s32 r = (s32)(sc + sc + sc + sc) * 100 * s->w / dx + 2;   /* 400 u x scale */
    mark_rect(s, &s->z[1], ((s32)m[0x2C / 4] - x0) * s->w / dx,
              ((s32)m[0x4C / 4] - z0) * s->h / dz, r);
}

/* Trampoline: saves r3-r8, calls goop_mark(r4, r5, r6, r7), replays the first
   instruction of pushTask (lwz r9, 8(r3)) and returns there. */
__asm__(
    ".globl goop_push_tramp\n"
    "goop_push_tramp:\n"
    "  stwu 1, -48(1)\n"
    "  mflr 0\n"
    "  stw 0, 52(1)\n"
    "  stw 3, 8(1)\n"
    "  stw 4, 12(1)\n"
    "  stw 5, 16(1)\n"
    "  stw 6, 20(1)\n"
    "  stw 7, 24(1)\n"
    "  stw 8, 28(1)\n"
    "  mr 3, 4\n"
    "  mr 4, 5\n"
    "  mr 5, 6\n"
    "  mr 6, 7\n"
    "  bl goop_mark\n"
    "  lwz 3, 8(1)\n"
    "  lwz 4, 12(1)\n"
    "  lwz 5, 16(1)\n"
    "  lwz 6, 20(1)\n"
    "  lwz 7, 24(1)\n"
    "  lwz 8, 28(1)\n"
    "  lwz 0, 52(1)\n"
    "  mtlr 0\n"
    "  addi 1, 1, 48\n"
    "  lwz 9, 8(3)\n"
    "  b pushTask_resume\n");

/* Trampoline for pushModelStampTask(r3 queue, r4 layer index, r5 J3DModel*):
   saves r3-r5, calls goop_mark_model(r4, r5), replays the first instruction
   (lhz r0, 0x28(r3)) and returns there. */
__asm__(
    ".section .text.tramp_model,\"ax\"\n"
    ".globl goop_model_tramp\n"
    "goop_model_tramp:\n"
    "  stwu 1, -32(1)\n"
    "  mflr 0\n"
    "  stw 0, 36(1)\n"
    "  stw 3, 8(1)\n"
    "  stw 4, 12(1)\n"
    "  stw 5, 16(1)\n"
    "  mr 3, 4\n"
    "  mr 4, 5\n"
    "  bl goop_mark_model\n"
    "  lwz 3, 8(1)\n"
    "  lwz 4, 12(1)\n"
    "  lwz 5, 16(1)\n"
    "  lwz 0, 36(1)\n"
    "  mtlr 0\n"
    "  addi 1, 1, 32\n"
    "  lhz 0, 0x28(3)\n"
    "  b modelTask_resume\n"
    ".previous\n");
