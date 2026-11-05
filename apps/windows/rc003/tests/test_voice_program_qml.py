import json
import os
import subprocess
import sys
import tempfile
import unittest


_PROBE = r"""
import json
import os
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from ovb_rc003 import qt_settings_app as m
from unittest.mock import Mock
m.wetype_control_windows.begin_input_profile_selection = Mock(
    return_value=Mock(result=Mock(return_value=False)))
from ovb_rc003 import chromecast_etw_windows
chromecast_etw_windows.sensitive_logging_enabled = lambda: True


def find(root, name):
    children = list(root.children())
    child_items = getattr(root, "childItems", None)
    if callable(child_items):
        children.extend(child for child in child_items() if child not in children)
    for child in children:
        if child.objectName() == name:
            return child
        found = find(child, name)
        if found is not None:
            return found
    return None


def render(window, app, count=10):
    image = None
    for _ in range(count):
        image = window.grabWindow()
        app.processEvents()
    return image


def wait_for_voice_hotkey_idle(controller, app, timeout=3.0):
    deadline = time.monotonic() + timeout
    while controller.voiceHotkeyBusy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not controller.voiceHotkeyBusy


def geometry(item):
    if hasattr(item, "mapToScene"):
        point = item.mapToScene(QPointF(0, 0))
        x = point.x()
        y = point.y()
    else:
        x = float(item.property("x"))
        y = float(item.property("y"))
    width = float(item.property("width"))
    height = float(item.property("height"))
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "right": x + width,
        "bottom": y + height,
    }


classes = m._load_qt_classes()
QGuiApplication = classes["QGuiApplication"]
QQmlApplicationEngine = classes["QQmlApplicationEngine"]
QQuickStyle = classes["QQuickStyle"]
QUrl = classes["QUrl"]
qmlRegisterSingletonInstance = classes["qmlRegisterSingletonInstance"]
ButtonMappingModel = classes["ButtonMappingModel"]
SettingsController = classes["SettingsController"]
DiagnosticsController = classes["DiagnosticsController"]


class FakeHotkeyCapture:
    def __init__(self, on_captured, *, accept_injected=False, isolated=False, on_error=None):
        self.on_captured = on_captured
        self.accept_injected = accept_injected
        self.is_running = False

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False


m.hotkey_capture_windows.HotkeyCapture = FakeHotkeyCapture


voice_program_probe_status = {"code": "not_found", "elevated": None}


def inspect_voice_program(settings):
    provider_id = str(settings.get("provider", ""))
    return m.voice_program_manager.VoiceProgramStatus(
        provider_id=provider_id,
        display_name=m.voice_program_manager.VOICE_PROGRAM_PROVIDER_NAMES.get(
            provider_id, "测试语音程序"
        ),
        available=voice_program_probe_status["code"] != "not_found",
        running=voice_program_probe_status["code"] == "running",
        elevated=voice_program_probe_status["elevated"],
        executable=None,
        code=voice_program_probe_status["code"],
    )


m.voice_program_manager.inspect_voice_program = inspect_voice_program
m.voice_program_manager.launch_voice_program = lambda settings: (
    m.voice_program_manager.VoiceProgramLaunchResult(
        str(settings.get("provider", "")), False, True, "already_running"
    )
)


provider_read_requests = []


def read_provider_hotkey(
    provider_id,
    *,
    allow_settings_window=False,
    cancel_event=None,
    trigger="hold",
):
    provider_id = str(provider_id)
    provider_read_requests.append((provider_id, allow_settings_window))
    shortcuts = {
        "sogou": "rctrl",
        "wetype": "lctrl+lwin",
        "doubao_ime": "ralt",
        "chatterfly": "rctrl+rshift+0",
    }
    shortcut = shortcuts.get(provider_id, "")
    if provider_id == "wetype" and not allow_settings_window:
        shortcut = ""
    return m.voice_hotkey_sync_windows.VoiceHotkeySyncResult(
        provider_id,
        bool(shortcut),
        "read" if shortcut else "local_only",
        shortcut,
        "test provider shortcut",
    )


m.voice_hotkey_sync_windows.read_provider_hotkey = read_provider_hotkey

QQuickStyle.setStyle("Basic")
app = QGuiApplication.instance() or QGuiApplication([])
m.single_instance.bridge_instance_running = lambda: False
model = ButtonMappingModel()
controller = SettingsController(model)
diagnostics = DiagnosticsController(controller, m.config.config_root())
# Harness safety: probes must never launch or replace a real bridge process.
controller._start_automatic_bridge_recovery = lambda: None
qmlRegisterSingletonInstance(
    SettingsController, "OvbRc003Settings", 1, 0, "SettingsController", controller
)
qmlRegisterSingletonInstance(
    ButtonMappingModel, "OvbRc003Settings", 1, 0, "ButtonMappingModel", model
)
qmlRegisterSingletonInstance(
    DiagnosticsController,
    "OvbRc003Settings",
    1,
    0,
    "DiagnosticsController",
    diagnostics,
)
from ovb_rc003.presentation import registry
_viewmodels = registry.register(controller=controller, mapping_model=model, diagnostics=diagnostics)

engine = QQmlApplicationEngine()
qml_dir = m._qml_directory()
engine.addImportPath(str(qml_dir))
warnings = []
engine.warnings.connect(lambda values: warnings.extend(values))
engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
assert len(engine.rootObjects()) == 1
window = engine.rootObjects()[0]
window.show()
render(window, app)

page_stack = find(window, "pageStack")
window.setProperty("width", 900)
window.setProperty("height", 2400)
_viewmodels.AppViewModel.currentPage = 2
find(window, "settingsVoiceSection").setProperty("folded", False)
render(window, app)

voice_vm = _viewmodels.VoiceViewModel

pick_button = find(window, "settingsPickCustomProgramButton")
custom_path_field = pick_button.parent().children()[0]
start_button = find(window, "settingsStartHotkeyCaptureButton")
stop_button = find(window, "settingsStopHotkeyCaptureButton")
hotkey_label = start_button.parent().children()[0]

controls = {
    name: find(window, name)
    for name in (
        "settingsVoiceSection",
        "settingsPickCustomProgramButton",
        "settingsLaunchVoiceProgramButton",
        "settingsOpenVoiceProgramSettingsButton",
        "settingsStartHotkeyCaptureButton",
        "settingsStopHotkeyCaptureButton",
        "settingsTestAudioButton",
        "settingsInstallVirtualCableButton",
        "settingsSetRecordingLimitButton",
    )
}
assert all(control is not None for control in controls.values())
assert custom_path_field is not None
assert hotkey_label is not None


def click(item):
    point = item.mapToScene(
        QPointF(item.property("width") / 2, item.property("height") / 2)
    ).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    render(window, app)


controller.selectedVoiceProgramIndex = 1
wait_for_voice_hotkey_idle(controller, app)
render(window, app)

managed = {}
for name, control in list(controls.items()) + [
    ("customProgramPathField", custom_path_field),
    ("hotkeyLabel", hotkey_label),
]:
    managed[name] = {
        "visible": bool(control.property("visible")),
        "enabled": bool(control.property("enabled")),
        "geometry": geometry(control),
        "text": str(control.property("text"))
        if name in ("settingsOpenVoiceProgramSettingsButton", "customProgramPathField",
                    "hotkeyLabel")
        else "",
    }

program_rows = [
    {
        "id": str(row.contract.id),
        "label": str(row.contract.label),
        "enabled": bool(row.contract.enabled),
        "selected": bool(row.contract.selected),
    }
    for row in voice_vm.voicePrograms
]
open_settings_text = str(
    controls["settingsOpenVoiceProgramSettingsButton"].property("text")
)
auto_launch = bool(voice_vm.autoLaunch)
launch_elevated = bool(voice_vm.launchElevated)

original_hotkey = str(controller.holdVoiceHotkeyText)
hotkey_label_before = str(voice_vm.hotkeyLabel)
click(start_button)
capture_started = bool(controller.hotkeyCaptureActive)
click(stop_button)
capture_flow = {
    "started": capture_started,
    "stopped": not bool(controller.hotkeyCaptureActive),
    "original_text": original_hotkey,
    "field_text": str(controller.holdVoiceHotkeyText),
    "label_before": hotkey_label_before,
    "label_after": str(voice_vm.hotkeyLabel),
}

controller.selectedVoiceProgramIndex = 2
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
wetype_explicit_reads = provider_read_requests.count(("wetype", True))
voice_program_probe_status.update(code="stopped", elevated=None)
controller._refresh_voice_program_status()
render(window, app)
wetype_program_installed = str(voice_vm.voiceCard.contract.detail)
voice_program_probe_status.update(code="running", elevated=None)
controller._refresh_voice_program_status()
render(window, app)
wetype_program_running = str(voice_vm.voiceCard.contract.detail)
voice_program_probe_status.update(code="not_found", elevated=None)
controller._refresh_voice_program_status()

controller.selectedVoiceProgramIndex = 5
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
chatterfly_hotkey_label = str(voice_vm.hotkeyLabel)

controller._replace_voice_program_settings(
    dict(controller._voice_program_settings, provider="custom")
)
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
custom_exe = m.config.config_root() / "voice-tool.exe"
custom_exe.parent.mkdir(parents=True, exist_ok=True)
custom_exe.touch()
picked = voice_vm.pickCustomProgramPath(QUrl.fromLocalFile(str(custom_exe)).toString())
custom_path = {
    "ok": bool(picked.ok),
    "expected": str(custom_exe),
    "path": str(picked.message),
    "view_path": str(voice_vm.customProgramPath),
    "field_text": str(custom_path_field.property("text")),
}

provider_states = {}
for provider_id, index in (("sogou", 1), ("wetype", 2), ("doubao_ime", 3), ("chatterfly", 5)):
    controller.selectedVoiceProgramIndex = index
    wait_for_voice_hotkey_idle(controller, app)
    render(window, app)
    provider_states[provider_id] = {
        "controls_visible": all(
            bool(control.property("visible")) for control in controls.values()
        ),
        "controls_enabled": all(
            bool(control.property("enabled")) for control in controls.values()
        ),
        "auto_launch": bool(voice_vm.autoLaunch),
        "launch_elevated": bool(voice_vm.launchElevated),
        "custom_program_path": str(voice_vm.customProgramPath),
    }

controller.hotkeyCaptureError.emit("模拟启动失败")
render(window, app)
inactive_capture_error = {
    "message": str(voice_vm.lastValidation.contract.message),
    "ok": bool(voice_vm.lastValidation.contract.ok),
    "field": str(voice_vm.lastValidation.contract.field),
    "facet": str(find(window, "homeFacetDictation").property("valueText")),
    "capture_active": bool(controller.hotkeyCaptureActive),
}

retained_capture = FakeHotkeyCapture(lambda _chord: None)
retained_capture.is_running = True
controller._hotkey_capture = retained_capture
controller._set_input_operation_state("hotkey", "active")
controller.hotkeyCaptureError.emit("模拟停止前异常")
render(window, app)
active_capture_error = {
    "message": str(voice_vm.lastValidation.contract.message),
    "facet": str(find(window, "homeFacetDictation").property("valueText")),
    "capture_retained": bool(controller.hotkeyCaptureActive),
}
controller.stopHotkeyCapture()
render(window, app)

click(start_button)
elevated_before = bool(voice_vm.launchElevated)
other_verdict = voice_vm.setLaunchElevated(not elevated_before)
hotkey_other_action = {
    "action_completed": bool(voice_vm.launchElevated) != elevated_before,
    "validation_ok": bool(other_verdict.ok),
}
voice_vm.setLaunchElevated(elevated_before)
controller.stopHotkeyCapture()
render(window, app)

screenshot = os.environ.get("VOICE_PROGRAM_SCREENSHOT")
if screenshot:
    window.grabWindow().save(screenshot)

result = {
    "warnings": [value.toString() for value in warnings],
    "root_objects": len(engine.rootObjects()),
    "window_width": float(window.property("width")),
    "window_height": float(window.property("height")),
    "managed": managed,
    "open_settings_text": open_settings_text,
    "program_rows": program_rows,
    "auto_launch": auto_launch,
    "launch_elevated": launch_elevated,
    "capture_flow": capture_flow,
    "wetype_explicit_reads": wetype_explicit_reads,
    "wetype_program_installed": wetype_program_installed,
    "wetype_program_running": wetype_program_running,
    "chatterfly_hotkey_label": chatterfly_hotkey_label,
    "custom_path": custom_path,
    "provider_states": provider_states,
    "inactive_capture_error": inactive_capture_error,
    "active_capture_error": active_capture_error,
    "hotkey_other_action": hotkey_other_action,
    "retired_controls_absent": all(
        find(window, name) is None
        for name in (
            "voiceProgramButton",
            "voiceProgramDialog",
            "voiceProgramAutoStartCheckBox",
            "saveVoiceProgramButton",
            "refreshVoiceProgramButton",
            "launchVoiceProgramButton",
            "voiceProgramSpecificRow",
            "voiceProgramLaunchText",
            "voiceProgramStatusRefreshTimer",
            "useWindowsDictationHotkeyButton",
            "voiceProgramCombo",
            "voiceProgramSelectionRow",
            "voiceHotkeyRow",
            "holdVoiceHotkeyField",
            "recordVoiceHotkeyButton",
            "refreshVoiceHotkeyButton",
            "voiceProgramElevatedCheckBox",
            "openVoiceProgramSettingsButton",
            "voiceProgramCustomPathField",
            "voiceScroll",
        )
    ),
}
controller.shutdownBackgroundTasks()
m._shutdown_diagnostics_workers()
print(json.dumps(result, ensure_ascii=False))
"""


