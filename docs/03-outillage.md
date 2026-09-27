# Outillage

Quinze modules Python, en deux familles :

- **hors ligne**, sur le fichier DOL — `gciso`, `dol`, `symbols`, `disasm`, `xref` ;
- **à chaud**, sur un Dolphin en cours d'exécution — `dolphin`,
  `measure_substeps`, `patch`, `substep_clock`, `pad`, `test_freefall`,
  `test_physics`, `test_ballistic`, `dolphin_host`, `second_instance`.

Seule dépendance externe : `capstone` (désassembleur), installé par
`python -m pip install capstone`.

Aucun outil ne code en dur une adresse propre à une région : les bases `r2`/`r13`
sont lues dans le DOL analysé, et les objets du jeu sont résolus depuis les
globales. Les commandes hors ligne fonctionnent donc sur `GMSE01`, `GMSP01` et
`GMSJ01`.

---

# Outils hors ligne

---

## `tools/gciso.py` — image disque

Lecture d'une image GCM/ISO : en-tête, FST, extraction de fichiers.

```sh
python tools/gciso.py header  <iso>
python tools/gciso.py dol     <iso> <sortie>
python tools/gciso.py fst     <iso>
python tools/gciso.py extract <iso> <chemin-dans-iso> <sortie>
```

La taille du `main.dol` n'est pas stockée dans l'en-tête disque : elle est
déduite du plus grand `offset + taille` parmi les 18 sections déclarées.

Le magic GameCube (`0xC2339F3D` en `0x1C`) est vérifié à chaque lecture. Une
image Wii, RVZ ou CISO est rejetée explicitement plutôt que de produire des
offsets absurdes.

---

## `tools/dol.py` — exécutable DOL

Table des sections, correspondance adresse virtuelle ↔ offset fichier, lectures
typées, recherche de motifs, désassemblage brut.

```sh
python tools/dol.py sections <dol>
python tools/dol.py read     <dol> <adresse> [octets]
python tools/dol.py dis      <dol> <adresse> [instructions]
python tools/dol.py f32      <dol> <adresse> [nombre]
python tools/dol.py find     <dol> <octets-hex>
python tools/dol.py findf32  <dol> <valeur>
```

Une adresse tombant dans le BSS produit un message explicite : la valeur
n'existe qu'à l'exécution, pas dans le fichier. C'est le piège classique quand
on suit une chaîne de pointeurs à partir d'un listing.

Capstone ne connaît pas les instructions *paired single* du Gekko (`psq_l`,
`ps_madd`…). Elles ressortent en `.byte` au lieu de faire échouer le
désassemblage — un `.byte` dans un listing signale une instruction Gekko, pas
une erreur de lecture.

---

## `tools/symbols.py` — table de symboles et démangling

```sh
python tools/symbols.py lookup   <map> <adresse>
python tools/symbols.py find     <map> <motif>
python tools/symbols.py demangle <nom-manglé>
```

Format de map accepté : `nom=0xADRESSE`, une entrée par ligne. C'est celui des
maps publiées par BetterSunshineEngine et Corona.

Les noms sont manglés par **CodeWarrior**, pas par le schéma Itanium de
GCC/Clang — `c++filt` ne sait pas les lire. Le démangleur implémenté ici couvre
les portées imbriquées (`Q2`), les templates, les qualificatifs `P`/`R`/`C` et
les méthodes const. Il est volontairement partiel : en cas de doute il rend le
nom manglé brut, parce qu'un listing partiellement démanglé reste exploitable
alors qu'un listing faux ne l'est pas.

**Limite à connaître :** une map ne donne que des adresses de départ, jamais de
tailles. `SymbolTable.containing()` borne un symbole à l'adresse du suivant,
ce qui surestime le dernier symbole de chaque section. Ne pas s'en servir pour
délimiter une fonction avec certitude.

---

## `tools/disasm.py` — désassemblage annoté

L'outil principal. Dépend de `dol.py` et `symbols.py`.

```sh
python tools/disasm.py <dol> <map> <fonction-ou-adresse> [instructions]

python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map SMSGetVSyncTimesPerSec__Fv
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map 0x802FC9A4 80
```

Trois annotations s'ajoutent au listing brut :

