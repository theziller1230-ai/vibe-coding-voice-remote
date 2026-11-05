import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Dialogs
import OvbRc003Presentation 1.0

// 按键页：产品图热点 + 一行一按键的映射矩阵。
// 所有映射内容只来自 MappingViewModel.buttons 的 ButtonRow 值；
// 选中状态是纯视图态；编辑经 setAction(buttonId, gesture, actionText) 转发。
Item {
    id: root

    property var tokens

    // 视图态：当前选中的按键（仅用于高亮与连线）。
    property string selectedButtonId: ""
    property bool connectorRepaintQueued: false

    onSelectedButtonIdChanged: scheduleConnectorRepaint()
    Component.onCompleted: probePhoto()

    // 版式按行集合区分（含 YouTube/Netflix 等键的为 Chromecast 版式）。
    readonly property bool chromecastLayout: {
        const rows = MappingViewModel.buttons
        for (let i = 0; i < rows.length; ++i) {
            const id = rows[i].id
            if (id === "volume_mute" || id === "youtube"
                    || id === "netflix" || id === "input_source")
                return true
        }
        return false
    }

    readonly property real mappingCardGap: 2
    readonly property real mappingBoardGap: 6
    readonly property real mappingPhotoColumnWidth: 114
    // GridLayout rounds child widths to whole logical pixels. Keep both
    // columns integral so the rightmost card cannot grow past the clip.
    readonly property int mappingCardColumnWidth: Math.floor(
        (mappingList.width - mappingPhotoColumnWidth - mappingBoardGap * 2) / 2
    )
    readonly property real mappingKeyLabelWidth: 56

    readonly property var leftButtonIds: chromecastLayout
        ? ["up", "left", "down", "back", "home", "youtube", "power"]
        : ["power", "up", "left", "back", "home", "menu"]

    // 产品图热点标定（视图专属版式数据）：按键 id ->
    // [中心x, 中心y, 宽, 高, 是否语音键]，均为照片自身宽高的比例。
    readonly property var rc003Hotspots: ({
        "power": [0.386, 0.099, 0.15, 0.072, false],
        "mic": [0.630, 0.099, 0.15, 0.072, true],
        "up": [0.502, 0.179, 0.18, 0.065, false],
        "left": [0.362, 0.246, 0.15, 0.080, false],
        "ok": [0.502, 0.246, 0.19, 0.095, false],
        "right": [0.638, 0.246, 0.15, 0.080, false],
        "down": [0.502, 0.317, 0.18, 0.065, false],
        "back": [0.406, 0.389, 0.17, 0.080, false],
        "volume_up": [0.604, 0.390, 0.16, 0.080, false],
        "home": [0.406, 0.479, 0.17, 0.080, false],
        "volume_down": [0.604, 0.480, 0.16, 0.080, false],
        "menu": [0.406, 0.569, 0.17, 0.080, false],
        "tv": [0.604, 0.569, 0.17, 0.080, false]
    })

    readonly property var chromecastHotspots: ({
        "up": [0.50, 0.060, 0.22, 0.045, false],
        "left": [0.20, 0.152, 0.17, 0.065, false],
        "ok": [0.50, 0.152, 0.28, 0.095, false],
        "right": [0.81, 0.152, 0.17, 0.065, false],
        "down": [0.50, 0.250, 0.22, 0.045, false],
        "back": [0.26, 0.355, 0.28, 0.090, false],
        "mic": [0.73, 0.355, 0.28, 0.090, true],
        "home": [0.26, 0.483, 0.28, 0.090, false],
        "volume_mute": [0.73, 0.483, 0.28, 0.090, false],
        "youtube": [0.26, 0.612, 0.28, 0.090, false],
        "netflix": [0.73, 0.612, 0.28, 0.090, false],
        "power": [0.26, 0.733, 0.16, 0.052, false],
        "input_source": [0.73, 0.733, 0.16, 0.052, false],
        "volume_up": [0.98, 0.208, 0.04, 0.035, false],
        "volume_down": [0.98, 0.252, 0.04, 0.035, false]
    })

    function hotspotFor(buttonId) {
        // Total on purpose: during a profile switch the delegates re-evaluate
        // for one frame before `chromecastLayout` recomputes, so an id from the
        // incoming layout can be looked up against the outgoing one.
        const map = chromecastLayout ? chromecastHotspots : rc003Hotspots
        const hotspot = map[buttonId]
        return hotspot !== undefined ? hotspot : []
    }

    function isLeftButton(buttonId) {
        return leftButtonIds.indexOf(buttonId) >= 0
    }

    function visualRow(buttonId) {
        // Same one-pass race as hotspotFor: fall back to row 0 rather than
        // handing QML an undefined int.
        let row
        if (chromecastLayout) {
            const chromeRows = {
                "up": 0, "left": 1, "down": 2,
                "ok": 0, "right": 1, "volume_up": 2, "volume_down": 3,
                "back": 3, "mic": 4, "home": 4, "volume_mute": 5,
                "youtube": 5, "netflix": 6, "power": 6, "input_source": 7
            }
            row = chromeRows[buttonId]
        } else {
            const rows = {
                "power": 0, "up": 1, "left": 2, "back": 3, "home": 4, "menu": 5,
                "mic": 0, "right": 1, "ok": 2, "down": 3,
                "volume_up": 4, "volume_down": 5, "tv": 6
            }
            row = rows[buttonId]
        }
        return row !== undefined ? row : 0
    }

    // ---- 产品图（内置产品图的候选位置逐个尝试，缺图时降级为纯文字矩阵） ----
    readonly property string photoFile: chromecastLayout
        ? "Chromecast-remote-photo.png" : "RC003-remote-photo.png"
    readonly property var photoCandidates: [
        Qt.resolvedUrl("../../../../../../Resources/" + photoFile),
        Qt.resolvedUrl("../Resources/" + photoFile),
        Qt.resolvedUrl("../../Resources/" + photoFile)
    ]
    // 候选位置静默探测（Canvas 加载缺失文件不产生警告），取第一个实际存在的。
    property string photoSourceUrl: ""
    property int photoProbesPending: 0
    onPhotoFileChanged: Qt.callLater(probePhoto)
    readonly property bool photoAvailable: photoImage.status === Image.Ready

    function probePhoto() {
        photoSourceUrl = ""
        photoProbesPending = photoCandidates.length
        for (let i = 0; i < photoCandidates.length; ++i)
            photoProbeCanvas.loadImage(photoCandidates[i])
    }

    function resolvePhotoProbe() {
        for (let i = 0; i < photoCandidates.length; ++i) {
            if (photoProbeCanvas.isImageLoaded(photoCandidates[i])) {
                photoSourceUrl = photoCandidates[i]
                photoProbesPending = 0
                return
            }
        }
    }

    Canvas {
        id: photoProbeCanvas
        visible: false
        onImageLoaded: {
            root.photoProbesPending = Math.max(0, root.photoProbesPending - 1)
            root.resolvePhotoProbe()
        }
    }

    // ---- 行卡片与热点之间的连线 ----
    function scheduleConnectorRepaint() {
        if (connectorRepaintQueued)
            return
        connectorRepaintQueued = true
        Qt.callLater(function() {
            connectorRepaintQueued = false
            mappingLines.requestPaint()
            activeMappingLine.requestPaint()
        })
    }

    function connectorControlRadius(startX, endX) {
        const span = Math.abs(endX - startX)
        const preferred = Math.max(12, Math.min(72, span * 0.56))
        return Math.min(preferred, span * 0.48)
    }

    function connectorStrokeColor(active) {
        if (active)
            return tokens.accent
        return tokens.borderStrong
    }

    function connectorRoute(card, hotspot, coordinateItem) {
        if (!card || !hotspot)
            return null

        const leftSide = root.isLeftButton(hotspot.buttonId)
        const start = card.mapToItem(
            coordinateItem,
            leftSide ? card.width : 0,
            card.height / 2
        )
        const center = hotspot.mapToItem(
            coordinateItem,
            hotspot.width / 2,
            hotspot.height / 2
        )
        // Chromecast connectors stop at the marker edge;
        // so neither the photo silhouette nor the line obscures the key symbol.
        const endX = center.x + (root.chromecastLayout || hotspot.buttonId === "ok"
            ? 0 : (leftSide ? -1 : 1) * hotspot.width / 2)
        const endY = center.y - (root.chromecastLayout && hotspot.buttonId === "ok"
            ? hotspot.height / 2 : 0)
        const direction = leftSide ? 1 : -1
        // Both profiles use one uninterrupted cubic over the full endpoint
        // span, with horizontal tangents. Do not squeeze its bend into a gutter.
        const controlRadius = root.connectorControlRadius(start.x, endX)
        const control1X = start.x + direction * controlRadius
        const control1Y = start.y
        const control2X = endX - direction * controlRadius
        const control2Y = endY
        return {
            startX: start.x,
            startY: start.y,
            control1X: control1X,
            control1Y: control1Y,
            control2X: control2X,
            control2Y: control2Y,
            endX: endX,
            endY: endY
        }
    }

    function paintConnectors(canvas, activeOnly) {
        const ctx = canvas.getContext("2d")
        ctx.reset()
        const rows = MappingViewModel.buttons
        for (let i = 0; i < rows.length; i++) {
            const leftCard = leftCardRepeater.itemAt(i)
            const rightCard = rightCardRepeater.itemAt(i)
            const hotspot = photoHotspotRepeater.itemAt(i)
            const buttonId = hotspot ? hotspot.buttonId : ""
            const active = root.selectedButtonId === buttonId
            if (active !== activeOnly)
                continue
            const card = root.isLeftButton(buttonId) ? leftCard : rightCard
            if (!card || !hotspot || !card.visible || !hotspot.visible)
                continue
            const route = root.connectorRoute(card, hotspot, canvas)
            if (!route)
                continue
            ctx.beginPath()
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            ctx.moveTo(route.startX, route.startY)
            ctx.bezierCurveTo(
                route.control1X,
                route.control1Y,
                route.control2X,
                route.control2Y,
                route.endX,
                route.endY
            )
            ctx.strokeStyle = root.connectorStrokeColor(active)
            ctx.lineWidth = active ? 2.2 : 1.25
            ctx.stroke()
        }
    }

    // ---- 动作编辑（只转发 setAction，不理解动作语义） ----
    property string editButtonId: ""
    property string editButtonLabel: ""
    property bool editIsMic: false
    property var originalTexts: ({})
    property var originalNotes: ({})
    property var originalPaths: ({})
    property var originalContents: ({})
    property string captureTargetGesture: ""
    property string pickTargetGesture: ""
    property string recorderPreviewText: ""

    function openEditor(row) {
        editButtonId = row.id
        editButtonLabel = row.label
        editIsMic = row.isMic
        originalTexts = {
            "single": String(row.single),
            "double": String(row.double),
            "longPress": String(row.longPress)
        }
        originalNotes = {
            "single": String(row.singleNote ? row.singleNote : ""),
            "double": String(row.doubleNote ? row.doubleNote : ""),
            "longPress": String(row.longNote ? row.longNote : "")
        }
        originalPaths = {
            "single": String(MappingViewModel.programPath(editButtonId, "single")),
            "double": String(MappingViewModel.programPath(editButtonId, "double")),
            "longPress": String(MappingViewModel.programPath(editButtonId, "longPress"))
        }
        originalContents = {
            "single": String(MappingViewModel.textContent(editButtonId, "single")),
            "double": String(MappingViewModel.textContent(editButtonId, "double")),
            "longPress": String(MappingViewModel.textContent(editButtonId, "longPress"))
        }
        editorSingleField.text = String(row.single)
        editorDoubleField.text = String(row.double)
        editorLongField.text = String(row.longPress)
        editorSingleNoteField.text = originalNotes["single"]
        editorDoubleNoteField.text = originalNotes["double"]
        editorLongNoteField.text = originalNotes["longPress"]
        editorSinglePathField.text = originalPaths["single"]
        editorDoublePathField.text = originalPaths["double"]
        editorLongPathField.text = originalPaths["longPress"]
        editorSingleContentField.text = originalContents["single"]
        editorDoubleContentField.text = originalContents["double"]
        editorLongContentField.text = originalContents["longPress"]
        editorErrorLabel.text = ""
        actionEditor.open()
    }

    function normalizedText(text) {
        // TextArea 会把 CRLF 归一成 LF：比较时归一化，未改动不回写，
        // 保住模型里原有的 CRLF。
        return String(text).replace(/\r\n/g, "\n")
    }

    function commitEditor() {
        // 提交顺序：先落载荷（输入文字 / 程序路径），再切动作类型，最后备注。
        // 动作类型校验需要先看到本格的草稿载荷，否则切换到输入文字 / 打开程序
        // 会被“请填写…”误拒；载荷先落库也避免被后续自动保存丢弃。
        const contentEdits = [
            ["single", editorSingleContentField.text],
            ["double", editorDoubleContentField.text],
            ["longPress", editorLongContentField.text]
        ]
        for (let i = 0; i < contentEdits.length; ++i) {
            const gesture = contentEdits[i][0]
            const content = contentEdits[i][1]
            if (root.normalizedText(content)
                    === root.normalizedText(originalContents[gesture]))
                continue
            const result = MappingViewModel.setTextContent(
                editButtonId, gesture, content)
            if (result && !result.ok) {
                editorErrorLabel.text = result.message
                return
            }
            originalContents[gesture] = content
        }
        const pathEdits = [
            ["single", editorSinglePathField.text],
            ["double", editorDoublePathField.text],
            ["longPress", editorLongPathField.text]
        ]
        for (let i = 0; i < pathEdits.length; ++i) {
            const gesture = pathEdits[i][0]
            const trimmed = pathEdits[i][1].trim()
            if (trimmed === originalPaths[gesture].trim())
                continue
            const result = MappingViewModel.pickProgramPath(
                editButtonId, gesture, root.toFileUrl(trimmed))
            if (result && !result.ok) {
                editorErrorLabel.text = result.message
                return
            }
            originalPaths[gesture] = trimmed
        }
        const edits = [
            ["single", editorSingleField.text],
            ["double", editorDoubleField.text],
            ["longPress", editorLongField.text]
        ]
        for (let i = 0; i < edits.length; ++i) {
            const gesture = edits[i][0]
            const trimmed = edits[i][1].trim()
            if (trimmed === originalTexts[gesture].trim())
                continue
            const result = MappingViewModel.setAction(
                editButtonId, gesture,
                trimmed.length > 0 ? trimmed : qsTr("未设置"))
            if (result && !result.ok) {
                editorErrorLabel.text = result.message
                return
            }
            originalTexts[gesture] = trimmed
        }
        const noteEdits = [
            ["single", editorSingleNoteField.text],
            ["double", editorDoubleNoteField.text],
            ["longPress", editorLongNoteField.text]
        ]
        for (let i = 0; i < noteEdits.length; ++i) {
            const gesture = noteEdits[i][0]
            const trimmed = noteEdits[i][1].trim()
            if (trimmed === originalNotes[gesture].trim())
                continue
            const result = MappingViewModel.setNote(editButtonId, gesture, trimmed)
            if (result && !result.ok) {
                editorErrorLabel.text = result.message
                return
            }
            originalNotes[gesture] = trimmed
        }
        actionEditor.close()
    }

    function gestureField(gesture) {
        return gesture === "single" ? editorSingleField
            : gesture === "double" ? editorDoubleField : editorLongField
    }

    function pathField(gesture) {
        return gesture === "single" ? editorSinglePathField
            : gesture === "double" ? editorDoublePathField : editorLongPathField
    }

    function toFileUrl(path) {
        let normalized = path.replace(/\\/g, "/")
        if (/^[A-Za-z]:\//.test(normalized))
            return "file:///" + encodeURI(normalized)
        return encodeURI(normalized)
    }

    function openRecorder(gesture) {
        captureTargetGesture = gesture
        recorderPreviewText = qsTr("请按下希望遥控器发送的键盘快捷键")
        shortcutRecorder.open()
        MappingViewModel.captureShortcut()
    }

    function finishRecorder() {
        MappingViewModel.stopShortcutCapture()
        captureTargetGesture = ""
        shortcutRecorder.close()
    }

    function browseProgram(gesture) {
        pickTargetGesture = gesture
        programFileDialog.open()
    }

    function commitProgramPick(fileUrl) {
        const result = MappingViewModel.pickProgramPath(
            editButtonId, pickTargetGesture, fileUrl)
        if (!result)
            return
        if (result.ok) {
            pathField(pickTargetGesture).text = result.message
            originalPaths[pickTargetGesture] = String(result.message).trim()
        } else {
            editorErrorLabel.text = result.message
        }
    }

    ColumnLayout {
        id: pageColumn
        anchors.fill: parent
        anchors.margins: tokens.pageHorizontalPadding
        spacing: tokens.spacingSmall

        RowLayout {
            visible: MappingViewModel.mappingAutoSaveRetryAvailable
            Layout.fillWidth: true
            spacing: tokens.spacingSmall

            UiLabel {
                tokens: root.tokens
                kind: noteKind
                Layout.fillWidth: true
                text: qsTr("按键映射正在等待自动保存。")
                color: root.tokens.voiceAccent
                elide: Text.ElideRight
            }
            CompactButton {
                objectName: "retryMappingAutoSaveButton"
                tokens: root.tokens
                compactMinimumWidth: root.tokens.buttonWidth4Chars
                text: qsTr("重试保存")
                onClicked: MappingViewModel.retryMappingAutoSave()
            }
        }

        Flickable {
            id: mappingList
            objectName: "mappingList"
            clip: true
            contentWidth: width
            contentHeight: root.chromecastLayout
                ? Math.max(height, leftSideCards.implicitHeight,
                          rightSideCards.implicitHeight)
                : height
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                objectName: "mappingScrollBar"
                policy: ScrollBar.AsNeeded
                // Use the page gutter, not the right-hand mapping cards.
                parent: root
                x: pageColumn.x + mappingList.x + mappingList.width
                y: pageColumn.y + mappingList.y
                height: mappingList.height
            }
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 306
            onWidthChanged: root.scheduleConnectorRepaint()
            onHeightChanged: root.scheduleConnectorRepaint()

            Canvas {
                id: mappingLines
                objectName: "mappingLines"
                anchors.fill: parent
                z: 0
                antialiasing: true
                onPaint: root.paintConnectors(mappingLines, false)
                onWidthChanged: root.scheduleConnectorRepaint()
                onHeightChanged: root.scheduleConnectorRepaint()
            }

            Canvas {
                id: activeMappingLine
                objectName: "activeMappingLine"
                anchors.fill: parent
                z: 2
                antialiasing: true
                onPaint: root.paintConnectors(activeMappingLine, true)
                onWidthChanged: root.scheduleConnectorRepaint()
                onHeightChanged: root.scheduleConnectorRepaint()
            }

            GridLayout {
                id: leftSideCards
                objectName: "leftMappingCards"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: root.mappingCardColumnWidth
                columns: 1
                rows: root.chromecastLayout ? 7 : 6
                rowSpacing: root.mappingCardGap
                z: 3
                onXChanged: root.scheduleConnectorRepaint()
                onYChanged: root.scheduleConnectorRepaint()
                onWidthChanged: root.scheduleConnectorRepaint()
                onHeightChanged: root.scheduleConnectorRepaint()

                Repeater {
                    id: leftCardRepeater
                    model: MappingViewModel.buttons
                    onItemAdded: root.scheduleConnectorRepaint()
                    delegate: MappingCard {
                        required property var modelData
                        readonly property string buttonId: modelData.id

                        visible: root.isLeftButton(buttonId)
                        exposeObjectNames: visible
                        tokens: root.tokens
                        cardId: buttonId
                        Layout.row: root.visualRow(buttonId)
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? implicitHeight : 0
                        buttonName: modelData.label
                        keyLabelWidth: root.mappingKeyLabelWidth
                        singleText: modelData.single
                        doubleText: modelData.double
                        longText: modelData.longPress
                        singleNoteText: modelData.singleNote
                            ? modelData.singleNote : ""
                        doubleNoteText: modelData.doubleNote
                            ? modelData.doubleNote : ""
                        longNoteText: modelData.longNote
                            ? modelData.longNote : ""
                        selected: root.selectedButtonId === buttonId
                        voiceAction: modelData.isMic
                        onXChanged: root.scheduleConnectorRepaint()
                        onYChanged: root.scheduleConnectorRepaint()
                        onWidthChanged: root.scheduleConnectorRepaint()
                        onHeightChanged: root.scheduleConnectorRepaint()
                        onVisibleChanged: root.scheduleConnectorRepaint()
                        Component.onCompleted: root.scheduleConnectorRepaint()
                        onClicked: {
                            root.selectedButtonId = buttonId
                            root.openEditor(modelData)
                        }
                    }
                }
            }

            Item {
                id: photoSidebar
                objectName: "photoSidebar"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                width: root.mappingPhotoColumnWidth
                height: photoFrame.height + 20
                z: 1
                onXChanged: root.scheduleConnectorRepaint()
                onYChanged: root.scheduleConnectorRepaint()

                Item {
                    id: photoFrame
                    objectName: "photoFrame"
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 86
                    height: root.chromecastLayout ? 250 : 270
                    // Keep the photo crop, but let the shadow extend beyond
                    // the image without moving its hotspots.
                    clip: !root.chromecastLayout
                    onXChanged: root.scheduleConnectorRepaint()
                    onYChanged: root.scheduleConnectorRepaint()

                    Image {
                        id: photoImage
                        objectName: "photoImage"
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.verticalCenter: parent.verticalCenter
                        width: root.chromecastLayout
                            ? parent.width : height * 240 / 360
                        height: parent.height
                        source: root.photoSourceUrl
                        fillMode: root.chromecastLayout
                            ? Image.PreserveAspectFit : Image.Stretch
                        smooth: true
                        mipmap: true
                        layer.enabled: root.chromecastLayout
                            && root.photoAvailable
                            && GraphicsInfo.shaderType === GraphicsInfo.RhiShader
                        layer.effect: MultiEffect {
                            shadowEnabled: true
                            shadowColor: root.tokens.remotePhotoShadowColor
                            shadowBlur: 1.0
                            blurMax: root.tokens.remotePhotoShadowRadius
                            shadowHorizontalOffset: 0
                            shadowVerticalOffset: root.tokens.remotePhotoShadowOffset
                        }
                        onXChanged: root.scheduleConnectorRepaint()
                        onYChanged: root.scheduleConnectorRepaint()
                        onPaintedWidthChanged: root.scheduleConnectorRepaint()
                        onPaintedHeightChanged: root.scheduleConnectorRepaint()
                    }

                    UiLabel {
                        anchors.fill: parent
                        visible: root.photoSourceUrl.length === 0
                            && root.photoProbesPending === 0
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("实物图缺失")
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    Repeater {
                        id: photoHotspotRepeater
                        model: MappingViewModel.buttons
                        onItemAdded: root.scheduleConnectorRepaint()
                        delegate: Item {
                            id: photoHotspot
                            required property var modelData
                            readonly property string buttonId: modelData.id
                            readonly property var hotspot: root.hotspotFor(buttonId)
                            readonly property bool hasHotspot:
                                hotspot ? hotspot.length > 0 : false
                            readonly property bool hotspotIsVoice:
                                hasHotspot && hotspot[4] === true
                            readonly property bool isSelected:
                                root.selectedButtonId === buttonId

                            width: hasHotspot ? hotspot[2] * photoImage.paintedWidth : 0
                            height: hasHotspot ? hotspot[3] * photoImage.paintedHeight : 0
                            x: photoImage.x
                                + (photoImage.width - photoImage.paintedWidth) / 2
                                + (hasHotspot ? hotspot[0] * photoImage.paintedWidth : 0)
                                - width / 2
                            y: photoImage.y
                                + (photoImage.height - photoImage.paintedHeight) / 2
                                + (hasHotspot ? hotspot[1] * photoImage.paintedHeight : 0)
                                - height / 2
                            visible: root.photoAvailable && hasHotspot
                            z: 2
                            onXChanged: root.scheduleConnectorRepaint()
                            onYChanged: root.scheduleConnectorRepaint()

                            Rectangle {
                                objectName: "photoHotspotMarker_" + photoHotspot.buttonId
                                anchors.fill: parent
                                z: 1
                                visible: photoHotspot.isSelected
                                radius: Math.min(width, height) / 2
                                color: photoHotspot.hotspotIsVoice
                                    ? Qt.rgba(tokens.voiceAccent.r, tokens.voiceAccent.g,
                                              tokens.voiceAccent.b, 0.24)
                                    : Qt.rgba(tokens.accent.r, tokens.accent.g,
                                              tokens.accent.b, 0.18)
                                border.width: 2
                                border.color: photoHotspot.hotspotIsVoice
                                    ? tokens.voiceAccent : tokens.accent
                            }

                            TapHandler {
                                onTapped: root.selectedButtonId = photoHotspot.buttonId
                            }
                            HoverHandler { id: hotspotHover }
                            Rectangle {
                                anchors.fill: parent
                                z: 1
                                visible: hotspotHover.hovered && !photoHotspot.isSelected
                                radius: Math.min(width, height) / 2
                                color: Qt.rgba(tokens.accent.r, tokens.accent.g,
                                               tokens.accent.b, 0.10)
                                border.width: 1
                                border.color: tokens.accent
                            }
                        }
                    }
                }
            }

            GridLayout {
                id: rightSideCards
                objectName: "rightMappingCards"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: root.mappingCardColumnWidth
                columns: 1
                rows: root.chromecastLayout ? 8 : 7
                rowSpacing: root.mappingCardGap
                z: 3
                onXChanged: root.scheduleConnectorRepaint()
                onYChanged: root.scheduleConnectorRepaint()
                onWidthChanged: root.scheduleConnectorRepaint()
                onHeightChanged: root.scheduleConnectorRepaint()

                Repeater {
                    id: rightCardRepeater
                    model: MappingViewModel.buttons
                    onItemAdded: root.scheduleConnectorRepaint()
                    delegate: MappingCard {
                        required property var modelData
                        readonly property string buttonId: modelData.id

                        visible: !root.isLeftButton(buttonId)
                        exposeObjectNames: visible
                        tokens: root.tokens
                        cardId: buttonId
                        Layout.row: root.visualRow(buttonId)
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? implicitHeight : 0
                        buttonName: modelData.label
                        keyLabelWidth: root.mappingKeyLabelWidth
                        singleText: modelData.single
                        doubleText: modelData.double
                        longText: modelData.longPress
                        singleNoteText: modelData.singleNote
                            ? modelData.singleNote : ""
                        doubleNoteText: modelData.doubleNote
                            ? modelData.doubleNote : ""
                        longNoteText: modelData.longNote
                            ? modelData.longNote : ""
                        selected: root.selectedButtonId === buttonId
                        voiceAction: modelData.isMic
                        onXChanged: root.scheduleConnectorRepaint()
                        onYChanged: root.scheduleConnectorRepaint()
                        onWidthChanged: root.scheduleConnectorRepaint()
                        onHeightChanged: root.scheduleConnectorRepaint()
                        onVisibleChanged: root.scheduleConnectorRepaint()
                        Component.onCompleted: root.scheduleConnectorRepaint()
                        onClicked: {
                            root.selectedButtonId = buttonId
                            root.openEditor(modelData)
                        }
                    }
                }
            }
        }

        UiLabel {
            tokens: root.tokens
            kind: noteKind
            Layout.fillWidth: true
            text: qsTr("点击按键行或照片上的按键标记互相定位；再次点击按键行可编辑动作。")
            elide: Text.ElideRight
        }
    }

    Connections {
        target: MappingViewModel
        function onButtonsChanged() {
            root.scheduleConnectorRepaint()
        }
        function onShortcutCaptured(text) {
            if (root.captureTargetGesture.length === 0)
                return
            const gesture = root.captureTargetGesture
            root.gestureField(gesture).text = text
            root.recorderPreviewText = text
            const result = MappingViewModel.setAction(
                root.editButtonId, gesture, text)
            if (result && !result.ok)
                root.editorErrorLabel.text = result.message
            else
                root.originalTexts[gesture] = text
            root.finishRecorder()
        }
    }

    SettingsDialog {
        id: actionEditor
        objectName: "actionEditorDialog"
        tokens: root.tokens
        preferredWidth: 520
        title: qsTr("编辑按键动作")
        titleNote: root.editButtonLabel

        contentItem: ColumnLayout {
            spacing: root.tokens.spacingMedium

            RowLayout {
                Layout.fillWidth: true
                spacing: root.tokens.spacingMedium

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall

                    UiLabel {
                        tokens: root.tokens
                        kind: bodyKind
                        font.weight: Font.Medium
                        text: qsTr("单击")
                    }
                    CompactTextField {
                        id: editorSingleField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("单击动作")
                    }
                    RowLayout {
                        spacing: root.tokens.spacingSmall
                        CompactButton {
                            objectName: "actionEditorPrimaryRecordButton"
                            tokens: root.tokens
                            text: qsTr("录入")
                            onClicked: root.openRecorder("single")
                        }
                        CompactButton {
                            objectName: "actionEditorPrimaryBrowseButton"
                            tokens: root.tokens
                            text: qsTr("浏览…")
                            onClicked: root.browseProgram("single")
                        }
                    }
                    CompactTextField {
                        id: editorSingleNoteField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("备注名称")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("单击备注名称")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("程序路径")
                    }
                    CompactTextField {
                        id: editorSinglePathField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("尚未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("单击程序路径")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("输入文字")
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.tokens.controlHeight * 2
                        clip: true
                        TextArea {
                            id: editorSingleContentField
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            padding: root.tokens.spacingSmall
                            color: root.tokens.textPrimary
                            placeholderTextColor: root.tokens.disabledText
                            selectionColor: root.tokens.accent
                            selectedTextColor: root.tokens.accentText
                            font.family: root.tokens.fontFamily
                            font.pixelSize: root.tokens.fontSizeControl
                            placeholderText: qsTr("输入文字，可换行")
                            Accessible.name: root.editButtonLabel + qsTr("单击输入文字")
                            background: Rectangle {
                                radius: root.tokens.cornerRadiusControl
                                color: root.tokens.fieldBackground
                                border.width: root.tokens.hairlineWidth
                                border.color: editorSingleContentField.activeFocus
                                    ? root.tokens.accent : root.tokens.border
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall
                    enabled: !root.editIsMic

                    UiLabel {
                        tokens: root.tokens
                        kind: bodyKind
                        font.weight: Font.Medium
                        text: qsTr("双击")
                    }
                    CompactTextField {
                        id: editorDoubleField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("双击动作")
                    }
                    RowLayout {
                        spacing: root.tokens.spacingSmall
                        CompactButton {
                            objectName: "actionEditorDoubleRecordButton"
                            tokens: root.tokens
                            text: qsTr("录入")
                            onClicked: root.openRecorder("double")
                        }
                        CompactButton {
                            objectName: "actionEditorDoubleBrowseButton"
                            tokens: root.tokens
                            text: qsTr("浏览…")
                            onClicked: root.browseProgram("double")
                        }
                    }
                    CompactTextField {
                        id: editorDoubleNoteField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("备注名称")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("双击备注名称")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("程序路径")
                    }
                    CompactTextField {
                        id: editorDoublePathField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("尚未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("双击程序路径")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("输入文字")
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.tokens.controlHeight * 2
                        clip: true
                        TextArea {
                            id: editorDoubleContentField
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            padding: root.tokens.spacingSmall
                            color: root.tokens.textPrimary
                            placeholderTextColor: root.tokens.disabledText
                            selectionColor: root.tokens.accent
                            selectedTextColor: root.tokens.accentText
                            font.family: root.tokens.fontFamily
                            font.pixelSize: root.tokens.fontSizeControl
                            placeholderText: qsTr("输入文字，可换行")
                            Accessible.name: root.editButtonLabel + qsTr("双击输入文字")
                            background: Rectangle {
                                radius: root.tokens.cornerRadiusControl
                                color: root.tokens.fieldBackground
                                border.width: root.tokens.hairlineWidth
                                border.color: editorDoubleContentField.activeFocus
                                    ? root.tokens.accent : root.tokens.border
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: root.tokens.spacingSmall
                    enabled: !root.editIsMic

                    UiLabel {
                        tokens: root.tokens
                        kind: bodyKind
                        font.weight: Font.Medium
                        text: qsTr("长按")
                    }
                    CompactTextField {
                        id: editorLongField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("长按动作")
                    }
                    RowLayout {
                        spacing: root.tokens.spacingSmall
                        CompactButton {
                            objectName: "actionEditorLongRecordButton"
                            tokens: root.tokens
                            text: qsTr("录入")
                            onClicked: root.openRecorder("longPress")
                        }
                        CompactButton {
                            objectName: "actionEditorLongBrowseButton"
                            tokens: root.tokens
                            text: qsTr("浏览…")
                            onClicked: root.browseProgram("longPress")
                        }
                    }
                    CompactTextField {
                        id: editorLongNoteField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("备注名称")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("长按备注名称")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("程序路径")
                    }
                    CompactTextField {
                        id: editorLongPathField
                        tokens: root.tokens
                        Layout.fillWidth: true
                        placeholderText: qsTr("尚未设置")
                        selectByMouse: true
                        Accessible.name: root.editButtonLabel + qsTr("长按程序路径")
                    }
                    UiLabel {
                        tokens: root.tokens
                        kind: noteKind
                        text: qsTr("输入文字")
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.tokens.controlHeight * 2
                        clip: true
                        TextArea {
                            id: editorLongContentField
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            padding: root.tokens.spacingSmall
                            color: root.tokens.textPrimary
                            placeholderTextColor: root.tokens.disabledText
                            selectionColor: root.tokens.accent
                            selectedTextColor: root.tokens.accentText
                            font.family: root.tokens.fontFamily
                            font.pixelSize: root.tokens.fontSizeControl
                            placeholderText: qsTr("输入文字，可换行")
                            Accessible.name: root.editButtonLabel + qsTr("长按输入文字")
                            background: Rectangle {
                                radius: root.tokens.cornerRadiusControl
                                color: root.tokens.fieldBackground
                                border.width: root.tokens.hairlineWidth
                                border.color: editorLongContentField.activeFocus
                                    ? root.tokens.accent : root.tokens.border
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: root.tokens.spacingSmall

                CompactButton {
                    objectName: "detectRealKeyButton"
                    tokens: root.tokens
                    compactMinimumWidth: root.tokens.buttonWidth6Chars
                    text: qsTr("检测真实按键")
                    onClicked: MappingViewModel.startKeyDetection()
                }
                CompactButton {
                    objectName: "stopKeyDetectionButton"
                    tokens: root.tokens
                    compactMinimumWidth: root.tokens.buttonWidth2Chars
                    text: qsTr("停止")
                    onClicked: MappingViewModel.stopKeyDetection()
                }
                UiLabel {
                    tokens: root.tokens
                    kind: noteKind
                    Layout.fillWidth: true
                    text: MappingViewModel.keyDetectionText
                    elide: Text.ElideRight
                    HoverHandler { id: detectionTextHover }
                    CompactToolTip {
                        tokens: root.tokens
                        active: detectionTextHover.hovered
                            && MappingViewModel.keyDetectionText.length > 0
                        text: MappingViewModel.keyDetectionText
                    }
                }
            }

            UiLabel {
                visible: root.editIsMic
                tokens: root.tokens
                kind: noteKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("语音键在语音模式下暂停双击 / 长按。")
            }

            UiLabel {
                id: editorErrorLabel
                objectName: "actionEditorValidationError"
                tokens: root.tokens
                kind: noteKind
                Layout.fillWidth: true
                visible: text.length > 0
                wrapMode: Text.WordWrap
                color: tokens.errorColor
                Accessible.name: text
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: root.tokens.spacingSmall
                Item { Layout.fillWidth: true }
                CompactButton {
                    objectName: "actionEditorCancelButton"
                    tokens: root.tokens
                    compactMinimumWidth: root.tokens.buttonWidth2Chars
                    text: qsTr("取消")
                    onClicked: actionEditor.close()
                }
                CompactButton {
                    objectName: "actionEditorSaveButton"
                    tokens: root.tokens
                    compactMinimumWidth: root.tokens.buttonWidth2Chars
                    text: qsTr("完成")
                    highlighted: true
                    onClicked: root.commitEditor()
                }
            }
        }
    }

    SettingsDialog {
        id: shortcutRecorder
        objectName: "shortcutRecorderDialog"
        tokens: root.tokens
        preferredWidth: 380
        title: qsTr("录入快捷键")
        titleNote: root.editButtonLabel
        onRejected: root.finishRecorder()

        contentItem: ColumnLayout {
            spacing: root.tokens.spacingMedium

            UiLabel {
                objectName: "shortcutRecorderPreview"
                tokens: root.tokens
                kind: bodyKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: root.recorderPreviewText
                color: tokens.textPrimary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: root.tokens.spacingSmall
                Item { Layout.fillWidth: true }
                CompactButton {
                    objectName: "shortcutRecorderCloseButton"
                    tokens: root.tokens
                    compactMinimumWidth: root.tokens.buttonWidth2Chars
                    text: qsTr("停止")
                    onClicked: root.finishRecorder()
                }
            }
        }
    }

    FileDialog {
        id: programFileDialog
        objectName: "mappingProgramFileDialog"
        title: qsTr("选择要打开的程序")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("应用程序 (*.exe)")]
        onAccepted: root.commitProgramPick(String(selectedFile))
    }
}