class VoiceProgramQmlTests(unittest.TestCase):
    def test_running_sogou_is_shown_as_running_without_a_voice_window(self):
        probe = _PROBE.replace(
            "controller.shutdownBackgroundTasks()",
            '''voice_program_probe_status.update(code="running", elevated=None)
controller._replace_voice_program_settings(
    m.voice_program_manager.normalize_voice_program_settings({"provider": "sogou"})
)
controller._refresh_voice_program_status()
render(window, app)
result["root_objects"] = len(engine.rootObjects())
result["sogou_running_state"] = str(voice_vm.voiceCard.contract.detail)
controller.shutdownBackgroundTasks()''',
        )
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env["LOCALAPPDATA"] = tempfile.mkdtemp()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"voice-program QML probe failed: {result.stdout}\n{result.stderr}",
        )
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["root_objects"], 1)
        self.assertEqual(data["sogou_running_state"], "正在运行（权限状态未知）。")

    def test_voice_page_owns_the_provider_specific_voice_program_controls(self):
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env["LOCALAPPDATA"] = tempfile.mkdtemp()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"voice-program QML probe failed: {result.stdout}\n{result.stderr}",
        )
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["root_objects"], 1)
        self.assertTrue(data["retired_controls_absent"])

        # The voice surface owns the provider selection rows and every
        # provider-specific voice-program control.
        self.assertEqual(len(data["program_rows"]), 5)
        self.assertEqual(
            [row["id"] for row in data["program_rows"]], ["0", "1", "2", "3", "4"]
        )
        self.assertTrue(all(row["enabled"] for row in data["program_rows"]))
        self.assertEqual(
            [row["selected"] for row in data["program_rows"]],
            [False, True, False, False, False],
        )
        self.assertTrue(all(item["visible"] for item in data["managed"].values()))
        self.assertTrue(all(item["enabled"] for item in data["managed"].values()))
        self.assertEqual(
            data["managed"]["settingsOpenVoiceProgramSettingsButton"]["text"],
            "打开语音程序设置",
        )
        self.assertTrue(data["auto_launch"])
        self.assertTrue(data["launch_elevated"])

        # Provider hotkey read-back reflects onto the presentation label and
        # never opens the provider settings window implicitly.
        self.assertEqual(data["chatterfly_hotkey_label"], "右 Ctrl + 右 Shift + 0")
        self.assertEqual(data["wetype_explicit_reads"], 0)
        self.assertEqual(
            data["wetype_program_installed"],
            "已找到微信输入法；由 Windows 管理，当前未检测到后台进程。",
        )
        self.assertEqual(
            data["wetype_program_running"],
            "微信输入法已安装并正在运行（由 Windows 管理）。",
        )

        # Hotkey capture is owned by the 录入/停止 pair; cancelling preserves
        # the configured shortcut exactly.
        self.assertTrue(data["capture_flow"]["started"])
        self.assertTrue(data["capture_flow"]["stopped"])
        self.assertEqual(
            data["capture_flow"]["field_text"], data["capture_flow"]["original_text"]
        )
        self.assertEqual(
            data["capture_flow"]["label_after"], data["capture_flow"]["label_before"]
        )

        # Custom program path: the typed pick slot stores the chosen file and
        # both the view-model and the path field reflect it.
        self.assertTrue(data["custom_path"]["ok"])
        self.assertEqual(
            os.path.normcase(os.path.normpath(data["custom_path"]["path"])),
            os.path.normcase(os.path.normpath(data["custom_path"]["expected"])),
        )
        self.assertTrue(data["custom_path"]["path"].endswith("voice-tool.exe"))
        self.assertEqual(data["custom_path"]["view_path"], data["custom_path"]["path"])
        self.assertEqual(data["custom_path"]["field_text"], data["custom_path"]["path"])

        # The provider-specific controls stay available and operable across
        # every provider state.
        for provider, state in data["provider_states"].items():
            self.assertTrue(state["controls_visible"], provider)
            self.assertTrue(state["controls_enabled"], provider)
        self.assertTrue(data["provider_states"]["sogou"]["auto_launch"])

        # Capture errors surface to the user; a capture error while the capture
        # is still owned does not tear the capture down.
        inactive = data["inactive_capture_error"]
        self.assertEqual(inactive["message"], "模拟启动失败")
        self.assertFalse(inactive["ok"])
        self.assertEqual(inactive["field"], "hotkey")
        self.assertEqual(inactive["facet"], "模拟启动失败")
        self.assertFalse(inactive["capture_active"])
        active = data["active_capture_error"]
        self.assertEqual(active["message"], "模拟停止前异常")
        self.assertEqual(active["facet"], "模拟停止前异常")
        self.assertTrue(active["capture_retained"])

        # An in-progress capture must not block other voice-program actions.
        self.assertTrue(data["hotkey_other_action"]["action_completed"])
        self.assertTrue(data["hotkey_other_action"]["validation_ok"])

        # Layout: the hotkey row keeps its controls side by side without
        # overlap, and every control stays inside the window.
        hotkey_label = data["managed"]["hotkeyLabel"]["geometry"]
        start_button = data["managed"]["settingsStartHotkeyCaptureButton"]["geometry"]
        stop_button = data["managed"]["settingsStopHotkeyCaptureButton"]["geometry"]
        self.assertLessEqual(hotkey_label["right"], start_button["x"] + 1)
        self.assertLessEqual(start_button["right"], stop_button["x"] + 1)
        self.assertGreaterEqual(start_button["x"], hotkey_label["x"])
        for item in data["managed"].values():
            bounds = item["geometry"]
            self.assertGreater(bounds["width"], 0)
            self.assertGreater(bounds["height"], 0)
            self.assertGreaterEqual(bounds["x"], 0)
            self.assertGreaterEqual(bounds["y"], 0)
            self.assertLessEqual(bounds["right"], data["window_width"])
            self.assertLessEqual(bounds["bottom"], data["window_height"])


if __name__ == "__main__":
    unittest.main()