1. **cibles de branchement** résolues en symboles démanglés ;
2. **accès aux petites données** — `lfs f0, -0x3e8(r2)` devient
   `-> 0x804167B8 = 0x3F000000  f32 0.5  i32 1056964608`. C'est l'annotation
   qui rend ce projet praticable : sans elle, aucun littéral flottant n'est
   identifiable dans un listing ;
3. **bornes de fonction** — le listing s'arrête au symbole suivant quand aucun
   nombre d'instructions n'est donné.

L'argument peut être une adresse, un symbole manglé exact, ou une sous-chaîne
si elle ne correspond qu'à un seul symbole.

Sans map utilisable, `__init_registers` est retrouvé en suivant le premier `bl`
du point d'entrée. Passer un fichier vide comme map suffit donc à analyser un
DOL sans symboles :

```sh
: > work/maps/empty.map
python tools/disasm.py work/dol/GMSP01.dol work/maps/empty.map 0x8029FC8C 20
```

---

## `tools/xref.py` — références croisées

```sh
python tools/xref.py <dol> <map> <adresse-ou-symbole>
```

Le DOL n'a ni relocations ni table de symboles : aucun index des références
n'existe. L'outil le reconstruit en balayant les sections exécutables.

Trois formes détectées :

| Forme | Exemple | Fiabilité |
|---|---|---|
| forme D relative à `r2`/`r13` | `lfs f0, -0x3e8(r2)` | **exacte** — aucun faux positif, aucun manque |
| paire `lis` + `addi`/`ori` | `lis r3, 0x8041 ; addi r3, r3, 0x4904` | certaine mais **incomplète** |
| branchement | `bl fonction` | **exacte** |

> **Lire l'avertissement.** La détection des paires `lis`/`lo` n'examine que des
> instructions **adjacentes** portant sur le même registre. Un compilateur qui
> intercale du code entre les deux moitiés y échappe, et l'invalidation du
> registre en attente ne couvre pas les instructions de forme X. Toute
> référence trouvée est donc vraie, mais **un résultat vide ne prouve rien**.

En pratique cette limite ne gêne pas le projet : tous les littéraux flottants
passent par la forme D relative à `r2`, pour laquelle la détection est exacte.

---

# Outils d'exécution

Les cinq modules ci-dessus travaillent sur le DOL, hors ligne. Les dix
suivants s'adressent à un **Dolphin en cours d'exécution**. Ils sont
Windows-seulement (API Win32) et n'exigent ni le débogueur de Dolphin, ni de
point d'arrêt, ni la moindre action dans l'interface.

Justification et limites de l'approche : [`adr/0002-instrumentation.md`](adr/0002-instrumentation.md).

## `tools/dolphin.py` — mémoire émulée

```sh
python tools/dolphin.py info
python tools/dolphin.py read  <adresse> [octets]
python tools/dolphin.py u32   <adresse> [nombre]
python tools/dolphin.py f32   <adresse> [nombre]
python tools/dolphin.py write <adresse> <octets-hex>
python tools/dolphin.py deref <adresse> [offset…]
```

La projection de la MEM1 est localisée en balayant les régions du processus,
puis **validée en lisant l'en-tête de disque GameCube** (identifiant en
`0x80000000`, magic `0xC2339F3D` en `0x8000001C`). Cette validation distingue
la vraie MEM1 de toute autre projection et confirme quelle image est chargée.

Débit mesuré : ~405 000 lectures de 4 octets par seconde, soit 2,5 µs par
lecture.

> **Données oui, code non.** Écrire dans une **instruction** reste sans effet :
> Dolphin continue d'exécuter le bloc JIT déjà compilé. Écrire dans une
> **donnée** prend effet immédiatement. Vérifié expérimentalement.

## `tools/measure_substeps.py` — phase 0

```sh
python tools/measure_substeps.py [durée-en-secondes]
```

Sonde l'accumulateur `TMarDirector + 0x54` et en déduit images/s, sous-pas/s et
sous-pas par image.

La mesure est **auto-validante** : l'accumulateur ne varie que par
`+vsyncRate` et `-5`. Si le sondage ratait une transition, l'écart observé ne
serait plus 5. Le script vérifie que tout décrément vaut exactement 5 et que
tout incrément vaut exactement la même valeur, et **rejette** la mesure sinon
au lieu de la rapporter.

