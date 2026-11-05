"""Presentation view-models (layer ②) - read / translate / forward only.

Each view-model wraps the *existing* backend objects (``SettingsController``,
``ButtonMappingModel``, ``DiagnosticsController`` from ``qt_settings_app``)
through constructor injection, so every unit test drives fakes instead of the
real Qt/Windows backend.  No business decisions live here: state-dependent
dispatches are closed, documented tables over existing backend state (the
same choices the old QML made inline), and every user-visible string is
either a display literal from this layer or text the backend already
produces.

Contract shapes come from ``contracts.py``; the Qt marshalling details live in
``transport.py``.  QML sees only the Property/Slot surface listed in
docs/UI-REDESIGN.md §3/§3.5 plus the typed-slot extensions noted in the
delivery report (D1/D5/D6 sanctioned).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from .contracts import (
    MAINTENANCE_ITEM_IDS,
    PREFERENCE_IDS,
    ButtonRow,
    CheckRow,
    ChoiceRow,
    StatusCard,
    ToggleRow,
    Validation,
)
from .transport import contract_qml_map, row_view, row_views

# ---------------------------------------------------------------------------
# Closed display vocabularies (presentation level - no backend words).
# ---------------------------------------------------------------------------

_HOLD_MODE_LABEL = "按住说话"
_TOGGLE_MODE_LABEL = "按一次开·再按一次关"
_RECORDING_MODE_INDEX_BY_LABEL: Dict[str, int] = {
    _HOLD_MODE_LABEL: 0,
    _TOGGLE_MODE_LABEL: 1,
}

# Presentation gesture tokens -> backend trigger values.  The backend values
# are translated here so they never leak to QML (key_mapping.ButtonTrigger).
GESTURE_TRIGGERS: Dict[str, str] = {
    "single": "single_click",
    "double": "double_click",
    "longPress": "long_press",
}

_CHECK_STATE_BY_STATUS: Dict[str, str] = {
    "pass": "done",
    "fail": "failed",
    "manual": "todo",
    "unsupported": "todo",
}

_FIX_LABEL = "修复受影响项目"

# Diagnostics check ids (windows_diagnostics.check_specs) -> the existing fix
# affordance.  Closed over the backend's check catalogue; unlisted checks have
# no fix action.
_FIX_BY_CHECK_ID: Dict[str, Tuple[str, str]] = {
    "ble_candidate": ("controller", "refreshRemoteDevices"),
    "vb_cable_endpoints": ("diagnostics", "launchVbCableSetup"),
    "output_endpoint": ("diagnostics", "selectDetectedCableInputAsOutput"),
    "raw_input": ("controller", "refreshBridgeState"),
    # "os_version" has no fix affordance in the backend.
}

_PREFERENCE_LABELS: Dict[str, str] = {
    "start_with_windows": "随 Windows 启动",
    "auto_start_bridge": "启动程序时自动运行服务",
    "diagnostic_logging": "诊断日志",
    "hide_to_tray_on_close": "关闭窗口时隐藏到任务栏",
}

_ITEM_DEFS: Dict[str, Tuple[str, str, str]] = {
    # id: (title, detail-hint, action label)
    "update": ("软件更新", "检查并安装新版本", "检查更新"),
    "helper": ("HID 助手", "修复按键注入所需的助手组件", "修复"),
    "diagnostics": ("运行检测", "重新检查遥控器、按键与音频链路", "重新检测"),
    "logs": ("日志导出", "导出 app.log 便于反馈问题", "导出日志"),
    "bluetooth": ("蓝牙设置", "打开系统蓝牙设置", "打开蓝牙设置"),
    "guide": ("使用方法", "打开在线使用说明", "查看使用方法"),
}

_ACTION_ID_TEST_DICTATION = "test-dictation"
_ACTION_ID_BRIDGE = "bridge"
_ACTION_ID_UPDATE = "update"


# ---------------------------------------------------------------------------
# Pure translations.
# ---------------------------------------------------------------------------


def bridge_state_label(running: bool, connected: bool) -> str:
    """Bridge connection state as end-user wording."""

    if connected:
        return "已连接"
    if running:
        return "连接中"
    return "未连接"


def battery_label(level: int) -> str:
    """Remote battery as end-user wording; ``-1`` means unknown."""

    if level is None or level < 0:
        return "电量未知"
    return f"电量 {level}%"


def check_row(row: Dict[str, Any]) -> CheckRow:
    """Translate one backend diagnostic row into its user-facing shape.

    Backend rows are the ``{checkId, title, group, status, detail, resultCode}``
    dicts built by ``qt_settings_app._diagnostics_check_to_row``; none of those
    key names cross to QML.
    """

    status = _CHECK_STATE_BY_STATUS.get(str(row.get("status", "")), "todo")
    return CheckRow(
        id=str(row.get("checkId", "")),
        title=str(row.get("title", "")),
        status=status,  # type: ignore[arg-type]
        detail=str(row.get("detail", "")),
        fixLabel=_FIX_LABEL if status == "failed" else "",
    )


def remote_choice(row: Dict[str, Any]) -> ChoiceRow:
    """Translate one remote-device choice dict into its user-facing shape."""

    return ChoiceRow(
        id=str(row.get("key", "")),
        label=str(row.get("label", "")),
        detail=str(row.get("profile", "")),
        enabled=bool(row.get("canUse", True)),
        selected=bool(row.get("isActive", False)),
    )


def _connect(source: Any, signal_name: str, callback: Any) -> None:
    """Subscribe to a backend signal when it exists (fakes may omit signals)."""

    signal = getattr(source, signal_name, None)
    if signal is not None and hasattr(signal, "connect"):
        signal.connect(callback)


def _prefers_hide_to_tray(close_behavior: str) -> bool:
    """``config.CLOSE_BEHAVIOR_HIDE_TO_TRAY`` is the only value meaning the
    window close hides to the tray instead of quitting (config.py constants).
    """

    from .. import config

    return close_behavior == config.CLOSE_BEHAVIOR_HIDE_TO_TRAY


class _ViewmodelBase(QObject):
    """Shared recompute/notify plumbing.

    Every view-model recomputes its derived contract values from the live
    backend on read and re-emits its notify signals when the backend reports a
    change; the QML-visible values therefore never go stale without polling.
    """

    _NOTIFY_NAMES: Tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self._view_cache: Dict[str, Tuple[Any, Any]] = {}

    def _emit_changed(self, *args: Any) -> None:
        # Accepts the arguments of whichever signal triggered it: Qt model
        # signals (``dataChanged``/``layoutChanged``/``modelReset``) carry
        # payloads, custom signals often carry none.
        for name in self._NOTIFY_NAMES:
            getattr(self, name).emit()

    def _cached_views(self, key: str, values: Sequence[Any]) -> List[QObject]:
        cached = self._view_cache.get(key)
        if cached is None or cached[0] != list(values):
            cached = (list(values), row_views(values))
            self._view_cache[key] = cached
        return cached[1]

    def _cached_view(self, key: str, value: Any) -> QObject:
        cached = self._view_cache.get(key)
        if cached is None or cached[0] != value:
            cached = (value, row_view(value))
            self._view_cache[key] = cached
        return cached[1]


# ---------------------------------------------------------------------------
# Native dictation observation (the default ``dictation_probe`` seam).
# ---------------------------------------------------------------------------


class NativeDictationProbe:
    """End-to-end dictation evidence over the existing observation seams.

    Evidence sources (D9 honesty rule - the verdict claims ONLY what was
    actually observed, and never claims input-source attribution):

    * ``voice_interaction_diagnostics_windows.capture_focus_snapshot`` /
      ``compare_submission`` - WM_GETTEXTLENGTH delta on the focused *native*
      edit control ("text growth observed");
    * the bridge's voice runtime state stream (``voiceRuntimeState``): session
      start / non-empty audio / normal session end are certified by the
      ``bridge_runtime_status`` state machine - ``success`` is a distinct
      outcome from ``audio_empty``, so a ``success`` state proves the attempt
      completed with non-empty audio and a normal stop.

    Known limitation the verdict text always states: the backend cannot
    distinguish voice input from hand-typed input or paste.
    """

    _CLAIMS = {
        "started": "会话已开始",
        "audio": "收到非空音频",
        "ended": "会话正常结束",
        "text": "测试输入框文本增长",
    }
    _LIMITATION = "限制：现有后端无法区分手工输入/粘贴与语音输入，本结果只证明以上观测到的事实。"
    _FAILURE_TEXT = {
        "audio_empty": "收到的音频为空",
        "output_open_failed": "音频输出打开失败",
        "host_start_failed": "语音会话启动失败",
        "host_stop_failed": "语音会话结束失败",
        "host_unconfirmed": "语音宿主未确认",
    }

    def __init__(
        self,
        *,
        capture: Any = None,
        compare: Any = None,
        runtime_state: Any = None,
        clock: Any = None,
        timeout_seconds: float = 40.0,
    ) -> None:
        self._capture = capture
        self._compare = compare
        self._runtime_state = runtime_state
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._before: Any = None
        self._deadline = 0.0
        self._seen: Dict[str, bool] = {}
        self._failure_state = ""

    def _deps(self) -> None:
        if self._capture is None or self._compare is None:
            from .. import voice_interaction_diagnostics_windows as observed

            self._capture = self._capture or observed.capture_focus_snapshot
            self._compare = self._compare or observed.compare_submission
        if self._clock is None:
            import time

            self._clock = time.monotonic

    def start(self) -> Optional[Validation]:
        """Arm the observation; ``None`` means armed, a verdict means refused."""

        self._deps()
        try:
            self._before = self._capture()
        except Exception as exc:  # observation must never crash the UI
            return Validation(False, f"无法开始口述观测：{exc}", "probe")
        if not getattr(self._before, "supported", False):
            return Validation(
                False,
                "当前环境无法观测输入框文本；请在桌面版 Windows 上重新测试。",
                "probe",
            )
        self._deadline = self._clock() + self._timeout_seconds
        self._seen = {"started": False, "audio": False, "ended": False, "text": False}
        self._failure_state = ""
        self._sample_runtime()
        return None

    def _sample_runtime(self) -> None:
        if self._runtime_state is None:
            return
        try:
            state = str(self._runtime_state())
        except Exception:
            return
        if state in ("active", "mic_confirmed", "receiving_audio", "finishing", "success"):
            self._seen["started"] = True
        if state == "receiving_audio":
            self._seen["audio"] = True
        if state == "success":
            # ``success`` is the state machine's normal, non-empty-audio
            # completion (``audio_empty`` is the distinct empty-audio outcome).
            self._seen["audio"] = True
            self._seen["ended"] = True
        if state in self._FAILURE_TEXT and not self._failure_state:
            self._failure_state = state

    def _verdict(self, ok: bool, headline: str) -> Validation:
        observed = [text for key, text in self._CLAIMS.items() if self._seen.get(key)]
        missing = [text for key, text in self._CLAIMS.items() if not self._seen.get(key)]
        if ok:
            message = f"{headline}：{'、'.join(observed)}。{self._LIMITATION}"
        else:
            detail = f"已观测：{'、'.join(observed) or '无'}"
            if missing:
                detail += f"；未观测到：{'、'.join(missing)}"
            message = f"{headline}。{detail}。{self._LIMITATION}"
        return Validation(ok, message, "probe")

    def poll(self) -> Optional[Validation]:
        """Return the settled verdict, or ``None`` while still observing."""

        self._deps()
        self._sample_runtime()
        if self._failure_state:
            return self._verdict(
                False,
                f"口述验收未通过：{self._FAILURE_TEXT[self._failure_state]}",
            )
        try:
            after = self._capture()
            observation = self._compare(self._before, after)
        except Exception:
            observation = None  # transient capture failure: keep polling
        if observation is not None:
            text_state = getattr(observation, "text_state", "unavailable")
            if text_state == "unavailable":
                return self._verdict(
                    False,
                    "口述验收未通过：无法观测当前输入框文本（仅原生输入框可观测）",
                )
            if text_state == "grew":
                self._seen["text"] = True
        if self._seen["ended"]:
            if self._seen["text"]:
                return self._verdict(True, "口述验收通过")
            return self._verdict(
                False, "口述验收未通过：会话结束但未观测到测试输入框文本增长"
            )
        if self._clock() > self._deadline:
            return self._verdict(False, "口述验收超时")
        return None


# ---------------------------------------------------------------------------
# AppViewModel
# ---------------------------------------------------------------------------


class AppViewModel(_ViewmodelBase):
    """Window-level presentation state (doc §3)."""

    windowTitleChanged = Signal()
    statusCardChanged = Signal()
    currentPageChanged = Signal()
    versionLabelChanged = Signal()
    bridgeStateLabelChanged = Signal()
    startHiddenChanged = Signal()
    windowRestoreRequested = Signal()

    _NOTIFY_NAMES = (
        "windowTitleChanged",
        "statusCardChanged",
        "currentPageChanged",
        "versionLabelChanged",
        "bridgeStateLabelChanged",
        "startHiddenChanged",
    )

    def __init__(self, controller: Any) -> None:
        super().__init__()
        self._controller = controller
        self._current_page = 0
        _connect(controller, "windowRestoreRequested", self._on_window_restore_requested)
        for name in (
            "bridgeRunningChanged",
            "bridgeConnectedChanged",
            "bridgeConnectionStateChanged",
            "remoteBatteryChanged",
            "remoteSelectionChanged",
            "voiceRuntimeStatusChanged",
            "voiceMappingReadyChanged",
            "launchStatusTextChanged",
            "statusMessageChanged",
            "trayStateChanged",
        ):
            _connect(controller, name, self._emit_changed)

    def _on_window_restore_requested(self) -> None:
        self.windowRestoreRequested.emit()

    # -- properties --------------------------------------------------------

    @Property(bool, notify=bridgeStateLabelChanged)
    def startHidden(self) -> bool:
        """Whether this launch asked to come up hidden in the tray.

        A launch-mode fact, not a business decision: the view shows or hides
        the window accordingly and nothing else.
        """
        return bool(getattr(self._controller, "startHidden", False))

    @Slot(result=bool)
    def onWindowReady(self) -> bool:
        """The window is up; let the backend run its launch-time work.

        The view only says "the window is ready" — what that means is a
        presentation-layer decision.  It forwards to the controller's
        application-start hook, which owns starting the bridge service
        exactly as the pre-split shell did.
        """
        hook = getattr(self._controller, "startBridgeOnApplicationStart", None)
        if hook is None:
            return False
        try:
            hook()
        except Exception:
            return False
        return True

    @Slot(result=bool)
    def startupSettled(self) -> bool:
        """The launch grace period is over; run deferred startup work.

        The pre-split shell checked for an application update five seconds
        after launch so the bridge had time to settle first.  The view owns
        the pacing, the presentation layer owns the meaning.
        """
        hook = getattr(self._controller, "checkForApplicationUpdateOnStartup", None)
        if hook is None:
            return False
        try:
            hook()
        except Exception:
            return False
        return True

    @Slot()
    def tick(self) -> None:
        """One presentation heartbeat.

        The view decides only how often to call; everything polled is chosen
        here so QML never learns what the backend exposes.  Status is always
        refreshed, while the bridge-launch and window-restore pumps run only
        while the backend says there is something pending.
        """
        controller = self._controller
        for name, active_attr in (
            ("refreshBridgeState", None),
            ("pollBridgeLaunch", "bridgeLaunchBusy"),
            ("pollWindowRestoreRequest", None),
        ):
            hook = getattr(controller, name, None)
            if hook is None:
                continue
            if active_attr is not None and not getattr(controller, active_attr, False):
                continue
            try:
                hook()
            except Exception:
                continue
        self._refresh_bridge_label()

    def _refresh_bridge_label(self) -> None:
        self.bridgeStateLabelChanged.emit()

    @Property(str, notify=windowTitleChanged)
    def windowTitle(self) -> str:
        return str(getattr(self._controller, "applicationPresentationLabel", ""))

    @Property(QObject, notify=statusCardChanged)
    def statusCard(self) -> QObject:
        return self._cached_view("statusCard", self._build_status_card())

    @Property(int, notify=currentPageChanged)
    def currentPage(self) -> int:
        return self._current_page

    @currentPage.setter
    def currentPage(self, value: int) -> None:
        # D2: pure writable view state - deliberately NOT forwarded to the
        # backend's activePageIndex.
        self._current_page = int(value)
        self.currentPageChanged.emit()

    @Property(str, notify=versionLabelChanged)
    def versionLabel(self) -> str:
        return str(getattr(self._controller, "applicationVersion", ""))

    @Property(str, notify=bridgeStateLabelChanged)
    def bridgeStateLabel(self) -> str:
        return bridge_state_label(
            bool(getattr(self._controller, "bridgeRunning", False)),
            bool(getattr(self._controller, "bridgeConnected", False)),
        )

    @Property(bool, notify=startHiddenChanged)
    def startHidden(self) -> bool:
        """The ``--background`` autostart path (lifecycle, D3)."""

        return bool(getattr(self._controller, "startHidden", False))

    @Slot()
    def pollWindowRestoreRequest(self) -> None:
        """Forward of the backend's duplicate-launch restore poll; the
        matching ``windowRestoreRequested`` signal fires from it.
        """

        self._controller.pollWindowRestoreRequest()

    # -- derivation --------------------------------------------------------

    def _build_status_card(self) -> StatusCard:
        controller = self._controller
        remote = (
            getattr(controller, "activeRemoteLabel", "")
            or getattr(controller, "remoteDisplayName", "")
            or "未连接遥控器"
        )
        title = f"{remote} · {battery_label(int(getattr(controller, 'remoteBatteryLevel', -1)))}"
        voice_ready = bool(getattr(controller, "voiceMappingReady", False))
        connected = bool(getattr(controller, "bridgeConnected", False))
        running = bool(getattr(controller, "bridgeRunning", False))
        if connected and voice_ready:
            tone = "ok"
        elif running:
            tone = "warn"
        else:
            tone = "idle"
        return StatusCard(
            title=title,
            subtitle="语音就绪" if voice_ready else "语音未就绪",
            tone=tone,  # type: ignore[arg-type]
            detail=str(getattr(controller, "launchStatusText", ""))
            or str(getattr(controller, "statusMessage", "")),
            actionLabel="口述测试",
            actionId=_ACTION_ID_TEST_DICTATION,
        )


# ---------------------------------------------------------------------------
# DeviceViewModel
# ---------------------------------------------------------------------------


class DeviceViewModel(_ViewmodelBase):
    """Remote connection + diagnostics presentation (doc §3/§3.5 D5)."""

    connectionCardChanged = Signal()
    checksChanged = Signal()
    remoteChoicesChanged = Signal()
    batteryLabelChanged = Signal()

    _NOTIFY_NAMES = (
        "connectionCardChanged",
        "checksChanged",
        "remoteChoicesChanged",
        "batteryLabelChanged",
    )

    def __init__(self, controller: Any, diagnostics: Any) -> None:
        super().__init__()
        self._controller = controller
        self._diagnostics = diagnostics
        for name in (
            "bridgeRunningChanged",
            "bridgeConnectedChanged",
            "bridgeConnectionStateChanged",
            "bridgeLaunchPhaseChanged",
            "bridgeRestartRecommendedChanged",
            "bridgeReconnectAvailableChanged",
            "bridgeReconnectBusyChanged",
            "remoteSelectionChanged",
            "remoteBatteryChanged",
            "launchStatusTextChanged",
            "statusMessageChanged",
        ):
            _connect(controller, name, self._emit_changed)
        for name in ("checkResultsChanged", "isRefreshingChanged", "diagnosticsErrorMessageChanged"):
            _connect(diagnostics, name, self._emit_changed)

    # -- properties --------------------------------------------------------

    @Property(QObject, notify=connectionCardChanged)
    def connectionCard(self) -> QObject:
        return self._cached_view("connectionCard", self._build_connection_card())

    @Property(list, notify=checksChanged)
    def checks(self) -> List[QObject]:
        rows = [
            check_row(row) for row in getattr(self._diagnostics, "checkResults", []) or []
        ]
        return self._cached_views("checks", rows)

    @Property(list, notify=remoteChoicesChanged)
    def remoteChoices(self) -> List[QObject]:
        choices = [
            remote_choice(row)
            for row in getattr(self._controller, "remoteDeviceChoices", []) or []
        ]
        return self._cached_views("remoteChoices", choices)

    @Property(str, notify=batteryLabelChanged)
    def batteryLabel(self) -> str:
        return battery_label(int(getattr(self._controller, "remoteBatteryLevel", -1)))

    # -- slots -------------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        self._controller.refreshRemoteDevices()
        self._diagnostics.refreshDiagnostics()

    @Slot(str)
    def fixCheck(self, checkId: str) -> None:
        target = _FIX_BY_CHECK_ID.get(checkId)
        if target is None:
            return
        owner_name, method_name = target
        owner = self._controller if owner_name == "controller" else self._diagnostics
        getattr(owner, method_name)()

    @Slot(str)
    def useRemote(self, id: str) -> None:
        self._controller.useRemoteDevice(id)

    @Slot(result="QVariantMap")
    def bridgeAction(self) -> Validation:
        """Typed D5 slot: start / restart / reconnect the service.

        The choice mirrors exactly what the old bridge button decided from
        the same backend state; no new policy is introduced here.
        """

        controller = self._controller
        if bool(getattr(controller, "bridgeLaunchBusy", False)):
            verdict = Validation(
                False,
                str(getattr(controller, "launchStatusText", "")) or "服务正在启动，请稍候。",
                "bridge",
            )
        elif not bool(getattr(controller, "bridgeRunning", False)):
            controller.startBridge()
            verdict = Validation(
                True,
                str(getattr(controller, "launchStatusText", "")) or "已请求启动服务。",
                "bridge",
            )
        elif bool(getattr(controller, "bridgeReconnectAvailable", False)) and not bool(
            getattr(controller, "bridgeConnected", False)
        ):
            controller.reconnectBridgeNow()
            verdict = Validation(
                True,
                str(getattr(controller, "launchStatusText", "")) or "已请求重新连接。",
                "bridge",
            )
        else:
            controller.restartBridge()
            verdict = Validation(
                True,
                str(getattr(controller, "launchStatusText", "")) or "已请求重启服务。",
                "bridge",
            )
        return contract_qml_map(verdict)

    # -- derivation --------------------------------------------------------

    def _build_connection_card(self) -> StatusCard:
        controller = self._controller
        connected = bool(getattr(controller, "bridgeConnected", False))
        running = bool(getattr(controller, "bridgeRunning", False))
        if connected:
            tone = "ok"
        elif running:
            tone = "warn"
        else:
            tone = "error"
        return StatusCard(
            title="遥控器连接",
            subtitle=bridge_state_label(running, connected),
            tone=tone,  # type: ignore[arg-type]
            detail=str(getattr(controller, "launchStatusText", ""))
            or str(getattr(controller, "statusMessage", ""))
            or str(getattr(controller, "remoteSelectionMessage", "")),
            actionLabel="连接 / 重连",
            actionId=_ACTION_ID_BRIDGE,
        )


# ---------------------------------------------------------------------------
# VoiceViewModel
# ---------------------------------------------------------------------------


class VoiceViewModel(_ViewmodelBase):
    """Voice programs / hotkey / audio route / dictation (doc §3/§3.5 D6)."""

    voiceCardChanged = Signal()
    voiceProgramsChanged = Signal()
    hotkeyLabelChanged = Signal()
    recordingModeChanged = Signal()
    audioRouteLabelChanged = Signal()
    lastValidationChanged = Signal()
    outputEndpointsChanged = Signal()
    recordingLimitSecondsChanged = Signal()
    customProgramPathChanged = Signal()
    autoLaunchChanged = Signal()
    launchElevatedChanged = Signal()

    _NOTIFY_NAMES = (
        "voiceCardChanged",
        "voiceProgramsChanged",
        "hotkeyLabelChanged",
        "recordingModeChanged",
        "audioRouteLabelChanged",
        "lastValidationChanged",
        "outputEndpointsChanged",
        "recordingLimitSecondsChanged",
        "customProgramPathChanged",
        "autoLaunchChanged",
        "launchElevatedChanged",
    )

    def __init__(self, controller: Any, diagnostics: Any, *, dictation_probe: Any = None) -> None:
        super().__init__()
        self._controller = controller
        self._diagnostics = diagnostics
        self._dictation_probe = dictation_probe
        self._dictation_timer: Optional[QTimer] = None
        self._last_validation = Validation(True, "", "")
        for name in (
            "voiceRuntimeStatusChanged",
            "voiceMappingReadyChanged",
            "voiceHotkeySaveStateChanged",
            "holdVoiceHotkeyTextChanged",
            "selectedVoiceProgramIndexChanged",
            "voiceProgramOptionsChanged",
            "voiceProgramStatusTextChanged",
            "endpointOptionsChanged",
            "selectedEndpointIndexChanged",
            "recommendedEndpointIndexChanged",
            "voiceProgramCustomPathChanged",
            "voiceProgramLaunchOnBridgeStartChanged",
            "voiceProgramLaunchElevatedChanged",
            # The controller announces a device/recording-mode change through
            # ``remoteSelectionChanged``; there is no ``remoteRecordingModeChanged``.
            # Listening for a signal nobody emits left the recording-mode
            # selectors stale after a rejected or failed change.
            "remoteSelectionChanged",
            "bridgeConnectedChanged",
        ):
            _connect(controller, name, self._emit_changed)
        _connect(controller, "hotkeyCaptured", self._on_hotkey_captured)
        _connect(controller, "hotkeyCaptureError", self._on_hotkey_capture_error)

    # -- properties --------------------------------------------------------

    @Property(QObject, notify=voiceCardChanged)
    def voiceCard(self) -> QObject:
        return self._cached_view("voiceCard", self._build_voice_card())

    @Property(list, notify=voiceProgramsChanged)
    def voicePrograms(self) -> List[QObject]:
        options = list(getattr(self._controller, "voiceProgramOptions", []) or [])
        selected = int(getattr(self._controller, "selectedVoiceProgramIndex", -1))
        rows = [
            ChoiceRow(
                id=str(index),
                label=str(label),
                detail="",
                enabled=True,
                selected=(index == selected),
            )
            for index, label in enumerate(options)
        ]
        return self._cached_views("voicePrograms", rows)

    @Property(str, notify=hotkeyLabelChanged)
    def hotkeyLabel(self) -> str:
        controller = self._controller
        text = str(getattr(controller, "holdVoiceHotkeyText", ""))
        if not text:
            return ""
        return str(controller.formatHotkeyText(text))

    @Property(str, notify=recordingModeChanged)
    def recordingMode(self) -> str:
        if int(getattr(self._controller, "remoteRecordingModeIndex", 0)) == 1:
            return _TOGGLE_MODE_LABEL
        return _HOLD_MODE_LABEL

    @Property(str, notify=audioRouteLabelChanged)
    def audioRouteLabel(self) -> str:
        options = list(getattr(self._controller, "endpointOptions", []) or [])
        index = int(getattr(self._controller, "selectedEndpointIndex", -1))
        if 0 <= index < len(options):
            return str(options[index])
        return ""

    @Property(QObject, notify=lastValidationChanged)
    def lastValidation(self) -> QObject:
        return self._cached_view("lastValidation", self._last_validation)

    @Property(list, notify=outputEndpointsChanged)
    def outputEndpoints(self) -> List[QObject]:
        options = list(getattr(self._controller, "endpointOptions", []) or [])
        selected = int(getattr(self._controller, "selectedEndpointIndex", -1))
        recommended = int(getattr(self._controller, "recommendedEndpointIndex", -1))
        rows = [
            ChoiceRow(
                id=str(index),
                label=str(label),
                detail="推荐" if index == recommended else "",
                enabled=True,
                selected=(index == selected),
            )
            for index, label in enumerate(options)
        ]
        return self._cached_views("outputEndpoints", rows)

    @Property(int, notify=recordingLimitSecondsChanged)
    def recordingLimitSeconds(self) -> int:
        limits = _recording_limits()
        index = int(getattr(self._controller, "remoteRecordingLimitIndex", 0))
        if not 0 <= index < len(limits):
            index = 0
        return int(limits[index])

    @Property(str, notify=customProgramPathChanged)
    def customProgramPath(self) -> str:
        return str(getattr(self._controller, "voiceProgramCustomPath", ""))

    @Property(bool, notify=autoLaunchChanged)
    def autoLaunch(self) -> bool:
        return bool(getattr(self._controller, "voiceProgramLaunchOnBridgeStart", False))

    @Property(bool, notify=launchElevatedChanged)
    def launchElevated(self) -> bool:
        return bool(getattr(self._controller, "voiceProgramLaunchElevated", False))

    # -- slots -------------------------------------------------------------

    @Slot(str)
    def setVoiceProgram(self, id: str) -> None:
        try:
            index = int(id)
        except (TypeError, ValueError):
            return
        options = list(getattr(self._controller, "voiceProgramOptions", []) or [])
        if 0 <= index < len(options):
            self._controller.selectedVoiceProgramIndex = index

    @Slot(str)
    def setRecordingMode(self, mode: str) -> None:
        index = _RECORDING_MODE_INDEX_BY_LABEL.get(mode)
        if index is None:
            return
        self._controller.setRemoteRecordingPreferences(
            index, int(getattr(self._controller, "remoteRecordingLimitIndex", 0))
        )

    @Slot()
    def startHotkeyCapture(self) -> None:
        self._controller.startHotkeyCapture()

    @Slot()
    def stopHotkeyCapture(self) -> None:
        self._controller.stopHotkeyCapture()

    @Slot()
    def testAudio(self) -> None:
        self._diagnostics.testVbCableChannel()

    @Slot()
    def installVirtualCable(self) -> None:
        self._diagnostics.launchVbCableSetup()

    @Slot(str)
    def selectOutput(self, id: str) -> None:
        try:
            index = int(id)
        except (TypeError, ValueError):
            return
        self._controller.selectAndPersistOutputEndpointIndex(index)

    @Slot(int)
    def setRecordingLimit(self, v: int) -> None:
        limits = _recording_limits()
        nearest = min(range(len(limits)), key=lambda i: abs(int(limits[i]) - int(v)))
        self._controller.setRemoteRecordingPreferences(
            int(getattr(self._controller, "remoteRecordingModeIndex", 0)), nearest
        )

    @Slot(str, result="QVariantMap")
    def pickCustomProgramPath(self, fileUrl: str) -> Validation:
        path = str(self._controller.programPathFromFileUrl(fileUrl))
        if not path:
            return contract_qml_map(Validation(False, "请选择本地程序文件。", "voiceProgram"))
        self._controller.voiceProgramCustomPath = path
        return contract_qml_map(Validation(True, path, "voiceProgram"))

    @Slot(bool, result="QVariantMap")
    def setAutoLaunch(self, v: bool) -> Validation:
        self._controller.voiceProgramLaunchOnBridgeStart = bool(v)
        return contract_qml_map(Validation(True, "", "autoLaunch"))

    @Slot(bool, result="QVariantMap")
    def setLaunchElevated(self, v: bool) -> Validation:
        self._controller.voiceProgramLaunchElevated = bool(v)
        return contract_qml_map(Validation(True, "", "launchElevated"))

    @Slot(result="QVariantMap")
    def launchVoiceProgram(self) -> Validation:
        self._controller.launchVoiceProgram()
        return contract_qml_map(
            Validation(
                True,
                str(getattr(self._controller, "voiceProgramStatusText", "")),
                "voiceProgram",
            )
        )

    @Slot(result="QVariantMap")
    def openVoiceProgramSettings(self) -> Validation:
        self._controller.openVoiceProgramSettings()
        return contract_qml_map(Validation(True, "", "voiceProgram"))

    @Slot(result="QVariantMap")
    def testDictation(self) -> Validation:
        """Real dictation acceptance over the strongest observable evidence.

        Synchronous result is the pre-flight verdict (or an immediately
        settled one); the settled end-to-end verdict is published on
        ``lastValidation``.
        """

        blocker = self._dictation_blocker()
        if blocker is not None:
            self._set_last_validation(blocker)
            return contract_qml_map(blocker)
        if self._dictation_probe is None:
            ready = Validation(
                True, "语音链路已就绪；请说一句话，确认文字出现在测试输入框。", ""
            )
            self._set_last_validation(ready)
            return contract_qml_map(ready)
        started = self._dictation_probe.start()
        if started is not None:
            self._set_last_validation(started)
            return contract_qml_map(started)
        self._set_last_validation(
            Validation(True, "口述验收进行中：请对测试输入框说话。", "")
        )
        self._poll_dictation()
        return contract_qml_map(self._last_validation)

    # -- internals ---------------------------------------------------------

    def _dictation_blocker(self) -> Optional[Validation]:
        controller = self._controller
        if not bool(getattr(controller, "bridgeConnected", False)):
            return Validation(False, "服务未连接：请先在设备页连接遥控器。", "connection")
        if not bool(getattr(controller, "voiceMappingReady", False)):
            return Validation(False, "语音尚未就绪：请先完成语音设置。", "voice")
        if str(getattr(controller, "voiceHotkeySaveState", "")) == "retry":
            return Validation(False, "语音快捷键尚未保存成功，请重试。", "hotkey")
        return None

    def _poll_dictation(self) -> None:
        if self._dictation_probe is None:
            return
        verdict = self._dictation_probe.poll()
        if verdict is None:
            if self._dictation_timer is None:
                self._dictation_timer = QTimer(self)
                self._dictation_timer.setInterval(250)
                self._dictation_timer.timeout.connect(self._poll_dictation)
            if not self._dictation_timer.isActive():
                self._dictation_timer.start()
            return
        if self._dictation_timer is not None:
            self._dictation_timer.stop()
        self._set_last_validation(verdict)

    def _set_last_validation(self, verdict: Validation) -> None:
        self._last_validation = verdict
        self._view_cache.pop("lastValidation", None)
        self.lastValidationChanged.emit()

    def _on_hotkey_captured(self, chord: str) -> None:
        # Commit exactly the way old VoicePage.qml did: the captured chord is
        # assigned to the backend's hold-to-talk shortcut (persisting setter).
        self._controller.holdVoiceHotkeyText = str(chord)

    def _on_hotkey_capture_error(self, message: str) -> None:
        self._set_last_validation(Validation(False, str(message), "hotkey"))

    def _build_voice_card(self) -> StatusCard:
        controller = self._controller
        ready = bool(getattr(controller, "voiceMappingReady", False))
        detail = str(getattr(controller, "voiceProgramStatusText", "")) or self.audioRouteLabel
        return StatusCard(
            title="语音",
            subtitle=f"{self.recordingMode} · {self.hotkeyLabel}",
            tone="ok" if ready else "warn",  # type: ignore[arg-type]
            detail=detail,
            actionLabel="口述测试",
            actionId=_ACTION_ID_TEST_DICTATION,
        )


# ---------------------------------------------------------------------------
# MappingViewModel
# ---------------------------------------------------------------------------


class MappingViewModel(_ViewmodelBase):
    """Button mapping presentation + editor operations (doc §3/§3.5 D6)."""

    buttonsChanged = Signal()
    presetsChanged = Signal()
    keyDetectionTextChanged = Signal()
    mappingAutoSaveRetryAvailableChanged = Signal()
    shortcutCaptured = Signal(str)

    _NOTIFY_NAMES = (
        "buttonsChanged",
        "presetsChanged",
        "keyDetectionTextChanged",
        "mappingAutoSaveRetryAvailableChanged",
    )

    def __init__(self, mapping_model: Any, controller: Any) -> None:
        super().__init__()
        self._model = mapping_model
        self._controller = controller
        self._presets_loaded = False
        _connect(mapping_model, "mappingEdited", self._emit_changed)
        _connect(mapping_model, "actionEdited", self._emit_changed)
        # Switching device (or restoring defaults) rebuilds the model's rows
        # through ``set_profile``/``reset``, which announce themselves with the
        # standard QAbstractListModel signals rather than a custom one. Without
        # these the Keys page kept showing the previous device's cards.
        for name in ("modelReset", "layoutChanged", "dataChanged",
                     "rowsInserted", "rowsRemoved"):
            _connect(mapping_model, name, self._emit_changed)
        # A device switch also changes which rows the page should show, even
        # when the model itself reports no structural change.
        _connect(controller, "selectedDeviceChanged", self._emit_changed)
        _connect(controller, "mappingPresetsChanged", self._emit_changed)
        _connect(controller, "keyDetectionTextChanged", self._emit_changed)
        _connect(controller, "mappingAutoSaveRetryAvailableChanged", self._emit_changed)
        _connect(controller, "hotkeyCaptured", self._on_shortcut_captured)
        self._ensure_presets_loaded()

    def _on_shortcut_captured(self, text: str) -> None:
        self.shortcutCaptured.emit(str(text))

    def _ensure_presets_loaded(self) -> None:
        """Materialize the preset store through the backend's refresh op.

        The retired MappingPresetsDialog ran ``mappingPresetAction("refresh")``
        on open; without it the preset combo starts empty in real sessions.
        The view-model owns reading (D1), so refresh once at construction and
        retry lazily on first read while the backend is still busy at startup.
        """

        if self._presets_loaded:
            return
        try:
            result = self._controller.mappingPresetAction("refresh", "", "")
        except Exception:
            return
        self._presets_loaded = bool(result.get("ok", False))

    # -- properties --------------------------------------------------------

    @Property(list, notify=buttonsChanged)
    def buttons(self) -> List[QObject]:
        rows = self._build_button_rows()
        return self._cached_views("buttons", rows)

    @Property(list, notify=presetsChanged)
    def presets(self) -> List[QObject]:
        self._ensure_presets_loaded()
        rows = [
            ChoiceRow(
                id=str(row.get("id", "")),
                label=str(row.get("name", "")),
                detail="自动" if row.get("automatic") else "",
                enabled=True,
                selected=bool(row.get("applied")),
            )
            for row in getattr(self._controller, "mappingPresets", []) or []
        ]
        return self._cached_views("presets", rows)

    @Property(str, notify=keyDetectionTextChanged)
    def keyDetectionText(self) -> str:
        return str(getattr(self._controller, "keyDetectionText", ""))

    @Property(bool, notify=mappingAutoSaveRetryAvailableChanged)
    def mappingAutoSaveRetryAvailable(self) -> bool:
        return bool(getattr(self._controller, "mappingAutoSaveRetryAvailable", False))

    # -- slots -------------------------------------------------------------

    @Slot(str, str, str, result="QVariantMap")
    def setAction(self, buttonId: str, gesture: str, actionText: str) -> Validation:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return contract_qml_map(
                Validation(False, f"不支持的手势：{gesture}", gesture)
            )
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return contract_qml_map(Validation(False, f"未知按键：{buttonId}", buttonId))
        # Draft-aware validation: the editor commits the cell's payload before
        # the kind switch (KeysPanel.commitEditor), so the model's current
        # payload IS the draft a kind switch must validate against - the
        # retired combo saved kind+payload atomically and rejecting the switch
        # without it made 输入文字/打开程序 uncreatable.
        message = self._controller.buttonActionValidationMessage(
            buttonId,
            trigger,
            actionText,
            text_content=self._model.textContentAt(row, trigger),
            program_path=self._model.programPathAt(row, trigger),
        )
        if message:
            return contract_qml_map(Validation(False, str(message), buttonId))
        if trigger == "single_click":
            self._model.setActionTextAt(row, actionText)
        else:
            self._model.setSecondaryActionTextAt(row, trigger, actionText)
        return contract_qml_map(Validation(True, "", buttonId))

    @Slot(str, str, str)
    def setNote(self, buttonId: str, gesture: str, note: str) -> None:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return
        self._model.setDisplayNoteAt(row, trigger, note)

    @Slot(str, str, result=str)
    def programPath(self, buttonId: str, gesture: str) -> str:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return ""
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return ""
        return str(self._model.programPathAt(row, trigger))

    @Slot(str, str, result=str)
    def textContent(self, buttonId: str, gesture: str) -> str:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return ""
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return ""
        return str(self._model.textContentAt(row, trigger))

    @Slot(str, str, str, result="QVariantMap")
    def pickProgramPath(self, buttonId: str, gesture: str, fileUrl: str) -> Validation:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return contract_qml_map(Validation(False, f"不支持的手势：{gesture}", gesture))
        path = str(self._controller.programPathFromFileUrl(fileUrl))
        if not path:
            return contract_qml_map(
                Validation(False, "请选择本地程序文件。", buttonId)
            )
        message = self._controller.buttonActionValidationMessage(
            buttonId, trigger, "打开程序", program_path=path
        )
        if message:
            return contract_qml_map(Validation(False, str(message), buttonId))
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return contract_qml_map(Validation(False, f"未知按键：{buttonId}", buttonId))
        self._model.setProgramPathAt(row, trigger, path)
        return contract_qml_map(Validation(True, path, buttonId))

    @Slot(str, str, str, result="QVariantMap")
    def setTextContent(self, buttonId: str, gesture: str, content: str) -> Validation:
        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return contract_qml_map(Validation(False, f"不支持的手势：{gesture}", gesture))
        message = self._controller.buttonActionValidationMessage(
            buttonId, trigger, "输入文字", text_content=content
        )
        if message:
            return contract_qml_map(Validation(False, str(message), buttonId))
        row = self._model.indexOfButton(buttonId)
        if row < 0:
            return contract_qml_map(Validation(False, f"未知按键：{buttonId}", buttonId))
        self._model.setTextContentAt(row, trigger, content)
        return contract_qml_map(Validation(True, "", buttonId))

    @Slot()
    def restoreDefaults(self) -> None:
        self._controller.restoreDefaults()

    @Slot()
    def captureShortcut(self) -> None:
        self._controller.startMappingHotkeyCapture()

    @Slot()
    def stopShortcutCapture(self) -> None:
        self._controller.stopHotkeyCapture()

    @Slot(result="QVariantMap")
    def startKeyDetection(self) -> Validation:
        self._controller.startKeyDetection()
        return contract_qml_map(Validation(True, "", "keyDetection"))

    @Slot(result="QVariantMap")
    def stopKeyDetection(self) -> Validation:
        ok = bool(self._controller.stopKeyDetection())
        return contract_qml_map(
            Validation(ok, "" if ok else "按键检测未能停止；请重试。", "keyDetection")
        )

    @Slot(result="QVariantMap")
    def retryMappingAutoSave(self) -> Validation:
        ok = bool(self._controller.retryMappingAutoSave())
        return contract_qml_map(
            Validation(ok, "" if ok else "保存仍未成功；请稍后重试。", "save")
        )

    @Slot(str, result="QVariantMap")
    def applyPreset(self, id: str) -> Validation:
        return self._preset_action("apply", id, "")

    @Slot(str, result="QVariantMap")
    def savePreset(self, name: str) -> Validation:
        from .. import mapping_presets

        return self._preset_action("copy", mapping_presets.AUTO_ID, name)

    @Slot(str, str, result="QVariantMap")
    def renamePreset(self, id: str, name: str) -> Validation:
        return self._preset_action("rename", id, name)

    @Slot(str, result="QVariantMap")
    def deletePreset(self, id: str) -> Validation:
        return self._preset_action("delete", id, "")

    @Slot(str, str, result="QVariantMap")
    def exportPreset(self, id: str, fileUrl: str) -> Validation:
        return self._preset_action("export", id, fileUrl)

    @Slot(str, result="QVariantMap")
    def importPreset(self, fileUrl: str) -> Validation:
        return self._preset_action("import", "", fileUrl)

    @Slot(str, str, result=list)
    def actionOptions(self, buttonId: str, gesture: str) -> List[QObject]:
        """Editor dropdown choices, grouped by ``detail`` (old UI option sets)."""

        trigger = GESTURE_TRIGGERS.get(gesture)
        if trigger is None:
            return []
        controller = self._controller
        if trigger == "single_click":
            labels = list(controller.primaryActionOptionsFor(buttonId))
        elif trigger == "double_click":
            labels = list(controller.secondaryActionOptionsFor(buttonId))
        else:
            labels = list(controller.longPressActionOptionsFor(buttonId))
        current = self._current_action_text(buttonId, gesture)
        rows = [
            ChoiceRow(
                id=str(label),
                label=str(label),
                detail=str(controller.actionOptionGroupTitle(str(label))),
                enabled=True,
                selected=(str(label) == current),
            )
            for label in labels
        ]
        return self._cached_views(f"actionOptions:{buttonId}:{gesture}", rows)

    # -- internals ---------------------------------------------------------

    def _preset_action(self, operation: str, identity: str, text: str) -> Validation:
        result = self._controller.mappingPresetAction(operation, identity, text)
        return contract_qml_map(
            Validation(
                bool(result.get("ok", False)),
                str(result.get("message", "")),
                str(result.get("id", "")),
            )
        )

    def _current_action_text(self, buttonId: str, gesture: str) -> str:
        for row in self._build_button_rows():
            if row.id == buttonId:
                return {
                    "single": row.single,
                    "double": row.double,
                    "longPress": row.longPress,
                }.get(gesture, "")
        return ""

    def _build_button_rows(self) -> List[ButtonRow]:
        model = self._model
        roles = {
            bytes(name).decode("utf-8"): role for role, name in model.roleNames().items()
        }

        def value(row_index: int, name: str, default: Any) -> Any:
            role = roles.get(name)
            if role is None:
                return default
            raw = model.data(model.index(row_index), role)
            return default if raw is None else raw

        rows: List[ButtonRow] = []
        for row_index in range(model.rowCount()):
            rows.append(
                ButtonRow(
                    id=str(value(row_index, "buttonId", "")),
                    label=str(value(row_index, "displayName", "")),
                    single=str(value(row_index, "actionText", "")),
                    double=str(value(row_index, "doubleClickText", "")),
                    longPress=str(value(row_index, "longPressText", "")),
                    isMic=bool(value(row_index, "isMic", False)),
                    singleNote=str(value(row_index, "singleNote", "")),
                    doubleNote=str(value(row_index, "doubleNote", "")),
                    longNote=str(value(row_index, "longNote", "")),
                )
            )
        return rows


# ---------------------------------------------------------------------------
# MaintenanceViewModel
# ---------------------------------------------------------------------------


class MaintenanceViewModel(_ViewmodelBase):
    """Update / HID helper / diagnostics / logs / system affordances and the
    boolean preferences (doc §3.5 D3/D4).
    """

    itemsChanged = Signal()
    updateStatusChanged = Signal()
    preferencesChanged = Signal()

    _NOTIFY_NAMES = ("itemsChanged", "updateStatusChanged", "preferencesChanged")

    def __init__(self, controller: Any, diagnostics: Any) -> None:
        super().__init__()
        self._controller = controller
        self._diagnostics = diagnostics
        for name in (
            "applicationUpdateChanged",
            "logExportBusyChanged",
            "hidHelperStateChanged",
            "hidHelperRepairBusyChanged",
            "desktopBehaviorChanged",
            "settingsDirtyChanged",
            "mappingDirtyChanged",
        ):
            _connect(controller, name, self._emit_changed)
        for name in ("checkResultsChanged", "isRefreshingChanged", "diagnosticsErrorMessageChanged"):
            _connect(diagnostics, name, self._emit_changed)

    # -- properties --------------------------------------------------------

    @Property(list, notify=itemsChanged)
    def items(self) -> List[QObject]:
        rows = []
        for item_id in MAINTENANCE_ITEM_IDS:
            title, detail_hint, action_label = _ITEM_DEFS[item_id]
            status, detail = self._item_state(item_id, detail_hint)
            rows.append(
                CheckRow(
                    id=item_id,
                    title=title,
                    status=status,  # type: ignore[arg-type]
                    detail=detail,
                    fixLabel=action_label,
                )
            )
        return self._cached_views("items", rows)

    @Property(QObject, notify=updateStatusChanged)
    def updateStatus(self) -> QObject:
        return self._cached_view("updateStatus", self._build_update_status())

    @Property(list, notify=preferencesChanged)
    def preferences(self) -> List[QObject]:
        controller = self._controller
        enabled = not bool(getattr(controller, "configurationReadOnly", False))
        values = {
            "start_with_windows": bool(getattr(controller, "launchAtLogin", False)),
            "auto_start_bridge": bool(getattr(controller, "launchBridgeOnAppStart", False)),
            "diagnostic_logging": bool(getattr(controller, "diagnosticTraceEnabled", False)),
            "hide_to_tray_on_close": _prefers_hide_to_tray(
                str(getattr(controller, "closeBehavior", ""))
            ),
        }
        rows = [
            ToggleRow(
                id=pref_id,
                label=_PREFERENCE_LABELS[pref_id],
                detail="",
                value=values[pref_id],
                enabled=enabled,
            )
            for pref_id in PREFERENCE_IDS
        ]
        return self._cached_views("preferences", rows)

    # -- slots -------------------------------------------------------------

    @Slot(str)
    def run(self, item: str) -> None:
        """Closed dispatch over ``MAINTENANCE_ITEM_IDS`` - presentation-level
        ids mapped onto the existing controller/diagnostics affordances.
        """

        controller = self._controller
        if item == "update":
            if bool(getattr(controller, "applicationUpdateBusy", False)):
                return
            if bool(getattr(controller, "applicationUpdateCanDownload", False)):
                controller.downloadApplicationUpdate()
            elif str(getattr(controller, "applicationUpdateDownloadedPath", "")):
                controller.openDownloadedApplicationUpdate()
            else:
                controller.checkForApplicationUpdate()
        elif item == "helper":
            if not bool(getattr(controller, "hidHelperRepairBusy", False)):
                controller.repairHidHelper()
        elif item == "diagnostics":
            self._diagnostics.refreshDiagnostics()
        elif item == "logs":
            controller.exportLogs(controller.logExportDefaultFile())
        elif item == "bluetooth":
            controller.openBluetoothSettings()
        elif item == "guide":
            controller.openUsageGuide()

    @Slot(str, bool, result="QVariantMap")
    def setPreference(self, id: str, value: bool) -> Validation:
        controller = self._controller
        if bool(getattr(controller, "configurationReadOnly", False)):
            return contract_qml_map(
                Validation(
                    False,
                    str(getattr(controller, "configurationError", "")) or "配置为只读，无法修改。",
                    id,
                )
            )
        if id == "start_with_windows":
            controller.setLaunchAtLogin(bool(value))
        elif id == "auto_start_bridge":
            controller.setLaunchBridgeOnAppStart(bool(value))
        elif id == "diagnostic_logging":
            controller.setDiagnosticTraceEnabled(bool(value))
        elif id == "hide_to_tray_on_close":
            controller.setCloseBehaviorIndex(0 if value else 1)
        else:
            return contract_qml_map(Validation(False, f"未知偏好项：{id}", id))
        return contract_qml_map(Validation(True, "", id))

    @Slot(result="QVariantMap")
    def confirmExitSave(self) -> Validation:
        """Save-on-exit decision exactly as the old exit prompt made it:
        dirty -> the backend's save-and-exit flow; clean -> plain exit flow.
        """

        controller = self._controller
        if bool(controller.canAutoSaveMappingBeforeExit()):
            controller.saveSettingsAndExit()
            verdict = Validation(True, "正在保存并退出。", "")
        else:
            controller.requestApplicationExit()
            verdict = Validation(True, "没有待保存的更改，正在退出。", "")
        return contract_qml_map(verdict)

    @Slot(str, result="QVariantMap")
    def saveLogs(self, fileUrl: str) -> Validation:
        controller = self._controller
        if bool(getattr(controller, "logExportBusy", False)):
            return contract_qml_map(Validation(False, "日志导出进行中。", "logs"))
        ok = bool(controller.exportLogs(fileUrl))
        return contract_qml_map(
            Validation(ok, "" if ok else "日志导出失败；请查看 app.log。", "logs")
        )

    @Slot(result="QVariantMap")
    def openLogs(self) -> Validation:
        ok = bool(self._controller.openLogLocation())
        return contract_qml_map(
            Validation(ok, "" if ok else "无法打开日志目录。", "logs")
        )

    @Slot(result="QVariantMap")
    def openMicrophonePrivacySettings(self) -> Validation:
        self._controller.openMicrophonePrivacySettings()
        return contract_qml_map(Validation(True, "", "system"))

    @Slot(result="QVariantMap")
    def openSpeechSettings(self) -> Validation:
        self._controller.openSpeechSettings()
        return contract_qml_map(Validation(True, "", "system"))

    @Slot(result="QVariantMap")
    def openSoundSettings(self) -> Validation:
        self._controller.openSoundSettings()
        return contract_qml_map(Validation(True, "", "system"))

    @Slot(result="QVariantMap")
    def openAppsSettings(self) -> Validation:
        self._controller.openAppsSettings()
        return contract_qml_map(Validation(True, "", "system"))

    @Slot(result="QVariantMap")
    def removeHelper(self) -> Validation:
        self._controller.removeHidHelper()
        return contract_qml_map(Validation(True, "", "helper"))

    @Slot(result="QVariantMap")
    def cancelUpdateDownload(self) -> Validation:
        ok = bool(self._controller.cancelApplicationUpdateDownload())
        return contract_qml_map(
            Validation(ok, "" if ok else "没有正在进行的更新下载。", "update")
        )

    @Slot(result="QVariantMap")
    def openUpdateRelease(self) -> Validation:
        ok = bool(self._controller.openApplicationUpdateRelease())
        return contract_qml_map(
            Validation(ok, "" if ok else "无法打开更新发布页。", "update")
        )

    # -- internals ---------------------------------------------------------

    def _item_state(self, item_id: str, detail_hint: str) -> Tuple[str, str]:
        controller = self._controller
        diagnostics = self._diagnostics
        if item_id == "update":
            if bool(getattr(controller, "applicationUpdateBusy", False)):
                return "current", str(getattr(controller, "applicationUpdateMessage", ""))
            if bool(getattr(controller, "applicationUpdateCanDownload", False)):
                return "todo", str(getattr(controller, "applicationUpdateMessage", ""))
            return "done", str(getattr(controller, "applicationUpdateMessage", ""))
        if item_id == "helper":
            if bool(getattr(controller, "hidHelperRepairBusy", False)):
                return "current", str(getattr(controller, "hidHelperIssueText", ""))
            if bool(getattr(controller, "hidHelperIssueVisible", False)) or bool(
                getattr(controller, "hidHelperSetupRequired", False)
            ):
                return "failed", str(getattr(controller, "hidHelperIssueText", ""))
            return "done", ""
        if item_id == "diagnostics":
            if bool(getattr(diagnostics, "isRefreshing", False)):
                return "current", ""
            if str(getattr(diagnostics, "diagnosticsErrorMessage", "")):
                return "failed", str(getattr(diagnostics, "diagnosticsErrorMessage", ""))
            return "done", ""
        return "todo", detail_hint

    def _build_update_status(self) -> StatusCard:
        controller = self._controller
        if bool(getattr(controller, "applicationUpdateCanDownload", False)):
            tone = "warn"
        elif bool(getattr(controller, "applicationUpdateBusy", False)):
            tone = "idle"
        else:
            tone = "ok"
        latest = str(getattr(controller, "applicationUpdateLatestVersion", ""))
        return StatusCard(
            title="软件更新",
            subtitle=f"最新版本 {latest}" if latest else "",
            tone=tone,  # type: ignore[arg-type]
            detail=str(getattr(controller, "applicationUpdateMessage", "")),
            actionLabel="下载更新" if getattr(controller, "applicationUpdateCanDownload", False) else "检查更新",
            actionId=_ACTION_ID_UPDATE,
        )


def _recording_limits() -> Tuple[int, ...]:
    """Supported maximum recording durations (seconds) - backend constants."""

    from .. import chromecast_voice

    return tuple(int(value) for value in chromecast_voice.LIMITS)
