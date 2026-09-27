# Journal de bord

> Append-only. Chaque entrée dit **ce qui a été fait**, **ce qui en est
> ressorti** et **ce qui reste ouvert**. Les conclusions migrent ensuite vers
> les documents thématiques ; le journal garde la trace du chemin, y compris
> des impasses.

---

## 2026-09-15 — Session 1 : mise en place et vérification statique

### Fait

- Identification des images disponibles. L'image initialement fournie était
  **PAL (`GMSP01`)** alors que le plan est écrit pour US. Signalé ; l'image US
  (`GMSE01`) a été ajoutée. Décision consignée en
  [`adr/0001-region-cible.md`](adr/0001-region-cible.md).
- Écriture de l'outillage : `gciso.py`, `dol.py`, `symbols.py`, `disasm.py`,
  `xref.py`. Voir [`03-outillage.md`](03-outillage.md).
- Extraction des deux DOL, récupération de `us.map` (15 107 symboles, conforme
  au plan).
- Désassemblage et analyse de `TMarDirector::direct()`,
  `SMSGetVSyncTimesPerSec()`, `SMSGetAnmFrameRate()`,
  `JDrama::TVideo::waitForRetrace()`, `TModelGate::perform()` et
  `TModelGate::loadAfter()`.

### Ressorti

Cinq points que le plan de départ classait en « non vérifié » sont **résolus**, et
deux de ses affirmations sont **corrigées**.

| Point | Statut avant | Statut après |
|---|---|---|
| identité de `0x804167B8` | déduction par les splits | **vérifié** — `lfs f0,-0x3e8(r2)` dans `SMSGetVSyncTimesPerSec` |
| instruction neutralisée par `042FCB24` | non identifiée | **vérifié** — `bl VIWaitForRetrace` |
| identité de `0x80414904` | non identifiée | **vérifié** — taux de fondu de `TModelGate` |
| mécanisme de l'accumulateur | pseudo-code non recoupé | **vérifié** sur le code machine (`li 0x258`, `divw`, `addi -5`) |
| « nop ≡ `mRetraceCount = 1` » | affirmé sans preuve | **démontré** par le régime permanent |

**Corrections apportées au plan :**

1. *« le `break` du dernier sous-pas rend la branche de dessin inatteignable —
   le code décompilé est auto-contradictoire »*. Le code machine **n'est pas
   contradictoire**. Le drapeau `0x4000` survit au retour de `direct()` et le
   bloc de dessin s'exécute au début de l'appel suivant. C'est une boucle dont
   le point d'entrée est au milieu, que le décompilateur rend mal.
   → [`01-mecanismes.md` § 1.2](01-mecanismes.md)

2. *« `0x8040DD10` et `0x8040BE54` : portage JP faux dans BSE »*. Ce sont des
   adresses **PAL**, pas des adresses JP mal portées. Vérifié dans le DOL PAL :
   `0x8040DD10` contient `0.5f` et est chargé par la contrepartie exacte de
   `SMSGetVSyncTimesPerSec` en `0x8029FC8C`.
   → [`05-regions.md`](05-regions.md)

**Trouvailles non prévues au plan :**

- `0x804167B8` a **trois** consommateurs, le troisième étant
  `TApplication::drawDVDErr()`. Le patch touche l'écran d'erreur disque.
- Le `600` de `direct()` est un immédiat (`li r3, 0x258`), pas un littéral
  mémoire : **non patchable** par écriture simple. Seul le diviseur l'est.
- Patché **et** `count = 1`, `waitForRetrace` n'attend plus aucun champ — une
  voie de débridage de la présentation qui ne passe pas par le VBI Override.
  Non testée.
- En PAL, le code « 60 FPS » produit **50 FPS** hors mode EURGB60.

### Ouvert

- **Phase 0 non exécutée.** Aucune mesure à l'exécution n'a été faite. Le
  compte de sous-pas reste une conclusion statique.
  → [`04-tests.md`](04-tests.md)
- **Anomalie `0x80414904`.** BSE et `gamemasterplc` *doublent* un incrément par
  appel là où la règle de classement dit qu'il faudrait soit ne rien faire,
  soit diviser. Trois explications possibles, aucune écartée. Ne pas reprendre
  cette ligne du Gecko par imitation avant mesure.
  → [`01-mecanismes.md` § 4.3](01-mecanismes.md)
- **Classement des listes de perform.** Indéterminable statiquement
  (répartition virtuelle). Bloque la classification de tous les objets à
  corriger.
- **Hooks ASM non analysés** : `0x800066EC` (`TBoidLeader`) et `0x80C28028`.
- **Dolphin non lancé.** Aucune vérification en émulation.

---

## 2026-09-15 — Session 2 : phase 0 exécutée, palier 60 FPS validé

Dolphin 2606a tournant, GMSE01 chargé, Delfino Plaza.

### Fait

- Écriture de `tools/dolphin.py` : accès à la MEM1 émulée depuis l'extérieur,
  par `ReadProcessMemory` / `WriteProcessMemory`. La projection est localisée
  en balayant les régions du processus et **validée en lisant l'en-tête de
  disque GameCube** — ce qui confirme du même coup quelle image est chargée.
  Décision consignée en [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).
- `tools/measure_substeps.py`, `tools/patch.py`, `tools/test_freefall.py`.
- Phase 0.A et 0.B exécutées, campagne de mesure aux trois paliers, test de
  loi de présentation, test de régression de chute libre.

### Ressorti

**Le modèle du plan est confirmé sur toute la ligne.** Aucune mesure ne le
contredit.

| Mesure | Attendu | Obtenu |
|---|---|---|
| `vsyncRate` à 30 FPS | 20 | **20** |
| sous-pas par image à 30 FPS | 4 | **4,000** |
| sous-pas par seconde à 30 FPS | 120 | **120,00** |
| sous-pas par image à 60 FPS | 2 | **1,992** |
| images par seconde à 60 FPS | 60 | **60,00** |
| vitesse de simulation à 60 FPS | 100 % | **99,6 %** |
| intégrations de physique, chute de 3000 u | identiques | **198 à 30 FPS, 198 à 60 FPS** |

L'échantillonnage est auto-validé : à 30 FPS, sur 750 transitions, les 600
décréments valent tous exactement 5 et les 150 incréments tous exactement 20.

**Loi de présentation vérifiée expérimentalement** — `mRetraceCount = N` donne
59,94/N images par seconde :

| N | 1 | 2 | 3 | 4 | 0 |
|---|---|---|---|---|---|
| images/s mesuré | 59,67 | 30,00 | 20,00 | 15,00 | 60,00 |
| 59,94/N attendu | 59,94 | 29,97 | 19,98 | 14,98 | — |

Y compris la prédiction que `N = 0` et `N = 1` sont indiscernables, dérivée au
§ 3.1 de [`01-mecanismes.md`](01-mecanismes.md).

**Obstacle trouvé et contourné — le cache JIT.** Écrire `nop` en `0x802FCB24`
modifie bien la MEM1 (relecture confirmée) mais **ne change rien** : Dolphin
continue d'exécuter le bloc compilé. Le correctif de `gamemasterplc` est donc
inapplicable à chaud depuis l'extérieur.

Contournement : `mRetraceCount` est une **donnée**, en `TDisplay + 0x4C`, et
`TDisplay` s'atteint par `gpApplication + 0x1C`. L'écrire produit exactement le
même effet, sans toucher une instruction. C'est aussi la voie de BSE.
→ règle générale : **données oui, code non**.

**Le palier 120 FPS est bloqué par le VI, comme prévu.** Littéral à `2.0f` et
`mRetraceCount = 1` donnent bien 1 sous-pas par image, mais la présentation
plafonne à 60 images/s (le VI ne délivre que 59,94 champs/s) : la simulation
tombe à 60 Hz et le jeu tourne à **mi-vitesse**. Il faut le **VBI Frequency
Override** de Dolphin à 2×.

### Ouvert

- **Palier 120 FPS non démontré.** Le VBI Frequency Override est un réglage
  hôte de Dolphin, absent de la MEM1 et non rechargeable à chaud depuis le
  fichier de configuration. Il demande soit une action dans l'interface, soit
  un redémarrage de Dolphin avec la configuration modifiée.
- **Anomalie `0x80414904` toujours ouverte.** Le niveau chargé ne contient
  **aucune** instance de `TModelGate` (balayage de MEM1 par vtable
  `0x803D3F9C` : 0 résultat). Le chronométrage du fondu exige un niveau qui en
  contienne. Le classement des listes de perform a en revanche progressé
  statiquement — voir § 1.3 de [`01-mecanismes.md`](01-mecanismes.md).
- **Batterie de régression incomplète.** Seule la chute libre est faite. Les
  tests de saut, course et glissade demandent des entrées manette ; les tests
  de transitions et de boss demandent d'atteindre les situations concernées.
- **Hooks ASM non analysés** : `0x800066EC` (`TBoidLeader`) et `0x80C28028`.

---

## 2026-09-15 — Session 3 : entrées automatisées, physique tranchée

Même environnement : Dolphin 2606a, GMSE01, Delfino Plaza.

### Fait

- `tools/pad.py` — injection d'entrées manette par écriture dans
  `TMarioGamePad`. Décision et limites en
  [`adr/0003-injection-manette.md`](adr/0003-injection-manette.md).
- `tools/substep_clock.py` — comptage des sous-pas par observation de
  l'accumulateur, pour cadrer les mesures ailleurs qu'à l'horloge murale.
  [`adr/0004-mesure-en-sous-pas.md`](adr/0004-mesure-en-sous-pas.md).
- `tools/test_physics.py` — saut court, saut long, course, aux deux paliers.
- `tools/test_ballistic.py` — arc balistique imposé, sans entrée ni contact.
- `tools/dolphin_host.py`, `tools/second_instance.py` — deux tentatives pour
  atteindre le réglage hôte dont dépend le palier 120.

### Ressorti

**La physique est rigoureusement indépendante de la cadence.** L'arc balistique
donne la même suite de vitesses verticales sur **90 intégrations** à 30 et à
60 FPS, le même nombre d'intégrations jusqu'au sommet (**42**) et la même
altitude de sommet (**225,75**). La gravité vaut exactement 1,0 unité de
vitesse par sous-pas. Avec les 198 intégrations de la chute libre relevées en
session 2, la question est close.

→ [`04-tests.md`](04-tests.md)

**Les offsets de `TMario` sont prouvés, pas déduits.**
`SMS_SetMarioAccessParams()` @ `0x80273A0C` publie une douzaine de pointeurs
vers l'intérieur de l'objet : position en `+0x10`, vitesse en `+0xA4`, angles en
`+0x94`. Vingt-cinq instructions qui remplacent toute une séance de recherche
mémoire. → [`02-adresses.md`](02-adresses.md)

