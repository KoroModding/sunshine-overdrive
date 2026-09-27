"""Physics regression suite (jump and run) across several frame rates.

Nothing measured here should change between tiers: the accumulator keeps the
simulation at 120 Hz whatever the display rate. A difference means the
decoupling is broken; look for the cause, do not compensate by editing
`TJumpParams`, `TRunParams` or the `.prm` files.

Three methodology traps
-----------------------
1. Walls. An early version ran Mario into scenery: speed froze at 6.00 instead
   of the ~32 reached in open ground, so the comparison only measured geometry.
   `probe_open_direction` tries eight headings and keeps the one that covers
   the most distance.

2. Wall-clock timing. "For 0.5 s" does not cover the same number of frames at
   30 and 60 FPS, and input injection is a race whose success rate depends on
   the frame count. Measured that way, jump height varied by 15% (an
   instrumentation artifact). Everything is therefore indexed on substeps
   (`substep_clock.py`): press duration and measurement window alike.

3. The comparison criterion. Jump height and distance are output quantities
   that depend on terrain as much as on the integrator. Measured 2026-09-15
   near a wall in Delfino Plaza: 96.60 at 30 FPS vs 81.59 at 60 FPS, fully
   reproducible, with the same initial impulse (`vy` = 42). Gravity is not the
   cause (the free ballistic arc is identical at both tiers, see
   `test_ballistic.py`); the scenery is.

The verdict is therefore based on profiles: the per-substep sequence of
vertical speeds during a jump, and of horizontal speeds during a run. Two
decoupled tiers must produce the same sequence. Heights and distances are
still printed, but only as indicative values.

Criterion revised 2026-09-17. The pure functions (sequence reduction, onset
alignment, comparison) are checked offline, but the whole test has NOT yet been
rerun against a live Dolphin. The reading in `04-tests.md` still uses the old
criterion, with its false alarm flagged as such.

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
OFF_VEL = 0xA4  # from gpMarioSpeedX/Y/Z

MAX_ATTEMPTS = 5

# Press-edge duration. Kept short on purpose: the hold is provided by `+0x18`,
# and replaying the edge every frame would chain jumps (see `pad.press`). The
# jump duration itself is set in substeps.
EDGE_WINDOW = 0.12


class Subject:
    """Mario: state readout and reset."""

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
    """Reduce an oversampled sequence to its successive distinct values.

    Polling runs at ~400,000 reads/s against 120 integrations/s, so each value
    is seen hundreds of times. Keeping only the changes yields the sequence of
    simulation states, which is comparable between tiers.
    """
    reduced: list[float] = []
    for value in values:
        rounded = round(value, 4)
        if not reduced or rounded != reduced[-1]:
            reduced.append(rounded)
    return reduced


def from_onset(values: list[float], threshold: float = 0.0) -> list[float]:
    """Drop everything before the first value above `threshold`.

    Aligns the profile on the event rather than on the start of polling. The
    injected input is not seen on the same frame at every rate, so the number
    of idle values before the impulse varies between tiers, and two identical
    profiles would otherwise appear to diverge at their first element.
    """
    for index, value in enumerate(values):
        if value > threshold:
            return values[index:]
    return []


def compare_profiles(a: list[float], b: list[float]) -> tuple[bool, int, int]:
    """Return (identical, compared length, divergence index)."""
    n = min(len(a), len(b))
    for index in range(n):
        if a[index] != b[index]:
            return False, n, index
    return True, n, -1


def prepare(subject: Subject, pad: Pad) -> None:
    """Reset Mario and let the game see a neutral controller.

    The first reset clears the state left by the previous attempt; the second
    undoes any movement physics applied while settling.
    """
    subject.reset()
    pad.settle(0.7)
    subject.reset()
    time.sleep(0.25)


def probe_open_direction(subject: Subject, pad: Pad) -> tuple[float, float]:
    """Find the stick direction that covers the most distance."""
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
    """Jump with A held for `hold_substeps` substeps.

    Returns a reading, or None if the injected input was not seen:

        hauteur   relative apex; indicative only, depends on terrain
        vy max    initial impulse, identifies the jump type
        profil    per-substep vertical speeds aligned on the impulse. This is
                  what the verdict uses: it depends only on the integrator as
                  long as Mario touches nothing.
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
    """Run held for `substeps` substeps.

    Returns a reading, or None if the input was not seen:

        vitesse max   top speed reached
        distance      indicative only; an obstacle cuts it short
        profil        per-substep horizontal speeds aligned on the start. This
                      is the `TRunParams` acceleration curve; the verdict
                      uses it.
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
    """Retry until the injected input is seen.

    Injection wins the race most of the time, not always. Without retries a
    lost attempt would read as a physics difference.
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

        # Output quantities: printed but not used for the verdict. An apex
        # height measures the ceiling as much as gravity.
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

        # Profiles are the real criterion: same start state and same input in a
        # decoupled simulation must give an identical state sequence.
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
