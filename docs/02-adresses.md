# Registre d'adresses

> Toute adresse utilisée par le projet est inscrite ici avec **son niveau de
> preuve** et **la commande qui la reproduit**. Une adresse absente de ce
> registre n'a pas été vérifiée et ne doit pas être écrite dans du code.

Cible : `GMSE01` (NTSC-U, révision 0).
DOL de référence : SHA-1 `a6782903ef79d4196c8489ecb1b57decb5b3728f`.

## Niveaux de preuve

| Niveau | Signification |
|---|---|
| **M** | lu dans le code machine — l'instruction elle-même le démontre |
| **S** | issu d'une table de symboles, recoupé avec le code machine |
| **T** | issu d'une table de symboles seule, non recoupé |
| **H** | hypothèse — reprise d'une source tierce, jamais vérifiée ici |

Ne jamais écrire de correctif sur la foi d'un **H**.

---

## Bases de registres

Fixées une fois pour toutes par `__init_registers` @ `0x80005364`, jamais
modifiées ensuite (ABI PowerPC EABI).

| Registre | Valeur | Rôle | Preuve |
|---|---|---|---|
| `r2` | `0x80416BA0` | base `.sdata2`, petites données en lecture seule | **M** |
| `r13` | `0x804141C0` | base `.sdata`, petites données en lecture/écriture | **M** |

```sh
python tools/dol.py dis work/dol/GMSE01.dol 0x80005364 6
```

Tous les littéraux flottants du jeu sont adressés en `déplacement(r2)`. Un
déplacement seul ne veut rien dire sans cette base — c'est pourquoi
`tools/disasm.py` la résout automatiquement.

---

## Fonctions

