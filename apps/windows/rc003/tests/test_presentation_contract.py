"""Contract tests for the presentation layer (docs/UI-REDESIGN.md §5).

§5 items 1-4 live here:

1. every view-model's property/slot surface matches the doc tables
   (reflection comparison, including the §3.5 D4/D5/D6 extensions);
2. every QML file may only ``import OvbRc003Presentation 1.0`` -
   ``OvbRc003Settings`` and any other app module is banned;
3. QML sources contain no backend vocabulary (§1 hard rule);
4. layer ② functions never return bare dicts (static return-annotation check).

Item 5 (layer ③ files unchanged) is the git-diff assertion the main agent
runs.  D4 additionally requires the closed enumerations to be enforced as
exactly ``PREFERENCE_IDS`` / ``MAINTENANCE_ITEM_IDS`` - the dispatch tests
below assert no more and no less.
"""

import ast
import inspect
import re
import unittest
from unittest import mock
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal

from ovb_rc003.presentation import contracts
from ovb_rc003.presentation.viewmodels import (
    AppViewModel,
    DeviceViewModel,
    MaintenanceViewModel,
    MappingViewModel,
    VoiceViewModel,
)
from ovb_rc003.presentation.transport import contract_qml_map, row_view

_ROOT = Path(__file__).resolve().parents[1]
_QML_DIR = _ROOT / "src" / "ovb_rc003" / "qml"
_PRESENTATION_DIR = _ROOT / "src" / "ovb_rc003" / "presentation"

_CLASSES = {
    "AppViewModel": AppViewModel,
    "DeviceViewModel": DeviceViewModel,
    "VoiceViewModel": VoiceViewModel,
    "MappingViewModel": MappingViewModel,
    "MaintenanceViewModel": MaintenanceViewModel,
}

# Doc §3 tables + §3.5 D4/D5/D6 additions + the typed-slot extensions noted in
# the delivery report (D1: "cards needing actions get typed slots").
EXPECTED_PROPERTIES = {
    "AppViewModel": {
        "windowTitle": "str",
        "statusCard": "StatusCard",
        "currentPage": "int",
        "versionLabel": "str",
        "bridgeStateLabel": "str",
        "startHidden": "bool",
    },
    "DeviceViewModel": {
        "connectionCard": "StatusCard",
        "checks": "list[CheckRow]",
        "remoteChoices": "list[ChoiceRow]",
        "batteryLabel": "str",
    },
    "VoiceViewModel": {
        "voiceCard": "StatusCard",
        "voicePrograms": "list[ChoiceRow]",
        "hotkeyLabel": "str",
        "recordingMode": "str",
        "audioRouteLabel": "str",
        "lastValidation": "Validation",
        "outputEndpoints": "list[ChoiceRow]",
        "recordingLimitSeconds": "int",
        "customProgramPath": "str",
        "autoLaunch": "bool",
        "launchElevated": "bool",
    },
    "MappingViewModel": {
        "buttons": "list[ButtonRow]",
        "presets": "list[ChoiceRow]",
        "keyDetectionText": "str",
        "mappingAutoSaveRetryAvailable": "bool",
    },
    "MaintenanceViewModel": {
        "items": "list[CheckRow]",
        "updateStatus": "StatusCard",
        "preferences": "list[ToggleRow]",
    },
}

EXPECTED_SLOTS = {
    "AppViewModel": {
        "pollWindowRestoreRequest": (),
        "onWindowReady": (),
        "startupSettled": (),
        "tick": (),
    },
    "DeviceViewModel": {
        "refresh": (),
        "fixCheck": ("checkId",),
        "useRemote": ("id",),
        "bridgeAction": (),
    },
    "VoiceViewModel": {
        "setVoiceProgram": ("id",),
        "setRecordingMode": ("mode",),
        "startHotkeyCapture": (),
        "stopHotkeyCapture": (),
        "testAudio": (),
        "testDictation": (),
        "installVirtualCable": (),
        "selectOutput": ("id",),
        "setRecordingLimit": ("v",),
        "pickCustomProgramPath": ("fileUrl",),
        "setAutoLaunch": ("v",),
        "setLaunchElevated": ("v",),
        "launchVoiceProgram": (),
        "openVoiceProgramSettings": (),
    },
    "MappingViewModel": {
        "setAction": ("buttonId", "gesture", "actionText"),
        "setNote": ("buttonId", "gesture", "note"),
        "programPath": ("buttonId", "gesture"),
        "textContent": ("buttonId", "gesture"),
        "pickProgramPath": ("buttonId", "gesture", "fileUrl"),
        "setTextContent": ("buttonId", "gesture", "content"),
        "restoreDefaults": (),
        "captureShortcut": (),
        "stopShortcutCapture": (),
        "startKeyDetection": (),
        "stopKeyDetection": (),
        "retryMappingAutoSave": (),
        "applyPreset": ("id",),
        "savePreset": ("name",),
        "renamePreset": ("id", "name"),
        "deletePreset": ("id",),
        "exportPreset": ("id", "fileUrl"),
        "importPreset": ("fileUrl",),
        "actionOptions": ("buttonId", "gesture"),
    },
    "MaintenanceViewModel": {
        "run": ("item",),
        "confirmExitSave": (),
        "setPreference": ("id", "value"),
        "saveLogs": ("fileUrl",),
        "openLogs": (),
        "openMicrophonePrivacySettings": (),
        "openSpeechSettings": (),
        "openSoundSettings": (),
        "openAppsSettings": (),
        "removeHelper": (),
        "cancelUpdateDownload": (),
        "openUpdateRelease": (),
    },
}

_EXPECTED_SLOT_RETURNS = {
    "onWindowReady": "bool",
    "startupSettled": "bool",
    "bridgeAction": "Validation",
    "testDictation": "Validation",
    "setAction": "Validation",
    "pickProgramPath": "Validation",
    "setTextContent": "Validation",
    "applyPreset": "Validation",
    "savePreset": "Validation",
    "renamePreset": "Validation",
    "deletePreset": "Validation",
    "exportPreset": "Validation",
    "importPreset": "Validation",
    "confirmExitSave": "Validation",
    "setPreference": "Validation",
    "saveLogs": "Validation",
    "openLogs": "Validation",
    "startKeyDetection": "Validation",
    "stopKeyDetection": "Validation",
    "onWindowReady": "bool",
    "startupSettled": "bool",
    "retryMappingAutoSave": "Validation",
    "pickCustomProgramPath": "Validation",
    "setAutoLaunch": "Validation",
    "setLaunchElevated": "Validation",
    "launchVoiceProgram": "Validation",
    "openVoiceProgramSettings": "Validation",
    "openMicrophonePrivacySettings": "Validation",
    "openSpeechSettings": "Validation",
    "openSoundSettings": "Validation",
    "openAppsSettings": "Validation",
    "removeHelper": "Validation",
    "cancelUpdateDownload": "Validation",
    "openUpdateRelease": "Validation",
    "programPath": "str",
    "textContent": "str",
    "actionOptions": "List[QObject]",
}


# ---------------------------------------------------------------------------
# §5 item 1 - reflection comparison against the doc tables.
# ---------------------------------------------------------------------------


