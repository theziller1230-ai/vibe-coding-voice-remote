"""First-run acceptance wizard (slice C): ``OnboardingViewModel``.

This module is the presentation-layer (layer 2) view-model for the five-step
first-run setup wizard.  Per ``docs/UI-REDESIGN.md`` section 3 the exported
surface is exactly ``steps``, ``currentStep``, ``canContinue``, ``next()``,
``back()``, ``repair(stepId)`` and ``verifyCurrent()``.

The wizard is an **acceptance walkthrough, not a feature tour**: a step is
complete only when this software observes the real outcome, and no step can be
skipped.  The observable facts are read from the existing backend surfaces
(never reimplemented here):

========================================  ==========================================
Evidence                                  Backend source (read, not reimplemented)
========================================  ==========================================
Remote key device present                 ``windows_diagnostics.check_raw_input``
                                          (the same check ``DiagnosticsController``
                                          renders as a row)
Real button event ("sending events")      ``key_detection_bridge`` one-shot IPC
                                          (the bridge publishes the next real
                                          button id, including ``mic``)
Permission / authorization chain live     ``bridge_runtime_status`` input-channel
                                          and authorization states
Virtual cable's two ends exist/match      ``audio_output`` endpoint enumeration
                                          (``is_cable_input_endpoint`` /
                                          ``is_cable_output_endpoint``)
Audio actually travels the route          ``windows_diagnostics.
                                          check_vb_cable_loopback_isolated``
                                          (sweeps CABLE Input, listens on the
                                          matching CABLE Output)
Tool holds an active capture session      ``chromecast_host_activity.
                                          read_doubao_capture`` (and the sibling
                                          readers for the other tools)
Genuinely non-empty audio arrived         the PCM frame counter where it is
                                          counted and logged
                                          (``voice_audio_session`` "voice PCM
                                          progress" log lines: frames and peak)
Text arrived in the bound target field    ``voice_interaction_diagnostics_windows.
                                          capture_focus_snapshot/compare_submission``
                                          (WM_GETTEXTLENGTH delta on the focused
                                          native edit control)
========================================  ==========================================

Step 5 is the acceptance gate.  One attempt is only accepted when ALL of the
following were observed inside the attempt's own bounded window:

1. a **fresh** capture session started (a session already active when the
   attempt began is stale and never counts),
2. the expected control (the remote's voice key) was used,
3. genuinely non-empty audio arrived (frames > 0 **and** peak > 0),
4. the user ended that session,
5. the target field's text grew afterwards.

Discrimination implemented (exactly what the observations support):

* **Stale results** — the field baseline is taken at attempt start, every
  piece of evidence is bound to the current attempt generation, and text that
  first appears before the observed session ended (i.e. hand typing during the
  run, or a late result left over from an earlier attempt) is rejected.
* **Late results** — text that first appears after the settle window closes is
  rejected as late.
* **Output shown elsewhere** — the target field is bound (field identity) at
  attempt start; growth observed on a different field/focus is rejected.
* **Hand-entered text** — text growth observed before the session ended, or
  growth the observation surface attributes to keyboard/clipboard input, is
  rejected.  Where the view can cut the keyboard and paste routes at the
  insertion point, the only remaining insertion channel is the input method.

What this gate CANNOT distinguish, stated plainly instead of simulated:

* Whether the tool's text *finally landed* in the target field cannot be
  observed directly: the only text observable is a text-length delta on the
  focused **native** edit control (WM_GETTEXTLENGTH).  A length delta has no
  input-source attribution — IME commits, manual typing and paste all change
  the length identically — and the privacy contract forbids reading text.
  A hand-typed or pasted string that lands in the bound field during the
  post-session settle window is therefore indistinguishable from tool output;
  only its timing/provenance outside that window can be rejected.
* The wizard's own QML controls are not native edit controls and are
  invisible to the Win32 length probe, so the bound target field must be a
  system text box (e.g. Notepad); this is spelled out in the step guidance
  and in the ``no_field`` repair action.
* Audio silence carrying frames (peak == 0) is rejected as empty; a peak that
  is nonzero is "non-empty" but is not proof of speech.
* Physical-keyboard provenance tracking exists only inside the bridge process
  and is not published cross-process, so it is not available here.

Settings collected along the way are **staged** in memory (and mirrored into
the wizard's own progress file for recoverability) and are committed to the
real configuration exactly once — only after the final gate passes.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QObject, Property, Signal, Slot

from .contracts import StepStatus, Validation

# ---------------------------------------------------------------------------
# Step vocabulary (display wording lives here; QML only renders these values).
# ---------------------------------------------------------------------------

STEP_IDS: tuple[str, ...] = (
    "connect_device",
    "system_permissions",
    "audio_route",
    "voice_tool",
    "dictation_check",
)

STEP_TITLES: dict[str, str] = {
    "connect_device": "连接遥控器",
    "system_permissions": "系统权限",
    "audio_route": "音频路由",
    "voice_tool": "语音转写工具",
    "dictation_check": "口述测试",
}

# Cause -> (what went wrong, the single repair action).  The repair action text
# always names its cause when the step status is rendered (fixLabel embeds the
# cause text), so a failure exposes exactly one repair action that names why.
_CAUSES: dict[str, tuple[str, str]] = {
    "device_missing": ("未找到遥控器按键设备", "完成遥控器蓝牙配对后重新检测"),
    "device_ambiguous": ("找到多个遥控器按键设备", "只保留一个已连接的遥控器后重新检测"),
    "device_probe_failed": ("按键设备检测未完成", "重新检测按键设备"),
    "no_button_event": ("未收到遥控器按键事件", "按下遥控器任意按键后重新检测"),
    "service_not_running": ("遥控器服务未运行", "启动遥控器服务后重新检测"),
    "authorization_incomplete": ("管理员授权未完成", "重新完成管理员授权后重新检测"),
    "input_channels_not_ready": ("按键接收通道未就绪", "重启遥控器服务后重新检测"),
    "no_output_selected": ("尚未选择语音输出端点", "在设置中选择 CABLE Input 输出端点"),
    "output_endpoint_missing": ("所选输出端点不存在", "重新选择输出端点"),
    "endpoint_not_cable_input": ("所选输出端点不是 CABLE Input", "改选 CABLE Input 输出端点"),
    "cable_output_missing": ("缺少 CABLE Output 录音端点，虚拟声卡两端不匹配", "安装 VB-CABLE 驱动后重新检测"),
    "route_probe_failed": ("音频通道测试未通过", "重测音频通道（CABLE Input → CABLE Output）"),
    "no_tool_selected": ("尚未选择语音转写工具", "在语音设置中选择转写工具"),
    "tool_not_capturing": ("转写工具未在采集声音", "在转写工具中开始麦克风采集后重新检测"),
    "tool_mic_not_cable": ("转写工具的麦克风不是 CABLE Output", "在转写工具设置中把麦克风改为 CABLE Output"),
    "no_field": ("未找到可观察的系统文本输入框", "在记事本等系统文本框中放置光标"),
    "no_control": ("未检测到语音键按下", "短按遥控器语音键后重新口述"),
    "no_fresh_session": ("转写工具未开始新的采集会话", "按住遥控器语音键重新口述"),
    "audio_empty": ("未收到非空音频（没有有效声音信号）", "检查音频路由后重新口述"),
    "session_not_ended": ("采集会话未结束", "松开语音键结束口述"),
    "hand_entered": ("检测到手工输入或残留的文字，无法确认来自口述", "重新口述，期间不要手工输入或粘贴"),
    "field_changed": ("光标离开了测试输入框", "将光标保持在测试输入框内重新口述"),
    "output_late": ("文字结果超过时限才到达", "重新口述一次"),
    "output_not_observed": ("未观察到文字上屏", "在转写工具中检查麦克风与识别设置后重新口述"),
    "commit_failed": ("设置未能写入", "重试保存设置"),
    "check_failed": ("检测未能完成", "重新检测本步"),
}

# Each failure is repaired at the nearest affected step — not necessarily the
# step whose verification noticed it.
_REPAIR_TARGET: dict[str, str] = {
    "device_missing": "connect_device",
    "device_ambiguous": "connect_device",
    "device_probe_failed": "connect_device",
    "no_button_event": "connect_device",
    "service_not_running": "system_permissions",
    "authorization_incomplete": "system_permissions",
    "input_channels_not_ready": "system_permissions",
    "no_output_selected": "audio_route",
    "output_endpoint_missing": "audio_route",
    "endpoint_not_cable_input": "audio_route",
    "cable_output_missing": "audio_route",
    "route_probe_failed": "audio_route",
    "no_tool_selected": "voice_tool",
    "tool_not_capturing": "voice_tool",
    "tool_mic_not_cable": "voice_tool",
    "no_field": "dictation_check",
    "no_control": "dictation_check",
    "no_fresh_session": "voice_tool",
    "audio_empty": "audio_route",
    "session_not_ended": "dictation_check",
    "hand_entered": "dictation_check",
    "field_changed": "dictation_check",
    "output_late": "dictation_check",
    "output_not_observed": "voice_tool",
    "commit_failed": "dictation_check",
    # "check_failed" repairs at the step whose probe broke (resolved dynamically).
}

# Observation cadence and bounded windows (seconds).
POLL_INTERVAL_SECONDS = 0.5
BUTTON_EVENT_WINDOW_SECONDS = 30.0
DICTATION_START_WINDOW_SECONDS = 45.0
DICTATION_END_WINDOW_SECONDS = 45.0
DICTATION_SETTLE_SECONDS = 12.0
DICTATION_LATE_GRACE_SECONDS = 4.0

_HAND_ENTERED_SOURCES = frozenset({"keyboard", "clipboard", "paste", "manual"})


def _fix_label(cause: str) -> str:
    cause_text, action = _CAUSES[cause]
    return f"{action}（{cause_text}）"


# ---------------------------------------------------------------------------
# Observation seam values (plain data, no Qt, no backend types cross here).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    """One tool capture session as observed through the WASAPI session API."""

    endpoint_id: str
    instance_id: str
    pid: int
    active: bool

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.endpoint_id, self.instance_id, self.pid


@dataclass(frozen=True)
class FieldObservation:
    """The bound target field: identity plus text length where observable."""

    field_id: str
    text_length: Optional[int]
    editable: bool
    supported: bool
    raw: Any = None  # backend snapshot kept for the real diff seam; fakes omit it


@dataclass(frozen=True)
class FieldDiff:
    """Text growth on the bound field since its baseline observation."""

    same_field: bool
    growth: Optional[int]  # None when the surface cannot observe the field
    source: str  # "unknown" | "ime" | "keyboard" | "clipboard" | "manual"


@dataclass(frozen=True)
class ProbeVerdict:
    """Outcome of one real backend check, already translated to a cause key."""

    ok: bool
    cause: str  # "" when ok; otherwise a key of ``_CAUSES``
    detail: str


@dataclass(frozen=True)
class StagedSettings:
    """Settings staged by the wizard; committed only at the final gate."""

    voice_program: str = ""
    output_endpoint_name: str = ""
    output_endpoint_host_api: str = ""


@dataclass(frozen=True)
class ProgressState:
    """Wizard progress mirrored to disk so closing/reopening resumes."""

    current_index: int
    verified_ids: tuple[str, ...]
    staged: StagedSettings


@dataclass(frozen=True)
class OnboardingEnvironment:
    """Every observation the wizard needs, injected so tests run anywhere.

    The real implementations (``real_environment``) read the existing backend
    surfaces listed in the module docstring; nothing is reimplemented there.
    """

    probe_device: Callable[[], ProbeVerdict]
    arm_control_watch: Callable[[], Any]
    poll_control_watch: Callable[[Any], str]
    cancel_control_watch: Callable[[Any], None]
    probe_permissions: Callable[[], ProbeVerdict]
    probe_cable_ends: Callable[[str, str], ProbeVerdict]
    probe_route: Callable[[str, str], ProbeVerdict]
    tool_sessions: Callable[[str], tuple[SessionInfo, ...]]
    cable_output_endpoint_id: Callable[[], str]
    pcm_watermark: Callable[[], int]
    pcm_progress: Callable[[int], tuple[int, int]]
    observe_field: Callable[[], FieldObservation]
    diff_field: Callable[[FieldObservation], FieldDiff]
    load_settings: Callable[[], StagedSettings]
    commit: Callable[[StagedSettings], None]
    load_progress: Callable[[], Optional[ProgressState]]
    save_progress: Callable[[ProgressState], None]
    now: Callable[[], float]
    sleep: Callable[[float], None]


# ---------------------------------------------------------------------------
# Step 5 acceptance attempt: the discrimination logic, pure and testable.
# ---------------------------------------------------------------------------


class _DictationAttempt:
    """One bounded acceptance run over the observable chain.

    All evidence is bound to this attempt: sessions active before it started
    are baselined out (stale), the target field is bound by identity at start,
    and text growth is classified by when it is first observed relative to the
    observed session end — growth before the end is hand-entered or a leftover
    result from an earlier attempt, growth inside the settle window is the
    tool's candidate output, growth after it is late and rejected.
    """

    def __init__(self, env: OnboardingEnvironment, provider: str) -> None:
        self._env = env
        self._provider = provider
        self._baseline = {
            session.identity for session in env.tool_sessions(provider) if session.active
        }
        self.field0 = env.observe_field()
        self._control_token = env.arm_control_watch()
        self._watermark = env.pcm_watermark()
        start = env.now()
        self._start_deadline = start + DICTATION_START_WINDOW_SECONDS
        self._end_deadline = self._start_deadline + DICTATION_END_WINDOW_SECONDS
        self._settle_deadline: Optional[float] = None
        self._late_deadline: Optional[float] = None
        self.control_used = False
        self.fresh_started = False
        self.session_ended = False
        self.frames = 0
        self.peak = 0
        self.hand_entered = False
        self.field_changed = False
        self.output_growth = 0
        self.output_late = False
        self._fresh_ids: set[tuple[str, str, int]] = set()

    # -- observation -------------------------------------------------------

    def tick(self) -> bool:
        """Poll every observation once; return True when the chain is proven."""

        env = self._env
        now = env.now()
        if not self.control_used:
            button = env.poll_control_watch(self._control_token)
            if button == "mic":
                self.control_used = True
            elif button:
                # Any other button consumed the one-shot watch; re-arm so the
                # voice key press can still be observed.
                self._control_token = env.arm_control_watch()
        sessions = env.tool_sessions(self._provider)
        active_ids = {s.identity for s in sessions if s.active}
        new_ids = active_ids - self._baseline
        if new_ids and not self.fresh_started:
            self.fresh_started = True
            self._fresh_ids = set(new_ids)
            self._end_deadline = now + DICTATION_END_WINDOW_SECONDS
        if self.fresh_started and not self.session_ended and not (
            active_ids & self._fresh_ids
        ):
            self.session_ended = True
            self._settle_deadline = now + DICTATION_SETTLE_SECONDS
            self._late_deadline = self._settle_deadline + DICTATION_LATE_GRACE_SECONDS
        if self.fresh_started and not self.session_ended:
            frames, peak = env.pcm_progress(self._watermark)
            self.frames = max(self.frames, int(frames))
            self.peak = max(self.peak, int(peak))
        diff = env.diff_field(self.field0)
        if not diff.same_field:
            self.field_changed = True
        growth = 0 if diff.growth is None else int(diff.growth)
        if growth > 0 and self.output_growth == 0 and not self.hand_entered:
            if diff.source in _HAND_ENTERED_SOURCES:
                self.hand_entered = True
            elif not self.session_ended:
                # The tool cannot have produced final output yet: this growth
                # is hand typing or a stale result from an earlier attempt.
                self.hand_entered = True
            elif self._settle_deadline is not None and now <= self._settle_deadline:
                self.output_growth = growth
            else:
                self.output_late = True
        return self.complete()

    def close(self) -> None:
        """Release the one-shot control watch; a stale watch would steal the
        user's next voice-key press outside the wizard."""

        self._env.cancel_control_watch(self._control_token)

    def complete(self) -> bool:
        return (
            self.control_used
            and self.fresh_started
            and self.session_ended
            and self.frames > 0
            and self.peak > 0
            and self.output_growth > 0
            and not self.hand_entered
            and not self.field_changed
        )

    def expired(self) -> bool:
        now = self._env.now()
        if not self.fresh_started:
            return now >= self._start_deadline
        if not self.session_ended:
            return now >= self._end_deadline
        return self._late_deadline is not None and now >= self._late_deadline

    def failure_cause(self) -> str:
        if self.field_changed:
            return "field_changed"
        if self.hand_entered:
            return "hand_entered"
        if not self.control_used:
            return "no_control"
        if not self.fresh_started:
            return "no_fresh_session"
        if not (self.frames > 0 and self.peak > 0):
            return "audio_empty"
        if not self.session_ended:
            return "session_not_ended"
        if self.output_late:
            return "output_late"
        return "output_not_observed"


