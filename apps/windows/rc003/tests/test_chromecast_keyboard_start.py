import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from ovb_rc003 import chromecast_host_activity
from ovb_rc003 import chromecast_voice_host as subject
from ovb_rc003 import chromecast_voice_receiver
from ovb_rc003 import voice_program_manager
from ovb_rc003.chromecast_voice import Recording
from ovb_rc003.voice_playback_session_windows import CaptureSession


def capture(name="current", state=1, pid=20):
    return CaptureSession("capture", name, pid, state)


def doubao_settings():
    return {
        "remote_recording_mode": "toggle",
        "voice_program": {"provider": voice_program_manager.VOICE_PROGRAM_DOUBAO_IME},
        "voice_hotkeys_by_provider": {
            voice_program_manager.VOICE_PROGRAM_DOUBAO_IME: {
                "toggle": "ralt", "toggle_source": "manual",
                "hold": "ralt", "source": "manual",
            }
        },
    }


def make_host():
    services = mock.Mock()
    services.settings.return_value = doubao_settings()
    services.configured_backend.return_value = "doubao_physicalizer"
    services.shortcut.lock = threading.Lock()
    services.shortcut.controller = mock.Mock()
    services.shortcut.controller.on_mic_button_pressed.return_value = "down"
    services.shortcut.controller.on_mic_button_released.return_value = "up"
    services.shortcut.apply.return_value = True
    services.audio.open.return_value = True
    services.logger = mock.Mock()
    return subject.VoiceHost(services)


class KeyboardStartTests(unittest.TestCase):
    """The keyboard hotkey starts Doubao itself, so the attempt must adopt the
    capture instead of re-sending the toggle hotkey (which would switch the
    engine straight back off)."""

    def run_start(self, host, *, keyboard_initiated, active_captures=()):
        with mock.patch.object(subject, "read_doubao_capture",
                               return_value=list(active_captures)), \
             mock.patch.object(subject, "win32_input") as win32_input, \
             mock.patch.object(subject, "CaptureWatch") as watch_type:
            watch_type.return_value.status = "tracking"
            win32_input.can_begin_tracked_hold.return_value = True
            host._start_doubao_handsfree(
                None, keyboard_initiated=keyboard_initiated)
        return watch_type

    def test_keyboard_start_adopts_without_resending_the_hotkey(self):
        host = make_host()
        self.run_start(host, keyboard_initiated=True,
                       active_captures=[capture()])
        self.assertFalse(host.services.shortcut.apply.called)
        self.assertTrue(host.engaged)
        self.assertTrue(host._doubao_handsfree)

    def test_remote_start_still_sends_the_hotkey(self):
        host = make_host()
        self.run_start(host, keyboard_initiated=False)
        self.assertTrue(host.services.shortcut.apply.called)
        self.assertTrue(host.engaged)

    def test_capture_started_elsewhere_is_adopted_not_refused(self):
        # The old behaviour refused the attempt outright, which is exactly what
        # left the remote dead after a keyboard-started dictation.
        host = make_host()
        self.run_start(host, keyboard_initiated=False,
                       active_captures=[capture()])
        self.assertFalse(host.services.shortcut.apply.called)
        self.assertTrue(host.engaged)

    def test_keyboard_start_adopts_the_already_running_capture(self):
        host = make_host()
        watch_type = self.run_start(host, keyboard_initiated=True,
                                    active_captures=[capture()])
        self.assertTrue(watch_type.call_args.kwargs["adopt_existing"])

    def test_keyboard_start_event_requests_a_begin(self):
        host = make_host()
        host.client = mock.Mock()
        host._keyboard_start()
        host.client.voice_host.assert_called_once_with(0, "begin")
        self.assertTrue(host._consume_keyboard_initiated())

    def test_keyboard_start_ignored_while_an_attempt_runs(self):
        host = make_host()
        host.client = mock.Mock()
        host.state = "recording"
        host._keyboard_start()
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())

    def test_keyboard_start_ignored_right_after_our_own_hotkey_send(self):
        # Our synthesized hotkey can look like a hardware edge once an earlier
        # hook cleared its marker; it must never open an attempt.
        host = make_host()
        host.client = mock.Mock()
        now = time.monotonic()
        host._last_shortcut_send_at = now
        host._keyboard_start(now + 0.01)
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())


