"""Injection d'entrées manette par écriture dans l'objet `TMarioGamePad`.

Permet de piloter Mario depuis un script, sans manette physique, sans envoyer
de frappes à la fenêtre de Dolphin et sans lui voler le focus. C'est ce qui
rend la batterie de tests entièrement automatisable.

Structure de `TMarioGamePad` (dérivée de `JUTGamePad`)
------------------------------------------------------
Les offsets ont été relevés dans le code, pas devinés :

    +0x18  u32  boutons **maintenus**      (`updateMeaning` y teste la croix)
    +0x1C  u32  boutons **nouvellement pressés** (front)
    +0x2C  f32  gâchette analogique
    +0xA8  f32  stick principal X, dans [-1, 1]   (`checkController`, ×128)
    +0xAC  f32  stick principal Y, dans [-1, 1]
    +0xDC  u16  « meaning » — interprétation calculée par le jeu

Vérifié expérimentalement : écrire seulement `+0x18` ne fait **rien**, écrire
`+0x1C` fait sauter Mario. Le saut se déclenche donc sur le front, pas sur le
maintien — ce qui confirme l'attribution des deux champs.

Pourquoi un martèlement
-----------------------
Le jeu réécrit l'objet à chaque image depuis la vraie manette
(`TMarioGamePad::read`). Une écriture unique serait donc écrasée avant d'être
lue. Un fil d'arrière-plan réécrit les valeurs en continu : à ~400 000
écritures par seconde contre une relecture par image, les valeurs injectées
sont en place quand `TMario::checkController` les consulte.

C'est une course, pas un verrou : elle est gagnée très largement, mais elle
reste une course. Les tests doivent donc mesurer un résultat (hauteur atteinte,
distance parcourue) plutôt que supposer qu'une image précise a vu l'entrée.

Usage
-----
    with Pad(dolphin) as pad:
        pad.stick(0.0, 1.0)      # avant toute
        time.sleep(1.0)
        pad.tap("A")             # saut
        pad.neutral()
"""

from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from dolphin import Dolphin  # noqa: E402

GP_MARIO = 0x8040E0E8
OFF_MARIO_GAMEPAD = 0x4FC  # TMario::mGamePad — `stw r4, 0x4fc(r3)` dans setGamePad

OFF_HELD = 0x18
OFF_PRESSED = 0x1C
OFF_ANALOG = 0x2C
OFF_STICK_X = 0xA8
OFF_STICK_Y = 0xAC

# Masques de boutons de la manette GameCube (PAD_BUTTON_* de la bibliothèque).
BUTTONS = {
    "LEFT": 0x0001,
    "RIGHT": 0x0002,
    "DOWN": 0x0004,
    "UP": 0x0008,
    "Z": 0x0010,
    "R": 0x0020,
    "L": 0x0040,
    "A": 0x0100,
    "B": 0x0200,
    "X": 0x0400,
    "Y": 0x0800,
    "START": 0x1000,
}

# Durée d'un front de pression.
#
# Le martèlement est une course : à chaque image, le jeu remet le pad à zéro
# depuis la vraie manette, puis le consulte un peu plus tard. L'injection ne
# « gagne » que si une écriture tombe entre les deux. Une fenêtre d'une seule
# image ne laisse donc qu'une ou deux chances, ce qui est insuffisant —
# mesuré : un front de 50 ms ne déclenche pas le saut de façon fiable.
#
# 200 ms couvrent 6 images à 30 FPS et 12 à 60 FPS, ce qui rend la perte
# improbable. Les fronts surnuméraires sont sans effet : Mario est déjà en
# l'air et le jeu ignore l'entrée.
PRESS_WINDOW = 0.200


def mask_of(buttons: str | int | None) -> int:
    """Convertit « A », « A+B » ou un entier en masque de boutons."""
    if buttons is None:
        return 0
    if isinstance(buttons, int):
        return buttons
    total = 0
    for name in buttons.replace(" ", "").split("+"):
        if name:
            total |= BUTTONS[name.upper()]
    return total


