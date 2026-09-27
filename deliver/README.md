> **Historique.** Ce document décrit le **profil de base** (cadence, particules,
> portails, musiques) tel que livré en session 5. Le profil actuel y ajoute les
> modules de `tools/fixes/` (transitions, audio, oiseaux, boss…) : voir le
> [README principal](../README.md) et [`docs/00-journal.md`](../docs/00-journal.md).

# Profil 120 FPS — Super Mario Sunshine (GMSE01, NTSC-U)

Ce qui est livré ici fait tourner le jeu à **119,8 images par seconde avec la
vitesse de jeu correcte**, sur Dolphin, sans modifier l'ISO. Mesuré, pas déduit
— relevés plus bas.

Ce n'est pas un speedhack : la simulation continue de tourner à ses 120 Hz
d'origine. Le moteur de Sunshine est déjà découplé — il simule à 120 Hz et
choisit combien de sous-pas il exécute par image rendue. Au palier 120, ce
nombre vaut exactement 1. Il n'y a donc rien à interpoler et rien à remettre à
l'échelle : c'est la seule cadence au-dessus de 60 qui s'obtienne sans écrire
une ligne de nouvelle logique de jeu.

C'est aussi la dernière : le quantum de l'accumulateur vaut 5 unités sur un
budget de 600 par seconde, et il ne descend pas sous un sous-pas par image.
**120 FPS est une limite arithmétique du moteur**, pas une limite pratique.
Au-delà, il faut découpler le rendu de la logique et interpoler.

---

## Installer

```sh
python tools/install_profile.py install
```

Puis **démarrer le jeu** — ou le redémarrer s'il tourne déjà. Tout le profil est
lu à l'amorçage et n'a aucun effet sur une partie en cours.

C'est tout. Un seul fichier, `GameSettings/GMSE01.ini`, déposé dans le
répertoire utilisateur de Dolphin. Rien d'autre n'est touché : ni la
configuration globale, ni l'INI livré avec Dolphin, ni l'ISO, ni les
sauvegardes. Un `GMSE01.ini` utilisateur préexistant est mis de côté dans
`work/` et restauré à la désinstallation.

Revenir à l'état d'origine :

```sh
python tools/install_profile.py uninstall
```

## Vérifier

```sh
python tools/validate_120.py
```

Le script peut être lancé **avant** de démarrer le jeu : il attend. Il contrôle
les deux moitiés du profil séparément, puis rend un verdict sur la vitesse de
simulation — la seule grandeur qui dise si le jeu tourne juste.

---

## Ce que le profil contient

Une écriture côté hôte, trois mots de données et de code, et une routine à état.

| Où | Quoi | Pourquoi |
|---|---|---|
| hôte | `VIOverclock = 2.0` | le VI émulé délivre 119,88 champs/s au lieu de 59,94 |
| `0x804167B8` | `0.5f` → `2.0f` | `SMSGetVSyncTimesPerSec()` renvoie 120 : un sous-pas par image, animations recalées |
| `0x802FCB24` | `bl` → `nop` | `waitForRetrace` ne consomme plus qu'un champ par image présentée |
| `0x802887B0` | `lwz r23,…` → `bl 0x80002F10` | particules à 60 Hz à tous les paliers (voir plus bas) |
| `0x801EC29C` | chargement 0.02f → 0.005f | portails graffiti franchissables (décrément par image de `TModelGate`) |
| `0x80002F04`… | routine | générée par `tools/build_caves.py` — **incompatibles avec des codes Gecko actifs** |

L'overclock VI est la seule moitié qui ne puisse pas être posée depuis la MEM1 :
elle vit dans Dolphin, pas dans la GameCube émulée. Les trois autres passent par
la section `[OnFrame]`, que le PatchEngine de Dolphin applique **avant que le
JIT ne compile le bloc concerné** — ce qui permet de patcher une instruction,
impossible par écriture externe à chaud.

Ce que donne chaque moitié seule :

| VI à 2× | `[OnFrame]` | Résultat |
|---|---|---|
| non | non | 30 images/s, vitesse correcte — le jeu d'origine |
| non | oui | 60 images/s, **jeu à mi-vitesse** |
| oui | non | 60 images/s, **jeu à double vitesse** |
| oui | oui | **119,8 images/s, vitesse correcte** |

La ligne « double vitesse » n'est pas théorique : c'est l'état observé le
2026-09-22 entre l'installation du profil et son application. C'est pour elle
que `validate_120.py` juge sur les **sous-pas par seconde** et non sur les
images par seconde.

### Filet de sécurité

Si le profil hôte s'applique mais pas `[OnFrame]` :

```sh
python tools/keep120.py       # pose la cadence par écriture de données
```

Il attend le jeu, survit à un redémarrage, et **lit `0x802FCB24` avant de
décider du compte de champs** : le `nop` et `mRetraceCount = 1` mènent tous deux
à un champ par image mais s'additionnent, et leur cumul donne zéro champ — plus
aucune attente de balayage, le jeu s'emballe. Il ne peut pas, en revanche,
dégeler les particules : cela demande un correctif de code.

---

## Relevés du 2026-09-22

Cadence, par sondage de l'accumulateur (`measure_substeps.py` et
`validate_120.py`, Delfino Plaza) :

| | attendu | mesuré |
|---|---|---|
| `vsyncRate` | 5 | **5** |
| images présentées | 119,88 /s | **119,87 · 119,80 · 119,80 · 119,80 · 119,83** |
| sous-pas | 120,00 /s | **119,87 · 119,80 · 119,80 · 120,00 · 120,00** |
| sous-pas par image | 1,000 | **1,000** |
| vitesse de simulation | 100 % | **100,0 %** |

