import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OvbRc003Presentation 1.0

// 首次使用验收向导：展示步骤状态、每步要做的事与修复入口。
// 只绑定展示层：状态与验证结果全部来自 OnboardingViewModel，
// 这里不出现任何后端概念（设备 id、配置键、状态码）。
Item {
    id: root

    property var tokens
    readonly property bool allDone: {
        var rows = OnboardingViewModel.steps
        for (var i = 0; i < rows.length; ++i) {
            if (rows[i].state !== "done") {
                return false
            }
        }
        return rows.length > 0
    }

    function guidanceFor(index) {
        switch (index) {
        case 0:
            return "请为遥控器装好电池并完成 Windows 蓝牙配对，然后按下遥控器任意按键，让软件确认设备已连接并在发送按键。"
        case 1:
            return "接收按键需要管理员授权。请在系统弹出授权提示时选择“是”；软件会检测授权后的按键接收通道是否就绪。"
        case 2:
            return "语音走虚拟声卡：请确认 VB-CABLE 已安装，并在设置中把语音输出端点选为 CABLE Input。软件会实际发送测试音，确认 CABLE Input 与 CABLE Output 两端相通。"
        case 3:
            return "请选择语音转写工具（例如豆包输入法），并在该工具的设置里把麦克风选为 CABLE Output；然后在工具中开始一次麦克风采集，软件会检测它的采集会话。"
        case 4:
            return "口述验收：请在记事本等系统文本框中点击放置光标；短按一次遥控器语音键（用于按键检测），再按住语音键说话、松开结束。只有完整观察到“语音键 → 新采集会话 → 非空音频 → 会话结束 → 文字上屏”才通过，请不要手工输入或粘贴文字。"
        default:
            return ""
        }
    }

    function stateLabel(state) {
        switch (state) {
        case "done":
            return "已完成"
        case "current":
            return "进行中"
        case "failed":
            return "需修复"
        default:
            return "待完成"
        }
    }

    function stateColor(state) {
        switch (state) {
        case "done":
            return tokens.successColor
        case "current":
            return tokens.accent
        case "failed":
            return tokens.errorColor
        default:
            return tokens.disabledText
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        UiLabel {
            Layout.fillWidth: true
            tokens: root.tokens
            kind: pageTitleKind
            text: "首次使用验收向导"
        }

        UiLabel {
            Layout.fillWidth: true
            tokens: root.tokens
            kind: noteKind
            wrapMode: Text.WordWrap
            text: "每一步都要真实验证通过才能继续；没有“跳过”。失败时按提示修复后重新验证，修复只会回到受影响的那一步。"
        }

        Repeater {
            model: OnboardingViewModel.steps

            delegate: OnboardingStepCard {
                required property var modelData
                required property int index

                Layout.fillWidth: true
                tokens: root.tokens
                step: modelData
                stepIndex: index
                isCurrent: index === OnboardingViewModel.currentStep
                guidance: root.guidanceFor(index)
                stateLabel: root.stateLabel(modelData.state)
                stateColor: root.stateColor(modelData.state)
                onRepairRequested: OnboardingViewModel.repair(modelData.id)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            CompactButton {
                tokens: root.tokens
                text: "上一步"
                enabled: OnboardingViewModel.currentStep > 0
                onClicked: OnboardingViewModel.back()
            }

            CompactButton {
                tokens: root.tokens
                text: "验证本步"
                highlighted: true
                onClicked: OnboardingViewModel.verifyCurrent()
            }

            CompactButton {
                tokens: root.tokens
                text: "下一步"
                enabled: OnboardingViewModel.canContinue
                    && OnboardingViewModel.currentStep < OnboardingViewModel.steps.length - 1
                onClicked: OnboardingViewModel.next()
            }

            Item { Layout.fillWidth: true }

            UiLabel {
                tokens: root.tokens
                kind: noteKind
                visible: root.allDone
                text: "全部验收通过；设置已保存。"
            }
        }
    }
}
