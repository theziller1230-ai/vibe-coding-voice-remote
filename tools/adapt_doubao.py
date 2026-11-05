"""adapt_doubao.py - add a new Doubao build to the hook/stop tables automatically.

Everything the tables need is derivable from the installed files:

    ImeService.exe    sha256              -> _VERIFIED_IME_SERVICE_BUILDS key
    doubaoime-rpc-new.dll sha256          -> _VERIFIED_VOICE_STOP_BUILDS key
    tsf-oime-core.dll sha256              -> recorded next to the rpc key
    callback/forward/continue RVAs        -> located via the CallNextHookEx IAT
    prologue + forward bytes              -> read straight from those RVAs

Usage:
    python tools/adapt_doubao.py                 # dry run, active VersionDir
    python tools/adapt_doubao.py --write         # patch doubao_rpc.py in place
    python tools/adapt_doubao.py --dir "...\\vX.Y.Z" --write

After a successful patch, rebuild with build.bat (or PyInstaller) and test the
remote's voice key twice.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import winreg
from pathlib import Path

import pefile

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "apps" / "windows" / "rc003" / "src" / "ovb_rc003" / "doubao_rpc.py"

PROLOGUE_ANCHOR = b"\x41\x54\x41\x55\x41\x56\x41\x57"
PROLOGUE_LOOKBACK = 0x18
SIG0_LEN = 20
SIG1_LEN = 25


def active_version_dir() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\DoubaoIme") as key:
            value, _ = winreg.QueryValueEx(key, "VersionDir")
    except OSError:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_section(pe: pefile.PE):
    for section in pe.sections:
        if section.Name.rstrip(b"\x00") == b".text":
            return section.VirtualAddress, section.get_data()
    raise SystemExit("no .text section")


def call_next_hook_iat(pe: pefile.PE) -> int:
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
        if entry.dll.decode(errors="ignore").lower() != "user32.dll":
            continue
        for imp in entry.imports:
            if imp.name and imp.name.decode(errors="ignore") == "CallNextHookEx":
                return imp.address - pe.OPTIONAL_HEADER.ImageBase
    raise SystemExit("user32!CallNextHookEx not imported")


def layout_for(directory: Path):
    pe = pefile.PE(str(directory / "ImeService.exe"), fast_load=False)
    iat = call_next_hook_iat(pe)
    base, code = text_section(pe)

    calls = []
    index = 0
    while True:
        index = code.find(b"\xff\x15", index)
        if index < 0 or index + 6 > len(code):
            break
        disp = int.from_bytes(code[index + 2:index + 6], "little", signed=True)
        if base + index + 6 + disp == iat:
            calls.append(index)          # index into .text
        index += 2
    if not calls:
        raise SystemExit("no call to CallNextHookEx found")

    results = []
    for offset in calls:
        anchor = code.rfind(PROLOGUE_ANCHOR, max(0, offset - 0x2000), offset)
        if anchor < 0:
            continue
        start = None
        for pos in range(anchor, max(0, anchor - PROLOGUE_LOOKBACK), -1):
            if code[pos - 1] == 0xCC and code[pos] != 0xCC:
                start = pos
                break
        if start is None:
            continue
        results.append((base + start, base + offset, base + offset + 6))
    if not results:
        raise SystemExit("could not anchor any CallNextHookEx call to a prologue")

    results.sort()
    return results, base, code


def pick(candidates):
    """The keyboard callback is the first CallNextHookEx caller in .text."""
    return candidates[0]


def version_token(directory: Path) -> str:
    name = directory.name
    if name.startswith("v"):
        name = name[1:]
    return "".join(part for part in name.split(".") if part)


def patch_source(text: str, token: str, layout, sig0: bytes, sig1: bytes,
                 ime_hash: str, rpc_hash: str, tsf_hash: str, wparam: int):
    const = f"_DOUBAO_{token}_HOOK_LAYOUT"
    if const in text:
        return text, f"already present: {const}"

    literal = f"{const} = ({layout[0]}, {layout[1]}, {layout[2]}, 0, 0)"

    # 1) constant, right after the last existing layout constant
    last = None
    for match in re.finditer(r"^_DOUBAO_\w+_HOOK_LAYOUT = \(.*\)$", text, re.M):
        last = match
    if last is None:
        raise SystemExit("could not find a layout constant to anchor on")
    text = text[:last.end()] + "\n" + literal + text[last.end():]

    # 2) forward-only signatures
    anchor = "_VERIFIED_FORWARD_ONLY_SIGNATURES = {"
    head = text.index(anchor) + len(anchor)
    tail = text.index("\n}", head)
    entry = (
        f"\n    {const}: (\n"
        f"        bytes.fromhex(\"{sig0.hex(' ').upper()}\"),\n"
        f"        bytes.fromhex(\"{sig1.hex(' ').upper()}\"),\n"
        f"    ),"
    )
    text = text[:tail] + entry + text[tail:]

    # 3) IME build table
    anchor = "_VERIFIED_IME_SERVICE_BUILDS = {"
    head = text.index(anchor) + len(anchor)
    tail = text.index("\n}", head)
    text = text[:tail] + f"\n    \"{ime_hash}\":\n        {const}," + text[tail:]

    # 4) voice-stop build table
    anchor = "_VERIFIED_VOICE_STOP_BUILDS = {"
    head = text.index(anchor) + len(anchor)
    tail = text.index("\n}", head)
    entry = (
        f"\n    \"{rpc_hash}\": (\n"
        f"        \"{ime_hash}\",\n"
        f"        \"{tsf_hash}\",\n"
        f"        {wparam},\n"
        f"    ),"
    )
    text = text[:tail] + entry + text[tail:]

    return text, f"added {const} = ({layout[0]}, {layout[1]}, {layout[2]}, 0, 0)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=None, help="Doubao version directory")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--target", default=str(TARGET))
    parser.add_argument("--json", default=None,
                        help="write a doubao_profiles.json instead of patching source")
    parser.add_argument("--wparam", type=int, default=1,
                        help="stop wParam (1 for current builds; try 0 if stop fails)")
    args = parser.parse_args()

    directory = Path(args.dir) if args.dir else active_version_dir()
    if directory is None or not directory.is_dir():
        raise SystemExit("Doubao version directory not found")

    candidates, base, code = layout_for(directory)
    layout = pick(candidates)
    token = version_token(directory)
    ime_hash = sha256(directory / "ImeService.exe")
    rpc_hash = sha256(directory / "doubaoime-rpc-new.dll")
    tsf_hash = sha256(directory / "tsf-oime-core.dll")

    def read(rva, n):
        return code[rva - base:rva - base + n]

    sig0 = read(layout[0], SIG0_LEN)
    sig1 = read(layout[1], SIG1_LEN)

    print(f"version dir : {directory}")
    print(f"constant    : _DOUBAO_{token}_HOOK_LAYOUT")
    print(f"layout      : ({layout[0]}, {layout[1]}, {layout[2]}, 0, 0)")
    print(f"ime sha256  : {ime_hash}")
    print(f"rpc sha256  : {rpc_hash}")
    print(f"tsf sha256  : {tsf_hash}")
    print(f"sig0        : {sig0.hex(' ').upper()}")
    print(f"sig1        : {sig1.hex(' ').upper()}")
    if len(candidates) > 1:
        print(f"note        : {len(candidates) - 1} other CallNextHookEx caller(s) ignored")

    target = Path(args.target)
    if args.json:
        out = Path(args.json)
        try:
            data = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
        except ValueError:
            data = {}
        data.setdefault("ime_builds", {})[ime_hash] = {
            "layout": [layout[0], layout[1], layout[2], 0, 0],
            "sig0": sig0.hex(" ").upper(),
            "sig1": sig1.hex(" ").upper(),
            "note": f"{directory.name} (added by adapt_doubao.py)",
        }
        data.setdefault("voice_stop_builds", {})[rpc_hash] = [ime_hash, tsf_hash, args.wparam]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote profile {out}")
        print("restart the app - no rebuild needed")
        return 0

    text = target.read_text(encoding="utf-8")
    patched, note = patch_source(text, token, layout, sig0, sig1,
                                 ime_hash, rpc_hash, tsf_hash, args.wparam)
    print(f"\n{note}")

    if not args.write:
        print("\n(dry run - rerun with --write to modify doubao_rpc.py)")
        return 0

    if patched == text:
        print("nothing to write")
        return 0
    target.write_text(patched, encoding="utf-8")
    print(f"\nwrote {target}")
    print("next: rebuild, then press the remote voice key twice to test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
