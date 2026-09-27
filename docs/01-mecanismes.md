# Les mécanismes de cadencement, vérifiés sur le code machine

> Statut : **vérifié statiquement puis confirmé à l'exécution** sur `GMSE01`
> (NTSC-U, révision 0, SHA-1 du DOL `a6782903ef79d4196c8489ecb1b57decb5b3728f`).
> Les mesures sont en [`04-tests.md`](04-tests.md) ; aucune ne contredit
> l'analyse ci-dessous.
> Ce document remplace, pour les points qu'il couvre, les hypothèses du
> plan de départ. Chaque affirmation est accompagnée de l'adresse permettant de la
> reproduire. Voir [`00-journal.md`](00-journal.md) pour la chronologie et
> [`02-adresses.md`](02-adresses.md) pour le registre d'adresses.

Reproduire n'importe quel listing de ce document :

```sh
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map <adresse-ou-symbole>
```

---

## 1. L'accumulateur de sous-pas — `TMarDirector::direct()`

`direct__12TMarDirectorFv` @ `0x80299838`, longueur `0x510`.

### 1.1 Calcul du quantum

```
80299850  bl     SMSGetVSyncTimesPerSec()   ; f1 = 30.0 en NTSC
80299854  fctiwz f0, f1                     ; conversion en entier
8029985C  li     r3, 0x258                  ; 600
80299864  stfd   f0, 0x160(r1)              ; transfert FPR -> GPR par la pile
80299868  lwz    r0, 0x164(r1)              ; mot bas du résultat de fctiwz
8029986C  divw   r25, r3, r0                ; r25 = 600 / 30 = 20
```

Confirme mot pour mot le pseudo-code du plan de départ :

```c
int vsyncRate = 600 / (int)SMSGetVSyncTimesPerSec();
```

Le `600` est un immédiat en dur (`li r3, 0x258`), pas un littéral en mémoire :
**il n'est pas patchable par un code Gecko à écriture simple.** Seul le
diviseur — la valeur de retour de `SMSGetVSyncTimesPerSec()` — est modifiable,
et il l'est indirectement via le littéral `0x804167B8` (§ 2).

### 1.2 Structure réelle de la boucle

C'est le point où le plan de départ mettait en garde : « le `break` du dernier
sous-pas rend la branche de dessin inatteignable — le code décompilé est
auto-contradictoire à cet endroit ». **Le code machine n'est pas
contradictoire.** La décompilation rend mal une boucle dont le point d'entrée
se situe au milieu.

```c
s32 TMarDirector::direct() {            // appelée une fois par image rendue
    /* initialisation unique, gardée par le booléen this+0x260 */

    unk54 += vsyncRate;                 // 0x80299938 — budget de l'image

loop:                                   // 0x8029994C
    if (unk4C & 0x4000) {               // reliquat laissé par l'appel précédent
        perform(+0x40); perform(+0x38); perform(+0x3C);   // 0x80299C28 — DESSIN
        GXInvalidateTexAll();                             // 0x80299D04
        goto after;
    }

    if (++i == 1)      unk4C |= 0x2000; // 0x80299964 — premier sous-pas
    unk54 -= 5;                         // 0x80299974 — quantum
    if (unk54 < 5)     unk4C |= 0x4000; // 0x8029998C — dernier sous-pas

    /* ... listes de perform de SIMULATION : movement() ... */

    if (unk4C & 0x4000) {               // 0x80299BF4
        perform(+0x34);                 // 0x80299C00 — animations
        return status;                  // 0x80299C24 — rend la main
    }

after:                                  // 0x80299D08
    status = changeState();             // 0x80299D0C
    unk4C &= ~(0x2000 | 0x4000);        // 0x80299D18 — rlwinm r0,r0,0,0x13,0x10
    goto loop;                          // 0x80299D20
}
```

Le point clé : **le drapeau `0x4000` survit au retour de fonction.** Le dernier
sous-pas le positionne puis rend la main à `TApplication::gameLoop()` pour la
présentation ; à l'appel suivant, le test en tête de boucle le voit encore armé
et exécute le bloc de dessin. Le dessin est donc *différé au début de l'appel
suivant*, ce qui explique à la fois la structure et l'échec du décompilateur.

### 1.3 Conséquence : la règle de classement

C'est la règle qui dit ce qui casse quand on débride le framerate.

| Emplacement | Fréquence | Effet du passage 30 → 60 FPS |
|---|---|---|
| listes de perform de simulation (corps du sous-pas) | **par sous-pas**, 120 Hz constants | aucun — correct automatiquement |
| liste `+0x34` (animations, dernier sous-pas) | **par image rendue** | doublée |
| listes `+0x40`, `+0x38`, `+0x3C` (dessin) | **par image rendue** | doublée |

