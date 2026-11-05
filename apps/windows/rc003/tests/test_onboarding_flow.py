"""First-run acceptance wizard (slice C) tests.

Drives ``OnboardingViewModel`` end-to-end with a fully scripted observation
environment and a fake clock — no Qt event loop, no Windows hardware, no real
backend.  The acceptance criteria under test:

* an unverified step blocks ``next()``;
* a failing step exposes exactly one repair action naming its cause;
* staged settings are not committed before the final gate;
* a stale or hand-entered result does not satisfy the final gate.

Plus the wizard's contract surface (UI-REDESIGN.md section 3) and the QML
contract for the owned ``Onboarding*.qml`` files.
"""

import inspect
import unittest
from pathlib import Path

from ovb_rc003.presentation import onboarding
from ovb_rc003.presentation.onboarding import (
    FieldDiff,
    FieldObservation,
    OnboardingEnvironment,
    OnboardingFlow,
    OnboardingViewModel,
    ProbeVerdict,
    SessionInfo,
    StagedSettings,
    STEP_IDS,
)

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "ovb_rc003" / "qml"

ACTIVE_SESSION = SessionInfo("cable-endpoint", "instance-1", 4242, True)
CABLE_ENDPOINT_ID = "cable-endpoint"

QUIET_FIELD = FieldDiff(True, 0, "unknown")
GROWN_FIELD = FieldDiff(True, 8, "unknown")


