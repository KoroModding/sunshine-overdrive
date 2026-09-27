"""Horloge de sous-pas : synchroniser une mesure sur la simulation, pas sur le mur.

Pourquoi
--------
Comparer deux cadences d'affichage en chronométrant à l'horloge murale est
piégeux. Une mesure « pendant 2,5 s » ne couvre pas le même nombre d'images
rendues à 30 et à 60 FPS, et l'injection d'entrées (voir `pad.py`) est une
course dont le taux de réussite dépend justement du nombre d'images. Les écarts
observés mesurent alors l'instrumentation, pas le jeu.

Or la simulation, elle, avance à 120 Hz constants quelle que soit la cadence.
Indexer les mesures sur le **sous-pas** élimine donc la variable d'affichage :
« l'état après 60 sous-pas » est une grandeur comparable entre paliers, là où
« l'état après 0,5 s » ne l'est pas.

Comment
-------
L'accumulateur `TMarDirector + 0x54` perd exactement 5 unités par sous-pas et
gagne `vsyncRate` au début de chaque image. Compter ses décréments compte donc
les sous-pas, sans point d'arrêt ni hook.

Le sondage tourne à ~2,5 µs contre 2,1 ms par sous-pas : aucune transition
n'est manquée. La méthode reste **auto-validante** — tout décrément qui ne vaut
pas 5 signale un sondage pris en défaut, et `wait` le signale au lieu de rendre
un compte faux.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MAR_DIRECTOR = 0x8040E178
OFF_ACCUMULATOR = 0x54
QUANTUM = 5


class SubstepClock:
    """Compteur de sous-pas fondé sur l'accumulateur du directeur."""

    def __init__(self, dolphin: Dolphin) -> None:
        self.dolphin = dolphin
        director = dolphin.u32(GP_MAR_DIRECTOR)
        if not dolphin.is_valid_pointer(director):
            raise RuntimeError("TMarDirector introuvable")
        self.address = director + OFF_ACCUMULATOR

    def wait(self, count: int, timeout: float = 20.0) -> tuple[int, bool]:
        """Attend `count` sous-pas.

        Retourne (sous-pas comptés, sondage valide). Le drapeau tombe à faux si
        un décrément autre que 5 est observé : la mesure a alors sauté au moins
        un sous-pas et ne doit pas être utilisée.
        """
        seen = 0
        valid = True
        previous = self.dolphin.s32(self.address)
        deadline = time.perf_counter() + timeout

        while seen < count and time.perf_counter() < deadline:
            value = self.dolphin.s32(self.address)
            if value < previous:
                step = previous - value
                if step != QUANTUM:
                    valid = False
                seen += step // QUANTUM
            previous = value

        return seen, valid

    def sample_while(self, count: int, probe, timeout: float = 20.0):
        """Échantillonne `probe()` pendant `count` sous-pas.

        Retourne (liste des valeurs, sondage valide). `probe` est appelé aussi
        vite que possible ; le découpage temporel reste libre, seule la borne
        de fin est synchronisée sur la simulation.
        """
        values = []
        seen = 0
        valid = True
        previous = self.dolphin.s32(self.address)
        deadline = time.perf_counter() + timeout

        while seen < count and time.perf_counter() < deadline:
            value = self.dolphin.s32(self.address)
            if value < previous:
                step = previous - value
                if step != QUANTUM:
                    valid = False
                seen += step // QUANTUM
            previous = value
            values.append(probe())

        return values, valid


def _main(argv: list[str]) -> int:
    count = int(argv[1]) if len(argv) > 1 else 120
    dolphin = Dolphin()
    clock = SubstepClock(dolphin)

    start = time.perf_counter()
    seen, valid = clock.wait(count)
    elapsed = time.perf_counter() - start

    print(f"{seen} sous-pas en {elapsed:.3f} s -> {seen / elapsed:.2f} Hz")
    print("sondage valide" if valid else "SONDAGE PRIS EN DÉFAUT — mesure à rejeter")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
