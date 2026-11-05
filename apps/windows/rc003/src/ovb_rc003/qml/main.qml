import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.platform as Platform
import OvbRc003Presentation 1.0

// 应用外壳：只做窗口、导航、托盘与退出生命周期；
// 所有业务内容都在 HomePanel / KeysPanel / SettingsPanel 中，只绑定展示层。
ApplicationWindow {
    id: window
    title: AppViewModel.windowTitle
    width: 720
    height: 560
    minimumWidth: 640
    minimumHeight: 480
    visible: true
    readonly property string preferredWindowsUiFont: "Microsoft YaHei UI"
    readonly property bool preferredWindowsUiFontAvailable:
        Qt.platform.os === "windows"
        && Qt.fontFamilies().indexOf(preferredWindowsUiFont) >= 0

    property Tokens tokens: Tokens {
        fontFamily: window.preferredWindowsUiFontAvailable
            ? window.preferredWindowsUiFont : Qt.application.font.family
    }
    readonly property color nativeCaptionColor: tokens.windowFrame
    readonly property color nativeCaptionTextColor: tokens.textPrimary
    readonly property color nativeBorderColor: tokens.nativeWindowBorder

    // 启动时的后端工作（启动遥控器服务、启动期检查）由展示层决定，
    // 视图只说"窗口已就绪"。--background 自启动路径允许隐藏启动（D3 保留）。
    Component.onCompleted: {
        if (AppViewModel.startHidden)
            window.hide()
        AppViewModel.onWindowReady()
    }

    // 视图只负责"什么时候叫一声"，叫了之后做什么由展示层决定。
    Timer {
        interval: 1000
        repeat: true
        running: true
        onTriggered: AppViewModel.tick()
    }
    Timer {
        interval: 5000
        repeat: false
        running: true
        onTriggered: AppViewModel.startupSettled()
    }

    component ClientShellCorner: Item {
        property bool rightSide: false
        property bool bottomSide: false
        property color contentColor: window.tokens.background
        width: window.tokens.windowClientRadius
        height: window.tokens.windowClientRadius
        clip: true

        Rectangle {
            anchors.fill: parent
            color: window.tokens.windowFrame
        }
        Rectangle {
            width: parent.width * 2
            height: parent.height * 2
            x: parent.rightSide ? -parent.width : 0
            y: parent.bottomSide ? -parent.height : 0
            radius: width / 2
            color: parent.contentColor
            antialiasing: true
        }
    }

    property string applicationExitError: ""
    property string lifecycleErrorTitle: qsTr("操作未完成")
    property bool applicationExitInProgress: false

    // 重复启动时由现有实例恢复窗口（D3 保留）。
    Connections {
        target: AppViewModel
        function onWindowRestoreRequested() {
            window.restoreWindow()
        }
    }

    function restoreWindow() {
        window.showNormal()
        window.raise()
        window.requestActivate()
    }

    // 通用偏好只按展示层的封闭枚举取值，缺省值由外壳兜底。
    function preferenceValue(id, fallback) {
        const rows = MaintenanceViewModel.preferences
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i].id === id)
                return rows[i].value
        }
        return fallback
    }

    function performExit() {
        if (window.applicationExitInProgress)
            return
        const result = MaintenanceViewModel.confirmExitSave()
        if (result && result.ok) {
            window.applicationExitInProgress = true
            window.hide()
            Qt.quit()
            return
        }
        window.restoreWindow()
        window.lifecycleErrorTitle = qsTr("无法完全退出")
        window.applicationExitError = result ? result.message : ""
        exitFailedDialog.open()
    }

    onClosing: function(close) {
        if (window.applicationExitInProgress) {
            close.accepted = true
            return
        }
        close.accepted = false
        if (window.preferenceValue("hide_to_tray_on_close", true)) {
            window.hide()
        } else {
            window.performExit()
        }
    }

    Dialog {
        id: exitFailedDialog
        objectName: "exitFailedDialog"
        anchors.centerIn: parent
        modal: true
        title: window.lifecycleErrorTitle
        standardButtons: Dialog.Ok
        Label {
            width: 360
            text: window.applicationExitError
            wrapMode: Text.Wrap
            color: window.tokens.textPrimary
        }
    }

    // 托盘图标为静态产品图标；两种内置位置按顺序静默探测（Canvas 加载缺失
    // 文件不产生 QML 警告），取第一个实际存在的。
    property url trayIconSource: ""
    Canvas {
        id: trayIconProbe
        visible: false
        property var candidates: [
            Qt.resolvedUrl("../assets/icons/remote-mic.ico"),
            Qt.resolvedUrl("../app_icons/remote-mic.ico")
        ]
        function resolve() {
            for (let i = 0; i < candidates.length; ++i) {
                if (isImageLoaded(candidates[i])) {
                    window.trayIconSource = candidates[i]
                    return
                }
            }
        }
        onImageLoaded: resolve()
        Component.onCompleted: {
            for (let i = 0; i < candidates.length; ++i)
                loadImage(candidates[i])
        }
    }

    Platform.SystemTrayIcon {
        id: systemTrayIcon
        objectName: "systemTrayIcon"
        visible: true
        icon.source: window.trayIconSource
        tooltip: AppViewModel.windowTitle
        onActivated: function(reason) {
            if (reason !== Platform.SystemTrayIcon.Context)
                window.restoreWindow()
        }
        menu: Platform.Menu {
            Platform.MenuItem {
                text: qsTr("打开%1").arg(AppViewModel.windowTitle)
                onTriggered: window.restoreWindow()
            }
            Platform.MenuSeparator {}
            Platform.MenuItem {
                text: qsTr("完全退出")
                onTriggered: window.performExit()
            }
        }
    }

    // 重复启动恢复与状态刷新都走 AppViewModel.tick()，
    // 视图只定节奏，轮询什么由展示层决定。

    color: tokens.windowFrame
    font.family: tokens.fontFamily

    palette.window: tokens.background
    palette.windowText: tokens.textPrimary
    palette.button: tokens.buttonBackground
    palette.buttonText: tokens.buttonText
    palette.base: tokens.fieldBackground
    palette.text: tokens.textPrimary
    palette.highlight: tokens.accent
    palette.highlightedText: tokens.accentText

    Rectangle {
        id: clientShell
        objectName: "clientShell"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: tokens.windowFrameGap
        anchors.rightMargin: tokens.windowFrameGap
        anchors.bottomMargin: tokens.windowFrameGap
        color: tokens.background
        radius: tokens.windowClientRadius

        RowLayout {
            id: clientContent
            objectName: "clientContent"
            anchors.fill: parent
            spacing: 0

            Rectangle {
                id: navigationBar
                objectName: "navigationBar"
                Layout.preferredWidth: tokens.navigationWidth
                Layout.minimumWidth: tokens.navigationWidth
                Layout.maximumWidth: tokens.navigationWidth
                Layout.fillHeight: true
                color: tokens.sidebar

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: tokens.structuralDividerWidth
                    color: tokens.borderStrong
                }

                Column {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.topMargin: 8
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4
                    spacing: 3

                    NavButton {
                        id: homeTabButton
                        objectName: "homeTabButton"
                        tokens: window.tokens
                        text: qsTr("首页")
                        glyph: ""
                        checked: AppViewModel.currentPage === 0
                        onPressed: AppViewModel.currentPage = 0
                        Accessible.name: text
                        KeyNavigation.tab: mappingTabButton
                        KeyNavigation.backtab: settingsTabButton
                    }
                    NavButton {
                        id: mappingTabButton
                        objectName: "mappingTabButton"
                        tokens: window.tokens
                        text: qsTr("按键")
                        glyph: ""
                        checked: AppViewModel.currentPage === 1
                        onPressed: AppViewModel.currentPage = 1
                        Accessible.name: text
                        KeyNavigation.tab: settingsTabButton
                        KeyNavigation.backtab: homeTabButton
                    }
                    NavButton {
                        id: settingsTabButton
                        objectName: "settingsTabButton"
                        tokens: window.tokens
                        text: qsTr("设置")
                        glyph: ""
                        checked: AppViewModel.currentPage === 2
                        onPressed: AppViewModel.currentPage = 2
                        Accessible.name: text
                        KeyNavigation.tab: homeTabButton
                        KeyNavigation.backtab: mappingTabButton
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                StackLayout {
                    id: pageStack
                    objectName: "pageStack"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: AppViewModel.currentPage

                    HomePanel {
                        objectName: "homePanel"
                        tokens: window.tokens
                    }
                    KeysPanel {
                        objectName: "keysPanel"
                        tokens: window.tokens
                    }
                    SettingsPanel {
                        objectName: "settingsPanel"
                        tokens: window.tokens
                    }
                }

                Rectangle {
                    id: globalStatusBar
                    objectName: "globalStatusBar"
                    Layout.fillWidth: true
                    Layout.minimumHeight: tokens.statusBarMinHeight
                    Layout.preferredHeight: tokens.statusBarMinHeight
                    color: tokens.background

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: tokens.spacingMedium
                        anchors.rightMargin: tokens.spacingMedium
                        spacing: tokens.spacingSmall

                        UiLabel {
                            objectName: "bridgeStateLabel"
                            tokens: window.tokens
                            kind: noteKind
                            Layout.fillWidth: true
                            text: AppViewModel.bridgeStateLabel
                            color: tokens.textSecondary
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            Accessible.name: text
                        }

                        UiLabel {
                            objectName: "versionLabel"
                            tokens: window.tokens
                            kind: noteKind
                            text: AppViewModel.versionLabel
                            color: tokens.disabledText
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }

        ClientShellCorner {
            anchors.top: parent.top
            anchors.left: parent.left
            contentColor: tokens.sidebar
            z: 10
        }
        ClientShellCorner {
            anchors.top: parent.top
            anchors.right: parent.right
            rightSide: true
            contentColor: tokens.background
            z: 10
        }
        ClientShellCorner {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            bottomSide: true
            contentColor: tokens.sidebar
            z: 10
        }
        ClientShellCorner {
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            rightSide: true
            bottomSide: true
            contentColor: globalStatusBar.color
            z: 10
        }

        Rectangle {
            id: clientShellOutline
            objectName: "clientShellOutline"
            anchors.fill: parent
            color: "transparent"
            radius: tokens.windowClientRadius
            border.width: tokens.hairlineWidth
            border.color: tokens.windowFrameBorder
            antialiasing: true
            z: 20
        }
    }
}