| Symbole | Adresse | Preuve | Note |
|---|---|---|---|
| `gpApplication` | `0x803E9700` | **M** | **l'objet lui-même**, pas un pointeur vers lui |
| `gpMarioPos` | `0x8040E10C` | **M** | pointeur vers `TMario + 0x10` |
| `gpMarioSpeedX/Y/Z` | `0x8040E11C`…`0x8040E124` | **M** | pointeurs vers `TMario + 0xA4/0xA8/0xAC` |
| `__vt__13TMarioGamePad` | `0x803DF44C` | **T** | sert à repérer les manettes par balayage, hors niveau |
| `gpMarDirector` | `0x8040E178` | **M** | pointeur ; valait `0x80902A40` en session |
| `gpMarioOriginal` | `0x8040E0E8` | **M** | pointeur ; valait `0x81322DA0` en session |
| `__vt__10TModelGate` | `0x803D3F9C` | **T** | sert à repérer les instances par balayage |
| `TMarioParticleManager::perform` | `0x80288780` | **S** | contient la boucle d'appels à `JPAEmitterManager::calc()` |
| `JPAEmitterManager::calc` | `0x80324F0C` | **S** | avance le système de particules d'un pas |
| `gpMarioParticleManager` | `0x8040E150` | **M** | lu par `lwz r3,-0x6070(r13)` |
| `TMapObjWaterSpray::calc` | `0x801C12D4` | **S** | jets d'eau — émet par `TMarioParticleManager::emit` |
| `TMario::warpInEffect` | `0x802637A0` | **S** | entrée de graffiti — entièrement JPA, callback `TWarpInCallBack` |
| `__start` | `0x8000522C` | **M** | point d'entrée, lu dans l'en-tête DOL |
| `__init_registers` | `0x80005364` | **M** | |
| `direct__12TMarDirectorFv` | `0x80299838` | **M** | fin `0x80299D48` |
| `changeState__12TMarDirectorFv` | `0x80298E80` | **S** | appelée en `0x80299D0C` |
| `setupObjects__12TMarDirectorFv` | `0x802B76F4` | **S** | appelée en `0x802998B8` |
| `SMSGetAnmFrameRate__Fv` | `0x802A7BD8` | **M** | |
| `SMSGetVSyncTimesPerSec__Fv` | `0x802A7C48` | **M** | |
| `waitForRetrace__Q26JDrama6TVideoFUs` | `0x802FC9A4` | **M** | fin `0x802FCB5C` |
| `perform__10TModelGateFUlPQ26JDrama9TGraphics` | `0x801EB014` | **M** | |
| `SMS_SetMarioAccessParams__Fv` | `0x80273A0C` | **M** | publie les offsets de `TMario` — voir ci-dessous |
| `setGamePad__6TMarioFP13TMarioGamePad` | `0x802765EC` | **M** | `stw r4, 0x4fc(r3)`, deux instructions en tout |
| `checkController__6TMarioFPQ26JDrama9TGraphics` | `0x80251494` | **M** | lit le stick en `0xA8`/`0xAC` de la manette |
| `updateMeaning__13TMarioGamePadFv` | `0x802A80E0` | **M** | lit `0x18`, `0x2C`, écrit `0xDC`/`0xDE` |
| `update__10JUTGamePadFv` | `0x802C8F70` | **M** | recopie le bloc d'état de la manette |
| `loadAfter__10TModelGateFv` | `0x801EC048` | **M** | |
| `screenBlur__10TModelGateFPQ26JDrama9TGraphics` | `0x801EBD84` | **T** | |
| `VIWaitForRetrace` | `0x8034F684` | **M** | cible du `bl` en `0x802FCB24` |
| `VIGetRetraceCount` | `0x803504EC` | **M** | |
| `VIConfigure` | `0x8034FB4C` | **M** | |
| `VIFlush` | `0x803502E8` | **M** | |
| `VISetBlack` | `0x80350470` | **M** | |
| `VISetNextFrameBuffer` | `0x80350404` | **M** | |
| `VIGetTvFormat` | `0x8035069C` | **M** | appelée par `SMSGetVSyncTimesPerSec` |
| `OSGetTick` | `0x803494F0` | **M** | |
| `IsEqualRenderModeVIParams__6JDrama…` | `0x802FB808` | **M** | |
| `gameLoop__12TApplicationFv` | `0x802A5F50` | **T** | repris du plan de départ, non recoupé |
| `proc__12TApplicationFv` | `0x802A6398` | **T** | idem |
| `initialize__12TApplicationFv` | `0x802A73C4` | **T** | idem |
| `startRendering__Q26JDrama8TDisplayFv` | `0x802F7FD8` | **T** | idem |
| `endRendering__Q26JDrama8TDisplayFv` | `0x802F80D0` | **T** | idem |
| `SMSSetupGameRenderingInfo__FPQ26JDrama8TDisplayb` | `0x802A5010` | **T** | idem |

---

## Littéraux — pool `.sdata2`

| Adresse | Valeur | Rôle | Preuve |
|---|---|---|---|
| `0x804167B8` | `0.5f` | multiplicande de `SMSGetVSyncTimesPerSec` | **M** |
| `0x804167D8` | `60.0f` | cadence NTSC / MPAL / EURGB60 | **M** |
| `0x804167DC` | `50.0f` | cadence PAL | **M** |
| `0x80414900` | `1000.0f` | `TModelGate` — rayon lointain | **M** |
| `0x80414904` | `0.01f` | `TModelGate` — taux de fondu lent | **M** |
| `0x80414908` | `1.0f` | `TModelGate` — borne du fondu | **M** |
| `0x8041490C` | `0.0f` | `TModelGate` — valeur initiale | **M** |
| `0x80414964` | `0.02f` | `TModelGate` — taux de fondu rapide | **M** |
| `0x8041496C` | `500.0f` | `TModelGate` — rayon proche | **M** |

```sh
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x804167B8
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x80414904
```

### Consommateurs de `0x804167B8`

Trois, et non deux comme le laisse entendre le plan de départ :

| Site | Fonction |
|---|---|
| `0x802A5EFC` | `TApplication::drawDVDErr()+0x3B8` |
| `0x802A7C24` | `SMSGetAnmFrameRate()+0x4C` |
| `0x802A7C94` | `SMSGetVSyncTimesPerSec()+0x4C` |

Le patch touche donc aussi l'écran d'erreur disque. Effet de bord d'un pool de
constantes partagé, sans conséquence attendue en émulation.

