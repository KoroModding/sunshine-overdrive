# Sunshine Overdrive

**Super Mario Sunshine at 120 frames per second on Dolphin, at the original game
speed.** Not a speedhack, no interpolation: the game still simulates at its
native 120 Hz — it simply displays every simulation step instead of one in four.

It also fixes:

- **The infamous high-FPS music bug.** At 60 FPS and above, Sunshine's music
  can freeze or lose its tempo. The cause is a race between the game thread and
  the audio thread that drops the tempo flag, and it gets likelier the faster
  the game runs. Sunshine Overdrive fixes it at the source. Audio timing is
  corrected too: fades, the Doppler effect, sound-effect pitch and repeat
  rates.
- **Staircase goop edges.** The blocky edges of the pollution, very visible at
  high internal resolutions, are replaced with rounded outlines on every goop
  layer (brown and pink), and new goop such as Petey's puddles spreads
  smoothly — without touching gameplay.

---

## Install

**Requirements:**

- a recent Dolphin (developed and tested with Dolphin 2606a);
- your own copy of **Super Mario Sunshine NTSC-U (GMSE01)** — no other region is
  supported;
- a PC able to emulate the game at **2× speed**: the VI overclock also speeds up
  the emulated CPU clock.

**With the installer (recommended):**

1. Download `Sunshine-Overdrive-Setup-*.exe` from the
   [Releases](https://github.com/KoroModding/sunshine-overdrive/releases/latest)
   and run it. No administrator rights needed.
2. If Windows shows "Windows protected your PC" (the installer is not signed):
   *More info → Run anyway*.
3. The installer finds Dolphin's user folder on its own (Dolphin's registry
   entry, then `%APPDATA%`, then `Documents`). Portable Dolphin: pick the `User`
   folder next to `Dolphin.exe`.
4. An existing `GMSE01.ini` is set aside and **restored on uninstall**
   (Windows Settings → Apps → Sunshine Overdrive).

Silent install:
`Sunshine-Overdrive-Setup-1.4.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DOLPHINDIR="C:\...\Dolphin Emulator"`.

**Manually:**