**Le saut se déclenche sur le front, pas sur le maintien.** Écrire `+0x18`
(maintien) ne fait rien, écrire `+0x1C` (front) fait sauter Mario. Recoupé avec
`JUTGamePad::update`, qui recopie ce bloc depuis le tableau statique
`0x80404484 + port × 0x30`.

**Trois impasses, gardées ici parce qu'elles coûtent cher à redécouvrir :**

1. *Le clavier est hors de portée.* `SendInput` n'atteint pas le bureau
   interactif depuis ce contexte — même `GetAsyncKeyState` dans le processus
   injecteur ne voit pas la frappe. Toute automatisation clavier est exclue.
   `tools/dolphin_host.py` en porte la trace.
2. *Un front permanent fabrique des triples sauts.* Rejouer le front à chaque
   image revient à réappuyer sur A à l'atterrissage. La hauteur d'un même saut
   variait alors de 73,79 à 140,0, avec trois `vy` initiales distinctes
   (41, 42, 52).
3. *L'écran titre lance une démo d'attraction.* Pendant celle-ci
   `gpMarDirector` et `gpMarioOriginal` sont parfaitement valides : un test
   instantané conclut « en jeu » à tort. Le critère d'arrivée exige donc une
   stabilité de plusieurs secondes.

**Une fausse alarme instructive.** Le premier relevé annonçait
`ÉCART SIGNIFICATIF` : 96,60 contre 81,59 sur la hauteur du saut long,
reproductible. Trois hypothèses écartées par la mesure (aléa d'injection, type
de saut, résolution du relâchement), et la cause était le décor — Mario tapait
un surplomb. Une hauteur d'apogée mesure le plafond autant que la gravité.

**Seconde instance de Dolphin pilotable de bout en bout.** Répertoire
utilisateur isolé, `VIOverclock = 2.0` passé en ligne de commande, carte mémoire
recopiée, et traversée complète — logos, intro, écran titre, sélection de
fichier — par la seule injection mémoire. Arrivée en jeu stable en **92,6 s**,
sans aucune intervention.

### Ouvert

- **Palier 120 FPS toujours pas mesuré.** La seconde instance était en jeu, le
  VI à 2×, la mesure allait être lancée — la session s'est arrêtée là.
- **Anomalie `0x80414904`** — inchangée, toujours en attente d'un niveau
  contenant un `TModelGate`.
- **Classement des listes de perform (0.C)** — inchangé. C'est le seul point de
  la phase 0 qui exige encore un point d'arrêt : compter les exécutions d'une
  fonction ne se lit pas dans la mémoire.
- **Hooks ASM non analysés** : `0x800066EC` (`TBoidLeader`) et `0x80C28028`.

---

## 2026-09-17 — Session 4 : consolidation, et mise en attente de la voie 120

Aucune mesure nouvelle : Dolphin n'était pas lancé, et l'instruction reçue
était de **ne pas lancer de seconde instance**. Session de mise au propre.

### Fait

- Consignation de la session 3, restée entièrement hors documentation :
  journal, relevés de tests, registre d'adresses, outillage, et les deux ADR
  ci-dessus.
- Les offsets utilisés par `pad.py`, `test_physics.py` et `test_ballistic.py`
  sont désormais inscrits au registre avec leur niveau de preuve. Ils
  circulaient dans le code sans y figurer, ce que la règle du projet interdit.
  Tous sont passés **M** : `SMS_SetMarioAccessParams` prouve les offsets de
  `TMario`, `setGamePad` celui de `mGamePad`, `updateMeaning` et
  `checkController` ceux de la manette.
- **Révision du critère de `test_physics.py`.** Son verdict portait sur des
  hauteurs et des distances — les grandeurs qui avaient produit la fausse
  alarme. Il porte désormais sur les profils de vitesse par sous-pas ; les
  scalaires restent affichés, sans valeur de verdict. Les profils sont recalés
  sur l'événement (première valeur non nulle) et non sur le début du sondage :
  l'entrée injectée n'étant pas vue à la même image selon la cadence, deux
  profils identiques auraient sinon semblé diverger dès leur premier élément.
  Les trois fonctions pures qui portent ce calcul sont vérifiées hors ligne.
- `second_instance.py` et `dolphin_host.py` complétés : leurs commandes
  documentées existent maintenant réellement. `second_instance start` **refuse**
  de démarrer si une instance tourne déjà, deux instances se disputant le GPU.
- L'impasse clavier est inscrite en tête de `dolphin_host.py`, au lieu de
  n'exister que dans l'historique d'une session.

### Ouvert

Inchangé par rapport à la session 3, plus un point :

- **La révision du critère de `test_physics.py` n'a pas été rejouée.** Le code
  compile, ses fonctions pures passent un contrôle hors ligne, mais aucune
  exécution ne l'a confrontée au jeu. Le relevé de `04-tests.md` reste celui de
  l'ancien critère et le dit.

---

## 2026-09-22 — Session 5 : palier 120 FPS atteint, mesuré, et deux défauts trouvés

Dolphin 2606a, GMSE01, Delfino Plaza. Première session où le jeu tourne
réellement à 120 FPS.

### Fait

- **Livraison** : `deliver/GMSE01.ini` (profil par jeu Dolphin),
  `tools/install_profile.py` (installation réversible), `tools/keep120.py`
  (maintien du palier par écriture de données), `tools/validate_120.py`
  (contrôle des deux moitiés + verdict sur la vitesse de simulation).
- Campagne de mesure au palier 120, régression balistique 30 vs 120, chute
  libre à 120.
- Analyse statique de `TMarioParticleManager::perform`, `TMapObjWaterSpray::calc`
  et `TMario::warpInEffect` à la suite de deux défauts visuels signalés.

### Ressorti

**Le palier 120 FPS est atteint et mesuré.** C'était le point ouvert depuis la
session 3.

| Mesure | Attendu | Obtenu |
|---|---|---|
| `vsyncRate` | 5 | **5** |
| images présentées | 119,88 /s | **119,87 · 119,80 · 119,80 · 119,80** |
| sous-pas | 120,00 /s | **119,87 · 119,80 · 119,80 · 120,00** |
| sous-pas par image | 1,000 | **1,000** |

Physique inchangée : arc balistique **identique sur 90 intégrations** entre 30
et 120 FPS, 42 intégrations jusqu'au sommet, sommet à 225,75 — les mêmes
valeurs qu'aux paliers 30 et 60 de la session 3. Chute libre de 3000 unités en
**1,656 s** contre 1,655 s relevées à 30 FPS en session 2, soit **0,06 %**.
Le compte d'intégrations relevé est 199 contre 198 : une unité d'écart sur un
détecteur de bord, pas une différence de physique.

**Le `[Gecko]` de Dolphin n'a pas chargé.** Le profil livrait d'abord les deux
écritures de cadence en section `[Gecko]`, sur le modèle du `$60FPS` de
`gamemasterplc`. Jeu démarré, `0x80001800` était **entièrement nul** : aucun
codehandler injecté, aucun code actif — alors que la section `[Core]` du
*même fichier* avait bien pris effet, `EnableCheats = True` étant par ailleurs
posé globalement. Cause non élucidée.

État intermédiaire observé, et instructif : **VI à 2× sans correctif côté jeu
= jeu à double vitesse**. C'est la ligne du tableau de `deliver/README.md` qui
n'était jusque-là que déduite.

Contournement retenu : les écritures de données, éprouvées depuis la session 2.
→ [`adr/0005-gecko-ou-donnees.md`](adr/0005-gecko-ou-donnees.md)

**Deux défauts visuels signalés, une seule cause.** Jets d'eau de la place
figés ; animation de rétrécissement à l'entrée d'un graffiti absente — « il
saute et disparaît ». Les deux sont du JPA, et la cause est exacte :

```
802887A4  bl SMSGetAnmFrameRate()        ; 60 / horloge logique
802887A8  fctiwz f0, f1                  ; troncature vers l'entier
802887B0  lwz    r23, 0x94(r1)           ; compteur de boucle
802887B8  bl     JPAEmitterManager::calc()
802887C0  addi   r23, r23, -1
802887C8  bgt    802887B8
```

Le nombre d'appels à `JPAEmitterManager::calc()` par image rendue vaut
`(int)SMSGetAnmFrameRate()` : **2** à 30 FPS, **1** à 60, **0 à 120**. Le
système de particules n'avance plus du tout. `TMario::warpInEffect()` passant
entièrement par `gpMarioParticleManager` (`emitAndBindToMtx`, callback
`TWarpInCallBack`), le « petit rond » est émis mais jamais avancé, donc
invisible.

C'est le seul point où la valeur 0,5 de `SMSGetAnmFrameRate()` casse : partout
ailleurs elle est consommée en flottant, et 0,5 y est **correct**.

**BetterSunshineEngine ne corrige pas ce point.** Son `src/patches/fps.cpp`,
récupéré et relu, ne mentionne ni JPA ni le gestionnaire de particules, et son
`case FPS_120` ne pose que `mRetraceCount = 0`, `0x804167B8 = 2.0f` et
`0x80414904 = 0.04f`. **Son mode 120 FPS a donc le même défaut.**

**Un cumul dangereux, trouvé avant de le subir.** Le `nop` de `0x802FCB24` et
`mRetraceCount = 1` mènent tous deux à un champ par image, mais ils
s'additionnent : `count - 1` avec le `nop`, soit **zéro** champ, donc plus
aucune attente de balayage. `keep120.py` et `validate_120.py` lisent désormais
`0x802FCB24` avant de décider du compte.

### Ouvert

- **Le correctif des particules n'est pas vérifié.** `0x802887B0 → li r23, 1`
  est posé en section `[OnFrame]` du profil, mais **le jeu n'a pas été
  redémarré** : la session s'est arrêtée là. Deux inconnues d'un coup — le
  correctif fonctionne-t-il, et le `[OnFrame]` de Dolphin s'applique-t-il là où
  le `[Gecko]` a échoué. Si `[OnFrame]` passe, le profil tient en un seul
  fichier et `keep120.py` devient optionnel.
- **Ce correctif est une compensation imparfaite, et assumée comme telle.**
  Forcer le compteur à 1 fait avancer les particules à 120 Hz au lieu des 60
  d'origine : deux fois trop vite. Le correctif exact demande un appel une
  image sur deux, donc un état, donc un hook ASM. C'est la seule ligne du
  profil qui ne soit pas correcte par construction.
- **Pourquoi `[Gecko]` n'a pas chargé.** Première piste à vérifier : la case
  « Enable Cheats » dans la configuration de Dolphin, qui conditionnerait le
  codehandler sans conditionner `[Core]`.
- **L'audio n'a pas été jugé.** L'instrumentation lit la mémoire, elle n'entend
  rien. L'overclock VI scale l'horloge CPU émulée et la période de l'AudioDMA
  en dérive ; le plan de départ affirme que le son n'est pas affecté, ce reste une
  affirmation.
