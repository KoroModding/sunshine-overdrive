# ADR 0001 — Cibler GMSE01 (NTSC-U)

- **Date** : 2026-09-15
- **Statut** : accepté

## Contexte

Deux images du jeu sont disponibles dans `E:\Jeux Gamecube` :

| Identifiant | Région |
|---|---|
| `GMSE01` | NTSC-U |
| `GMSP01` | PAL |

Au départ de la session, seule l'image PAL était présente. L'image US a été
ajoutée par l'utilisateur après signalement de l'écart avec le plan.

Le plan de départ est écrit pour GMSE01 : toutes ses adresses, ses
références à BetterSunshineEngine et son code Gecko de référence sont US.

## Décision

Le projet cible **GMSE01 (NTSC-U, révision 0)**.

## Raisons

1. **L'écosystème est US.** BetterSunshineEngine ne supporte que GMSE01, et le
   plan impose de dépendre de son API exportée plutôt que de réimplémenter ses
   correctifs. Cibler PAL rendrait cette règle inapplicable.
2. **Les symboles sont US.** `maps/us.map` (15 107 symboles) et les symboles
   Corona (4 439) couvrent GMSE01. Aucune table équivalente n'existe pour PAL :
   tout le travail se ferait sur des adresses nues.
3. **NTSC évite une complication d'horloge.** En PAL, `VIGetTvFormat()` renvoie
   `VI_PAL` et l'horloge logique part de 50 Hz au lieu de 60. Les valeurs de
   littéral de BSE (`0.5` / `1.0` / `2.0`) ne s'y transposent pas — il faudrait
   `0.5` / `1.2` / `2.4`. Voir [`../05-regions.md`](../05-regions.md).
4. **Le palier 120 FPS est plus net.** 60 Hz × 2 = 120 tombe juste ;
   50 Hz demanderait un facteur non entier.

## Conséquences

- Le DOL de référence est `work/dol/GMSE01.dol`,
  SHA-1 `a6782903ef79d4196c8489ecb1b57decb5b3728f`.
- L'image PAL reste extraite (`work/dol/GMSP01.dol`) **à titre documentaire
  seulement** : elle a servi à établir la correspondance d'adresses qui corrige
  l'attribution « JP » erronée relevée dans le plan, et sert de contre-épreuve
  pour valider que l'outillage ne code aucune adresse en dur.
- L'outillage reste malgré tout indépendant de la région : les bases `r2`/`r13`
  sont lues dans le DOL analysé, jamais codées en dur. Un support PAL ultérieur
  ne demanderait pas de réécrire les outils, seulement de refaire les mesures.
- Un éventuel support PAL constituerait un ADR distinct.

## Alternative écartée

**Cibler PAL** pour coller à l'image initialement fournie. Écartée : le coût est
un portage complet des symboles et des correctifs sans base existante, pour
aucun gain, alors que se procurer l'image US supprime entièrement le problème —
ce qui a été fait.
