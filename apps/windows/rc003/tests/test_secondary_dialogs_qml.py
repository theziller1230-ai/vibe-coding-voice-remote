"""Exercise secondary dialogs with isolated settings and no live device I/O."""
import os
import subprocess
import sys
import tempfile
import unittest

from tests.test_remote_selection import _QML_PROBE


_PROBE = _QML_PROBE.split('# == shared journey marker ==')[0] + r'''
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

def screenshot(name):
    directory = os.environ.get('SECONDARY_DIALOG_SCREENSHOTS')
    if directory:
        window.grabWindow().save(str(Path(directory) / (name + '.png')))

results = []
for width, height in ((640, 480), (720, 560)):
    window.setWidth(width)
    window.setHeight(height)
    settle()
    # The retired device dialog maps to the remote choice rows plus the
    # useRemote(id) slot in the settings device section.
    nav('settingsTabButton')
    click('settingsDeviceSection_foldToggle')
    click('settingsRefreshChecksButton')
    settle()
    choices = [(row.id, row.label, row.enabled, row.selected)
               for row in _viewmodels.DeviceViewModel.remoteChoices]
    assert [(row[0], row[1]) for row in choices] == [(A, selection.label(A)), (B, label_b)], choices
    assert [row[2] for row in choices] == [True, True], choices
    _viewmodels.DeviceViewModel.useRemote(A)
    settle()
    assert controller.activeRemoteKey == A
    choices = [(row.id, row.selected) for row in _viewmodels.DeviceViewModel.remoteChoices]
    assert choices == [(A, True), (B, False)], choices
    # The remaining secondary dialogs stay compact at every window size and
    # style; a long title note never widens them.
    for dialog_name, preferred in (('restoreDefaultsDialog', 420), ('deletePresetDialog', 420),
                                   ('removeHelperDialog', 420), ('actionEditorDialog', 520),
                                   ('shortcutRecorderDialog', 380)):
        dialog = item(dialog_name)
        QMetaObject.invokeMethod(dialog, 'open')
        settle()
        assert dialog.property('visible'), dialog_name
        assert dialog.property('width') <= preferred, (dialog_name, dialog.property('width'))
        assert dialog.property('width') <= width - 32, (dialog_name, dialog.property('width'))
        screenshot(f'{width}-{dialog_name}')
        QTest.keyClick(window, Qt.Key_Escape)
        settle()
        assert not dialog.property('visible'), dialog_name
    for dialog_name in ('restoreDefaultsDialog', 'deletePresetDialog', 'removeHelperDialog'):
        dialog = item(dialog_name)
        QMetaObject.invokeMethod(dialog, 'open')
        settle()
        assert 100 < dialog.property('height') < 250, (dialog_name, dialog.property('height'))
        QTest.keyClick(window, Qt.Key_Escape)
        settle()
    editor = item('actionEditorDialog')
    QMetaObject.invokeMethod(editor, 'open')
    settle()
    before = editor.property('width')
    editor.setProperty('titleNote', '当前使用：' + '很长的遥控器名称' * 12)
    settle()
    assert editor.property('width') == before, (before, editor.property('width'))
    screenshot(f'{width}-title-note')
    QTest.keyClick(window, Qt.Key_Escape)
    settle()
    # The sound-channel test stays reachable from the voice section.
    click('settingsVoiceSection_foldToggle')
    audio_titles = find_all(item('settingsVoiceSection'), lambda node: node.metaObject().indexOfProperty('titleText') >= 0
                            and node.property('titleText') == '声音通路')
    assert audio_titles, '声音通路'
    assert item('settingsTestAudioButton').property('enabled')
    assert item('settingsInstallVirtualCableButton').property('enabled')
    assert not diagnostics.vbCableTestRunning
    results.append({'size': [width, height], 'dialogs': 'opened-closed'})

from PySide6.QtQml import QQmlComponent
component = QQmlComponent(engine)
component.setData(b"""
import QtQuick
import QtQuick.Controls
import "."
SettingsDialog {
    tokens: Tokens {}
    standardButtons: Dialog.Ok | Dialog.Cancel
    property int accepts: 0
    property int rejects: 0
    onAccepted: accepts += 1
    onRejected: rejects += 1
    function confirmForProbe() { standardButton(Dialog.Ok).clicked() }
    function cancelForProbe() { standardButton(Dialog.Cancel).clicked() }
}
""", QUrl.fromLocalFile(str(m._qml_directory() / 'DialogProbe.qml')))
confirmation = component.createWithInitialProperties({'parent': window.contentItem()})
assert confirmation is not None, component.errors()
confirmation.setParent(window)
QMetaObject.invokeMethod(confirmation, 'open')
settle()
QMetaObject.invokeMethod(confirmation, 'confirmForProbe')
assert confirmation.property('accepts') == 1, confirmation.property('accepts')
QMetaObject.invokeMethod(confirmation, 'open')
settle()
QMetaObject.invokeMethod(confirmation, 'cancelForProbe')
assert confirmation.property('rejects') == 1, confirmation.property('rejects')
confirmation.deleteLater()
controller.shutdownBackgroundTasks()
m._shutdown_diagnostics_workers()
assert not warnings, warnings
print(json.dumps(results))
'''


class SecondaryDialogsQmlTests(unittest.TestCase):
    def test_compact_device_and_audio_dialogs(self):
        for style in ('Basic', 'Fusion'):
            with self.subTest(style=style), tempfile.TemporaryDirectory() as directory:
                env = dict(os.environ, LOCALAPPDATA=directory, QT_QPA_PLATFORM='offscreen',
                           RC003_DISABLE_LIVE_INPUT='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                           REMOTE_SELECTION_STYLE=style)
                probe = _PROBE
                result = subprocess.run([sys.executable, '-c', probe], env=env,
                                        capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
