import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import OvbRc003Presentation 1.0

// 设置页：高级选项，默认全部折叠（设备 / 语音 / 按键 / 维护）。
// 只读展示合同数据、把用户操作转发给对应视图模型，不做任何业务判断。
Item {
    id: root

    property var tokens

    // 最近一次转发操作的反馈（仅展示 Validation 的结论）。
    property string feedbackText: ""
    property bool feedbackIsError: false

    function showFeedback(result) {
        if (result && result.ok === false) {
            feedbackIsError = true
            feedbackText = result.message
        } else {
            feedbackIsError = false
            feedbackText = result && result.message ? result.message : ""
        }
    }

    function toneColor(tone) {
        if (tone === "ok")
            return tokens.successColor
        if (tone === "warn")
            return tokens.voiceAccent
        if (tone === "error")
            return tokens.errorColor
        return tokens.textSecondary
    }

    function checkStatusColor(status) {
        if (status === "done")
            return tokens.successColor
        if (status === "current")
            return tokens.accent
        if (status === "failed")
            return tokens.errorColor
        return tokens.textSecondary
    }

    function checkStatusLabel(status) {
        if (status === "done")
            return qsTr("正常")
        if (status === "current")
            return qsTr("进行中")
        if (status === "failed")
            return qsTr("异常")
        return qsTr("待处理")
    }

    function presetLabels() {
        const rows = MappingViewModel.presets
        const out = []
        for (let i = 0; i < rows.length; ++i)
            out.push(rows[i].label)
        return out
    }

    function presetIdAt(index) {
        const rows = MappingViewModel.presets
        return index >= 0 && index < rows.length ? rows[index].id : ""
    }

    function presetEnabledAt(index) {
        const rows = MappingViewModel.presets
        return index >= 0 && index < rows.length ? rows[index].enabled : false
    }

    function appliedPresetIndex() {
        const rows = MappingViewModel.presets
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i].selected)
                return i
        }
        return -1
    }

    function toFileUrl(path) {
        let normalized = path.replace(/\\/g, "/")
        if (/^[A-Za-z]:\//.test(normalized))
            return "file:///" + encodeURI(normalized)
        return encodeURI(normalized)
    }

    // 选择行（遥控器 / 语音程序）：点击选中并转发。
    component ChoiceRowItem: Item {
        id: choice
        property var tokens
        property string labelText: ""
        property string detailText: ""
        property bool rowEnabled: true
        property bool rowSelected: false
        signal chosen()

        Layout.fillWidth: true
        implicitHeight: row.implicitHeight

        InlineSettingsRow {
            id: row
            anchors.fill: parent
            tokens: choice.tokens
            titleText: choice.labelText
            titleWidth: 150
            descriptionText: choice.detailText
            stateText: choice.rowSelected ? qsTr("当前使用") : ""
            stateColor: choice.tokens.accent
        }

        TapHandler {
            enabled: choice.rowEnabled
            onTapped: choice.chosen()
        }
    }

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight + tokens.pageVerticalPadding * 2
        clip: true

        ColumnLayout {
            id: contentColumn
            width: parent.width
            spacing: tokens.spacingLarge

            Item { Layout.preferredHeight: tokens.pageVerticalPadding }

            // ---- 设备 ----
            FoldSection {
                objectName: "settingsDeviceSection"
                tokens: root.tokens
                Layout.fillWidth: true
                titleText: qsTr("设备")
                noteText: DeviceViewModel.batteryLabel

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: root.tokens.spacingSmall

                            UiLabel {
                                tokens: root.tokens
                                kind: bodyKind
                                font.weight: Font.Medium
                                text: DeviceViewModel.connectionCard.title
                                color: root.toneColor(DeviceViewModel.connectionCard.tone)
                                elide: Text.ElideRight
                            }
                            UiLabel {
                                tokens: root.tokens
                                kind: noteKind
                                Layout.fillWidth: true
                                text: DeviceViewModel.connectionCard.subtitle
                                elide: Text.ElideRight
                            }
                        }

                        UiLabel {
                            visible: text.length > 0
                            tokens: root.tokens
                            kind: noteKind
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: DeviceViewModel.connectionCard.detail
                        }
                    }

                    CompactButton {
                        objectName: "settingsBridgeActionButton"
                        tokens: root.tokens
                        highlighted: true
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: DeviceViewModel.connectionCard.actionLabel
                        onClicked: root.showFeedback(DeviceViewModel.bridgeAction())
                    }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("遥控器")
                }

                Repeater {
                    model: DeviceViewModel.remoteChoices
                    delegate: ChoiceRowItem {
                        required property var modelData
                        tokens: root.tokens
                        labelText: modelData.label
                        detailText: modelData.detail
                        rowEnabled: modelData.enabled
                        rowSelected: modelData.selected
                        onChosen: DeviceViewModel.useRemote(modelData.id)
                    }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("检查项")
                }

                Repeater {
                    model: DeviceViewModel.checks
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.tokens.spacingSmall

                        DiagnosticResultRow {
                            Layout.fillWidth: true
                            tokens: root.tokens
                            indicatorColor: root.checkStatusColor(modelData.status)
                            titleText: modelData.title
                            statusText: root.checkStatusLabel(modelData.status)
                            detailText: modelData.detail
                        }
                        CompactButton {
                            visible: modelData.fixLabel.length > 0
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: modelData.fixLabel
                            onClicked: DeviceViewModel.fixCheck(modelData.id)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    CompactButton {
                        objectName: "settingsRefreshChecksButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: qsTr("重新检查")
                        onClicked: DeviceViewModel.refresh()
                    }
                }
            }

            // ---- 语音 ----
            FoldSection {
                objectName: "settingsVoiceSection"
                tokens: root.tokens
                Layout.fillWidth: true
                titleText: qsTr("语音")

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("语音程序")
                }

                Repeater {
                    model: VoiceViewModel.voicePrograms
                    delegate: ChoiceRowItem {
                        required property var modelData
                        tokens: root.tokens
                        labelText: modelData.label
                        detailText: modelData.detail
                        rowEnabled: modelData.enabled
                        rowSelected: modelData.selected
                        onChosen: VoiceViewModel.setVoiceProgram(modelData.id)
                    }
                }

                FormField {
                    tokens: root.tokens
                    titleText: qsTr("自定义程序")
                    noteText: qsTr("旧自定义配置使用的程序路径")

                    RowLayout {
                        spacing: root.tokens.spacingSmall

                        CompactTextField {
                            id: customProgramPathField
                            tokens: root.tokens
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: VoiceViewModel.customProgramPath
                            placeholderText: qsTr("选择或粘贴 .exe / .lnk 路径")
                            selectByMouse: true
                            Accessible.name: qsTr("自定义程序路径")
                            onEditingFinished: {
                                const trimmed = text.trim()
                                if (trimmed !== VoiceViewModel.customProgramPath.trim())
                                    root.showFeedback(
                                        VoiceViewModel.pickCustomProgramPath(
                                            root.toFileUrl(trimmed)))
                            }
                        }
                        CompactButton {
                            objectName: "settingsPickCustomProgramButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: qsTr("选择")
                            onClicked: customProgramFileDialog.open()
                        }
                    }
                }

                SettingsListRow {
                    tokens: root.tokens
                    titleText: qsTr("随遥控器服务启动")
                    descriptionText: qsTr("关闭后请自行启动语音程序")

                    CompactSwitch {
                        tokens: root.tokens
                        checked: VoiceViewModel.autoLaunch
                        Accessible.name: qsTr("随遥控器服务启动")
                        onToggled: root.showFeedback(
                            VoiceViewModel.setAutoLaunch(checked))
                    }
                }

                SettingsListRow {
                    tokens: root.tokens
                    titleText: qsTr("管理员启动")
                    descriptionText: qsTr("以管理员身份启动语音程序")

                    CompactSwitch {
                        tokens: root.tokens
                        checked: VoiceViewModel.launchElevated
                        Accessible.name: qsTr("管理员启动")
                        onToggled: root.showFeedback(
                            VoiceViewModel.setLaunchElevated(checked))
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    CompactButton {
                        objectName: "settingsLaunchVoiceProgramButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: qsTr("启动语音程序")
                        onClicked: VoiceViewModel.launchVoiceProgram()
                    }
                    CompactButton {
                        objectName: "settingsOpenVoiceProgramSettingsButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth6Chars
                        text: qsTr("打开语音程序设置")
                        onClicked: VoiceViewModel.openVoiceProgramSettings()
                    }
                    Item { Layout.fillWidth: true }
                }

                FormField {
                    tokens: root.tokens
                    titleText: qsTr("按键模式")
                    noteText: qsTr("语音键按下时的录音方式")

                    SelectionComboBox {
                        tokens: root.tokens
                        Layout.preferredWidth: 240
                        // 与 VoiceViewModel.recordingMode 的展示值一致。
                        model: ["按住说话", "按一次开·再按一次关"]
                        currentIndex: VoiceViewModel.recordingMode
                            === "按一次开·再按一次关" ? 1 : 0
                        onActivated: function(index) {
                            VoiceViewModel.setRecordingMode(
                                index === 1
                                    ? "按一次开·再按一次关" : "按住说话")
                        }
                    }
                }

                FormField {
                    tokens: root.tokens
                    titleText: qsTr("最长录音时间")
                    noteText: qsTr("录音自动停止前的最长秒数")

                    RowLayout {
                        spacing: root.tokens.spacingSmall

                        CompactTextField {
                            id: recordingLimitField
                            tokens: root.tokens
                            Layout.preferredWidth: 90
                            text: String(VoiceViewModel.recordingLimitSeconds)
                            selectByMouse: true
                            validator: IntValidator { bottom: 1 }
                            Accessible.name: qsTr("最长录音秒数")
                        }
                        CompactButton {
                            objectName: "settingsSetRecordingLimitButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: qsTr("设置")
                            onClicked: VoiceViewModel.setRecordingLimit(
                                Number(recordingLimitField.text))
                        }
                    }
                }

                FormField {
                    tokens: root.tokens
                    titleText: qsTr("语音按键")
                    noteText: qsTr("语音程序用来开 / 关麦的快捷键")

                    RowLayout {
                        spacing: root.tokens.spacingSmall

                        UiLabel {
                            tokens: root.tokens
                            kind: bodyKind
                            text: VoiceViewModel.hotkeyLabel.length > 0
                                ? VoiceViewModel.hotkeyLabel : qsTr("尚未录入")
                            color: VoiceViewModel.hotkeyLabel.length > 0
                                ? tokens.textPrimary : tokens.disabledText
                        }
                        CompactButton {
                            objectName: "settingsStartHotkeyCaptureButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: qsTr("录入")
                            onClicked: VoiceViewModel.startHotkeyCapture()
                        }
                        CompactButton {
                            objectName: "settingsStopHotkeyCaptureButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: qsTr("停止")
                            onClicked: VoiceViewModel.stopHotkeyCapture()
                        }
                    }
                }

                FormField {
                    tokens: root.tokens
                    titleText: qsTr("声音通路")
                    noteText: VoiceViewModel.audioRouteLabel

                    RowLayout {
                        spacing: root.tokens.spacingSmall

                        CompactButton {
                            objectName: "settingsTestAudioButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth4Chars
                            text: qsTr("检查声音通路")
                            onClicked: VoiceViewModel.testAudio()
                        }
                        CompactButton {
                            objectName: "settingsInstallVirtualCableButton"
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth4Chars
                            text: qsTr("安装虚拟音频")
                            onClicked: VoiceViewModel.installVirtualCable()
                        }
                    }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("输出端点")
                }

                Repeater {
                    model: VoiceViewModel.outputEndpoints
                    delegate: ChoiceRowItem {
                        required property var modelData
                        tokens: root.tokens
                        labelText: modelData.label
                        detailText: modelData.detail
                        rowEnabled: modelData.enabled
                        rowSelected: modelData.selected
                        onChosen: VoiceViewModel.selectOutput(modelData.id)
                    }
                }
            }

            // ---- 按键 ----
            FoldSection {
                objectName: "settingsMappingSection"
                tokens: root.tokens
                Layout.fillWidth: true
                titleText: qsTr("按键")

                UiLabel {
                    tokens: root.tokens
                    kind: noteKind
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: qsTr("逐键动作的编辑在“按键”页完成。")
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("按键配置")
                }

                SelectionComboBox {
                    id: presetCombo
                    objectName: "settingsPresetCombo"
                    tokens: root.tokens
                    Layout.fillWidth: true
                    model: root.presetLabels()
                    effectiveIndex: root.appliedPresetIndex()
                    showEffectiveMarker: true
                    Component.onCompleted: {
                        if (currentIndex < 0 && count > 0)
                            currentIndex = 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    CompactButton {
                        objectName: "settingsApplyPresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("应用")
                        enabled: root.presetEnabledAt(presetCombo.currentIndex)
                        onClicked: root.showFeedback(
                            MappingViewModel.applyPreset(
                                root.presetIdAt(presetCombo.currentIndex)))
                    }
                    CompactButton {
                        objectName: "settingsRenamePresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("重命名")
                        enabled: root.presetEnabledAt(presetCombo.currentIndex)
                            && presetNameField.text.trim().length > 0
                        onClicked: {
                            root.showFeedback(MappingViewModel.renamePreset(
                                root.presetIdAt(presetCombo.currentIndex),
                                presetNameField.text.trim()))
                            presetNameField.text = ""
                        }
                    }
                    CompactButton {
                        objectName: "settingsExportPresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("导出")
                        enabled: root.presetIdAt(presetCombo.currentIndex).length > 0
                        onClicked: exportFileDialog.open()
                    }
                    CompactButton {
                        objectName: "settingsDeletePresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("删除")
                        enabled: root.presetEnabledAt(presetCombo.currentIndex)
                        onClicked: deletePresetDialog.open()
                    }
                    CompactButton {
                        objectName: "settingsImportPresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("导入")
                        onClicked: importFileDialog.open()
                    }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    CompactTextField {
                        id: presetNameField
                        objectName: "settingsPresetNameField"
                        tokens: root.tokens
                        Layout.preferredWidth: 180
                        placeholderText: qsTr("新配置名称")
                        selectByMouse: true
                        Accessible.name: qsTr("新配置名称")
                    }
                    CompactButton {
                        objectName: "settingsSavePresetButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: qsTr("保存当前")
                        enabled: presetNameField.text.trim().length > 0
                        onClicked: {
                            root.showFeedback(MappingViewModel.savePreset(
                                presetNameField.text.trim()))
                            presetNameField.text = ""
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    CompactButton {
                        objectName: "settingsRestoreDefaultsButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth6Chars
                        text: qsTr("恢复内置默认")
                        onClicked: restoreDefaultsDialog.open()
                    }
                }
            }

            // ---- 维护 ----
            FoldSection {
                objectName: "settingsMaintenanceSection"
                tokens: root.tokens
                Layout.fillWidth: true
                titleText: qsTr("维护")

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: root.tokens.spacingSmall

                            UiLabel {
                                tokens: root.tokens
                                kind: bodyKind
                                font.weight: Font.Medium
                                text: MaintenanceViewModel.updateStatus.title
                                color: root.toneColor(MaintenanceViewModel.updateStatus.tone)
                                elide: Text.ElideRight
                            }
                            UiLabel {
                                tokens: root.tokens
                                kind: noteKind
                                Layout.fillWidth: true
                                text: MaintenanceViewModel.updateStatus.subtitle
                                elide: Text.ElideRight
                            }
                        }

                        UiLabel {
                            visible: text.length > 0
                            tokens: root.tokens
                            kind: noteKind
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: MaintenanceViewModel.updateStatus.detail
                        }
                    }

                    CompactButton {
                        objectName: "settingsUpdateActionButton"
                        tokens: root.tokens
                        highlighted: true
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: MaintenanceViewModel.updateStatus.actionLabel
                        onClicked: MaintenanceViewModel.run("update")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    CompactButton {
                        objectName: "settingsOpenUpdateReleaseButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth2Chars
                        text: qsTr("发布页")
                        onClicked: MaintenanceViewModel.openUpdateRelease()
                    }
                    CompactButton {
                        objectName: "settingsCancelUpdateDownloadButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: qsTr("取消下载")
                        onClicked: MaintenanceViewModel.cancelUpdateDownload()
                    }
                    Item { Layout.fillWidth: true }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("维护项目")
                }

                Repeater {
                    model: MaintenanceViewModel.items
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.tokens.spacingSmall

                        DiagnosticResultRow {
                            Layout.fillWidth: true
                            tokens: root.tokens
                            indicatorColor: root.checkStatusColor(modelData.status)
                            titleText: modelData.title
                            statusText: root.checkStatusLabel(modelData.status)
                            detailText: modelData.detail
                        }
                        CompactButton {
                            tokens: root.tokens
                            compactMinimumWidth: root.tokens.buttonWidth2Chars
                            text: modelData.fixLabel.length > 0
                                ? modelData.fixLabel : qsTr("运行")
                            onClicked: MaintenanceViewModel.run(modelData.id)
                        }
                    }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("通用设置")
                }

                Repeater {
                    model: MaintenanceViewModel.preferences
                    delegate: SettingsListRow {
                        required property var modelData
                        tokens: root.tokens
                        titleText: modelData.label
                        descriptionText: modelData.detail

                        CompactSwitch {
                            tokens: root.tokens
                            checked: modelData.value
                            enabled: modelData.enabled
                            Accessible.name: modelData.label
                            onToggled: root.showFeedback(
                                MaintenanceViewModel.setPreference(
                                    modelData.id, checked))
                        }
                    }
                }

                SettingsSectionTitle {
                    tokens: root.tokens
                    text: qsTr("系统设置")
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingMedium

                    CompactLink {
                        objectName: "settingsMicrophonePrivacyLink"
                        tokens: root.tokens
                        text: qsTr("麦克风隐私")
                        onClicked: MaintenanceViewModel.openMicrophonePrivacySettings()
                    }
                    CompactLink {
                        objectName: "settingsSpeechSettingsLink"
                        tokens: root.tokens
                        text: qsTr("语音设置")
                        onClicked: MaintenanceViewModel.openSpeechSettings()
                    }
                    CompactLink {
                        objectName: "settingsSoundSettingsLink"
                        tokens: root.tokens
                        text: qsTr("声音设置")
                        onClicked: MaintenanceViewModel.openSoundSettings()
                    }
                    CompactLink {
                        objectName: "settingsAppsSettingsLink"
                        tokens: root.tokens
                        text: qsTr("应用设置")
                        onClicked: MaintenanceViewModel.openAppsSettings()
                    }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: qsTr("移除后，本机所有无线麦版本都不能使用自定义按键映射。")
                    }
                    CompactButton {
                        objectName: "settingsRemoveHelperButton"
                        tokens: root.tokens
                        compactMinimumWidth: root.tokens.buttonWidth4Chars
                        text: qsTr("移除权限")
                        onClicked: removeHelperDialog.open()
                    }
                }
            }

            UiLabel {
                visible: root.feedbackText.length > 0
                tokens: root.tokens
                kind: noteKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: root.feedbackText
                color: root.feedbackIsError
                    ? root.tokens.errorColor : root.tokens.textSecondary
                Accessible.name: text
            }

            Item { Layout.preferredHeight: tokens.pageVerticalPadding }
        }
    }

    SettingsDialog {
        id: restoreDefaultsDialog
        objectName: "restoreDefaultsDialog"
        tokens: root.tokens
        preferredWidth: 420
        title: qsTr("恢复内置默认？")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: MappingViewModel.restoreDefaults()

        contentItem: ColumnLayout {
            spacing: root.tokens.spacingSmall
            UiLabel {
                tokens: root.tokens
                kind: bodyKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("所有按键动作将恢复为内置默认值。")
            }
        }
    }

    SettingsDialog {
        id: deletePresetDialog
        objectName: "deletePresetDialog"
        tokens: root.tokens
        preferredWidth: 420
        title: qsTr("删除配置？")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: root.showFeedback(MappingViewModel.deletePreset(
            root.presetIdAt(presetCombo.currentIndex)))

        contentItem: ColumnLayout {
            spacing: root.tokens.spacingSmall
            UiLabel {
                tokens: root.tokens
                kind: bodyKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("删除后无法恢复该按键配置。")
            }
        }
    }

    FileDialog {
        id: exportFileDialog
        objectName: "presetExportFileDialog"
        title: qsTr("导出按键配置")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("按键配置 (*.json)")]
        onAccepted: root.showFeedback(MappingViewModel.exportPreset(
            root.presetIdAt(presetCombo.currentIndex), String(selectedFile)))
    }

    FileDialog {
        id: importFileDialog
        objectName: "presetImportFileDialog"
        title: qsTr("导入按键配置")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("按键配置 (*.json)")]
        onAccepted: root.showFeedback(
            MappingViewModel.importPreset(String(selectedFile)))
    }

    FileDialog {
        id: customProgramFileDialog
        objectName: "customProgramFileDialog"
        title: qsTr("选择语音程序")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("程序 (*.exe *.lnk)")]
        onAccepted: root.showFeedback(
            VoiceViewModel.pickCustomProgramPath(String(selectedFile)))
    }

    SettingsDialog {
        id: removeHelperDialog
        objectName: "removeHelperDialog"
        tokens: root.tokens
        preferredWidth: 420
        title: qsTr("移除按键映射权限？")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: MaintenanceViewModel.removeHelper()

        contentItem: ColumnLayout {
            spacing: root.tokens.spacingSmall
            UiLabel {
                tokens: root.tokens
                kind: bodyKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("移除后，本机所有无线麦版本都不能使用自定义按键映射。")
            }
        }
    }
}
