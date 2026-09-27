# Sunshine Overdrive

**Super Mario Sunshine à 120 images par seconde, sur Dolphin, avec la vitesse de
jeu d'origine.** Pas un speedhack, pas d'interpolation : le jeu simule toujours à
ses 120 Hz d'origine, il affiche simplement chaque pas de simulation au lieu d'un
sur quatre.

En prime : **la goop aux bords lisses**. Les bords en escalier de la pollution,
très visibles en haute résolution, sont remplacés par des contours arrondis et
un bord adouci, sans toucher au gameplay.

> **English summary.** A Dolphin game-settings profile (`GMSE01.ini`) that runs
> Super Mario Sunshine (NTSC-U) at ~120 FPS with correct game speed. The engine
> already simulates at a fixed 120 Hz and renders every 4th step; the profile
> overclocks the emulated VI 2× and makes the game render every step. It then
> fixes the systems that were counting in *rendered frames* instead of
> *simulation steps* (particles, screen wipes, audio fades, birds, bosses…),
> all as `[OnFrame]` patches — no ISO modification. It also smooths the
> staircase edges of the goop (display-only filtered copy of the pollution
> mask, compiled C code injected the same way). Copy `deliver/GMSE01.ini` to
> `%APPDATA%\Dolphin Emulator\GameSettings\` and boot the game. Docs are in
> French.

---

## Installer

**Il faut :**

- Dolphin récent (développé et testé avec Dolphin 2606a) ;
- votre propre copie de **Super Mario Sunshine NTSC-U (GMSE01)** — aucune autre
  région n'est prise en charge ;
- un PC capable d'émuler le jeu à **2× sa vitesse** : l'overclock du VI accélère
  aussi l'horloge du processeur émulé.

**Avec l'installateur (recommandé) :**

1. Télécharger `Sunshine-Overdrive-Setup-*.exe` dans les
   [Releases](https://github.com/KoroModding/sunshine-overdrive/releases/latest)
   et le lancer. Aucun droit administrateur n'est demandé.
2. Si Windows affiche « Windows a protégé votre ordinateur » (l'installateur
   n'est pas signé) : *Informations complémentaires → Exécuter quand même*.
3. L'installateur trouve le dossier de Dolphin tout seul (registre de Dolphin,
   puis `%APPDATA%`, puis `Documents`). Dolphin portable : choisir le dossier
   `User` situé à côté de `Dolphin.exe`.
4. Un `GMSE01.ini` déjà présent est mis de côté et **restauré à la
   désinstallation** (Paramètres Windows → Applications → Sunshine Overdrive).

Installation silencieuse :
`Sunshine-Overdrive-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DOLPHINDIR="C:\...\Dolphin Emulator"`.

**À la main :**

1. Copier [`deliver/GMSE01.ini`](deliver/GMSE01.ini) dans le dossier
   utilisateur de Dolphin, sous `GameSettings\` :
   - Windows : `%APPDATA%\Dolphin Emulator\GameSettings\GMSE01.ini`
   - Linux : `~/.local/share/dolphin-emu/GameSettings/GMSE01.ini`
   - macOS : `~/Library/Application Support/Dolphin/GameSettings/GMSE01.ini`

   S'il existe déjà un `GMSE01.ini` à cet endroit, le sauvegarder d'abord :
   le profil le remplace.
2. **Démarrer le jeu** (ou le redémarrer). Tout est lu au lancement.

**Par script (Windows, Python 3.10+) :**

```sh
python tools/install_profile.py install     # installe, en gardant l'ancien fichier de côté
python tools/install_profile.py status
python tools/install_profile.py uninstall   # revient exactement à l'état d'avant
```

**Réglages Dolphin :**

- **N'activez aucun code Gecko ni Action Replay pour ce jeu.** Le profil loge ses
  routines dans la zone mémoire du gestionnaire Gecko (0x80001800–0x80003000) ;
  un code Gecko actif les écraserait.
- Le profil inclut le code **écran large 16:9** de gamemasterplc : réglez
  *Graphiques → Rapport d'aspect* sur *Forcer 16:9*.
- Rien d'autre à toucher : l'overclock du VI est porté par le profil lui-même
  (section `[Core]`), il ne change rien pour les autres jeux.

**Vérifier (facultatif, Windows) :**

```sh
python tools/validate_120.py     # peut être lancé avant le jeu, il attend
```

Il relit le profil dans la mémoire du jeu et mesure la vitesse de simulation :
attendu ~119,8 images/s et 120,0 pas de simulation par seconde.

**Désinstaller :** supprimer le fichier (ou `install_profile.py uninstall`).

---

## Comment ça marche

### Le moteur est déjà découplé

`TMarDirector::direct()` contient un accumulateur à virgule fixe : 600 unités de
budget par seconde, 5 unités par pas de simulation. Le jeu simule donc à
**120 Hz constants**, et c'est le nombre de pas exécutés par image affichée qui
varie : 4 à 30 FPS, 2 à 60, **1 à 120**. En dessous d'un pas par image, le
quantum ne descend pas : **120 FPS est la limite arithmétique du moteur**.
Au-delà, il faudrait interpoler.

Trois écritures suffisent à atteindre ce palier :

| Où | Quoi | Effet |
|---|---|---|
| Dolphin `[Core]` | `VIOverclock = 2.0` | le VI émulé délivre 119,88 champs/s au lieu de 59,94 |
| `0x804167B8` | `0.5f` → `2.0f` | `SMSGetVSyncTimesPerSec()` renvoie 120 : un pas par image, animations recalées |
| `0x802FCB24` | `bl VIWaitForRetrace` → `nop` | une image présentée par champ VI |

Mesuré : **119,8 images/s, simulation à 120,0 Hz**, trajectoire de saut
identique à la virgule près sur 90 pas entre 30 et 120 FPS, chute libre à
0,06 % près. La physique de Mario n'est **jamais** remise à l'échelle : elle tourne
déjà par pas de simulation.

### Ce qui casse quand même, et pourquoi

Tout le code de Sunshine ne tourne pas au même rythme :

- ce qui est exécuté **à chaque pas de simulation** (drapeau de perform `0x1` :
  mouvements, nerfs des ennemis, physique) est correct à toute cadence ;
- ce qui est exécuté **une fois par image affichée** (drapeau `0x2`, dessin,
  calcul des matrices) tourne 4× plus souvent à 120 FPS. Tout ce qui y compte en
  « images » va 4× trop vite ;
- `SMSGetAnmFrameRate()` vaut 2,0 à 30 FPS et 0,5 à 120. C'est juste pour une
  animation avancée une fois par image. Mais quand ce facteur est utilisé dans du
  code exécuté **par pas** comme multiplicateur de vitesse, l'objet devient 4×
  trop lent : c'est le cas des oiseaux, de l'anguille géante, de la grande roue.

Chaque correctif du profil traite un cas relu dans l'exécutable du jeu, et
presque tous ont été mesurés en jeu avant et après. Le facteur
`M = 2 × littéral 0x804167B8` (1 à 30 FPS, 4 à 120) est relu à l'exécution par
la plupart des routines.

### Ce que contient le profil

| Module (`tools/fixes/`) | Correction |
|---|---|
| base (`build_profile.py`, `build_caves.py`) | cadence ; **particules** (le gestionnaire JPA n'avançait plus du tout à 120 FPS) ; **portails graffiti** (infranchissables sans correctif) ; **musiques qui se figeaient** (perte du tempo entre fil de jeu et fil audio) |
| `fades.py` | durées des fondus audio (pause, changements de musique) |
| `soundsets.py` | sons de FLUDD, du nettoyage, de la goop, qui se répétaient 4× trop souvent |
| `sound.py` | hauteur et volume des sons d'animation (hors Mario) |
| `doppler.py` | effet Doppler 4× trop faible |
| `widescreen.py` | code 16:9 de gamemasterplc, converti en `[OnFrame]` |
| `hx.py` | **transitions d'écran** (cercle, fondus d'entrée de niveau, Game Over…) 4× trop rapides |
| `petey.py` | Petey Piranha vomissait 4× trop vite |
| `birds.py` | oiseaux 4× trop lents en vol |
| `eel.py` | anguille géante (baie Noki) : toutes ses animations 4× trop lentes |
| `bosses.py` | Mario Ombre, sous-marin de Bowser Jr, socles de la baignoire, Chenille géante, tête de Petey, calmar, flamme de Mecha-Bowser, Bullet Bills, grande roue et montagnes russes de Pinna Park |
| `goop.py` (+ `goop/goop.c`) | **goop aux bords lisses** : voir ci-dessous |

Le détail de chaque correctif (adresses, instruction d'origine, preuve,
mesure) est en tête de son module et dans [`docs/00-journal.md`](docs/00-journal.md).

### La goop aux bords lisses

Le contour de la goop est l'isoligne 0,5 d'un masque I8 de 128×128 à 256×256
texels étiré sur toute une zone : un texel mesure 32 unités de jeu, et un
masque binaire filtré en bilinéaire donne des marches de la taille d'un texel.
Aucun réglage de Dolphin n'y change rien (filtrage forcé, MSAA, SSAA).

Contrainte : **ce masque est aussi celui du gameplay** (glissade, nettoyage,
comptage), et le jeu écrit directement dedans quand on arrose. Il n'est donc
jamais modifié. À la place, `goop.c` :

1. au chargement de chaque couche, alloue dans la mémoire du niveau une
   **copie d'affichage** de même taille (16 à 64 Ko, garde de 512 Ko libres,
   sinon rien ne change) et branche les matériaux dessus — le gameplay garde
   ses propres pointeurs vers le masque d'origine ;
2. remplit la copie avec un **filtre tente 3×3** du masque : contours arrondis
   et continus, sans décalage ;
3. la tient à jour : zones de chaque tampon de nettoyage aussitôt, et un
   balayage de fond de quelques lignes par image pour tout le reste ;
4. adoucit le bord (rampe d'opacité autour du seuil, mélange activé).

Le code est écrit en C, compilé pour le processeur de la GameCube avec le
clang PowerPC de BetterSunshineEngine, et injecté par `[OnFrame]` comme le
reste. Mesuré à Bianco : 5 couches, 120 images/s, 3,9 Mo encore libres.

### Pourquoi `[OnFrame]` et pas `[Gecko]`

Le PatchEngine de Dolphin applique les lignes `[OnFrame]` à chaque champ VI,
avant que le JIT ne compile le code concerné : on peut donc remplacer des
instructions. La section `[Gecko]` ne s'est pas chargée dans nos essais.

Piège découvert en chemin : Dolphin pose un crochet HLE en **0x800018A8**, le
point d'entrée du gestionnaire Gecko, **même sans code Gecko actif**. Exécuter une
instruction à cette adresse vide tout le cache JIT. Une routine qui y tombait
faisait chuter l'émulation à 8 images/s pendant les transitions en cercle.
`build_profile.py` refuse désormais tout mot en 0x800018A8 et 0x80002FFC.

---

## Limites connues

- **GMSE01 (NTSC-U) uniquement.** Les adresses ne valent pas pour les versions
  PAL ou japonaise.
- **Pas au-delà de 120 FPS** : il faudrait découpler rendu et simulation, puis
  interpoler.
- **Dolphin uniquement.** Le comportement du VI d'une vraie GameCube hors modes
  standard n'est pas connu.
- **Non corrigé, repéré à l'audit :**
  - fondus au noir simples (`TSMSFader`) : 4× plus courts (le correctif
    `fader.py` existe mais n'est pas activé) ;
  - Roi Boo : peut-être moins de bulles par crachat ;
  - Chomp de feu : Mario peut-être tiré trop fort par la queue ;
  - quelques effets cosmétiques de la raie et du calmar.
- **Incompatible avec les mods basés sur BetterSunshineEngine**, dont Super Mario
  Eclipse : ils ont leur propre réglage de cadence et modifient les mêmes endroits
  du code.
- **Incompatible avec tout code Gecko ou Action Replay** actif pour GMSE01.
- **Packs de textures** remplaçant les masques de goop (dossier
  `pollution_maps` de certains packs) : la goop affiche désormais la copie
  lissée, ces remplacements ne s'appliquent plus.

---

## Pour les développeurs

Les outils sont en Python et visent Windows : lecture et écriture de la mémoire
d'un Dolphin en cours d'exécution par `ReadProcessMemory`.

```sh
pip install -r requirements.txt
```

Le module de la goop est du C (`tools/fixes/goop/goop.c`). Les binaires compilés
sont versionnés : le profil se reconstruit **sans compilateur**. Pour modifier
le C, il faut le clang PowerPC livré avec
[BetterSunshineEngine](https://github.com/DotKuribo/BetterSunshineEngine)
(dossier `compiler/`) :

```sh
set PPC_CLANG_DIR=C:\chemin\vers\BetterSunshineEngine\compiler
python tools/fixes/goop.py        # compile, lie, vérifie bornes et sites
```

Les fichiers du jeu ne sont **pas** dans le dépôt. À placer dans `work/`, qui est
ignoré par git :

```sh
python tools/gciso.py dol <votre-iso-GMSE01> work/dol/GMSE01.dol
curl -sSL -o work/maps/us.map \
  https://raw.githubusercontent.com/DotKuribo/BetterSunshineEngine/master/maps/us.map