Échantillonnage auto-validé : tous les décréments valent exactement 5 et tous
les incréments exactement 5.

Physique, comparée au palier 30 FPS (`test_ballistic.py 42 30 120`) :

| | 30 FPS | 120 FPS |
|---|---|---|
| suite des vitesses verticales | référence | **identique sur 90 intégrations** |
| intégrations jusqu'au sommet | 42 | **42** |
| altitude du sommet | 225,75 | **225,75** |

Ce sont les mêmes valeurs qu'aux paliers 30 et 60 relevés en session 3 : la
gravité ne dépend pas de la cadence, et le palier 120 ne la change pas.

Chute libre de 3000 unités (`test_freefall.py 3000 120`) : **1,656 s** de durée
réelle, contre 1,655 s relevées à 30 FPS en session 2 — **0,06 % d'écart**.
C'est la mesure qui dit que le jeu tourne à la bonne vitesse en temps réel, et
pas seulement par sous-pas. Le compte d'intégrations relevé est 199 contre 198 :
une unité d'écart sur un détecteur de bord, pas une différence de physique.

---

## Les particules — un défaut trouvé ici, et une compensation assumée

À 120 FPS, **tout ce qui est JPA se fige** : jets d'eau, et l'animation
d'entrée dans un graffiti, où Mario saute et disparaît au lieu de se rétrécir.

La cause est exacte. Dans `TMarioParticleManager::perform`, le nombre d'appels à
`JPAEmitterManager::calc()` par image rendue vaut `(int)SMSGetAnmFrameRate()` :
2 à 30 FPS, 1 à 60, et **0 à 120**, la troncature de 0,5 valant zéro.

Ce n'est pas un défaut de `SMSGetAnmFrameRate()` : sa valeur de 0,5 est juste,
et les 215 autres sites d'appel la consomment en flottant sans problème. Seule
cette troncature est fausse.

**BetterSunshineEngine ne corrige pas ce point** — son `src/patches/fps.cpp` ne
mentionne ni JPA ni le gestionnaire de particules. Son mode 120 FPS a donc le
même défaut.

Premier correctif (`li r23, 1`) : particules dégelées mais **deux fois trop
rapides**, constaté à l'œil. Remplacé par un accumulateur à état,
`acc += SMSGetAnmFrameRate()`, un appel par unité entière : 2 / 1 / « 0 puis 1 »
selon le palier, soit 60 appels/s partout. Correct par construction ; **vitesse
à l'œil non encore jugée**.

## La musique — gel observé une fois, cause inconnue

Une fois, la musique de la place s'est figée : séquence « en lecture » côté
JAI, mais tempo effectif nul côté JASystem. Une limitation de la couche audio à
30 Hz a été essayée, puis retirée : elle faisait perdre des sons d'animation de
Mario (glissade sur l'eau), et la musique boucle normalement sans elle (test
A/B à l'oreille). `python tools/watch_audio.py` signale une séquence figée si
le gel revient. Détail dans `docs/00-journal.md`, session 6.

## Ce que le profil ne fait pas

**Il ne corrige aucun autre objet du jeu.** Tout ce qui vit dans les listes de
perform de simulation est correct automatiquement — la physique de Mario en fait
partie, mesures à l'appui — mais tout ce qui est mis à jour une fois par image
rendue tourne quatre fois trop vite au palier 120 :

- les nuées d'oiseaux (`TBoidLeader`)
- le boss anguille — 19 sites
- `TJointCoin`, SandBird, Petey Piranha, FireWanwan
- le minuteur des boîtes de dialogue
- **toutes** les transitions HX, `TSMSFader` et ses délais
- l'écran de sélection des Shines
- le boot, les logos, l'intro et les boucles de chargement — que BSE force à
  30 FPS et que ce profil laisse courir

Réimplémenter ces correctifs n'est pas au programme : le plan de départ demande de
dépendre de BetterSunshineEngine plutôt que de refaire son travail. Pour une
partie complète et non seulement une cadence juste, c'est BSE en mode 120 FPS
qu'il faut installer — et ce profil montre alors comment régler Dolphin en
face, ce que BSE ne peut pas faire depuis la GameCube émulée. Le correctif des
particules, lui, manque aussi à BSE.

## Ce qui n'est pas mesuré

À traiter comme inconnu tant que ce n'est pas vérifié :

- **L'audio.** L'overclock VI de Dolphin scale aussi l'horloge CPU émulée, et la
  période de l'AudioDMA en dérive. Que la hauteur et la vitesse du son restent
  justes est une affirmation du plan de départ, pas un relevé — l'instrumentation
  du projet lit la mémoire, elle n'entend rien. À juger à l'oreille.
- **Le coût hôte.** Un VI à 2× demande davantage à la machine. Une mesure sur
  cinq a relevé 87,5 images/s au lieu de 119,8, et à 87,5 images la simulation
  tombe à 72,9 % de la vitesse correcte : quand Dolphin ne tient pas la cadence,
  **le jeu ralentit pour de bon**. Les mesures suivantes sont revenues à 119,8 ;
  l'à-coup n'a pas été caractérisé.
- **Le littéral `0x80414904`** (fondu `TModelGate`), volontairement absent du
  profil. Voir `docs/01-mecanismes.md` § 4.3.
- **Le comportement hors NTSC-U.** Le profil est écrit pour GMSE01. En PAL les
  adresses diffèrent (`docs/05-regions.md`).
- **Pourquoi la section `[Gecko]` n'a pas été chargée.** Plus bloquant depuis
  que `[OnFrame]` fonctionne, mais toujours inexpliqué. Voir
  `docs/adr/0005-gecko-ou-donnees.md`.