class Scripted:
    """One value per call; once exhausted, the last value keeps repeating."""

    def __init__(self, *values, fallback=None):
        self.values = list(values)
        self.fallback = fallback
        self.last = None

    def take(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last if self.last is not None else self.fallback


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += float(seconds)


class FakeEnvironment:
    """Scriptable stand-in for every observation the wizard makes."""

    def __init__(self):
        self.clock = FakeClock()
        self.device = ProbeVerdict(True, "", "按键设备已找到")
        self.permissions = ProbeVerdict(True, "", "按键接收授权已就绪")
        self.cable = ProbeVerdict(True, "", "两端匹配")
        self.route = ProbeVerdict(True, "", "通道正常")
        self.settings = StagedSettings("doubao_ime", "CABLE Input", "Windows WASAPI")
        self.cable_id = CABLE_ENDPOINT_ID
        self.buttons = Scripted(fallback="")
        self.sessions = Scripted(fallback=())
        self.pcm = Scripted(fallback=(0, 0))
        self.field_observations = Scripted(
            FieldObservation("field-1", 10, True, True),
            fallback=FieldObservation("field-1", 10, True, True),
        )
        self.diffs = Scripted(fallback=QUIET_FIELD)
        self.commits = []
        self.saves = []
        self.progress_store = None
        self.cancelled = []
        self.armed = 0

    def _arm(self):
        self.armed += 1
        return f"watch-{self.armed}"

    def commit(self, settings):
        self.commits.append(settings)

    def _save_progress(self, state):
        self.saves.append(state)
        self.progress_store = state

    def build(self):
        return OnboardingEnvironment(
            probe_device=lambda: self.device,
            arm_control_watch=self._arm,
            poll_control_watch=lambda _token: self.buttons.take() or "",
            cancel_control_watch=lambda token: self.cancelled.append(token),
            probe_permissions=lambda: self.permissions,
            probe_cable_ends=lambda _name, _api: self.cable,
            probe_route=lambda _name, _api: self.route,
            tool_sessions=lambda _provider: self.sessions.take() or (),
            cable_output_endpoint_id=lambda: self.cable_id,
            pcm_watermark=lambda: 0,
            pcm_progress=lambda _watermark: self.pcm.take() or (0, 0),
            observe_field=lambda: self.field_observations.take(),
            diff_field=lambda _before: self.diffs.take(),
            load_settings=lambda: self.settings,
            commit=lambda settings: self.commit(settings),
            load_progress=lambda: self.progress_store,
            save_progress=self._save_progress,
            now=self.clock.now,
            sleep=self.clock.sleep,
        )


def inline_runner(work):
    work()


def make_vm(fake):
    return OnboardingViewModel(fake.build(), runner=inline_runner)


def steps_by_id(vm):
    return {step.id: step for step in vm.steps}


def walk_steps_1_to_4(fake, vm):
    """Verify the first four steps successfully (real chain, scripted facts)."""

    fake.buttons = Scripted("side")
    vm.verifyCurrent()  # 1. connect_device: device present + button event
    vm.next()
    vm.verifyCurrent()  # 2. system_permissions
    vm.next()
    vm.verifyCurrent()  # 3. audio_route
    vm.next()
    fake.sessions = Scripted((ACTIVE_SESSION,), fallback=(ACTIVE_SESSION,))
    vm.verifyCurrent()  # 4. voice_tool: tool holds an active capture session
    vm.next()
    if vm.currentStep != 4:
        raise AssertionError("walk did not reach the dictation step")


def good_dictation_timeline(fake):
    """control -> fresh session -> non-empty audio -> end -> text growth."""

    fake.buttons = Scripted("mic", fallback="")
    fake.sessions = Scripted(
        (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
    )
    fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
    fake.diffs = Scripted(QUIET_FIELD, QUIET_FIELD, QUIET_FIELD, GROWN_FIELD,
                          fallback=GROWN_FIELD)


class UnverifiedStepBlocksNextTests(unittest.TestCase):
    def test_unverified_step_blocks_next(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)

        self.assertFalse(vm.canContinue)
        vm.next()
        self.assertEqual(vm.currentStep, 0)

        fake.buttons = Scripted("side")
        vm.verifyCurrent()
        self.assertTrue(vm.canContinue)
        vm.next()
        self.assertEqual(vm.currentStep, 1)

        self.assertFalse(vm.canContinue)
        vm.next()
        self.assertEqual(vm.currentStep, 1)

    def test_back_preserves_completed_verifications(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)
        vm.back()
        self.assertEqual(vm.currentStep, 3)
        self.assertTrue(vm.canContinue)  # step 4 stays verified
        self.assertEqual(steps_by_id(vm)["connect_device"].state, "done")


class FailingStepRepairActionTests(unittest.TestCase):
    def test_failing_step_exposes_exactly_one_repair_action_naming_cause(self):
        fake = FakeEnvironment()
        fake.device = ProbeVerdict(False, "device_missing", "未找到遥控器按键设备")
        vm = make_vm(fake)

        vm.verifyCurrent()

        failed = [step for step in vm.steps if step.state == "failed"]
        self.assertEqual(len(failed), 1)
        step = failed[0]
        self.assertEqual(step.id, "connect_device")
        self.assertNotEqual(step.fixLabel, "")
        # Exactly one repair action overall, and it names its cause.
        self.assertIn("未找到遥控器按键设备", step.fixLabel)
        repair_actions = [s for s in vm.steps if s.fixLabel != ""]
        self.assertEqual(len(repair_actions), 1)
        self.assertFalse(vm.canContinue)

        vm.repair(step.id)
        self.assertEqual(vm.currentStep, 0)
        self.assertEqual(steps_by_id(vm)["connect_device"].state, "current")

    def test_button_evidence_required_for_sending_events(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        fake.buttons = Scripted(fallback="")  # device present, no events ever
        vm.verifyCurrent()
        step = steps_by_id(vm)["connect_device"]
        self.assertEqual(step.state, "failed")
        self.assertIn("未收到遥控器按键事件", step.fixLabel)

    def test_missing_field_fails_with_matching_repair(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)
        fake.field_observations = Scripted(
            FieldObservation("field-1", None, False, True),
            fallback=FieldObservation("field-1", None, False, True),
        )
        vm.verifyCurrent()
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("未找到可观察的系统文本输入框", step.fixLabel)


class StagedSettingsCommitTests(unittest.TestCase):
    def test_staged_settings_not_committed_before_final_gate(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)
        self.assertEqual(fake.commits, [])  # steps 1-4 stage, never commit

        # Final gate fails -> still no commit.
        fake.buttons = Scripted(fallback="")
        fake.sessions = Scripted(fallback=())
        fake.diffs = Scripted(fallback=QUIET_FIELD)
        vm.verifyCurrent()
        self.assertEqual(fake.commits, [])

        # Final gate passes -> exactly one atomic commit of the staged values.
        good_dictation_timeline(fake)
        vm.verifyCurrent()
        self.assertEqual(len(fake.commits), 1)
        self.assertEqual(
            fake.commits[0],
            StagedSettings("doubao_ime", "CABLE Input", "Windows WASAPI"),
        )
        self.assertEqual(vm.steps[-1].state, "done")

    def test_failed_commit_is_repairable_and_not_counted(self):
        fake = FakeEnvironment()

        def failing_commit(_settings):
            raise OSError("disk full")

        fake.commit = failing_commit
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)
        good_dictation_timeline(fake)
        vm.verifyCurrent()
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("设置未能写入", step.fixLabel)


class DictationGateDiscriminationTests(unittest.TestCase):
    def _ready_for_dictation(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)
        return fake, vm

    def test_full_chain_passes_the_gate(self):
        fake, vm = self._ready_for_dictation()
        good_dictation_timeline(fake)
        vm.verifyCurrent()
        self.assertTrue(vm.canContinue)
        self.assertEqual(steps_by_id(vm)["dictation_check"].state, "done")

    def test_stale_result_does_not_satisfy_final_gate(self):
        # Text from an earlier attempt is already in the field before this
        # attempt (the baseline excludes it) and no fresh chain is ever
        # observed: the gate must fail rather than accept the visible text.
        fake, vm = self._ready_for_dictation()
        fake.field_observations = Scripted(
            FieldObservation("field-1", 57, True, True),
            fallback=FieldObservation("field-1", 57, True, True),
        )
        fake.diffs = Scripted(fallback=QUIET_FIELD)
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted(fallback=())  # no fresh session ever
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        self.assertEqual(steps_by_id(vm)["dictation_check"].state, "current")
        affected = steps_by_id(vm)["voice_tool"]
        self.assertEqual(affected.state, "failed")
        self.assertIn("新的采集会话", affected.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_stale_session_active_before_attempt_never_counts(self):
        # A capture session that was already running before the attempt is
        # stale: no fresh start is ever seen, so its text (which does arrive)
        # can never satisfy this attempt.
        fake, vm = self._ready_for_dictation()
        fake.buttons = Scripted("mic", fallback="")
        stale = SessionInfo("cable-endpoint", "instance-old", 4242, True)
        fake.sessions = Scripted((stale,), fallback=(stale,))
        fake.diffs = Scripted(GROWN_FIELD, fallback=GROWN_FIELD)
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("残留的文字", step.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_late_result_does_not_satisfy_final_gate(self):
        # The chain runs, but text only appears after the settle window:
        # a late result is rejected.
        fake, vm = self._ready_for_dictation()
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted((), (ACTIVE_SESSION,), (), fallback=())
        fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
        # Ticks run at a 0.5s cadence; the session ends on tick 2 (t=0.5s),
        # the settle window closes at t=12.5s and the attempt expires at
        # t=16.5s.  First growth at t=14s is past the settle window.
        diffs = [QUIET_FIELD] * 28 + [GROWN_FIELD]
        fake.diffs = Scripted(*diffs, fallback=GROWN_FIELD)
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("超过时限才到达", step.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_hand_entered_result_does_not_satisfy_final_gate(self):
        # Full genuine chain, but the text growth is attributed to keyboard
        # input at the insertion point: hand-entered text must not pass.
        fake, vm = self._ready_for_dictation()
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted(
            (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
        )
        fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
        fake.diffs = Scripted(
            QUIET_FIELD, QUIET_FIELD, QUIET_FIELD,
            FieldDiff(True, 8, "keyboard"),
            fallback=FieldDiff(True, 8, "keyboard"),
        )
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("手工输入", step.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_text_growth_before_session_end_is_rejected(self):
        # Typing (or a stale result landing early) before the observed session
        # ended cannot be tool output and must not pass.
        fake, vm = self._ready_for_dictation()
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted(
            (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
        )
        fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
        fake.diffs = Scripted(QUIET_FIELD, GROWN_FIELD, fallback=GROWN_FIELD)
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("手工输入", step.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_output_shown_elsewhere_does_not_pass(self):
        # The target field is bound at attempt start; growth observed on a
        # different field/focus ("shown elsewhere") never counts.
        fake, vm = self._ready_for_dictation()
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted(
            (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
        )
        fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
        fake.diffs = Scripted(
            FieldDiff(False, None, "unknown"), fallback=FieldDiff(False, None, "unknown")
        )
        vm.verifyCurrent()
        self.assertFalse(vm.canContinue)
        step = steps_by_id(vm)["dictation_check"]
        self.assertEqual(step.state, "failed")
        self.assertIn("光标离开了测试输入框", step.fixLabel)
        self.assertEqual(fake.commits, [])

    def test_every_chain_condition_is_required(self):
        never_ends = Scripted(
            (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), fallback=(ACTIVE_SESSION,)
        )
        cases = {
            # The text growth is credited as output in these cases, so only
            # the one dropped condition can fail each run.
            "no_control": dict(buttons=Scripted(fallback="")),
            "no_fresh_session": dict(
                sessions=Scripted(fallback=()), diffs=Scripted(fallback=QUIET_FIELD)
            ),
            "audio_empty": dict(pcm=Scripted((0, 0), fallback=(0, 0))),
            "session_not_ended": dict(
                sessions=never_ends, diffs=Scripted(fallback=QUIET_FIELD)
            ),
        }
        for expected_cause, overrides in cases.items():
            with self.subTest(cause=expected_cause):
                fake, vm = self._ready_for_dictation()
                fake.buttons = Scripted("mic", fallback="")
                fake.sessions = Scripted(
                    (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
                )
                fake.pcm = Scripted((120, 3000), fallback=(120, 3000))
                fake.diffs = Scripted(
                    QUIET_FIELD, QUIET_FIELD, QUIET_FIELD, GROWN_FIELD,
                    fallback=GROWN_FIELD,
                )
                for name, script in overrides.items():
                    setattr(fake, name, script)
                vm.verifyCurrent()
                self.assertFalse(vm.canContinue)
                repair_actions = [s for s in vm.steps if s.fixLabel != ""]
                self.assertEqual(len(repair_actions), 1, expected_cause)
                self.assertIn(
                    onboarding._CAUSES[expected_cause][0],
                    repair_actions[0].fixLabel,
                )
                self.assertEqual(fake.commits, [])


class RepairNavigationTests(unittest.TestCase):
    def test_repair_returns_to_nearest_affected_step(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        walk_steps_1_to_4(fake, vm)

        # The gate fails because audio never arrived: the nearest affected
        # step is the audio route, not the dictation check itself.
        fake.buttons = Scripted("mic", fallback="")
        fake.sessions = Scripted(
            (), (), (ACTIVE_SESSION,), (ACTIVE_SESSION,), (), fallback=()
        )
        fake.pcm = Scripted((0, 0), fallback=(0, 0))
        fake.diffs = Scripted(
            QUIET_FIELD, QUIET_FIELD, QUIET_FIELD, GROWN_FIELD,
            fallback=GROWN_FIELD,
        )
        vm.verifyCurrent()

        affected = steps_by_id(vm)["audio_route"]
        self.assertEqual(affected.state, "failed")
        self.assertIn("未收到非空音频", affected.fixLabel)
        self.assertEqual(steps_by_id(vm)["dictation_check"].state, "current")

        vm.repair("audio_route")
        self.assertEqual(vm.currentStep, 2)
        by_id = steps_by_id(vm)
        self.assertEqual(by_id["connect_device"].state, "done")
        self.assertEqual(by_id["system_permissions"].state, "done")
        self.assertEqual(by_id["audio_route"].state, "current")
        self.assertEqual(by_id["voice_tool"].state, "todo")
        self.assertEqual(by_id["dictation_check"].state, "todo")
        self.assertFalse(vm.canContinue)


class RecoveryTests(unittest.TestCase):
    def test_closing_and_reopening_resumes_at_first_unverified_step(self):
        fake = FakeEnvironment()
        vm = make_vm(fake)
        fake.buttons = Scripted("side")
        vm.verifyCurrent()
        vm.next()
        self.assertEqual(vm.currentStep, 1)

        # Reopen: a fresh view-model over the same machine state.
        reopened = make_vm(fake)
        self.assertEqual(reopened.currentStep, 1)
        self.assertEqual(steps_by_id(reopened)["connect_device"].state, "done")
        self.assertFalse(reopened.canContinue)


class ContractSurfaceTests(unittest.TestCase):
    def test_viewmodel_surface_matches_contract(self):
        declared = {
            name
            for name in vars(OnboardingViewModel)
            if not name.startswith("_")
        }
        contract_members = {
            "steps",
            "currentStep",
            "canContinue",
            "next",
            "back",
            "repair",
            "verifyCurrent",
        }
        notify_signals = {
            "stepsChanged",
            "currentStepChanged",
            "canContinueChanged",
        }
        self.assertTrue(contract_members <= declared)
        self.assertEqual(
            declared - notify_signals - {"staticMetaObject"}, contract_members
        )
        self.assertIn("_flowUpdate", vars(OnboardingViewModel))
        self.assertEqual(
            list(inspect.signature(OnboardingViewModel.repair).parameters)[1],
            "stepId",
        )

    def test_qml_files_respect_presentation_contract(self):
        qml_files = sorted(QML_DIR.glob("Onboarding*.qml"))
        self.assertTrue(qml_files)
        banned = (
            "OvbRc003Settings",
            "ActionKind",
            "doubao_ime",
            "voice_hotkeys_by_provider",
            "wetype_hotkey",
            "state == 1",
        )
        for path in qml_files:
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith("import "):
                    continue
                target = stripped[len("import "):].split(" ")[0]
                allowed = target == "OvbRc003Presentation" or target.startswith("Qt")
                self.assertTrue(
                    allowed, f"{path.name}: unexpected import {target!r}"
                )
            for word in banned:
                self.assertNotIn(word, text, f"{path.name}: backend word {word!r}")


class FlowLevelTests(unittest.TestCase):
    """The same flow core without the QObject wrapper."""

    def test_verify_returns_validation_for_current_step(self):
        fake = FakeEnvironment()
        fake.device = ProbeVerdict(False, "device_missing", "未找到遥控器按键设备")
        flow = OnboardingFlow(fake.build())
        validation = flow.verify()
        self.assertEqual(validation.field, "connect_device")
        self.assertFalse(validation.ok)
        self.assertIn("未找到遥控器按键设备", validation.message)

    def test_no_skip_path_is_enforced(self):
        fake = FakeEnvironment()
        flow = OnboardingFlow(fake.build())
        # Without verification the flow never advances: there is no skip.
        flow.advance()
        self.assertEqual(flow.current_index, 0)
        self.assertEqual([s.id for s in flow.snapshot()], list(STEP_IDS))


if __name__ == "__main__":
    unittest.main()