class SurfaceReflectionTests(unittest.TestCase):
    def _property_names(self, cls):
        return {
            name
            for name, attr in vars(cls).items()
            if isinstance(attr, Property)
        }

    def test_property_surface_matches_contract_exactly(self):
        for name, cls in _CLASSES.items():
            with self.subTest(viewmodel=name):
                self.assertEqual(
                    self._property_names(cls),
                    set(EXPECTED_PROPERTIES[name]),
                    f"{name} property surface diverged from the contract",
                )

    def test_every_property_has_a_notify_signal(self):
        for name, cls in _CLASSES.items():
            for prop_name in EXPECTED_PROPERTIES[name]:
                with self.subTest(viewmodel=name, prop=prop_name):
                    notify = vars(cls).get(prop_name + "Changed")
                    self.assertIsInstance(
                        notify, Signal, f"{name}.{prop_name} lacks {prop_name}Changed"
                    )

    def test_current_page_is_writable_view_state(self):
        # D2: pure writable view state.
        self.assertIsNotNone(vars(AppViewModel)["currentPage"].fset)

    def test_other_properties_are_read_only(self):
        for name, cls in _CLASSES.items():
            for prop_name in EXPECTED_PROPERTIES[name]:
                if name == "AppViewModel" and prop_name == "currentPage":
                    continue
                with self.subTest(viewmodel=name, prop=prop_name):
                    self.assertIsNone(vars(cls)[prop_name].fset)

    def test_slot_surface_matches_contract_exactly(self):
        for name, cls in _CLASSES.items():
            with self.subTest(viewmodel=name):
                slots = {
                    member: attr
                    for member, attr in vars(cls).items()
                    if inspect.isfunction(attr) and not member.startswith("_")
                }
                self.assertEqual(
                    set(slots), set(EXPECTED_SLOTS[name]),
                    f"{name} slot surface diverged from the contract",
                )
                for slot_name, params in EXPECTED_SLOTS[name].items():
                    signature = inspect.signature(slots[slot_name])
                    self.assertEqual(
                        tuple(signature.parameters)[1:], params,
                        f"{name}.{slot_name} parameters diverged",
                    )

    def test_slot_return_annotations_match_contract(self):
        for name, cls in _CLASSES.items():
            for slot_name in EXPECTED_SLOTS[name]:
                with self.subTest(viewmodel=name, slot=slot_name):
                    method = vars(cls)[slot_name]
                    annotation = inspect.signature(method).return_annotation
                    text = annotation if isinstance(annotation, str) else getattr(
                        annotation, "__name__", str(annotation)
                    )
                    self.assertEqual(
                        text,
                        _EXPECTED_SLOT_RETURNS.get(slot_name, "None"),
                        f"{name}.{slot_name} return annotation diverged",
                    )

    def test_mapping_viewmodel_signal_surface(self):
        signal = vars(MappingViewModel)["shortcutCaptured"]
        self.assertIsInstance(signal, Signal)

    def test_lifecycle_signal_surface(self):
        self.assertIsInstance(vars(AppViewModel)["windowRestoreRequested"], Signal)


# ---------------------------------------------------------------------------
# §5 item 2 - QML may only import OvbRc003Presentation 1.0.
# ---------------------------------------------------------------------------


