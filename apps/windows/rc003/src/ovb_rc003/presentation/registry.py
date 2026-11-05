"""QML singleton registration for the presentation layer.

Registers the presentation view-models as QML singletons under the URI
``OvbRc003Presentation 1.0`` so ``qml/`` only ever imports this module
(UI-REDESIGN.md §1).  ``qmlRegisterSingletonInstance`` is process-global and
engine-free - exactly like the backend's own three singletons - so this module
needs no ``QQmlEngine`` reference.

Integration hook point (report - the backend file must not be edited from
this slice):

    ``qt_settings_app.run_settings_window`` (src/ovb_rc003/qt_settings_app.py),
    right after the three existing ``qmlRegisterSingletonInstance`` calls for
    ``OvbRc003Settings`` (which end at line 10249) and before
    ``engine = QQmlApplicationEngine()`` (line 10251) - or anywhere before
    ``engine.load(main_qml)`` at line 10256 - insert::

        from .presentation import registry
        registry.register(
            controller=controller,
            mapping_model=model,
            diagnostics=diagnostics_controller,
        )

    The three names above are the locals ``run_settings_window`` already
    constructs (``model = ButtonMappingModel()``, ``controller =
    SettingsController(model, ...)``, ``diagnostics_controller =
    DiagnosticsController(controller, ...)``).  There is no other extension
    seam in the current backend; without this one-line insertion the new QML
    module cannot resolve.

Slice C (onboarding) seam: ``presentation.onboarding.OnboardingViewModel`` is
registered automatically by :func:`register` when that module is present
(lazy import; the class is constructed with its zero-arg default environment,
per slice C's constructor contract), as the QML type ``OnboardingViewModel``
under the same URI.  Callers may still pass an explicit instance via
``onboarding=`` (tests) or call :func:`register_onboarding` directly; a
genuinely absent ``presentation.onboarding`` module simply means the wizard
singleton is not registered.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional

from PySide6.QtCore import QObject
from PySide6.QtQml import qmlRegisterSingletonInstance

from .viewmodels import (
    AppViewModel,
    DeviceViewModel,
    MaintenanceViewModel,
    MappingViewModel,
    VoiceViewModel,
)

QML_URI = "OvbRc003Presentation"
QML_VERSION = (1, 0)

# QML type names as registered; keep in sync with docs/UI-REDESIGN.md §3/§3.5.
SINGLETON_TYPE_NAMES = (
    "AppViewModel",
    "DeviceViewModel",
    "VoiceViewModel",
    "MappingViewModel",
    "MaintenanceViewModel",
)
ONBOARDING_TYPE_NAME = "OnboardingViewModel"


class ViewmodelSet(NamedTuple):
    """The constructed view-models, keyed by their QML type names."""

    AppViewModel: AppViewModel
    DeviceViewModel: DeviceViewModel
    VoiceViewModel: VoiceViewModel
    MappingViewModel: MappingViewModel
    MaintenanceViewModel: MaintenanceViewModel

    def pairs(self) -> list:
        """(qml type name, instance) pairs for registration."""

        return [
            (name, getattr(self, name))
            for name in SINGLETON_TYPE_NAMES
        ]


def build_viewmodels(
    *,
    controller: Any,
    mapping_model: Any,
    diagnostics: Any,
    dictation_probe: Any = None,
) -> ViewmodelSet:
    """Construct the five view-models around the existing backend objects.

    ``dictation_probe`` is the VoiceViewModel observation seam; ``None`` uses
    no probe (readiness-only verdicts), production wires
    ``viewmodels.NativeDictationProbe()`` via :func:`register`.
    """

    return ViewmodelSet(
        AppViewModel=AppViewModel(controller),
        DeviceViewModel=DeviceViewModel(controller, diagnostics),
        VoiceViewModel=VoiceViewModel(
            controller, diagnostics, dictation_probe=dictation_probe
        ),
        MappingViewModel=MappingViewModel(mapping_model, controller),
        MaintenanceViewModel=MaintenanceViewModel(controller, diagnostics),
    )


def register_singletons(pairs) -> None:
    """Register (type name, instance) pairs under the presentation URI."""

    for name, instance in pairs:
        qmlRegisterSingletonInstance(
            type(instance),
            QML_URI,
            QML_VERSION[0],
            QML_VERSION[1],
            name,
            instance,
        )


def register_onboarding(viewmodel: QObject) -> None:
    """Slice C seam: register the OnboardingViewModel singleton."""

    register_singletons([(ONBOARDING_TYPE_NAME, viewmodel)])


def _build_onboarding_viewmodel() -> Optional[QObject]:
    """Construct slice C's OnboardingViewModel when its module is present.

    ``presentation.onboarding`` is owned by slice C and uses lazy backend
    imports, so importing/constructing it here is safe; a genuinely absent
    module (partial deployment) means the wizard singleton is skipped.
    Real construction errors propagate - they must not be swallowed.
    """

    try:
        from . import onboarding
    except ImportError:
        return None
    factory = getattr(onboarding, "OnboardingViewModel", None)
    if factory is None:
        return None
    return factory()


def register(
    *,
    controller: Any,
    mapping_model: Any,
    diagnostics: Any,
    onboarding: Optional[QObject] = None,
    dictation_probe: Any = None,
) -> ViewmodelSet:
    """One-call integration entry point (see the hook-point note above).

    Builds the view-models, registers them as QML singletons under
    ``OvbRc003Presentation 1.0`` and - when slice C passes ``onboarding=`` -
    registers ``OnboardingViewModel`` alongside them.  Returns the set so the
    caller can keep references for the application lifetime.
    """

    if dictation_probe is None:
        from .viewmodels import NativeDictationProbe

        dictation_probe = NativeDictationProbe(
            runtime_state=lambda: getattr(controller, "voiceRuntimeState", "")
        )
    viewmodels = build_viewmodels(
        controller=controller,
        mapping_model=mapping_model,
        diagnostics=diagnostics,
        dictation_probe=dictation_probe,
    )
    register_singletons(viewmodels.pairs())
    if onboarding is None:
        onboarding = _build_onboarding_viewmodel()
    if onboarding is not None:
        register_onboarding(onboarding)
    return viewmodels