1. Copy [`deliver/GMSE01.ini`](deliver/GMSE01.ini) into Dolphin's user folder,
   under `GameSettings\`:
   - Windows: `%APPDATA%\Dolphin Emulator\GameSettings\GMSE01.ini`
   - Linux: `~/.local/share/dolphin-emu/GameSettings/GMSE01.ini`
   - macOS: `~/Library/Application Support/Dolphin/GameSettings/GMSE01.ini`

   If a `GMSE01.ini` already exists there, back it up first: the profile
   replaces it.
2. **Start the game** (or restart it). Everything is read at boot.

**With a script (Windows, Python 3.10+):**

```sh
python tools/install_profile.py install     # installs, keeping the previous file aside
python tools/install_profile.py status
python tools/install_profile.py uninstall   # restores exactly the previous state
```

**Dolphin settings:**

- **Do not enable any Gecko or Action Replay code for this game.** The profile
  places its routines in the Gecko code handler's memory area
  (0x80001800–0x80003000); an active Gecko code would overwrite them.
- The profile includes gamemasterplc's **16:9 widescreen** code: set
  *Graphics → Aspect Ratio* to *Force 16:9*.
- Nothing else to change: the VI overclock is carried by the profile itself
  (`[Core]` section) and does not affect other games.

**Check (optional, Windows):**

```sh
python tools/validate_120.py     # can be started before the game, it waits
```

It reads the profile back from the game's memory and measures the simulation
speed: expect ~119.8 frames/s and 120.0 simulation steps per second.

**Uninstall:** Windows Settings → Apps (installer), delete the file, or
`install_profile.py uninstall`.

---

## How it works

### The engine is already decoupled

`TMarDirector::direct()` contains a fixed-point accumulator: a budget of 600
units per second, 5 units per simulation step. The game therefore simulates at a
**constant 120 Hz**, and what varies is the number of steps run per displayed
frame: 4 at 30 FPS, 2 at 60, **1 at 120**. The quantum cannot go below one step
per frame: **120 FPS is the engine's arithmetic limit**. Going further would
require interpolation.

Three writes are enough to reach that tier:

| Where | What | Effect |
|---|---|---|
| Dolphin `[Core]` | `VIOverclock = 2.0` | the emulated VI delivers 119.88 fields/s instead of 59.94 |
| `0x804167B8` | `0.5f` → `2.0f` | `SMSGetVSyncTimesPerSec()` returns 120: one step per frame, animations rescaled |
| `0x802FCB24` | `bl VIWaitForRetrace` → `nop` | one frame presented per VI field |

Measured: **119.8 frames/s, simulation at 120.0 Hz**, jump trajectory identical
to the last digit over 90 steps between 30 and 120 FPS, free fall within 0.06%.
Mario's physics are **never** rescaled: they already run per simulation step.

### What still breaks, and why

Not all of Sunshine's code runs at the same rate:

- code executed **every simulation step** (perform flag `0x1`: movement, enemy
  nerves, physics) is correct at any frame rate;
- code executed **once per displayed frame** (flag `0x2`, drawing, matrix
  computation) runs 4× more often at 120 FPS. Anything it counts in "frames"
  goes 4× too fast;
- `SMSGetAnmFrameRate()` is 2.0 at 30 FPS and 0.5 at 120. That is correct for an
  animation advanced once per frame. But when this factor is used as a speed
  multiplier in code that runs **per step**, the object becomes 4× too slow:
  birds, the giant eel, the Ferris wheel;
- at 30 FPS, the once-per-frame side (animation, animation sounds, collision
  boxes placed on a joint) only ran after four simulation steps, so states that
  lasted less than that were never observed. At 120 FPS they are: a Poink's
  collision box one frame behind it, or a looping animation seen wrapping just
  before the actor switches to another one (the Gatekeeper's double cry).

Each fix in the profile addresses a case read back from the game's executable,
and almost all were measured in game before and after. Most routines read the
factor `M = 2 × literal 0x804167B8` (1 at 30 FPS, 4 at 120) at run time.

### What the profile contains

| Module (`tools/fixes/`) | Fix |
|---|---|
| base (`build_profile.py`, `build_caves.py`) | frame rate; **particles** (the JPA manager stopped advancing at 120 FPS); **graffiti portals** (impassable without the fix); **music freezing** (tempo lost between game and audio threads) |
| `fades.py` | audio fade durations (pause, music changes) |
| `soundsets.py` | FLUDD, cleaning and goop sounds repeating 4× too often |
| `sound.py` | pitch and volume of animation sounds (except Mario) |
| `doppler.py` | Doppler effect 4× too weak |
| `widescreen.py` | gamemasterplc's 16:9 code, converted to `[OnFrame]` |
| `hx.py` | **screen wipes** (circle, level-entry fades, Game Over…) 4× too fast |
| `petey.py` | Petey Piranha vomiting 4× too fast |
| `birds.py` | birds flying 4× too slowly |
| `jointcoin.py` | Sand Bird (Gelato Beach) flying 4× too slowly, wings flapping 2.5× too slowly |
| `loopsnd.py` | animation sounds replayed when a looping animation wraps just before the actor switches to another one (the Gatekeeper crying twice on every hit) |
| `poink.py` | Poinks (Petey Piranha, Bianco Hills) exploding right after being launched: they hit their own collision box, which lags one frame behind them |
| `eel.py` | giant eel (Noki Bay): all animations 4× too slow |
| `bosses.py` | Shadow Mario, Bowser Jr.'s submarine, bathtub platforms, Wiggler, Petey's head, Gooper Blooper, Mecha-Bowser's flame, Bullet Bills, Pinna Park Ferris wheel and roller coaster |
| `goop.py` (+ `goop/goop.c`) | **smooth goop edges**: see below |

Details for each fix (addresses, original instruction, proof, measurements) are
in the header of its module (in French) and in [`docs/00-journal.md`](docs/00-journal.md).

### Smooth goop edges

The goop outline is the 0.5 isoline of a 128×128 to 256×256 I8 mask stretched
over an entire area: one texel is 32 game units, and a binary mask with bilinear
filtering produces steps the size of a texel. No Dolphin setting changes that
(forced filtering, MSAA, SSAA).

Constraint: **this mask is also the gameplay mask** (sliding, cleaning,
counting), and the game writes directly into it when you spray. So it is never
modified. Instead, `goop.c`:

1. when each layer loads, allocates a same-size **display copy** in the level's
   memory (16 to 64 KB, with a 512 KB free-memory guard — otherwise nothing
   changes) and points the materials at it — including the display lists some
   layers freeze at load time (Bianco's large pink-goop floors), whose texture
   address is rewritten in place. Gameplay keeps its own pointers to the
   original mask;
2. fills the copy with a **3×3 tent filter** of the mask: rounded, continuous
   outlines, with no offset;
3. keeps it up to date: the area of each cleaning stamp immediately, the area
   around each model stamp (Petey's goop puddles, Gooper Blooper, Shadow Mario…)
   every frame while it spreads, plus a background sweep of a few rows per
   frame for everything else;
4. softens the edge (opacity ramp around the threshold, blending enabled) on
   the regular brown goop; the pink goop's material differs and keeps its hard
   (but smoothed) edge.

The code is written in C, compiled for the GameCube CPU with
BetterSunshineEngine's PowerPC clang, and injected through `[OnFrame]` like the
rest. Measured in Bianco Hills: 5 layers, 120 frames/s, 3.9 MB still free;
up to 16 layers per level (the pink-goop episode has 9).

### Why `[OnFrame]` and not `[Gecko]`

Dolphin's PatchEngine applies `[OnFrame]` lines on every VI field, before the JIT
compiles the affected code, so instructions can be replaced. The `[Gecko]`
section did not load in our tests.

Pitfall found along the way: Dolphin installs an HLE hook at **0x800018A8**, the
Gecko code handler's entry point, **even with no Gecko code enabled**. Executing
an instruction at that address flushes the entire JIT cache. A routine that
landed there dropped emulation to 8 frames/s during circle wipes.
`build_profile.py` now rejects any word at 0x800018A8 and 0x80002FFC.

---

## Known limitations

- **GMSE01 (NTSC-U) only.** The addresses do not apply to the PAL or Japanese
  versions.
- **No higher than 120 FPS**: that would require decoupling rendering from
  simulation, then interpolating.
- **Dolphin only.** How a real GameCube's VI behaves outside standard modes is
  unknown.
- **Not fixed, found during the audit:**
  - plain fades to black (`TSMSFader`): 4× shorter (the `fader.py` fix exists
    but is not enabled);
  - King Boo: possibly fewer bubbles per spit;
  - Fire Chomp: Mario possibly pulled too hard by the tail;
  - a few cosmetic effects on Phantamanta and Gooper Blooper.
- **Incompatible with mods based on BetterSunshineEngine**, including Super
  Mario Eclipse: they have their own frame-rate setting and patch the same code.
- **Incompatible with any Gecko or Action Replay code** enabled for GMSE01.
- **Texture packs** that replace the goop masks (the `pollution_maps` folder of
  some packs): the goop now displays the smoothed copy, so those replacements no
  longer apply.

---

## For developers

The tools are written in Python and target Windows: they read and write the
memory of a running Dolphin through `ReadProcessMemory`.

```sh
pip install -r requirements.txt
```

The goop module is C (`tools/fixes/goop/goop.c`). The compiled binaries are
committed: the profile rebuilds **without a compiler**. To modify the C code, you
need the PowerPC clang shipped with
[BetterSunshineEngine](https://github.com/DotKuribo/BetterSunshineEngine)
(`compiler/` folder):

```sh
set PPC_CLANG_DIR=C:\path\to\BetterSunshineEngine\compiler
python tools/fixes/goop.py        # compiles, links, checks bounds and hook sites
```

The game files are **not** in the repository. Put them in `work/`, which git
ignores:

```sh
python tools/gciso.py dol <your-GMSE01-iso> work/dol/GMSE01.dol
curl -sSL -o work/maps/us.map \
  https://raw.githubusercontent.com/DotKuribo/BetterSunshineEngine/master/maps/us.map
