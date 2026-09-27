"""Validation of the 120 FPS profile shipped in `deliver/`.

The profile has two halves -- the host-side VI overclock and the game-side
frame rate writes -- and neither reports on the other. This script checks them
separately, then gives a verdict, so a missing half is not taken for success.

What is checked
---------------
1. **Game side, by direct read.** The literal at 0x804167B8 must be 2.0f, and
   presentation must consume exactly one VI field per frame -- which two
   different fixes provide, and they must not stack.
2. **Host side, by measurement.** `VIOverclock` cannot be read from MEM1: it
   is not there. Its only observable trace is the presentation rate. A VI at
   2x gives 119.88 frames per second; a VI at nominal rate caps at 59.94. This
   is what separates "120 FPS" from "half speed".
3. **Simulation speed**, the point of the whole project: 120 substeps per
   second regardless of display rate.

Criterion
---------
Simulation must run at 120 Hz +/- 2 %. That is the deciding quantity, not the
frame count: a game showing 119 frames per second while simulating only 60
runs at half speed, which is exactly the trap of the 120 tier.

Waiting for the game
--------------------
Since the profile only takes effect at boot, this script can **wait** for the
game: start it first, then the user starts the game. Arrival requires
`gpMarDirector` and `gpMarioOriginal` to be *stably* valid -- an instantaneous
check concludes "in game" during the title screen attract demo (dead end
found in session 3).

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
SIM_TOLERANCE = 0.02  # beyond 2 %, game speed is wrong
STABLE_SECONDS = 3.0  # continuous validity required before measuring


def connect(timeout: float) -> Dolphin:
    """Wait for a Dolphin whose MEM1 holds a game."""
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
    """Wait for a running game, stable for `STABLE_SECONDS` in a row.

    Returns the TMarDirector address. Stability is required because the title
    screen attract demo makes both pointers valid.
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
    """Are both data writes in place?"""
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
        # Two fixes lead to one field per frame, and they stack:
        # `waitForRetrace` consumes `count` fields per call if the final wait
        # is intact, `count - 1` if it was removed (docs/01-mecanismes.md
        # section 3.1). What matters is the combined result.
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