---

## Points de correctif

| Adresse | Contenu d'origine | Rôle du patch | Preuve |
|---|---|---|---|
| `0x804167B8` | `3F000000` (`0.5f`) | `→ 3F800000` : horloge logique à 60 Hz **et** cadence d'animation recalée | **M** |
| `0x802FCB24` | `48052B61` (`bl VIWaitForRetrace`) | `→ 60000000` (`nop`) : un champ par appel. **Sans effet à chaud** — voir ci-dessous | **M** |
| `TDisplay + 0x4C` | `2` | `→ 1` : un champ par image. **Voie à privilégier** — c'est une donnée | **M** |
| `0x80414904` | `3C23D70A` (`0.01f`) | `→ 3CA3D70A` (`0.02f`) : fondu `TModelGate`. **Sens douteux**, voir [`01-mecanismes.md` § 4.3](01-mecanismes.md) | **M** pour l'identité, **H** pour le bien-fondé |
| `0x802887B0` | `80010094` (`lwz r23,0x94(r1)`) | `→ 3AE00001` (`li r23,1`) : dégèle le système de particules. **Compensation, pas correctif exact** — voir [`01-mecanismes.md` § 5](01-mecanismes.md) | **M** |
| `0x800066EC` | hook ASM | zone `TBoidLeader` — vitesse des nuées | **H** |
| `0x80C28028` | hook ASM | non analysé | **H** |

Le `600` de `direct()` est un **immédiat** (`li r3, 0x258` @ `0x8029985C`),
pas un littéral en mémoire : il n'est pas modifiable par une écriture simple.
Seul le diviseur l'est, indirectement via `0x804167B8`.

### Données contre code — règle impérative

Une écriture externe dans une **instruction** n'a aucun effet tant que Dolphin
exécute le bloc JIT déjà compilé. Vérifié le 2026-09-15 : `nop` écrit en
`0x802FCB24`, relecture confirmant `0x60000000`, et **aucun changement de
comportement**.

Une écriture dans une **donnée** prend effet immédiatement.

| Point | Nature | Utilisable à chaud |
|---|---|---|
| `0x804167B8` | littéral f32 | **oui** |
| `0x80414904` | littéral f32 | **oui** |
| `TDisplay + 0x4C` | champ u16 | **oui** |
| `0x802FCB24` | instruction | **non** |

`mRetraceCount = 1` et le `nop` produisent le même effet ; **ils ne se
cumulent pas impunément** — neutralisée, `waitForRetrace` consomme `count - 1`
champs par appel, donc zéro avec `count = 1`, et le jeu s'emballe. Tout outil
qui pose le compte doit lire `0x802FCB24` d'abord.

**La règle « code non » ne vaut que pour les écritures externes.** Le
PatchEngine de Dolphin — section `[OnFrame]` d'un profil par jeu — applique ses
écritures à l'amorçage, avant que le JIT ne compile le bloc : un correctif
d'instruction y prend effet. C'est la voie retenue pour la livraison.
Voir [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md) et
[`adr/0005-gecko-ou-donnees.md`](adr/0005-gecko-ou-donnees.md).

### Audio JAI — durées des fondus (session 7, `tools/fixes/fades.py`)

Reproduire : `python tools/fixes/fades.py` (vérifie chaque mot d'origine dans
le DOL, puis affiche le listing), `python tools/disasm.py work/dol/GMSE01.dol
work/maps/us.map <symbole>`.

