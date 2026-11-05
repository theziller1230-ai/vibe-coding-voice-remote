"""Stable product identity and Windows portable-layout naming.

The public presentation name may change without changing configuration,
single-instance, update, or privileged-helper identities.  Keep all visible
Windows filenames derived here so Python, PyInstaller, and PowerShell agree.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath
from typing import Any


# VCVR = Vibe Coding Voice Remote (Windows).  The Chinese consumer name of the
# upstream build is deliberately dropped: this fork ships a different default
# key layout and a different Doubao compatibility table.
DISPLAY_NAME = "VCVR"
WINDOWS_EDITION_NAME = ""
WINDOWS_PRODUCT_NAME = (
    DISPLAY_NAME if not WINDOWS_EDITION_NAME
    else f"{DISPLAY_NAME} {WINDOWS_EDITION_NAME}"
)
LEGACY_WINDOWS_EXECUTABLE_NAME = "RemoteMicRC003.exe"
# Executables named after the pre-rename product keep matching exactly: an
# existing install's autostart entry, HID-helper consumer markers and bundled
# runtime directory can only be migrated while the old name stays recognized.
PREVIOUS_WINDOWS_PRODUCT_NAME = "无线麦 win版"
WINDOWS_RUNTIME_DIRECTORY_NAME = "程序文件"
WINDOWS_DOCUMENTATION_DIRECTORY_NAME = "说明与许可"
WINDOWS_PORTABLE_README_NAME = "使用说明.txt"
HID_HELPER_EXECUTABLE_NAME = "RemoteMicRC003HidHelper.exe"
HID_HELPER_FILE_DESCRIPTION = f"{DISPLAY_NAME} privilege helper"
WINDOWS_INTERNAL_NAME = "RemoteMicRC003"

_VERSION_PATTERN = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<suffix>[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?"
)
_WINDOWS_EXECUTABLE_PATTERNS = tuple(
    re.compile(
        rf"{re.escape(product_name)} (?P<version>.+)\.exe",
        re.IGNORECASE,
    )
    for product_name in (WINDOWS_PRODUCT_NAME, PREVIOUS_WINDOWS_PRODUCT_NAME)
)
_WINDOWS_VERSION_COMPONENT_MAX = 65_535


def validate_version(version: str) -> str:
    """Return one supported VERSION value, rejecting path-like input."""

    if not isinstance(version, str):
        raise TypeError("version must be a string")
    normalized = version.strip()
    if normalized != version or not _VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(f"unsupported application version: {version!r}")
    if PurePath(normalized).name != normalized or any(
        character in normalized for character in ("/", "\\", "\0")
    ):
        raise ValueError(f"invalid application version: {version!r}")
    return normalized


def windows_presentation_label(version: str) -> str:
    return f"{WINDOWS_PRODUCT_NAME} {validate_version(version)}"


def windows_executable_name(version: str) -> str:
    return f"{windows_presentation_label(version)}.exe"


def windows_executable_stem(version: str) -> str:
    return Path(windows_executable_name(version)).stem


def windows_portable_folder_name(version: str) -> str:
    return windows_presentation_label(version)


def windows_fixed_file_version(version: str) -> tuple[int, int, int, int]:
    """Map the semantic version to the numeric Windows fixed-file tuple."""

    match = _VERSION_PATTERN.fullmatch(validate_version(version))
    assert match is not None
    values = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    if any(value > _WINDOWS_VERSION_COMPONENT_MAX for value in values):
        raise ValueError("Windows version component exceeds 65535")
    return (*values, 0)


def windows_version_is_prerelease(version: str) -> bool:
    match = _VERSION_PATTERN.fullmatch(validate_version(version))
    assert match is not None
    return bool(match.group("suffix"))


def recognized_windows_executable_layout(name: str) -> str | None:
    """Return ``legacy``/``current`` only for an exact known basename."""

    if not isinstance(name, str) or not name or Path(name).name != name:
        return None
    if name.casefold() == LEGACY_WINDOWS_EXECUTABLE_NAME.casefold():
        return "legacy"
    for pattern in _WINDOWS_EXECUTABLE_PATTERNS:
        match = pattern.fullmatch(name)
        if match is None:
            continue
        try:
            validate_version(match.group("version"))
        except (TypeError, ValueError):
            continue
        return "current"
    return None


def is_recognized_windows_executable_name(name: str) -> bool:
    return recognized_windows_executable_layout(name) is not None


def windows_runtime_relative_directory_for_executable(name: str) -> Path:
    layout = recognized_windows_executable_layout(name)
    if layout == "legacy":
        return Path("_internal")
    if layout == "current":
        return Path(WINDOWS_RUNTIME_DIRECTORY_NAME)
    raise ValueError(f"unrecognized Windows executable name: {name!r}")


def windows_main_version_metadata(version: str) -> dict[str, Any]:
    normalized = validate_version(version)
    return {
        "file_description": windows_presentation_label(normalized),
        "product_name": WINDOWS_PRODUCT_NAME,
        "file_version": normalized,
        "product_version": normalized,
        "original_filename": windows_executable_name(normalized),
        "internal_name": WINDOWS_INTERNAL_NAME,
        "fixed_file_version": windows_fixed_file_version(normalized),
        "prerelease": windows_version_is_prerelease(normalized),
    }


def windows_hid_helper_version_metadata(version: str) -> dict[str, Any]:
    normalized = validate_version(version)
    return {
        "file_description": HID_HELPER_FILE_DESCRIPTION,
        "product_name": WINDOWS_PRODUCT_NAME,
        "file_version": normalized,
        "product_version": normalized,
        "original_filename": HID_HELPER_EXECUTABLE_NAME,
        "internal_name": "RemoteMicRC003HidHelper",
        "fixed_file_version": windows_fixed_file_version(normalized),
        "prerelease": windows_version_is_prerelease(normalized),
    }
