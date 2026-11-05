"""doubao_profile.py - derive the Doubao hook layout for a new ImeService.exe.

The Remote Mic physicalizer needs three RVAs inside ImeService.exe:

    callback_rva        start of the low-level keyboard hook callback
    early_forward_rva   the `call [CallNextHookEx]` inside it
    early_continue_rva  the instruction right after that call

and a stop wParam, plus content hashes for the build table.  Those numbers are
normally hand-derived per Doubao release.  This tool derives them mechanically:

  1. parse the PE, find the IAT slot for user32!CallNextHookEx
  2. find every `call qword ptr [rip+disp32]` that targets that slot
  3. walk back from each call site to the enclosing function prologue
  4. report (prologue_rva, call_rva, call_rva+6) and the content hashes

Usage:
    python doubao_profile.py "C:\\Program Files\\DoubaoIME\\versions\\vX.Y.Z"
    python doubao_profile.py <dir> --expect 0x7CD5A0   # validate a known build
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pefile

# Both known ImeService builds save r12-r15 high in the prologue.  That
# 8-byte run is rare enough to anchor on, unlike a bare ``push rbp`` which
# also occurs in the middle of ordinary instructions.
PROLOGUE_ANCHOR = b"\x41\x54\x41\x55\x41\x56\x41\x57"
PROLOGUE_LOOKBACK = 0x18           # prologue bytes before the anchor


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call_next_hook_iat(pe: pefile.PE) -> int | None:
    slot = None
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
        if entry.dll.decode(errors="ignore").lower() != "user32.dll":
            continue
        for imp in entry.imports:
            if imp.name and imp.name.decode(errors="ignore") == "CallNextHookEx":
                slot = imp.address - pe.OPTIONAL_HEADER.ImageBase
    return slot


def text_ranges(pe: pefile.PE):
    for section in pe.sections:
        name = section.Name.rstrip(b"\x00")
        if name == b".text":
            yield section.VirtualAddress, section.get_data()


def find_call_sites(code: bytes, base_rva: int, iat_rva: int):
    """`FF 15 disp32` -> call qword ptr [rip+disp32]; rip is the next insn."""
    hits = []
    index = 0
    while True:
        index = code.find(b"\xff\x15", index)
        if index < 0:
            break
        if index + 6 > len(code):
            break
        disp = int.from_bytes(code[index + 2:index + 6], "little", signed=True)
        target = base_rva + index + 6 + disp
        if target == iat_rva:
            hits.append(base_rva + index)
        index += 2
    return hits


def enclosing_prologue(code: bytes, base_rva: int, call_rva: int, window: int = 0x2000):
    """Find the function start that owns ``call_rva``.

    Anchor on the r12-r15 push run, then walk back over the prologue to the
    first byte after the int3 padding.  Requiring the padding boundary is what
    rejects mid-instruction look-alikes.
    """

    offset = call_rva - base_rva
    limit = max(0, offset - window)
    anchor = code.rfind(PROLOGUE_ANCHOR, limit, offset)
    if anchor < 0:
        return None
    start = max(limit, anchor - PROLOGUE_LOOKBACK)
    for pos in range(anchor, start, -1):
        if code[pos - 1] == 0xCC and code[pos] != 0xCC:
            return base_rva + pos
    return None


def profile(directory: Path):
    exe = directory / "ImeService.exe"
    rpc = directory / "doubaoime-rpc-new.dll"
    tsf = directory / "tsf-oime-core.dll"
    for required in (exe, rpc, tsf):
        if not required.is_file():
            raise SystemExit(f"missing: {required}")

    pe = pefile.PE(str(exe), fast_load=False)
    iat = call_next_hook_iat(pe)
    if iat is None:
        raise SystemExit("user32!CallNextHookEx is not imported - layout unknown")

    candidates = []
    for base_rva, code in text_ranges(pe):
        for call_rva in find_call_sites(code, base_rva, iat):
            start = enclosing_prologue(code, base_rva, call_rva)
            if start is None:
                continue
            candidates.append((start, call_rva, call_rva + 6))

    return {
        "ime_service_sha256": sha256(exe),
        "rpc_dll_sha256": sha256(rpc),
        "tsf_core_sha256": sha256(tsf),
        "call_next_hook_iat_rva": iat,
        "candidates": sorted(set(candidates)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--expect", default=None,
                        help="expected callback RVA, e.g. 0x7CD5A0, to validate")
    args = parser.parse_args()

    result = profile(Path(args.directory))
    print(f"ImeService.exe  : {result['ime_service_sha256']}")
    print(f"rpc.dll         : {result['rpc_dll_sha256']}")
    print(f"tsf-oime-core   : {result['tsf_core_sha256']}")
    print(f"CallNextHookEx  : IAT 0x{result['call_next_hook_iat_rva']:X}")
    print(f"candidates ({len(result['candidates'])}):")
    for start, call, cont in result["candidates"]:
        print(f"   callback=0x{start:06X}  forward=0x{call:06X}  "
              f"continue=0x{cont:06X}   layout=({start}, {call}, {cont}, 0, 0)")

    if args.expect:
        want = int(args.expect, 0)
        match = [c for c in result["candidates"] if c[0] == want]
        print()
        print("MATCH" if match else "NO MATCH", f"for callback 0x{want:06X}")
        if match:
            start, call, cont = match[0]
            print(f"({start}, {call}, {cont}, 0, 0)")
        return 0 if match else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
