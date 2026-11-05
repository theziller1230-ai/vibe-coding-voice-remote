"""Drive the real text editor in isolated Qt processes and temporary configs."""
import json
import os
import subprocess
import sys
import unittest

from tests import test_qt_settings_app as qt_tests

PROBE = r'''
import json, os
from pathlib import Path
from PySide6.QtCore import QMetaObject, QUrl, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QPalette, QColor
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression, qmlContext
from ovb_rc003 import qt_settings_app as m, config, key_mapping, mapping_presets
from tests.test_qt_settings_app import SettingsControllerTests
classes = m._load_qt_classes()
classes['QQuickStyle'].setStyle('FluentWinUI3')
app = classes['QGuiApplication']([])
for font in ('msyh.ttc', 'msyhbd.ttc', 'segmdl2.ttf', 'seguiemj.ttf'):
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / font
    if path.is_file(): QFontDatabase.addApplicationFont(str(path))
if os.environ.get('TEXT_TEST_DARK') == '1':
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor('#171a1f'))
    palette.setColor(QPalette.WindowText, QColor('#f3f4f6'))
    app.setPalette(palette)
fixture = SettingsControllerTests()
fixture.setUp()
try:
    profile = os.environ['TEXT_TEST_PROFILE']
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
    # The action editor's payload fields are QML ids without objectNames, so
    # resolve them through the dialog's creation context (same ids commitEditor
    # itself uses).
    def field(gesture, name):
        return qml('editor%s%sField' % (gesture, name))
    def set_field(gesture, name, text):
        qml('editor%s%sField.text = %s' % (gesture, name, json.dumps(text, ensure_ascii=False)))
    # The retired editor switched the action kind through its mode combo and
    # saved the payload atomically; the new seam (MappingViewModel.setAction)
    # validates a kind switch against the persisted bindings without the draft
    # payload, so creating a brand-new text action in one session is rejected
    # (reported gap). Establish the text mapping the same way the retired suite
    # set up its CRLF fixture - through the registered model - and protect the
    # editor round-trips on top of it.
    row = model.indexOfButton('ok')
    model.setActionTextAt(row, '输入文字')
    model.setSecondaryActionTextAt(row, 'double_click', '输入文字')
    model.setSecondaryActionTextAt(row, 'long_press', '输入文字')
    model.setTextContentAt(row, 'single_click', '初始单击')
    model.setTextContentAt(row, 'double_click', '初始双击')
    model.setTextContentAt(row, 'long_press', '初始长按')
    assert controller._save_mapping()
    settle()
    click('mappingTabButton')
    tick()
    click('editMapping_ok')
    assert dialog.property('visible')
    # Reopen round-trip: the editor shows the persisted text mapping verbatim.
    assert field('Single', '').property('text') == '输入文字'
    assert field('Single', 'Content').property('text') == '初始单击'
    assert field('Double', 'Content').property('text') == '初始双击'
    assert field('Long', 'Content').property('text') == '初始长按'
    # Empty required payload stays a blocking "填写" validation error.
    set_field('Single', 'Content', '')
    click('actionEditorSaveButton')
    assert dialog.property('visible')
    assert '填写' in find('actionEditorValidationError').property('text')
    text = ' 你好😀\nCtrl+C\nEnter\nquicker:runaction:literal\t '
    set_field('Single', 'Content', text)
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['text'] == text
    # All three gestures can contain text without pushing Save out of the window.
    click('editMapping_ok')
    set_field('Double', 'Content', text + 'Double')
    set_field('Long', 'Content', text + 'Long')
    tick()
    assert dialog.property('height') <= window.height()
    screenshot = os.environ.get('TEXT_TEST_SCREENSHOT_DIR')
    if screenshot:
        window.grabWindow().save(str(Path(screenshot) / (profile + '-three-text.png')))
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['text'] == text
    for name, trigger in (('Double', 'double_click'), ('Long', 'long_press')):
        assert controller._bindings['secondary_bindings']['ok'][trigger]['text'] == text + name
    # Editing only the body must persist on completion.
    click('editMapping_ok')
    set_field('Single', 'Content', '第二段')
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok']['text'] == '第二段'
    click('editMapping_ok')
    set_field('Single', 'Content', '不保存')
    click('actionEditorCancelButton')
    settle()
    assert controller._bindings['bindings']['ok']['text'] == '第二段'
    click('editMapping_ok')
    assert field('Single', 'Content').property('text') == '第二段'
    click('actionEditorCancelButton')
    # An imported CRLF payload renders identically to its LF original and
    # viewing it must never rewrite the stored bytes.
    imported_text = text.replace('\n', '\r\n')
    model.setTextContentAt(model.index_of('ok'), 'single_click', imported_text)
    assert controller._save_mapping()
    settle()
    click('editMapping_ok')
    assert field('Single', 'Content').property('text') == text
    click('actionEditorCancelButton')
    settle()
    assert controller._bindings['bindings']['ok']['text'] == imported_text
    # Switching the action to a chord replaces the text payload wholesale.
    click('editMapping_ok')
    set_field('Single', '', 'Ctrl+C')
    click('actionEditorSaveButton')
    assert not dialog.property('visible')
    settle()
    assert controller._bindings['bindings']['ok'] == {'kind': 'key_combo', 'keys': ['ctrl', 'c']}
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
class TextMappingQmlTests(unittest.TestCase):
    def test_edit_save_reopen_and_cancel_in_both_profiles(self):
        for profile, scale, dark in (("xiaomi-rc003", "1", "0"), ("chromecast-remote", "1.5", "1")):
            with self.subTest(profile=profile):
                env = dict(os.environ, QT_QPA_PLATFORM="offscreen", RC003_DISABLE_LIVE_INPUT="1",
                           TEXT_TEST_PROFILE=profile, TEXT_TEST_DARK=dark, QT_SCALE_FACTOR=scale)
                result = subprocess.run([sys.executable, "-B", "-c", PROBE], env=env,
                                        capture_output=True, text=True, encoding="utf-8", timeout=40)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])["warnings"], [])