class QmlImportTests(unittest.TestCase):
    _IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)(?:\s+(\d+)\.(\d+))?", re.M)

    def _qml_files(self):
        return sorted(_QML_DIR.glob("*.qml"))

    def test_qml_tree_exists(self):
        self.assertTrue(self._qml_files(), f"no QML files under {_QML_DIR}")

    def test_qml_never_imports_the_backend_module(self):
        for path in self._qml_files():
            with self.subTest(qml=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(
                    "OvbRc003Settings", text,
                    f"{path.name} still imports the legacy backend module",
                )

    def test_qml_app_imports_are_exactly_the_presentation_uri(self):
        for path in self._qml_files():
            text = path.read_text(encoding="utf-8")
            for module, major, minor in self._IMPORT_RE.findall(text):
                with self.subTest(qml=path.name, module=module):
                    if module.startswith("Qt"):
                        continue
                    self.assertEqual(
                        module, "OvbRc003Presentation",
                        f"{path.name} imports non-presentation module {module}",
                    )
                    self.assertEqual(
                        (major, minor), ("1", "0"),
                        f"{path.name} pins wrong presentation version",
                    )


# ---------------------------------------------------------------------------
# §5 item 3 - no backend vocabulary in QML sources.
# ---------------------------------------------------------------------------


class QmlVocabularyTests(unittest.TestCase):
    _BLACKLIST = (
        # doc §1 named offenders
        "ActionKind",
        "voice_hotkeys_by_provider",
        "doubao_ime",
        "wetype_hotkey",
        "state == 1",
        # backend type / module names
        "SettingsController",
        "ButtonMappingModel",
        "DiagnosticsController",
        "VoiceTriggerMode",
        "ButtonTrigger",
        "key_mapping",
        "settings_ui",
        "qt_settings_app",
        # backend id vocabulary
        "checkId",
        "resultCode",
        "single_click",
        "double_click",
        "long_press",
        "voice_hold",
        "voice_trigger_mode",
        "voice_hotkey",
        "output_endpoint_name",
        "output_endpoint_host_api",
        "selected_device_profile",
        "secondary_bindings",
        "display_notes",
        "combo_bindings",
        "key_bindings",
        "remote_recording_mode",
        "remote_recording_limit",
        "close_behavior",
        "launch_at_login",
        "launch_bridge_on_app_start",
        "diagnostic_trace_enabled",
        "activePageIndex",
    )

    def test_qml_sources_carry_no_backend_vocabulary(self):
        for path in sorted(_QML_DIR.glob("*.qml")):
            text = path.read_text(encoding="utf-8")
            for token in self._BLACKLIST:
                with self.subTest(qml=path.name, token=token):
                    self.assertNotIn(
                        token, text,
                        f"{path.name} leaks backend vocabulary {token!r}",
                    )


# ---------------------------------------------------------------------------
# §5 item 4 - layer ② never returns a bare dict.
# ---------------------------------------------------------------------------


class NoBareDictTests(unittest.TestCase):
    _DICT_ANNOTATION_RE = re.compile(r"\b(dict|Dict|Mapping|MutableMapping)\b")

    def _python_files(self):
        return sorted(_PRESENTATION_DIR.glob("*.py"))

    def test_return_annotations_never_declare_dicts(self):
        for path in self._python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                with self.subTest(module=path.name, function=node.name):
                    self.assertIsNotNone(
                        node.returns,
                        f"{path.name}:{node.name} lacks a return annotation",
                    )
                    annotation = ast.unparse(node.returns)
                    self.assertIsNone(
                        self._DICT_ANNOTATION_RE.search(annotation),
                        f"{path.name}:{node.name} returns {annotation} (bare dict)",
                    )


# ---------------------------------------------------------------------------
# D4 - closed enumerations: exactly PREFERENCE_IDS / MAINTENANCE_ITEM_IDS.
# ---------------------------------------------------------------------------


class ClosedEnumerationTests(unittest.TestCase):
    def test_enumerations_match_the_contract(self):
        self.assertEqual(
            contracts.PREFERENCE_IDS,
            ("start_with_windows", "auto_start_bridge", "diagnostic_logging", "hide_to_tray_on_close"),
        )
        self.assertEqual(
            contracts.MAINTENANCE_ITEM_IDS,
            ("update", "helper", "diagnostics", "logs", "bluetooth", "guide"),
        )


class QmlBindingSurfaceTests(unittest.TestCase):
    """Every view-model member a QML file names must actually exist.

    A binding to a missing member does not fail loudly - it aborts the whole
    JavaScript block containing it. ``AppViewModel.startHidden`` silently
    killed ``Component.onCompleted`` and with it the launch-time bridge start,
    which is why this guard exists.
    """

    _MEMBER = re.compile(
        r"\b(AppViewModel|DeviceViewModel|VoiceViewModel|MappingViewModel"
        r"|MaintenanceViewModel|OnboardingViewModel)\.([A-Za-z_][A-Za-z0-9_]*)"
    )

    def _class_for(self, vm_name):
        if vm_name in _CLASSES:
            return _CLASSES[vm_name]
        from ovb_rc003.presentation import onboarding as _onboarding
        return getattr(_onboarding, vm_name)

    def _qml_references(self):
        for path in sorted(_QML_DIR.glob("*.qml")):
            text = path.read_text(encoding="utf-8")
            for match in self._MEMBER.finditer(text):
                yield path.name, match.group(1), match.group(2)

    def test_every_viewmodel_member_used_by_qml_exists(self):
        missing, seen = [], set()
        for filename, vm_name, member in self._qml_references():
            seen.add((vm_name, member))
            if not hasattr(self._class_for(vm_name), member):
                missing.append(f"{filename}: {vm_name}.{member}")
        self.assertTrue(seen, "expected QML to reference the presentation layer")
        self.assertEqual(
            missing, [],
            "QML binds to presentation members that do not exist; the binding "
            "aborts its enclosing handler",
        )


class NotifyLivenessTests(unittest.TestCase):
    """A view-model must re-notify when its source actually changes.

    Two silent-staleness defects motivated this: ``VoiceViewModel`` listened
    for a signal nobody emits, and ``MappingViewModel`` ignored the Qt model
    signals that fire when the device profile rebuilds the rows.
    """

    def _fake_source(self, signals):
        """A QObject that really owns the named signals.

        A ``mock.Mock`` cannot stand in for Qt signals: ``emit()`` on a mock
        calls no connected slot, so the assertion would pass for the wrong
        reason (or fail for one).
        """
        attrs = {name: Signal() for name in signals}
        cls = type("FakeSource", (QObject,), attrs)
        source = cls()
        for name in signals:
            setattr(source, name + "_seen", [])
        return source

    def test_voice_viewmodel_follows_remote_selection_changes(self):
        source = self._fake_source((
            "remoteSelectionChanged", "remoteRecordingModeChanged",
        ))
        vm = VoiceViewModel(source, mock.Mock())
        fired = []
        vm.voiceCardChanged.connect(lambda: fired.append(1))
        source.remoteSelectionChanged.emit()
        self.assertTrue(fired, "device/mode changes must re-notify the view")

    def test_mapping_buttons_follow_model_rebuilds(self):
        model = self._fake_source((
            "mappingEdited", "actionEdited", "modelReset", "layoutChanged",
            "dataChanged", "rowsInserted", "rowsRemoved",
        ))
        vm = MappingViewModel(model, mock.Mock())
        fired = []
        vm.buttonsChanged.connect(lambda: fired.append(1))
        model.modelReset.emit()
        self.assertTrue(fired, "set_profile/reset rebuilds rows through modelReset")
        fired.clear()
        model.layoutChanged.emit()
        self.assertTrue(fired, "layoutChanged must also refresh the cards")

    def test_notify_helper_accepts_payload_bearers(self):
        model = self._fake_source((
            "mappingEdited", "actionEdited", "modelReset", "layoutChanged",
            "dataChanged", "rowsInserted", "rowsRemoved",
        ))
        vm = MappingViewModel(model, mock.Mock())
        fired = []
        vm.buttonsChanged.connect(lambda: fired.append(1))
        vm._emit_changed(object(), object(), [1, 2, 3])
        self.assertEqual(fired, [1])


class VoiceProgramIndexSpaceTests(unittest.TestCase):
    """Row ids are SELECTABLE-order; the controller speaks PROVIDER-order.

    Dispatching the row index directly turned the last selectable row
    (Chatterfly) into the legacy ``custom`` slot, which the setter rejects -
    picking Chatterfly was a silent no-op and the marked row was wrong too.
    """

    def _vm(self, provider_id):
        from ovb_rc003 import voice_program_manager as _vpm

        controller = FakeController()
        controller.voiceProgramOptions = list(_vpm.provider_options())
        controller.selectedVoiceProgramIndex = _vpm.provider_index(provider_id)
        return VoiceViewModel(controller, FakeDiagnostics()), controller, _vpm

    def test_chatterfly_selects_the_chatterfly_provider(self):
        vm, controller, _vpm = self._vm("none")
        vm.setVoiceProgram("4")  # the Chatterfly row
        self.assertEqual(
            controller.selectedVoiceProgramIndex,
            _vpm.provider_index(_vpm.VOICE_PROGRAM_CHATTERFLY),
            "row 4 must reach Chatterfly, not the legacy custom slot",
        )

    def test_marked_row_matches_the_current_provider(self):
        vm, controller, _vpm = self._vm("chatterfly")
        marked = [row.contract.id for row in vm.voicePrograms if row.contract.selected]
        self.assertEqual(marked, ["4"], "Chatterfly must be the marked row")

    def test_no_row_is_marked_for_a_legacy_custom_program(self):
        vm, controller, _vpm = self._vm("custom")
        marked = [row.contract.id for row in vm.voicePrograms if row.contract.selected]
        self.assertEqual(marked, [], "custom is not one of the selectable rows")

    def test_selectable_order_matches_the_menu_order(self):
        vm, controller, _vpm = self._vm("sogou")
        marked = [row.contract.id for row in vm.voicePrograms if row.contract.selected]
        self.assertEqual(marked, ["1"], "sogou is the second selectable row")


class OnboardingSurfaceTests(unittest.TestCase):
    """Doc §3 ``OnboardingViewModel`` surface - enforced whenever slice C's
    module is importable (the class itself is slice C's; this gate keeps it
    contract-conformant, per §5 item 1 "every view-model").
    """

    def _onboarding_class(self):
        try:
            from ovb_rc003.presentation import onboarding
        except Exception as exc:  # pragma: no cover - depends on slice C
            self.skipTest(f"slice C module not importable: {exc}")
        cls = getattr(onboarding, "OnboardingViewModel", None)
        if cls is None:
            self.skipTest("OnboardingViewModel not defined yet")
        return cls

    def test_surface_matches_contract(self):
        cls = self._onboarding_class()
        properties = {
            name for name, attr in vars(cls).items() if isinstance(attr, Property)
        }
        self.assertEqual(properties, {"steps", "currentStep", "canContinue"})
        slots = {
            name: attr
            for name, attr in vars(cls).items()
            if inspect.isfunction(attr) and not name.startswith("_")
        }
        self.assertEqual(set(slots), {"next", "back", "repair", "verifyCurrent"})
        self.assertEqual(tuple(inspect.signature(slots["repair"]).parameters)[1:], ("stepId",))
        for name in ("next", "back", "repair", "verifyCurrent"):
            annotation = inspect.signature(slots[name]).return_annotation
            text = annotation if isinstance(annotation, str) else getattr(
                annotation, "__name__", str(annotation)
            )
            self.assertEqual(text, "None", name)
        for prop_name in ("steps", "currentStep", "canContinue"):
            self.assertIsInstance(vars(cls).get(prop_name + "Changed"), Signal)


# ---------------------------------------------------------------------------
# Behaviour proofs over injected fakes (no Qt event loop, no Windows).
# ---------------------------------------------------------------------------


class FakeSignal:
    def __init__(self):
        self._subscribers = []

    def connect(self, callback):
        self._subscribers.append(callback)

    def emit(self, *args):
        for callback in list(self._subscribers):
            callback(*args)


_SIGNAL_NAMES = (
    "bridgeRunningChanged", "bridgeConnectedChanged", "bridgeConnectionStateChanged",
    "bridgeLaunchPhaseChanged", "bridgeRestartRecommendedChanged",
    "bridgeReconnectAvailableChanged", "bridgeReconnectBusyChanged",
    "selectedDeviceChanged",
    "remoteSelectionChanged", "remoteBatteryChanged", "launchStatusTextChanged",
    "statusMessageChanged", "trayStateChanged", "voiceRuntimeStatusChanged",
    "voiceMappingReadyChanged", "voiceHotkeySaveStateChanged",
    "holdVoiceHotkeyTextChanged", "selectedVoiceProgramIndexChanged",
    "voiceProgramOptionsChanged", "voiceProgramStatusTextChanged",
    "endpointOptionsChanged", "selectedEndpointIndexChanged",
    "recommendedEndpointIndexChanged", "voiceProgramCustomPathChanged",
    "voiceProgramLaunchOnBridgeStartChanged", "voiceProgramLaunchElevatedChanged",
    "keyDetectionTextChanged", "mappingAutoSaveRetryAvailableChanged",
    "hotkeyCaptured", "hotkeyCaptureError", "windowRestoreRequested",
    "mappingPresetsChanged", "applicationUpdateChanged", "logExportBusyChanged",
    "hidHelperStateChanged", "hidHelperRepairBusyChanged", "desktopBehaviorChanged",
    "settingsDirtyChanged", "mappingDirtyChanged",
)


class FakeController:
    def __init__(self):
        self.applicationPresentationLabel = "RemoteMic RC003"
        self.applicationVersion = "1.0.104"
        self.bridgeRunning = True
        self.bridgeConnected = False
        self.bridgeLaunchBusy = False
        self.bridgeReconnectAvailable = True
        self.launchStatusText = "服务已启动（PID 1）；正在连接小米遥控器2 Pro"
        self.statusMessage = ""
        self.remoteSelectionMessage = ""
        self.remoteBatteryLevel = 87
        self.activeRemoteLabel = "小米遥控器2 Pro"
        self.remoteDisplayName = "小米遥控器2 Pro"
        self.voiceMappingReady = True
        self.voiceHotkeySaveState = "saved"
        self.voiceProgramStatusText = ""
        self.holdVoiceHotkeyText = "ralt"
        self.voiceProgramOptions = ["系统托管", "搜狗输入法", "豆包输入法"]
        self._selected_voice_program_index = 1
        self.endpointOptions = ["CABLE Output — WASAPI", "扬声器 (Realtek)"]
        self.selectedEndpointIndex = 0
        self.recommendedEndpointIndex = 0
        self.remoteRecordingModeIndex = 0
        self.remoteRecordingLimitIndex = 2
        self.remoteDeviceChoices = [
            {"key": "x1", "profile": "xiaomi-rc003", "label": "小米遥控器2 Pro",
             "canUse": True, "isActive": True},
            {"key": "x2", "profile": "xiaomi-rc003", "label": "备用遥控器",
             "canUse": False, "isActive": False},
        ]
        self.applicationUpdateMessage = "已是最新版本"
        self.applicationUpdateLatestVersion = "1.0.104"
        self.applicationUpdateBusy = False
        self.applicationUpdateCanDownload = False
        self.applicationUpdateDownloadedPath = ""
        self.logExportBusy = False
        self.hidHelperRepairBusy = False
        self.hidHelperIssueVisible = False
        self.hidHelperSetupRequired = False
        self.hidHelperIssueText = ""
        self.configurationReadOnly = False
        self.configurationError = ""
        self.mappingPresets = []
        self.keyDetectionText = ""
        self.mappingAutoSaveRetryAvailable = False
        self.voiceProgramCustomPath = ""
        self.voiceProgramLaunchOnBridgeStart = False
        self.voiceProgramLaunchElevated = False
        self.launchAtLogin = True
        self.launchBridgeOnAppStart = False
        self.diagnosticTraceEnabled = False
        self.closeBehavior = "hide_to_tray"
        self.startHidden = False
        self.buttonValidationMessage = ""
        self.preset_refresh_ok = True
        self.calls = []
        for name in _SIGNAL_NAMES:
            setattr(self, name, FakeSignal())

    @property
    def selectedVoiceProgramIndex(self):
        return self._selected_voice_program_index

    @selectedVoiceProgramIndex.setter
    def selectedVoiceProgramIndex(self, value):
        self._selected_voice_program_index = value
        self.calls.append(("selectedVoiceProgramIndex", value))

    def _record(self, *args):
        self.calls.append(args)

    def formatHotkeyText(self, text):
        return {"ralt": "右 Alt"}.get(text, text)

    def buttonActionValidationMessage(self, button_id, trigger, text, text_content=None, program_path=None):
        self._record("validate", button_id, trigger, text, text_content, program_path)
        return self.buttonValidationMessage

    def programPathFromFileUrl(self, fileUrl):
        return fileUrl.removeprefix("file:///").replace("/", "\\") if fileUrl else ""

    def mappingPresetAction(self, operation, identity, text):
        self._record("preset", operation, identity, text)
        if operation == "refresh" and not self.preset_refresh_ok:
            return {"ok": False, "id": identity, "message": "正在处理设置或输入，请完成后重试。"}
        return {"ok": True, "id": identity or "p1", "message": f"{operation} ok"}

    def primaryActionOptionsFor(self, button_id):
        return ["Escape", "输入文字", "打开程序"]

    def secondaryActionOptionsFor(self, button_id):
        return ["禁用", "Escape"]

    def longPressActionOptionsFor(self, button_id):
        return ["禁用", "鼠标左键长按"]

    def actionOptionGroupTitle(self, option):
        return {"Escape": "按键操作", "输入文字": "文字输入", "打开程序": "启动应用",
                "禁用": "其他", "鼠标左键长按": "鼠标长按"}.get(option, "")

    def canAutoSaveMappingBeforeExit(self):
        self._record("canAutoSaveMappingBeforeExit")
        return self._can_auto_save

    def logExportDefaultFile(self):
        return "file:///C:/Users/u/Desktop/app-logs.zip"

    def __getattr__(self, name):
        # Every remaining backend slot is an observable no-op recorder.
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self._record(name, *args, *kwargs.values())
            return True

        setattr(self, name, method)
        return method


class FakeDiagnostics:
    def __init__(self):
        self.checkResults = [
            {"checkId": "os_version", "title": "系统版本", "group": "ordinary_buttons",
             "status": "pass", "detail": "Windows 11", "resultCode": "ready"},
            {"checkId": "vb_cable_endpoints", "title": "虚拟声卡", "group": "optional_driver",
             "status": "fail", "detail": "未检测到 CABLE", "resultCode": "no_candidate"},
            {"checkId": "raw_input", "title": "按键输入", "group": "ordinary_buttons",
             "status": "manual", "detail": "请按一下遥控器按键", "resultCode": ""},
        ]
        self.isRefreshing = False
        self.diagnosticsErrorMessage = ""
        self.calls = []
        for name in ("checkResultsChanged", "isRefreshingChanged", "diagnosticsErrorMessageChanged"):
            setattr(self, name, FakeSignal())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args):
            self.calls.append((name,) + args)
            return True

        setattr(self, name, method)
        return method


