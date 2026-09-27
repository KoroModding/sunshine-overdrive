# Phase 0 et batterie de tests

> Le plan de départ impose : **phase 0 avant tout code**, et **écrire les tests avant
> les correctifs**. Ce document est le protocole et le relevé.
>
> **Phase 0 exécutée le 2026-09-15** par instrumentation mémoire externe
> (`tools/dolphin.py`), sur Dolphin 2606a, GMSE01, Delfino Plaza. Les mesures
> ci-dessous sont réelles. Les tableaux encore vides ne l'ont pas été.
>
> **Batterie de physique exécutée le 2026-09-15** au même endroit, avec
> injection d'entrées (`tools/pad.py`) et mesures indexées sur le sous-pas
> (`tools/substep_clock.py`). Voir aussi
> [`adr/0003-injection-manette.md`](adr/0003-injection-manette.md) et
> [`adr/0004-mesure-en-sous-pas.md`](adr/0004-mesure-en-sous-pas.md).

---

## Phase 0 — confirmer le compte de sous-pas

L'analyse statique a établi le *mécanisme* de l'accumulateur
([`01-mecanismes.md` § 1](01-mecanismes.md)). Elle ne peut pas établir le
*compte effectif* à l'exécution, ni l'appartenance d'un `perform` donné à une
liste de simulation ou à une liste par image rendue : les listes sont peuplées
à l'exécution et parcourues par répartition virtuelle.

### 0.A — Watchpoint sur l'accumulateur (mesure directe)

La plus directe des deux méthodes, et celle à faire en premier.

1. Dolphin → View → Debugging Mode, charger `work/maps/us.map`.
2. Lancer le jeu, atteindre une zone jouable stable (Delfino Plaza, Mario à
   l'arrêt).
3. Récupérer le pointeur `TMarDirector`. Point d'arrêt à l'exécution sur
   `0x80299838` (`direct()`) : `r3` contient `this`.
4. Point d'arrêt mémoire **en écriture** sur `this + 0x54`.
5. Compter les déclenchements entre deux passages en `0x80299938`
   (`unk54 += vsyncRate`), qui délimite une image rendue.

| Cadence | `vsyncRate` attendu | Sous-pas/image attendu | `vsyncRate` **mesuré** | Sous-pas/image **mesuré** |
|---|---|---|---|---|
| 30 FPS (non patché) | 20 | 4 | **20** | **4,000** |
| 60 FPS (patché) | 10 | 2 | **10** | **1,992** |
| 120 FPS (patché) | 5 | 1 | **5** | **1,000** |

Relevé complet, sondage de 4 s par palier :

| Palier | images/s | sous-pas/s | vitesse de simulation |
|---|---|---|---|
| 30 FPS (origine) | 30,00 | 120,00 | **100 %** |
| 60 FPS | **60,00** | 119,50 | **99,6 %** |
| 120 FPS sans overclock VI | 60,00 | 60,00 | 50 % — **mi-vitesse** |

Le palier 120 plafonne parce que la présentation ne peut pas dépasser le taux
de champs du VI (59,94 Hz). Il exige le **VBI Frequency Override** de Dolphin à
2×. Ce n'est pas un défaut du modèle : c'est sa confirmation.

L'échantillonnage est **auto-validé** — sur 750 transitions relevées à 30 FPS,
les 600 décréments valent tous exactement 5 et les 150 incréments tous
exactement 20. Aucune transition manquée.

Lire aussi la valeur de `r25` au sortir de `0x8029986C` : elle doit valoir
exactement 20, 10 puis 5.

### 0.B — Watchpoint sur `mVel.y` de Mario (contre-mesure)

Méthode indiquée par le plan de départ. Elle vaut comme **contrôle indépendant** de
0.A : elle mesure le nombre d'exécutions de `movement()`, pas le nombre de
soustractions de l'accumulateur. Les deux doivent concorder.

1. Récupérer `gpMarioOriginal`, en déduire l'adresse de `mVel.y`.
2. Point d'arrêt mémoire en écriture, Mario en chute libre (saut depuis un
   point haut) pour garantir une écriture par sous-pas.
