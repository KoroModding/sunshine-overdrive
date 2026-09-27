"""Validation du profil 120 FPS livré dans `deliver/`.

Le profil a deux moitiés — l'overclock VI côté hôte, les écritures de cadence
côté jeu — et chacune est muette sur l'autre. Ce script les contrôle séparément puis
rend un verdict, pour qu'une moitié manquante ne passe pas pour un succès.

Ce qui est contrôlé
-------------------
1. **Côté jeu, par lecture directe.** Le littéral en 0x804167B8 doit valoir
   2.0f, et la présentation doit consommer exactement un champ VI par image —
   ce que donnent deux correctifs différents, qui ne doivent pas se cumuler.
2. **Côté hôte, par mesure.** `VIOverclock` ne se lit pas dans la MEM1 : il n'y
   est pas. Son seul témoin observable est la cadence de présentation. Un VI à
   2× donne 119,88 images par seconde, un VI au taux nominal plafonne à 59,94.
   C'est ce qui distingue « 120 FPS » de « mi-vitesse ».
3. **La vitesse de simulation**, qui est l'objet de tout le projet : 120 sous-pas
   par seconde, quelle que soit la cadence d'affichage.

Le critère
----------
La simulation doit tourner à 120 Hz ± 2 %. C'est la grandeur qui décide, pas le
nombre d'images : un jeu qui affiche 119 images par seconde en n'en simulant que
60 tourne à mi-vitesse, et c'est précisément le piège du palier 120.

Attente du jeu
--------------
Le profil ne prenant effet qu'à l'amorçage, ce script sait **attendre** que le
jeu démarre : il peut être lancé avant, puis l'utilisateur démarre la partie.
Le critère d'arrivée exige une validité *stable* de `gpMarDirector` et
`gpMarioOriginal` — un test instantané conclut « en jeu » pendant la démo
d'attraction de l'écran titre (impasse relevée en session 3).

Usage
-----
    python validate_120.py [--wait <secondes>] [--duree <secondes>]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402
from measure_substeps import analyse, sample  # noqa: E402

GP_MAR_DIRECTOR = 0x8040E178
GP_MARIO = 0x8040E0E8
OFF_ACCUMULATOR = 0x54

LITERAL_VSYNC = 0x804167B8
PATCH_SITE_RETRACE = 0x802FCB24
NOP = 0x60000000
GP_APPLICATION = 0x803E9700
OFF_DISPLAY = 0x1C
OFF_RETRACE_COUNT = 0x4C

SIM_HZ_TARGET = 120.0
SIM_TOLERANCE = 0.02  # 2 % — au-delà, la vitesse de jeu est fausse
STABLE_SECONDS = 3.0  # durée de validité continue exigée avant de mesurer


def connect(timeout: float) -> Dolphin:
    """Attend qu'un Dolphin porte une MEM1 avec un jeu dedans."""
    deadline = time.perf_counter() + timeout
    announced = False
    while True:
        try:
            return Dolphin()
        except RuntimeError as error:
            if time.perf_counter() >= deadline:
                raise
            if not announced:
                print(f"  en attente de Dolphin… ({str(error).splitlines()[0]})")
                announced = True
            time.sleep(1.0)


def wait_in_game(dolphin: Dolphin, timeout: float) -> int:
    """Attend une partie en cours, stable `STABLE_SECONDS` d'affilée.

    Retourne l'adresse du TMarDirector. La stabilité est exigée parce que la
    démo d'attraction de l'écran titre rend les deux pointeurs valides.
    """
    deadline = time.perf_counter() + timeout
    stable_since = None
    announced = False

    while time.perf_counter() < deadline:
        director = dolphin.u32(GP_MAR_DIRECTOR)
        mario = dolphin.u32(GP_MARIO)
        ok = dolphin.is_valid_pointer(director) and dolphin.is_valid_pointer(mario)

        if not ok:
            stable_since = None
            if not announced:
                print("  en attente d'une partie en cours…")
                announced = True
        elif stable_since is None:
            stable_since = time.perf_counter()
        elif time.perf_counter() - stable_since >= STABLE_SECONDS:
            return director

        time.sleep(0.25)

    raise RuntimeError(
        "aucune partie stable détectée — démarrer le jeu et entrer dans un niveau"
    )


