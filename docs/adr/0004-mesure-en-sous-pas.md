# ADR 0004 — Mesurer en sous-pas, et juger sur des profils

- **Date** : 2026-09-15, révisé le 2026-09-17
- **Statut** : accepté

## Contexte

Tout le projet repose sur une comparaison : *la même grandeur, mesurée à 30 et
à 60 FPS, doit-elle bouger ?* La validité de la réponse dépend entièrement de
la façon dont on cadre la mesure.

Les premières comparaisons ont été cadrées à l'horloge murale — « relever
pendant 0,5 seconde ». Résultat : des écarts de 15 % sur une hauteur de saut,
qui ne mesuraient rien d'autre que l'instrumentation.

## Décision 1 — l'unité de mesure est le sous-pas

| Unité | Défaut |
|---|---|
| seconde | ne couvre pas le même nombre d'images selon la cadence, et le taux de réussite de l'injection d'entrées varie avec ce nombre |
| image rendue | c'est la variable que l'on fait justement changer |
| champ VI | stable, mais ne dit rien du nombre d'intégrations exécutées |
| **sous-pas** | **120 Hz constants par construction, quelle que soit la cadence** |

« L'état après 40 sous-pas » est une grandeur comparable entre paliers.
« L'état après 0,5 s » ne l'est pas.

Le compte se fait sans point d'arrêt, en observant les décréments de
l'accumulateur `TMarDirector + 0x54` : il perd exactement 5 unités par
sous-pas. La mesure reste auto-validante — tout décrément différent de 5
signale un sondage pris en défaut, et la mesure est rejetée
(voir [`0002-instrumentation.md`](0002-instrumentation.md)).

## Décision 2 — le verdict porte sur des profils, pas sur des scalaires

Corollaire découvert par l'échec, le 2026-09-15.

Une fois l'unité corrigée, le test annonçait encore un écart : hauteur de saut
96,60 contre 81,59, reproductible, alors que l'impulsion initiale était
identique (`vy` = 42) aux deux paliers. Trois hypothèses ont été écartées par
la mesure — aléa de l'injection, type de saut différent, résolution du
relâchement de A.

L'explication tenait au **décor** : un arc libre depuis `vy` = 42 culmine à
225,75 ; les deux sauts plafonnaient bien plus bas parce que Mario tapait un
surplomb. La mesure était juste, la grandeur était mal choisie.

Une hauteur d'apogée et une distance parcourue sont des grandeurs **de
sortie** : elles agrègent l'intégrateur *et* la géométrie du niveau. Ce qui
distingue les deux paliers doit être cherché dans une grandeur qui ne dépend
que de l'intégrateur :

- la **suite des vitesses**, sous-pas par sous-pas ;
- le **nombre d'intégrations** jusqu'à un événement donné.

Deux paliers découplés produisent la même suite, à l'identique. C'est vérifié :
90 intégrations identiques entre 30 et 60 FPS
([`../04-tests.md`](../04-tests.md)).

## Conséquences

- `tools/substep_clock.py` fournit l'unité ; toute la batterie l'utilise.
- `tools/test_ballistic.py` est la mesure de référence : impulsion imposée en
  altitude, ni entrée ni contact, rien que l'intégrateur.
- `tools/test_physics.py` conserve hauteurs et distances mais ne leur fait plus
  porter le verdict. **Cette révision n'a pas encore été rejouée** sur un
  Dolphin en cours d'exécution.
- Règle générale pour la suite : **avant de conclure à un écart de physique,
  mesurer la variance intra-palier.** Un écart entre paliers ne veut rien dire
  tant que la mesure varie déjà d'un essai à l'autre au sein d'un même palier.