Un objet dont le `perform` est enregistré dans une liste de simulation n'a
jamais besoin d'être remis à l'échelle. C'est pourquoi BSE ne touche jamais à
`TJumpParams` ni `TRunParams`.

Les listes se répartissent ainsi, par les offsets chargés dans chaque région :

| Région de `direct()` | Listes (offsets depuis `TMarDirector`) |
|---|---|
| corps du sous-pas — **simulation** | `+0x18`, `+0x28`, `+0x2C`, `+0x30`, `+0x34`, `+0x44`, `+0x48`, `+0x58`, `+0x5C` |
| bloc de dessin — **par image rendue** | `+0x1C`, `+0x20`, `+0x24`, `+0x38`, `+0x3C`, `+0x40` |
| dernier sous-pas — animations | `+0x34` |

`+0x34` apparaît dans les deux premiers : la liste est parcourue à chaque
sous-pas pour le mouvement, puis une fois de plus au dernier sous-pas pour les
animations.

**Non vérifié :** dans quelle liste un objet donné s'enregistre. Les listes sont
peuplées à l'exécution et parcourues par répartition virtuelle
(`lwz r12, 0(r3) ; lwz r12, 0x20(r12) ; blrl`) : seule une mesure en situation
le dira. Voir 0.C dans [`04-tests.md`](04-tests.md).

### 1.4 Confirmation à l'exécution

Mesuré par sondage de l'accumulateur (`tools/measure_substeps.py`) :

| Palier | `vsyncRate` | images/s | sous-pas/s | sous-pas/image |
|---|---|---|---|---|
| 30 FPS | **20** | **30,00** | **120,00** | **4,000** |
| 60 FPS | **10** | **60,00** | 119,50 | **1,992** |
| 120 FPS (sans overclock VI) | **5** | 60,00 | 60,00 | **1,000** |