class FakeModel:
    def __init__(self):
        self.rows = [
            {"buttonId": "mic", "displayName": "麦克风键", "actionText": "按住说话",
             "doubleClickText": "", "longPressText": "", "isMic": True,
             "singleNote": "说话", "doubleNote": "", "longNote": ""},
            {"buttonId": "power", "displayName": "电源键", "actionText": "Escape",
             "doubleClickText": "禁用", "longPressText": "禁用", "isMic": False,
             "singleNote": "", "doubleNote": "备用", "longNote": ""},
        ]
        self._role_by_name = {
            name.encode("utf-8"): index for index, name in enumerate(self.rows[0])
        }
        self.edits = []
        self.program_paths = {}
        self.text_contents = {}
        # Standard QAbstractListModel signals plus the model's edit signals -
        # device switches (set_profile -> modelReset) and programmatic loads
        # (load_display_map -> dataChanged) must notify the view-models.
        self.modelReset = FakeSignal()
        self.layoutChanged = FakeSignal()
        self.dataChanged = FakeSignal()
        self.rowsInserted = FakeSignal()
        self.rowsRemoved = FakeSignal()
        self.mappingEdited = FakeSignal()
        self.actionEdited = FakeSignal()

    def rowCount(self):
        return len(self.rows)

    def roleNames(self):
        return {index: name for name, index in self._role_by_name.items()}

    def index(self, row):
        return row

    def data(self, row_index, role):
        for name, index in self._role_by_name.items():
            if index == role:
                return self.rows[row_index][name.decode("utf-8")]
        return None

    def indexOfButton(self, button_id):
        for index, row in enumerate(self.rows):
            if row["buttonId"] == button_id:
                return index
        return -1

    def _edit(self, *args):
        self.edits.append(args)

    def setActionTextAt(self, row, text):
        self._edit("setActionTextAt", row, text)

    def setSecondaryActionTextAt(self, row, trigger, text):
        self._edit("setSecondaryActionTextAt", row, trigger, text)

    def setDisplayNoteAt(self, row, trigger, text):
        self._edit("setDisplayNoteAt", row, trigger, text)

    def setProgramPathAt(self, row, trigger, path):
        self._edit("setProgramPathAt", row, trigger, path)
        self.program_paths[(row, trigger)] = path

    def setTextContentAt(self, row, trigger, content):
        self._edit("setTextContentAt", row, trigger, content)
        self.text_contents[(row, trigger)] = content

    def programPathAt(self, row, trigger):
        return self.program_paths.get(
            (row, trigger), "C:\\Tools\\app.exe" if trigger == "single_click" else ""
        )

    def textContentAt(self, row, trigger):
        return self.text_contents.get(
            (row, trigger), "你好" if trigger == "single_click" else ""
        )


