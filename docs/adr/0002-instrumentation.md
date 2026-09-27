# ADR 0002 — Instrumenter par accès mémoire externe, pas par le débogueur

- **Date** : 2026-09-15
- **Statut** : accepté

## Contexte

Le plan de départ décrit la phase 0 en termes de débogueur Dolphin : activer le mode
*Debugging*, charger `us.map`, poser un point d'arrêt mémoire en écriture sur
`TMarDirector + 0x54` ou sur le `mVel.y` de Mario, et compter les
déclenchements.

Cette méthode suppose un opérateur humain devant l'interface pour chaque
mesure. Or les mesures utiles sont nombreuses et répétitives : trois paliers ×
plusieurs grandeurs, plus les comparaisons avant/après correctif. Chaque
aller-retour avec un opérateur coûte du temps et introduit des variations qui
polluent la comparaison.

## Décision

Instrumenter depuis un processus tiers, en lisant et écrivant directement la
MEM1 émulée par `ReadProcessMemory` / `WriteProcessMemory`.

## Raisons

1. **Automatisable de bout en bout.** Une campagne aux trois paliers avec
   restauration s'exécute en une commande.
2. **Comparaisons valides.** Le même script, la même durée d'échantillonnage et
   le même état de départ pour chaque palier.
3. **Rapide.** ~405 000 lectures par seconde, soit une période de 2,5 µs. Un
   sous-pas dure 2,1 ms : la marge est de trois ordres de grandeur, aucune
   transition n'est manquée.
4. **Auto-validante.** Voir ci-dessous — c'est l'argument décisif.
5. **Sans interaction avec l'émulateur.** Ni point d'arrêt, ni pause, ni
   ralentissement : le jeu tourne normalement pendant la mesure.

## L'auto-validation remplace la certitude du point d'arrêt

Un point d'arrêt ne rate rien par construction ; un sondage, si. C'est
l'objection sérieuse à cette approche, et elle se traite par la structure même
de la grandeur observée.

L'accumulateur ne varie que de deux façons : `+vsyncRate` au début d'une image,
`-5` à chaque sous-pas. Si le sondage rate une transition, l'écart observé
n'est plus 5 mais 10 ou 15. **Le script vérifie donc que tout décrément vaut
exactement 5 et que tout incrément vaut exactement la même valeur** ; si une
seule transition anormale apparaît, la mesure est rejetée au lieu d'être
rapportée.

En pratique, sur 750 transitions relevées à 30 FPS, les 600 décréments valaient
tous 5 et les 150 incréments tous 20.

## Conséquence majeure : données oui, code non

La mesure a mis au jour une limite qu'il faut connaître avant d'écrire le
moindre correctif.

Dolphin compile le code PowerPC en code natif et met les blocs en cache. Une
écriture externe dans une **instruction** n'invalide pas le cache :

> Écrire `nop` en `0x802FCB24` modifie bien la MEM1 (relecture confirmée) mais
> **ne change rien au comportement** — le jeu continue de présenter 30 images
> par seconde.

Une écriture dans une **donnée** prend effet immédiatement, puisque le jeu la
relit à chaque exécution.

Cela **écarte** le correctif de `gamemasterplc` (`042FCB24 60000000`) pour tout
usage à chaud, et impose de passer par `mRetraceCount`, qui est une donnée en
`TDisplay + 0x4C` et produit exactement le même effet (démontré au § 3.1 de
[`../01-mecanismes.md`](../01-mecanismes.md), puis vérifié expérimentalement).

C'est aussi la voie que prend BetterSunshineEngine — qui s'exécute, lui, à
l'intérieur du jeu et n'a donc pas ce problème. La convergence est rassurante.

## Portée et limites

- **Les correctifs appliqués ainsi ne survivent pas** à un redémarrage du jeu,
  et ne constituent pas un mod distribuable. L'objet est la mesure, pas la
  livraison. Un mod réel passera par Kuribo / BetterSunshineEngine.
- **Les adresses d'objets sont dynamiques.** `TDisplay`, `TMarDirector` et
  Mario sont sur le tas ; leurs adresses changent d'une session à l'autre. Tout
  est donc résolu à l'exécution depuis les globales `gpApplication`,
  `gpMarDirector` et `gpMarioOriginal`, jamais codé en dur.
- **Les réglages hôtes de Dolphin restent hors de portée.** Le VBI Frequency
  Override, nécessaire au palier 120 FPS, n'est pas dans la MEM1. Il faudra une
  autre voie.
- **Windows uniquement.** `tools/dolphin.py` s'appuie sur l'API Win32.

## Alternative écartée

**Injecter du code PowerPC** dans la zone Gecko libre (`0x80001800`–`0x80003000`,
vérifiée entièrement nulle) pour poser des compteurs exacts, à la manière d'un
code `C2`. Écartée : elle se heurte au même cache JIT que toute écriture de
code, et le sondage auto-validé donne déjà des résultats exacts sans modifier
le jeu.
