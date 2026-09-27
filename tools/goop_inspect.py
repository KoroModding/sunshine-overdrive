"""Read-only inspection of the goop layers (TPollutionLayer) and their J3D
materials in the running game, down to the GX display list.

Goal: know exactly what the GPU receives to draw the goop (TEV, alpha compare,
blend, texgen, texture) before changing anything about how it is displayed.
The tool NEVER writes to game memory.

Pointer chain (verified in the US DOL disassembly)
--------------------------------------------------
    TPollutionLayer (vtable 0x803C2160, subclasses Wall*/Wave)
      +0x24 J3DModelData*        +0x28 J3DModel*      +0x2C MActor*
      +0x30 u16 type             +0x54 u8* mask        +0x58 ResTIMG*
    J3DModelData : +0x24 u16 material count, +0x28 J3DMaterial**,
                   +0xAC J3DTexture* (+0 u16 count, +4 ResTIMG[] of 0x20 bytes),
                   +0xB4 material JUTNameTab*
    J3DModel     : +0x04 J3DModelData*, +0x80 J3DMatPacket[] (stride 0x48)
    J3DMatPacket : +0x10 flags (bit 0 = locked), +0x30 J3DDisplayListObj*,
                   +0x38 J3DMaterial*, +0x40 J3DTexture*
    J3DDisplayListObj : +0 active buffer, +4 spare buffer, +8 used size,
                   +0xC capacity (two buffers, swapped by beginDL)
    J3DMaterial  : +0x20 color, +0x24 texgen, +0x28 TEV, +0x2C indirect,
                   +0x30 PE, +0x38 J3DMaterialAnm*, +0x3C shared DL (null
                   unless the model was created with flag 0x20000)
    J3DPEBlockFull : +0x04 fog*, +0x08 u16 alpha compare index (table
                   0x80407150, 3 bytes comp0/op/comp1), +0x0A ref0, +0x0B ref1,
                   +0x0C..0x0F blend type/src/dst/logic, +0x10 u16 zmode
                   index (table 0x80407450), +0x12 zcomploc, +0x13 dither
    J3DTevBlock4 : +0x1C stage count, +0x1D stages (2 raw BP words per stage)

A material's display list is NOT the one from the BMD file: it is built at
runtime by J3DMaterial::makeDisplayList (0x802DAF28) from the blocks, into the
packet's J3DDisplayListObj, then called as-is by J3DMaterial::load (0x802DB08C)
-> callDL (0x802ED8D8).

Usage
-----
    python tools/goop_inspect.py                  all goop layers
    python tools/goop_inspect.py --layer N        only the N-th one
    python tools/goop_inspect.py --model ADDR     one J3DModel or J3DModelData
    python tools/goop_inspect.py --mario          Mario's model
    python tools/goop_inspect.py --list-models    J3DModels in memory
Options: --no-dl (no DL decoding), --hex (raw DL as well),
         --mat N (a single material).

GX decoding: BP (0x61), XF (0x10), CP (0x08), NOP. Fields follow the hardware
documentation as used by Dolphin (BPMemory.h, XFMemory.h). The raw value is
always printed next to the decoding.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dolphin import Dolphin  # noqa: E402
from symbols import SymbolTable  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "work" / "maps" / "us.map"

# GMSE01 addresses

LAYER_VTABLES = {
    0x803C2160: "TPollutionLayer",
    0x803C21BC: "TPollutionLayerWallBase",
    0x803C2218: "TPollutionLayerWallPlusX",
    0x803C1E90: "TPollutionLayerWallMinusX",
    0x803C2274: "TPollutionLayerWallPlusZ",
    0x803C1EEC: "TPollutionLayerWallMinusZ",
    0x803C22D0: "TPollutionLayerWave",
}
VT_J3DMODEL = 0x803E115C
VT_J3DMODELDATA = 0x803E1178
VT_PEBLOCK_FULL = 0x803E0968
VT_TEVBLOCK4 = 0x803E0AB0        # +0x1C stage count, +0x1D stages (8 bytes: 2 BP words)
ALPHACMP_TABLE = 0x80407150      # j3dAlphaCmpTable: 3 bytes per entry
ZMODE_TABLE = 0x80407450         # j3dZModeTable:    3 bytes per entry
GP_MARIO = 0x8040E0E8            # TMario* ; +0x3A8 M3UModel* ; +0x8 J3DModel*
MEM1_END = 0x81800000

CMP = ["NEVER", "LESS", "EQUAL", "LEQUAL", "GREATER", "NEQUAL", "GEQUAL", "ALWAYS"]
AOP = ["AND", "OR", "XOR", "XNOR"]
BL_SRC = ["ZERO", "ONE", "DSTCLR", "INVDSTCLR", "SRCALPHA", "INVSRCALPHA", "DSTALPHA", "INVDSTALPHA"]
BL_DST = ["ZERO", "ONE", "SRCCLR", "INVSRCCLR", "SRCALPHA", "INVSRCALPHA", "DSTALPHA", "INVDSTALPHA"]
LOGIC = ["CLEAR", "AND", "REVAND", "COPY", "INVAND", "NOOP", "XOR", "OR",
         "NOR", "EQUIV", "INV", "REVOR", "INVCOPY", "INVOR", "NAND", "SET"]
BM_TYPE = ["NONE", "BLEND", "LOGIC", "SUBTRACT"]
CC_IN = ["CPREV", "APREV", "C0", "A0", "C1", "A1", "C2", "A2",
         "TEXC", "TEXA", "RASC", "RASA", "ONE", "HALF", "KONST", "ZERO"]
CA_IN = ["APREV", "A0", "A1", "A2", "TEXA", "RASA", "KONST", "ZERO"]
BIAS = ["0", "+0.5", "-0.5", "COMPARE"]
SCALE = ["x1", "x2", "x4", "x0.5"]
DEST = ["PREV", "REG0", "REG1", "REG2"]
CMP_MODE_C = ["R8", "GR16", "BGR24", "RGB8"]
CMP_MODE_A = ["R8", "GR16", "BGR24", "A8"]
RAS_CHAN = {0: "COLOR0A0", 1: "COLOR1A1", 5: "ALPHA_BUMP", 6: "ALPHA_BUMPN", 7: "ZERO"}
CULL = ["NONE", "BACK", "FRONT", "ALL"]
WRAP = ["CLAMP", "REPEAT", "MIRROR", "?3"]
TEXFMT = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3",
          6: "RGBA8", 8: "C4", 9: "C8", 0xA: "C14X2", 0xE: "CMPR"}
FILTER = ["NEAR", "LINEAR", "NEAR_MIP_NEAR", "LIN_MIP_NEAR", "NEAR_MIP_LIN", "LIN_MIP_LIN"]
KCSEL = {0: "1", 1: "7/8", 2: "3/4", 3: "5/8", 4: "1/2", 5: "3/8", 6: "1/4", 7: "1/8"}
for _k in range(4):
    KCSEL[0x0C + _k] = f"K{_k}"
    KCSEL[0x10 + _k] = f"K{_k}_R"
    KCSEL[0x14 + _k] = f"K{_k}_G"
    KCSEL[0x18 + _k] = f"K{_k}_B"
    KCSEL[0x1C + _k] = f"K{_k}_A"
TG_TYPE = ["REGULAR", "EMBOSS", "COLOR0", "COLOR1", "?4", "?5", "?6", "?7"]
# GX API enums (J3DTexCoord fields), distinct from the XF encoding
API_TG_TYPE = ["MTX3x4", "MTX2x4"] + [f"BUMP{i}" for i in range(8)] + ["SRTG"]
API_TG_SRC = (["POS", "NRM", "BINRM", "TANGENT"] + [f"TEX{i}" for i in range(8)]
              + [f"TEXCOORD{i}" for i in range(7)] + ["COLOR0", "COLOR1"])
TG_SRC = ["POS", "NRM", "COLORS", "BINRM_T", "BINRM_B"] + [f"TEX{i}" for i in range(8)]
ZFUNC = CMP


def bits(v: int, lo: int, n: int) -> int:
    return (v >> lo) & ((1 << n) - 1)


def s11(v: int) -> int:
    return v - 0x800 if v & 0x400 else v


def _texmap_reg(reg: int) -> tuple[str, int] | None:
    """(kind, texmap) for texture registers 0x80-0xBB."""
    groups = ["MODE0", "MODE1", "IMAGE0", "IMAGE1", "IMAGE2", "IMAGE3", "TLUT"]
    for base, first in ((0x80, 0), (0xA0, 4)):
        off = reg - base
        if 0 <= off < 0x1C:
            return groups[off // 4], first + off % 4
    return None


def decode_bp(reg: int, v: int, mask: int | None = None) -> str:
    if reg == 0x00:
        return (f"GENMODE texgens={bits(v,0,4)} chans={bits(v,4,3)} "
                f"tevstages={bits(v,10,4)+1} cull={CULL[bits(v,14,2)]} "
                f"indstages={bits(v,16,3)}")
    if 0x06 <= reg <= 0x0E:
        k, r = divmod(reg - 0x06, 3)
        return (f"IND_MTX{k}{'ABC'[r]} m0={s11(bits(v,0,11))/1024:+.4f} "
                f"m1={s11(bits(v,11,11))/1024:+.4f} sbits={bits(v,22,2)}")
    if reg == 0x0F:
        return f"IND_IMASK {v:06X}"
    if 0x10 <= reg <= 0x1F:
        return (f"IND_CMD stage{reg-0x10} indstage={bits(v,0,2)} fmt={bits(v,2,2)} "
                f"bias={bits(v,4,3):03b} alpha={bits(v,7,2)} mtx={bits(v,9,4)} "
                f"wrapS={bits(v,13,3)} wrapT={bits(v,16,3)} utclod={bits(v,19,1)} "
                f"addprev={bits(v,20,1)}")
    if reg in (0x25, 0x26):
        s = (reg - 0x25) * 2
        return (f"RAS1_SS{reg-0x25} ind{s}: s>>{bits(v,0,4)} t>>{bits(v,4,4)}  "
                f"ind{s+1}: s>>{bits(v,8,4)} t>>{bits(v,12,4)}")
    if reg == 0x27:
        return "RAS1_IREF " + "  ".join(
            f"ind{i}: map{bits(v,6*i,3)} coord{bits(v,6*i+3,3)}" for i in range(4))
    if 0x28 <= reg <= 0x2F:
        s = (reg - 0x28) * 2
        out = []
        for k, lo in ((0, 0), (1, 12)):
            en = bits(v, lo + 6, 1)
            out.append(f"stage{s+k}: map{bits(v,lo,3) if en else '-'} "
                       f"coord{bits(v,lo+3,3)} tex={'on' if en else 'off'} "
                       f"ras={RAS_CHAN.get(bits(v,lo+7,3), bits(v,lo+7,3))}")
        return "TEV_ORDER " + " | ".join(out)
    if 0x30 <= reg <= 0x3F:
        c, t = divmod(reg - 0x30, 2)
        name = "SSIZE" if t == 0 else "TSIZE"
        return (f"SU_{name} coord{c} size={bits(v,0,16)+1} bias={bits(v,16,1)} "
                f"cylwrap={bits(v,17,1)}")
    if reg == 0x40:
        return (f"PE_ZMODE test={bits(v,0,1)} func={ZFUNC[bits(v,1,3)]} "
                f"update={bits(v,4,1)}")
    if reg == 0x41:
        fields = [(0, 1, "blend", str), (1, 1, "logic", str), (2, 1, "dither", str),
                  (3, 1, "colorupd", str), (4, 1, "alphaupd", str),
                  (8, 3, "src", BL_SRC.__getitem__), (5, 3, "dst", BL_DST.__getitem__),
                  (11, 1, "subtract", str), (12, 4, "logicop", LOGIC.__getitem__)]
        shown, kept = [], []
        for lo, n, name, fmt in fields:
            fmask = ((1 << n) - 1) << lo
            if mask is None or mask & fmask == fmask:
                shown.append(f"{name}={fmt(bits(v, lo, n))}")
            else:
                kept.append(name)
        return ("PE_CMODE0 " + " ".join(shown)
                + (f"  (inchangés, hors masque : {', '.join(kept)})" if kept else ""))
    if reg == 0x42:
        return f"PE_CMODE1 constalpha_en={bits(v,8,1)} constalpha={bits(v,0,8)}"
    if reg == 0x43:
        return (f"PE_CONTROL pixfmt={bits(v,0,3)} zfmt={bits(v,3,3)} "
                f"zcomploc={'avant texture' if bits(v,6,1) else 'apres texture'}")
    if reg == 0x66:
        return "TX_INVALIDATE (cache de texture)"
    tm = _texmap_reg(reg)
    if tm:
        kind, m = tm
        if kind == "MODE0":
            mip = bits(v, 5, 2)
            minf = ("LIN" if bits(v, 7, 1) else "NEAR") + (["", "_MIP_NEAR", "_MIP_LIN", "_MIP?"][mip])
            lb = bits(v, 9, 8)
            lb = lb - 256 if lb & 0x80 else lb
            return (f"TX_MODE0 map{m} wrapS={WRAP[bits(v,0,2)]} wrapT={WRAP[bits(v,2,2)]} "
                    f"mag={'LINEAR' if bits(v,4,1) else 'NEAR'} min={minf} "
                    f"lodbias={lb/32:+.2f} diaglod={bits(v,8,1)} aniso={bits(v,19,2)} "
                    f"lodclamp={bits(v,21,1)}")
        if kind == "MODE1":
            return f"TX_MODE1 map{m} minlod={bits(v,0,8)/16} maxlod={bits(v,8,8)/16}"
        if kind == "IMAGE0":
            return (f"TX_IMAGE0 map{m} {bits(v,0,10)+1}x{bits(v,10,10)+1} "
                    f"fmt={TEXFMT.get(bits(v,20,4), bits(v,20,4))}")
        if kind in ("IMAGE1", "IMAGE2"):
            return (f"TX_{kind} map{m} tmem=0x{bits(v,0,15)*32:05X} "
                    f"cachew={bits(v,15,3)} cacheh={bits(v,18,3)} preload={bits(v,21,1)}")
        if kind == "IMAGE3":
            return f"TX_IMAGE3 map{m} adresse=0x{0x80000000 | (bits(v,0,24) << 5):08X}"
        return f"TX_TLUT map{m} tmem=0x{bits(v,0,10) << 9:05X} fmt={bits(v,10,2)}"
    if 0xC0 <= reg <= 0xDF:
        s, alpha = divmod(reg - 0xC0, 2)
        bias, op, sc = bits(v, 16, 2), bits(v, 18, 1), bits(v, 20, 2)
        dest, clamp = DEST[bits(v, 22, 2)], bits(v, 19, 1)
        if not alpha:
            a, b, c, d = (CC_IN[bits(v, lo, 4)] for lo in (12, 8, 4, 0))
            kind = "TEV_COLOR_ENV"
        else:
            a, b, c, d = (CA_IN[bits(v, lo, 3)] for lo in (13, 10, 7, 4))
            kind = "TEV_ALPHA_ENV"
        if bias == 3:
            mode = (CMP_MODE_A if alpha else CMP_MODE_C)[sc]
            formula = (f"{d} + (({a} {'==' if op else '>'} {b}) [{mode}] ? {c} : 0)")
        else:
            formula = (f"({d} {'-' if op else '+'} lerp({a},{b},{c}) {BIAS[bias]}) "
                       f"{SCALE[sc]}")
        extra = f" rswap={bits(v,0,2)} tswap={bits(v,2,2)}" if alpha else ""
        return (f"{kind} stage{s}: {dest} = {formula}"
                f"{' clamp' if clamp else ''}  [a={a} b={b} c={c} d={d} "
                f"bias={BIAS[bias]} op={'SUB' if op else 'ADD'} scale={SCALE[sc]}]{extra}")
    if 0xE0 <= reg <= 0xE7:
        r, hi = divmod(reg - 0xE0, 2)
        konst = bits(v, 23, 1)
        x, y = bits(v, 0, 11), bits(v, 12, 11)
        if not konst:
            x, y = s11(x), s11(y)
        name = f"K{r}" if konst else ["PREV", "C0", "C1", "C2"][r]
        return (f"TEV_REG {name} " + (f"B={x} G={y}" if hi else f"R={x} A={y}"))
    if reg == 0xE8:
        return f"FOG_RANGE {v:06X}"
    if 0xEE <= reg <= 0xF2:
        return f"FOG_PARAM{reg-0xEE} {v:06X}"
    if reg == 0xF3:
        return (f"ALPHA_COMPARE (A {CMP[bits(v,16,3)]} {bits(v,0,8)}) "
                f"{AOP[bits(v,22,2)]} (A {CMP[bits(v,19,3)]} {bits(v,8,8)})")
    if reg == 0xF4:
        return f"TEV_Z_ENV0 zbias={v}"
    if reg == 0xF5:
        return f"TEV_Z_ENV1 type={bits(v,0,2)} op={bits(v,2,2)}"
    if 0xF6 <= reg <= 0xFD:
        i = reg - 0xF6
        t, half = divmod(i, 2)
        sw = ("r" if half == 0 else "b", "g" if half == 0 else "a")
        return (f"TEV_KSEL{i} swap{t}.{sw[0]}={bits(v,0,2)} swap{t}.{sw[1]}={bits(v,2,2)}  "
                f"stage{2*i}: kc={KCSEL.get(bits(v,4,5), bits(v,4,5))} "
                f"ka={KCSEL.get(bits(v,9,5), bits(v,9,5))}  "
                f"stage{2*i+1}: kc={KCSEL.get(bits(v,14,5), bits(v,14,5))} "
                f"ka={KCSEL.get(bits(v,19,5), bits(v,19,5))}")
    if reg == 0xFE:
        return f"BP_MASK {v:06X} (ne s'applique qu'à l'écriture BP suivante)"
    return "(registre BP non décodé)"


def _f(u: int) -> float:
    return struct.unpack(">f", struct.pack(">I", u))[0]


def decode_xf(addr: int, values: list[int]) -> list[str]:
    out = []
    if addr < 0x100:
        mid = addr // 4
        name = f"PNMTX{mid//3}" if mid < 30 else f"TEXMTX{(mid-30)//3}"
        out.append(f"XF matrice {name} (id GX {mid}), {len(values)} flottants")
        for i in range(0, len(values), 4):
            out.append("    " + " ".join(f"{_f(x):+9.4f}" for x in values[i:i+4]))
        return out
    if 0x400 <= addr < 0x460:
        out.append(f"XF matrice normale @0x{addr:03X}, {len(values)} flottants")
        return out
    if 0x500 <= addr < 0x600:
        mid = (addr - 0x500) // 4
        out.append(f"XF matrice post-transfo DTT id {mid + 64}, {len(values)} flottants")
        for i in range(0, len(values), 4):
            out.append("    " + " ".join(f"{_f(x):+9.4f}" for x in values[i:i+4]))
        return out
    if 0x600 <= addr < 0x680:
        out.append(f"XF lumière @0x{addr:03X}, {len(values)} mots")
        return out
    for i, v in enumerate(values):
        a = addr + i
        if a == 0x1008:
            s = f"VTXSPECS colors={bits(v,0,2)} normals={bits(v,2,2)} texs={bits(v,4,4)}"
        elif a == 0x1009:
            s = f"NUMCHAN {bits(v,0,2)} (canaux couleur)"
        elif a in (0x100A, 0x100B):
            s = f"AMB_COLOR{a-0x100A} RGBA={v:08X}"
        elif a in (0x100C, 0x100D):
            s = f"MAT_COLOR{a-0x100C} RGBA={v:08X}"
        elif 0x100E <= a <= 0x1011:
            nm = ["COLOR0", "COLOR1", "ALPHA0", "ALPHA1"][a - 0x100E]
            mask = bits(v, 2, 4) | (bits(v, 11, 4) << 4)
            s = (f"CHAN_CTRL {nm} matsrc={'VTX' if bits(v,0,1) else 'REG'} "
                 f"lighting={bits(v,1,1)} ambsrc={'VTX' if bits(v,6,1) else 'REG'} "
                 f"lights={mask:08b} diffuse={bits(v,7,2)} attn={bits(v,9,2)}")
        elif a == 0x1012:
            s = f"DUALTEX enable={bits(v,0,1)}"
        elif a == 0x1018:
            s = ("MATIDX_A pos=" + str(bits(v, 0, 6)) + " " +
                 " ".join(f"tex{k}={bits(v,6+6*k,6)}" for k in range(4)))
        elif a == 0x1019:
            s = "MATIDX_B " + " ".join(f"tex{4+k}={bits(v,6*k,6)}" for k in range(4))
        elif a == 0x103F:
            s = f"NUMTEXGENS {v}"
        elif 0x1040 <= a <= 0x1047:
            src = bits(v, 7, 5)
            s = (f"TEXGEN{a-0x1040} type={TG_TYPE[bits(v,4,3)]} "
                 f"src={TG_SRC[src] if src < len(TG_SRC) else src} "
                 f"proj={'STQ' if bits(v,1,1) else 'ST'} "
                 f"input={'ABC1' if bits(v,2,1) else 'AB11'} "
                 f"emboss src={bits(v,12,3)} light={bits(v,15,3)}")
        elif 0x1050 <= a <= 0x1057:
            s = (f"POSTTEX{a-0x1050} mtx=PTTMTX id {bits(v,0,6)+64} "
                 f"normalize={bits(v,8,1)}")
        else:
            s = "(registre XF non décodé)"
        out.append(f"XF[0x{a:04X}] = {v:08X}  {s}")
    return out


def decode_dl(data: bytes) -> list[str]:
    out: list[str] = []
    i, n, mask = 0, len(data), None
    nops = 0
    while i < n:
        op = data[i]
        if op == 0x00:
            nops += 1
            i += 1
            continue
        if nops:
            out.append(f"      ({nops} NOP)")
            nops = 0
        if op == 0x61 and i + 5 <= n:
            word = struct.unpack_from(">I", data, i + 1)[0]
            reg, val = word >> 24, word & 0xFFFFFF
            note = ""
            if mask is not None and reg != 0xFE:
                note = f"  [masque {mask:06X}]"
            out.append(f"{i:04X} BP {reg:02X} {val:06X}  "
                       f"{decode_bp(reg, val, mask if reg != 0xFE else None)}{note}")
            mask = val if reg == 0xFE else None
            i += 5
        elif op == 0x10 and i + 5 <= n:
            hdr = struct.unpack_from(">I", data, i + 1)[0]
            cnt, addr = bits(hdr, 16, 4) + 1, hdr & 0xFFFF
            vals = [struct.unpack_from(">I", data, i + 5 + 4 * k)[0]
                    for k in range(cnt) if i + 9 + 4 * k <= n]
            raw = " ".join(f"{x:08X}" for x in vals)
            out.append(f"{i:04X} XF {addr:04X} x{cnt}  {raw}")
            out.extend("       " + line for line in decode_xf(addr, vals))
            i += 5 + 4 * cnt
        elif op == 0x08 and i + 6 <= n:
            reg = data[i + 1]
            val = struct.unpack_from(">I", data, i + 2)[0]
            out.append(f"{i:04X} CP {reg:02X} {val:08X}  (registre CP)")
            i += 6
        elif op in (0x20, 0x28, 0x30, 0x38) and i + 5 <= n:
            word = struct.unpack_from(">I", data, i + 1)[0]
            out.append(f"{i:04X} LOAD_INDX_{'ABCD'[(op-0x20)//8]} {word:08X}")
            i += 5
        elif op == 0x48:
            out.append(f"{i:04X} INVALIDATE_VTX_CACHE")
            i += 1
        else:
            out.append(f"{i:04X} commande 0x{op:02X} inconnue ou primitive — "
                       f"reste brut : {data[i:i+32].hex(' ')}")
            break
    if nops:
        out.append(f"      ({nops} NOP)")
    return out


class Inspector:
    def __init__(self, d: Dolphin, show_dl: bool, show_hex: bool, only_mat: int | None):
        self.d = d
        self.show_dl = show_dl
        self.show_hex = show_hex
        self.only_mat = only_mat
        try:
            self.sym = SymbolTable.load(MAP)
        except OSError:
            self.sym = None

    def ptr(self, v: int) -> bool:
        return 0x80000000 <= v < MEM1_END

    def vtclass(self, vt: int) -> str:
        if self.sym:
            s = self.sym.at(vt)
            if s and s.name.startswith("__vt__"):
                raw = s.name[6:]
                k = 0
                while k < len(raw) and raw[k].isdigit():
                    k += 1
                return raw[k:] if k else raw
        return f"0x{vt:08X}"

    def scan(self, targets: set[int]) -> list[tuple[int, int]]:
        mem = self.d.read(0x80000000, 0x1800000)
        found = []
        for off in range(0, len(mem) - 4, 4):
            v = struct.unpack_from(">I", mem, off)[0]
            if v in targets:
                found.append((0x80000000 + off, v))
        return found

    def find_layers(self) -> list[tuple[int, str]]:
        out = []
        for addr, vt in self.scan(set(LAYER_VTABLES)):
            name = LAYER_VTABLES[vt]
            if name == "TPollutionLayerWave":
                if self.ptr(self.d.u32(addr + 0x58)):
                    out.append((addr, name))
                continue
            md, mdl = self.d.u32(addr + 0x24), self.d.u32(addr + 0x28)
            if (self.ptr(md) and self.ptr(mdl) and self.d.u32(md) == VT_J3DMODELDATA
                    and self.d.u32(mdl) == VT_J3DMODEL and self.d.u32(mdl + 4) == md):
                out.append((addr, name))
        return out

    def restimg(self, t: int, label: str) -> None:
        d = self.d
        fmt, alpha = d.u8(t), d.u8(t + 1)
        w, h = d.u16(t + 2), d.u16(t + 4)
        ws, wt = d.u8(t + 6), d.u8(t + 7)
        minf, magf = d.u8(t + 0x14), d.u8(t + 0x15)
        mip, cnt = d.u8(t + 0x10), d.u8(t + 0x18)
        lodb = struct.unpack(">h", d.read(t + 0x1A, 2))[0]
        off = d.u32(t + 0x1C)
        print(f"  {label} ResTIMG @0x{t:08X} : {w}x{h} {TEXFMT.get(fmt, fmt)} "
              f"alphaEnabled={alpha} wrap={WRAP[ws & 3]}/{WRAP[wt & 3]} "
              f"min={FILTER[minf] if minf < 6 else minf} mag={FILTER[magf] if magf < 6 else magf} "
              f"mip={mip} n={cnt} lodbias={lodb/100:+.2f} "
              f"données=0x{(t + off) & 0xFFFFFFFF:08X}")

    def material_names(self, md: int) -> list[str]:
        d = self.d
        nt = d.u32(md + 0xB4)
        if not self.ptr(nt):
            return []
        res, num = d.u32(nt), d.u16(nt + 8)
        if not self.ptr(res) or num > 512:
            return []
        names = []
        for i in range(num):
            o = d.u16(res + 6 + 4 * i)
            raw = d.read(res + o, 64)
            names.append(raw.split(b"\0")[0].decode("ascii", "replace"))
        return names

    def texgen_block(self, blk: int) -> None:
        d = self.d
        num = d.u32(blk + 4)
        print(f"      texgen : {num} coordonnée(s)", end="")
        for i in range(min(num, 8)):
            typ, src, mtx = d.u8(blk + 8 + 4 * i), d.u8(blk + 9 + 4 * i), d.u8(blk + 10 + 4 * i)
            mname = "IDENTITY" if mtx == 60 else (f"TEXMTX{(mtx-30)//3}" if 30 <= mtx < 60 else f"PNMTX{mtx//3}")
            tn = API_TG_TYPE[typ] if typ < len(API_TG_TYPE) else typ
            sn = API_TG_SRC[src] if src < len(API_TG_SRC) else src
            print(f"  [{i}] {tn} src={sn} mtx={mname}", end="")
        print()
        for i in range(8):
            tm = d.u32(blk + 0x28 + 4 * i)
            if not self.ptr(tm):
                continue
            proj, info = d.u8(tm), d.u8(tm + 1)
            sx, sy = d.f32(tm + 0x10), d.f32(tm + 0x14)
            rot = struct.unpack(">h", d.read(tm + 0x18, 2))[0]
            tx, ty = d.f32(tm + 0x1C), d.f32(tm + 0x20)
            print(f"      J3DTexMtx[{i}] @0x{tm:08X} proj={proj} mode={info & 0x7F} "
                  f"SRT: échelle=({sx:.4f},{sy:.4f}) rot={rot} trans=({tx:.4f},{ty:.4f})"
                  "   (champs SRT : d'après la décomp, non vérifiés)")

    def tev_block(self, blk: int) -> None:
        """TEV stages as stored in the block: each J3DTevStage is the raw copy
        of the two BP words (0xC0+2s color, 0xC1+2s alpha) that load() copies
        into the DL. Offsets verified for J3DTevBlock4 only
        (load__12J3DTevBlock4Fv 0x802D8544: +0x0C order, +0x1D stages,
        +0x3E S10 colors, +0x5E K colors)."""
        d = self.d
        if d.u32(blk) != VT_TEVBLOCK4:
            return
        n = d.u8(blk + 0x1C)
        print(f"      TEV J3DTevBlock4 @0x{blk:08X} : {n} étage(s) (+0x1C)")
        for st in range(min(n, 4)):
            for half in range(2):
                a = blk + 0x1D + 8 * st + 4 * half
                w = struct.unpack(">I", d.read(a, 4))[0]
                print(f"        @0x{a:08X} (+0x{a - blk:02X}) {w >> 24:02X} {w & 0xFFFFFF:06X}  "
                      f"{decode_bp(w >> 24, w & 0xFFFFFF)}")

    def pe_block(self, blk: int) -> None:
        d = self.d
        vt = d.u32(blk)
        if vt != VT_PEBLOCK_FULL:
            print(f"      PE : {self.vtclass(vt)} (valeurs fixes codées dans son load())")
            return
        fog = d.u32(blk + 4)
        ac = d.u16(blk + 8)
        r0, r1 = d.u8(blk + 0xA), d.u8(blk + 0xB)
        bt, bs, bd, bl = (d.u8(blk + 0xC + k) for k in range(4))
        zm, zc, di = d.u16(blk + 0x10), d.u8(blk + 0x12), d.u8(blk + 0x13)
        if ac != 0xFFFF:
            c0, op, c1 = (d.u8(ALPHACMP_TABLE + 3 * ac + k) for k in range(3))
            acs = f"(A {CMP[c0 & 7]} {r0}) {AOP[op & 3]} (A {CMP[c1 & 7]} {r1})"
        else:
            acs = "non chargé"
        if zm != 0xFFFF:
            ze, zf, zu = (d.u8(ZMODE_TABLE + 3 * zm + k) for k in range(3))
            zs = f"test={ze} func={ZFUNC[zf & 7]} update={zu}"
        else:
            zs = "non chargé"
        print(f"      PE J3DPEBlockFull @0x{blk:08X} : fog=0x{fog:08X}")
        print(f"        +0x08 alphacomp id={ac} → {acs}   (+0x0A ref0={r0}, +0x0B ref1={r1})")
        print(f"        +0x0C blend type={BM_TYPE[bt & 3] if bt < 4 else bt} src={BL_SRC[bs & 7]} "
              f"dst={BL_DST[bd & 7]} logic={LOGIC[bl & 15]}")
        print(f"        +0x10 zmode id={zm} → {zs}   +0x12 zcomploc={zc}  +0x13 dither={di}")

    def model(self, mdl: int, md: int | None = None, actor: int | None = None) -> None:
        d = self.d
        if md is None:
            md = d.u32(mdl + 4) if mdl else 0
        nmat = d.u16(md + 0x24)
        mats = d.u32(md + 0x28)
        tex = d.u32(md + 0xAC)
        names = self.material_names(md)
        print(f"  J3DModelData @0x{md:08X} : {nmat} matériau(x), J3DTexture @0x{tex:08X}"
              + (f" ({d.u16(tex)} texture(s))" if self.ptr(tex) else ""))
        if self.ptr(tex):
            res = d.u32(tex + 4)
            for k in range(min(d.u16(tex), 8)):
                self.restimg(res + 0x20 * k, f"tex{k}")
        if mdl:
            print(f"  J3DModel     @0x{mdl:08X} : paquets matériau @0x{d.u32(mdl + 0x80):08X}")
        if actor and self.ptr(actor):
            a2c, a30 = d.u32(actor + 0x2C), d.u32(actor + 0x30)
            print(f"  MActor       @0x{actor:08X} : makeDL={d.u8(actor + 0x38)} "
                  f"btk=0x{d.u32(actor + 0x1C):08X} bpk=0x{d.u32(actor + 0x14):08X} "
                  f"brk=0x{d.u32(actor + 0x20):08X}")
        for i in range(nmat):
            if self.only_mat is not None and i != self.only_mat:
                continue
            m = d.u32(mats + 4 * i)
            nm = names[i] if i < len(names) else "?"
            blocks = [d.u32(m + o) for o in (0x20, 0x24, 0x28, 0x2C, 0x30)]
            print(f"\n  --- matériau {i} « {nm} » @0x{m:08X}  drawmode(+8)=0x{d.u32(m + 8):X} "
                  f"sortkey(+0x18)=0x{d.u32(m + 0x18):08X}")
            print("      blocs : " + "  ".join(
                f"{lbl}={self.vtclass(d.u32(b)) if self.ptr(b) else 'nul'}@0x{b:08X}"
                for lbl, b in zip(("couleur", "texgen", "tev", "ind", "pe"), blocks)))
            anm = d.u32(m + 0x38)
            print(f"      J3DMaterialAnm(+0x38)=0x{anm:08X}  DL partagée(+0x3C)=0x{d.u32(m + 0x3C):08X}")
            if actor and self.ptr(actor):
                a2c, a30 = d.u32(actor + 0x2C), d.u32(actor + 0x30)
                if self.ptr(a2c) and self.ptr(a30):
                    print(f"      MActor anm[+0x2C]={d.u16(a2c + 2*i)} texmtx[+0x30]={d.u16(a30 + 2*i)}"
                          "  (0x32 = rien → DL figée)")
            if self.ptr(blocks[1]):
                self.texgen_block(blocks[1])
            if self.ptr(blocks[2]):
                self.tev_block(blocks[2])
            if self.ptr(blocks[4]):
                self.pe_block(blocks[4])
            dlobj = 0
            if mdl:
                pk = d.u32(mdl + 0x80) + 0x48 * i
                flags, dlobj = d.u32(pk + 0x10), d.u32(pk + 0x30)
                pm = d.u32(pk + 0x38)
                print(f"      J3DMatPacket @0x{pk:08X} : verrouillé={flags & 1} "
                      f"(DL {'figée' if flags & 1 else 'refaite par J3DJoint::entryIn à chaque entrée en draw buffer'})"
                      f"  matériau={'OK' if pm == m else f'0x{pm:08X} ≠'}")
            elif self.ptr(d.u32(m + 0x3C)):
                dlobj = d.u32(m + 0x3C)
            if not self.ptr(dlobj):
                print("      (pas de display list accessible)")
                continue
            b0, b1, size, cap = (d.u32(dlobj + 4 * k) for k in range(4))
            print(f"      J3DDisplayListObj @0x{dlobj:08X} : actif=0x{b0:08X} réserve=0x{b1:08X} "
                  f"taille={size} capacité={cap}")
            if not self.show_dl or not self.ptr(b0) or not 0 < size <= 0x2000:
                continue
            data = d.read(b0, size)
            if self.show_hex:
                for k in range(0, len(data), 32):
                    print(f"      {k:04X}: {data[k:k+32].hex(' ')}")
            for line in decode_dl(data):
                print("      " + line)

    def layer(self, idx: int, addr: int, name: str) -> None:
        d = self.d
        typ, fl = d.u16(addr + 0x30), d.u16(addr + 0x32)
        area = [d.f32(addr + o) for o in (0x38, 0x3C, 0x40, 0x44)]
        mask, timg = d.u32(addr + 0x54), d.u32(addr + 0x58)
        print(f"\n=== couche {idx} : {name} @0x{addr:08X}  type(+0x30)={typ} "
              f"drapeaux(+0x32)=0x{fl:04X}")
        print(f"  zone X[{area[0]:.0f} ; {area[1]:.0f}]  Z[{area[2]:.0f} ; {area[3]:.0f}]")
        if self.ptr(timg):
            self.restimg(timg, "masque")
            same = mask == (timg + d.u32(timg + 0x1C)) & 0xFFFFFFFF
            print(f"  masque(+0x54)=0x{mask:08X}  "
                  f"{'= données de la texture (+0x58 + imageDataOffset)' if same else '≠ données de la texture !'}")
        if name == "TPollutionLayerWave":
            print("  (Wave : dessin GX direct par initGX/draw, pas de J3DModel)")
            return
        md, mdl, actor = d.u32(addr + 0x24), d.u32(addr + 0x28), d.u32(addr + 0x2C)
        tex = d.u32(md + 0xAC)
        if self.ptr(tex):
            t0 = d.u32(tex + 4)
            print(f"  texture 0 du modèle = 0x{t0:08X} "
                  f"{'= ResTIMG de la couche' if t0 == timg else '≠ ResTIMG de la couche'}")
        self.model(mdl, md, actor)


def _main(argv: list[str]) -> int:
    args = argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0

    def opt(name: str) -> str | None:
        if name in args:
            k = args.index(name)
            return args[k + 1] if k + 1 < len(args) else None
        return None

    only_mat = opt("--mat")
    ins = Inspector(Dolphin(), "--no-dl" not in args, "--hex" in args,
                    int(only_mat, 0) if only_mat is not None else None)
    d = ins.d

    if "--list-models" in args:
        for addr, _ in ins.scan({VT_J3DMODEL}):
            md = d.u32(addr + 4)
            if ins.ptr(md) and d.u32(md) == VT_J3DMODELDATA:
                tex = d.u32(md + 0xAC)
                names = ins.material_names(md)
                print(f"J3DModel 0x{addr:08X}  data 0x{md:08X}  {d.u16(md + 0x24):3} mat  "
                      f"{d.u16(tex) if ins.ptr(tex) else 0:3} tex  {', '.join(names[:4])}")
        return 0

    if "--mario" in args:
        mario = d.u32(GP_MARIO)
        m3u = d.u32(mario + 0x3A8) if ins.ptr(mario) else 0
        mdl = d.u32(m3u + 8) if ins.ptr(m3u) else 0
        if not ins.ptr(mdl) or d.u32(mdl) != VT_J3DMODEL:
            print("modèle de Mario introuvable (gpMarioOriginal → +0x3A8 → +0x8)")
            return 1
        print(f"Mario : TMario 0x{mario:08X} → M3UModel 0x{m3u:08X} → J3DModel 0x{mdl:08X}")
        ins.model(mdl)
        return 0

    target = opt("--model")
    if target is not None:
        a = int(target, 0)
        vt = d.u32(a)
        if vt == VT_J3DMODEL:
            ins.model(a)
        elif vt == VT_J3DMODELDATA:
            owners = [x for x, _ in ins.scan({VT_J3DMODEL}) if d.u32(x + 4) == a]
            print(f"J3DModelData : {len(owners)} J3DModel l'utilisent "
                  + " ".join(f"0x{x:08X}" for x in owners))
            ins.model(owners[0] if owners else 0, a)
        else:
            print(f"0x{a:08X} n'est ni un J3DModel ni un J3DModelData (vtable 0x{vt:08X})")
            return 1
        return 0

    layers = ins.find_layers()
    print(f"{len(layers)} couche(s) de goop trouvée(s) en MEM1.")
    which = opt("--layer")
    for i, (addr, name) in enumerate(layers):
        if which is None or int(which, 0) == i:
            ins.layer(i, addr, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