- **Le coût hôte n'est pas caractérisé.** Une mesure sur quatre a relevé
  87,5 images/s au lieu de 119,8 — et à 87,5 images la simulation tombe à
  72,9 % de la vitesse correcte, c'est-à-dire que **le jeu ralentit pour de
  bon**. Les trois mesures suivantes sont revenues à 119,8. À-coup non expliqué.
- **Le reste de l'inventaire « ce qui casse quand même » est intact** : boss
  anguille, minuteurs de dialogue, transitions HX, `TSMSFader`, écran de
  sélection des Shines, boucles de chargement.
- **Anomalie `0x80414904`** — inchangée, toujours absente du profil.
- **Classement des listes de perform (0.C)** — inchangé.
- **Hooks ASM non analysés** : `0x800066EC` (`TBoidLeader`) et `0x80C28028`.

### À refaire au redémarrage de l'outillage

`keep120.py` tournait en tâche de fond et s'arrête avec le terminal. Après
redémarrage du jeu, relancer :

```sh
python tools/validate_120.py      # attend le jeu, puis rend un verdict
python tools/keep120.py           # seulement si [OnFrame] ne s'est pas appliqué
```

### Addendum, même session — `[OnFrame]` s'applique, profil en un seul fichier

Le jeu a été redémarré avant la fin de la session. Les trois écritures du
profil sont en mémoire, relues une à une :

| Adresse | Valeur lue | Attendu |
|---|---|---|
| `0x804167B8` | `40000000` | `2.0f` |
| `0x802FCB24` | `60000000` | `nop` |
| `0x802887B0` | `3AE00001` | `li r23, 1` |

`mRetraceCount` vaut **2**, sa valeur NTSC d'origine : le `nop` porte à lui
seul la présentation par champ, et `keep120.py` le détecte et s'abstient.

Validation complète : **119,83 images/s, simulation à 120,00 Hz, soit 100,0 %
de la vitesse correcte.**

Trois conséquences :

1. **Le `[OnFrame]` de Dolphin s'applique là où le `[Gecko]` a échoué.** Le
   PatchEngine écrit avant que le JIT ne compile le bloc, ce qui permet de
   patcher une *instruction* — impossible par écriture externe à chaud.
   La cause de l'échec du `[Gecko]` reste inconnue, mais elle n'est plus
   bloquante.
2. **Le profil tient en un seul fichier** et `keep120.py` devient optionnel :
   filet de sécurité, plus mécanisme principal.
3. **Le cumul dangereux ne s'est pas produit**, la garde ajoutée juste avant
   ayant fonctionné du premier coup en situation réelle.

Bogue d'outillage corrigé au passage : `keep120.py` mourait sur `RuntimeError`
quand le jeu s'arrêtait, au lieu de se rattacher. Il attend maintenant le jeu,
survit à un redémarrage et se reprojette sur la nouvelle MEM1.

**Reste à vérifier à l'œil** : que les jets d'eau et l'animation d'entrée de
graffiti soient effectivement revenus, et à quel point les particules
paraissent deux fois trop rapides.

## Session 6 — 2026-09-22 — jets deux fois trop rapides, musique figée

Retour à l'œil et à l'oreille de l'auteur, profil de la session 5 appliqué :
**les jets d'eau sont deux fois trop rapides** (attendu : c'était la
compensation `li r23, 1`) et **la musique de la place ne boucle pas, puis plus
de musique du tout**.

### Musique — relevé en mémoire, jeu en cours

| Grandeur | Valeur lue | Lecture |
|---|---|---|
| `MSBgm::smBgmInTrack[0]` → handle | `JAISound` son `80010001`, état 4 | JAI la croit en lecture |
| `JAISeqParameter+0x04` (tempo JAI, courant) | 1.0 | JAI demande un tempo normal |
| racine JASystem 1, `TTrack+0x3B0` (tempo effectif) | **0.0** | racine 0 : 0.2398 |
| racine 1, `TOuterParam+0x18` (multiplicateur) | **0.0**, commutateur `0x40` levé | racine 0 : 1.0 |
| minuteurs des 6 pistes filles | identiques à 2 s d'écart | la racine 0 décompte |

Le tempo demandé par JAI n'a jamais atteint le lecteur : multiplicateur resté à
sa valeur d'initialisation 0.0, tempo effectif nul, séquence figée — muette, et
donc jamais revenue au début.

`MSound::mainLoop` — seul appelant de `JAIBasic::startFrameInterfaceWork` —
est appelé une fois par image par `TApplication::gameLoop()+0x38C`. Le compteur
`JAISound+0x14`, incrémenté à chaque passage, avance à **~120/s** : la couche
JAI tourne quatre fois plus vite qu'à l'origine.

**Hypothèse, non démontrée** : à 120 Hz, JAI enchaîne démarrage de séquence et
transmission des paramètres plus vite que le fil audio ne les consomme, et la
transmission du tempo se perd. Cohérent avec le relevé, pas prouvé par lui.
Indépendamment de la cause exacte, tous les fondus JAI sont comptés en images
et tournaient 4× trop vite.

### Correctifs — deux routines à état

`tools/build_caves.py` assemble deux routines en `0x80002F00` (zone du
codehandler Gecko, relevée entièrement nulle en jeu) et émet leurs lignes
`[OnFrame]` :

- **particules**, `0x802887B0 → bl 0x80002F10` : accumulateur
  `acc += SMSGetAnmFrameRate()`, un appel à `JPAEmitterManager::calc()` par
  unité entière. 2 / 1 / « 0 puis 1 » — 60 appels/s à tous les paliers.
  Correct par construction ; remplace la compensation.
- **audio**, `0x802A62DC → bl 0x80002F50` : `MSound::mainLoop` n'est appelé
  que toutes les `2 × littéral(0x804167B8)` images — 1 à 30 FPS et en PAL,
  2 à 60, 4 à 120. La couche JAI retrouve ses 30 Hz d'origine.

Encodage relu au désassembleur (Capstone) et cibles des deux `bl` recalculées
à la main. **Rien n'est encore mesuré en jeu** : le profil est réinstallé, le
jeu doit redémarrer.

Conséquence à connaître : la zone choisie est celle du codehandler Gecko —
**activer des codes Gecko pour GMSE01 écraserait les routines**.

### À faire au redémarrage

```sh
python tools/watch_audio.py 600
```

Relit les 29 mots, mesure la cadence JAI (attendu ~30/s) et signale toute
séquence figée. Détecteur éprouvé avant correction : il marque bien la racine 1
figée. Restent à juger à l'œil et à l'oreille : vitesse des jets, entrée de
graffiti, bouclage de la musique de la place.

### Addendum — portail graffiti infranchissable

Jeu redémarré avec les routines : `watch_audio.py` relève 29/29 mots, cadence
JAI **30,0/s**, aucune séquence figée ; accumulateur particules observé en
alternance 0,0 / 0,5. Nouveau signalement de l'auteur : **impossible d'entrer
dans le portail**.

Relevé sur les trois `TModelGate` de la place (vtable `0x803D3F9C`) : Mario à
845 unités du premier, jauge `+0xD0` **alternant 0,00 / 0,01**, compteur
d'ouverture `+0xCA` à 0. La jauge gagne 0,01 par **sous-pas** et perd `+0xD8`
= 0,02 par **image rendue** tant que le portail est fermé :

| Cadence | gain/s | perte/s | net |
|---|---|---|---|
| 30 | 1,2 | 0,6 | +0,6 — ouvert en ~1,7 s |
| 60 | 1,2 | 1,2 | 0 — jamais |
| 120 | 1,2 | 2,4 | −1,2 — jamais |

**L'anomalie `0x80414904` (§ 4.3) est tranchée** : le 0,01 → 0,02 / 0,04 de
`gamemasterplc` et BSE compense ce décrément par image, au prix d'une ouverture
2× / 4× trop rapide. Ce n'était ni un choix esthétique ni une erreur de signe,
mais un mécanisme invisible depuis le seul site d'usage.

Correctif : `0x801EC29C`, le chargement de `+0xD8` dans `TModelGate::loadAfter`,
vise `0x80414104` = 0,005f (constante préexistante, lue sinon par `TLeanBlock`
seul). Net +0,6/s, la dynamique d'origine. `+0xEC`, autre copie du 0,02, part
dans `gpAfterEffect+0x50` et n'est pas touché, faute de savoir si c'est une
vitesse. Portails déjà chargés corrigés en direct (`+0xD8` = 0,005).

**Non mesuré** : la montée de la jauge après correction — Mario était loin des
portails au moment de l'écriture. Restent 4× trop rapides, cosmétiques :
fermeture `+0xDC`, lissage du flou `+0xE8`, durée d'ouverture `+0xC8`.

### Addendum — son de glissade sur l'eau absent : test A/B

Interrupteur de diagnostic ajouté à la routine audio : `0x80002F0C` non nul =
`MSound::mainLoop` à chaque image (jamais écrit par le profil ; basculable à
chaud). Résultat à l'oreille de l'auteur : **son absent en mode A (JAI 30 Hz),
présent en mode B (JAI 120 Hz)**. La limitation à 30 Hz est en cause.

Relevé comparé des SE (45 s par mode, glissades continues) : le son `0x1969`
(catégorie 1, bit `0x800`, ~170 ms) démarre 6 fois en B, **1 fois en A**. Aucun
`li` ne le charge : l'id vient des données d'animation, c'est un son de
`JAIAnimeSound`. Pourquoi ses déclenchements se perdent à 30 Hz n'est pas
démontré.

Conséquence : la limitation globale est trop grossière. En cours : vérifier si
la musique se fige réellement en mode B (surveillance 10 min) avant de
concevoir une limitation limitée aux séquences.

### Addendum — limitation audio retirée

Mode B (JAI à 120 Hz, interrupteur `0x80002F0C` = 1) : **la musique de la
place boucle normalement**, à l'oreille de l'auteur ; son de glissade présent.
La limitation à 30 Hz n'est donc pas nécessaire au bouclage, et elle casse des
sons d'animation : **retirée du profil** (`build_caves.py` ne génère plus que la
routine particules ; `0x802A62DC` n'est plus patché).

Le gel du premier essai reste **inexpliqué** : un seul occurrence observée,
sous JAI à 120 Hz, non reproduite depuis. `watch_audio.py` le détecte.
L'hypothèse « JAI à 120 Hz perd la transmission du tempo » n'est ni confirmée
ni écartée : une boucle correcte ne prouve pas l'absence de course.

### Addendum — musique des égouts figée : cause trouvée

Signalement : pas de musique dans les égouts. Relevé en direct : son
`8001001B`, piste MSBgm 2, racine JASystem 2 **figée**, multiplicateur de tempo
0.0 — même symptôme que le premier gel, **sans** limitation audio (JAI à
120 Hz). Le gel est donc réel et indépendant de la routine retirée.

