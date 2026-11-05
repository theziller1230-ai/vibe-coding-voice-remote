"""Real panel flow in disposable Qt processes; no native remote input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests import test_qt_settings_app as qt_tests


PROBE = r'''
import json, os, time
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QUrl, QPointF, Qt
from PySide6.QtGui import QPalette, QColor, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression, qmlContext
from ovb_rc003 import qt_settings_app as m, config, mapping_presets
from tests.test_qt_settings_app import SettingsControllerTests

classes = m._load_qt_classes()
classes['QQuickStyle'].setStyle('FluentWinUI3')
app = classes['QGuiApplication']([])
# The offscreen platform does not enumerate all Windows system font fallbacks.
for font in ('msyh.ttc', 'msyhbd.ttc', 'segmdl2.ttf'):
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / font
    if path.is_file():
        QFontDatabase.addApplicationFont(str(path))
if os.environ.get('PRESET_TEST_DARK') == '1':
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor('#171a1f'))
    palette.setColor(QPalette.WindowText, QColor('#f3f4f6'))
    app.setPalette(palette)
fixture = SettingsControllerTests()
fixture.setUp()
try:
    profile = os.environ['PRESET_TEST_PROFILE']
    settings = config.load_config(config.config_path())
    settings['selected_device_profile'] = profile
    config.save_settings_pair(config.config_path(), settings, config.key_bindings_path(), config.default_key_bindings(profile))
    controller, model = fixture._make_controller()
    diagnostics = classes['DiagnosticsController'](controller, controller._config_root, auto_refresh=False)
    for key, instance in [('SettingsController', controller), ('ButtonMappingModel', model), ('DiagnosticsController', diagnostics)]:
        classes['qmlRegisterSingletonInstance'](classes[key], 'OvbRc003Settings', 1, 0, key, instance)
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
        for _ in range(3):
            app.processEvents()
        QTest.qWait(250)  # Fluent popup transitions finish before the next click.
    def settle():
        for _ in range(16):
            app.processEvents()
            QTest.qWait(50)
    def find(name):
        def walk(root):
            if root.objectName() == name:
                return root
            children = list(root.children())
            if hasattr(root, 'childItems'):
                children.extend(child for child in root.childItems() if child not in children)
            for child in children:
                result = walk(child)
                if result is not None:
                    return result
            return None
        obj = walk(window)
        assert obj is not None, name
        return obj
    def click(name):
        item = find(name)
        assert item.property('visible') and item.property('enabled'), name
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        assert 0 <= point.x() <= window.width() and 0 <= point.y() <= window.height(), (name, point)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(40)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
        tick()
    def walk_items(root):
        children = list(root.children())
        if hasattr(root, 'childItems'):
            children.extend(child for child in root.childItems() if child not in children)
        for child in children:
            yield child
            yield from walk_items(child)
    def qml_of(dialog, expression):
        expr = QQmlExpression(qmlContext(dialog), dialog, expression)
        value = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        while isinstance(value, tuple):
            value = value[0]
        return value
    # The action editor's payload fields are QML ids without objectNames, so
    # resolve them through the dialog's creation context (same ids commitEditor
    # itself uses).
    editor = find('actionEditorDialog')
    def set_editor_field(gesture, name, text):
        qml_of(editor, 'editor%s%sField.text = %s' % (gesture, name, json.dumps(text, ensure_ascii=False)))
    # Seed the working state through the real editor: a long-press mouse hold.
    click('mappingTabButton')
    tick()
    click('editMapping_ok')
    assert editor.property('visible')
    set_editor_field('Long', '', '鼠标左键长按')
    click('actionEditorSaveButton')
    assert not editor.property('visible')
    settle()
    assert controller._bindings['secondary_bindings']['ok']['long_press']['kind'] == 'mouse_left_hold'
    # The preset management row moved from the retired MappingPresetsDialog to
    # the settings page's 按键 section.
    click('settingsTabButton')
    tick()
    flick = None
    for obj in walk_items(find('settingsPanel')):
        if 'Flickable' in obj.metaObject().className():
            flick = obj
            break
    assert flick is not None
    def ensure_visible(item):
        content = flick.property('contentItem')
        pos = item.mapToItem(content, QPointF(0, 0))
        flick.setProperty('contentY', max(0, min(pos.y() - 40,
            flick.property('contentHeight') - flick.property('height'))))
        tick()
    def click_in(name):
        ensure_visible(find(name))
        click(name)
    click('settingsMappingSection_foldToggle')
    tick()
    # The retired MappingPresetsDialog refreshed the preset list on open through
    # this same controller entry point; the new panel exposes no load trigger of
    # its own (reported gap), so the probe performs the load step explicitly.
    loaded = controller.mappingPresetAction('refresh', '', '')
    assert loaded['ok'] and loaded['message'] == '', loaded
    tick()
    combo = find('settingsPresetCombo')
    ensure_visible(combo)
    assert combo.property('count') == 1
    assert combo.property('currentIndex') == combo.property('effectiveIndex') == 0
    assert '自动保存' in combo.property('displayText')
    assert find('settingsApplyPresetButton').property('text') == '应用'
    assert not find('settingsRenamePresetButton').property('enabled')
    assert not find('settingsSavePresetButton').property('enabled')
    assert find('settingsPanel').property('feedbackText') == ''
    assert len(controller.mappingPresets) == 1
    assert controller.mappingPresets[0]['automatic'] and controller.mappingPresets[0]['applied']
    # All management actions form one row; every button stays within the section.
    buttons = [find('settings' + name + 'PresetButton')
               for name in ('Apply', 'Rename', 'Export', 'Delete', 'Import')]
    positions = [button.mapToScene(QPointF(0, 0)) for button in buttons]
    assert max(point.y() for point in positions) - min(point.y() for point in positions) < 1
    section = find('settingsMappingSection')
    section_origin = section.mapToScene(QPointF(0, 0))
    for button, point in zip(buttons, positions):
        assert point.x() >= section_origin.x()
        assert point.x() + button.width() <= section_origin.x() + section.width()
    screenshot_dir = os.environ.get('PRESET_TEST_SCREENSHOT_DIR')
    if screenshot_dir:
        window.grabWindow().save(str(Path(screenshot_dir) / (profile + '-initial.png')))
    # Copying the automatic row into a named preset; empty input cannot even be
    # submitted (the retired naming dialog rejected it after accept).
    name_field = find('settingsPresetNameField')
    name_field.setProperty('text', '')
    assert not find('settingsSavePresetButton').property('enabled')
    name_field.setProperty('text', '我的按键配置')
    tick()
    assert find('settingsSavePresetButton').property('enabled')
    click_in('settingsSavePresetButton')
    settle()
    assert len(controller.mappingPresets) == 2
    first = controller.mappingPresets[1]['id']
    assert controller.mappingPresets[1]['name'] == '我的按键配置'
    assert combo.property('effectiveIndex') == 0
    # Browsing another row cannot redirect the copy's source.
    click('mappingTabButton')
    tick()
    click('editMapping_ok')
    set_editor_field('Long', '', 'Ctrl+C')
    click('actionEditorSaveButton')
    assert not editor.property('visible')
    settle()
    assert controller._bindings['secondary_bindings']['ok']['long_press'] == {'kind': 'key_combo', 'keys': ['ctrl', 'c']}
    click('settingsTabButton')
    tick()
    ensure_visible(combo)
    combo.setProperty('currentIndex', 1)
    name_field.setProperty('text', '副本二')
    tick()
    click_in('settingsSavePresetButton')
    settle()
    store = mapping_presets.PresetStore(controller._config_root)
    assert len(controller.mappingPresets) == 3
    second = controller.mappingPresets[2]['id']
    assert second != first
    assert controller.mappingPresets[2]['name'] == '副本二'
    assert store.get(second)['mapping'] == mapping_presets.snapshot(controller._bindings, profile)
    assert store.get(second)['mapping'] != store.get(first)['mapping']
    # Renaming is scoped to the row selected at click time; others are untouched.
    combo.setProperty('currentIndex', 2)
    name_field.setProperty('text', '副本改名')
    tick()
    assert find('settingsRenamePresetButton').property('enabled')
    click_in('settingsRenamePresetButton')
    settle()
    assert store.get(second)['name'] == '副本改名'
    assert store.get(first)['name'] == '我的按键配置'
    first_mapping = store.get(first)['mapping']
    # Applying replaces the live bindings with the selected preset.
    combo.setProperty('currentIndex', 1)
    tick()
    click_in('settingsApplyPresetButton')
    settle()
    assert '已应用' in find('settingsPanel').property('feedbackText')
    assert mapping_presets.snapshot(controller._bindings, profile) == first_mapping
    applied_index = next(index for index, row in enumerate(controller.mappingPresets) if row['applied'])
    assert combo.property('effectiveIndex') == applied_index
    # Browsing an unapplied row must not move the check mark or bold type.
    combo.setProperty('currentIndex', 2)
    tick()
    assert combo.property('effectiveIndex') == applied_index
    combo.setProperty('currentIndex', applied_index)
    tick()
    click('settingsPresetCombo')
    for index in range(combo.property('count')):
        option = find('settingsPresetCombo_option_' + str(index))
        weight = option.property('contentItem').property('font').weight()
        assert int(weight) == (600 if index == applied_index else 400), (index, weight)
        mark = find('settingsPresetCombo_effectiveMark_' + str(index))
        assert bool(mark.property('visible')) == (index == applied_index)
    if screenshot_dir:
        window.grabWindow().save(str(Path(screenshot_dir) / (profile + '.png')))
    QTest.keyClick(window, Qt.Key_Escape)
    tick()
    if screenshot_dir:
        window.grabWindow().save(str(Path(screenshot_dir) / (profile + '-panel.png')))
    # Deleting requires confirmation; rejecting keeps both the preset and the
    # live bindings intact.
    before_bindings = json.dumps(controller._bindings, sort_keys=True)
    combo.setProperty('currentIndex', 2)
    tick()
    click_in('settingsDeletePresetButton')
    delete_dialog = find('deletePresetDialog')
    assert delete_dialog.property('visible')
    QMetaObject.invokeMethod(delete_dialog, 'reject')
    tick()
    assert len(controller.mappingPresets) == 3
    assert json.dumps(controller._bindings, sort_keys=True) == before_bindings
    for identity in (second, first):
        rows = controller.mappingPresets
        combo.setProperty('currentIndex', next(index for index, row in enumerate(rows) if row['id'] == identity))
        tick()
        click_in('settingsDeletePresetButton')
        QMetaObject.invokeMethod(delete_dialog, 'accept')
        settle()
    # Both records are removed; the applied values remain intact.
    assert len(controller.mappingPresets) == 1
    assert controller.mappingPresets[0]['automatic'] and controller.mappingPresets[0]['applied']
    assert mapping_presets.snapshot(controller._bindings, profile) == first_mapping
    # The automatic entry cannot be renamed or removed.
    combo.setProperty('currentIndex', 0)
    name_field.setProperty('text', '试图改名')
    tick()
    click_in('settingsRenamePresetButton')
    settle()
    assert controller.mappingPresets[0]['name'] == mapping_presets.AUTO_NAME
    assert find('settingsPanel').property('feedbackText') == '自动保存项代表当前按键设置，不能重命名或删除。'
    click_in('settingsDeletePresetButton')
    QMetaObject.invokeMethod(delete_dialog, 'accept')
    settle()
    assert len(controller.mappingPresets) == 1
    assert controller.mappingPresets[0]['automatic'] and controller.mappingPresets[0]['applied']
    # A legacy mapping that needs correction must not hide valid named copies.
    store = mapping_presets.PresetStore(controller._config_root)
    compatible = store.create('兼容验证副本', profile, mapping_presets.snapshot(controller._bindings, profile))
    export = controller._config_root.parent / 'compatible.json'
    store.export_file(compatible, export)
    controller._bindings['bindings']['mic'] = {'kind': 'voice_toggle', 'keys': []}
    controller._removed_voice_bindings = config.normalize_voice_product_boundary(controller._config, controller._bindings)
    controller._load_bindings_into_model()
    controller._set_mapping_dirty(True)
    legacy_before = json.dumps(controller._bindings, sort_keys=True)
    click('homeTabButton')
    tick()
    click('settingsTabButton')
    tick()
    ensure_visible(combo)
    loaded = controller.mappingPresetAction('refresh', '', '')
    assert loaded['ok'] and loaded['message'] == '', loaded
    tick()
    assert combo.property('count') == 2
    assert combo.property('currentIndex') == combo.property('effectiveIndex') == 0
    assert [row['id'] for row in controller.mappingPresets] == [mapping_presets.AUTO_ID, compatible]
    imported = _viewmodels.MappingViewModel.importPreset(QUrl.fromLocalFile(str(export)).toString())
    assert imported['ok'], imported
    settle()
    assert combo.property('count') == 3
    assert controller.mappingPresets[2]['id'] == imported['field']
    assert json.dumps(controller._bindings, sort_keys=True) == legacy_before
    assert not warnings, warnings
    print(json.dumps({'profile': profile, 'warnings': warnings, 'width': 640, 'height': 480}))
    window.hide()
    engine.deleteLater()
    app.processEvents()
finally:
    fixture.tearDown()
    fixture.doCleanups()
    m._shutdown_diagnostics_workers()
'''


@unittest.skipUnless(qt_tests._HAS_PYSIDE6, qt_tests._SKIP_REASON)
class MappingPresetsQmlTests(unittest.TestCase):
    def test_real_panel_flow_in_both_profiles_and_light_dark_scaled_windows(self):
        for profile, scale, dark in (("xiaomi-rc003", "1", "0"), ("chromecast-remote", "1.5", "1")):
            with self.subTest(profile=profile, scale=scale, dark=dark):
                env = dict(os.environ, QT_QPA_PLATFORM="offscreen", RC003_DISABLE_LIVE_INPUT="1",
                           PRESET_TEST_PROFILE=profile, PRESET_TEST_DARK=dark, QT_SCALE_FACTOR=scale)
                result = subprocess.run([sys.executable, "-c", PROBE], env=env,
                                        capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])["warnings"], [])