3. Compter les déclenchements par champ VI, à 30 puis à 60 FPS.

Attendu : 4, puis 2.

**Réalisé autrement, et de façon plus probante** : plutôt qu'un point d'arrêt
sur `mVel.y`, la chute libre automatisée (§ *Physique* ci-dessous) compte les
intégrations de la position. Elle donne **198 intégrations à 30 FPS et 198 à
60 FPS** — chiffre identique, soit ~120 Hz dans les deux cas. Cela recoupe 0.A
par une voie entièrement indépendante de l'accumulateur.

> 0.A et 0.B **concordent**. Le modèle de l'accumulateur est confirmé.

### 0.C — Classer les listes de perform

Déterminer, pour chaque objet à corriger, s'il est appelé par sous-pas ou par
image rendue. C'est la mesure qui décide de tout le reste.

1. Point d'arrêt à l'exécution sur le `perform` de l'objet.
2. Compter les déclenchements entre deux passages en `0x80299938`.

| Résultat | Classement | Correction nécessaire |
|---|---|---|
| 4 à 30 FPS, 2 à 60 FPS | liste de **simulation** | aucune |
| 1 à 30 FPS, 1 à 60 FPS | liste **par image rendue** | facteur `30 / cadence` |

Premier objet à passer au crible : `TModelGate::perform` @ `0x801EB014`, pour
trancher l'anomalie du § 4.3 de [`01-mecanismes.md`](01-mecanismes.md).

---

## Test dédié — l'anomalie `0x80414904`

Le littéral `0.01f` est un incrément **par appel** du fondu de `TModelGate`.
BSE et `gamemasterplc` le **doublent** à chaque palier. Les deux lectures
possibles de la règle de classement disent qu'il faudrait soit ne rien faire,
soit **diviser**. L'expérience tranche :

