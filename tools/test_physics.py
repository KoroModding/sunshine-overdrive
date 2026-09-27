"""Batterie de régression physique — saut et course — à plusieurs cadences.

Toutes les grandeurs mesurées ici **ne doivent pas bouger** d'un palier à
l'autre. L'accumulateur maintient la simulation à 120 Hz quelle que soit la
cadence d'affichage ; si une hauteur de saut ou une vitesse de course changeait,
c'est que le découplage est rompu.

Le plan de départ est formel sur la conduite à tenir alors : **ne pas corriger en
retouchant `TJumpParams`, `TRunParams` ou les `.prm`**. Un écart désigne une
cause à chercher, pas un symptôme à compenser.

Trois pièges méthodologiques, et comment ils sont traités
---------------------------------------------------------
**1. Le mur.** Une première version de ce test mesurait Mario lancé contre un
décor : sa vitesse se figeait à 6,00 au lieu des ~32 atteints en terrain libre,
et les comparaisons ne mesuraient que la géométrie. La direction de course est
donc choisie automatiquement au début (`probe_open_direction`), en essayant huit
azimuts et en retenant celui qui fait parcourir le plus de distance.

**2. L'horloge murale.** Chronométrer « pendant 0,5 s » ne couvre pas le même
nombre d'images à 30 et à 60 FPS, et l'injection d'entrées est une course dont
le taux de réussite dépend du nombre d'images. Mesurée ainsi, une hauteur de
saut variait de 15 % — un artefact d'instrumentation, pas de physique.

Tout est donc indexé sur le **sous-pas** (`substep_clock.py`) : durée de
pression comme fenêtre de mesure. « Après 40 sous-pas » est comparable entre
paliers ; « après 0,5 s » ne l'est pas.

**3. Le critère de comparaison lui-même.** Une hauteur de saut et une distance
parcourue sont des grandeurs **de sortie** : elles dépendent du relief autant
que de l'intégrateur. Mesuré le 2026-09-15 près d'un mur de Delfino Plaza :
96,60 à 30 FPS contre 81,59 à 60 FPS, de façon parfaitement reproductible, avec
la **même** impulsion de départ (`vy` = 42) et la même indépendance à la durée
de maintien. Ce n'est pas la gravité qui change — l'arc balistique libre est
rigoureusement identique aux deux paliers, voir `test_ballistic.py` — c'est le
décor qui intervient.

Le verdict de ce test porte donc sur les **profils** : la suite des vitesses
verticales du saut, sous-pas par sous-pas, et la suite des vitesses de course.
Deux paliers découplés doivent produire la même suite. Les hauteurs et
distances restent affichées, mais à titre **indicatif** : elles n'emportent
aucun verdict.

Cette révision du critère date du 2026-09-17. Ses fonctions pures — réduction
d'une suite, recalage sur l'événement, comparaison — sont vérifiées hors ligne,
mais l'ensemble **n'a pas encore été rejoué sur un Dolphin en cours
d'exécution.** Le relevé de `04-tests.md` reste celui de l'ancien critère, avec
sa fausse alarme signalée comme telle.

Usage
-----
    python test_physics.py [palier…]
    python test_physics.py 30 60
"""

from __future__ import annotations

import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import patch  # noqa: E402
from dolphin import Dolphin  # noqa: E402
from pad import Pad  # noqa: E402
from substep_clock import SubstepClock  # noqa: E402

GP_MARIO = 0x8040E0E8
OFF_POS = 0x10
OFF_VEL = 0xA4  # d'après gpMarioSpeedX/Y/Z

MAX_ATTEMPTS = 5

# Durée du front de pression. Volontairement courte : le maintien du bouton est
# assuré par `+0x18`, et rejouer le front à chaque image ferait enchaîner les
# sauts (voir `pad.press`). La durée du saut, elle, est fixée en sous-pas.
EDGE_WINDOW = 0.12


class Subject:
    """Mario : lecture d'état et remise en place."""

    def __init__(self, dolphin: Dolphin) -> None:
        self.dolphin = dolphin
        self.address = dolphin.u32(GP_MARIO)
        if not dolphin.is_valid_pointer(self.address):
            raise RuntimeError("Mario introuvable — le jeu est-il dans un niveau ?")
        self.home = self.position()

    def position(self) -> tuple[float, float, float]:
        return struct.unpack(">fff", self.dolphin.read(self.address + OFF_POS, 12))

    def velocity(self) -> tuple[float, float, float]:
        return struct.unpack(">fff", self.dolphin.read(self.address + OFF_VEL, 12))

    def speed(self) -> float:
        vx, _, vz = self.velocity()
        return math.hypot(vx, vz)

    def y(self) -> float:
        return self.dolphin.f32(self.address + OFF_POS + 4)

    def reset(self) -> None:
        self.dolphin.write(self.address + OFF_POS, struct.pack(">fff", *self.home))
        self.dolphin.write(self.address + OFF_VEL, struct.pack(">fff", 0.0, 0.0, 0.0))