# ---------------------------------------------------------------------------
# Flow core: pure state machine over the environment seams.
# ---------------------------------------------------------------------------


class OnboardingFlow:
    """Verification flow state for the five acceptance steps."""

    def __init__(self, environment: OnboardingEnvironment) -> None:
        self._env = environment
        self._index = 0
        self._statuses: dict[str, StepStatus] = {}
        self._verified: dict[str, bool] = {}
        self._staged = StagedSettings()
        self._commit_count = 0
        self._progress: Callable[[str], None] = lambda _note: None
        self._reset_statuses()
        restored = environment.load_progress()
        if restored is not None:
            self._restore(restored)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def commit_count(self) -> int:
        return self._commit_count

    @property
    def staged(self) -> StagedSettings:
        return self._staged

    def snapshot(self) -> list[StepStatus]:
        return [self._statuses[step_id] for step_id in STEP_IDS]

    def can_continue(self) -> bool:
        return bool(self._verified.get(STEP_IDS[self._index], False))

    def set_progress_sink(self, sink: Callable[[str], None]) -> None:
        self._progress = sink if sink is not None else (lambda _note: None)

    def _reset_statuses(self) -> None:
        for position, step_id in enumerate(STEP_IDS):
            self._statuses[step_id] = StepStatus(
                id=step_id,
                title=STEP_TITLES[step_id],
                state="current" if position == 0 else "todo",
                detail="",
                fixLabel="",
            )
            self._verified[step_id] = False

    def _emit_progress(self, note: str) -> None:
        current = STEP_IDS[self._index]
        self._statuses[current] = replace(self._statuses[current], detail=note)
        self._progress(note)

    def _restore(self, restored: ProgressState) -> None:
        verified_ids = set(restored.verified_ids)
        for position, step_id in enumerate(STEP_IDS):
            done = step_id in verified_ids
            self._verified[step_id] = done
            if done:
                self._statuses[step_id] = replace(
                    self._statuses[step_id], state="done"
                )
        index = int(restored.current_index)
        if not 0 <= index < len(STEP_IDS):
            index = 0
        self._index = index
        self._staged = restored.staged
        self._statuses[STEP_IDS[self._index]] = replace(
            self._statuses[STEP_IDS[self._index]], state="current"
        )

    def _save(self) -> None:
        self._env.save_progress(
            ProgressState(
                current_index=self._index,
                verified_ids=tuple(
                    step_id for step_id in STEP_IDS if self._verified[step_id]
                ),
                staged=self._staged,
            )
        )
    # -- navigation --------------------------------------------------------

    def advance(self) -> None:
        if not self.can_continue() or self._index >= len(STEP_IDS) - 1:
            return
        self._index += 1
        current = STEP_IDS[self._index]
        self._statuses[current] = replace(self._statuses[current], state="current")
        self._save()

    def back(self) -> None:
        if self._index <= 0:
            return
        self._index -= 1
        self._save()

    def repair(self, step_id: str) -> None:
        """Return to the affected step; later results are no longer trusted."""

        target = self._resolve_step_id(step_id)
        if target is None:
            return
        index = STEP_IDS.index(target)
        self._index = index
        for later in STEP_IDS[index:]:
            self._verified[later] = False
            self._statuses[later] = replace(
                self._statuses[later], state="todo", detail="", fixLabel=""
            )
        self._statuses[target] = replace(
            self._statuses[target], state="current", detail="", fixLabel=""
        )
        self._save()

    @staticmethod
    def _resolve_step_id(step_id: str) -> Optional[str]:
        value = str(step_id)
        if value in STEP_IDS:
            return value
        if value.isdigit() and int(value) < len(STEP_IDS):
            return STEP_IDS[int(value)]
        return None

    # -- verification ------------------------------------------------------

    def verify(self) -> Validation:
        step_id = STEP_IDS[self._index]
        try:
            ok, detail, cause = self._verify_step(step_id)
        except Exception as exc:  # noqa: BLE001 - a broken probe is a failed check
            ok, detail, cause = False, f"检测未能完成：{type(exc).__name__}", "check_failed"
        if ok:
            if step_id == "dictation_check":
                try:
                    self._commit()
                except Exception as exc:  # noqa: BLE001 - gate passed, save failed
                    ok = False
                    detail = f"设置未能写入：{type(exc).__name__}"
                    cause = "commit_failed"
        if ok:
            self._verified[step_id] = True
            self._statuses[step_id] = replace(
                self._statuses[step_id], state="done", detail=detail, fixLabel=""
            )
            for other in STEP_IDS:  # fresh evidence supersedes stale failures
                status = self._statuses[other]
                if status.state == "failed":
                    restored = (
                        "done"
                        if self._verified[other]
                        else "current"
                        if other == step_id
                        else "todo"
                    )
                    self._statuses[other] = replace(
                        status, state=restored, fixLabel=""
                    )
        else:
            self._fail(cause, detail)
        self._save()
        return Validation(ok=bool(ok), message=detail, field=step_id)

    def _fail(self, cause: str, detail: str) -> None:
        target = (
            STEP_IDS[self._index]
            if cause == "check_failed"
            else _REPAIR_TARGET[cause]
        )
        cause_text = _CAUSES[cause][0]
        self._statuses[target] = replace(
            self._statuses[target],
            state="failed",
            detail=cause_text,
            fixLabel=_fix_label(cause),
        )
        current = STEP_IDS[self._index]
        if target != current:
            self._statuses[current] = replace(
                self._statuses[current],
                state="current",
                detail=f"验证未通过：{cause_text}；请修复受影响项目",
                fixLabel="",
            )

    def _commit(self) -> None:
        self._env.commit(self._staged)
        self._commit_count += 1

    def _verify_step(self, step_id: str) -> tuple[bool, str, str]:
        if step_id == "connect_device":
            return self._verify_connect_device()
        if step_id == "system_permissions":
            return self._verify_system_permissions()
        if step_id == "audio_route":
            return self._verify_audio_route()
        if step_id == "voice_tool":
            return self._verify_voice_tool()
        return self._verify_dictation()

    def _verify_connect_device(self) -> tuple[bool, str, str]:
        verdict = self._env.probe_device()
        if not verdict.ok:
            return False, verdict.detail, verdict.cause or "device_probe_failed"
        self._emit_progress("等待按下遥控器任意按键…")
        token = self._env.arm_control_watch()
        deadline = self._env.now() + BUTTON_EVENT_WINDOW_SECONDS
        try:
            while True:
                button = self._env.poll_control_watch(token)
                if button:
                    return True, f"已连接并收到按键事件：{button}", ""
                if self._env.now() >= deadline:
                    return False, _CAUSES["no_button_event"][0], "no_button_event"
                self._env.sleep(POLL_INTERVAL_SECONDS)
        finally:
            self._env.cancel_control_watch(token)

    def _verify_system_permissions(self) -> tuple[bool, str, str]:
        verdict = self._env.probe_permissions()
        return verdict.ok, verdict.detail, verdict.cause

    def _verify_audio_route(self) -> tuple[bool, str, str]:
        settings = self._env.load_settings()
        name = settings.output_endpoint_name
        host_api = settings.output_endpoint_host_api
        verdict = self._env.probe_cable_ends(name, host_api)
        if not verdict.ok:
            return False, verdict.detail, verdict.cause
        self._emit_progress("正在测试音频通道（CABLE Input → CABLE Output）…")
        verdict = self._env.probe_route(name, host_api)
        if not verdict.ok:
            return False, verdict.detail, verdict.cause
        self._staged = replace(
            self._staged,
            output_endpoint_name=name,
            output_endpoint_host_api=host_api,
        )
        return True, f"音频通道已验证：{name} → CABLE Output", ""

    def _verify_voice_tool(self) -> tuple[bool, str, str]:
        settings = self._env.load_settings()
        provider = settings.voice_program
        if not provider or provider == "none":
            return False, _CAUSES["no_tool_selected"][0], "no_tool_selected"
        active = [s for s in self._env.tool_sessions(provider) if s.active]
        if not active:
            return False, _CAUSES["tool_not_capturing"][0], "tool_not_capturing"
        cable_id = self._env.cable_output_endpoint_id()
        if cable_id and all(s.endpoint_id != cable_id for s in active):
            return False, _CAUSES["tool_mic_not_cable"][0], "tool_mic_not_cable"
        mic_note = "，麦克风为 CABLE Output" if cable_id else ""
        self._staged = replace(self._staged, voice_program=provider)
        return True, f"转写工具正在采集{mic_note}", ""

    def _verify_dictation(self) -> tuple[bool, str, str]:
        settings = self._env.load_settings()
        provider = settings.voice_program or "doubao_ime"
        self._emit_progress("请短按一次遥控器语音键，然后按住说话、松开结束…")
        attempt = _DictationAttempt(self._env, provider)
        try:
            if not attempt.field0.supported or not attempt.field0.editable:
                return False, _CAUSES["no_field"][0], "no_field"
            while True:
                if attempt.tick():
                    return (
                        True,
                        "口述验证通过：语音键 → 新采集会话 → 非空音频 → 会话结束 → 文字上屏",
                        "",
                    )
                if attempt.expired():
                    break
                self._env.sleep(POLL_INTERVAL_SECONDS)
            cause = attempt.failure_cause()
            return False, _CAUSES[cause][0], cause
        finally:
            attempt.close()