class QueuedKeyboardStartTests(unittest.TestCase):
    """Windows delivers every physical press to Doubao, so a press that no
    attempt can serve right now must queue one pending start instead of being
    dropped: during "stopping" the previous dictation is over and during
    "starting" the press retries one whose attempt has not confirmed.  The
    pending start fires when the host is idle again (failed starts included);
    an attempt that recovers and records serves the press instead."""

    def start_attempt(self, host, state, *, closed=False):
        host.attempt = 7
        host.closed = closed
        host.state = state

    def idle(self, host):
        host.closed = True     # cleanup finished, as _stop_host reports
        host._handle({"event": "state", "attempt": 7, "data": "idle"})

    def starting_host(self):
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "starting")
        host.provider = voice_program_manager.VOICE_PROGRAM_DOUBAO_IME
        host.engaged = True
        host.capture_watch = mock.Mock(status="waiting", identity=None, baseline=None)
        host.capture_watch.poll.return_value = False
        host._fail_voice = mock.Mock()
        host._stop_host = mock.Mock()
        return host

    def test_press_during_stopping_begins_once_the_host_is_idle(self):
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "stopping")
        host._keyboard_start()
        self.assertTrue(host._pending_keyboard_start_at)
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())
        self.idle(host)
        self.assertEqual(host.state, "idle")
        host.client.voice_host.assert_called_once_with(7, "begin")
        self.assertTrue(host._consume_keyboard_initiated())

    def test_press_during_recording_queues_nothing(self):
        # The key toggles Doubao off and the capture watch closes the attempt,
        # so no start may be queued for it.
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "recording")
        host._keyboard_start()
        self.assertFalse(host._pending_keyboard_start_at)
        self.idle(host)
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())

    def test_two_presses_during_stopping_queue_a_single_begin(self):
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "stopping")
        host._keyboard_start()
        host._keyboard_start()
        self.idle(host)
        host.client.voice_host.assert_called_once_with(7, "begin")

    def test_press_during_starting_fires_after_the_attempt_fails(self):
        # The stuck attempt has not confirmed; the retry press must still get
        # an attempt for the dictation Doubao began when Windows delivered it.
        host = self.starting_host()
        host._keyboard_start()
        self.assertTrue(host._pending_keyboard_start_at)
        self.assertFalse(host.client.voice_host.called)
        host.start_at = time.monotonic() - 2.5
        host._poll_host()
        host._fail_voice.assert_called_once_with(
            "Doubao microphone startup was not confirmed")
        host.state = "stopping"    # _stop_host winds the failed attempt down
        self.idle(host)
        host.client.voice_host.assert_called_once_with(7, "begin")
        self.assertTrue(host._consume_keyboard_initiated())

    def test_recording_serves_the_queued_press_without_a_later_begin(self):
        # A retry press during "starting" is served by the attempt that adopts
        # Doubao's capture; once it records the queue entry is done and must
        # not reopen a phantom attempt after the recording ends.
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "starting")
        host._keyboard_start()
        self.assertTrue(host._pending_keyboard_start_at)
        host.confirmed = True
        host._handle({"event": "state", "attempt": 7, "data": "recording"})
        self.assertEqual(host.state, "recording")
        self.assertFalse(host._pending_keyboard_start_at)
        self.idle(host)
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())

    def test_queued_press_dropped_if_the_host_is_busy_again_at_fire_time(self):
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "stopping")
        host._keyboard_start()
        host.state = "recording"    # a new attempt claimed the host meanwhile
        host._fire_pending_keyboard_start()
        self.assertFalse(host.client.voice_host.called)
        host.state = "idle"
        host._fire_pending_keyboard_start()   # a dropped press never fires late
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())

    def test_own_hotkey_echo_is_never_queued(self):
        # The 0.5s guard runs before any queueing: our own synthesized hotkey
        # must not arm a pending start either.
        host = make_host()
        host.client = mock.Mock()
        self.start_attempt(host, "stopping")
        now = time.monotonic()
        host._last_shortcut_send_at = now
        host._keyboard_start(now + 0.01)
        self.assertFalse(host._pending_keyboard_start_at)
        self.idle(host)
        self.assertFalse(host.client.voice_host.called)
        self.assertFalse(host._consume_keyboard_initiated())

    def test_startup_confirm_deadline_is_two_seconds(self):
        # A stuck "starting" attempt used to freeze both entry points for the
        # whole nine-second ready window.
        host = self.starting_host()
        host.start_at = time.monotonic() - 1.0
        host._poll_host()
        self.assertFalse(host._fail_voice.called)
        host.start_at = time.monotonic() - 2.5
        host._poll_host()
        host._fail_voice.assert_called_once_with(
            "Doubao microphone startup was not confirmed")