def distinct(values: list[float]) -> list[float]:
    """Réduit une suite sur-échantillonnée à ses valeurs successives distinctes.

    Le sondage tourne à ~400 000 lectures par seconde contre 120 intégrations :
    chaque valeur est vue des centaines de fois. Ne garder que les changements
    rend la suite comparable entre paliers — c'est la suite des états de la
    simulation, plus celle du sondage.
    """
    reduced: list[float] = []
    for value in values:
        rounded = round(value, 4)
        if not reduced or rounded != reduced[-1]:
            reduced.append(rounded)
    return reduced


def from_onset(values: list[float], threshold: float = 0.0) -> list[float]:
    """Coupe la suite avant son premier dépassement de `threshold`.

    Recadre le profil sur l'**événement** plutôt que sur le démarrage du
    sondage. L'entrée injectée n'est pas vue à la même image selon la cadence :
    le nombre de valeurs neutres qui précèdent l'impulsion varie donc d'un
    palier à l'autre, et deux profils rigoureusement identiques sembleraient
    diverger dès leur premier élément.
    """
    for index, value in enumerate(values):
        if value > threshold:
            return values[index:]
    return []


def compare_profiles(a: list[float], b: list[float]) -> tuple[bool, int, int]:
    """Compare deux suites. Retourne (identiques, longueur comparée, index de divergence)."""
    n = min(len(a), len(b))
    for index in range(n):
        if a[index] != b[index]:
            return False, n, index
    return True, n, -1


def prepare(subject: Subject, pad: Pad) -> None:
    """Replace Mario et laisse le jeu voir la manette au neutre.

    Les deux remises en place encadrent la stabilisation : la première pour que
    Mario ne parte pas de l'état laissé par l'essai précédent, la seconde parce
    que la physique a pu le déplacer pendant qu'on attendait.
    """
    subject.reset()
    pad.settle(0.7)
    subject.reset()
    time.sleep(0.25)


def probe_open_direction(subject: Subject, pad: Pad) -> tuple[float, float]:
    """Cherche la direction de stick qui dégage le plus de distance."""
    best = (0.0, (0.0, 1.0))
    for i in range(8):
        angle = i * math.pi / 4
        direction = (round(math.sin(angle), 3), round(math.cos(angle), 3))
        prepare(subject, pad)
        start = subject.position()
        pad.stick(*direction)
        time.sleep(1.2)
        end = subject.position()
        pad.settle(0.4)
        distance = math.dist((start[0], start[2]), (end[0], end[2]))
        if distance > best[0]:
            best = (distance, direction)
    return best[1]


def jump(subject: Subject, pad: Pad, clock: SubstepClock, hold_substeps: int):
    """Saut avec A maintenu pendant `hold_substeps` sous-pas.

    Retourne un relevé, ou None si l'entrée injectée n'a pas été vue :

        hauteur   apogée relative — **indicative**, dépend du relief
        vy max    impulsion initiale, discrimine le type de saut
        profil    suite des vitesses verticales, sous-pas par sous-pas,
                  recalée sur l'impulsion. C'est elle qui porte le verdict :
                  elle ne dépend que de l'intégrateur tant que Mario ne
                  touche rien.
    """
    prepare(subject, pad)
    base = subject.y()

    pad.press("A", window=EDGE_WINDOW)
    samples, valid = clock.sample_while(
        hold_substeps, lambda: (subject.y(), subject.velocity()[1])
    )
    pad.release("A")
    more, valid_more = clock.sample_while(
        140 - hold_substeps, lambda: (subject.y(), subject.velocity()[1])
    )
    pad.settle(0.4)

    if not (valid and valid_more):
        return None
    heights = [y for y, _ in samples + more]
    speeds = [v for _, v in samples + more]
    peak = max(heights) - base
    if peak <= 10.0:
        return None
    return {"hauteur": peak, "vy max": max(speeds),
            "profil": from_onset(distinct(speeds))}


def run(subject: Subject, pad: Pad, clock: SubstepClock,
        direction: tuple[float, float], substeps: int):
    """Course tenue pendant `substeps` sous-pas.

    Retourne un relevé, ou None si l'entrée n'a pas été vue :

        vitesse max   palier de vitesse atteint
        distance      **indicative** — un obstacle la tronque
        profil        suite des vitesses horizontales, sous-pas par sous-pas,
                      recalée sur le démarrage. C'est la courbe d'accélération
                      de `TRunParams` ; elle porte le verdict.
    """
    prepare(subject, pad)
    start = subject.position()

    pad.stick(*direction)
    samples, valid = clock.sample_while(substeps, subject.speed)
    end = subject.position()
    pad.settle(0.5)

    if not valid:
        return None
    distance = math.dist((start[0], start[2]), (end[0], end[2]))
    if distance <= 10.0:
        return None
    return {"vitesse max": max(samples), "distance": distance,
            "profil": from_onset(distinct(samples))}