Mécanisme, lu dans Graffito-Decomp et confirmé dans le DOL :

1. `JAISystemInterface::outerInit` (fil audio, rappel de début de séquence)
   remplit les arguments de port de la racine, drapeaux `0xff` (tempo = bit
   `0x80`), puis `addPortCmdOnce`.
2. `JAIBasic::checkPlayingSeq` (fil du jeu, chaque passage JAI) écrit les
   drapeaux du moment par **écrasement** (`setSeqPortargsU32` : `stw`), efface
   le marqueur « en file » de la commande (`0x80307CF0`), puis la rechaîne.
3. Si le rappel audio (`portCmdMain`) n'a pas encore consommé la commande, le
   bit tempo est perdu ; `setPortParameter` n'applique que les bits présents.
   Le multiplicateur reste à sa valeur d'initialisation 0.0.

À 30 Hz la fenêtre est rarement atteinte ; à 120 Hz, souvent. Même motif dans
`sendSeAllParameter` (`0x8030669C`).

Correctif (`build_caves.py`, routine `0x80002F40`) : fusion des drapeaux si la
commande est en file, écrasement sinon, MSR.EE masqué ; effacements du
marqueur remplacés par `nop`. Encodage relu ; **non mesuré en jeu** (profil
réinstallé, redémarrage requis). `watch_audio.py --suivi` ajouté : surveillance
longue, multi-niveaux, qui journalise chaque musique et chaque gel dans
`work/suivi_audio.log`.

## Session 6, suite — 2026-09-23 — passe complète : animations, transitions, effets sonores

Demande de l'auteur : régler d'un coup musiques, effets sonores et animations.

**Portage de l'inventaire BetterSunshineEngine** (`src/patches/fps.cpp`, cloné
et relu), en cinq groupes analysés en parallèle, un module par groupe dans
`tools/fixes/`, chacun avec sa zone de grotte et la même convention : facteur
M = 2 × littéral `0x804167B8`, lu à l'exécution (1 à 30 FPS, 4 à 120).

| Module | Mots | Contenu | Écarts avec BSE |
|---|---|---|---|
| `hx.py` | 179 | transitions HX : Circle, GameOver, Test1/2/2R/4/5, HX_MotionUpdate | + 7 compteurs de Circle ; durée du 1er rebond GameOver (oubli BSE) ; Test5 sans état ; logo laissé d'origine |
| `fader.py` | 34 | TSMSFader : durée, délai, taux capturé à l'amorçage | taux +0x14 **mesuré à 120.0** dans le jeu en cours → épinglé à 30, M appliqué ailleurs |
| `menus.py` | 61 | sélection des Shines (rotation, alpha, TCoord2D), minuteur de dialogue | 7 autres `setValue` repérés, non corrigés |
| `actors.py` | 60 | boids (+ meneur, absent de BSE), oiseaux (+2 sites), anguille 19 sites, TJointCoin, Petey | TJointCoin 2,5/(4+M) (BSE 6,7 % trop haut à 120) ; FireWanwan **désactivé** : le filtre BSE figerait la queue 3 images sur 4 |
| `contexts.py` | 43 | 30 FPS forcé au boot, logos, intro, boucles de chargement ; QFSync | `mRetraceCount` = 5 (et non 2) à cause du `nop` ; le littéral n'est plus écrit par [OnFrame] |

**Effets sonores, passe générique :**

- *Défaut systémique trouvé* : tous les acteurs passent à `MAnmSound::animeLoop`
  la vitesse d'animation (`J3DFrameCtrl+0xC`), 2,0 à 30 FPS et 0,5 à 120 FPS ;
  `JAIAnimeSound` en tire la hauteur (`base + k(v−1)/32`) et le volume
  (`base + 2v'(v−1)`) de chaque son d'animation. À 120 FPS ils sortaient plus
  graves et moins forts. Corrigé en un point (`0x80012E9C`, vitesse × M).
- *Mesure générique* : journal de tous les démarrages de sons, posé à l'entrée
  unique `JAIBasic::startSoundBasic` (anneau `0x80002C00`), et interrupteur
  « 30 FPS partout » (`0x80002BFC`). `tools/watch_se_rates.py ab` compare la
  fréquence de chaque son aux deux cadences et signale tout rapport hors
  [0,5 ; 2].

**Bogue d'outillage** : Keystone calcule faux tous les branchements qui suivent
un `slwi` dans le même bloc (cible `0x80304B04` au lieu de `0x803020B0`).
Remplacé par `rlwinm`. `tools/build_profile.py` assemble désormais tout le
profil et bloque sur : conflit d'adresse, écriture identique au DOL,
branchement vers une cible ni écrite, ni symbole, ni retour de site.

Profil : **426 lignes**, installé. **Rien de cette passe n'est encore mesuré en
jeu.**

### Addendum — jeu à 2 FPS au menu de sélection de sauvegarde

Premier démarrage avec la passe complète : transition au ralenti, menu à ~2 FPS
à l'œil. Relevé : contexte 5, littéral 2.0, `mRetraceCount` 2 — réglages
corrects — mais **14,3 champs VI/s pour 14,3 images/s** : 1,00 champ par image,
le jeu tient sa cadence ; c'est **l'émulation** qui tourne à 12 % de sa vitesse.

Cause probable (non démontrée) : le PatchEngine réécrit chaque ligne
[OnFrame] à chaque champ et invalide le code JIT à l'adresse écrite ; 426
lignes, dont beaucoup en code chaud, font recompiler en permanence. Invisible
avec la trentaine de lignes précédente.

Correctif : lignes **conditionnelles** `adresse:dword:valeur:comparant`
(syntaxe utilisée par les INI livrés avec Dolphin, vérifié dans
`Sys/GameSettings`). Comparant = mot d'origine du DOL, ou 0 en grotte : chaque
ligne s'applique une fois, puis plus jamais. 425 lignes (un mot nul de grotte
omis). À mesurer au redémarrage.

### Addendum — retour au profil sain

Avec les lignes conditionnelles, le jeu ne démarre toujours pas correctement
(signalement de l'auteur). **Retour immédiat au profil de base éprouvé** :
31 lignes inconditionnelles — littéral, `nop`, portail, particules, drapeaux
JAI — celui avec lequel la musique des égouts a été confirmée.
`build_profile.py` accepte désormais `--modules` et `--inconditionnel`.

Cause du ralentissement **non établie** : les lignes conditionnelles n'ont pas
suffi, donc l'hypothèse « invalidation JIT » n'est ni confirmée ni exclue, et
un module peut être en cause. Les modules de la passe complète ne seront
réintroduits qu'un par un, chacun testé en jeu.

## 2026-09-26 — Session 7 : passe audio, un correctif à la fois

Demande de l'auteur : reprendre musiques, effets sonores et effets ; **ne pas
toucher** aux cinématiques ni aux effets d'écran des chargements (fondus au
noir). Les modules `hx`, `fader`, `contexts` de la passe complète sont donc
écartés ; `menus` et `actors` restent en attente.

### Analyse — la couche son compte en passages, et passe 4× plus souvent

JAI tourne à 120 passages/s depuis le retrait de la limitation (session 6).
Tout ce qu'elle compte en passages s'écoule 4× trop vite. Relu dans
Graffito-Decomp puis dans le DOL :

| # | Mécanisme | Effet à 120 FPS | Correctif |
|---|---|---|---|
| 1 | `JAIMoveParaSet`, compteur décrémenté par passage ; durées posées par `initMoveParameter` et les 5 `setSeInter*` | fondus de musique, changements de tempo (`MSModBgm::changeTempo` 5 / 20), atténuation de la musique sous certains sons, fondus croisés, fondus de sortie des SE : **4× trop courts** | `fades.py`, **installé** |
| 2 | `MSSetSoundTL::frameLoopDyna` : horloge `+0x54` et verrou « un départ par passage » `+0xB8` des 9 jeux de sons (impact du jet de FLUDD, nettoyage de graffiti, goop, colonnes de feu / électriques, séchage, cri de la raie) — intervalle minimal, durées de modulation, continuité en passages | ces sons repartent jusqu'à **4× plus souvent** | à faire : n'exécuter `frameLoopDyna` qu'un passage sur M |
| 3 | `MSModBgm::loop` : compteur +1 par passage, seuils 5 et 180 (musique qui ralentit et s'éteint) | effet **4× trop court** (1,5 s au lieu de 6) | à faire : même garde |
| 4 | Doppler (`setPositionDopplarCommon`) : déplacement relatif **par passage** | décalage de hauteur **4× trop faible** ; transition `dopplarMoveTime` 4× trop courte | à faire : `dopplarParameter` ÷ M, et durée inlinée × M |
| 5 | sons d'animation : vitesse `J3DFrameCtrl+0xC` transmise à `JAIAnimeSound` | hauteur et volume modulés comme à vitesse 0,5 au lieu de 2 | `sound.py` partie 1 (session 6), à réintroduire seul |

Vérifiés sans défaut : `MSMainProc::entranceDemoLoop` est vide (`blr`) en
GMSE01 ; la liste des tampons de position fictifs (`checkDummyPositionBuffer`)
n'est jamais alimentée (`getDummyVecPointer` vide) ; le compte à rebours de
maintien des SE en boucle (`JAISound+0x2`, 10 passages) est rafraîchi au
même rythme qu'il décroît, une fois par image.

### Correctif 1 — durées des fondus (`tools/fixes/fades.py`)

Durée (`r5`) multipliée par M à l'entrée des six fonctions ; M tiré de
l'exposant du littéral `0x804167B8` (`décalage = exposant − 126`, sans
flottant). 26 mots de routine en `0x80002E40`, 6 sites. Encodage relu à
Capstone ; `build_profile.py` : aucun conflit, branchements résolus. Profil
« base + fades » **63 lignes inconditionnelles**, installé. Profil de base
copié dans `work/GMSE01.base.ini` (identique à la régénération
`--modules none --inconditionnel`, vérifié par `diff`).

`tools/watch_fades.py` chronomètre en jeu chaque fondu de la musique de fond
(compteur N, durée réelle). **Rien n'est encore mesuré en jeu.**

### Correctif 1 — mesuré en jeu : validé

Jeu redémarré par l'auteur. Profil 63/63 mots en place ; 120,00 images/s sur
deux mesures (un premier relevé à 99,75 était concomitant de
`watch_audio.py`, non reproduit) ; JAI 120,0 passages/s ; aucune séquence
figée. Pauses répétées, `watch_fades.py` :

