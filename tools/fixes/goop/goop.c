/*
 * Goop lissée — copie d'affichage du masque de pollution, filtrée « tente » 3×3.
 *
 * Le masque de gameplay (TPollutionLayer +0x54, texture tex0 de la couche) n'est
 * JAMAIS écrit. On alloue, au chargement de chaque couche, un bloc contenant :
 *   - une copie du tableau des ResTIMG du modèle (J3DTexture +4) ;
 *   - une texture I8 de même taille que le masque, D = tente3x3(masque).
 * Dans la copie, l'entrée qui pointait vers le masque pointe vers D ; le
 * J3DTexture du modèle est rebranché sur la copie. Les matériaux (display list
 * reconstruite à chaque dessin) lisent donc D ; le gameplay (unk54, unk58,
 * PollutionCount) continue de lire le masque par ses propres pointeurs.
 *
 * Mise à jour de D :
 *   - zone marquée par chaque tampon (TPollutionTexStamp::pushTask), recalculée
 *     pendant 8 passages (le GPU recopie le masque en RAM avec un peu de retard) ;
 *   - rafraîchissement de fond : 4 lignes par passage, pour tout autre écrivain.
 * Dolphin détecte les textures modifiées par le CPU en échantillonnant leurs
 * données (le premier mot en fait partie) : une fois par passage, les 2 bits
 * de poids faible du texel (0,0) reçoivent un compteur modulo 3, différent
 * d'un passage à l'autre à 1, 2 ou 4 sous-pas par image. Un basculement par
 * mise à jour s'annulait quand deux mises à jour tombaient dans la même image
 * (relevé 2026-09-27 : couche marquée à chaque image, texel figé, affichage
 * en retard de plusieurs secondes selon l'endroit arrosé).
 *
 * Bord fondu (optionnel) : étage 1 alpha (APREV−0,5)×4, étage 2 clamp(+0,5),
 * blend SRCALPHA/INVSRCALPHA, alpha compare ref0 = 1 — seulement si le
 * matériau a exactement la signature de la goop de Bianco.
 *
 * Interrupteurs (octets en RAM, 0 = actif) : cfg.no_smooth, cfg.no_soft.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;

/* --- jeu (adresses fournies à l'édition de liens) ------------------------- */
extern void initTexImage(void *layer, const char *name);
extern void TJointModel_perform(void *layer, u32 flags, void *gfx);
extern void DCStoreRange(void *p, u32 n);
extern void *JKRHeap_sCurrentHeap;

#define VT_TEVBLOCK4    0x803E0AB0u
#define VT_PEBLOCK_FULL 0x803E0968u

#define RD32(p) (*(volatile u32 *)(p))
#define RD16(p) (*(volatile u16 *)(p))
#define RD8(p)  (*(volatile u8 *)(p))

/* --- état ------------------------------------------------------------------
 * goop_cfg et goop_roots : zone de caverne nulle au démarrage, hors profil.
 * Chaque Slot vit en tête du bloc alloué pour sa couche (tas du niveau) : il
 * disparaît avec le niveau. Un pointeur de goop_roots n'est suivi en écriture
 * qu'après live() : couche de pollution vivante dont le masque est le nôtre. */
#define MAXL 8
struct Slot {
    u8 *layer;          /* TPollutionLayer* */
    u8 *mask;           /* masque de gameplay */
    u8 *disp;           /* copie lissée */
    u8 *tex;            /* J3DTexture* du modèle */
    u8 *orig_arr;       /* tableau ResTIMG d'origine */
    u8 *new_arr;        /* copie rebranchée */
    u16 w, h;
    u16 cursor;
    u16 dx0, dx1, dy0, dy1;
    u8 dframes;
    u8 idx;
    u8 soft_on;
    u8 nonce;           /* compteur modulo 3, écrit dans le texel (0,0) */
};
struct Cfg {
    u32 magic;          /* 'GOOP' une fois initialisé au moins une fois */
    u8 no_smooth;
    u8 no_soft;
    u16 nlayers;
    u32 last_free;
    u32 last_need;
    u32 fails;
    u32 updates;
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

/* --- lissage ---------------------------------------------------------------- */
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
    /* bandes de tuiles touchées */
    u32 b0 = (y0 >> 2) * tw * 32, b1 = ((y1 >> 2) + 1) * tw * 32;
    DCStoreRange(d + b0, b1 - b0);
    goop_cfg.updates++;
}

/* --- bord fondu ---------------------------------------------------------------
 * Mots BP complets (id + 3 octets). Les étages TEV sont à +0x29 et +0x31 du
 * bloc, non alignés : le Gekko (750) fait les accès entiers non alignés en
 * matériel, Dolphin aussi. */
