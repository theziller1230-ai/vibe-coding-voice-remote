"""Presentation-layer data contracts (UI-REDESIGN.md §2).

These frozen dataclasses are the **only** data shapes allowed to cross the
boundary between the presentation layer (layer ②, ``presentation/``) and the
QML views (layer ①, ``qml/``).  Layer ① and layer ② may exchange nothing but
instances of the classes below plus plain ``str``/``int``/``bool`` scalars
and ``list``s of these instances.

Rules fixed by the architecture contract (docs/UI-REDESIGN.md):

* pure ``dataclass(frozen=True)`` — no Qt import, no business logic;
* field names are the QML-facing (camelCase) names from the doc tables;
* no function in the presentation layer returns a bare ``dict`` — every
  dict-shaped backend result is translated into one of these types first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

# Status wording tone for cards.
Tone = Literal["ok", "warn", "error", "idle"]

# State of a wizard step / diagnostic check row.
State = Literal["done", "current", "todo", "failed"]


@dataclass(frozen=True)
class StatusCard:
    """Home-page hero card / connection card / voice card (doc §2/§3)."""

    title: str
    subtitle: str
    tone: Tone
    detail: str
    actionLabel: str
    actionId: str


@dataclass(frozen=True)
class CheckRow:
    """One diagnostic row, phrased for end users (doc §2/§3)."""

    id: str
    title: str
    status: State
    detail: str
    fixLabel: str


@dataclass(frozen=True)
class ChoiceRow:
    """One selectable option (remote choice, voice program, …)."""

    id: str
    label: str
    detail: str
    enabled: bool
    selected: bool


@dataclass(frozen=True)
class ButtonRow:
    """One physical button with its per-gesture action display text and
    per-gesture note names (doc §2 + §3.5 D6: ``singleNote/doubleNote/longNote``).
    """

    id: str
    label: str
    single: str
    double: str
    longPress: str
    isMic: bool
    singleNote: str
    doubleNote: str
    longNote: str


@dataclass(frozen=True)
class Validation:
    """Result of an editor/validation flow (replaces legacy {ok,text,…})."""

    ok: bool
    message: str
    field: str


@dataclass(frozen=True)
class StepStatus:
    """One onboarding wizard step (slice C consumes this)."""

    id: str
    title: str
    state: State
    detail: str
    fixLabel: str


@dataclass(frozen=True)
class ToggleRow:
    """One boolean preference row (doc §3.5 D4)."""

    id: str
    label: str
    detail: str
    value: bool
    enabled: bool


# Closed enumerations (doc §3.5 D4).  These ids are the ONLY values the
# presentation layer accepts for ``MaintenanceViewModel.setPreference`` and
# ``MaintenanceViewModel.run`` - they are presentation-level vocabulary, not
# backend key names, and the contract tests assert the dispatch tables cover
# exactly these sets (no more, no less) so the id parameters cannot degrade
# into unbounded string dispatch.
PREFERENCE_IDS: Tuple[str, ...] = (
    "start_with_windows",
    "auto_start_bridge",
    "diagnostic_logging",
    "hide_to_tray_on_close",
)

MAINTENANCE_ITEM_IDS: Tuple[str, ...] = (
    "update",
    "helper",
    "diagnostics",
    "logs",
    "bluetooth",
    "guide",
)