def check_game_side(dolphin: Dolphin) -> tuple[bool, list[str]]:
    """Les deux écritures de données sont-elles en place ?"""
    literal = dolphin.f32(LITERAL_VSYNC)
    display = dolphin.u32(GP_APPLICATION + OFF_DISPLAY)
    lines = []
    ok = True

    if abs(literal - 2.0) < 1e-6:
        lines.append(f"  [ok]  0x804167B8   = {literal:g}f -> horloge logique 120 Hz")
    else:
        ok = False
        lines.append(
            f"  [NON] 0x804167B8   = {literal:g}f -> horloge logique "
            f"{60.0 * literal:g} Hz, attendu 2.0f / 120 Hz"
        )

    if not dolphin.is_valid_pointer(display):
        ok = False
        lines.append(f"  [NON] TDisplay      invalide (0x{display:08X})")
    else:
        # Deux correctifs mènent à un champ par image, et ils se cumulent :
        # `waitForRetrace` consomme `count` champs par appel si l'attente
        # finale est intacte, `count - 1` si elle a été neutralisée
        # (docs/01-mecanismes.md § 3.1). Ce qui compte est le produit.
        count = dolphin.u16(display + OFF_RETRACE_COUNT)
        patched = dolphin.u32(PATCH_SITE_RETRACE) == NOP
        fields = count - 1 if patched else count
        how = "nop + " if patched else ""
        if fields == 1:
            lines.append(
                f"  [ok]  présentation  = {how}count {count} -> 1 champ VI par image"
            )
        else:
            ok = False
            lines.append(
                f"  [NON] présentation  = {how}count {count} -> {fields} champs "
                "par image, attendu 1"
            )
            if fields <= 0:
                lines.append(
                    "        ZÉRO champ : plus aucune attente de balayage, le jeu "
                    "s'emballe."
                )

    return ok, lines


def _main(argv: list[str]) -> int:
    wait = 300.0
    duration = 6.0
    for index, argument in enumerate(argv):
        if argument == "--wait" and index + 1 < len(argv):
            wait = float(argv[index + 1])
        if argument == "--duree" and index + 1 < len(argv):
            duration = float(argv[index + 1])

    print("Validation du profil 120 FPS")
    print("=" * 60)

    dolphin = connect(wait)
    print(f"Dolphin     PID {dolphin.pid}, jeu {dolphin.game_id}")
    if dolphin.game_id[:6] != "GMSE01":
        print(
            f"  ATTENTION : le profil vise GMSE01, or le jeu chargé est "
            f"{dolphin.game_id}"
        )

    director = wait_in_game(dolphin, wait)
    print(f"Partie      TMarDirector 0x{director:08X}, stable")
    print()

    print("1. Côté jeu — la cadence")
    game_ok, lines = check_game_side(dolphin)
    print("\n".join(lines))
    print()

    print(f"2. Côté hôte — mesure de la cadence sur {duration:g} s")
    transitions, reads, elapsed = sample(dolphin, director + OFF_ACCUMULATOR, duration)
    result = analyse(transitions, elapsed)

    if not transitions:
        print("  aucune transition : jeu en pause ou sans simulation")
        return 1
    if not result["valid"]:
        print(
            f"  MESURE NON VALIDE — décréments {dict(result['steps_down'])}, "
            f"incréments {dict(result['steps_up'])}"
        )
        print("  Le sondage a manqué des transitions ; refaire la mesure.")
        return 1

    fps = result["frames"] / elapsed
    sim_hz = result["substeps"] / elapsed
    per_frame = result["substeps"] / result["frames"] if result["frames"] else 0.0

    print(f"  vsyncRate            {result['vsync_rate']}    (5 attendu au palier 120)")
    print(f"  images présentées    {fps:7.2f} /s   (119,88 attendu avec VI à 2×)")
    print(f"  sous-pas             {sim_hz:7.2f} /s   (120,00 attendu, toujours)")
    print(f"  sous-pas par image   {per_frame:7.3f}      (1,000 attendu)")
    print(
        f"  {reads:,} lectures, {len(transitions):,} transitions".replace(",", " ")
    )
    print()

    deviation = abs(sim_hz - SIM_HZ_TARGET) / SIM_HZ_TARGET
    speed = sim_hz / SIM_HZ_TARGET

    print("Verdict")
    print("-" * 60)
    if not game_ok:
        print("ÉCHEC — le palier n'est pas posé côté jeu.")
        print("Lancer `python tools/keep120.py` et le laisser tourner.")
        return 1
    if deviation > SIM_TOLERANCE:
        print(
            f"ÉCHEC — simulation à {sim_hz:.2f} Hz, soit {speed:.1%} de la "
            "vitesse correcte."
        )
        if fps < 90:
            print(
                "La présentation plafonne sous 90 images/s : le VI n'est pas "
                "overclocké."
            )
            print(
                "Vérifier VIOverclockEnable/VIOverclock dans le profil, puis "
                "redémarrer le jeu."
            )
        else:
            print(
                "La présentation tient, mais pas la simulation — cause à "
                "chercher ailleurs."
            )
        return 1

    print(
        f"SUCCÈS — {fps:.2f} images par seconde, simulation à {sim_hz:.2f} Hz "
        f"({speed:.1%} de la vitesse correcte)."
    )
    print()
    print("Rappel : seule la cadence est validée. Les objets mis à jour une fois")
    print("par image rendue — nuées d'oiseaux, boss anguille, minuteurs de")
    print("dialogue, transitions, fondus — restent non corrigés. Voir")
    print("deliver/README.md § « Ce qui n'est pas corrigé ».")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