class FakeProbe:
    def __init__(self, verdict=None):
        self.verdict = verdict
        self.started = 0
        self.polled = 0

    def start(self):
        self.started += 1
        return None

    def poll(self):
        self.polled += 1
        return self.verdict


class TranslationTests(unittest.TestCase):
    def test_bridge_and_battery_labels(self):
        from ovb_rc003.presentation.viewmodels import battery_label, bridge_state_label

        self.assertEqual(bridge_state_label(True, True), "已连接")
        self.assertEqual(bridge_state_label(True, False), "连接中")
        self.assertEqual(bridge_state_label(False, False), "未连接")
        self.assertEqual(battery_label(87), "电量 87%")
        self.assertEqual(battery_label(-1), "电量未知")

    def test_check_row_translation(self):
        from ovb_rc003.presentation.viewmodels import check_row

        failed = check_row({"checkId": "vb_cable_endpoints", "title": "虚拟声卡",
                            "status": "fail", "detail": "未检测到 CABLE"})
        self.assertEqual(failed.id, "vb_cable_endpoints")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.fixLabel, "修复受影响项目")
        passed = check_row({"checkId": "os_version", "title": "系统版本",
                            "status": "pass", "detail": "Windows 11"})
        self.assertEqual(passed.status, "done")
        self.assertEqual(passed.fixLabel, "")
        self.assertEqual(check_row({"status": "manual"}).status, "todo")
        self.assertEqual(check_row({"status": "unsupported"}).status, "todo")

    def test_transport_renders_contract_shapes(self):
        verdict = contracts.Validation(True, "ok", "field")
        mapped = contract_qml_map(verdict)
        self.assertIsInstance(mapped, contracts.Validation)
        self.assertEqual(dict(mapped), {"ok": True, "message": "ok", "field": "field"})
        mirror = row_view(contracts.CheckRow("a", "b", "done", "d", ""))
        self.assertEqual(mirror.id, "a")
        self.assertEqual(mirror.title, "b")
        self.assertIsInstance(mirror.contract, contracts.CheckRow)


class AppViewmodelTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.vm = AppViewModel(self.controller)

    def test_status_card_and_labels(self):
        self.assertEqual(self.vm.windowTitle, "RemoteMic RC003")
        self.assertEqual(self.vm.versionLabel, "1.0.104")
        self.assertEqual(self.vm.bridgeStateLabel, "连接中")
        card = self.vm.statusCard.contract
        self.assertIsInstance(card, contracts.StatusCard)
        self.assertIn("小米遥控器2 Pro", card.title)
        self.assertIn("电量 87%", card.title)
        self.assertEqual(card.subtitle, "语音就绪")
        self.assertEqual(card.tone, "warn")
        self.assertEqual(card.actionLabel, "口述测试")
        self.assertEqual(card.actionId, "test-dictation")

    def test_current_page_is_pure_view_state(self):
        self.vm.currentPage = 2
        self.assertEqual(self.vm.currentPage, 2)
        self.assertFalse(
            any("activePageIndex" in str(call) for call in self.controller.calls),
            "currentPage must not touch the backend's activePageIndex (D2)",
        )

    def test_window_restore_lifecycle_forwarding(self):
        # Regression (TestRetool GAP 2): duplicate-launch restore must reach QML.
        self.assertFalse(self.vm.startHidden)
        self.controller.startHidden = True
        self.assertTrue(self.vm.startHidden)
        captured = []
        self.vm.windowRestoreRequested.connect(lambda: captured.append(True))
        self.controller.windowRestoreRequested.emit()
        self.assertEqual(len(captured), 1)
        self.vm.pollWindowRestoreRequest()
        self.assertIn(("pollWindowRestoreRequest",), self.controller.calls)

    def test_startup_lifecycle_slots(self):
        self.assertTrue(self.vm.onWindowReady())
        self.assertIn(("startBridgeOnApplicationStart",), self.controller.calls)
        self.assertTrue(self.vm.startupSettled())
        self.assertIn(("checkForApplicationUpdateOnStartup",), self.controller.calls)
        self.vm.tick()
        self.assertIn(("refreshBridgeState",), self.controller.calls)


class DeviceViewmodelTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.diagnostics = FakeDiagnostics()
        self.vm = DeviceViewModel(self.controller, self.diagnostics)

    def test_checks_and_remote_choices(self):
        checks = [row.contract for row in self.vm.checks]
        self.assertEqual([c.id for c in checks], ["os_version", "vb_cable_endpoints", "raw_input"])
        self.assertEqual(checks[1].fixLabel, "修复受影响项目")
        choices = [row.contract for row in self.vm.remoteChoices]
        self.assertEqual(choices[0].id, "x1")
        self.assertTrue(choices[0].selected)
        self.assertFalse(choices[1].enabled)
        self.assertEqual(self.vm.batteryLabel, "电量 87%")

    def test_bridge_action_dispatch(self):
        self.controller.bridgeRunning = False
        result = self.vm.bridgeAction()
        self.assertEqual(result["ok"], True)
        self.assertIn(("startBridge",), self.controller.calls)

        self.controller.calls.clear()
        self.controller.bridgeRunning = True
        self.controller.bridgeConnected = False
        self.vm.bridgeAction()
        self.assertIn(("reconnectBridgeNow",), self.controller.calls)

        self.controller.calls.clear()
        self.controller.bridgeReconnectAvailable = False
        self.vm.bridgeAction()
        self.assertIn(("restartBridge",), self.controller.calls)

        self.controller.calls.clear()
        self.controller.bridgeLaunchBusy = True
        result = self.vm.bridgeAction()
        self.assertEqual(result["ok"], False)
        self.assertEqual(self.controller.calls, [])

    def test_fix_check_dispatch(self):
        self.vm.fixCheck("vb_cable_endpoints")
        self.assertIn(("launchVbCableSetup",), self.diagnostics.calls)
        self.vm.fixCheck("ble_candidate")
        self.assertIn(("refreshRemoteDevices",), self.controller.calls)
        self.vm.fixCheck("os_version")
        self.vm.fixCheck("nonsense")

    def test_refresh_and_use_remote(self):
        self.vm.refresh()
        self.vm.useRemote("x1")
        self.assertIn(("refreshRemoteDevices",), self.controller.calls)
        self.assertIn(("refreshDiagnostics",), self.diagnostics.calls)
        self.assertIn(("useRemoteDevice", "x1"), self.controller.calls)


class VoiceViewmodelTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.controller.bridgeConnected = True
        self.diagnostics = FakeDiagnostics()
        self.probe = FakeProbe(contracts.Validation(True, "口述验收通过", "probe"))
        self.vm = VoiceViewModel(
            self.controller, self.diagnostics, dictation_probe=self.probe
        )

    def test_labels(self):
        self.assertEqual(self.vm.hotkeyLabel, "右 Alt")
        self.assertEqual(self.vm.recordingMode, "按住说话")
        self.assertEqual(self.vm.audioRouteLabel, "CABLE Output — WASAPI")
        self.assertEqual(self.vm.recordingLimitSeconds, 180)
        programs = [row.contract for row in self.vm.voicePrograms]
        self.assertEqual([p.id for p in programs], ["0", "1", "2"])
        self.assertTrue(programs[1].selected)
        endpoints = [row.contract for row in self.vm.outputEndpoints]
        self.assertEqual(endpoints[0].detail, "推荐")
        self.assertTrue(endpoints[0].selected)

    def test_setters_forward(self):
        self.vm.setVoiceProgram("2")
        self.assertEqual(self.controller.selectedVoiceProgramIndex, 2)
        self.vm.setRecordingMode("按一次开·再按一次关")
        self.assertIn(("setRemoteRecordingPreferences", 1, 2), self.controller.calls)
        self.vm.setRecordingLimit(350)
        self.assertIn(("setRemoteRecordingPreferences", 0, 3), self.controller.calls)
        self.vm.selectOutput("1")
        self.assertIn(("selectAndPersistOutputEndpointIndex", 1), self.controller.calls)
        self.vm.installVirtualCable()
        self.assertIn(("launchVbCableSetup",), self.diagnostics.calls)
        self.vm.testAudio()
        self.assertIn(("testVbCableChannel",), self.diagnostics.calls)

    def test_hotkey_capture_auto_commits_like_old_view(self):
        self.vm.startHotkeyCapture()
        self.assertIn(("startHotkeyCapture",), self.controller.calls)
        self.controller.hotkeyCaptured.emit("ctrl+alt+j")
        self.assertEqual(self.controller.holdVoiceHotkeyText, "ctrl+alt+j")
        self.controller.hotkeyCaptureError.emit("无法录入")
        self.assertEqual(self.vm.lastValidation.contract.ok, False)

    def test_dictation_runs_real_probe(self):
        result = self.vm.testDictation()
        self.assertEqual(result["ok"], True)
        self.assertEqual(self.probe.started, 1)
        self.assertEqual(self.vm.lastValidation.contract.message, "口述验收通过")

    def test_dictation_reports_blockers(self):
        self.controller.bridgeConnected = False
        result = self.vm.testDictation()
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["field"], "connection")
        self.assertEqual(self.probe.started, 0)

    def test_recording_display_refreshes_on_selection_notify(self):
        # Regression (remote-selection probe): recording-pref saves, busy/save
        # rejections and limit-only saves all report through the controller's
        # remoteSelectionChanged; without it the selectors never snap back.
        hits = []
        self.vm.recordingModeChanged.connect(lambda: hits.append(True))
        self.controller.remoteSelectionChanged.emit()
        self.assertTrue(hits, "remoteSelectionChanged must refresh recording display")


class MappingViewmodelTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.model = FakeModel()
        self.vm = MappingViewModel(self.model, self.controller)

    def test_buttons_carry_notes_and_mic_flag(self):
        rows = [row.contract for row in self.vm.buttons]
        self.assertEqual(rows[0].id, "mic")
        self.assertTrue(rows[0].isMic)
        self.assertEqual(rows[0].singleNote, "说话")
        self.assertEqual(rows[1].doubleNote, "备用")

    def test_set_action_validates_and_translates_gesture(self):
        result = self.vm.setAction("power", "double", "回车")
        self.assertEqual(result["ok"], True)
        self.assertIn(
            ("validate", "power", "double_click", "回车", "", ""),
            self.controller.calls,
        )
        self.assertIn(("setSecondaryActionTextAt", 1, "double_click", "回车"),
                      self.model.edits)
        result = self.vm.setAction("power", "nonsense", "回车")
        self.assertEqual(result["ok"], False)

    def test_set_action_is_draft_aware_for_kind_switches(self):
        # Regression (mapping-editor probe GAP 2): the editor commits the
        # cell's payload FIRST, so the kind switch must validate against that
        # draft - otherwise 输入文字/打开程序 can never be created (the retired
        # combo saved kind+payload atomically).
        self.vm.setTextContent("power", "single", "你好世界")
        self.controller.calls.clear()
        result = self.vm.setAction("power", "single", "输入文字")
        self.assertEqual(result["ok"], True, result["message"])
        self.assertIn(
            ("validate", "power", "single_click", "输入文字", "你好世界", "C:\\Tools\\app.exe"),
            self.controller.calls,
        )
        self.assertIn(("setActionTextAt", 1, "输入文字"), self.model.edits)

    def test_presets_self_load_and_retry_while_busy(self):
        # Regression (mapping-editor probe GAP 1): the retired dialog ran the
        # refresh op on open; nothing else materializes the preset store, so
        # the view-model loads at construction and retries on first read.
        from ovb_rc003.presentation.viewmodels import MappingViewModel as Fresh

        self.controller.preset_refresh_ok = False
        self.controller.calls.clear()
        vm = Fresh(self.model, self.controller)
        refresh = ("preset", "refresh", "", "")
        self.assertIn(refresh, self.controller.calls)
        first = self.controller.calls.count(refresh)
        list(vm.presets)  # busy refusal must not mark the store loaded
        self.assertGreater(self.controller.calls.count(refresh), first)
        self.controller.preset_refresh_ok = True
        list(vm.presets)
        settled = self.controller.calls.count(refresh)
        list(vm.presets)
        self.assertEqual(self.controller.calls.count(refresh), settled,
                         "once loaded, reads must not re-refresh")

    def test_set_action_surfaces_validation_message(self):
        self.controller.buttonValidationMessage = "长按：不支持的按键"
        result = self.vm.setAction("power", "longPress", "nope")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["message"], "长按：不支持的按键")
        self.assertEqual(self.model.edits, [])

    def test_pick_program_path_and_text_content(self):
        result = self.vm.pickProgramPath("power", "single", "file:///C:/Tools/app.exe")
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["message"], "C:\\Tools\\app.exe")
        self.assertIn(("setProgramPathAt", 1, "single_click", "C:\\Tools\\app.exe"),
                      self.model.edits)
        self.assertEqual(self.vm.programPath("power", "single"), "C:\\Tools\\app.exe")
        result = self.vm.setTextContent("power", "single", "你好")
        self.assertEqual(result["ok"], True)
        self.assertEqual(self.vm.textContent("power", "single"), "你好")

    def test_presets_and_notes(self):
        from ovb_rc003 import mapping_presets

        self.controller.mappingPresets = [
            {"id": "auto", "name": "自动保存项", "automatic": True, "applied": True},
            {"id": "p1", "name": "看电视", "automatic": False, "applied": False},
        ]
        presets = [row.contract for row in self.vm.presets]
        self.assertEqual(presets[0].detail, "自动")
        self.assertTrue(presets[0].selected)
        self.assertFalse(presets[1].selected)
        self.vm.applyPreset("p1")
        self.assertIn(("preset", "apply", "p1", ""), self.controller.calls)
        self.vm.savePreset("新配置")
        self.assertIn(("preset", "copy", mapping_presets.AUTO_ID, "新配置"), self.controller.calls)
        self.vm.deletePreset("p1")
        self.vm.exportPreset("p1", "file:///tmp/p1.json")
        self.vm.importPreset("file:///tmp/p2.json")
        self.vm.renamePreset("p1", "改名")
        self.vm.setNote("power", "double", "")
        self.assertIn(("setDisplayNoteAt", 1, "double_click", ""), self.model.edits)

    def test_action_options_grouped(self):
        rows = [row.contract for row in self.vm.actionOptions("power", "single")]
        self.assertEqual([r.label for r in rows], ["Escape", "输入文字", "打开程序"])
        self.assertEqual(rows[1].detail, "文字输入")
        self.assertTrue(rows[0].selected)  # current action text is Escape

    def test_shortcut_recorder_forwards(self):
        self.vm.captureShortcut()
        self.assertIn(("startMappingHotkeyCapture",), self.controller.calls)
        self.vm.stopShortcutCapture()
        self.assertIn(("stopHotkeyCapture",), self.controller.calls)
        captured = []
        self.vm.shortcutCaptured.connect(captured.append)
        self.controller.hotkeyCaptured.emit("ctrl+shift+p")
        self.assertEqual(captured, ["ctrl+shift+p"])

    def test_buttons_notify_on_device_switch_and_load(self):
        # Regression (remote-selection probe): switching remotes rebuilds the
        # model via set_profile/modelReset and load_display_map/dataChanged -
        # the buttons binding must re-evaluate or the Keys page goes stale.
        hits = []
        self.vm.buttonsChanged.connect(lambda: hits.append(True))
        self.model.modelReset.emit()
        self.assertTrue(hits, "modelReset must emit buttonsChanged")
        hits.clear()
        self.model.dataChanged.emit()
        self.assertTrue(hits, "dataChanged must emit buttonsChanged")
        hits.clear()
        self.controller.selectedDeviceChanged.emit()
        self.assertTrue(hits, "device switch must emit buttonsChanged")


class MaintenanceViewmodelTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.controller._can_auto_save = True
        self.diagnostics = FakeDiagnostics()
        self.vm = MaintenanceViewModel(self.controller, self.diagnostics)

    def test_items_cover_exactly_the_maintenance_enum(self):
        rows = [row.contract for row in self.vm.items]
        self.assertEqual(tuple(r.id for r in rows), contracts.MAINTENANCE_ITEM_IDS)
        self.assertEqual(rows[3].fixLabel, "导出日志")

    def test_run_dispatch_covers_exactly_the_maintenance_enum(self):
        for item_id in contracts.MAINTENANCE_ITEM_IDS:
            self.controller.calls.clear()
            self.diagnostics.calls.clear()
            self.vm.run(item_id)
            forwarded = self.controller.calls + self.diagnostics.calls
            self.assertTrue(forwarded, f"run({item_id!r}) forwarded nothing")
        self.controller.calls.clear()
        self.vm.run("not-an-item")
        self.assertEqual(self.controller.calls, [], "unknown run ids must not dispatch")

    def test_set_preference_dispatch_covers_exactly_the_preference_enum(self):
        for pref_id in contracts.PREFERENCE_IDS:
            self.controller.calls.clear()
            result = self.vm.setPreference(pref_id, True)
            self.assertEqual(result["ok"], True, pref_id)
            self.assertTrue(self.controller.calls, pref_id)
        self.controller.calls.clear()
        result = self.vm.setPreference("unknown", True)
        self.assertEqual(result["ok"], False)
        self.assertEqual(self.controller.calls, [])

    def test_preferences_rows_and_read_only(self):
        rows = [row.contract for row in self.vm.preferences]
        self.assertEqual(tuple(r.id for r in rows), contracts.PREFERENCE_IDS)
        self.assertTrue(rows[0].value)
        self.assertTrue(all(r.enabled for r in rows))
        self.controller.configurationReadOnly = True
        rows = [row.contract for row in self.vm.preferences]
        self.assertFalse(any(r.enabled for r in rows))

    def test_close_behavior_reads_the_config_constants(self):
        # Regression (TestRetool BUG 1): closeBehavior carries
        # config.CLOSE_BEHAVIOR_HIDE_TO_TRAY ("hide_to_tray"), never "hide".
        from ovb_rc003 import config

        self.controller.closeBehavior = config.CLOSE_BEHAVIOR_HIDE_TO_TRAY
        rows = {row.contract.id: row.contract for row in self.vm.preferences}
        self.assertTrue(rows["hide_to_tray_on_close"].value)
        self.controller.closeBehavior = config.CLOSE_BEHAVIOR_QUIT
        rows = {row.contract.id: row.contract for row in self.vm.preferences}
        self.assertFalse(rows["hide_to_tray_on_close"].value)
        self.assertTrue(self.vm.setPreference("hide_to_tray_on_close", True)["ok"])
        self.assertIn(("setCloseBehaviorIndex", 0), self.controller.calls)
        self.vm.setPreference("hide_to_tray_on_close", False)
        self.assertIn(("setCloseBehaviorIndex", 1), self.controller.calls)

    def test_confirm_exit_save_branches(self):
        result = self.vm.confirmExitSave()
        self.assertEqual(result["ok"], True)
        self.assertIn(("saveSettingsAndExit",), self.controller.calls)
        self.controller.calls.clear()
        self.controller._can_auto_save = False
        self.vm.confirmExitSave()
        self.assertIn(("requestApplicationExit",), self.controller.calls)

    def test_logs_affordances(self):
        result = self.vm.saveLogs("file:///tmp/app-logs.zip")
        self.assertEqual(result["ok"], True)
        self.assertIn(("exportLogs", "file:///tmp/app-logs.zip"), self.controller.calls)
        result = self.vm.openLogs()
        self.assertEqual(result["ok"], True)
        self.assertIn(("openLogLocation",), self.controller.calls)

    def test_update_status_and_run_update(self):
        card = self.vm.updateStatus.contract
        self.assertEqual(card.actionId, "update")
        self.vm.run("update")
        self.assertIn(("checkForApplicationUpdate",), self.controller.calls)
        self.controller.calls.clear()
        self.controller.applicationUpdateCanDownload = True
        self.vm.run("update")
        self.assertIn(("downloadApplicationUpdate",), self.controller.calls)


