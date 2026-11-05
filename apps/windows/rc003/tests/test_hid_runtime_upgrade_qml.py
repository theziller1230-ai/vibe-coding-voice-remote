"""Exercise the real device surface with isolated HID upgrade states."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.test_voice_program_qml import _PROBE as _VOICE_PAGE_PROBE


# Reuse the existing offscreen application setup and its hardware/host stubs.
# Run only setup, before that probe begins its page interactions.
_SETUP = _VOICE_PAGE_PROBE.split('page_stack = find(window, "pageStack")', 1)[0]
_SETUP = _SETUP.replace(
    "engine = QQmlApplicationEngine()",
    "m.windows_diagnostics.run_diagnostics = lambda **_kwargs: None\n"
    "from pathlib import Path\n"
    "from PySide6.QtGui import QFontDatabase\n"
    "font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'\n"
    "if font_path.is_file():\n"
    "    QFontDatabase.addApplicationFont(str(font_path))\n"
    "engine = QQmlApplicationEngine()",
)
_PROBE = _SETUP + r'''
from ovb_rc003 import bridge_runtime_status, frida_compat, hid_elevation_windows
from unittest import mock

window.setProperty("width", 900)
window.setProperty("height", 1400)
_viewmodels.AppViewModel.currentPage = 2
find(window, "settingsDeviceSection").setProperty("folded", False)
render(window, app)
wait_for_voice_hotkey_idle(controller, app)
deadline = time.monotonic() + 3.0
while diagnostics.isRefreshing and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert not diagnostics.isRefreshing
controller._config["remote_selection"] = {"schema": 1, "active": "a" * 64,
    "devices": [{"key": "a" * 64, "profile": "xiaomi-rc003"}]}
controller.remoteSelectionChanged.emit()
controller._bridge_running = True
controller.bridgeRunningChanged.emit()
controller._set_bridge_connected(True)
controller._set_bridge_connection_state("connected")
root_path = m.config.config_root()

device_vm = _viewmodels.DeviceViewModel
app_vm = _viewmodels.AppViewModel

def input_state(hid_state, raw_state="ready"):
    bridge_runtime_status.publish_status(
        root_path, bridge_runtime_status.BridgeConnectionState.CONNECTED,
        pid=os.getpid(), raw_input_state=raw_state, hid_tap_state=hid_state,
        voice_key_physicalizer_state="ready",
    )
    status = bridge_runtime_status.read_status(root_path)
    controller._set_bridge_input_states(status)
    controller._sync_bridge_connection_status(True)
    deadline = time.monotonic() + 3.0
    while diagnostics.isRefreshing and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not diagnostics.isRefreshing
    assert not controller._runtime_status_requires_restart(status)
    return status

def detail():
    return str(device_vm.connectionCard.detail)

def click(item):
    point = item.mapToScene(
        QPointF(item.property("width") / 2, item.property("height") / 2)
    ).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    render(window, app)

bridge_button = find(window, "settingsBridgeActionButton")
assert bridge_button is not None

# --- Host reload required: the receiver state is visible on the device
# surface and the required computer restart is never downgraded to a
# service restart.
status = input_state(frida_compat.HidTapState.RESTART_REQUIRED.value)
assert controller.hidTapState == "restart_required"
assert not controller.buttonReceiverUsable
assert "Windows 原始按键可用；自定义按键映射正在检查" in detail()
assert app_vm.bridgeStateLabel == "已连接"
# A stale restart-service recommendation must not hide the required host reload.
controller._set_bridge_restart_recommended(True)
assert "Windows 原始按键可用；自定义按键映射正在检查" in detail()
assert not controller._runtime_status_requires_restart(status)
controller._set_bridge_restart_recommended(False)

# --- Source consent failures remain actionable without recommending a restart.
for state in ("authorization_cancelled", "authorization_failed"):
    status = input_state(state)
    controller._set_bridge_restart_recommended(True)
    assert "按键授权未完成；请在设备页点击“重新授权”" in detail()
    assert not controller._runtime_status_requires_restart(status)
    status = bridge_runtime_status.read_status(root_path)
    controller._update_bridge_restart_recommendation(status, schedule_recovery=True)
    assert not controller.bridgeRestartRecommended
    assert "重新授权" in controller._describe_runtime_status(status)
    assert bridge_button.property("visible") and bridge_button.property("enabled")
    assert str(bridge_button.property("text")) == str(device_vm.connectionCard.actionLabel)
    with mock.patch.object(controller, "_begin_bridge_restart") as restart:
        click(bridge_button)
        assert restart.call_count == 1
        restart.assert_called_once_with(automatic=False)
controller._set_bridge_restart_recommended(False)
input_state(frida_compat.HidTapState.RESTART_REQUIRED.value)

# --- Ordinary-permission upgrades surface through the maintenance HID
# helper item and its repair affordance.
maintenance_vm = _viewmodels.MaintenanceViewModel
def helper_item():
    return {row.contract.id: row.contract for row in maintenance_vm.items}["helper"]
controller._hid_helper_frozen_distribution = True
controller._hid_helper_process_elevated = False
controller._hid_helper_portable_distribution = False
controller._hid_helper_can_self_elevate = True
controller._hid_helper_state = hid_elevation_windows.HidHelperState(
    False, "protected_helper_outdated"
)
controller.hidHelperStateChanged.emit()
assert controller.hidHelperRepairVisible
assert helper_item().status == "failed"
assert helper_item().fixLabel == "修复"
assert helper_item().detail == "改键已停用"
controller._hid_helper_portable_distribution = True
controller.hidHelperStateChanged.emit()
assert controller.hidHelperSetupRequired
assert helper_item().status == "failed"
controller._hid_helper_state = hid_elevation_windows.HidHelperState(True, "ready")
controller.hidHelperStateChanged.emit()
assert not controller.hidHelperIssueVisible
assert helper_item().status == "done"
# The tap state still governs the receiver guidance.
assert "Windows 原始按键可用；自定义按键映射正在检查" in detail()

# --- An unresolved source stays explicit without offering service/computer restart.
status = input_state(frida_compat.HidTapState.SHARED_HOST.value)
assert controller.hidTapState == "selected_device_shared_host"
assert not controller._runtime_status_requires_restart(status)
assert not controller.buttonReceiverUsable
assert "Windows 原始按键可用；自定义按键映射正在检查" in detail()

# --- After a compatible component has loaded, first input and normal
# operation retain the existing UI states.
status = input_state(frida_compat.HidTapState.UNAVAILABLE.value)
assert "Windows 原始按键可用；自定义按键映射已停用" in detail()
assert not controller._runtime_status_requires_restart(status)
assert not controller.buttonReceiverUsable
assert app_vm.bridgeStateLabel == "已连接"
# A stale restart-service recommendation must not replace the state guidance.
controller._set_bridge_restart_recommended(True)
assert "Windows 原始按键可用；自定义按键映射已停用" in detail()
controller._set_bridge_restart_recommended(False)

# --- A transient interception failure still offers the existing service restart.
input_state(frida_compat.HidTapState.UNHEALTHY.value)
assert "Windows 原始按键可用；自定义按键映射已停用" in detail()
assert bridge_button.property("visible") and bridge_button.property("enabled")
assert str(bridge_button.property("text")) == "连接 / 重连"
assert str(bridge_button.property("text")) == str(device_vm.connectionCard.actionLabel)
with mock.patch.object(controller, "_begin_bridge_restart") as restart:
    click(bridge_button)
    restart.assert_called_once_with(automatic=False)

input_state(frida_compat.HidTapState.ATTACHED_WAITING_IO.value)
assert controller.buttonReceiverUsable
assert "两个按键通道正常" in detail()
input_state(frida_compat.HidTapState.READY.value)
assert controller.buttonReceiverUsable
assert "两个按键通道正常" in detail()

# --- Chromecast does not consume the Xiaomi component or its stale failure state.
controller._config["remote_selection"]["devices"][0]["profile"] = "chromecast-remote"
controller.remoteSelectionChanged.emit()
assert not controller.isRc003Device
bridge_runtime_status.publish_status(
    root_path, bridge_runtime_status.BridgeConnectionState.CONNECTED,
    pid=os.getpid(), raw_input_state="chromecast_ready",
    hid_tap_state=frida_compat.HidTapState.UNAVAILABLE.value,
)
status = bridge_runtime_status.read_status(root_path)
controller._set_bridge_input_states(status)
controller._sync_bridge_connection_status(True)
assert controller.buttonReceiverUsable
assert "普通按键接收正常" in detail()
assert not controller._runtime_status_requires_restart(status)
controller._config["remote_selection"]["devices"][0]["profile"] = "xiaomi-rc003"
controller.remoteSelectionChanged.emit()

input_state(frida_compat.HidTapState.RESTART_REQUIRED.value)
render(window, app)
screenshot_dir = os.environ.get("HID_UPGRADE_SCREENSHOT_DIR")
if screenshot_dir:
    _viewmodels.AppViewModel.currentPage = 0
    render(window, app)
    window.grabWindow().save(os.path.join(screenshot_dir, "hid-upgrade-home.png"))
    _viewmodels.AppViewModel.currentPage = 2
    render(window, app)
    window.grabWindow().save(os.path.join(screenshot_dir, "hid-upgrade-device.png"))
print(json.dumps({"warnings": [str(warning) for warning in warnings]}))
window.hide()
m._shutdown_diagnostics_workers()
'''



class HidRuntimeUpgradeQmlTests(unittest.TestCase):
    def test_upgrade_and_host_reload_states_in_real_pages(self):
        with tempfile.TemporaryDirectory() as local_app_data:
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["LOCALAPPDATA"] = local_app_data
            result = subprocess.run(
                [sys.executable, "-B", "-c", _PROBE],
                env=env, capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["warnings"], [])


if __name__ == "__main__":
    unittest.main()
