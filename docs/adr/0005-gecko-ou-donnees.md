# ADR 0005 — Livrer le palier 120 par `[OnFrame]`, pas par `[Gecko]` ni par écriture à chaud

- **Date** : 2026-09-22
- **Statut** : accepté

## Contexte

Le palier 120 FPS demande trois écritures, dont deux portent sur des
**instructions** :

| Adresse | Nature | Rôle |
|---|---|---|
| `0x804167B8` | donnée (f32) | horloge logique à 120 Hz |
| `0x802FCB24` | **instruction** | un champ VI par image présentée |
| `0x802887B0` | **instruction** | dégèle le système de particules |

Or l'[ADR 0002](0002-instrumentation.md) a établi qu'une écriture externe dans
une instruction **n'a aucun effet** : Dolphin continue d'exécuter le bloc JIT
déjà compilé. Les correctifs de code sont donc hors de portée de
`tools/dolphin.py`, quel que soit leur intérêt.

Trois voies étaient ouvertes.

## Voies essayées

### 1. Section `[Gecko]` du profil par jeu — échec

Les deux lignes de cadence ont d'abord été livrées en `[Gecko]`, sur le modèle
du `$60FPS` de `gamemasterplc`, avec le nom repris en `[Gecko_Enabled]`.

Jeu démarré, `0x80001800` était **entièrement nul** : aucun codehandler
injecté, donc aucun code actif. La section `[Core]` du *même fichier* avait
pourtant bien pris effet — l'overclock VI était en vigueur, le jeu tournait à
double vitesse. `EnableCheats = True` était posé globalement.

**Cause non élucidée.** Piste non vérifiée : la case « Enable Cheats » de
l'interface, qui conditionnerait le codehandler sans conditionner `[Core]`.

### 2. Écritures de données à chaud — fonctionne, mais incomplet

`tools/keep120.py` pose `0x804167B8 = 2.0f` et `mRetraceCount = 1`, ce qui
donne la bonne cadence sans toucher une instruction. **Mesuré : 119,80
images/s, 119,80 sous-pas/s.**

Mais cette voie ne peut pas dégeler les particules, qui demandent un correctif
de code. Et elle exige un processus résident.

### 3. Section `[OnFrame]` du profil par jeu — retenue

Le PatchEngine de Dolphin applique ces écritures **à l'amorçage, avant que le
JIT ne compile le bloc concerné** : un correctif d'instruction y prend donc
effet, contrairement à une écriture externe.

Vérifié le 2026-09-22 : les trois valeurs relues en mémoire après redémarrage,
et validation à **119,83 images/s, simulation à 120,00 Hz, 100,0 % de la
vitesse correcte**.

## Décision

Livrer le profil en section `[OnFrame]` du fichier
`GameSettings/GMSE01.ini` du répertoire utilisateur de Dolphin.

Conserver `tools/keep120.py` comme **filet de sécurité** — il pose la cadence
par écriture de données si le profil hôte ne s'applique pas — et non comme
mécanisme principal.

## Le cumul à éviter

Le `nop` de `0x802FCB24` et `mRetraceCount = 1` mènent tous deux à un champ par
image, **mais ils s'additionnent** : neutralisée, `waitForRetrace` consomme
`count - 1` champs par appel (§ 3.1 de [`../01-mecanismes.md`](../01-mecanismes.md)).
Avec `count = 1`, cela fait **zéro** — plus aucune attente de balayage, le jeu
s'emballe à la vitesse de l'hôte.

`keep120.py` et `validate_120.py` lisent donc `0x802FCB24` avant de décider du
compte attendu. La garde a fonctionné du premier coup en situation réelle.

## Ce que la décision coûte

- **Le profil ne prend effet qu'à l'amorçage.** Changer de palier demande un
  redémarrage du jeu, là où les écritures de données étaient immédiates. Pour
  les campagnes de mesure comparatives, `patch.py` et `keep120.py` restent les
  bons outils.
- **Une ligne du profil n'est pas correcte par construction** :
  `0x802887B0 → li r23, 1` fait avancer les particules à 120 Hz au lieu de 60.
  Voir [`../01-mecanismes.md`](../01-mecanismes.md) et le § du profil.