class Pad:
    """Manette virtuelle martelée dans la mémoire du jeu."""

    def __init__(self, dolphin: Dolphin | None = None) -> None:
        self.dolphin = dolphin or Dolphin()
        mario = self.dolphin.u32(GP_MARIO)
        if not self.dolphin.is_valid_pointer(mario):
            raise RuntimeError("Mario introuvable — le jeu est-il dans un niveau ?")
        self.address = self.dolphin.u32(mario + OFF_MARIO_GAMEPAD)
        if not self.dolphin.is_valid_pointer(self.address):
            raise RuntimeError(f"TMarioGamePad invalide (0x{self.address:08X})")

        self._held = 0
        self._pressed = 0
        self._pressed_until = 0.0
        self._stick = (0.0, 0.0)
        self._analog = 0.0
        self._stop = threading.Event()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    # -- cycle de vie ------------------------------------------------------

    def start(self) -> "Pad":
        """Démarre le martèlement et **attend** qu'il écrive réellement.

        L'attente n'est pas une précaution de confort : localiser la MEM1
        demande un balayage des régions du processus, qui prend plus de temps
        qu'un front de pression ne dure. Sans elle, une commande émise juste
        après `start()` serait perdue.
        """
        if self._thread is None:
            self._stop.clear()
            self._running.clear()
            self._thread = threading.Thread(target=self._hammer, daemon=True)
            self._thread.start()
            if not self._running.wait(timeout=10.0):
                raise RuntimeError("le fil de martèlement n'a pas démarré")
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        # Rendre la main à la vraie manette : remettre tout à neutre une fois.
        self.dolphin.write(self.address + OFF_HELD, struct.pack(">II", 0, 0))
        self.dolphin.write(self.address + OFF_STICK_X, struct.pack(">ff", 0.0, 0.0))

    def __enter__(self) -> "Pad":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- fil de martèlement ------------------------------------------------

    def _hammer(self) -> None:
        # Connexion distincte : le handle Win32 est partagé sans risque, mais
        # une instance par fil évite tout entrelacement d'état. Sa construction
        # rebalaie les régions du processus — d'où le signal de démarrage, émis
        # seulement une fois la première écriture faite.
        dolphin = Dolphin(self.dolphin.pid)
        base = self.address
        dolphin.write(base + OFF_HELD, struct.pack(">II", 0, 0))
        self._running.set()
        while not self._stop.is_set():
            pressed = self._pressed if time.perf_counter() < self._pressed_until else 0
            dolphin.write(base + OFF_HELD, struct.pack(">II", self._held, pressed))

            # Le stick et la gâchette ne sont réécrits que s'ils servent : une
            # boucle plus courte martèle plus vite, ce qui augmente les chances
            # de gagner la course sur les boutons.
            x, y = self._stick
            if x or y:
                dolphin.write(base + OFF_STICK_X, struct.pack(">ff", x, y))
            if self._analog:
                dolphin.write(base + OFF_ANALOG, struct.pack(">f", self._analog))

    # -- commandes ---------------------------------------------------------

    def hold(self, buttons: str | int) -> None:
        """Maintient des boutons (sans front)."""
        self._held = mask_of(buttons)

    def press(self, buttons: str | int, window: float = PRESS_WINDOW) -> None:
        """Émet un front de pression borné, puis maintient les boutons.

        Le front ne dure que `window` : au-delà, seul le maintien subsiste.
        C'est essentiel et non cosmétique. Répéter le front à chaque image
        revient à appuyer à nouveau sur A dès que Mario touche le sol, ce qui
        déclenche un enchaînement double/triple saut. Mesuré : avec un front
        permanent, la hauteur d'un même saut variait de 73,79 à 140,0 selon
        l'essai, et `vy max` sautait entre trois valeurs discrètes (41, 42, 52)
        correspondant à trois types de saut différents.
        """
        mask = mask_of(buttons)
        self._pressed = mask
        self._pressed_until = time.perf_counter() + window
        self._held |= mask

    def tap(self, buttons: str | int, window: float = PRESS_WINDOW) -> None:
        """Front de pression puis relâchement immédiat."""
        self.press(buttons, window)
        time.sleep(window)
        self.release(buttons)

    def release(self, buttons: str | int | None = None) -> None:
        self._held = 0 if buttons is None else self._held & ~mask_of(buttons)

    def stick(self, x: float, y: float) -> None:
        """Stick principal, composantes dans [-1, 1]. Y positif = vers l'avant."""
        self._stick = (float(x), float(y))

    def analog(self, value: float) -> None:
        """Gâchette analogique, dans [0, 1]."""
        self._analog = float(value)

    def neutral(self) -> None:
        self._held = 0
        self._pressed = 0
        self._pressed_until = 0.0
        self._stick = (0.0, 0.0)
        self._analog = 0.0

    def settle(self, duration: float = 0.8) -> None:
        """Remet tout au neutre et laisse le jeu le constater.

        Indispensable avant une pression : le jeu tient sa propre mémoire de
        l'état précédent de la manette pour détecter les fronts. Sans quelques
        images de neutre, une pression injectée juste après le démarrage du
        martèlement n'est pas vue comme un front — vérifié expérimentalement,
        c'est la différence entre un saut et rien du tout.
        """
        self.neutral()
        time.sleep(duration)


def _main(argv: list[str]) -> int:
    """Démonstration : fait sauter Mario et rapporte la hauteur atteinte."""
    dolphin = Dolphin()
    mario = dolphin.u32(GP_MARIO)
    y_address = mario + 0x14

    with Pad(dolphin) as pad:
        print(f"TMarioGamePad 0x{pad.address:08X}")
        pad.settle()
        base = dolphin.f32(y_address)
        pad.press("A")
        peak = base
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            peak = max(peak, dolphin.f32(y_address))
        pad.settle(0.2)
        print(f"Y de départ {base:g}, sommet {peak:g}, hauteur {peak - base:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