class D8TypedSlotTests(unittest.TestCase):
    """D8: the homeless capabilities shipped as typed slots (D1 pattern)."""

    def setUp(self):
        self.controller = FakeController()
        self.diagnostics = FakeDiagnostics()
        self.model = FakeModel()

    def test_mapping_key_detection_and_save_retry(self):
        vm = MappingViewModel(self.model, self.controller)
        self.controller.keyDetectionText = "已检测到：确定键"
        self.assertEqual(vm.keyDetectionText, "已检测到：确定键")
        self.assertFalse(vm.mappingAutoSaveRetryAvailable)
        result = vm.startKeyDetection()
        self.assertTrue(result["ok"])
        self.assertIn(("startKeyDetection",), self.controller.calls)
        result = vm.stopKeyDetection()
        self.assertTrue(result["ok"])
        self.assertIn(("stopKeyDetection",), self.controller.calls)
        result = vm.retryMappingAutoSave()
        self.assertTrue(result["ok"])
        self.assertIn(("retryMappingAutoSave",), self.controller.calls)

    def test_voice_program_slots(self):
        vm = VoiceViewModel(self.controller, self.diagnostics, dictation_probe=FakeProbe())
        self.assertEqual(vm.customProgramPath, "")
        result = vm.pickCustomProgramPath("file:///C:/Tools/ime.exe")
        self.assertTrue(result["ok"])
        self.assertEqual(self.controller.voiceProgramCustomPath, "C:\\Tools\\ime.exe")
        self.assertEqual(vm.customProgramPath, "C:\\Tools\\ime.exe")
        self.assertFalse(vm.autoLaunch)
        self.assertTrue(vm.setAutoLaunch(True)["ok"])
        self.assertTrue(vm.autoLaunch)
        self.assertFalse(vm.launchElevated)
        self.assertTrue(vm.setLaunchElevated(True)["ok"])
        self.assertTrue(vm.launchElevated)
        self.assertTrue(vm.launchVoiceProgram()["ok"])
        self.assertIn(("launchVoiceProgram",), self.controller.calls)
        self.assertTrue(vm.openVoiceProgramSettings()["ok"])
        self.assertIn(("openVoiceProgramSettings",), self.controller.calls)

    def test_maintenance_system_affordances(self):
        vm = MaintenanceViewModel(self.controller, self.diagnostics)
        for slot_name in (
            "openMicrophonePrivacySettings",
            "openSpeechSettings",
            "openSoundSettings",
            "openAppsSettings",
        ):
            self.controller.calls.clear()
            self.assertTrue(getattr(vm, slot_name)()["ok"], slot_name)
            self.assertTrue(self.controller.calls, slot_name)
        self.assertTrue(vm.removeHelper()["ok"])
        self.assertIn(("removeHidHelper",), self.controller.calls)
        self.assertTrue(vm.cancelUpdateDownload()["ok"])
        self.assertIn(("cancelApplicationUpdateDownload",), self.controller.calls)
        self.assertTrue(vm.openUpdateRelease()["ok"])
        self.assertIn(("openApplicationUpdateRelease",), self.controller.calls)


class DictationProbeEvidenceTests(unittest.TestCase):
    """D9 honesty rule: the verdict claims only observed evidence and always
    states the input-source attribution limitation.
    """

    def _probe(self):
        from types import SimpleNamespace

        from ovb_rc003.presentation.viewmodels import NativeDictationProbe

        holder = {"state": "not_tested", "text": "unchanged"}

        class Clock:
            t = 0.0

            def __call__(self):
                return self.t

        clock = Clock()
        probe = NativeDictationProbe(
            capture=lambda: SimpleNamespace(supported=True),
            compare=lambda before, after: SimpleNamespace(text_state=holder["text"]),
            runtime_state=lambda: holder["state"],
            clock=clock,
            timeout_seconds=10.0,
        )
        return probe, holder, clock

    def test_success_claims_exactly_the_observed_evidence(self):
        probe, holder, _clock = self._probe()
        self.assertIsNone(probe.start())
        self.assertIsNone(probe.poll())  # session starting, no evidence yet
        holder["state"] = "receiving_audio"
        self.assertIsNone(probe.poll())
        holder["state"] = "success"
        holder["text"] = "grew"
        verdict = probe.poll()
        self.assertIsNotNone(verdict)
        self.assertTrue(verdict.ok)
        for claim in ("会话已开始", "收到非空音频", "会话正常结束", "测试输入框文本增长"):
            self.assertIn(claim, verdict.message)
        self.assertIn("限制", verdict.message)
        self.assertIn("无法区分手工输入/粘贴", verdict.message)

    def test_session_end_without_text_growth_fails(self):
        probe, holder, _clock = self._probe()
        self.assertIsNone(probe.start())
        holder["state"] = "success"
        verdict = probe.poll()
        self.assertFalse(verdict.ok)
        self.assertIn("未观测到测试输入框文本增长", verdict.message)
        self.assertIn("收到非空音频", verdict.message)  # observed evidence still named
        self.assertIn("限制", verdict.message)

    def test_empty_audio_fails_with_the_observed_reason(self):
        probe, holder, _clock = self._probe()
        self.assertIsNone(probe.start())
        holder["state"] = "audio_empty"
        verdict = probe.poll()
        self.assertFalse(verdict.ok)
        self.assertIn("收到的音频为空", verdict.message)
        self.assertIn("限制", verdict.message)

    def test_timeout_reports_missing_evidence(self):
        probe, holder, clock = self._probe()
        self.assertIsNone(probe.start())
        clock.t = 999.0
        verdict = probe.poll()
        self.assertFalse(verdict.ok)
        self.assertIn("超时", verdict.message)
        self.assertIn("限制", verdict.message)


class RegistrySeamTests(unittest.TestCase):
    """The registry must expose exactly the five view-models plus the
    self-activating slice-C seam (Main's landed hook passes no ``onboarding=``).
    """

    def test_pairs_cover_exactly_the_singleton_type_names(self):
        from ovb_rc003.presentation import registry

        set_ = registry.build_viewmodels(
            controller=FakeController(),
            mapping_model=FakeModel(),
            diagnostics=FakeDiagnostics(),
        )
        self.assertEqual(
            [name for name, _instance in set_.pairs()],
            list(registry.SINGLETON_TYPE_NAMES),
        )

    def test_onboarding_seam_constructs_slice_c_singleton(self):
        from ovb_rc003.presentation import registry

        viewmodel = registry._build_onboarding_viewmodel()
        try:
            from ovb_rc003.presentation import onboarding
        except ImportError:
            self.assertIsNone(viewmodel)
            return
        self.assertIsInstance(viewmodel, onboarding.OnboardingViewModel)


if __name__ == "__main__":
    unittest.main()
