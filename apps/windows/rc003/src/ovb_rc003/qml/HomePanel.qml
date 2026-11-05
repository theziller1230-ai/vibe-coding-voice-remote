import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OvbRc003Presentation 1.0

// 首页：一张大状态卡（遥控器连接 / 电量 / 语音就绪 / 上次口述结果）
// 加一个主操作（口述测试）。其余内容一律不放。
Item {
    id: root

    property var tokens

    function toneColor(tone) {
        if (tone === "ok")
            return tokens.successColor
        if (tone === "warn")
            return tokens.voiceAccent
        if (tone === "error")
            return tokens.errorColor
        return tokens.textSecondary
    }

    // 状态卡中的一个事实行：色点 + 名称 + 值 + 可选补充说明。
    component StatusFacet: RowLayout {
        property var tokens
        property string labelText: ""
        property string valueText: ""
        property string noteText: ""
        property color dotColor: tokens.textSecondary

        Layout.fillWidth: true
        spacing: tokens.spacingMedium

        Rectangle {
            Layout.preferredWidth: 8
            Layout.preferredHeight: 8
            Layout.alignment: Qt.AlignVCenter
            radius: 4
            color: dotColor
        }

        UiLabel {
            tokens: parent.tokens
            kind: noteKind
            Layout.preferredWidth: 92
            text: labelText
        }

        UiLabel {
            tokens: parent.tokens
            kind: bodyKind
            Layout.fillWidth: true
            text: valueText
            color: tokens.textPrimary
            elide: Text.ElideRight
        }

        UiLabel {
            visible: noteText.length > 0
            tokens: parent.tokens
            kind: noteKind
            Layout.maximumWidth: 220
            text: noteText
            elide: Text.ElideRight
            HoverHandler { id: noteHover }
            CompactToolTip {
                tokens: parent.tokens
                active: noteHover.hovered && noteText.length > 0
                text: noteText
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: tokens.pageHorizontalPadding
        anchors.topMargin: tokens.pageVerticalPadding
        spacing: tokens.spacingLarge

        SectionFrame {
            objectName: "homeStatusCard"
            tokens: root.tokens
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: tokens.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: tokens.spacingMedium

                    UiLabel {
                        tokens: root.tokens
                        kind: pageTitleKind
                        text: AppViewModel.statusCard.title
                        elide: Text.ElideRight
                    }

                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: AppViewModel.statusCard.subtitle
                        color: root.toneColor(AppViewModel.statusCard.tone)
                        elide: Text.ElideRight
                    }

                    Item { Layout.fillWidth: true }
                }

                UiLabel {
                    visible: text.length > 0
                    tokens: root.tokens
                    kind: noteKind
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: AppViewModel.statusCard.detail
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: tokens.hairlineWidth
                    color: tokens.border
                }

                StatusFacet {
                    objectName: "homeFacetConnection"
                    tokens: root.tokens
                    labelText: qsTr("遥控器连接")
                    valueText: DeviceViewModel.connectionCard.title
                    noteText: DeviceViewModel.connectionCard.subtitle
                    dotColor: root.toneColor(DeviceViewModel.connectionCard.tone)
                }

                StatusFacet {
                    objectName: "homeFacetBattery"
                    tokens: root.tokens
                    labelText: qsTr("电量")
                    valueText: DeviceViewModel.batteryLabel
                    dotColor: root.tokens.textSecondary
                }

                StatusFacet {
                    objectName: "homeFacetVoice"
                    tokens: root.tokens
                    labelText: qsTr("语音就绪")
                    valueText: VoiceViewModel.voiceCard.title
                    noteText: VoiceViewModel.voiceCard.subtitle
                    dotColor: root.toneColor(VoiceViewModel.voiceCard.tone)
                }

                StatusFacet {
                    objectName: "homeFacetDictation"
                    tokens: root.tokens
                    labelText: qsTr("上次口述结果")
                    valueText: VoiceViewModel.lastValidation.message.length > 0
                        ? VoiceViewModel.lastValidation.message
                        : qsTr("尚未进行口述测试")
                    dotColor: VoiceViewModel.lastValidation.message.length === 0
                        ? root.tokens.textSecondary
                        : VoiceViewModel.lastValidation.ok
                            ? root.tokens.successColor : root.tokens.errorColor
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: tokens.spacingSmall

            Item { Layout.fillWidth: true }

            CompactButton {
                objectName: "homePrimaryActionButton"
                tokens: root.tokens
                highlighted: true
                compactMinimumWidth: tokens.buttonWidth6Chars
                text: AppViewModel.statusCard.actionLabel
                Accessible.name: text
                onClicked: VoiceViewModel.testDictation()
            }

            Item { Layout.fillWidth: true }
        }

        UiLabel {
            objectName: "dictationHonestyNote"
            tokens: root.tokens
            kind: noteKind
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            // D9：后端无法判定文字是否真的来自口述，如实标注，不夸大。
            text: qsTr("口述测试只确认：语音链路就绪、录音会话完整、目标输入框文字有新增。无法区分手工输入、粘贴与真实口述，「手工输入不算」当前不可验证。")
            color: tokens.disabledText
        }

        Item { Layout.fillHeight: true }
    }
}