| Adresse | Symbole | Contenu d'origine | Rôle | Preuve |
|---|---|---|---|---|
| `0x8030A3B0` | `JAISound::initMoveParameter` | `9421FFE0` (`stwu r1,-0x20(r1)`) | durée en `r5` ; séquences et flux | **S** |
| `0x8030B700` | `JAISound::setSeInterVolume` | `7C0802A6` (`mflr r0`) | durée en `r5` (`addi r30,r5,0`), `setSeInterMovePara` inliné | **S** |
| `0x8030B8C8` | `JAISound::setSeInterPan` | `7C0802A6` | idem | **S** |
| `0x8030BA90` | `JAISound::setSeInterFxmix` | `7C0802A6` | idem | **S** |
| `0x8030BC58` | `JAISound::setSeInterDolby` | `7C0802A6` | idem | **S** |
| `0x8030BE20` | `JAISound::setSeInterPitch` | `7C0802A6` | idem (`addi r30,r5,0`) | **S** |
| `0x8030C690` | `JAISound::setSePositionDopplar` | — | transition Doppler inlinée, durée `dopplarMoveTime` ; **non corrigée** | **S** |
| `0x8040CD64` | `JAIGlobalParameter::dopplarMoveTime` | `0000000F` (15) | lu par `setSePositionDopplar` **et** `checkPlayingSeqTrack` (via `setSeqInterPitch`) : ne pas le multiplier en donnée | **S** |
| `0x8040CD8C` | `JAIGlobalParameter::dopplarParameter` | `45480000` (3200.0) | diviseur du Doppler, une seule lecture (`0x8030ACE4`) | **S** |
| `0x8001604C` | `MSSetSoundTL<MSSetSound>::frameLoopDyna` | — | horloge `+0x54` des jeux de sons FLUDD, +1 par passage JAI ; **non corrigée** | **S** |
| `0x8001D67C` | `MSModBgm::loop` | — | compteur `+0x4` (seuils 5 et 180) ; **non corrigé** | **S** |

`JAIMoveParaSet` : cible `+0`, courant `+4`, pas `+8`, compteur `+0xC` (u32).
`JAISound + 0x38` → `JAISeqParameter` : 309 `JAIMoveParaSet` de `+0x04` à
`+0x1353` (Graffito-Decomp, `JAIParameters.hpp`, **T** pour la disposition).

---

## `SMS_SetMarioAccessParams()` — la fonction qui prouve les offsets de `TMario`