## `tools/patch.py` — correctifs réversibles

```sh
python tools/patch.py status
python tools/patch.py apply <30|60|120>
python tools/patch.py restore
```

N'écrit que des **données** : le littéral `0x804167B8`, `mRetraceCount` en
`TDisplay + 0x4C` et le littéral `0x80414904`. Les valeurs d'origine sont
sauvegardées dans `work/patch-backup.json`, ce qui permet de restaurer même
après l'arrêt du script.

`TDisplay` est résolu à l'exécution par `gpApplication + 0x1C` : l'objet est
sur le tas, son adresse change à chaque session.

Ce module **n'applique aucune** des corrections d'objets recensées dans
le plan de départ. Il pose le socle de cadence, pas un mod jouable.

## `tools/test_freefall.py` — régression physique

```sh
python tools/test_freefall.py [hauteur] [palier…]
python tools/test_freefall.py 3000 30 60
```

Téléporte Mario en hauteur par écriture de `Mario + 0x14`, sonde son altitude,
et compte les intégrations de position ainsi que la durée réelle de la chute.
Aucune entrée manette n'est nécessaire, donc le test est entièrement
automatisable. La position est restaurée dans tous les cas.

C'est le contrôle le plus sévère de tout le projet : si la physique dépendait
de la cadence, il le montrerait immédiatement.

## `tools/substep_clock.py` — compter les sous-pas

```sh
python tools/substep_clock.py [nombre-de-sous-pas]
```

Attend un nombre de sous-pas de simulation, en comptant les décréments de
l'accumulateur `TMarDirector + 0x54`. Sert d'**unité de mesure** à toute la
batterie : « après 40 sous-pas » est comparable entre paliers, « après 0,5 s »
ne l'est pas, puisque le nombre d'images couvertes change avec la cadence.

Sondage à ~2,5 µs contre 2,1 ms par sous-pas : aucune transition n'est manquée.
La méthode est **auto-validante** — tout décrément différent de 5 signale un
sondage pris en défaut, et la mesure est alors rejetée, jamais rapportée.

> **Ce qu'il ne sait pas faire.** Il ne voit pas les sous-pas *pendant* une
> transition de scène : `gpMarDirector` peut être nul, et l'adresse est
> résolue une fois pour toutes à la construction. Un objet reconstruit invalide
> l'horloge sans que rien ne le signale.

## `tools/pad.py` — injection d'entrées manette

```sh
python tools/pad.py        # démonstration : fait sauter Mario
```

Écrit directement dans `TMarioGamePad` (résolu par `TMario + 0x4FC`), ce qui
permet de piloter Mario sans manette physique, sans frappe clavier et sans
voler le focus à Dolphin. C'est ce qui rend la batterie automatisable.

Le jeu réécrit l'objet à chaque image depuis la vraie manette : un fil
d'arrière-plan martèle donc les valeurs en continu, à ~400 000 écritures par
seconde contre une relecture par image.

> **Ce qu'il ne sait pas faire.** C'est une **course**, pas un verrou. Elle est
> gagnée très largement mais pas toujours — mesuré : un essai perdu sur trois
> avec une fenêtre de front de 50 ms, aucun avec 200 ms. Un test doit donc
> vérifier que l'action a eu lieu et réessayer (`test_physics.attempt`), jamais
> supposer qu'une image précise a vu l'entrée.
>
> Deux pièges, tous deux payés en mesures fausses avant d'être compris :
> il faut **quelques images de neutre** avant une pression, sans quoi le jeu ne
> voit pas de front ; et le front doit être **borné dans le temps**, sans quoi
> Mario réappuie sur A à l'atterrissage et enchaîne les sauts.

## `tools/test_physics.py` — saut et course

```sh
python tools/test_physics.py [palier…]
python tools/test_physics.py 30 60
```

Saut court, saut long et course tenue, à chaque palier, avec choix automatique
d'une direction dégagée (huit azimuts essayés, le plus long retenu).

Le verdict porte sur les **profils par sous-pas** — suite des vitesses
verticales, suite des vitesses de course — et non sur les hauteurs et
distances, qui dépendent du relief autant que de l'intégrateur.

