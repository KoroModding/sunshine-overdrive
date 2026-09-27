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
 *   - rafraîchissement de fond : 4 lignes par passage, pour tout autre écrivain ;
 *   - tâches « modèle » (pushModelStampTask : vomi et gouttes de Petey,
 *     Calmar, Mario Ombre, pollueurs…) : zone carrée autour du modèle tampon,
 *     recalculée pendant 8 passages, renouvelée à chaque tâche (image par
 *     image pendant l'étalement d'une flaque). Les tâches « objet articulé »
 *     (pushJointObjStampTask) restent au rafraîchissement de fond.
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
 * Interrupteurs (octets en RAM, 0 = actif) : cfg.no_smooth, cfg.no_soft,
 * cfg.no_model.
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
#define MAXL 16          /* Bianco (goop rose) : 9 couches */
struct Slot {
    u8 *layer;          /* TPollutionLayer* */
    u8 *mask;           /* masque de gameplay */
    u8 *disp;           /* copie lissée */
    u8 *tex;            /* J3DTexture* du modèle */
    u8 *orig_arr;       /* tableau ResTIMG d'origine */
    u8 *new_arr;        /* copie rebranchée */
    u16 w, h;
    u16 cursor;
    struct Rect { u16 x0, x1, y0, y1; u8 frames, pad; } z[2];
                        /* zones recalculées : [0] tampons, [1] tâches modèle */
    u8 idx;
    u8 soft_on;
    u8 nonce;           /* compteur modulo 3, écrit dans le texel (0,0) */
    u8 dl_tick;         /* contrôle des display lists figées tous les 16 passages */
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
    u8 no_model;        /* +24 : zones des tâches modèle */
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

/* --- display lists figées ---------------------------------------------------
 * Certaines couches (grandes couches de sol de Bianco, goop rose : relevé
 * 2026-09-27) ont un J3DMatPacket verrouillé (+0x10 bit 0) : leur display list
 * est construite une fois et l'adresse de texture (BP 0x94, TX_IMAGE3 map0) y
 * est figée sur le masque. Rebrancher le J3DTexture n'y change rien : on
 * réécrit ce mot, dans les deux tampons du J3DDisplayListObj, vers la cible
 * (copie lissée ou masque). J3DModel +0x80 paquets (pas 0x48), paquet +0x30
 * J3DDisplayListObj : +0 / +4 tampons.
 * La DL commence par les commandes BP (5 octets) de la texture 0 ; relevé sur
 * les 2 couches concernées : BP 0x94 à +5 dans les deux tampons. On ne
 * réécrit que ce mot, et seulement s'il vaut déjà l'adresse du masque ou de
 * la copie : toute autre structure est laissée intacte. */
__attribute__((noinline)) static void patch_dl(struct Slot *s, u32 to)
{
    u8 *pk = (u8 *)RD32(RD32(s->layer + 0x28) + 0x80);   /* paquet du matériau 0 */
    if (!(RD32(pk + 0x10) & 1))
        return;
    u32 vm = 0x94000000u | (((u32)s->mask & 0x1FFFFFFF) >> 5);
    u32 vd = 0x94000000u | (((u32)s->disp & 0x1FFFFFFF) >> 5);
    u8 *dl = (u8 *)RD32(pk + 0x30);
    for (u32 b = 0; b < 8; b += 4) {
        u8 *q = (u8 *)RD32(dl + b) + 5;
        u32 v = W32(q + 1);                          /* non aligné : pris en charge */
        if (q[0] == 0x61 && (v == vm || v == vd)) {
            W32(q + 1) = 0x94000000u | ((to & 0x1FFFFFFF) >> 5);
            __asm__ volatile("dcbst 0, %0" :: "r"(q) : "memory");   /* le GPU lit la RAM */
        }
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
    s->cursor = 0; s->z[0].frames = 0; s->z[1].frames = 0; s->idx = (u8)idx; s->soft_on = 0; s->dl_tick = 0;
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

/* Zone à recalculer : carré (cx, cy) ± r, borné à la couche, uni à la zone en
 * cours si elle est encore active ; recalculée pendant 8 passages. */
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

/* appelé par le trampoline à l'entrée de TPollutionTexStamp::pushTask */
void goop_mark(u32 idx, u32 size, u32 x, u32 z)
{
    struct Slot *s = slot_of(idx);
    if (s)
        mark_rect(s, &s->z[0], x & 0xFFFF, z & 0xFFFF, (s32)(size & 0xFFFF) + 2);
}

/* appelé par le trampoline de pushModelStampTask.
 * Zone carrée centrée sur la translation du
 * modèle tampon (J3DModel +0x2C x, +0x4C z, échelle +0x14), rayon 400 u ×
 * échelle — flaque de Petey mesurée à ~600 u pour l'échelle 2 (2026-09-27).
 * Zone [1], distincte de celle des tampons : pas d'union entre deux zones
 * éloignées. Arithmétique entière (fctiwz seulement) : aucune constante
 * flottante en mémoire. */
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
    s32 r = (s32)(sc + sc + sc + sc) * 100 * s->w / dx + 2;   /* 400 u × échelle */
    mark_rect(s, &s->z[1], ((s32)m[0x2C / 4] - x0) * s->w / dx,
              ((s32)m[0x4C / 4] - z0) * s->h / dz, r);
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

/* trampoline de pushModelStampTask(r3 file, r4 indice de couche, r5
   J3DModel*) : sauve r3–r5, appelle goop_mark_model(r4, r5), rejoue la 1re
   instruction (lhz r0, 0x28(r3)) et y retourne. */
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