class HostStartGateTests(unittest.TestCase):
    def test_begin_host_start_opens_an_attempt_without_a_device_stream(self):
        gate = Recording("toggle", 120)
        effects = gate.begin_host_start(1)
        self.assertEqual(gate.state, "starting")
        self.assertEqual([effect.kind for effect in effects],
                         ["host_start", "state"])
        # Host confirmation is what asks the remote for its stream.
        opened = [effect for effect in gate.host_result(1, True, 1.1)
                  if effect.kind == "device"]
        self.assertEqual([bytes(effect.value) for effect in opened], [b"\x0c\x00"])

    def test_begin_host_start_ignored_while_a_stream_is_open(self):
        gate = Recording("toggle", 120)
        gate.begin_host_start(1)
        self.assertEqual(gate.begin_host_start(2), [])
        self.assertEqual(gate.attempt, 1)


class AdoptExistingCaptureTests(unittest.TestCase):
    def watch(self, readings, adopt_existing=True):
        reader = mock.Mock(side_effect=readings)
        watch = chromecast_host_activity.CaptureWatch(
            reader, adopt_existing=adopt_existing)
        watch.begin()
        return watch

    def test_already_running_capture_binds_on_the_first_poll(self):
        # The physical hotkey reaches Doubao before the attempt does, so the
        # dictation is normally already capturing here. Making it wait for a
        # fallback window cost the user a full second of dead air before the
        # microphone opened - it must bind on the first poll.
        old = capture("old")
        watch = self.watch([(old,), (old,)])
        self.assertFalse(watch.poll(1))
        self.assertEqual(watch.identity, old.identity)
        self.assertEqual(watch.status, "tracking")

    def test_dying_leftover_is_replaced_by_the_fresh_capture(self):
        # A session left over from the previous attempt is visible but already
        # dying. The attempt must follow the user's real dictation instead of
        # ending together with the leftover.
        old, new = capture("old"), capture("new")
        watch = self.watch([(old,), (old,), (new,), (new,)])
        self.assertFalse(watch.poll(1))
        self.assertEqual(watch.identity, old.identity)
        self.assertFalse(watch.poll(1.25))          # leftover gone, fresh here
        self.assertEqual(watch.identity, new.identity)
        self.assertEqual(watch.status, "tracking")
        self.assertFalse(watch.poll(1.5))
        self.assertEqual(watch.status, "tracking")

    def test_dying_leftover_without_a_fresh_capture_ends_normally(self):
        # ...but a leftover that dies with nothing behind it still ends the
        # attempt, through the ordinary grace.
        old = capture("old")
        watch = self.watch([(old,), (old,), (), ()])
        self.assertFalse(watch.poll(1))
        self.assertEqual(watch.identity, old.identity)
        self.assertFalse(watch.poll(1.25))
        self.assertEqual(watch.status, "ending")
        self.assertTrue(watch.poll(2.1))            # past END_GRACE_SECONDS
        self.assertEqual(watch.status, "ended")

    def test_no_rebind_once_the_grace_is_over(self):
        # A capture the user stopped and restarted is a NEW dictation: after
        # the swap window the attempt ends instead of silently following it.
        old, new = capture("old"), capture("new")
        watch = self.watch([(old,), (old,), (), (new,)])
        self.assertFalse(watch.poll(1))
        self.assertEqual(watch.identity, old.identity)
        self.assertFalse(watch.poll(2.0))            # beyond REBIND_GRACE
        self.assertEqual(watch.status, "ending")
        self.assertFalse(watch.poll(2.5))
        self.assertEqual(watch.identity, old.identity)
        self.assertEqual(watch.status, "ending")

    def test_end_detection_is_unchanged_once_bound(self):
        # The grace still applies and an unknown reading never means ended.
        old = capture("old")
        watch = self.watch([(old,), (old,), (old,), (), OSError("query failed"),
                            (old,), (), ()])
        self.assertFalse(watch.poll(1))
        self.assertFalse(watch.poll(1.3))
        self.assertFalse(watch.poll(2))              # gone, inside the grace
        self.assertEqual(watch.status, "ending")
        self.assertFalse(watch.poll(2.25))           # unknown never ends it
        self.assertEqual(watch.status, "unknown")
        self.assertFalse(watch.poll(2.5))            # reappeared
        self.assertEqual(watch.status, "tracking")
        self.assertFalse(watch.poll(3))
        self.assertEqual(watch.status, "ending")
        self.assertTrue(watch.poll(3.9))
        self.assertEqual(watch.status, "ended")

    def test_baseline_still_hides_preexisting_captures(self):
        # Without adoption a pre-existing capture stays excluded forever.
        watch = chromecast_host_activity.CaptureWatch(lambda: [capture()])
        watch.begin()
        self.assertFalse(watch.poll(1))
        self.assertIsNone(watch.identity)
        self.assertFalse(watch.poll(5))
        self.assertIsNone(watch.identity)
        self.assertEqual(watch.status, "waiting")


