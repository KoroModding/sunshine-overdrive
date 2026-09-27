# Régions

> Le plan de départ pose la règle : **ne pas confondre les régions**. Ce document
> établit la correspondance par la preuve plutôt que par la table de codes de
> triche, et corrige une attribution erronée relevée dans le plan.

## Cible du projet

**`GMSE01` — NTSC-U, révision 0.** C'est la région couverte par
BetterSunshineEngine, par les symboles de Corona et par la map `us.map`. Toutes
les adresses de [`02-adresses.md`](02-adresses.md) s'y rapportent.

| Image | Identifiant | Région | SHA-1 du DOL |
|---|---|---|---|
| `Super Mario Sunshine (2002)(Nintendo)(US).iso` | `GMSE01` | NTSC-U | `a678…728f` |
| `Super Mario Sunshine (Europe) (En,Fr,De,Es,It).iso` | `GMSP01` | PAL | `a2ed…02bf` |

Le DOL PAL a été extrait et analysé pour établir la correspondance ci-dessous,
mais **le projet ne cible pas PAL**. Voir [`adr/0001-region-cible.md`](adr/0001-region-cible.md).

---

## Correction : `0x8040DD10` et `0x8040BE54` sont des adresses **PAL**

Le plan de départ, section « Ne pas confondre les régions », écrit :

> Le portage JP des adresses dans BSE semble faux : `0x8040DD10` et
> `0x8040BE54` tombent, dans les symboles GMSJ01, sur un littéral de
> `NpcInitPrg.cpp` et sur des constantes de `s_atan.c`.

Le constat est juste — ces adresses ne veulent rien dire en JP — mais la
conclusion l'est à moitié. **Ce ne sont pas des adresses JP mal portées : ce
sont les adresses PAL.** Elles figurent telles quelles dans le code
`$60FPS [gamemasterplc]` de `Sys/GameSettings/GMSP01.ini` livré avec Dolphin.

### Preuve

`0x8040DD10` contient `3F000000` (`0.5f`) dans le DOL PAL, et la fonction qui
le charge est structurellement identique à `SMSGetVSyncTimesPerSec` :

```
; GMSP01, 0x8029FC8C
8029FC9C  lfs    f31, -0x548(r2)   ; 0x8040DD38 = 60.0f
8029FCA0  bl     0x803488F8        ; VIGetTvFormat
8029FCA4  cmpwi  r3, 2
...
8029FCD4  lfs    f31, -0x544(r2)   ; 0x8040DD3C = 50.0f
8029FCD8  lfs    f0,  -0x570(r2)   ; 0x8040DD10 = 0.5f
```

Même séquence de comparaisons, mêmes trois littéraux, même rôle. `r2` vaut
`0x8040E280` en PAL (`lis r2,-0x7fc0 ; ori r2,r2,0xe280` @ `0x8000536C`).

```sh
: > work/maps/empty.map
python tools/disasm.py work/dol/GMSP01.dol work/maps/empty.map 0x8029FC8C 20
python tools/xref.py   work/dol/GMSP01.dol work/maps/empty.map 0x8040DD10
```

BSE a donc étiqueté « JP » un jeu d'adresses `GMSP01`. À signaler en amont si le
projet contribue à ce dépôt.

---

## Table de correspondance

| Rôle | `GMSE01` (US) | `GMSP01` (PAL) | Preuve |
|---|---|---|---|
| base `r2` (`.sdata2`) | `0x80416BA0` | `0x8040E280` | **M** |
| base `r13` (`.sdata`) | `0x804141C0` | `0x8040B960` | **M** |
| `SMSGetVSyncTimesPerSec` | `0x802A7C48` | `0x8029FC8C` | **M** |
| littéral `0.5f` (horloge logique) | `0x804167B8` | `0x8040DD10` | **M** |
| littéral `60.0f` | `0x804167D8` | `0x8040DD38` | **M** |
| littéral `50.0f` | `0x804167DC` | `0x8040DD3C` | **M** |
| `bl VIWaitForRetrace` dans `waitForRetrace` | `0x802FCB24` | `0x802F4CB4` | **H** (repris du `.ini`, non recoupé) |
| littéral `0.01f` (`TModelGate`) | `0x80414904` | `0x8040BE54` | **M** pour le contenu, **H** pour le rôle |
| hook `TBoidLeader` | `0x800066EC` | `0x800066EC` | **H** |

Les deux régions partagent l'adresse du hook `TBoidLeader` — le code exécutable
de tête est identique. Les écarts n'apparaissent que plus loin :
`0x802A7C48 − 0x8029FC8C = 0x7FBC` pour le code, `0x804167B8 − 0x8040DD10 = 0x8AA8`
pour `.sdata2`. **Le décalage n'est pas uniforme** : il ne faut jamais porter
une adresse d'une région à l'autre par soustraction d'un delta constant.

Le nombre de consommateurs diffère aussi : le littéral `0.5f` a **trois**
références en US et **quatre** en PAL. Un portage mécanique manquerait la
quatrième.

---

## PAL : le code « 60 FPS » n'en donne pas 60

Conséquence directe de la lecture ci-dessus, et point que ni le plan de départ ni le
`.ini` de Dolphin ne mentionnent.

`SMSGetVSyncTimesPerSec()` retourne `résultat × 0.5f`, où `résultat` dépend de
`VIGetTvFormat()` :

| Format | Valeur | Retour d'origine | Retour avec `0.5f → 1.0f` |
|---|---|---|---|
| `VI_NTSC`, `VI_MPAL`, `VI_EURGB60` | `60.0f` | 30 | **60** |
| `VI_PAL` | `50.0f` | 25 | **50** |

Sur une console ou une configuration Dolphin en PAL 50 Hz, le code
`$60FPS [gamemasterplc]` de `GMSP01.ini` produit donc **50 FPS**, pas 60. La
vitesse de jeu reste correcte — l'accumulateur ramène la simulation à 120 Hz
(4 5 5 5 5 4 5 5 sous-pas, moyenne 4,8 à 25 Hz ; 2 2 3 2 3 2 2 3, moyenne 2,4 à
50 Hz), mais la présentation plafonne à 50.

Pour 60 FPS réels en PAL il faut **EURGB60** (PAL60 / 480p), qui fait renvoyer
`VI_EURGB60` à `VIGetTvFormat()`. Pour 120 FPS logiques en PAL 50 Hz, le
littéral devrait valoir `2.4f`, pas `2.0f` — les valeurs de BSE ne sont pas
transposables telles quelles.

> **Non vérifié** — aucune de ces deux conclusions n'a été testée à
> l'exécution. Elles découlent du code lu, et sont sans objet tant que le
> projet reste sur `GMSE01`.

---

## Décompilations

| Dépôt | Cible | Utilité ici |
|---|---|---|
| `doldecomp/sms` | `GMSJ01` | lecture ; PAL cassé, US non supporté |
| `ryanbevins/Graffito-Decomp` | `GMSJ01` | fork actif, 0 unité *NonMatching* — meilleure base de lecture |
| `shibbo/Corona` | `GMSE01` | symboles, archivé depuis 2020 |
| `DotKuribo/BetterSunshineEngine` | `GMSE01` | `maps/us.map`, 15 107 symboles |

La décompilation cible **JP** alors que le projet cible **US**. Une lecture de
la décompilation donne la *structure*, jamais une adresse directement
utilisable. Toute adresse doit être retrouvée dans le DOL US — c'est
exactement ce que fait `tools/xref.py`.