def attempt(function, *args):
    """Réessaie tant que l'entrée injectée n'a pas été vue.

    L'injection gagne la course dans la grande majorité des cas, pas dans tous.
    Réessayer transforme un tirage en mesure ; sans cela un essai perdu se
    lirait comme un écart de physique.
    """
    for _ in range(MAX_ATTEMPTS):
        result = function(*args)
        if result is not None:
            return result
    return None


def _main(argv: list[str]) -> int:
    tiers = [int(a) for a in argv[1:]] or [30, 60]
    dolphin = Dolphin()
    subject = Subject(dolphin)
    clock = SubstepClock(dolphin)

    print(f"Mario 0x{subject.address:08X}, départ "
          f"({subject.home[0]:g}, {subject.home[1]:g}, {subject.home[2]:g})")

    results: dict[int, dict] = {}
    try:
        with Pad(dolphin) as pad:
            direction = probe_open_direction(subject, pad)
            print(f"direction dégagée retenue : ({direction[0]:+.3f}, {direction[1]:+.3f})")
            print()

            for fps in tiers:
                patch.apply(dolphin, fps, gate=False)
                time.sleep(0.8)
                scalars: dict = {}
                profiles: dict = {}

                short = attempt(jump, subject, pad, clock, 6)
                long_ = attempt(jump, subject, pad, clock, 40)
                sprint = attempt(run, subject, pad, clock, direction, 120)

                scalars["saut court — hauteur"] = short["hauteur"] if short else None
                scalars["saut long — hauteur"] = long_["hauteur"] if long_ else None
                scalars["saut long — vy max"] = long_["vy max"] if long_ else None
                scalars["course — vitesse max"] = sprint["vitesse max"] if sprint else None
                scalars["course — distance"] = sprint["distance"] if sprint else None

                profiles["saut long — profil vy"] = long_["profil"] if long_ else None
                profiles["course — profil vitesse"] = sprint["profil"] if sprint else None

                results[fps] = {"scalaires": scalars, "profils": profiles}
                print(f"{fps} FPS mesuré")
    finally:
        patch.restore(dolphin)
        time.sleep(0.4)
        subject.reset()
        print()
        print("Correctifs et position restaurés.")

    if len(results) >= 2:
        first, last = list(results)[0], list(results)[-1]

        # Grandeurs de sortie : affichées, mais sans valeur de verdict. Une
        # hauteur d'apogée mesure autant le plafond que la gravité.
        print()
        print("Grandeurs de sortie — indicatives, sensibles au relief")
        print(f"{'grandeur':<24} {f'{first} FPS':>11} {f'{last} FPS':>11} {'écart':>9}")
        print("-" * 58)
        for key in results[first]["scalaires"]:
            a = results[first]["scalaires"][key]
            b = results[last]["scalaires"][key]
            if a is None or b is None:
                print(f"{key:<24} {'échec':>11} {'échec':>11} {'—':>9}")
                continue
            drift = abs(a - b) / a * 100 if a else 0.0
            print(f"{key:<24} {a:>11.2f} {b:>11.2f} {drift:>8.2f}%")

        # Profils : le vrai critère. Même état de départ et même entrée dans
        # une simulation découplée ⇒ même suite d'états, à l'identique.
        print()
        print("Profils par sous-pas — c'est ici que se joue le verdict")
        verdict_ok = True
        measured = False
        for key in results[first]["profils"]:
            a = results[first]["profils"][key]
            b = results[last]["profils"][key]
            if not a or not b:
                print(f"  {key:<26} échec de mesure")
                continue
            measured = True
            same, length, index = compare_profiles(a, b)
            if same:
                print(f"  {key:<26} identiques sur {length} intégrations")
            else:
                verdict_ok = False
                print(f"  {key:<26} DIVERGENCE à l'intégration {index} : "
                      f"{a[index]} contre {b[index]}")

        print()
        if not measured:
            print("=> aucun profil mesuré : rien n'est conclu.")
        elif verdict_ok:
            print("=> la physique est INDÉPENDANTE de la cadence.")
        else:
            print("=> ÉCART SIGNIFICATIF — chercher la cause, ne pas retoucher "
                  "les .prm.")
            print("   Confirmer d'abord par test_ballistic.py, qui mesure "
                  "l'intégrateur seul, sans entrée ni contact au sol.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
