import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 可折叠分区：标题行常驻，正文默认折叠（设置页的高级选项按此收纳）。
// 纯展示组件：只持有 tokens / 标题 / 折叠状态，不接触任何视图模型。
ColumnLayout {
    id: root

    property var tokens
    property string titleText: ""
    property string noteText: ""
    property bool folded: true
    default property alias contentData: sectionBody.contentData

    spacing: tokens.spacingSmall

    RowLayout {
        Layout.fillWidth: true
        spacing: tokens.spacingSmall

        CompactButton {
            objectName: root.objectName + "_foldToggle"
            tokens: root.tokens
            flat: true
            text: root.folded ? qsTr("展开") : qsTr("折叠")
            Accessible.name: root.titleText + (root.folded ? qsTr("，展开") : qsTr("，折叠"))
            onClicked: root.folded = !root.folded
        }

        UiLabel {
            tokens: root.tokens
            kind: sectionTitleKind
            text: root.titleText
            Layout.fillWidth: true
        }

        UiLabel {
            visible: root.noteText.length > 0
            tokens: root.tokens
            kind: noteKind
            text: root.noteText
            elide: Text.ElideRight
            HoverHandler { id: noteHover }
            CompactToolTip {
                tokens: root.tokens
                active: noteHover.hovered && root.noteText.length > 0
                text: root.noteText
            }
        }
    }

    SectionFrame {
        id: sectionBody
        objectName: root.objectName + "_body"
        tokens: root.tokens
        Layout.fillWidth: true
        visible: !root.folded
    }
}