# ---------------------------------------------------------------------------
# Default environment: thin adapters over the real backend surfaces.
# ---------------------------------------------------------------------------

_PCM_PROGRESS_RE = re.compile(r"voice PCM progress:.*?frames=(\d+).*?peak=(\d+)")


def real_environment(config_root: Optional[Path] = None) -> OnboardingEnvironment:
    """Build the environment that reads the real, existing backend surfaces."""

    def _root() -> Path:
        if config_root is not None:
            return Path(config_root)
        from .. import config as config_module

        return config_module.config_root()

    def probe_device() -> ProbeVerdict:
        from .. import windows_diagnostics

        check = windows_diagnostics.check_raw_input()
        if check.status.value == "pass":
            return ProbeVerdict(True, "", check.detail)
        cause = {
            "no_device": "device_missing",
            "ambiguous": "device_ambiguous",
        }.get(check.result_code, "device_probe_failed")
        return ProbeVerdict(False, cause, check.detail)

    def arm_control_watch() -> Any:
        from .. import key_detection_bridge

        return key_detection_bridge.request_detection(_root())

    def poll_control_watch(token) -> str:
        from .. import key_detection_bridge

        return key_detection_bridge.poll_detection(token) or ""

    def cancel_control_watch(token) -> None:
        from .. import key_detection_bridge

        key_detection_bridge.cancel_detection(token)

    def probe_permissions() -> ProbeVerdict:
        from .. import bridge_runtime_status as runtime

        status = runtime.read_status(_root())
        if status is None:
            return ProbeVerdict(False, "service_not_running", _CAUSES["service_not_running"][0])
        if status.hid_tap_state in {"authorization_cancelled", "authorization_failed"}:
            return ProbeVerdict(
                False, "authorization_incomplete", _CAUSES["authorization_incomplete"][0]
            )
        if not runtime.input_channels_ready(status):
            return ProbeVerdict(
                False, "input_channels_not_ready", _CAUSES["input_channels_not_ready"][0]
            )
        return ProbeVerdict(True, "", "按键接收授权已就绪")

    def probe_cable_ends(name: str, host_api: str) -> ProbeVerdict:
        from .. import audio_output

        if not name:
            return ProbeVerdict(False, "no_output_selected", _CAUSES["no_output_selected"][0])
        try:
            playback = audio_output.enumerate_output_endpoints()
            recording = audio_output.enumerate_input_endpoints()
        except audio_output.AudioOutputUnavailableError as exc:
            return ProbeVerdict(False, "cable_output_missing", str(exc))
        matches = [
            endpoint
            for endpoint in playback
            if endpoint.name == name and (not host_api or endpoint.host_api == host_api)
        ]
        if not matches:
            return ProbeVerdict(
                False, "output_endpoint_missing", _CAUSES["output_endpoint_missing"][0]
            )
        if not any(audio_output.is_cable_input_endpoint(e.name) for e in matches):
            return ProbeVerdict(
                False, "endpoint_not_cable_input", _CAUSES["endpoint_not_cable_input"][0]
            )
        if not any(audio_output.is_cable_output_endpoint(e.name) for e in recording):
            return ProbeVerdict(
                False, "cable_output_missing", _CAUSES["cable_output_missing"][0]
            )
        return ProbeVerdict(True, "", "CABLE Input 与 CABLE Output 两端匹配")

    def probe_route(name: str, host_api: str) -> ProbeVerdict:
        from .. import windows_diagnostics

        check = windows_diagnostics.check_vb_cable_loopback_isolated(name, host_api)
        if check.status.value == "pass":
            return ProbeVerdict(True, "", check.detail)
        return ProbeVerdict(False, "route_probe_failed", check.detail)

    def tool_sessions(provider: str) -> tuple[SessionInfo, ...]:
        from .. import chromecast_host_activity as activity

        if provider == "sogou":
            raw = activity.read_sogou_capture()
        elif provider == "wetype":
            raw = activity.read_wetype_capture()
        elif provider == "chatterfly":
            raw = activity.read_chatterfly_voice_windows()
        else:
            raw = activity.read_doubao_capture()
        sessions = []
        for item in raw:
            pid = getattr(item, "pid", None)
            if pid is None:
                pid = item.identity[2]
            sessions.append(
                SessionInfo(
                    endpoint_id=getattr(item, "endpoint_id", ""),
                    instance_id=getattr(item, "instance_id", ""),
                    pid=int(pid),
                    active=int(getattr(item, "state", 0)) == 1,
                )
            )
        return tuple(sessions)

    def cable_output_endpoint_id() -> str:
        """Best-effort name -> capture-endpoint-id resolution.

        Returns "" when the cable's recording end cannot be resolved to a
        unique endpoint id; the wizard then skips the mic-identity check and
        says so rather than guessing.
        """

        from .. import audio_output
        from ..voice_playback_session_windows import _Session

        try:
            candidates = [
                endpoint.name
                for endpoint in audio_output.enumerate_input_endpoints()
                if audio_output.is_cable_output_endpoint(endpoint.name)
            ]
        except audio_output.AudioOutputUnavailableError:
            return ""
        for candidate in candidates:
            try:
                with _Session(name=candidate) as session:
                    if session.endpoint_id:
                        return session.endpoint_id
            except Exception:  # noqa: BLE001 - resolution is best-effort
                continue
        return ""

    def pcm_watermark() -> int:
        from .. import logging_setup

        try:
            return logging_setup.log_file_path(_root()).stat().st_size
        except OSError:
            return 0

    def pcm_progress(watermark: int) -> tuple[int, int]:
        """Read the counted PCM progress where it is logged.

        ``voice_audio_session`` logs cumulative ``frames`` and ``peak`` per
        voice session; that log line is the cross-process view of the frame
        counter.  "Genuinely non-empty" means frames > 0 and peak > 0.
        """

        from .. import logging_setup

        frames, peak = 0, 0
        try:
            path = logging_setup.log_file_path(_root())
            size = path.stat().st_size
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                if 0 <= watermark <= size:
                    stream.seek(watermark)
                for line in stream:
                    match = _PCM_PROGRESS_RE.search(line)
                    if match:
                        frames = max(frames, int(match.group(1)))
                        peak = max(peak, int(match.group(2)))
        except OSError:
            pass
        return frames, peak

    def observe_field() -> FieldObservation:
        from .. import voice_interaction_diagnostics_windows as focus

        snapshot = focus.capture_focus_snapshot()
        if not snapshot.supported or snapshot.error:
            return FieldObservation("", None, False, False, snapshot)
        field_id = f"{snapshot.foreground_pid}:{snapshot.focus_handle}"
        editable = (
            snapshot.focus_input_status == "native_edit_style"
            and snapshot.focus_read_only is False
        )
        return FieldObservation(
            field_id,
            snapshot.text_length,
            editable,
            snapshot.text_length is not None,
            snapshot,
        )

    def diff_field(before: FieldObservation) -> FieldDiff:
        from .. import voice_interaction_diagnostics_windows as focus

        after = focus.capture_focus_snapshot()
        if before.raw is None:
            return FieldDiff(False, None, "unknown")
        observation = focus.compare_submission(before.raw, after)
        same_field = observation.focus_state == "same"
        return FieldDiff(same_field, observation.text_delta, "unknown")

    def load_settings() -> StagedSettings:
        from .. import config as config_module

        data = config_module.load_config(config_module.config_path(_root()))
        return StagedSettings(
            voice_program=str(data.get("voice_program", "")),
            output_endpoint_name=str(data.get("output_endpoint_name", "")),
            output_endpoint_host_api=str(data.get("output_endpoint_host_api", "")),
        )

    def commit(settings: StagedSettings) -> None:
        from .. import config as config_module

        path = config_module.config_path(_root())
        data = config_module.load_config(path)
        data["voice_program"] = settings.voice_program
        data["output_endpoint_name"] = settings.output_endpoint_name
        data["output_endpoint_host_api"] = settings.output_endpoint_host_api
        config_module.save_config_and_load(path, data)

    def _progress_path() -> Path:
        return _root() / "onboarding-progress.json"

    def load_progress() -> Optional[ProgressState]:
        try:
            payload = json.loads(_progress_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return None
        staged = payload.get("staged") or {}
        if not isinstance(staged, dict):
            return None
        verified = payload.get("verified_ids")
        if not isinstance(verified, list):
            return None
        return ProgressState(
            current_index=int(payload.get("current_index", 0)),
            verified_ids=tuple(str(v) for v in verified if str(v) in STEP_IDS),
            staged=StagedSettings(
                voice_program=str(staged.get("voice_program", "")),
                output_endpoint_name=str(staged.get("output_endpoint_name", "")),
                output_endpoint_host_api=str(staged.get("output_endpoint_host_api", "")),
            ),
        )

    def save_progress(state: ProgressState) -> None:
        payload = {
            "schema": 1,
            "current_index": state.current_index,
            "verified_ids": list(state.verified_ids),
            "staged": {
                "voice_program": state.staged.voice_program,
                "output_endpoint_name": state.staged.output_endpoint_name,
                "output_endpoint_host_api": state.staged.output_endpoint_host_api,
            },
        }
        path = _progress_path()
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)

    return OnboardingEnvironment(
        probe_device=probe_device,
        arm_control_watch=arm_control_watch,
        poll_control_watch=poll_control_watch,
        cancel_control_watch=cancel_control_watch,
        probe_permissions=probe_permissions,
        probe_cable_ends=probe_cable_ends,
        probe_route=probe_route,
        tool_sessions=tool_sessions,
        cable_output_endpoint_id=cable_output_endpoint_id,
        pcm_watermark=pcm_watermark,
        pcm_progress=pcm_progress,
        observe_field=observe_field,
        diff_field=diff_field,
        load_settings=load_settings,
        commit=commit,
        load_progress=load_progress,
        save_progress=save_progress,
        now=time.monotonic,
        sleep=time.sleep,
    )