> **Ce qu'il ne sait pas faire.** Il ne sait pas distinguer un écart de
> physique d'un obstacle. Un test qui diverge doit être confirmé par
> `test_ballistic.py`, qui n'a ni entrée ni contact au sol.
>
> Le critère par profils date du 2026-09-17 et **n'a pas encore été rejoué**
> sur un Dolphin en cours d'exécution.

## `tools/test_ballistic.py` — l'intégrateur seul

```sh
python tools/test_ballistic.py [impulsion] [palier…]
python tools/test_ballistic.py 42 30 60
```

Place Mario à 2500 unités au-dessus du sol, lui impose une vitesse verticale et
relève l'arc, sous-pas par sous-pas. Ni entrée manette, ni décor, ni type de
saut : il ne reste que la gravité.

C'est la mesure de référence du projet pour la question « la physique
dépend-elle de la cadence ? ». Les trois grandeurs qu'elle produit — suite des
vitesses, nombre d'intégrations jusqu'au sommet, altitude du sommet — sont
indépendantes de tout ce qui n'est pas l'intégrateur.

## `tools/dolphin_host.py` — pilotage de l'hôte

```sh
python tools/dolphin_host.py savestate [emplacement]
python tools/dolphin_host.py relaunch [--vi 2.0] [--state <chemin>]
```

Relance Dolphin avec un réglage passé en ligne de commande (`-C`), ce qui est
la seule façon d'atteindre le **VBI Frequency Override** dont dépend le palier
120 : ce réglage vit dans l'hôte, pas dans la MEM1, et Dolphin ne relit pas sa
configuration en cours de partie. `-C` n'écrit rien dans `Dolphin.ini`.

> **Ce qu'il ne sait pas faire.** `savestate` **ne fonctionne pas** depuis un
> agent en ligne de commande : `SendInput` n'atteint pas le bureau interactif
> dans ce contexte — vérifié, même `GetAsyncKeyState` appelé dans le processus
> injecteur ne voit pas la frappe. Sans état sauvegardé, `relaunch` **détruit**
> la partie en cours.

## `tools/second_instance.py` — instance isolée

```sh
python tools/second_instance.py start [--vi 2.0] [--user <répertoire>]
python tools/second_instance.py stop
```

Lance une seconde instance de Dolphin avec son propre répertoire utilisateur,
son propre overclock VI et une copie de la carte mémoire, puis la fait entrer
en jeu **toute seule** — logos, intro, écran titre et sélection de fichier
traversés en martelant A et START par injection mémoire. La session de
l'utilisateur n'est jamais touchée.

Vérifié le 2026-09-15 : arrivée en jeu stable en 92,6 s, sans intervention.

> **Ce qu'il ne sait pas faire.** Il ne sait pas mesurer une cadence en même
> temps qu'une autre instance tourne : les deux se disputent le GPU. C'est la
> raison pour laquelle cette voie est **en attente** et ne doit pas être lancée
> sans accord explicite — voir [`00-journal.md`](00-journal.md), session 4.
>
> Son critère d'arrivée en jeu exige une stabilité de plusieurs secondes : la
> démo d'attraction de l'écran titre rend `gpMarDirector` valide par
> intermittence, et un test instantané conclut à tort.
>
> `stop` arrête **toutes** les instances trouvées, y compris celle de
> l'utilisateur.

---

## Reconstituer l'environnement

```sh
python -m pip install capstone

python tools/gciso.py dol "E:/Jeux Gamecube/Super Mario Sunshine (2002)(Nintendo)(US).iso" \
                      work/dol/GMSE01.dol

curl -sSL -o work/maps/us.map \
  https://raw.githubusercontent.com/DotKuribo/BetterSunshineEngine/master/maps/us.map
```

Contrôle d'intégrité attendu :

| Fichier | SHA-1 |
|---|---|
| `work/dol/GMSE01.dol` | `a6782903ef79d4196c8489ecb1b57decb5b3728f` |
| `work/dol/GMSP01.dol` | `a2edfa86880845f663f6f3b49e27cc9409d202bf` |

`work/` ne contient que des artefacts régénérables — DOL extraits, maps
téléchargées, listings. Rien n'y est à conserver ni à versionner.
