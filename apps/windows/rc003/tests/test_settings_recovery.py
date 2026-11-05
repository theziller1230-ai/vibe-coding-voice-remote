"""Unreadable settings may block execution/saves, never the diagnostic shell."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from ovb_rc003 import config, log_export, qt_settings_app, remote_selection
from tests import test_qt_settings_app as _qt_fixture


class WindowSettingsRecoveryTests(unittest.TestCase):
    def test_normal_old_settings_and_missing_files_keep_strict_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings, bindings, issues = config.load_window_settings(root)
            self.assertFalse(issues)
            self.assertNotIn(config.RUNTIME_READ_ONLY_KEY, settings)
            settings["voice_hotkey"] = "rctrl+l"
            settings["schema_version"] = 16
            (root / "config.json").write_text(json.dumps(settings), encoding="utf-8")
            (root / "key_bindings.json").write_text(json.dumps(bindings), encoding="utf-8")
            loaded, mapped, issues = config.load_window_settings(root)
            self.assertFalse(issues)
            self.assertEqual(loaded, config.load_config(root / "config.json"))
            self.assertEqual(mapped, config.load_key_bindings(root / "key_bindings.json"))

    def test_config_failures_keep_original_bytes_and_block_all_preview_saves(self):
        cases = [
            b'{"schema_version":', b'[]', b'\xff\xfe\x80',
            b'{"remote_recording_limit_seconds":"120","gain_db":4}',
            b'{"remote_recording_mode":"invalid"}',
            json.dumps({"remote_selection": {"schema": 1, "devices": [], "active": "a" * 64}}).encode(),
            json.dumps({"remote_settings": {"schema": 1, "records": {
                "b" * 64: {"unexpected_field": True}}, "unassigned": {}}}).encode(),
            b'{"address":"private-sentinel"}',
        ]
        for original in cases:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cfg, keys = root / "config.json", root / "key_bindings.json"
                cfg.write_bytes(original)
                saved_mapping = config.default_key_bindings()
                saved_mapping["bindings"]["ok"] = {"kind": "key_combo", "keys": ["f8"]}
                keys.write_text(json.dumps(saved_mapping), encoding="utf-8")
                original_keys = keys.read_bytes()
                settings, bindings, issues = config.load_window_settings(root)
                self.assertEqual([i.filename for i in issues], ["config.json"])
                self.assertTrue(settings[config.RUNTIME_READ_ONLY_KEY])
                self.assertEqual(bindings["bindings"]["ok"], saved_mapping["bindings"]["ok"])
                for save in (
                    lambda: config.save_config(cfg, settings),
                    lambda: config.save_config_and_load(cfg, settings),
                    lambda: config.save_key_bindings(keys, bindings),
                    lambda: config.save_settings_pair(cfg, settings, keys, bindings),
                    lambda: config.save_settings_pair(cfg, config.default_config(), keys, bindings),
                ):
                    with self.assertRaises(config.ConfigReadOnlyError):
                        save()
                self.assertEqual(cfg.read_bytes(), original)
                self.assertEqual(keys.read_bytes(), original_keys)
                with self.assertRaises(config._SETTINGS_READ_ERRORS):
                    config.load_config(cfg)
                self.assertNotIn("private-sentinel", repr(issues))

    def test_bad_recording_limit_preview_preserves_selection_and_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = "a" * 64
            document = {"remote_selection": {"schema": 1, "active": key,
                "devices": [{"key": key, "profile": "chromecast-remote"}]},
                "remote_settings": {"schema": 1, "records": {key: {
                    "remote_recording_limit_seconds": "120", "gain_db": 4,
                    "output_endpoint_name": "remembered endpoint"}}, "unassigned": {}}}
            (root / "config.json").write_text(json.dumps(document), encoding="utf-8")
            settings, _, issues = config.load_window_settings(root)
            self.assertTrue(issues)
            self.assertEqual(remote_selection.active_key(settings), key)
            self.assertEqual(settings["gain_db"], 4)
            self.assertEqual(settings["output_endpoint_name"], "remembered endpoint")

    def test_bad_bindings_keep_good_config_and_do_not_show_default_actions_as_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config.save_config(root / "config.json", dict(config.default_config(), gain_db=4))
            original = (root / "config.json").read_bytes()
            (root / "key_bindings.json").write_text('{"bindings":', encoding="utf-8")
            settings, bindings, issues = config.load_window_settings(root)
            self.assertEqual([i.filename for i in issues], ["key_bindings.json"])
            self.assertEqual(settings["gain_db"], 4)
            self.assertEqual(bindings["bindings"], {})
            self.assertEqual((root / "config.json").read_bytes(), original)

    def test_bad_unused_device_does_not_hide_valid_selected_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = "a" * 64
            document = {"remote_selection": {"schema": 1, "active": key,
                "devices": [{"key": key, "profile": "chromecast-remote"}]},
                "remote_settings": {"schema": 1, "records": {
                    key: {"gain_db": 4}, "b" * 64: {"unexpected_field": True}}, "unassigned": {}}}
            original = json.dumps(document).encode()
            (root / "config.json").write_bytes(original)
            settings, _, issues = config.load_window_settings(root)
            self.assertTrue(issues)
            self.assertEqual(settings["gain_db"], 4)
            self.assertEqual((root / "config.json").read_bytes(), original)

    def test_unreadable_files_and_independent_failures_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text('{', encoding="utf-8")
            (root / "key_bindings.json").write_text('[', encoding="utf-8")
            _, _, issues = config.load_window_settings(root)
            self.assertEqual([i.filename for i in issues], ["config.json", "key_bindings.json"])
            with mock.patch.object(config, "_read_settings_document", side_effect=PermissionError):
                _, _, issues = config.load_window_settings(root)
                self.assertEqual(issues[0].error_type, "PermissionError")

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing violation')
    def test_windows_locked_config_opens_preview_without_changing_the_file(self):
        import ctypes
        from ctypes import wintypes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config.json'
            original = b'{"gain_db":4}'
            path.write_bytes(original)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            try:
                settings, _, issues = config.load_window_settings(root)
                self.assertTrue(settings[config.RUNTIME_READ_ONLY_KEY])
                self.assertEqual(issues[0].error_type, 'PermissionError')
            finally:
                kernel.CloseHandle(handle)
            self.assertEqual(path.read_bytes(), original)


class SettingsControllerRecoveryTests(unittest.TestCase):
    setUp = _qt_fixture.SettingsControllerTests.setUp
    tearDown = _qt_fixture.SettingsControllerTests.tearDown
    _new_controller = _qt_fixture.SettingsControllerTests._new_controller

    def _broken_controller(self):
        root = config.config_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.json").write_text('{"remote_recording_limit_seconds":"120"}', encoding="utf-8")
        config.save_key_bindings(root / "key_bindings.json", config.default_key_bindings())
        # Save bindings first with a syntactically valid config; load still fails
        # later on its recording limit and must leave both documents untouched.
        model = self.Model()
        controller = self._new_controller(model, start_hidden=True, start_bridge=True,
                                          background_task_runner=lambda target, name: None)
        return root, controller, model

    def test_readonly_blocks_automatic_and_manual_side_effects_and_exports_reason(self):
        root, controller, model = self._broken_controller()
        before = {p.name: p.read_bytes() for p in root.glob("*.json")}
        self.assertTrue(controller.configurationReadOnly)
        self.assertFalse(controller.startHidden)
        self.assertFalse(controller.settingsDirty)
        self.assertIn("最长录音时间", controller.configurationError)
        with mock.patch.object(qt_settings_app.bridge_launcher, "start_bridge_launch") as start, \
             mock.patch.object(qt_settings_app.startup_windows, "set_startup_enabled") as startup, \
             mock.patch.object(controller, "_start_background_task") as work:
            controller.startBridgeOnApplicationStart()
            controller.startBridge()
            controller._start_bridge_process()
            controller._begin_bridge_restart(automatic=True)
            controller.reconnectBridgeNow()
            controller.loadVoiceHotkeyFromProvider()
            controller.refreshVoiceHotkeyFromProvider()
            controller.setLaunchAtLogin(True)
            controller._queue_mapping_auto_save()
            controller.restoreMappingDefaults()
            controller.restoreDefaults()
            self.assertFalse(controller.saveSettings())
            self.assertFalse(controller._save_mapping())
            self.assertFalse(controller._persist_desktop_behavior("close_behavior", "quit"))
            self.assertFalse(controller._save_remote_selection(remote_selection.empty_selection()))
            self.assertFalse(controller._record_hid_helper_setup_prompted())
            self.assertFalse(controller.mappingPresetAction("copy", "", "test")["ok"])
            start.assert_not_called(); startup.assert_not_called(); work.assert_not_called()
        self.assertIsNone(controller._voice_hotkey_load_pending)
        self.assertFalse(controller._mapping_auto_save_scheduled)
        diagnostics = qt_settings_app._load_qt_classes()['DiagnosticsController'](controller, root, auto_refresh=False)
        diagnostics.refreshDiagnostics()
        diagnostics.testVbCableChannel()
        self.assertFalse(diagnostics.isRefreshing)
        self.assertFalse(diagnostics.vbCableTestRunning)
        self.assertIn('配置读取异常', diagnostics.diagnosticsErrorMessage)
        model.setActionTextAt(model.index_of("ok"), "f9")
        self.assertFalse(controller.mappingDirty)
        result = log_export.export_logs(root / "evidence.zip", root=root)
        self.assertEqual(result.outcome, "exported")
        with zipfile.ZipFile(result.path) as archive:
            contents = b"\n".join(archive.read(name) for name in archive.namelist())
            self.assertIn(b"settings load failed: file=config.json error_type=ConfigFormatError", contents)
            self.assertNotIn("config.json", archive.namelist())
            self.assertNotIn("key_bindings.json", archive.namelist())
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.glob("*.json")})

    def test_logging_failure_does_not_prevent_open_and_reopen_after_repair_is_normal(self):
        with mock.patch.object(qt_settings_app.logging_setup, "get_logger", side_effect=OSError):
            root, controller, _ = self._broken_controller()
        self.assertTrue(controller.configurationReadOnly)
        self.assertIn("未能写入日志", controller.configurationError)
        original = json.loads((root / "config.json").read_text(encoding="utf-8"))
        original["remote_recording_limit_seconds"] = 120
        (root / "config.json").write_text(json.dumps(original), encoding="utf-8")
        reopened = self._new_controller(self.Model(), background_task_runner=lambda target, name: None)
        self.assertFalse(reopened.configurationReadOnly)
        self.assertEqual(reopened.configurationError, "")

    def test_actual_unwritable_log_location_does_not_block_the_window(self):
        root = config.config_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / 'logs').write_text('not a directory', encoding='utf-8')
        _, controller, _ = self._broken_controller()
        self.assertTrue(controller.configurationReadOnly)
        self.assertIn('未能', controller.configurationError)


_RECOVERY_WINDOW_PROBE = r'''
import json, sys
from pathlib import Path
from contextlib import ExitStack
from unittest import mock
from PySide6.QtCore import QObject, QTimer
from ovb_rc003 import config, qt_settings_app as m
from tests import test_qt_settings_app as fixtures
classes = m._load_qt_classes()
classes['QQuickStyle'].setStyle('FluentWinUI3')
app = classes['QGuiApplication']([])
fixture = fixtures.SettingsControllerTests(); fixture.setUp()
root = config.config_root(); root.mkdir(parents=True, exist_ok=True)
kind = sys.argv[1]
if kind == 'config':
    (root / 'config.json').write_text('{', encoding='utf-8')
else:
    config.save_config(root / 'config.json', dict(config.default_config(), launch_bridge_on_app_start=True))
    (root / 'key_bindings.json').write_text('[', encoding='utf-8')
originals = {p.name: p.read_bytes() for p in root.glob('*.json')}
controllers, engines, warnings, result = [], [], [], {}
Controller = classes['SettingsController']
original_init, Engine = Controller.__init__, classes['QQmlApplicationEngine']
def init(self, *args, **kwargs):
    kwargs['background_task_runner'] = lambda target, name: target()
    original_init(self, *args, **kwargs)
    controllers.append(self)
    fixture._controllers.append(self)
def engine_factory():
    engine = Engine(); engines.append(engine)
    engine.warnings.connect(lambda values: warnings.extend(str(value) for value in values))
    return engine
from ovb_rc003.presentation import registry as presentation_registry
held_viewmodels = {}
real_register = presentation_registry.register
def capture_register(*args, **kwargs):
    held_viewmodels['set'] = real_register(*args, **kwargs)
    return held_viewmodels['set']
def class_items(root_item, class_part):
    found, stack = [], [root_item]
    while stack:
        item = stack.pop(0)
        if class_part in str(item.metaObject().className()):
            found.append(item)
        children = list(item.children())
        child_items = getattr(item, 'childItems', None)
        if callable(child_items):
            children.extend(child for child in child_items() if child not in children)
        stack.extend(children)
    return found
def verify():
    try:
        controller = controllers[0]
        viewmodels = held_viewmodels['set']
        window = engines[0].rootObjects()[0]
        maintenance = viewmodels.MaintenanceViewModel
        result['readonly'] = controller.configurationReadOnly
        result['visible'] = window.isVisible()
        # The settings page owns every affordance checked below; open it the
        # way the user must (the old shell's controls all lived on its default
        # page and were visible from the start).
        viewmodels.AppViewModel.currentPage = 2
        app.processEvents()
        # The retired configurationWarning banner rendered
        # controller.configurationError whenever the settings were unreadable.
        # The surviving report paths keep that exact text reachable: every
        # preference toggle comes up disabled and the typed feedback seam
        # (the message SettingsPanel renders on a refused toggle) carries it.
        preferences = [row.contract for row in maintenance.preferences]
        result['save_disabled'] = len(preferences) == 4 and all(
            row.enabled is False for row in preferences)
        verdict = maintenance.setPreference('auto_start_bridge', True)
        result['config_error_reported'] = (
            verdict.ok is False
            and verdict.message == controller.configurationError
            and bool(controller.configurationError))
        # Unreadable settings never disable the diagnostic affordances.
        result['update_enabled'] = bool(
            window.findChild(QObject, 'settingsUpdateActionButton').property('enabled'))
        # The 维护 section starts folded; unfold it the way the user must.
        window.findChild(QObject, 'settingsMaintenanceSection').setProperty('folded', False)
        app.processEvents()
        items = {row.contract.id: row.contract for row in maintenance.items}
        section = window.findChild(QObject, 'settingsMaintenanceSection')
        logs_rows = [row for row in class_items(section, 'DiagnosticResultRow')
                     if row.property('titleText') == items['logs'].title]
        logs_button = class_items(logs_rows[0].parent(), 'CompactButton')[0]
        result['export_enabled'] = (
            bool(logs_button.property('enabled'))
            and bool(logs_button.property('visible')))
        # The log export completes even though the configuration is unreadable.
        default_export = classes['QUrl'](controller.logExportDefaultFile()).toLocalFile()
        maintenance.run('logs')
        result['exported'] = Path(default_export).is_file()
        # Remote selection is refused while readonly: the choice rows stay
        # offered, but the dispatch must not move the selection (the retired
        # 选择设备 button disabled itself in this state).
        controller._remote_devices = [{'key': 'a' * 64, 'profile': 'xiaomi-rc003'}]
        controller._remote_scan_valid = True
        choices_before = list(controller.remoteDeviceChoices)
        viewmodels.DeviceViewModel.useRemote('a' * 64)
        result['select_disabled'] = list(controller.remoteDeviceChoices) == choices_before
        # All three pages stay reachable and follow the page state.
        page_stack = window.findChild(QObject, 'pageStack')
        pages = []
        for index in (1, 2, 0):
            viewmodels.AppViewModel.currentPage = index
            app.processEvents()
            pages.append(page_stack.property('currentIndex'))
        result['pages_ok'] = pages == [1, 2, 0]
        if len(sys.argv) > 2:
            window.grabWindow().save(sys.argv[2])
        controller.requestApplicationExit()
    except Exception as exc:
        result['error'] = repr(exc); app.exit(1)
with ExitStack() as patches:
    patches.enter_context(mock.patch.object(Controller, '__init__', init))
    patches.enter_context(mock.patch.object(Controller, '_request_endpoint_options_refresh'))
    patches.enter_context(mock.patch.object(Controller, '_request_voice_program_status_refresh'))
    patches.enter_context(mock.patch.object(presentation_registry, 'register', capture_register))
    # The production shell now runs the startup update check immediately
    # (AppViewModel.startupSettled); the retired shell waited five seconds and
    # this probe always exited first. Take the daily-claim rejection path so
    # the probe never reaches the network - the update surface itself is
    # asserted below through the rendered affordance.
    patches.enter_context(mock.patch.object(m.application_update, 'claim_daily_update_check', return_value=False))
    patches.enter_context(mock.patch.dict(classes, {'QQmlApplicationEngine': engine_factory}))
    patches.enter_context(mock.patch.object(m.single_instance, 'register_settings_window_restore_event'))
    patches.enter_context(mock.patch.object(m.single_instance, 'release_settings_window_restore_event'))
    patches.enter_context(mock.patch.object(m, '_mark_settings_window_for_activation'))
    patches.enter_context(mock.patch.object(m.window_chrome_windows, 'apply_settings_window_chrome'))
    QTimer.singleShot(150, verify)
    QTimer.singleShot(8000, lambda: app.exit(99))
    result['exit_code'] = m.run_settings_window(start_hidden=True, start_bridge=True)
result['exit_confirmed'] = controllers[0]._application_exit_confirmed
result['unchanged'] = originals == {p.name: p.read_bytes() for p in root.glob('*.json')}
result['warnings'] = warnings
fixture.tearDown(); fixture.doCleanups()
print('RECOVERY_RESULT=' + json.dumps(result))
'''


class RecoveryWindowIntegrationTests(unittest.TestCase):
    def test_real_window_opens_exports_and_exits_with_either_broken_file(self):
        for broken_file in ('config', 'bindings'):
            with self.subTest(broken_file=broken_file):
                result = subprocess.run(
                    [sys.executable, '-X', 'utf8', '-B', '-c', _RECOVERY_WINDOW_PROBE, broken_file],
                    cwd=Path(__file__).resolve().parents[1],
                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', RC003_DISABLE_LIVE_INPUT='1'),
                    capture_output=True, text=True, encoding='utf-8', timeout=25,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                row = next(line for line in result.stdout.splitlines() if line.startswith('RECOVERY_RESULT='))
                evidence = json.loads(row.split('=', 1)[1])
                self.assertNotIn('error', evidence, evidence)
                self.assertEqual(evidence['exit_code'], 0, evidence)
                self.assertEqual(evidence['warnings'], [], evidence)
                for field in ('config_error_reported', 'readonly', 'visible', 'save_disabled',
                              'select_disabled', 'export_enabled', 'update_enabled', 'pages_ok',
                              'exported', 'exit_confirmed', 'unchanged'):
                    self.assertTrue(evidence[field], (field, evidence))


if __name__ == "__main__":
    unittest.main()
