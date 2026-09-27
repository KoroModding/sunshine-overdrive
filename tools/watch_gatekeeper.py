"""Gatekeeper (TBiancoGateKeeper, vtable 0x803BB71C): animations, animation
sound state and cries, to settle "he cries twice per hit".

Read in the DOL (GMSE01):
- TBiancoGateKeeper::changeBck 0x800FB718: *(MActor + 0xC) = BCK block
  (+0 animation index, +4 J3DFrameCtrl: +0x6 start, +0x8 end, +0xC rate,
  +0x10 frame); resets the frame, rate = SMSGetAnmFrameRate(), then
  TLiveActor::setAnmSound -> MAnmSound::initAnmSound (reset).
- TLiveActor: +0x80 MAnmSound* (derived from JAIAnimeSound).
- JAIAnimeSound (setAnimSoundActor 0x8030019C, initActorAnimSound
  0x80300010, playActorAnimSound 0x803005F0):
    +0x00 8 slots of 0xC: +0 active (u8), +4 JAISound*, +8 event*
    +0x78 mode (1 = forward), +0x7C start index, +0x80 current index,
    +0x84 loop counter, +0x88 previous animation frame (f32),
    +0x90 table (.bas): +0 u16 count, 0x20-byte events from +8
    (event: +0 sound id, +4 start frame, +8 end frame, +0x10 flags,
    +0x16 loop number).

    python tools/watch_gatekeeper.py [secondes]      (défaut 120)
"""
from __future__ import annotations
import struct, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402
from watch_se import snapshot  # noqa: E402

VT = 0x803BB71C
JAI = 0x8040E430


def find(d: Dolphin) -> int | None:
    raw = d.read(0x80000000, 0x01800000)
    key = struct.pack(">I", VT)
    i = raw.find(key)
    while i != -1 and i % 4:
        i = raw.find(key, i + 1)
    return 0x80000000 + i if i != -1 else None


def event_desc(d: Dolphin, table: int, ev: int) -> str:
    if not d.is_valid_pointer(ev):
        return "—"
    k = (ev - table - 8) // 0x20 if d.is_valid_pointer(table) else -1
    sid, f0, f1 = struct.unpack(">Iff", d.read(ev, 12))
    flags = d.u32(ev + 0x10)
    loop = d.u8(ev + 0x16)
    return f"év.{k} son {sid:08X} trames {f0:g}..{f1:g} drapeaux {flags:08X} boucle {loop}"


def main(argv: list[str]) -> int:
    dur = float(argv[1]) if len(argv) > 1 else 120.0
    d = Dolphin()
    print(f"littéral 0x804167B8 = {d.f32(0x804167B8)}", flush=True)
    gk = find(d)
    if gk is None:
        print("aucun TBiancoGateKeeper en MEM1")
        return 1
    print(f"TBiancoGateKeeper @ {gk:08X}", flush=True)
    last_anm, last_state, last_slots, last_fr = None, None, None, None
    prev_se = set(snapshot(d))
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < dur:
        try:
            now = time.perf_counter() - t0
            img = d.u32(d.u32(JAI) + 0x20)
            if d.u32(gk) != VT:
                print(f"[{now:7.3f}s] Gatekeeper disparu", flush=True)
                return 0
            bck = d.u32(d.u32(gk + 0x74) + 0xC)
            idx = struct.unpack(">i", d.read(bck, 4))[0]
            rate, fr = struct.unpack(">2f", d.read(bck + 4 + 0xC, 8))
            snd = d.u32(gk + 0x80)
            raw = d.read(snd, 0x94)
            mode, start, cur, loops = struct.unpack(">4I", raw[0x78:0x88])
            prevf = struct.unpack(">f", raw[0x88:0x8C])[0]
            table = struct.unpack(">I", raw[0x90:0x94])[0]
            slots = tuple(struct.unpack(">BxxxII", raw[k * 0xC:k * 0xC + 0xC]) for k in range(8))
        except (ValueError, RuntimeError) as e:
            print(f"lecture impossible ({e}) : arrêt", flush=True)
            return 0
        tag = f"[{now:7.3f}s img {img}]"
        if idx == 17 and fr != last_fr:
            print(f"{tag}   anim 17 trame {fr:.1f}  sons : index {cur} boucles {loops} trame préc. {prevf:.1f}", flush=True)
        last_fr = fr
        if idx != last_anm:
            print(f"{tag} animation {last_anm} -> {idx}  trame {fr:.1f}  débit {rate:.3f}", flush=True)
            last_anm = idx
        state = (start, cur, loops, table)
        if state != last_state:
            print(f"{tag}   sons : départ {start} index {cur} boucles {loops} "
                  f"trame préc. {prevf:.1f} (trame {fr:.1f}) table {table:08X}", flush=True)
            last_state = state
        if slots != last_slots:
            for k, (act, js, ev) in enumerate(slots):
                if last_slots is None or last_slots[k] != (act, js, ev):
                    print(f"{tag}     empl.{k} actif {act} JAISound {js:08X}  {event_desc(d, table, ev)}", flush=True)
            last_slots = slots
        cur_se = snapshot(d)
        for key in cur_se.keys() - prev_se:
            if key[1] in (0x2891, 0x2892):
                print(f"{tag} >>> CRI {key[1]:04X} @{key[0]:08X}  animation {idx} trame {fr:.1f}", flush=True)
        prev_se = set(cur_se)
        time.sleep(0.001)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