class KeyboardToMicrophoneChainTests(unittest.TestCase):
    """The whole keyboard path, minus the keystroke itself.

    Keyboard hotkey -> host -> pipe -> receiver gate -> MIC_OPEN. The remote
    button reaches the same ``_start_host``, so this is the shared spine both
    entry points rely on.
    """

    def receiver(self, gate):
        effects = []
        receiver = SimpleNamespace(available=True, detect_only=False,
                                   gate=gate, effects=effects.extend)
        return receiver, effects

    def test_begin_command_opens_the_attempt_on_the_receiver(self):
        from ovb_rc003 import chromecast_voice_receiver
        gate = Recording("toggle", 120)
        receiver, effects = self.receiver(gate)
        chromecast_voice_receiver.VoiceReceiver.host(
            receiver, {"attempt": 0, "result": "begin"})
        self.assertEqual(gate.state, "starting")
        self.assertEqual([effect.kind for effect in effects],
                         ["host_start", "state"])

    def test_keyboard_chain_ends_at_the_remote_microphone_open(self):
        host = make_host()
        gate = Recording("toggle", 120)
        host.client = mock.Mock()
        host.client.voice_host.side_effect = (
            lambda attempt, result: chromecast_voice_receiver.VoiceReceiver.host(
                SimpleNamespace(available=True, detect_only=False, gate=gate,
                                effects=lambda effects: None),
                {"attempt": attempt, "result": result}))

        host._keyboard_start()
        self.assertEqual(gate.state, "starting")

        # Host confirmation, exactly as the remote's button press gets it, is
        # what asks the device for its microphone stream.
        opened = [effect for effect in gate.host_result(1, True, time.monotonic() + 1)
                  if effect.kind == "device"]
        self.assertEqual([bytes(effect.value) for effect in opened],
                         [b"\x0c\x00"])

    def test_remote_press_while_keyboard_recording_stops_the_attempt(self):
        # Second press in toggle mode ends it - whichever side pressed.
        gate = Recording("toggle", 120)
        gate.begin_host_start(1)
        opened = [effect for effect in gate.host_result(1, True, 1.1)
                  if effect.kind == "device"]
        self.assertTrue(gate.command_submitted(opened[0]))
        gate.control(bytes((4, 0, 2, 0)), 1.2)   # software stream confirmed
        self.assertEqual(gate.state, "recording")
        effects = gate.control(bytes((4, 3, 2, 1)), 2)  # remote's own press
        self.assertEqual([effect.kind for effect in effects],
                         ["host_stop", "state", "device"])


if __name__ == "__main__":
    unittest.main()