#define W32(p) (*(volatile u32 *)(p))
#define ST1_ORIG 0xC331FF80u
#define ST2_ORIG 0xC500FF80u
#define ST1_SOFT 0xC322FF80u   /* (APREV-0.5)x4, sans clamp */
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
            continue;                        /* signature inconnue : on n'y touche pas */
        W32(tev + 0x29) = s1 ^ ST1_ORIG ^ ST1_SOFT;
        W32(tev + 0x31) = s2 ^ ST2_ORIG ^ ST2_SOFT;
        W32(pe + 0x0C) = bl ^ BL_ORIG ^ BL_SOFT;
        pe[0x0A] = on ? 1 : 128;
    }
}

/* --- crochets ---------------------------------------------------------------- */
typedef s32 (*fn_free)(void *);
typedef void *(*fn_alloc)(void *, u32, s32);

/* remplace « bl initTexImage » dans TPollutionLayer::initJointModel (0x801A0EB8) */
void goop_init(u8 *layer, const char *name)
{
    initTexImage(layer, name);

    u32 idx = RD32(layer + 4);
    goop_cfg.magic = 0x474F4F50;
    int free_i = -1;
    for (u32 i = 0; i < MAXL; ++i) {
        struct Slot *o = goop_roots[i];
        /* couche 0 = nouveau niveau : tout est périmé ; sinon même couche ou même index */
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
    u32 hdr = 64 + ((n * 0x20 + 31) & ~31u);        /* Slot + copie des ResTIMG */
    u32 need = hdr + w * h;
    void *heap = JKRHeap_sCurrentHeap;
    u32 *vt = *(u32 **)heap;
    s32 fr = ((fn_free)vt[36 / 4])(heap);
    goop_cfg.last_free = (u32)fr;
    goop_cfg.last_need = need;
    if (fr < 0 || (u32)fr < need + 0x80000) {  /* garde 512 Ko au niveau */
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
    s->cursor = 0; s->dframes = 0; s->idx = (u8)idx; s->soft_on = 0;
    goop_roots[free_i] = s;
    goop_cfg.nlayers++;
    smooth_rows(s, 0, h - 1, 0, w - 1);
    DCStoreRange(blk, need);
}

/* remplace « bl TJointModel::perform » à la fin de TPollutionLayer::perform (0x801A12C8) */
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
    if (cur != s->orig_arr && cur != s->new_arr)     /* modèle différent : on n'y touche pas */
        return;
    int smooth = !goop_cfg.no_smooth;
    *(u32 *)(s->tex + 4) = (u32)(smooth ? s->new_arr : s->orig_arr);
    int soft = !goop_cfg.no_soft;
    if (soft != s->soft_on) { set_soft(layer, soft); s->soft_on = (u8)soft; }
    if (!smooth)
        return;
    if (s->dframes) {
        smooth_rows(s, s->dy0, s->dy1, s->dx0, s->dx1);
        if (--s->dframes == 0) { s->dx0 = s->dy0 = 0xFFFF; s->dx1 = s->dy1 = 0; }
    }
    u32 y0 = s->cursor, y1 = y0 + 3;
    if (y1 >= s->h) y1 = s->h - 1;
    smooth_rows(s, y0, y1, 0, s->w - 1);
    s->cursor = (u16)((y1 + 1 >= s->h) ? 0 : y1 + 1);
    s->nonce = (u8)(s->nonce >= 2 ? 0 : s->nonce + 1);
    s->disp[0] = (u8)((s->disp[0] & 0xFC) | s->nonce);
    DCStoreRange(s->disp, 32);
}

/* appelé par le trampoline à l'entrée de TPollutionTexStamp::pushTask */
void goop_mark(u32 idx, u32 size, u32 x, u32 z)
{
    for (u32 i = 0; i < MAXL; ++i) {
        struct Slot *s = live(goop_roots[i]);
        if (!s || s->idx != (idx & 0xFF))
            continue;
        s32 r = (s32)(size & 0xFFFF) + 2;
        s32 xa = (s32)(x & 0xFFFF) - r, xb = (s32)(x & 0xFFFF) + r;
        s32 ya = (s32)(z & 0xFFFF) - r, yb = (s32)(z & 0xFFFF) + r;
        if (xa < 0) xa = 0;
        if (ya < 0) ya = 0;
        if (xb >= s->w) xb = s->w - 1;
        if (yb >= s->h) yb = s->h - 1;
        if (xa > xb || ya > yb)
            return;
        if (s->dframes == 0) { s->dx0 = s->dy0 = 0xFFFF; s->dx1 = s->dy1 = 0; }
        if ((u32)xa < s->dx0) s->dx0 = (u16)xa;
        if ((u32)xb > s->dx1) s->dx1 = (u16)xb;
        if ((u32)ya < s->dy0) s->dy0 = (u16)ya;
        if ((u32)yb > s->dy1) s->dy1 = (u16)yb;
        s->dframes = 8;
        return;
    }
}

/* trampoline : sauve r3–r8, appelle goop_mark(r4, r5, r6, r7), rejoue la 1re
   instruction de pushTask (lwz r9, 8(r3)) et y retourne. */
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