Vingt-cinq instructions, aucun appel : elle prend `gpMarioOriginal` et publie une
douzaine de pointeurs vers l'intérieur de l'objet. Chacun de ces pointeurs est
une **preuve machine** de l'offset correspondant, sans avoir à fouiller le code
de jeu.

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map SMS_SetMarioAccessParams__Fv
```

```
80273A0C  lwz   r8, -0x60d8(r13)   ; r8 = gpMarioOriginal
80273A18  addi  r9, r8, 0xa4       ; r9 = &mSpeed.x
80273A1C  addi  r4, r8, 0x10       ; r4 = &mPosition.x
80273A30  addi  r7, r9, 4          ; &mSpeed.y
80273A34  addi  r6, r9, 8          ; &mSpeed.z
80273A50  stw   r9, -0x60a4(r13)   ; -> gpMarioSpeedX
```

| Global | Adresse | Vaut | Offset prouvé |
|---|---|---|---|
| `gpMarioAddress` | `0x8040E108` | `mario + 0` | — |
| `gpMarioPos` | `0x8040E10C` | `mario + 0x10` | position X/Y/Z |
| `gpMarioAngleX/Y/Z` | `0x8040E110`…`0x8040E118` | `mario + 0x94`, `+0x96`, `+0x98` | angles (s16) |
| `gpMarioSpeedX/Y/Z` | `0x8040E11C`…`0x8040E124` | `mario + 0xA4`, `+0xA8`, `+0xAC` | **vitesse X/Y/Z** |
| `gpMarioLightID` | `0x8040E128` | `mario + 0xF8` | |
| `gpMarioFlag` | `0x8040E12C` | `mario + 0x118` | |
| `gpMarioThrowPower` | `0x8040E130` | `mario + 0x820` | |
| `gpMarioGroundPlane` | `0x8040E134` | `mario + 0xE0` | |

C'est ce qui fait passer `TMario + 0xA4` d'une déduction de session à une
adresse de niveau **M**. `tools/test_physics.py` et `tools/test_ballistic.py`
écrivent la vitesse à cet offset.

---

## Offsets de structures

| Structure | Offset | Champ | Preuve |
|---|---|---|---|
| `TMarDirector` | `0x4C` | drapeaux (`0x2000` premier sous-pas, `0x4000` dernier) | **M** |
| `TMarDirector` | `0x54` | accumulateur de sous-pas | **M** |
| `TMarDirector` | `0x34` | liste de perform — animations, dernier sous-pas | **M** |
| `TMarDirector` | `0x38`, `0x3C`, `0x40` | listes de perform — dessin | **M** |
| `TMarDirector` | `0x260` | booléen « objets initialisés » | **M** |
| `JDrama::TVideo` | `0x80` | `OSGetTick()` du dernier retrace | **M** |
| `JDrama::TVideo` | `0x84` | compteur de retrace cible | **M** |
| `JDrama::TDisplay` | `0x4C` | `mRetraceCount` (u16) | **M** — lu à 2 en mémoire vive, et sa loi vérifiée expérimentalement |
| `TApplication` | `0x1C` | `mDisplay` | **M** — `lwz r3, 0x1c(r31)` dans `gameLoop` |
| `TMario` | `0x10`/`0x14`/`0x18` | position X / Y / Z (f32) | **M** — relevé en mémoire vive |
| `TMario` | `0x24`…`0x2C` | échelle (1,1,1) | **M** |
| `TMario` | `0x94`/`0x96`/`0x98` | angles X / Y / Z (s16) | **M** — `SMS_SetMarioAccessParams` |
| `TMario` | `0xA4`/`0xA8`/`0xAC` | vitesse X / Y / Z (f32) | **M** — `SMS_SetMarioAccessParams` |
| `TMario` | `0x4FC` | `mGamePad` | **M** — `stw r4, 0x4fc(r3)` dans `setGamePad` |
| `TMarioGamePad` | `0x18` | boutons **maintenus** (u32) | **M** — bloc recopié par `JUTGamePad::update`, lu par `updateMeaning` |
| `TMarioGamePad` | `0x1C` | boutons **nouvellement pressés** (u32) | **M** pour le champ, **expérimental** pour le sens — voir ci-dessous |
| `TMarioGamePad` | `0x2C` | gâchette analogique (f32) | **M** — `lfs f1, 0x2c(r30)` dans `updateMeaning` |
| `TMarioGamePad` | `0xA8`/`0xAC` | stick principal X / Y (f32, `[-1,1]`) | **M** — `lfs f0, 0xa8(r4)` dans `checkController` |
| `TMarioGamePad` | `0xDC`/`0xDE` | « meaning » courant / précédent (u16) | **M** — `sth` dans `updateMeaning` |
| `TModelGate` | `0xD0` | progression du fondu, `[0,1]` | **M** |
| `TModelGate` | `0xC8` / `0xCA` | état / état précédent | **M** |
| `TModelGate` | `0xE4`…`0xF4` | bloc de paramètres du fondu | **M** |


---

## Maintien contre front — `TMarioGamePad + 0x18` et `+ 0x1C`

`JUTGamePad::update()` @ `0x802C8F70` recopie un bloc de 0x30 octets depuis le
tableau statique `0x80404484 + port × 0x30` vers `pad + 0x18`. Les deux
premiers mots de ce bloc atterrissent donc en `+0x18` et `+0x1C` — la paire
« boutons maintenus / boutons nouvellement pressés » de `JUTGamePad::CButton`.

Le **sens** des deux champs a été tranché expérimentalement le 2026-09-15, par
injection dans un jeu en cours :

| Écriture | Effet sur Mario |
|---|---|
| `+0x18` seul = `A` | **rien** (dY = 0,00) |
| `+0x1C` seul = `A` | **saut** (dY = 73,79) |
| `+0xA8` = 1,0 | course (dX = 717,04) |
| `+0xAC` = 1,0 | course (dZ = 933,20) |

Le saut se déclenche donc sur le **front**, pas sur le maintien. Conséquence
pratique, inscrite dans `tools/pad.py` : rejouer le front à chaque image
revient à réappuyer sur A dès l'atterrissage, ce qui enchaîne les sauts et rend
toute mesure de hauteur inexploitable.

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map update__10JUTGamePadFv
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map updateMeaning__13TMarioGamePadFv
```
