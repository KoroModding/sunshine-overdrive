# ADR 0003 — Injecter les entrées manette en mémoire, pas au clavier

- **Date** : 2026-09-15
- **Statut** : accepté

## Contexte

La moitié de la batterie de régression exige des entrées : saut, triple saut,
plongeon, course, glissade, hover. Sans moyen de les produire depuis un script,
ces tests demandent un opérateur humain à chaque palier — donc des entrées
différentes à chaque essai, donc des comparaisons sans valeur.

Le plan de départ prévoyait l'enregistrement `.dtm` de Dolphin (Movie → Record Input)
pour rejouer les mêmes entrées à chaque palier. C'est la solution correcte sur
le papier ; elle suppose néanmoins d'enregistrer à la main, de charger le
fichier par l'interface, et de relancer la partie à chaque essai.

## Options

| Option | Pourquoi elle a été écartée, ou retenue |
|---|---|
| **manette physique** | non scriptable ; entrées différentes à chaque essai |
| **`.dtm`** | correcte, mais passe par l'interface à chaque essai et ne peut pas être pilotée depuis le script qui mesure |
| **frappes clavier** (`SendInput`) | **impossible** — voir ci-dessous |
| **injection dans `TMarioGamePad`** | **retenue** |

## Le clavier ne marche pas dans ce contexte

Mesuré le 2026-09-15 : `SendInput` n'atteint pas le bureau interactif depuis un
agent en ligne de commande. Même `GetAsyncKeyState`, appelé dans le processus
qui vient d'injecter la frappe, ne la voit pas. Ni le forçage de focus
(`AttachThreadInput` + `SetForegroundWindow`), ni le choix de la fenêtre —
rendu ou principale — n'y changent quoi que ce soit.

C'est une limite de contexte d'exécution, pas un défaut de Dolphin. Toute
automatisation clavier est donc exclue du projet.

## Décision

Écrire directement dans l'objet `TMarioGamePad`, résolu par `TMario + 0x4FC`,
avec un fil d'arrière-plan qui martèle les valeurs en continu.

Offsets et preuves : [`../02-adresses.md`](../02-adresses.md).

## Ce que cette décision coûte

C'est une **course**, pas un verrou. Le jeu réécrit l'objet à chaque image
depuis la vraie manette, puis le consulte un peu plus tard ; l'injection ne
l'emporte que si une écriture tombe entre les deux. À ~400 000 écritures par
seconde contre une relecture par image, la course est gagnée très largement —
mais pas toujours.

Trois conséquences, toutes payées en mesures fausses avant d'être comprises :

1. **Un test doit vérifier que l'action a eu lieu et réessayer.** Sans cela, un
   essai perdu se lit comme un écart de physique. Mesuré : un échec sur trois
   avec une fenêtre de front de 50 ms, aucun avec 200 ms.
2. **Il faut quelques images de neutre avant une pression.** Le jeu tient sa
   propre mémoire de l'état précédent pour détecter les fronts ; sans neutre
   préalable, la pression injectée n'en est pas un. C'est la différence entre
   un saut et rien du tout.
3. **Le front doit être borné dans le temps.** Rejouer le front à chaque image
   revient à réappuyer sur A dès l'atterrissage : Mario enchaîne double et
   triple saut. Mesuré avec un front permanent, la hauteur d'un même saut
   variait de 73,79 à 140,0 et la `vy` initiale sautait entre 41, 42 et 52 —
   trois types de saut différents dans un seul relevé.

Et une conséquence de principe : **une mesure doit porter sur un résultat**
(hauteur atteinte, distance parcourue, profil de vitesse), jamais sur
l'hypothèse qu'une image précise a vu l'entrée.

## Ce que cette décision permet

Elle a une portée que le `.dtm` n'a pas : elle fonctionne **dans les menus**,
où Mario n'existe pas encore — les manettes se retrouvent alors par leur
pointeur de vtable (`0x803DF44C`). C'est ce qui rend une instance de Dolphin
pilotable depuis les logos jusqu'au jeu sans aucune intervention, et c'est la
seule raison pour laquelle `second_instance.py` est possible.
