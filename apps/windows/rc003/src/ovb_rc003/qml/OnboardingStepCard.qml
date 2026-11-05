import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 一个验收步骤卡片：要做的事、实时状态、失败时唯一的修复入口。
// 修复按钮的文案自带失败原因（fixLabel），点击后返回受影响的那一步。
Rectangle {
    id: root

    property var tokens
    property var step
    property int stepIndex: 0
    property bool isCurrent: false
    property string guidance: ""
    property string stateLabel: ""
    property color stateColor: tokens ? tokens.disabledText : "gray"

    signal repairRequested()

    radius: tokens ? tokens.cornerRadiusControl : 6
    color: isCurrent && tokens ? tokens.accentSoft : (tokens ? tokens.surface : "white")
    border.width: isCurrent ? 1 : 0
    border.color: tokens ? tokens.accent : "transparent"
    implicitHeight: content.implicitHeight + 24

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            UiLabel {
                tokens: root.tokens
                kind: sectionTitleKind
                text: (root.stepIndex + 1) + ". " + (root.step ? root.step.title : "")
            }

            Rectangle {
                radius: height / 2
                color: root.stateColor
                opacity: 0.16
                implicitWidth: stateChip.implicitWidth + 14
                implicitHeight: 20

                UiLabel {
                    id: stateChip
                    anchors.centerIn: parent
                    tokens: root.tokens
                    kind: noteKind
                    text: root.stateLabel
                }
            }

            Item { Layout.fillWidth: true }
        }

        UiLabel {
            Layout.fillWidth: true
            tokens: root.tokens
            kind: noteKind
            wrapMode: Text.WordWrap
            text: root.guidance
        }

        UiLabel {
            Layout.fillWidth: true
            visible: text !== ""
            tokens: root.tokens
            wrapMode: Text.WordWrap
            text: root.step ? root.step.detail : ""
        }

        CompactButton {
            visible: root.step && root.step.fixLabel !== ""
            tokens: root.tokens
            text: root.step ? root.step.fixLabel : ""
            onClicked: root.repairRequested()
        }
    }
}