| # | Cadence | `0x80414904` | Durée du fondu attendue si le patch est correct | Mesuré |
|---|---|---|---|---|
| 1 | 30 FPS | `0.01f` (d'origine) | référence | |
| 2 | 60 FPS | `0.01f` (non patché) | = réf. si liste de simulation ; ½ réf. si par image | |
| 3 | 60 FPS | `0.02f` (patché) | = réf. | |
| 4 | 120 FPS | `0.04f` (patché) | = réf. | |

Protocole : approcher un portail en ligne droite à vitesse constante depuis
au-delà de 1000 unités, chronométrer en nombre de champs VI entre le
franchissement du seuil et `m0xD0 == 1.0f` (point d'arrêt sur l'écriture en
`0x801EB188`).

**Si la mesure 2 est égale à la mesure 1**, `TModelGate::perform` est dans une
liste de simulation, aucune correction n'est nécessaire, et la ligne
`04414904` du Gecko est à retirer.

---

## Batterie de régression

À exécuter à chaque palier, avec les mêmes entrées. Le plan prévoyait un
enregistrement `.dtm` ; l'injection mémoire de `tools/pad.py` s'est révélée
plus commode et surtout scriptable — voir
[`adr/0003-injection-manette.md`](adr/0003-injection-manette.md).

Unité de mesure : le **sous-pas de simulation**, compté par
`tools/substep_clock.py`. Ni la seconde ni l'image ne conviennent :

| Unité | Pourquoi elle ne va pas |
|---|---|
| seconde | le nombre d'images couvertes change avec la cadence, et le taux de réussite de l'injection avec lui |
| image rendue | c'est précisément la variable que l'on fait changer |
| champ VI | stable, mais ne dit rien du nombre d'intégrations exécutées |
| **sous-pas** | **120 Hz constants par construction — la seule grandeur commune aux paliers** |

Le détail du raisonnement est en
[`adr/0004-mesure-en-sous-pas.md`](adr/0004-mesure-en-sous-pas.md).

### Physique — ne doit jamais bouger

Un écart ici signifie que l'accumulateur ne fait pas son travail, et
**interdit** de corriger en retouchant les `.prm` : c'est la cause qu'il faut
chercher, pas le symptôme.

| Test | Grandeur mesurée | 30 | 60 | 120 |
|---|---|---|---|---|
| **chute libre** | **intégrations de position** | **198** | **198** | |
| **chute libre** | **durée réelle** | **1,655 s** | **1,635 s** (+1,2 %) | |
| **chute libre** | **distance parcourue** | **3000,0** | **3000,0** | |
| **arc balistique** (`vy` = 42) | **suite des vitesses verticales** | **identique** | **identique** | |
| **arc balistique** | **intégrations jusqu'au sommet** | **42** | **42** | |
| **arc balistique** | **altitude du sommet** | **225,75** | **225,75** | |
| **saut court** (A, 6 sous-pas) | hauteur maximale | 73,79 | 73,79 | |
| **course** (120 sous-pas) | vitesse maximale | 8,91 | 8,91 | |
| course — distance parcourue | distance | *165,17* | *160,82* | |
| saut long (A, 40 sous-pas) | hauteur maximale | *96,60* | *81,59* | |
| triple saut | hauteur maximale | | | |
| plongeon | distance parcourue | | | |
| glissade | distance d'arrêt | | | |
| hover (F.L.U.D.D.) | champs de suspension à réservoir plein | | | |

*En italique : mesures faussées par le décor, voir ci-dessous. Elles ne sont pas
des résultats, elles sont une leçon de méthode.*

*La vitesse de course, elle, coïncide à la décimale entre paliers — mais à
8,91, soit la valeur d'un Mario qui pousse contre un obstacle ; en terrain
libre elle monte vers 32. Le choix automatique de direction
(`probe_open_direction`) n'a donc pas trouvé de dégagement depuis ce point de
départ. La coïncidence reste informative, elle n'est pas la mesure voulue.*

### L'arc balistique — la mesure qui tranche

```sh
python tools/test_ballistic.py 42 30 60
```

Mario est placé à 2500 unités du sol, sa vitesse verticale est imposée à 42, et
l'arc est relevé sous-pas par sous-pas. Aucune entrée, aucun contact, aucun
type de saut : il ne reste que l'intégrateur.

```
suite vy à 30 FPS : [42.0, 41.0, 40.0, 39.0, 38.0, 37.0, 36.0, 35.0, 34.0, …]
suite vy à 60 FPS : [42.0, 41.0, 40.0, 39.0, 38.0, 37.0, 36.0, 35.0, 34.0, …]
=> suites IDENTIQUES sur 90 intégrations.
```

**Gravité = exactement 1,0 unité de vitesse par sous-pas, aux deux paliers.**
Sommet à 225,75 des deux côtés, 42 intégrations jusqu'à l'apogée. Avec la chute
libre, c'est la démonstration la plus directe que la physique est découplée de
la cadence d'affichage.

### La fausse alarme du saut long — à lire avant d'interpréter un écart

Le premier relevé annonçait `ÉCART SIGNIFICATIF` : 96,60 contre 81,59 sur la
hauteur du saut long, 14,66 % d'écart, parfaitement reproductible. Trois
hypothèses ont été écartées par la mesure :

| Hypothèse | Vérification | Verdict |
|---|---|---|
| l'injection d'entrées est aléatoire | variance intra-palier sur 6 essais | **écartée** — 0,00 d'étendue à 60 FPS |
| le type de saut diffère (double, triple) | `vy` initiale relevée | **écartée** — 42,0 aux deux paliers |
| le relâchement de A est vu plus tard à 30 FPS | balayage de 6 à 150 sous-pas de maintien | **écartée** — hauteur insensible à la durée |

Reste le décor : un arc libre depuis `vy` = 42 culmine à **225,75**, alors que
les deux sauts mesurés plafonnaient à 96,60 et 81,59. Mario tapait un plafond
ou un surplomb près du mur choisi comme direction « dégagée ». Ce n'était pas
de la physique.

**La leçon est dans l'outillage.** Une hauteur d'apogée et une distance
parcourue sont des grandeurs *de sortie* : elles mesurent le relief autant que
l'intégrateur. `tools/test_physics.py` a donc été révisé — son verdict porte
désormais sur les **profils par sous-pas** (suite des vitesses), les hauteurs et
distances n'étant plus qu'indicatives. Cette révision **n'a pas encore été
rejouée** sur un Dolphin en cours d'exécution ; le tableau ci-dessus est celui
de l'ancien critère.

### À faire à la prochaine session de mesure

Dans cet ordre — chaque point conditionne le suivant :

1. **Choisir un point de départ dégagé** avant tout le reste. Delfino Plaza au
   pied du mur fausse à la fois la course (8,91 au lieu de ~32) et le saut
   (plafond). La plage ou une grande place conviennent ; le test le dira
   lui-même, `probe_open_direction` devant rapporter une distance franchement
   supérieure à 165.
2. **Rejouer `test_physics.py`** avec le critère par profils. C'est la seule
   partie du projet dont le code a changé sans être réexécutée.
3. **Mesurer le palier 120** avec le VBI Frequency Override à 2×. Tout est
   prêt : `second_instance.py start --vi 2.0` lance, navigue et arrive en jeu
   seul. Ne pas le faire pendant qu'une autre instance tourne — elles se
   disputent le GPU et la cadence mesurée n'a plus de sens.
4. **Compléter les lignes vides** de ce document : triple saut, plongeon,
   glissade, hover. Elles demandent des séquences d'entrées, pas de nouvelle
   mécanique.

### Cadencé par image rendue — suspects désignés

Ces éléments sont ceux que le plan de départ recense comme cassés. Chacun doit être
classé par la méthode 0.C avant d'être corrigé.

| Test | Grandeur mesurée | 30 | 60 | 120 |
|---|---|---|---|---|
| boîte de dialogue | champs d'affichage (`0x251` : 20 / 40 / 80) | | | |
| `TSMSFader` | champs du fondu | | | |
| transition HX Circle | champs | | | |
| transition HX GameOver | champs | | | |
| écran de sélection des Shines | champs par pas de défilement | | | |
| cutscene d'intro | champs, début à fin | | | |
| chargement de niveau | champs | | | |
| fondu `TModelGate` | champs (voir ci-dessus) | | | |

### Objets et ennemis

| Test | Grandeur mesurée | 30 | 60 | 120 |
|---|---|---|---|---|
| nuée d'oiseaux (`TBoidLeader`) | champs pour un tour de boucle | | | |
| boss anguille | champs par phase | | | |
| Petey Piranha | champs par cycle d'attaque | | | |
| `TJointCoin` / SandBird | champs d'animation | | | |
| FireWanwan | vitesse de déplacement | | | |
| ennemi scripté (Strollin' Stu) | champs par cycle de patrouille | | | |

---

## Instrumentation

Ce que le projet utilise réellement :

- **Mémoire émulée** — `tools/dolphin.py`, lecture/écriture de la MEM1 depuis
  l'extérieur. Ni débogueur, ni point d'arrêt, ni action dans l'interface.
- **Correctifs réversibles** — `tools/patch.py`, qui n'écrit que des données
  (le JIT ignore les écritures dans le code).
- **Entrées** — `tools/pad.py`, injection dans `TMarioGamePad`.
- **Horloge** — `tools/substep_clock.py`, sur l'accumulateur du directeur.

Ce que le plan prévoyait, resté en réserve :

- **Points d'arrêt** — Dolphin, View → Debugging Mode, map chargée depuis
  `work/maps/us.map`. Reste nécessaire pour l'étape 0.C : classer un `perform`
  demande de compter ses exécutions, ce qu'aucune lecture de mémoire ne donne.
- **Recherche RAM** — `dolphin-memory-engine` (aldelaro5).
- **Comptage de champs** — log `VIDEOINTERFACE` en niveau DEBUG : `LogField()`
  émet `WPL / STD / EQU / PRB / ACV / PSB` à chaque champ.
- **Enregistrement `.dtm`** — remplacé par l'injection mémoire, qui a l'avantage
  de se piloter depuis le même script que la mesure.

---

## Règle de consignation

Une ligne de mesure n'est renseignée que si elle a été **exécutée**. Une valeur
attendue par le calcul se note dans la colonne « attendu », jamais dans
« mesuré ». Un tableau à moitié vide est une information ; un tableau rempli de
suppositions est un piège pour la suite du projet.

---

## Palier 120 FPS — relevés du 2026-09-22

Dolphin 2606a, GMSE01, Delfino Plaza. Profil `deliver/GMSE01.ini` appliqué,
VI overclocké à 2×.

### Cadence

`measure_substeps.py` et `validate_120.py`, cinq mesures successives.

| Grandeur | Attendu | Mesuré |
|---|---|---|
| `vsyncRate` | 5 | **5** |
| images présentées | 119,88 /s | **119,87 · 119,80 · 119,80 · 119,80 · 119,83** |
| sous-pas | 120,00 /s | **119,87 · 119,80 · 119,80 · 120,00 · 120,00** |
| sous-pas par image | 1,000 | **1,000 · 1,000 · 1,000 · 1,002 · 1,001** |
| vitesse de simulation | 100 % | **99,8 – 100,0 %** |

Échantillonnage auto-validé à chaque mesure : tous les décréments valent
exactement 5, tous les incréments exactement 5.

**Une mesure aberrante, gardée ici.** Une sixième mesure, prise juste après un
changement de scène, a relevé **87,33 images/s et 87,50 sous-pas/s**, soit
72,9 % de la vitesse correcte. Les quatre mesures suivantes sont revenues à
119,8 sans intervention. À 120 FPS, l'hôte n'a plus de marge : quand Dolphin ne
tient pas la cadence, **le jeu ralentit pour de bon** — il n'y a pas de
mécanisme de rattrapage. L'à-coup n'a pas été caractérisé.

### Physique — arc balistique

`python tools/test_ballistic.py 42 30 120`

| Grandeur | 30 FPS | 120 FPS | Verdict |
|---|---|---|---|
| suite des vitesses verticales | référence | **identique sur 90 intégrations** | ✔ |
| intégrations jusqu'au sommet | 42 | **42** | ✔ |
| altitude du sommet | 225,75 | **225,75** | ✔ |

Les mêmes valeurs qu'aux paliers 30 et 60 relevés en session 3. La gravité vaut
1,0 unité de vitesse par sous-pas aux trois paliers.

### Physique — chute libre

`python tools/test_freefall.py 3000 120`

| Grandeur | 30 FPS (session 2) | 120 FPS | Écart |
|---|---|---|---|
| durée réelle d'une chute de 3000 u | 1,655 s | **1,656 s** | **0,06 %** |
| intégrations | 198 | 199 | 1 |

La durée réelle est la mesure qui compte : elle dit que le jeu tourne à la bonne
vitesse **en temps réel**, et pas seulement par sous-pas. L'unité d'écart sur le
compte d'intégrations est un effet de bord du détecteur, pas une différence de
physique — l'arc balistique, lui, est exact au flottant près.

### Ce qui n'est pas passé

| Sujet | État |
|---|---|
| particules JPA | **cassé puis compensé** — voir ci-dessous |
| audio sous overclock VI | **non jugé** — l'instrumentation n'entend rien |
| transitions HX, fondus, minuteurs de dialogue | **non testés**, et attendus faux (×4) |
| boss, ennemis scriptés | **non testés** |

### Particules — le défaut trouvé à l'usage

Signalé à l'œil, pas par un test : jets d'eau figés, et animation d'entrée dans
un graffiti absente. Cause en [`01-mecanismes.md` § 5](01-mecanismes.md) —
`JPAEmitterManager::calc()` appelé `(int)SMSGetAnmFrameRate()` fois par image,
soit **zéro** à 120 FPS.

Correctif posé (`0x802887B0 → li r23, 1`) : **vérifié présent en mémoire**,
**non vérifié à l'œil**. Et il est imparfait par construction — il fait avancer
les particules à 120 Hz au lieu de 60.

**Test à écrire** : chronométrer la durée de vie d'un effet JPA aux trois
paliers. C'est la seule façon de mesurer le facteur 2 plutôt que de le déduire.
