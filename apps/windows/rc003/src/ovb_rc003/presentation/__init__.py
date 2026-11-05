"""Presentation layer (②) - the only bridge between the pure QML views (①)
and the unchanged backend (③).

Modules:

* ``contracts``   - the frozen dataclass shapes allowed across the boundary
  (pure Python - importing this package never requires PySide6, matching the
  backend's optional-GUI convention);
* ``transport``   - Qt marshalling of those shapes (see its docstring for the
  PySide6 constraints that shaped it); requires PySide6.
* ``viewmodels``  - AppViewModel / DeviceViewModel / VoiceViewModel /
  MappingViewModel / MaintenanceViewModel (plus the OnboardingViewModel seam
  documented in ``registry``); requires PySide6.
* ``registry``    - QML singleton registration under ``OvbRc003Presentation 1.0``
  and the integration hook point; requires PySide6.

Import the Qt-side submodules directly (``.viewmodels`` / ``.registry`` /
``.transport``) so that ``.contracts`` stays importable in Qt-free contexts.
Nothing in this package modifies or reaches into backend internals beyond the
documented seams; see docs/UI-REDESIGN.md.
"""

from .contracts import (
    MAINTENANCE_ITEM_IDS,
    PREFERENCE_IDS,
    ButtonRow,
    CheckRow,
    ChoiceRow,
    State,
    StepStatus,
    StatusCard,
    ToggleRow,
    Tone,
    Validation,
)

__all__ = [
    "MAINTENANCE_ITEM_IDS",
    "PREFERENCE_IDS",
    "ButtonRow",
    "CheckRow",
    "ChoiceRow",
    "State",
    "StepStatus",
    "StatusCard",
    "ToggleRow",
    "Tone",
    "Validation",
]