# ---------------------------------------------------------------------------
# QML-facing view-model: exactly the surface named in the contract doc.
# ---------------------------------------------------------------------------


def _background_runner(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="onboarding-verify", daemon=True).start()


class OnboardingViewModel(QObject):
    """The wizard's QML singleton (doc section 3 ``OnboardingViewModel``).

    Public surface — exactly the contract members: ``steps``, ``currentStep``,
    ``canContinue``, ``next()``, ``back()``, ``repair(stepId)``,
    ``verifyCurrent()``.  The three notify signals are the change-notification
    plumbing required by Qt properties, and the single private signal carries
    worker-thread results back to this object's thread.
    """

    stepsChanged = Signal()
    currentStepChanged = Signal()
    canContinueChanged = Signal()
    _flowUpdate = Signal(object)

    def __init__(
        self,
        environment: Optional[OnboardingEnvironment] = None,
        *,
        runner: Optional[Callable[[Callable[[], None]], None]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._flow = OnboardingFlow(
            environment if environment is not None else real_environment()
        )
        self._runner = runner if runner is not None else _background_runner
        self._busy = False
        self._flowUpdate.connect(self._apply_update)

    # -- properties --------------------------------------------------------

    @Property(list, notify=stepsChanged)
    def steps(self) -> list[StepStatus]:
        return self._flow.snapshot()

    @Property(int, notify=currentStepChanged)
    def currentStep(self) -> int:
        return self._flow.current_index

    @Property(bool, notify=canContinueChanged)
    def canContinue(self) -> bool:
        return self._flow.can_continue()

    # -- slots -------------------------------------------------------------

    @Slot()
    def next(self) -> None:
        self._mutate(self._flow.advance)

    @Slot()
    def back(self) -> None:
        self._mutate(self._flow.back)

    @Slot(str)
    def repair(self, stepId: str) -> None:
        self._mutate(lambda: self._flow.repair(stepId))

    @Slot()
    def verifyCurrent(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._flow.set_progress_sink(lambda note: self._flowUpdate.emit(("progress", note)))
        self._runner(self._run_verification)

    # -- internals ---------------------------------------------------------

    def _run_verification(self) -> None:
        try:
            validation = self._flow.verify()
        finally:
            self._flow.set_progress_sink(None)
        self._flowUpdate.emit(("done", validation))

    def _apply_update(self, payload: object) -> None:
        kind = payload[0] if isinstance(payload, tuple) else "done"
        if kind == "progress":
            # Live status: the flow already wrote the note into the step detail
            # before each long wait; just refresh bindings.
            self.stepsChanged.emit()
            return
        self._busy = False
        self.stepsChanged.emit()
        self.currentStepChanged.emit()
        self.canContinueChanged.emit()

    def _mutate(self, action: Callable[[], None]) -> None:
        action()
        self.stepsChanged.emit()
        self.currentStepChanged.emit()
        self.canContinueChanged.emit()