```

Ensuite :

```sh
python tools/build_profile.py                     # assemble et contrôle, sans écrire
python tools/build_profile.py --write --inconditionnel \
  --modules fades,soundsets,widescreen,sound,petey,doppler,hx,birds,eel,bosses,goop
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map <symbole|adresse> [n]
python tools/xref.py   work/dol/GMSE01.dol work/maps/us.map <adresse>
```

`build_profile.py` bloque sur :
- toute adresse écrite deux fois avec des valeurs différentes ;
- toute écriture identique au mot déjà présent dans le jeu ;
- tout branchement vers une cible inconnue ;
- toute écriture sur un crochet HLE de Dolphin.

Outils de mesure en jeu (`tools/watch_*.py`, `validate_120.py`) : cadence,
transitions, fondus audio, sons, oiseaux, état de Mario image par image.
Goop : `goop_inspect.py` (matériaux J3D décodés commande GX par commande GX),
`goop_ctl.py` (état du module, interrupteurs lissage / bord fondu en direct),
`goop_probe.py` (la copie suit-elle le masque ?), `goop_soft.py` (prototype du
bord fondu, appliqué en direct).

L'installateur (`installer/SunshineOverdrive.iss`, Inno Setup 6) est construit
par GitHub Actions (`.github/workflows/installateur.yml`) à chaque tag `v*` et
publié en Release. En local :

```sh
ISCC.exe /DAppVer=1.0.0 installer\SunshineOverdrive.iss     # -> dist\
```

Documentation :

| Fichier | Contenu |
|---|---|
| [`docs/00-journal.md`](docs/00-journal.md) | journal de bord, session par session, avec toutes les mesures |
| [`docs/01-mecanismes.md`](docs/01-mecanismes.md) | les mécanismes de cadence du moteur, démontrés au désassembleur |
| [`docs/02-adresses.md`](docs/02-adresses.md) | registre des adresses et de leur degré de vérification |
| [`docs/03-outillage.md`](docs/03-outillage.md) | les outils |
| [`docs/04-tests.md`](docs/04-tests.md) | la batterie de tests et ses résultats |
| [`docs/05-regions.md`](docs/05-regions.md) | pourquoi GMSE01 seulement |
| [`docs/adr/`](docs/adr/) | décisions d'architecture |

---

## Crédits

- **gamemasterplc** : code 60 FPS d'origine et code écran large 16:9 (livrés
  avec Dolphin), point de départ de ce travail.
- **BetterSunshineEngine** ([DotKuribo](https://github.com/DotKuribo/BetterSunshineEngine),
  JoshuaMKW) : inventaire de référence des systèmes qui cassent au-delà de
  30 FPS, et carte des symboles GMSE01.
- Décompilations **[doldecomp/sms](https://github.com/doldecomp/sms)** et
  **[Graffito-Decomp](https://github.com/ryanbevins/Graffito-Decomp)**, symboles
  **[shibbo/Corona](https://github.com/shibbo/Corona)**.
- Super Mario Sunshine est une marque de Nintendo. Ce dépôt ne contient aucun
  fichier du jeu ; il faut posséder sa propre copie.