Et par un chemin entièrement indépendant — comptage des intégrations de
position pendant une chute libre de 3000 unités
(`tools/test_freefall.py`) : **198 intégrations à 30 FPS, 198 à 60 FPS**, pour
une durée réelle de 1,655 s contre 1,635 s (écart 1,2 %, du bruit
d'ordonnancement). La physique ne dépend pas de la cadence d'affichage.

---

## 2. L'horloge logique — `SMSGetVSyncTimesPerSec()`

`SMSGetVSyncTimesPerSec__Fv` @ `0x802A7C48`.

```
802A7C58  lfs    f31, -0x3c8(r2)   ; 0x804167D8 = 60.0f   (valeur par défaut)
802A7C5C  bl     VIGetTvFormat
802A7C60  cmpwi  r3, 2             ; VI_MPAL
...
802A7C88  lfs    f31, -0x3c8(r2)   ; 0x804167D8 = 60.0f   NTSC / MPAL / EURGB60
802A7C90  lfs    f31, -0x3c4(r2)   ; 0x804167DC = 50.0f   PAL
802A7C94  lfs    f0,  -0x3e8(r2)   ; 0x804167B8 = 0.5f
802A7C9C  fmuls  f1, f31, f0       ; 60.0 * 0.5 = 30.0
```

`r2 = 0x80416BA0`, lu dans `__init_registers` @ `0x80005364`
(`lis r2,-0x7fbf ; ori r2,r2,0x6ba0`). L'outillage décode cette paire au lieu de
coder la base en dur, ce qui le rend valable sur tous les DOL du jeu.

**L'identité de `0x804167B8` est désormais vérifiée, pas déduite.** C'est le
`0.5f` multiplié dans le résultat. Le plan de départ la classait en « non vérifié,
attribution par les splits de la décompilation » ; l'instruction la donne
directement.

Le compilateur a bien émis le réciproque : la source écrit `/ 2.0f`, le code
machine multiplie par `0.5f`.

### 2.1 `SMSGetAnmFrameRate()`

`SMSGetAnmFrameRate__Fv` @ `0x802A7BD8`. Recalcule la cadence en ligne plutôt
que d'appeler `SMSGetVSyncTimesPerSec()` :

```
802A7C24  lfs    f0, -0x3e8(r2)    ; 0.5f          <- même littéral
802A7C28  lfs    f1, -0x3c8(r2)    ; 60.0f
802A7C2C  fmuls  f0, f31, f0       ; vsync = 60.0 * 0.5 = 30.0
802A7C30  fdivs  f1, f1, f0        ; 60.0 / 30.0 = 2.0
```

Confirme `SMSGetAnmFrameRate() == 60.0f / SMSGetVSyncTimesPerSec()`. Les deux
fonctions partagent le littéral `0x804167B8`, ce qui est précisément la raison
pour laquelle le code Gecko recale l'horloge logique et la cadence d'animation
d'une seule écriture.

### 2.2 Un troisième consommateur, non documenté ailleurs

```sh
python tools/xref.py work/dol/GMSE01.dol work/maps/us.map 0x804167B8
```

donne **trois** références, pas deux :

| Adresse | Fonction |
|---|---|
| `0x802A5EFC` | `TApplication::drawDVDErr()+0x3B8` |
| `0x802A7C24` | `SMSGetAnmFrameRate()+0x4C` |
| `0x802A7C94` | `SMSGetVSyncTimesPerSec()+0x4C` |

Patcher `0x804167B8` modifie donc aussi l'écran d'erreur de lecture disque.
Sans conséquence attendue en émulation, mais à connaître : c'est un effet de
bord d'un littéral partagé par le pool de constantes, pas d'une intention.

---

## 3. La présentation — `JDrama::TVideo::waitForRetrace(u16)`

`waitForRetrace__Q26JDrama6TVideoFUs` @ `0x802FC9A4`, fin `0x802FCB5C`.

Reconstruction complète :

```c
void JDrama::TVideo::waitForRetrace(u16 count) {
    while ((s32)(mTargetRetrace - VIGetRetraceCount()) > 1)   // 0x802FC9C8..CDC
        VIWaitForRetrace();

    if (!IsEqualRenderModeVIParams(this, &this->mNextMode)) { // 0x802FC9E8
        VIConfigure(&mNextMode);                              // 0x802FC9F8
        /* ... VISetBlack, VIFlush, et jusqu'à 60 VIWaitForRetrace
           si l'entrelacement change (0x802FCA5C..A6C) ... */
    }
    /* ... recopie mNextMode -> mMode, champs 0x3C..0x7C -> 0x00..0x38 ... */

    VIWaitForRetrace();                                       // 0x802FCB24  <-- patché
    mLastTick      = OSGetTick();                             // 0x802FCB2C  -> +0x80
    mTargetRetrace = VIGetRetraceCount() + count;             // 0x802FCB3C  -> +0x84
}
```

Toutes les fonctions appelées ont été confirmées dans la map :
`VIWaitForRetrace` `0x8034F684`, `VIGetRetraceCount` `0x803504EC`,
`VIConfigure` `0x8034FB4C`, `VIFlush` `0x803502E8`, `VISetBlack` `0x80350470`,
`OSGetTick` `0x803494F0`, `IsEqualRenderModeVIParams` `0x802FB808`.

### 3.1 Pourquoi neutraliser `0x802FCB24` équivaut à `mRetraceCount = 1`

Le plan de départ l'affirmait sans démonstration. Voici le régime permanent.

Soit `c = VIGetRetraceCount()` et `t = mTargetRetrace` à l'entrée. La boucle
d'attente en tête sort dès que `t - c <= 1`, donc à `c = t - 1` si elle a
tourné.

**Non patché**, avec `count = N` : la boucle amène `c` à `t-1`, le
`VIWaitForRetrace` final l'amène à `t`, puis `t := t + N`.
→ **N champs consommés par appel.**

**Patché** (le `bl` final remplacé par `nop`), avec `count = N` : la boucle
amène `c` à `t-1`, il n'y a plus d'attente finale, puis `t := (t-1) + N`.
L'écart `t - c` vaut alors `N`, et la boucle du tour suivant effectue `N-1`
attentes.
→ **N−1 champs consommés par appel**, en régime permanent.

Avec la valeur NTSC `count = 2`, le patch donne donc exactement 1 champ par
appel, soit le comportement de `mRetraceCount = 1`. **L'équivalence est
démontrée**, et c'est un point fixe stable, pas une coïncidence de départ.

Deux corollaires utiles :

- Patché **et** `count = 1` → 0 champ par appel : plus aucune attente de
  balayage. Non testable à chaud, le `nop` étant bloqué par le cache JIT.
- Non patché, `count = 0` et `count = 1` sont indiscernables (1 champ par
  appel dans les deux cas). Le `mRetraceCount = 0` de BSE au palier 120 FPS ne
  produit donc pas à lui seul 120 images présentées : il faut que le VI tourne
  à 120 Hz, ce que fournit l'overclock VI de Dolphin.

### 3.2 Loi de présentation, vérifiée expérimentalement

`mRetraceCount = N` doit donner 59,94/N images par seconde. Mesuré en écrivant
directement `TDisplay + 0x4C`, littéral laissé à `0.5f` pour isoler la
présentation :

| N | 1 | 2 | 3 | 4 | 0 |
|---|---|---|---|---|---|
| images/s **mesuré** | 59,67 | 30,00 | 20,00 | 15,00 | 60,00 |
| 59,94/N attendu | 59,94 | 29,97 | 19,98 | 14,98 | — |
| écart | 0,5 % | 0,1 % | 0,1 % | 0,1 % | — |

La loi tient, **y compris la prédiction que `N = 0` se comporte comme `N = 1`**.

### 3.3 Le `nop` est inapplicable à chaud

Écrire `0x60000000` en `0x802FCB24` modifie bien la MEM1 émulée — relecture
confirmant la valeur — mais **ne change rien au comportement** : Dolphin
continue d'exécuter le bloc JIT compilé. Le correctif de `gamemasterplc` ne
peut donc pas être appliqué par écriture mémoire externe.

`mRetraceCount = 1` produit exactement le même effet et **est une donnée**.
C'est la voie à prendre, et c'est celle de BetterSunshineEngine.
Voir [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).

---

## 4. `0x80414904` — le littéral « non identifié » du plan

Identifié. Deux références, toutes deux dans `TModelGate` (les portails à flou
d'écran) :

| Adresse | Fonction |
|---|---|
| `0x801EB16C` | `TModelGate::perform(unsigned long, JDrama::TGraphics*)+0x158` |
| `0x801EC41C` | `TModelGate::loadAfter()+0x3D4` |

### 4.1 Site d'usage — `perform` @ `0x801EB16C`

```c
f32 d = JGeometry::TUtil<f>::sqrt(dx*dx + dy*dy + dz*dz);  // 0x801EB144..158
if (d < 1000.0f) {                 // 0x80414900 = 1000.0f
    this->m0xD0 += 0.01f;          // 0x80414904   <-- le littéral patché
    if (this->m0xD0 > 1.0f) {      // 0x80414908 = 1.0f
        this->m0xD0 = 1.0f;
        this->mState = this->mPrevState;   // lha +0xC8 -> sth +0xCA
    }
}
```

`m0xD0` est une progression normalisée dans `[0, 1]`, atteinte en 100 appels,
déclenchée par la proximité du joueur. Elle alimente
`TModelGate::screenBlur(JDrama::TGraphics*)` @ `0x801EBD84`.

### 4.2 Site d'initialisation — `loadAfter` @ `0x801EC414`

Le littéral appartient à un bloc de paramètres contigu recopié dans l'objet :

| Destination | Source | Valeur |
|---|---|---|
| `+0xE4` | `0x8041490C` | `0.0f` |
| `+0xE8` | `0x80414904` | `0.01f` ← patché |
| `+0xEC` | `0x80414964` | `0.02f` |
| `+0xF0` | `0x8041496C` | `500.0f` |
| `+0xF4` | `0x80414900` | `1000.0f` |

Un couple (taux lent, taux rapide) et un couple (rayon proche, rayon lointain).
Le DOL contient **déjà** `0.02f` en `0x80414964` — soit exactement la valeur
`3CA3D70A` que le Gecko écrit dans `0x80414904`. Le patch aligne donc le taux
lent sur le taux rapide.

### 4.3 Anomalie : le sens de la mise à l'échelle est douteux

> **À ne pas reprendre sans mesure.** Ce point est une divergence relevée avec
> l'implémentation de référence, pas une conclusion.

`gamemasterplc` et BSE font tous deux progresser ce littéral avec la cadence :
`0.01` à 30 FPS, `0.02` à 60, `0.04` à 120.

Or `m0xD0 += k` est un incrément **par appel**. D'après la règle du § 1.3,
lorsqu'on passe de 30 à 60 FPS :

- si `TModelGate::perform` est dans une liste **de simulation**, il est appelé
  120 fois par seconde dans les deux cas → **aucune correction n'est
  nécessaire** ;
- s'il est dans une liste **par image rendue**, la fréquence d'appel *double* →
  il faudrait **diviser** `k` par deux, pas le multiplier.

Dans les deux lectures, doubler `k` accélère le fondu. À 60 FPS avec `0.02`,
l'effet serait quatre fois plus rapide qu'à 30 FPS avec `0.01`.

Trois explications possibles, aucune écartée à ce stade :

1. un choix esthétique délibéré (« rendre les portails plus réactifs ») ;
2. une erreur de signe reconduite de `gamemasterplc` vers BSE ;
3. un mécanisme que l'analyse statique ne voit pas.

**Expérience décisive** — chronométrer le fondu d'un portail à 30 puis à 60 FPS,
littéral patché puis non patché. Quatre mesures, protocole en
[`04-tests.md`](04-tests.md). Tant qu'elles ne sont pas faites, ne pas reprendre
cette ligne du Gecko par imitation.

---

## 5. La troncature qui gèle les particules — `TMarioParticleManager::perform`

Quatrième mécanisme de cadencement, absent du plan de départ et, semble-t-il, de
toute la littérature sur le sujet. C'est le seul endroit connu où le palier 120
casse quelque chose **par un mécanisme propre**, et non par la règle générale du
§ 1.3.

`perform__21TMarioParticleManagerFUlPQ26JDrama9TGraphics` @ `0x80288780` :

```
802887A4  bl     SMSGetAnmFrameRate()     ; 60 / horloge logique
802887A8  fctiwz f0, f1                   ; conversion flottant -> entier, par troncature
802887AC  stfd   f0, 0x90(r1)
802887B0  lwz    r23, 0x94(r1)            ; r23 = le compteur de boucle
802887B4  b      802887C4
802887B8  lwz    r3, 0x3b8(r25)
802887BC  bl     JPAEmitterManager::calc()
802887C0  addi   r23, r23, -1
802887C4  cmpwi  r23, 0
802887C8  bgt    802887B8
```

Le système de particules est avancé `(int)SMSGetAnmFrameRate()` fois par image
rendue :

| Palier | `SMSGetAnmFrameRate()` | `(int)` | Appels à `calc()` | Cadence JPA |
|---|---|---|---|---|
| 30 FPS | 2,0 | 2 | 2 par image | 60 Hz |
| 60 FPS | 1,0 | 1 | 1 par image | 60 Hz |
| **120 FPS** | **0,5** | **0** | **aucun** | **0 Hz — figé** |

Le JPA est donc authoré à 60 Hz, comme les animations J3D, et la boucle le
recale correctement — tant que le facteur est entier. À 120 FPS il vaudrait 0,5,
et une boucle entière ne sait pas faire un demi-tour.

**Ce n'est pas un défaut de `SMSGetAnmFrameRate()`.** Sa valeur de 0,5 est
*juste* : les 215 autres sites d'appel la consomment en flottant, comme cadence
d'avance d'animation, et 0,5 image d'animation par image de jeu est exactement
ce qu'il faut à 120 FPS. Seule cette troncature est fausse.

### 5.1 Ce que cela gèle

Tout ce qui est JPA, ce qui va bien au-delà des « effets » au sens décoratif :

- les jets d'eau de la place Delfino (`TMapObjWaterSpray::calc` @ `0x801C12D4`,
  qui émet par `TMarioParticleManager::emit`) ;
- **l'animation d'entrée dans un graffiti** — `TMario::warpInEffect()` @
  `0x802637A0` passe entièrement par `gpMarioParticleManager`
  (`emitAndBindToMtx`, callback `TWarpInCallBack` posé en `+0x114`). Le
  rétrécissement de Mario en « petit rond » est émis, mais jamais avancé : Mario
  saute et disparaît.

Les particules sont émises normalement ; elles ne naissent, n'avancent ni ne
meurent. Selon l'effet, cela donne un ruban figé ou une absence complète.

### 5.2 BetterSunshineEngine ne corrige pas ce point

`src/patches/fps.cpp`, relu le 2026-09-22 : aucune mention de JPA ni du
gestionnaire de particules, et un `case FPS_120` qui se limite à
`mRetraceCount = 0`, `0x804167B8 = 2.0f`, `0x80414904 = 0.04f`.
**Le mode 120 FPS de BSE a donc le même défaut.**

### 5.3 Le correctif posé, et pourquoi il n'est pas exact

`0x802887B0` : `lwz r23, 0x94(r1)` → `li r23, 1`. Le compteur vaut 1 quelle que
soit la cadence.

À 120 FPS cela donne **un** appel par image rendue, soit 120 Hz de JPA au lieu
des 60 Hz d'origine : **deux fois trop vite**. C'est une compensation, pas une
correction.

Le correctif exact demande un appel **une image sur deux** — donc un état
persistant entre deux images, donc un hook ASM avec sa propre variable, pas une
écriture d'un mot. Il n'a pas été écrit.

Non figé vaut mieux que figé, mais la distinction doit rester lisible : c'est la
seule ligne du profil livré qui ne soit pas correcte par construction.