| Fondu (appelant, durée d'origine) | N relevé | durée réelle | d'origine à 30 Hz | sans correctif |
|---|---|---|---|---|
| `pauseOn` : musique → 0, 60 passages | 239 | **1,996 s** | 2,000 s | 0,50 s |
| `pauseOff` : → 1,0, 10 passages | 39 | **0,328 s** | 0,333 s | 0,08 s |
| volume 1,0 → 0,48, 30 passages (appelant non identifié) | 120 | **0,993 s** | 1,000 s | 0,25 s |
| 0,48 → 1,0, 15 passages | 60 | **0,493 s** | 0,500 s | 0,13 s |

N relevé = 4 × durée d'origine (à un passage près, manqué entre deux
lectures). Quatre fondus `pauseOn` mesurés plus courts (1,14–1,50 s) : pause
quittée avant la fin — `pauseOff` réarme le même `JAIMoveParaSet` sans passer
par 0, l'outil fond les deux en un seul relevé. Pas d'anomalie.

### Correctif 2 — jeux de sons FLUDD (`tools/fixes/soundsets.py`)

`frameLoopDyna` (MSSetSound 0x8001604C, MSSetSoundGrp 0x80016014) n'est
exécutée qu'un passage JAI sur M, phase lue sur `JAIBasic::basic+0x20`
(0x8040E430 ; compteur incrémenté par `processFrameWork` 0x80301D84, relevé
**119,99/s**, après les frameLoopDyna du passage). Vtables relues : entrée
+0x14 de 0x803AC6F0/0x803AC708 → 0x8001604C, de 0x803AC6A8/0x803AC6C0 →
0x80016014. Routine GATE + 2 stubs, 26 mots en 0x80001C00 (zone relevée
nulle en jeu). Profil « base + fades + soundsets » : **91 lignes**, installé,
en attente de redémarrage.

`tools/watch_soundsets.py` : cadence de l'horloge `+0x54` de chaque jeu
pendant son activité — attendu ~120/s avant, ~30/s après.

### Correctif 2 — complété avant tout test : l'âge du son précédent

Relecture de `startSoundSetDyna` (Graffito-Decomp `MSoundStruct.cpp`, puis
DOL) : la cadence de répétition ne dépend **pas** de l'horloge `+0x54` mais de
l'**âge du son précédent**, `JAISound+0x14`, incrémenté à chaque passage JAI.
Il est comparé à l'intervalle minimal, à la durée unitaire, aux seuils de
groupe, à la durée de modulation et à l'écart de continuité. Pour l'impact du
jet (0x6800), l'écart de continuité vaut 0 : `+0x54` n'y est jamais actif.
La garde de `frameLoopDyna` seule aurait laissé le défaut principal en place.

Ajout à `soundsets.py` : les 4 lectures `lwz rD, 0x14(rA)` de chaque instance
(MSSetSound 0x8001B504 / B66C / B750 / B8A4, MSSetSoundGrp +0x9D0) sont
suivies de `srw rD, rD, log2(M)`. Fonctions non feuilles (LR sauvé au
prologue, `mtlr r0` depuis la pile), `r11`/`r12` absents de tout le listing.
Profil : **136 lignes** (`--modules fades,soundsets --inconditionnel`),
installé, en attente de redémarrage.

Relevé avant correctif (profil base + fades, jeu en cours) : horloge `+0x54`
du jeu de sons 0x804 (séchage) **120,14 /s** pendant son activité —
attendu 30 dans le jeu d'origine.

