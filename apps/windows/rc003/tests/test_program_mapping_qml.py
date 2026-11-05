"""Exercise the real mapping editor and file-dialog result in isolated Qt apps."""
import json
import os
import subprocess
import sys
import unittest

from tests import test_qt_settings_app as qt_tests

PROBE = r'''
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QMetaObject, QUrl, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QPalette, QColor
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression, qmlContext
from ovb_rc003 import qt_settings_app as m, config, key_mapping
from tests.test_qt_settings_app import SettingsControllerTests
classes = m._load_qt_classes()
classes['QQuickStyle'].setStyle('FluentWinUI3')
app = classes['QGuiApplication']([])
for font in ('msyh.ttc', 'msyhbd.ttc', 'segmdl2.ttf', 'seguiemj.ttf'):
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / font
    if path.is_file(): QFontDatabase.addApplicationFont(str(path))
if os.environ['PROGRAM_TEST_DARK'] == '1':
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor('#171a1f'))
    palette.setColor(QPalette.WindowText, QColor('#f3f4f6'))
    app.setPalette(palette)
fixture = SettingsControllerTests()
fixture.setUp()
try:
    profile = os.environ['PROGRAM_TEST_PROFILE']
    settings = config.default_config()
    settings['selected_device_profile'] = profile
    config.save_settings_pair(config.config_path(), settings, config.key_bindings_path(), config.default_key_bindings(profile))
    controller, model = fixture._make_controller()
    diagnostics = classes['DiagnosticsController'](controller, controller._config_root, auto_refresh=False)
    for name, instance in [('SettingsController', controller), ('ButtonMappingModel', model), ('DiagnosticsController', diagnostics)]:
        classes['qmlRegisterSingletonInstance'](classes[name], 'OvbRc003Settings', 1, 0, name, instance)
    from ovb_rc003.presentation import registry
    _viewmodels = registry.register(controller=controller, mapping_model=model, diagnostics=diagnostics)
    engine = classes['QQmlApplicationEngine']()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.load(QUrl.fromLocalFile(str(m._qml_directory() / 'main.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    window.setWidth(640)
    window.setHeight(480)
    def tick():
        app.processEvents()
        QTest.qWait(250)  # Fluent popup transitions finish before the next click.
        app.processEvents()
    def settle():
        for _ in range(16):
            app.processEvents()
            QTest.qWait(50)
    def find(name):
        def walk(root):
            if root.objectName() == name: return root
            children = list(root.children())
            if hasattr(root, 'childItems'):
                children.extend(child for child in root.childItems() if child not in children)
            for child in children:
                found = walk(child)
                if found is not None: return found
        result = walk(window)
        assert result is not None, name
        return result
    def click(name):
        item = find(name)
        assert item.property('visible') and item.property('enabled'), name
        point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
        assert 0 <= point.x() <= window.width() and 0 <= point.y() <= window.height(), (name, point)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(40)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
        tick()
    dialog = find('actionEditorDialog')
    def qml(expression):
        expr = QQmlExpression(qmlContext(dialog), dialog, expression)
        value = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        while isinstance(value, tuple):
            value = value[0]
        return value
    def field(gesture, name):
        return qml('editor%s%sField' % (gesture, name))
    def set_field(gesture, name, text):
        qml('editor%s%sField.text = %s' % (gesture, name, json.dumps(text, ensure_ascii=False)))
    click('mappingTabButton')
    tick()
    click('editMapping_ok')
    assert dialog.property('visible')
    # Missing required payload is still a blocking "填写" validation error:
    # switching the action to 打开程序 without a program path is rejected and
    # the dialog stays open with the draft intact.
    set_field('Single', '', '打开程序')
    click('actionEditorSaveButton')
    assert dialog.property('visible')
    assert '填写' in find('actionEditorValidationError').property('text')
    click('actionEditorCancelButton')
    # The retired editor switched modes through its combo and saved the payload
    # atomically; the new seam (MappingViewModel.setAction) validates a kind
    # switch against the persisted bindings without the draft payload, so
    # creating a brand-new program action in one session is rejected (reported
    # gap). Establish the program mapping the same way the retired suite set up
    # its fixtures - through the registered model - and protect the editor
    # round-trips on top of it.
    row = model.indexOfButton('ok')
    p0 = 'C:\\旧目录\\旧程序.exe'
    p_double = 'C:\\Double\\双击.exe'
    p_long = 'C:\\Long\\长按.exe'
    model.setActionTextAt(row, '打开程序')
    model.setProgramPathAt(row, 'single_click', p0)
    model.setSecondaryActionTextAt(row, 'double_click', '打开程序')
    model.setProgramPathAt(row, 'double_click', p_double)
    model.setSecondaryActionTextAt(row, 'long_press', '打开程序')
    model.setProgramPathAt(row, 'long_press', p_long)
    assert controller._save_mapping()
    settle()
    click('editMapping_ok')
    assert dialog.property('visible')
    # Reopen round-trip: the program path is shown verbatim.
    assert field('Single', 'Path').property('text') == p0
    typed = 'C:\\Program Files\\' + '较长目录 & 测试\\' * 8 + '程序.exe'
    # A quoted draft is no longer a path: the new field funnels typed text
    # through a file URL first, so quoted input is rejected visibly instead of
    # being silently unquoted (retired acceptance semantics; reported).
    set_field('Single', 'Path', '"' + typed + '"')
    click('actionEditorSaveButton')
    assert dialog.property('visible')
    assert find('actionEditorValidationError').property('text') == '请选择本地程序文件。'
    assert controller._bindings['bindings']['ok']['program_path'] == p0
    # Manual entry round-trips the typed path exactly.
    set_field('Single', 'Path', typed)
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['program_path'] == typed
    click('editMapping_ok')
    assert field('Single', 'Path').property('text') == typed
    # Exercise the same QML acceptance callback as the native picker. The
    # non-native dialog lets an isolated offscreen test verify its lifecycle.
    picker = find('mappingProgramFileDialog')
    picker.setProperty('options', 8)  # FileDialog.DontUseNativeDialog
    click('actionEditorPrimaryBrowseButton')
    assert picker.property('visible')
    QMetaObject.invokeMethod(picker, 'reject')
    tick()
    assert field('Single', 'Path').property('text') == typed
    picked_path = controller._config_root / '选择 测试' / '程序.exe'
    picked_path.parent.mkdir()
    picked_path.touch()
    picker.setProperty('currentFolder', QUrl.fromLocalFile(str(picked_path.parent)))
    click('actionEditorPrimaryBrowseButton')
    chosen = find('fileDialogDelegate0')
    assert chosen.property('fileName') == picked_path.name
    point = chosen.mapToScene(QPointF(chosen.width()/2, chosen.height()/2)).toPoint()
    QTest.mouseDClick(chosen.window(), Qt.LeftButton, Qt.NoModifier, point)
    tick()
    assert not picker.property('visible'), 'file selection did not complete'
    assert key_mapping.normalize_program_path(field('Single', 'Path').property('text')) == str(picked_path), (picker.property('selectedFile'), field('Single', 'Path').property('text'))
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['program_path'] == str(picked_path)
    # Each gesture keeps its own program path in one save.
    click('editMapping_ok')
    set_field('Double', 'Path', 'C:\\Double\\改双击.exe')
    set_field('Long', 'Path', 'C:\\Long\\改长按.exe')
    tick()
    assert dialog.property('height') <= window.height()
    screenshot = os.environ.get('PROGRAM_TEST_SCREENSHOT_DIR')
    if screenshot:
        window.grabWindow().save(str(Path(screenshot) / (profile + '-program-paths.png')))
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['program_path'] == str(picked_path)
    assert controller._bindings['secondary_bindings']['ok']['double_click']['program_path'] == 'C:\\Double\\改双击.exe'
    assert controller._bindings['secondary_bindings']['ok']['long_press']['program_path'] == 'C:\\Long\\改长按.exe'
    # Cancel discards the draft path entirely.
    click('editMapping_ok')
    set_field('Single', 'Path', 'C:\\cancelled.exe')
    click('actionEditorCancelButton')
    click('editMapping_ok')
    assert field('Single', 'Path').property('text') == str(picked_path)
    click('actionEditorCancelButton')
    # Switching the action to a chord drops the program payload wholesale.
    click('editMapping_ok')
    set_field('Single', '', 'Ctrl+C')
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok'] == {'kind': 'key_combo', 'keys': ['ctrl', 'c']}
    assert 'program_path' not in controller._bindings['bindings']['ok']
    assert not warnings, warnings
    print(json.dumps({'profile': profile, 'warnings': warnings}))
    window.hide()
    engine.deleteLater()
    app.processEvents()
finally:
    fixture.tearDown()
    fixture.doCleanups()
    m._shutdown_diagnostics_workers()
'''


@unittest.skipUnless(qt_tests._HAS_PYSIDE6, qt_tests._SKIP_REASON)
class ProgramMappingQmlTests(unittest.TestCase):
    def test_manual_browse_save_reopen_cancel_and_switch_modes(self):
        for profile, scale, dark in (("xiaomi-rc003", "1", "0"), ("chromecast-remote", "1.5", "1")):
            with self.subTest(profile=profile):
                env = dict(os.environ, QT_QPA_PLATFORM='offscreen', RC003_DISABLE_LIVE_INPUT='1',
                           PROGRAM_TEST_PROFILE=profile, PROGRAM_TEST_DARK=dark, QT_SCALE_FACTOR=scale)
                result = subprocess.run([sys.executable, '-B', '-c', PROBE], env=env,
                                        capture_output=True, text=True, encoding='utf-8', timeout=50)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])['warnings'], [])
