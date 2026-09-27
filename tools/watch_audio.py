"""Vérifie les routines à état du profil et surveille la musique de fond.

Trois contrôles, dans l'ordre :

1. **Présence** — les mots écrits par [OnFrame] (build_caves.build()) sont
   relus un à un en mémoire.

2. **Cadence de la couche JAI** — JAISound+0x14 est incrémenté à chaque passage
   de JAIBasic::checkPlayingSeqTrack, donc une fois par appel de
   MSound::mainLoop. Sa pente mesure directement la cadence audio :
   ~120 /s au palier 120 (une fois par image : pas de limitation, voir
   build_caves.py) ; ~30 /s signalerait une ancienne routine audio encore posée.

3. **Santé de la séquence** — pour chaque racine JASystem active : tempo
   effectif (TTrack+0x3B0), multiplicateur externe (TOuterParam+0x18) et
   minuteurs d'attente des pistes filles. Une racine dont le tempo vaut 0 et
   dont les minuteurs ne bougent plus est figée : c'est le symptôme de la
   musique muette.

Offsets tirés de la décompilation Graffito-Decomp (JAISound.hpp, JASTrack.hpp,
JAIParameters.hpp) et recoupés en mémoire le 2026-09-22.

Usage
-----
    python tools/watch_audio.py [durée-en-secondes]     (défaut 600)
    python tools/watch_audio.py --suivi [journal]       surveillance longue :
        survit aux changements de niveau et aux redémarrages du jeu, note chaque
        musique rencontrée (id JAI, piste MSBgm) et chaque gel ; s'arrête avec
        Ctrl+C ou la fin du processus. Journal par défaut : work/suivi_audio.log
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_caves import build  # noqa: E402
from dolphin import Dolphin  # noqa: E402

SM_BGM_IN_TRACK = 0x803E9C80    # MSBgm::smBgmInTrack[] — MSBgm*, handle JAISound* à +0x14
ROOT_TRACKS = 0x8040E6C0        # JASystem::TrackMgr::sRootTrack
ROOT_COUNT = 0x8040E6C8         # JASystem::TrackMgr::sRootSeqCount


def bgm_sound(d: Dolphin) -> int:
    bgm = d.u32(SM_BGM_IN_TRACK)
    return d.u32(bgm + 0x14) if d.is_valid_pointer(bgm) else 0


def roots(d: Dolphin) -> list[dict]:
    table = d.u32(ROOT_TRACKS)
    out = []
    for i in range(d.u32(ROOT_COUNT)):
        t = d.u32(table + 4 * i)
        if not d.is_valid_pointer(t) or not d.u8(t + 0x3C4):
            continue
        outer = d.u32(t + 0x304)
        kids = [d.u32(t + 0x2C4 + 4 * k) for k in range(16)]
        out.append({
            "index": i,
            "tempo": d.f32(t + 0x3B0),
            "outer": d.f32(outer + 0x18) if d.is_valid_pointer(outer) else None,
            "waits": tuple(d.s32(k + 8) for k in kids if d.is_valid_pointer(k)),
        })
    return out


def main(argv: list[str]) -> int:
    duration = float(argv[1]) if len(argv) > 1 else 600.0
    d = Dolphin()

    patches, _ = build()
    wrong = [(a, v, d.u32(a)) for a, v in patches if d.u32(a) != v]
    print(f"Routines : {len(patches) - len(wrong)}/{len(patches)} mots en place")
    for a, v, got in wrong:
        print(f"  {a:08X}  attendu {v:08X}  lu {got:08X}")
    if wrong:
        return 1

    snd = bgm_sound(d)
    if snd:
        c0, t0 = d.u32(snd + 0x14), time.perf_counter()
        time.sleep(2.0)
        rate = (d.u32(snd + 0x14) - c0) / (time.perf_counter() - t0)
        print(f"Cadence JAI : {rate:.1f} passages/s   (attendu ~120 au palier 120)")
        print(f"Musique : son {d.u32(snd + 8):08X}, état {d.u8(snd + 1)}")
    else:
        print("Cadence JAI : pas de musique de fond en cours, mesure impossible")

    previous: dict[int, tuple] = {}
    frozen_since: dict[int, float] = {}
    end = time.perf_counter() + duration
    print(f"Surveillance des séquences pendant {duration:.0f} s…")
    while time.perf_counter() < end:
        now = time.perf_counter()
        for r in roots(d):
            i = r["index"]
            stuck = r["tempo"] == 0.0 and previous.get(i) == r["waits"]
            if stuck and i not in frozen_since:
                frozen_since[i] = now
            elif not stuck:
                frozen_since.pop(i, None)
            if i in frozen_since and now - frozen_since[i] >= 3.0:
                print(f"  FIGÉE  racine {i} : tempo {r['tempo']:.4f}, multiplicateur "
                      f"{r['outer']}, minuteurs {r['waits']}")
                frozen_since[i] = float("inf")   # ne signaler qu'une fois
            previous[i] = r["waits"]
        time.sleep(1.0)
    print("Fin. Aucune ligne FIGÉE ci-dessus = aucune séquence bloquée pendant la fenêtre.")
    return 0


def bgm_ids(d: Dolphin) -> dict[int, int]:
    """{piste MSBgm: id du son} pour les musiques de fond en cours."""
    out = {}
    for track in range(8):
        bgm = d.u32(SM_BGM_IN_TRACK + 4 * track)
        if d.is_valid_pointer(bgm):
            snd = d.u32(bgm + 0x14)
            if d.is_valid_pointer(snd):
                out[track] = d.u32(snd + 8)
    return out


def follow(log_path: Path) -> int:
    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    seen: set[int] = set()
    frozen_reported: set[tuple[int, int]] = set()
    log("Suivi démarré")
    while True:
        try:
            d = Dolphin()
            patches, _ = build()
            wrong = sum(1 for a, v in patches if d.u32(a) != v)
            log(f"Jeu trouvé ; routines {len(patches) - wrong}/{len(patches)} mots en place")
            previous: dict[int, tuple] = {}
            stuck_since: dict[int, float] = {}
            current: dict[int, int] = {}
            while True:
                ids = bgm_ids(d)
                if ids != current:
                    log("Musiques : " + (", ".join(f"piste {t} = {i:08X}" for t, i in sorted(ids.items())) or "aucune"))
                    for i in ids.values():
                        seen.add(i)
                    current = ids
                now = time.perf_counter()
                for r in roots(d):
                    k = r["index"]
                    stuck = r["tempo"] == 0.0 and previous.get(k) == r["waits"]
                    if not stuck:
                        stuck_since.pop(k, None)
                    else:
                        stuck_since.setdefault(k, now)
                        key = (k, hash(r["waits"]))
                        if now - stuck_since[k] >= 3.0 and key not in frozen_reported:
                            frozen_reported.add(key)
                            log(f"FIGÉE  racine {k} : multiplicateur {r['outer']}, musiques en cours "
                                + ", ".join(f"{i:08X}" for i in ids.values()))
                    previous[k] = r["waits"]
                time.sleep(1.0)
        except KeyboardInterrupt:
            break
        except Exception as exc:          # jeu arrêté, relancé, MEM1 déplacée
            log(f"Jeu indisponible ({type(exc).__name__}) ; nouvelle tentative dans 5 s. "
                f"Musiques vues jusqu'ici : {len(seen)}")
            time.sleep(5.0)
    log(f"Fin du suivi. Musiques vues : {', '.join(f'{i:08X}' for i in sorted(seen))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--suivi":
        default = Path(__file__).resolve().parent.parent / "work" / "suivi_audio.log"
        raise SystemExit(follow(Path(sys.argv[2]) if len(sys.argv) > 2 else default))
    raise SystemExit(main(sys.argv))