Relevé avant correctif, 60 s de jeu libre (geste non contrôlé) : 0x6800
impact du jet 129 départs, 0x804 séchage 206 départs (horloge **119,89 /s**
sur 48,7 s d'activité), groupe 74, 0x6801 6. Le nombre de départs dépend du
geste : `watch_soundsets.py` relève désormais aussi l'**écart** entre départs
consécutifs, indépendant du geste (attendu, calculé et non mesuré, pour
0x6800 : 58–108 ms sans correctif, 233–433 ms avec).

### Écran large 16:9 — code Gecko converti (`tools/fixes/widescreen.py`)

Demande de l'auteur : ajouter le code écran large au profil 120. Source : code
« Widescreen [gamemasterplc] » du `Sys/GameSettings/GMSE01.ini` de Dolphin,
recopié à l'identique. [Gecko] ne charge pas ici, et son gestionnaire
écraserait nos routines (même zone) : conversion en [OnFrame] — 12 écritures
`04` directes ; 12 insertions `C2` posées en 0x80001E00–0x80001F17 (zone
relevée nulle en jeu), dernier mot remplacé par le retour, site remplacé par
un saut. Vérifié dans le DOL : aux 12 sites, l'instruction d'origine figure
dans le bloc ; littéraux visés 600.0 (→ 800 / 700) et 4/3 en 0x80412408
(→ 16/9). 95 mots. Profil `--modules fades,soundsets,widescreen
--inconditionnel` : **231 lignes**, installé, en attente de redémarrage.
Repli sans écran large : `work/GMSE01.fades-soundsets.ini`.

Le correctif 2 tourne depuis le dernier démarrage : 136/136 mots en place,
119,67 images/s ; l'auteur, à l'oreille : « je trouve déjà ça bien mieux ».
Mesure des écarts entre départs de son pas encore faite (Dolphin fermé par
l'auteur pendant la mesure, pour installer un pack de textures).

### Écran large — confirmé en jeu par l'auteur (image en 16:9).

### Question de l'auteur : l'effet de chaleur de la place est-il accéléré ? — Non.

Objet : `TShimmer` « 陽炎 » (Graffito-Decomp `src/Map/Shimmer.cpp`), vtable
0x803C1F70, instance en jeu 0x81115554. Son animation de texture (BTK) avance
par son propre `J3DFrameCtrl` (+0x58) de **1,0 par appel** de `perform` avec
le drapeau 0x1 — vitesse non liée à `SMSGetAnmFrameRate`.

Inscription relevée en mémoire (maillons `TPerformLink {suivant, objet,
filtre}`, décomp. `System/PerformList.hpp`) : l'objet est dans le groupe
« インダイレクトシーン » (0x81115508), lui-même dans les listes du directeur :

| Liste | Filtre du groupe |
|---|---|
| `+0x24` GXPost | 0x40000008 |
| `+0x28` **Movement** | **0x40003001** — seul porteur du bit 0x1 |
| `+0x2C` CalcAnim | 0x40000002 |
| `+0x34` | 0x40000204 |

`direct()` exécute `+0x28` dans le corps du sous-pas (0x80299B54), drapeaux
`~r27` : le bit 0x1 passe à chaque sous-pas. D'où 120 pas d'animation par
seconde **aux deux cadences** — 4 par image à 30 FPS, 1 par image à 120.
Mesuré à 120 FPS : **119,96 trames d'animation/s** pour 120,00 images/s.
Vitesse d'origine ; la différence perçue tient à la fluidité (à 30 FPS l'effet
sautait de 4 trames par image).

Première inscription d'un objet dans une liste établie par relevé : la
méthode (parcours des `TPerformList`, compte `+0x10`, tête `+0x14`) répond au
« Non vérifié » de `01-mecanismes.md` § 1.3 pour n'importe quel objet.

### Correctif 2 — mesuré en jeu : validé

Profil 231 lignes (fades + soundsets + widescreen), arrosage continu 30 s,
`watch_soundsets.py 30` :

| Jeu de sons | départs | écart min | écart médian | horloge +0x54 | attendu (calcul) |
|---|---|---|---|---|---|
| 0x6800 impact du jet | 106 | **233 ms** | 269 ms | inactive | 233–433 ms (7 + aléa 0–6 passages à 30 Hz) ; sans correctif 58–108 ms |
| 0x804 séchage | 344 | 17 ms | 83 ms | **29,90 /s** | horloge 30 /s (avant : 119,89) |
| groupe | 15 | 575 ms | 711 ms | inactive | — |

L'écart minimal du son d'impact tombe exactement sur la valeur d'origine
(7 passages à 30 Hz = 233 ms). Pour 0x804, l'écart minimal de 17 ms est sous
le verrou d'un départ par passage à 30 Hz (33 ms) : limite de l'outil —
`time.sleep` sous Windows a une granularité de ~15,6 ms, les écarts relevés
sont quantifiés à ±16 ms. Médiane seule significative ; pas de relevé
d'écarts avant correctif pour ce son (outil ajouté après). Oreille de
l'auteur : « bien mieux ».

### Correctif 3 — sons d'animation (`tools/fixes/sound.py`, partie 1 seule)

Demande de l'auteur : sons d'animation puis Doppler. Installés **un à la fois**
(règle du projet). Site relu : `MAnmSound::animeLoop` 0x80012E9C `bl
setAnimSoundVec`, vitesse en `f2` transmise sans transformation. Le journal de
diagnostic sur `startSoundBasic` n'est plus posé par défaut
(`build(with_log=False)`). Ajout d'une sonde : la vitesse transmise est
recopiée en 0x80002A30 (f32, état) — attendu 2,0 pour une animation à vitesse
normale, 0,5 sans correctif. Profil `fades,soundsets,widescreen,sound` :
**239 lignes**, installé. Repli : `work/GMSE01.fades-soundsets-widescreen.ini`.

### Correctif 4 — Doppler (`tools/fixes/doppler.py`) : prêt, NON installé

`dopplarParameter` 3200 → 800 (donnée, suppose M = 4) ; transition inlinée de
`setSePositionDopplar` (0x8030C730) : `r31 <<= log2(M)`. `dopplarMoveTime`
n'est PAS modifié en donnée : sa lecture côté séquences passe déjà par
`initMoveParameter`, que fades.py multiplie. `r12` non lu après 0x8030C6EC
dans la fonction (listing). Profil complet à blanc : 248 lignes, contrôles
passés.

### Correctif 5 — Petey Piranha (`tools/fixes/petey.py`)

Signalement de l'auteur : « Petey vomit direct, pas le temps de remplir son
estomac ». Cause relue dans le DOL : `TBossPakkun::changeBck` écrase, pour
l'animation 0x15 seule, le débit correct par un paramètre brut (0x800955CC),
et `TNerveBPVomit::execute` règle toute la phase de vomissement sur cette
animation (trames 25–165, fin d'animation) : phase 4× trop rapide à 120 FPS.
Correctif = groupe 5 de actors.py extrait seul (mêmes 7 mots, vérifié
identique) : débit stocké divisé par M. Installé avec le correctif 3 — le code
n'est exécuté que pendant le combat, l'attribution d'un défaut reste donc
univoque. Profil `fades,soundsets,widescreen,sound,petey` : **246 lignes**.

### Correctif 5 — Petey : validé par l'auteur (« parfait pour Petey »).

### Correctif 3 — sons d'animation : prémisse fausse pour Mario, corrigée

Retour de l'auteur : pas et sauts **trop aigus**, plus de graves. Sonde :
vitesse transmise 2,0 (1551 relevés sur 5 s). Or `TMario::setAnimation`
fixe le débit de Mario à la **constante 0,5** (0x80247958 `lfs f0` ←
0x80415A94 = 0,5 ; 0x80247968 `stfs f0, 0xC(r3)`) : son animation avance par
sous-pas, et il transmettait déjà 0,5 dans le jeu d'origine à 30 FPS. La
prémisse de la session 6 (« tous les acteurs passent ~SMSGetAnmFrameRate »)
était une déduction non vérifiée, fausse pour Mario ; le ×M le poussait à 2,0.

Correction : la routine lit l'adresse de retour de l'appelant d'animeLoop
(0xC(r1), d'après le prologue `stw r0,4(r1)` / `stwu r1,-8(r1)`) et ne
multiplie pas si c'est TMario::animSound (0x80285824). Autres appelants
toujours multipliés ; débit issu de SMSGetAnmFrameRate vérifié pour
TLiveActor seulement, **non vérifié** pour TYoshi, TKoopa, TCannonDom,
TChorobei, TTamaNokoFlower, TEnemyManager. Profil 246 → 251 lignes, installé.

### Correctif 3 — sons d'animation : validé par l'auteur (« c'est parfait pour les sons »).

### Question de l'auteur : bords de la goop en escalier — diagnostic, pas de correctif

Indépendant du framerate. Relevé en jeu (Bianco, 5 couches `TPollutionLayer`,
vtable 0x803C2160, modèle `+0x24`) :

- masque = texture 0 du modèle (`getTexResource`), **I8, 128×128 à 256×256**
  pour toute une zone ; filtrage **déjà linéaire** (`ResTIMG+0x14/+0x15` = 1/1)
  — d'où l'absence d'effet de « Forcer linéaire » de Dolphin (testé par
  l'auteur) ;
- matériaux (`J3DPEBlockFull`, vt 0x803E0968), tous identiques : alpha compare
  id 0x00C3 = **GEQUAL 0x80 AND LEQUAL 0xFF**, blend `00 01 00 03` = aucun
  (opaque) ;
- `initTexImage` adoucit déjà les texels de bord (profondeur − 50 × voisins
  vides, `TPollutionManager::mEdgeAlpha`).

Seuil à mi-hauteur sur un masque filtré : le contour est l'isoligne 0,5 de
l'interpolation bilinéaire, d'où les dents en biais à l'échelle du texel.
C'est la résolution du masque (conçue pour du 480p), pas un réglage. Mon
hypothèse précédente (seuil à 0 comme la couche sur l'eau) est **réfutée**
pour la goop au sol. Pistes, non engagées : bord fondu (blend + remappage
d'alpha dans le TEV, visuel seulement) ; masque d'affichage suréchantillonné
(lourd). Le MSAA/SSAA de Dolphin ne change pas la forme des dents.

### Correctif 4 — Doppler installé ; goop ajoutée au plan

Décision de l'auteur : on laisse la goop, installer le Doppler, ajouter la
goop au plan (plan de départ, section « Chantier hors framerate », en attente).
Profil `fades,soundsets,widescreen,sound,petey,doppler` : **260 lignes**,
installé. Repli : `work/GMSE01.sans-doppler.ini`. Non mesuré en jeu.

## 2026-09-27 — Session 8 : transitions d'entrée de niveau

Demande de l'auteur : cinématiques d'entrée de niveau trop rapides, fondus au
noir de sélection et d'entrée de niveau, sommeil de Mario trop précoce. Il
revient sur la décision de la session 7 (« ne pas toucher aux transitions »).
Sommeil de Mario : **retiré par l'auteur** (« j'ai juste extrapolé ») — la
décompilation le compte en boucles d'animation, par sous-pas, donc à vitesse
d'origine ; cohérent, non mesuré.

### Relevé — `tools/watch_transitions.py` (nouveau)

Échantillonne à ~500 Hz, horodaté en images par le compteur JAI
(`JAIBasic::basic` → +0x20 ; `0x8040E430` est le **pointeur**, pas le
compteur) : état du directeur, démo caméra, `TCameraBck`, `TSMSFader`, minuteur
HX `0x803F43FC`, Mario. Profil 260 lignes, entrée dans un niveau :

| Grandeur | Relevé à 120 FPS | Origine (30 FPS) | Verdict |
|---|---|---|---|
| Caméra de démo `TCameraBck` : débit / avance | **0,5 trame par image**, fin 479 | 2,0 par image | 60 trames/s : **correct** |
| Démo : restant `+0x14` | 960, −1 par image → 8,0 s | (479+1)×2 sous-pas → 8,0 s | **correct** |
| Volet HX de sortie (directeur 9) | 24 → 0 en 25 images = **0,21 s** | 25 images = 0,83 s | **4× trop rapide** |
| Volet HX d'entrée (directeur 1) | 29 → 0 en 30 images = **0,25 s** | 30 images = 1,00 s | **4× trop rapide** |
| `TSMSFader` durée / compteur | 120 / 121, **inchangés** pendant les volets | — | ces fondus passent par la branche HX |

La démo relevée a été interrompue à la trame 98 (état 1 → 3) — saut probable
par un bouton, non confirmé. La « cinématique trop rapide » perçue est donc,
d'après ce relevé, le volet HX qui l'ouvre, pas la caméra.

### Installé — `hx` seul

`--modules fades,soundsets,widescreen,sound,petey,doppler,hx --inconditionnel` :
**439 lignes** ; contrôles passés ; caverne 0x80001800–0x80001A44 relue nulle
en jeu avant installation. Repli : `work/GMSE01.avant-hx.ini` (260 lignes,
identique au profil installé jusque-là, vérifié par `diff`).

Risque connu : `hx` faisait partie de la passe à 426 lignes qui avait fait
tomber l'émulation à 14 champs/s (cause non établie). À surveiller au premier
démarrage : cadence, puis durée des volets (attendu 100 et 120 images).
`fader` (TSMSFader hors HX) et `contexts` restent **non installés**.

### `hx` au premier démarrage : volet sans fin, émulation à 13 champs/s — cause trouvée

Signalement : fondu de lancement « ultra saccadé », se referme et se rouvre
sans que le jeu parte, écran de sélection à ~2 FPS. Relevé en direct :
**13,0 champs VI/s pour 13,0 images/s** (même signature qu'en session 6),
minuteur HX `0x803F43FC` = 0x7FFFFxxx (saturation de `fctiwz`), volet actif
Hx_Circle (`0x80181AB4`), variable de travail `0x8000180C` restée à 0 — mais
**`0x8000000C` = 0x19** (= 25, la durée du volet) et `0x80000010` = NaN.

Bogue d'adressage dans `tools/fixes/hx.py` : les routines font
`lis r12, 0x8000` puis emploient MAGIC/SCR/SCR_LO/SCR2/T4STATE (0x00–0x18),
qui étaient des décalages **dans la cave** et non depuis 0x80000000. Elles
écrivaient dans l'en-tête disque et prenaient « GMSE01 » pour la constante de
conversion 0x4330000000000000 : durée convertie en ±∞, minuteur saturé, volet
qui ne finit jamais. Le coût d'émulation vient très probablement de ce volet
dessiné en continu avec des valeurs aberrantes — **non démontré**, à confirmer
par la cadence au prochain démarrage. `hx` faisait partie de la passe à 426
lignes de la session 6 : c'est le premier suspect sérieux de son effondrement
à 14 champs/s, **jamais élucidé jusque-là**.

Correction : déplacements rendus absolus depuis 0x80000000 (0x1800 + décalage).
Relu à Capstone : tous les accès `d(r12)` tombent en 0x80001800–0x8000181B.
Contrôle ajouté, passé sur les 12 sources (build_caves + 11 modules) : aucun
accès `d(rX)` sous 0x80001800 après `lis rX, 0x8000` — le détecteur signale
bien l'ancien motif. Profil 439 lignes réinstallé ; repli inchangé
(`work/GMSE01.avant-hx.ini`).

### `hx` corrigé : le jeu démarre, volets d'entrée de niveau validés par l'auteur

« Les cinématiques et les fondus d'entrée de niveau sont parfaits. » Restent
saccadés : le fondu au lancement du jeu et au retour sur la place (cercle).

### Cercle saccadé — cause trouvée : crochet HLE de Dolphin en 0x800018A8

`tools/watch_wipe.py` (nouveau : champs VI/s et images/s par quart de
seconde, minuteur et routine de volet). Tous les volets **Hx_Circle**
(`0x80181AB4`, cercle fermant, ~100 images = 25 × 4) tournent à
**8 champs/s pour 8 images/s** ; tous les volets `0x8017E46C` (entrée de
niveau) à 120. Avant `hx` (premier relevé de la session), les deux cercles
(25 et 30) tournaient à 120 : le coût vient de `hx`. Variables du cercle
relues après coup (rayon 0x8040DE2C, anneaux DE30–DE44, mouvement) : saines,
pas de NaN.

Cause : Dolphin pose, dans la zone du gestionnaire Gecko et **même sans code
Gecko**, le crochet HLE `GeckoCodehandler` en `Gecko::ENTRY_POINT` =
**0x800018A8** (et `GeckoHandlerReturnTrampoline` en 0x80002FFC). Exécuter une
instruction à cette adresse lance `HLE_Misc::GeckoCodeHandlerICacheFlush` :
incrément du mot 0x80001800 et **vidage complet du cache JIT**. La routine
`INT_STEP` de `hx` avait une instruction en 0x800018A8 (`lis r12, 0x8000`) ;
Hx_Circle l'appelle 3 fois par image (opacité des trois anneaux), Test5
jamais — d'où la différence entre volets. Source : code de Dolphin (HLE.cpp,
HLE_Misc.cpp, GeckoCode.h), cité de mémoire, **non relu dans cette session** ;
l'adresse et l'effet concordent avec le relevé.

C'est très probablement aussi la cause de l'effondrement à 14 champs/s de la
passe complète (session 6), `hx` y figurant avec la même disposition.

Correctif : code de `hx` déplacé en 0x800018B0–0x80001AD8 (0x8000181C–0x800018AF
laissés vides). `build_profile.py` refuse désormais tout mot en 0x800018A8 ou
0x80002FFC (contrôle éprouvé sur l'ancien placement). Profil 439 lignes
réinstallé.

Constaté au passage, **non corrigé** : les fondus `TSMSFader` ordinaires
(compteur +0x12, durées 48 et 120 images) s'écoulent en 0,4 s et 1 s, soit 4×
trop vite — relève du module `fader`, non installé.

### Cercle : validé par l'auteur (« c'est effectivement parfait »).

Profil 439 lignes (`fades,soundsets,widescreen,sound,petey,doppler,hx`) : lancement,
retour sur la place, entrée de niveau, cinématiques — validés à l'œil.

### Oiseaux lents, glissades murales et pachinko — signalement de l'auteur

« Les oiseaux sont très lents, leur animation est normale mais ils ne volent
pas vite » ; glissades murales peut-être plus lentes ; propulsion du pachinko
« pas contrôlable » (impressions, non chiffrées).

**Oiseaux** — prédit par le groupe 2 de `actors.py` (session 6) : 5 sites de
`TAnimalBird` multiplient une vitesse par `SMSGetAnmFrameRate()` dans du code
exécuté par sous-pas (nerfs) — 0,5 au lieu de 2,0, soit 4× trop lent. Sites
relus dans le DOL. `tools/fixes/birds.py` : groupe 2 extrait seul (9 mots,
identiques à actors.py, vérifié). Référence avant correctif
(`tools/watch_birds.py`, nouveau, balayage des instances par vtable
0x803ABE78) : **médiane 300,9 u/s** sur 8 oiseaux en vol, 17 instances,
119,7 images/s. Attendu après correctif : ×4, ~1200 u/s. Profil
`…,hx,birds` : **448 lignes**, installé. Repli : `work/GMSE01.avant-birds.ini`.

**Glissades murales, pachinko** — aucun mécanisme identifié : parmi les ~215
appels de `SMSGetAnmFrameRate`, aucun dans la physique de Mario (seulement
`initModel`, effets, `TMarioGamePad::reset`). Le pachinko de la décompilation
ne contient que des clous (`MapObjPachinkoNail`, collision). Rien n'est
affirmé : `tools/watch_mario.py` (nouveau) journalise Mario image par image et
résume par action la vitesse en u/s, pour une comparaison 30 FPS d'origine /
120 FPS sur le même geste.

### Oiseaux : validé par l'auteur (« ils volent normalement ») et mesuré

Relu en mémoire : `0x8000D1D8` = `bl 0x80002410`, routine en place, constante
2,0. `tools/watch_birds.py`, six fenêtres de 2 s : oiseaux en vol de croisière
**1159–1169 u/s** (autres valeurs : virages, atterrissages, départs), contre
un plateau de **296–311 u/s** avant correctif. Rapport ≈ 3,9, cohérent avec ×4
(la distance en ligne droite sous-estime un vol courbe). Profil 448 lignes.

### Audit des boss (4 agents, lecture seule, sites relus au DOL US par chaque agent)

Aucun défaut **bloquant** trouvé. Classement des défauts (« vérifié » = site et
instruction relus au DOL ; le rythme par sous-pas / par image est parfois
déduit de la décompilation, signalé) :

| Boss | Défaut | Effet à 120 FPS | Gravité | Confiance | État |
|---|---|---|---|---|---|
| Anguille (TBossEel) | 19 sites, anim par sous-pas à 0,25×anmRate (motif c) | toutes les phases 4× trop longues | gênant fort | haute, 3 sites relus à la main | `tools/fixes/eel.py` prêt (23 mots), non installé |
| Mario Ombre (TEnemyMario) | anim de peinture état 0x13 par sous-pas, 800427CC (c) | reste 4× plus longtemps à peindre | gênant | haute | à écrire |
| Baignoire, socles (TBathtubGrip) | 801FBBC4, anim à rythme mixte (c) | effondrement ~2,5× (ou 4×) trop lent | gênant | moyenne (facteur) | à mesurer |
| Bowser Jr, sous-marin | moveSwing par image, 801195BC (d) | tangage 4× trop rapide, équilibrage modifié | gênant | haute (mécanisme) | à écrire |
| Roi Boo | genAttacker appelé 5×/crachat à 30 FPS, 2× à 120 | moins de bulles / Boos | gênant ? | haute (mécanisme), effet non vérifié | à mesurer |
| Chomp de feu | bloc « porteur » sans drapeau, 8008C5D0 | Mario tiré ×1,6–2 sur la queue | gênant ? | moyenne (K inconnu) | à mesurer |
| Chenille géante | plancher de débit brut 800F2680 (e) | pattes 2–4× trop rapides au ralenti | cosmétique | haute | — |
| Petey | calcHeadDir ±1°/image (d) | tête 4× plus vive | cosmétique | haute | — |
| Calmar, raie, anguille (yeux), Bullet Bills, Mecha-Bowser (flamme) | compteurs par image (d/e) | effets 4× plus rapides | cosmétique | haute | — |

Sans défaut : Bowser (TKoopa), baignoire hors socles, Chomp de Pianta, plante
gardienne, TBPTornado, dents et larmes de l'anguille, rejeu de Mario Ombre
(une entrée par sous-pas).

Hors boss, relevé en passant (vérifié au DOL) : grande roue de Pinna Park
4× trop lente (b), rail des montagnes russes du décor 4× trop lent (c) ;
`MSound::gateCheck` n'accepte certains sons qu'une fois par image (120×/s au
lieu de 30) — non entendu ; `TMario::initModel`+0x920 règle le frame ctrl 2 du
modèle de Mario à anmRate — à auditer.

### Correctifs des boss installés en bloc (demande explicite de l'auteur)

« Lance l'installe de tous, je te dirai si ça va pas. » Écart assumé avec la
règle « un correctif à la fois » : chaque groupe ne s'exécute que dans son
propre combat ou son propre décor, l'attribution d'un défaut reste donc
univoque.

- `tools/fixes/eel.py` (23 mots) : anguille, groupe 3 d'actors.
- `tools/fixes/bosses.py` (81 mots, caverne 0x800024C0–0x800025E7, + JCCHAR
  d'actors en 0x80002420, + CONST2 partagé) : Mario Ombre (pose de la
  signature), sous-marin de Bowser Jr (6 incréments par image ÷ M), socles de
  la baignoire (10/(4+M), confiance moyenne), Chenille (plancher ÷ M), tête de
  Petey (±0,25, M = 4 figé), yeux de l'anguille, traîne du calmar (5 → 20, M = 4
  figé), flamme de Mecha-Bowser, clignotement des Bullet Bills, grande roue et
  rail des montagnes russes de Pinna Park (CONST2).
- 20 sites relus au DOL par le module lui-même ; mots relus à Capstone à leur
  adresse réelle ; `r12` jamais relu après un site (balayage), `f12`/`f13`
  absents des fonctions hôtes.
- Correction d'un rapport d'audit : le 3e site de la grande roue n'est pas
  0x801D6A38 (`fadds`) mais `initMapObj` 0x801D690C.

Profil **552 lignes** (dont doublons identiques de K_2/CONST2), installé.
Repli : `work/GMSE01.avant-boss.ini` (448 lignes, dernier profil validé).
Non installés, faute de mesure : Roi Boo, Chomp de feu, raie, calmar G1,
culbute de la Chenille, fumée des Bullet Bills, wagon des montagnes russes.

### Question de l'auteur : compatible avec Super Mario Eclipse ? — Non, pas en l'état.

Relu dans le dépôt JoshuaMKW/Super-Mario-Eclipse : module Kuribo compilé contre
BetterSunshineEngine (sous-module `lib/BetterSunshineEngine`, carte US).
BSE embarque ses propres correctifs de cadence (fps.cpp) qui écrivent chaque
image le littéral 0x804167B8 et mRetraceCount selon son réglage 30/60/120, et
détournent plusieurs des mêmes sites que ce profil (fader, HX, oiseaux,
anguille…). Les deux se battraient. Emplacement mémoire du chargeur Kuribo et
identifiant de jeu d'Eclipse : non vérifiés.

### Boss : validés par l'auteur (« tout est parfait pour le moment »)

Profil 552 lignes (`fades,soundsets,widescreen,sound,petey,doppler,hx,birds,eel,bosses`).

### Publication — « Sunshine Overdrive »

Projet renommé **Sunshine Overdrive** pour sa publication (dépôt GitHub
public). Nom du patch `$120FPS [Sunshine Overdrive]` (en `[OnFrame]` **et**
`[OnFrame_Enabled]` — à garder identiques, sinon Dolphin n'active pas le
patch) ; `install_profile.py` reconnaît l'ancien et le nouveau nom.

Préparation : chemins personnels retirés des outils (`DOLPHIN_EXE`,
`DOLPHIN_USER_DIR`, `SMS_ISO`, défaut `%APPDATA%`) ; renvois au plan de départ
(non publié) reformulés ; `work/` exclu en entier (DOL du jeu, carte, journaux
de mesure) ; README principal réécrit (fonctionnement, installation, limites) ;
`requirements.txt`.

## 2026-09-27 — Session 8, suite : la goop en escalier

**Cartographie** (agent, vérifiée au DOL, outil `tools/goop_inspect.py`) :
display list du matériau **reconstruite à chaque dessin** depuis les blocs J3D
(paquets non verrouillés, btk présent) → modifier les blocs agit à l'image
suivante. Matériau (9 matériaux de Bianco, identiques) : étage 0 alpha = masque
(+ liseré clair si masque < 160), étage 1 alpha = (a+0,5)×0,5, test d'alpha
≥ 128, opaque. Texel = **32 unités** (zone de 8192 sur 256).

**Bord fondu en direct** (`tools/goop_soft.py`, K = 4 puis 2) : mieux, mais
les marches restent — elles ont la taille d'un texel. Le pack de textures de
l'auteur remplace les masques (`pollution_maps`, 8192², BC7) mais **pas** ceux
de cette partie : empreintes XXH64 recalculées, absentes du pack (formule
validée sur la texture CMPR de la goop, trouvée). Simulation sur le masque réel
(binaire 0/255 à cet endroit) : le bilinéaire reproduit les marches vues en
jeu ; un filtre tente 3×3 les rend continues (`work/goop-lissage-simulation.png`).

**Module `goop`** (`tools/fixes/goop/goop.c`, compilé par le clang PowerPC de
BSE, `tools/fixes/goop.py`) : copie d'affichage lissée par couche, allouée
dans le tas du niveau (garde de 512 Ko, sinon rien) ; J3DTexture rebranché sur
une copie des ResTIMG dont l'entrée « masque » pointe vers la copie — le
gameplay (unk54, unk58, PollutionCount) n'est jamais touché. Mise à jour :
zones des tampons (`pushTask`), 4 lignes de fond par passage, bit de poids
faible du texel (0,0) basculé pour que Dolphin voie le changement. Bord fondu
K = 4 appliqué par le module. Interrupteurs en RAM (`tools/goop_ctl.py`).
Sites : 0x801A0EB8, 0x801A12C8, 0x8019ABAC. Code en 4 zones libres
(0x80001AE0, 0x80001F20, 0x800025F0, 0x80002A40), état en 0x80002F80.
Profil **1349 lignes**, installé. Repli : `work/GMSE01.avant-goop.ini`.
**Rien n'est encore testé en jeu.**

### Goop lissée : validée par l'auteur (« c'est legit parfait ») et mesurée

Relevé (`tools/goop_ctl.py`) : 5 couches préparées, 0 échec, les 5 J3DTexture
rebranchés sur la copie ; tas du niveau : **3981 Ko libres** pour 64 Ko
demandés (garde de 512 Ko largement tenue). Cadence : **119,7 champs VI/s,
120,0 images/s** avec le profil de 1349 lignes. ~820 mises à jour de lignes
par seconde (fond + zones de tampons).

À savoir : dans les niveaux où le pack de textures de l'auteur remplaçait les
masques d'origine (`pollution_maps`), l'affichage lit désormais la copie
lissée, dont l'empreinte diffère : le remplacement du pack ne s'y applique
plus. Non vérifié niveau par niveau.

### Goop : nettoyage affiché avec plusieurs secondes de retard, selon l'endroit

Signalement : la goop arrosée met plusieurs secondes à disparaître à l'écran
(le gameplay, lui, est à jour : pas d'animation de marche sur goop), et pas
partout. `tools/goop_probe.py` (nouveau) : copie en RAM **identique** à
tente(masque) (écart 0) — le retard est dans Dolphin. Sur la couche 1, un
tampon est poussé **à chaque image** même sans arrosage (zone x162–205 sur
toute la hauteur, `dframes` bloqué à 3) : deux mises à jour par image, donc
deux basculements du bit du texel (0,0), qui restait figé (`D00 = 1`). Dolphin
ne rechargeait la texture que si le nettoyage touchait un mot échantillonné.

Correctif : marqueur écrit **une fois par passage**, compteur modulo 3 dans les
2 bits bas du texel (0,0) ; fenêtre des zones marquées portée à 8 passages.
`set_soft` réécrit en accès 32 bits (non alignés, pris en charge par le 750)
pour tenir dans la caverne. Profil réinstallé. **À retester.**

### Goop : validée par l'auteur (« c'est parfait, tout est parfait »)

Nettoyage affiché sans retard après le correctif du marqueur. Profil 1309
lignes. `goop.py` conserve les adresses des fonctions liées dans
`goop_symbols.json` : le profil se reconstruit sans compilateur, **identique
octet pour octet** (vérifié par `diff` contre le profil validé).

## 2026-09-27 — Installateur Windows

`installer/SunshineOverdrive.iss` (Inno Setup 6.7.3) : détection du dossier
utilisateur de Dolphin (registre `HKCU\Software\Dolphin Emulator\UserConfigPath`,
puis `%APPDATA%`, puis Documents), page de choix (Dolphin portable), contrôle
`Config\Dolphin.ini`, sauvegarde d'un `GMSE01.ini` étranger et restauration à
la désinstallation, sans droits administrateur, français / anglais,
`/DOLPHINDIR=` pour l'installation silencieuse.

Testé en local (compilateur extrait en mode portable, signature Pyrsys
vérifiée), dans un faux dossier Dolphin :
- installation : profil identique à `deliver/GMSE01.ini`, ancien fichier
  sauvegardé, clé `HKCU\Software\Sunshine Overdrive`, entrée « Applications » ;
- désinstallation : fichier d'origine restauré à l'identique, clé, entrée et
  dossier du programme supprimés ;
- double installation sur Dolphin vierge : pas de fausse sauvegarde ;
  désinstallation : dossier vide.

Publication : `.github/workflows/installateur.yml` construit le Setup à chaque
tag `v*` (Inno Setup téléchargé, signature vérifiée) et le publie en Release.

## 2026-09-27 — Oiseau de sable (TJointCoin)

Signalement de l'auteur : « l'oiseau de sable va trop lentement », avec
réserve (« ce n'est peut-être qu'une impression »). Lecture du DOL :
`TSandBird` hérite de `TJointCoin` (vtable 0x803CF2B4 : `loadAfter`
0x801F761C hérité, `control` appelle 0x801F79C4). `TJointCoin::control`, par
sous-pas, avance le MActor +0x138 et copie la translation de son joint racine
dans la position. `loadAfter` pose les débits à 0,25 × anmRate
(0x801F76A8 → +0x74, 0x801F76C4 → +0x138). Le groupe 4 d'`actors.py` qui le
corrige n'avait jamais été installé.

`tools/watch_sandbird.py` (nouveau) : débit et trame du frame ctrl 0 des deux
MActor, trames d'anim/s, vitesse de vol. Gelato, 5 fenêtres de 2 s, 120 images/s :

| | avant (profil 1309) | après (`jointcoin`) | cible, calculée à 30 FPS |
|---|---|---|---|
| débit +0x138 / +0x74 | 0,125 / 0,125 | 0,5 / 0,3125 | 0,5 / 0,5 |
| trajectoire, trames/s | 15,0 | 59,8–60,1 | 60 |
| ailes, trames/s | 30,0 | 74,7–75,1 | 75 |
| vol | 88 u/s | 351–353 u/s | ~350 u/s |
| tour de 9000 trames | ~600 s | ~150 s | 150 s |

Module `tools/fixes/jointcoin.py` : les deux sites seuls (→ JCCHAR, → CONST2),
routines identiques à `actors.py`. Profil 1324 mots, repli
`work/GMSE01.avant-jointcoin.ini`. Colonne 30 FPS **calculée**, non mesurée.
Autres `TJointCoin` du jeu (aucun dans ce niveau) : **non vérifiés**.
Publié en v1.1.0 à la demande de l'auteur.

## 2026-09-27 — Poinks (TPopo) : auto-collision en vol

Signalement de l'auteur : les Poinks (« petits cochons roses » à lancer sur
Petey, Bianco) « explosent instantanément et ne dépassent pas 2 m ». Classe
`TPopo` (nom japonais Popo), vtable 0x803BA558 ; boîte de collision secondaire
`TPopoCollision` en +0x23C (propriétaire en +0x68).

`tools/watch_popo.py` (nouveau) : nerfs, remplissage +0x198, gâchette R,
vitesse de lancement, durée et distance de vol, touches du Poink et de sa
boîte, écart boîte ↔ Poink. Mesuré à 120 images/s, 1 pas par image :

- 20 lancers : 19 explosés 7 à 10 pas après le lancement (< 0,1 s, 380–880 u),
  1 au pas 2. Minuterie de vol (+0x19C, limite prm+0x3DC = 1000) jamais
  atteinte ; drapeau « en l'air » encore levé : ni atterrissage ni minuterie.
- 8 lancers suivis : contact du Poink avec **sa propre boîte** au premier
  `checkActorsHit` (tous les 4 sous-pas, `unk58`) après la réactivation de la
  collision au pas 6 (`TNervePopoFly`) ; boîte à 150–210 u derrière le Poink.

Cause lue dans le DOL : `TPopo::calcRootMatrix` place la boîte sur un joint,
depuis les matrices de l'image précédente, et n'est appelé que dans la passe
d'animation (`TLiveActor::perform`, drapeau 0x2) : retard d'une image. À 120
FPS, une image = 1 sous-pas, la boîte colle au Poink ; à 30 FPS, 4 sous-pas de
plus, ≥ 500 u (**calculé**), pas de contact.

Deux chemins vers l'explosion, tous deux par `TPopo::isCollidMove`
(0x800E6C94) : Poink → boîte (`isCollidMove(Poink, boîte)`) et boîte → Poink
(`TPopo::bind` → `TSmallEnemy::behaveToHitOthers(Poink, Poink)` → vtable
+0x17C = `isCollidMove(Poink, Poink)`). Première version (boîte seule) :
installée, mesurée, **sans effet** (9 lancers sur 9 explosés au pas 7–10).

Module `tools/fixes/poink.py` : détour au prologue d'`isCollidMove`, renvoie 0
si l'autre est le Poink ou sa boîte. Routine en 0x80001D80 (zone nominale de
soundsets, inutilisée au-delà de 0x80001CF8, vérifiée nulle). Profil 1334
mots, repli `work/GMSE01.avant-poink.ini`.

Après : le Poink vole 54 pas (0,45 s), 4630 u, et explose sur `TBPNavel`
(nombril de Petey), qui se réveille. Validé par l'auteur (« ils volent
normalement »). Un seul lancer mesuré après correctif.

## 2026-09-27 — Goop rose (Bianco) et flaques de Petey

Signalement de l'auteur : la goop rose garde des bords en escalier ; la goop
crachée par Petey s'affiche « en 3 frames », « des fois normale, des fois non ».

**Trois causes, relevées en jeu** (`tools/goop_ctl.py`, `tools/goop_inspect.py`) :

1. **9 couches** dans l'épisode de la goop rose (7 murales, 2 de sol) pour
   `MAXL = 8` emplacements : la 9e (128×128) n'était pas traitée. MAXL → 16
   (`goop_roots` 0x80002FA0–0x80002FDF).
2. **Display lists figées** : les 2 grandes couches de sol ont un
   `J3DMatPacket` verrouillé (+0x10 bit 0) ; leur BP 0x94 (TX_IMAGE3 map0)
   reste sur le masque, rebrancher le J3DTexture n'y change rien. Preuve :
   lissage coupé en direct, aucun changement à l'écran ; mot réécrit à la
   main dans les deux tampons (+5) → « lisse ! ». Module : `patch_dl`, tous
   les 16 passages, n'écrit qu'un mot valant déjà le masque ou la copie.
   Toutes les copies relues : écart 0 avec tente(masque).
3. **Tâches « modèle »** (`TPollutionCounterLayer::pushModelStampTask`,
   appelée par `stampModel` : `TBPPolDrop`, `TBPVomit`, `TBossGesso`,
   `TEnemyMario`, `TPolluterBase`…) hors des tampons `pushTask` suivis :
   rattrapées seulement par le balayage de fond (4 lignes/passage).
   `tools/watch_poldrop.py` : étalement 0,5 trame/image, 79 trames en 156
   images = **60 trames/s, vitesse d'origine** (2,0 × 30) — l'étalement lent
   est normal. `tools/watch_goop_growth.py` : sur la couche de l'arène
   (512×512), la copie ne rattrapait le masque que toutes les ~16 images, par
   bonds (+77, +100 texels) — selon la position du balayage.
   Flaque mesurée : ~600 u autour du tampon (échelle 2), 2 flaques.
   Module : crochet 0x8019B120 → `goop_model_tramp` → `goop_mark_model` :
   zone carrée de rayon 400 u × échelle autour de la translation du modèle,
   recalculée 8 passages, renouvelée à chaque tâche ; zone distincte de celle
   des tampons. Interrupteur `goop_ctl.py model on|off`.

Essai intermédiaire abandonné : balayage rapide de toute la couche (32
lignes/passage) après une tâche modèle — insuffisant sur 512 lignes (16
passages par tour) ; crochet `pushJointObjStampTask` retiré avec lui (place).
Oubli corrigé en cours de route : champ `burst` non initialisé dans
`goop_init` (valeurs du tas relevées : 81, 108).

Place : `patch_dl` en zone E 0x80001CFC–0x80001D80 (132 o, pleine) ;
`goop_mark_model` en zone A, `slot_of` en zone C, `mark_rect` et le
trampoline en zone B. Profil **1484 mots**, repli
`work/GMSE01.avant-goop2.ini`. Validé par l'auteur : « tout est lisse, ça
s'étale de façon fluide ». Publié en v1.3.0.
