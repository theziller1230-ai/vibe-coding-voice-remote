"""Real QML selection/path/startup workflow; temporary config, no host launch."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.test_hid_runtime_upgrade_qml import _SETUP


_PROBE = _SETUP.replace('QQuickStyle.setStyle("Basic")',
                       'QQuickStyle.setStyle(os.environ.get("VOICE_SELECTION_STYLE", "Basic"))') + r'''
from PySide6.QtCore import QMetaObject, Q_ARG
from unittest import mock

# The retired shell's bridgeStatusRefreshTimer is gone; the new heartbeat
# (AppViewModel.tick) only refreshes bridge state and the duplicate-launch
# restore pump - none of which this probe asserts - so it keeps running, as
# in the rest of the voice-probe family.
window.setProperty("width", 640)
window.setProperty("height", 480)
_viewmodels.AppViewModel.currentPage = 2
find(window, "settingsVoiceSection").setProperty("folded", False)
render(window, app)

voice_vm = _viewmodels.VoiceViewModel
section = find(window, "settingsVoiceSection")
pick_button = find(window, "settingsPickCustomProgramButton")
custom_path_field = pick_button.parent().children()[0]

def items_with(root_item, predicate):
    found, stack = [], [root_item]
    while stack:
        item = stack.pop(0)
        if predicate(item):
            found.append(item)
        children = list(item.children())
        child_items = getattr(item, 'childItems', None)
        if callable(child_items):
            children.extend(child for child in child_items() if child not in children)
        stack.extend(children)
    return found

def rows_with(root_item, name):
    return items_with(root_item, lambda item: item.metaObject().indexOfProperty(name) >= 0)

def program_rows():
    return [row.contract for row in voice_vm.voicePrograms]

def marking():
    return [row.selected for row in program_rows()]

# ---- 语音程序选择行：形状、占位行、越界防线 ----
rows = program_rows()
assert [row.id for row in rows] == ["0", "1", "2", "3", "4"]
assert rows[0].label == "请选择语音程序"
assert marking() == [True, False, False, False, False]
# The retired combo ignored an out-of-range activation; the row list must
# leave the selection alone for an id outside it the same way.
voice_vm.setVoiceProgram("99")
wait_for_voice_hotkey_idle(controller, app)
assert controller._voice_program_settings["provider"] == "none"
assert marking() == [True, False, False, False, False]

# ---- 每一行都必须真正切换到对应语音程序（含 Chatterfly），选中标记跟随 ----
for row_index, provider_id in ((1, "sogou"), (2, "wetype"), (3, "doubao_ime"), (4, "chatterfly")):
    voice_vm.setVoiceProgram(str(row_index))
    wait_for_voice_hotkey_idle(controller, app)
    render(window, app)
    assert controller._voice_program_settings["provider"] == provider_id
    assert marking() == [i == row_index for i in range(5)], (
        provider_id, [(row.id, row.selected) for row in program_rows()])

# First selection of a launchable program defaults 自动运行服务 on (old switch).
voice_vm.setVoiceProgram("1")
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
assert controller._voice_program_settings["provider"] == "sogou"
assert marking() == [False, True, False, False, False]
assert voice_vm.autoLaunch is True

# ---- 占位行不能反选（老组合框的旧自定义项同样不可新选） ----
voice_vm.setVoiceProgram("0")
wait_for_voice_hotkey_idle(controller, app)
assert controller._voice_program_settings["provider"] == "sogou"
assert marking() == [False, True, False, False, False]

# ---- 旧自定义配置：保留、无行可选、自启偏好按程序记忆 ----
def load_legacy_custom():
    saved = dict(controller._config)
    saved["voice_program"] = dict(controller._voice_program_settings, provider="custom")
    m.config.save_config(m.config.config_path(m.config.config_root()), saved)
    before = m.config.config_path(m.config.config_root()).read_bytes()
    controller._config = m.config.load_config(m.config.config_path(m.config.config_root()))
    controller._replace_voice_program_settings(controller._config["voice_program"])
    wait_for_voice_hotkey_idle(controller, app)
    render(window, app)
    return before

before = load_legacy_custom()
assert controller._voice_program_settings["provider"] == "custom"
assert marking() == [False, False, False, False, False]
assert voice_vm.autoLaunch is False
assert m.config.config_path(m.config.config_root()).read_bytes() == before

# The auto-start switch round-trips its preference (retired switch toggling).
voice_vm.setAutoLaunch(True)
assert voice_vm.autoLaunch is True
assert controller.voiceProgramLaunchOnBridgeStart is True
voice_vm.setAutoLaunch(False)
assert voice_vm.autoLaunch is False
assert controller.voiceProgramLaunchOnBridgeStart is False

# ---- 自定义程序路径：选择与录入回路 ----
path = m.config.config_root() / "voice test.exe"
path.parent.mkdir(parents=True, exist_ok=True)
path.touch()
picked = voice_vm.pickCustomProgramPath(QUrl.fromLocalFile(str(path)).toString())
assert picked.ok is True
assert os.path.normcase(os.path.normpath(voice_vm.customProgramPath)) == os.path.normcase(os.path.normpath(str(path)))
assert custom_path_field.property("text") == voice_vm.customProgramPath
# A typed existing program path is stored exactly (unquoted manual entry).
typed = m.config.config_root() / "voice test2.exe"
typed.touch()
custom_path_field.setProperty("text", str(typed))
assert QMetaObject.invokeMethod(custom_path_field, "editingFinished")
render(window, app)
typed_stored = voice_vm.customProgramPath
assert os.path.normcase(os.path.normpath(typed_stored)) == os.path.normcase(os.path.normpath(str(typed)))
# Typed entries validate through a file URL (the retired field stripped
# quotes/arguments silently and kept the bare executable): a quoted entry is
# refused with the exact message and leaves the stored path alone.
custom_path_field.setProperty("text", '"' + str(path) + '"')
assert QMetaObject.invokeMethod(custom_path_field, "editingFinished")
render(window, app)
assert find(window, "settingsPanel").property("feedbackText") == "请选择本地程序文件。"
assert voice_vm.customProgramPath == typed_stored
# An entry with arguments is not a real program file: the save refuses it
# with the exact invalid-path message and preserves the stored path.
custom_path_field.setProperty("text", typed_stored + " --argument")
assert QMetaObject.invokeMethod(custom_path_field, "editingFinished")
render(window, app)
assert voice_vm.customProgramPath == typed_stored
assert controller.errorMessage == "自定义程序路径无效，请选择现有的 .exe 或有效的 .lnk。"

# ---- 每档语音程序各自记住自启偏好；越界防线在真实选择后依旧生效 ----
voice_vm.setVoiceProgram("1")
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
assert controller._voice_program_settings["provider"] == "sogou"
assert voice_vm.autoLaunch is True
voice_vm.setVoiceProgram("99")
wait_for_voice_hotkey_idle(controller, app)
assert controller._voice_program_settings["provider"] == "sogou"
assert marking() == [False, True, False, False, False]
load_legacy_custom()
assert voice_vm.autoLaunch is False
assert marking() == [False, False, False, False, False]

# ---- 录音模式：RC003 只支持按住型；谷歌档切换并完整回路 ----
# The retired rows showed a read-only 仅支持按住型 row for RC003 and an
# editor for Chromecast; the shared selector keeps the data rule: while the
# RC003 profile is active a toggle-mode request is refused unchanged.
assert controller.isRc003Device is True
assert controller.remoteRecordingModeIndex == 0
assert voice_vm.recordingMode == "按住说话"
voice_vm.setRecordingMode("按一次开·再按一次关")
wait_for_voice_hotkey_idle(controller, app)
assert controller.remoteRecordingModeIndex == 0
assert voice_vm.recordingMode == "按住说话"

controller._config["remote_selection"] = {"schema": 1, "active": "a" * 64,
    "devices": [{"key": "a" * 64, "profile": "chromecast-remote"}]}
controller.remoteSelectionChanged.emit()
controller.selectedDeviceChanged.emit()
render(window, app)
assert controller.isRc003Device is False
voice_vm.setRecordingMode("按一次开·再按一次关")
wait_for_voice_hotkey_idle(controller, app)
render(window, app)
assert controller.remoteRecordingModeIndex == 1
assert voice_vm.recordingMode == "按一次开·再按一次关"
voice_vm.setRecordingMode("按住说话")
wait_for_voice_hotkey_idle(controller, app)
assert controller.remoteRecordingModeIndex == 0
assert voice_vm.recordingMode == "按住说话"

# ---- 回到 RC003：渲染不得写配置/重启服务，也不得抢焦点 ----
config_path = m.config.config_path(m.config.config_root())
config_before = config_path.read_bytes()
controller._config["remote_selection"]["devices"][0]["profile"] = "xiaomi-rc003"
controller.remoteSelectionChanged.emit()
controller.selectedDeviceChanged.emit()
with mock.patch.object(m.config, "save_config_and_load", wraps=m.config.save_config_and_load) as save, \
        mock.patch.object(controller, "_start_bridge_process") as restart:
    render(window, app)
    assert controller.isRc003Device is True
    assert controller.remoteRecordingModeIndex == 0
    assert voice_vm.recordingMode == "按住说话"
    mode_selectors = items_with(section, lambda item: item.metaObject().indexOfProperty("currentIndex") >= 0
                                and "SelectionComboBox" in str(item.metaObject().className()))
    assert mode_selectors, "recording-mode selector missing"
    assert not mode_selectors[0].property("activeFocus")
    save.assert_not_called()
    restart.assert_not_called()
assert config_path.read_bytes() == config_before

# ---- 640x480 最小窗口下语音面不横向溢出（旧溢出防线的后继） ----
window.setProperty("width", 640)
window.setProperty("height", 480)
render(window, app)
named = [custom_path_field] + [find(window, name) for name in (
    "settingsPickCustomProgramButton", "settingsLaunchVoiceProgramButton",
    "settingsOpenVoiceProgramSettingsButton", "settingsStartHotkeyCaptureButton",
    "settingsStopHotkeyCaptureButton", "settingsTestAudioButton",
    "settingsInstallVirtualCableButton", "settingsSetRecordingLimitButton")]
overflow_items = (named + rows_with(section, "rowSelected")
                  + items_with(section, lambda item: "CompactSwitch" in str(item.metaObject().className())))
for item in overflow_items:
    bounds = geometry(item)
    assert bounds["x"] >= 0 and bounds["right"] <= 640, (str(item.metaObject().className()), bounds)

image_dir = os.environ.get("VOICE_SELECTION_SCREENSHOTS")
if image_dir:
    image_path = Path(image_dir)
    image_path.mkdir(parents=True, exist_ok=True)
    window.grabWindow().save(str(image_path / (os.environ["VOICE_SELECTION_STYLE"] + ".png")))
print(json.dumps({"warnings": [str(w) for w in warnings]}))
window.hide()
m._shutdown_diagnostics_workers()
'''


class VoiceProgramSelectionQmlTests(unittest.TestCase):
    def test_real_selection_and_custom_path_controls(self):
        for style in ("Basic", "Fusion", "FluentWinUI3"):
            with self.subTest(style=style), tempfile.TemporaryDirectory() as root:
                env = dict(os.environ, LOCALAPPDATA=root, QT_QPA_PLATFORM="offscreen",
                           QT_SCALE_FACTOR="1.5", VOICE_SELECTION_STYLE=style)
                result = subprocess.run([sys.executable, "-B", "-c", _PROBE],
                                        env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])["warnings"], [])