```

Then:

```sh
python tools/build_profile.py                     # assembles and checks, writes nothing
python tools/build_profile.py --write --inconditionnel \
  --modules fades,soundsets,widescreen,sound,petey,doppler,hx,birds,eel,bosses,goop,jointcoin,poink,loopsnd
python tools/disasm.py work/dol/GMSE01.dol work/maps/us.map <symbol|address> [n]
python tools/xref.py   work/dol/GMSE01.dol work/maps/us.map <address>
```

`build_profile.py` refuses to build on:
- any address written twice with different values;
- any write identical to the word already in the game;
- any branch to an unknown target;
- any write on a Dolphin HLE hook.

In-game measurement tools (`tools/watch_*.py`, `validate_120.py`): frame rate,
wipes, audio fades, sounds, birds, Sand Bird, Mario's state frame by frame. Goop:
`goop_inspect.py` (J3D materials decoded GX command by GX command), `goop_ctl.py`
(module state, live smoothing / soft-edge switches), `goop_probe.py` (does the
copy follow the mask?), `goop_soft.py` (live soft-edge prototype).

The installer (`installer/SunshineOverdrive.iss`, Inno Setup 6) is built by
GitHub Actions (`.github/workflows/installateur.yml`) on every `v*` tag and
published as a Release. Locally:

```sh
ISCC.exe /DAppVer=1.4.0 installer\SunshineOverdrive.iss     # -> dist\
```

Detailed documentation:

| File | Contents |
|---|---|
| [`docs/00-journal.md`](docs/00-journal.md) | project log, session by session, with every measurement |
| [`docs/01-mechanisms.md`](docs/01-mechanisms.md) | the engine's timing mechanisms, demonstrated in the disassembly |
| [`docs/02-addresses.md`](docs/02-addresses.md) | address register and how well each one is verified |
| [`docs/03-tooling.md`](docs/03-tooling.md) | the tools |
| [`docs/04-tests.md`](docs/04-tests.md) | the test suite and its results |
| [`docs/05-regions.md`](docs/05-regions.md) | why GMSE01 only |
| [`docs/adr/`](docs/adr/) | architecture decisions |

---

## Credits

- **gamemasterplc**: the original 60 FPS code and the 16:9 widescreen code
  (shipped with Dolphin), the starting point of this work.
- **BetterSunshineEngine** ([DotKuribo](https://github.com/DotKuribo/BetterSunshineEngine),
  JoshuaMKW): the reference inventory of systems that break above 30 FPS, and
  the GMSE01 symbol map.
- Decompilations **[doldecomp/sms](https://github.com/doldecomp/sms)** and
  **[Graffito-Decomp](https://github.com/ryanbevins/Graffito-Decomp)**, symbols
  from **[shibbo/Corona](https://github.com/shibbo/Corona)**.
- Super Mario Sunshine is a trademark of Nintendo. This repository contains no
  game files; you must own your own copy.
