"""Seeded chaos driver for the Chromecast voice state machine.

Random interleavings of keyboard Right-Alt presses, remote button frames,
host replies, capture-watch readings and irregular ``tick()`` calls hammer the
real ``Recording`` gate and the real ``VoiceHost`` wired through the real
``VoiceReceiver`` and ``Channel`` boundary.  Only external I/O is faked (device
writes, capture-session readings, shortcut delivery, the Doubao RPC) exactly
like ``tests/test_chromecast_hold_handoff.py`` does.

Invariants asserted after every step and at the end of every seed:

1. once input stops the gate returns to ``idle`` - it is never left permanently
   in ``starting``/``stopping``/``blocked``;
2. ``begin_host_start`` succeeds whenever the gate is genuinely idle;
3. ``VoiceHost.state`` and the gate state never diverge permanently;
4. no attempt is left engaged/live after its capture ended;
5. the ATVV stream is closed (``stream is None``) whenever the gate is ``idle``;
6. no exception escapes any handler.

Everything is deterministic per seed.  A failure prints the seed and the exact
operation sequence up to the violation.  The default run is small enough for
the normal suite; ``VOICE_CHAOS_LONG=1`` runs seeds 1..200 with ~320
operations each.  ``VOICE_CHAOS_SEEDS`` (comma list) and ``VOICE_CHAOS_OPS``
override both.
"""

import asyncio
import copy
import heapq
import os
import random
import traceback
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock

from ovb_rc003 import chromecast_doubao_handsfree as handsfree
from ovb_rc003 import chromecast_voice_host as host_module
from ovb_rc003.chromecast_channel import Channel, SessionIdentity
from ovb_rc003.chromecast_voice import LIMITS, Recording
from ovb_rc003.chromecast_voice_receiver import VoiceReceiver
from tests.test_chromecast_host_activity import session
import tests.test_chromecast_voice as voice_tests

SOFTWARE = bytes((4, 0, 2, 0))
RELEASE = bytes((0, 2))
STOP = bytes((0, 0))
MIC_BUTTON = bytes((8,))
OPEN_FAILED = bytes((0x0c, 0))

_LONG = os.environ.get("VOICE_CHAOS_LONG", "") == "1"
_SEEDS = tuple(
    int(seed) for seed in os.environ.get("VOICE_CHAOS_SEEDS", "").replace(";", ",").split(",")
    if seed.strip())
SEEDS = _SEEDS or tuple(range(1, (200 if _LONG else 12) + 1))
OPS = int(os.environ.get("VOICE_CHAOS_OPS", 320 if _LONG else 150))

PROVIDER_COMBOS = (("wetype", "hold"), ("doubao_ime", "hold"), ("doubao_ime", "toggle"))

GARBAGE_FRAMES = (b"\xff", b"\x04\x09", b"\x00", bytes((0, 2, 2)), b"\x0a\x00", b"\x08\x00")


class ChaosWorld:
    """One seeded run: real gate + real host + real receiver, faked I/O only."""

    def __init__(self, seed, ops):
        self.seed, self.ops = seed, ops
        self.rng = random.Random(seed)
        self.now = 1.0
        self.op_log = []
        self.violations = []  # (key, invariant, message, step)
        self._due = []  # (when, seq, kind, payload) world reactions
        self._seq = 0
        self._stream_ids = []
        self.replies = deque()
        self.sent = deque(maxlen=4096)
        self.open_plan = None
        self.open_failure_sent = False
        self._stack = []
        self.fixture = None
        self._setup()

    # ------------------------------------------------------------- fixture
    def _patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self._stack.append(patcher)
        return patcher.start()

    def _patch_object(self, target, attribute, **kwargs):
        patcher = mock.patch.object(target, attribute, **kwargs)
        self._stack.append(patcher)
        return patcher.start()

    def _setup(self):
        rng = self.rng
        self.provider, self.mode = rng.choice(PROVIDER_COMBOS)
        self.limit = rng.choice(LIMITS)
        self.fixture = fixture = voice_tests.HostTests()
        fixture.setUp()
        self.owner = fixture.owner
        self.host = fixture.host
        if self.provider == "wetype":
            self.owner._config = {
                "gain_db": 0, "voice_program": {"provider": "wetype"},
                "remote_recording_mode": self.mode,
                "remote_recording_limit_seconds": self.limit,
                "voice_hotkeys_by_provider": {"wetype": {
                    "hold": "lctrl+lwin", "source": "manual",
                    "toggle": "lshift+f9", "toggle_source": "manual"}}}
            self.owner._voice_shortcut.hotkey = SimpleNamespace(modifiers=("lctrl",), key="lwin")
            self.owner._configured_voice_hotkey_backend.return_value = "wetype_hotkey"
        else:
            self.owner._config = {
                "gain_db": 0, "voice_program": {"provider": "doubao_ime"},
                "remote_recording_mode": self.mode,
                "remote_recording_limit_seconds": self.limit,
                "voice_hotkeys_by_provider": {"doubao_ime": {
                    "hold": "ralt+space", "source": "auto",
                    "toggle": "lshift+f9", "toggle_source": "auto"}}}
            self.owner._voice_shortcut.hotkey = SimpleNamespace(modifiers=("ralt",), key="space")
            self.owner._configured_voice_hotkey_backend.return_value = "doubao_hotkey"
        self.owner._ensure_voice_key_physicalizer_for_hotkey.return_value = True
        self.owner._voice_shortcut.doubao_physicalizer.generation = 7
        self.owner._voice_shortcut.doubao_physicalizer.is_active_generation.return_value = True

        # External I/O boundaries: transiently flaky, never permanently dead.
        def open_output():
            if self.rng.random() < 0.08:
                return False
            writer = mock.Mock()
            writer.submit.return_value = True
            self.owner._voice_audio.writer = writer
            self.owner._voice_audio.sink = mock.Mock()
            self.owner._voice_shortcut.runtime_mic_confirmed = None
            return True

        def flush(_reason):
            roll = self.rng.random()
            if roll < 0.06:
                return SimpleNamespace(completed=False, error=None)
            if roll < 0.10:
                return SimpleNamespace(completed=True, error=OSError("chaos playback lost"))
            return SimpleNamespace(completed=True, error=None)

        def apply(_action, **_kwargs):
            return self.rng.random() >= 0.06

        self.owner._voice_audio.open.side_effect = open_output
        self.owner._voice_audio.flush.side_effect = flush
        self.owner._voice_shortcut.apply.side_effect = apply
        self.owner._voice_shortcut.release_pending.side_effect = lambda: self.rng.random() >= 0.05
        self.owner._voice_shortcut.control_flag.side_effect = lambda *_a: self.rng.random() < 0.05

        self._patch("ovb_rc003.chromecast_host_activity.read_wetype_capture",
                    side_effect=self.read_capture)
        self._patch_object(host_module, "read_doubao_capture", side_effect=self.read_capture)
        self._patch_object(handsfree, "finish_with_timeout",
                           side_effect=lambda _identity, **_kw: "sent_once")
        self._patch_object(host_module.win32_input, "send_voice_key_combo_tap")
        self._patch("ovb_rc003.chromecast_voice_receiver.time",
                    new=SimpleNamespace(monotonic=self.clock))
        self._patch("ovb_rc003.chromecast_voice_host.time",
                    new=SimpleNamespace(monotonic=self.clock, sleep=lambda _s: None))
        self._patch("ovb_rc003.chromecast_voice_receiver.config.load_config",
                    return_value={"remote_recording_mode": self.mode,
                                  "remote_recording_limit_seconds": self.limit})

        self.capture_sessions = []
        self.capture_error = False
        identity = SessionIdentity.create("a" * 64)
        self.event_out, self.event_in = (Channel(identity, commands=False) for _ in range(2))
        self.command_out, self.command_in = (Channel(identity, commands=True) for _ in range(2))
        self.event_in.decode(self.event_out.encode("ready"))
        self.command_in.decode(self.command_out.encode("start", mode="run", voice=True))
        self.device = SimpleNamespace(voice_attributes={0x3f: "control", 0x3c: "audio"},
                                      write_voice=self.write_voice)
        self.receiver = VoiceReceiver(self.device, self.send, direct_notifications=True)
        self.receiver.available = True
        self.receiver.capabilities = voice_tests.CAPS
        self.host.client.voice_host.side_effect = (
            lambda attempt, result: self.replies.append(
                self.command_out.encode("voice_host", attempt=attempt, result=result)))
        self.host.client.cancel_voice.side_effect = (
            lambda epoch: self.replies.append(
                self.command_out.encode("voice_cancel", input_epoch=epoch)))
        self.loop = asyncio.new_event_loop()

    def close(self):
        self.loop.close()
        for patcher in reversed(self._stack):
            patcher.stop()
        if self.fixture is not None:
            self.fixture.doCleanups()

    # ----------------------------------------------------------- world I/O
    def clock(self):
        return self.now

    def send(self, kind, attempt, data, stamp):
        event = self.event_in.decode(self.event_out.encode(
            "voice", event=kind, attempt=attempt, data=data, time=stamp))
        self.host.enqueue(event)
        self.sent.append((kind, attempt, data))
        if kind == "host_start":
            self.schedule_capture_appearance()

    async def write_voice(self, value):
        if value == b"\x0c\x00":
            roll = self.rng.random()
            self.open_plan = ("success", "failed", "silent")[0 if roll < .55 else 1 if roll < .8 else 2]
            self.open_failure_sent = False
            if self.open_plan == "success":
                self.schedule(0.05 + self.rng.random() * 1.5, "frame", SOFTWARE)
            elif self.open_plan == "failed":
                self.schedule(0.05 + self.rng.random() * 1.5, "frame", OPEN_FAILED)
        elif value[:1] == b"\x0d":
            if self.rng.random() < 0.85:
                self.schedule(0.05 + self.rng.random() * 1.5, "frame", STOP)
        if self.rng.random() < 0.06:
            raise OSError("chaos device write failed")

    def read_capture(self):
        if self.capture_error:
            raise OSError("chaos capture unreadable")
        return tuple(self.capture_sessions)

    def schedule(self, when, kind, payload):
        self._seq += 1
        heapq.heappush(self._due, (self.now + when, self._seq, kind, payload))

    def schedule_capture_appearance(self):
        roll = self.rng.random()
        if roll < 0.25:
            return  # the capture never appears
        if roll < 0.45 or any(s.state == 1 for s in self.capture_sessions):
            self.schedule(0.0, "capture", "appear")
        else:
            self.schedule(0.05 + self.rng.random() * 2.0, "capture", "appear")

    def deliver_due(self, force=False):
        while self._due and (force or self._due[0][0] <= self.now):
            _when, _seq, kind, payload = heapq.heappop(self._due)
            if kind == "frame":
                self.receiver.notification(0x3f, payload, self.clock())
            elif kind == "capture":
                self.capture_mutate(payload)

    def capture_mutate(self, action):
        active = any(s.state == 1 for s in self.capture_sessions)
        if action == "appear" and not active:
            index = len(self.op_log) + len(self.capture_sessions)
            self.capture_sessions.append(session(name=f"cap{index}", state=1, pid=20 + index % 40))
        elif action == "end" and active:
            self.capture_sessions = [session(name=s.instance_id, state=0, pid=s.pid)
                                     if s.state == 1 else s for s in self.capture_sessions]
        elif action == "vanish":
            self.capture_sessions = []
        elif action == "error_on":
            self.capture_error = True
            self.schedule(0.2 + self.rng.random() * 2.0, "capture", "error_off")
        elif action == "error_off":
            self.capture_error = False
        elif action == "replace" and active:
            self.capture_sessions = [session(name="replacement", state=1, pid=30)]

    # ---------------------------------------------------------------- ops
    def advance(self):
        roll = self.rng.random()
        self.now += (self.rng.uniform(1.0, 12.0) if roll < 0.08 else self.rng.uniform(0.01, 0.3))

    def pick_op(self):
        rng = self.rng
        table = [("tick", 0.12), ("keyboard", 0.12), ("remote_physical", 0.13),
                 ("remote_mic", 0.07), ("remote_release", 0.08), ("remote_stop", 0.08),
                 ("remote_software", 0.05), ("reply", 0.12), ("rogue_reply", 0.05),
                 ("capture", 0.07), ("audio", 0.05), ("sync", 0.02), ("garbage", 0.04)]
        if self.provider == "wetype":
            table.append(("wetype_confirm", 0.05))
        roll = rng.random() * sum(weight for _, weight in table)
        for name, weight in table:
            roll -= weight
            if roll <= 0:
                return name
        return table[-1][0]

    def do_op(self, name):
        rng, host, receiver = self.rng, self.host, self.receiver
        if name == "keyboard":
            if rng.random() < 0.75:
                granted = host.enqueue_keyboard_start()
                return f"enqueue_keyboard_start({granted})"
            host._keyboard_start(self.clock())
            return "_keyboard_start"
        if name == "remote_physical":
            stream = self._stream_ids[-1] if self._stream_ids and rng.random() < 0.2 else rng.randint(1, 128)
            self._stream_ids.append(stream)
            receiver.notification(0x3f, bytes((4, 3, 2, stream)), self.clock())
            return f"physical stream={stream}"
        if name == "remote_mic":
            receiver.notification(0x3f, MIC_BUTTON, self.clock())
            return "mic_button"
        if name == "remote_release":
            receiver.notification(0x3f, RELEASE, self.clock())
            return "release"
        if name == "remote_stop":
            receiver.notification(0x3f, STOP, self.clock())
            return "stop"
        if name == "remote_software":
            receiver.notification(0x3f, SOFTWARE, self.clock())
            return "software_start"
        if name == "garbage":
            frame = rng.choice(GARBAGE_FRAMES)
            receiver.notification(0x3f, frame, self.clock())
            return f"garbage={frame.hex()}"
        if name == "reply":
            return "reply=" + ("none" if not self.deliver_reply() else "delivered")
        if name == "rogue_reply":
            gate = receiver.gate
            attempt = rng.choice([1, max(1, gate.attempt - 1), gate.attempt + 1])
            if attempt == gate.attempt:
                attempt += 1
            result = rng.choice(("ready", "failed", "released", "release_failed", "stop", "begin"))
            receiver.host({"attempt": attempt, "result": result})
            return f"rogue {result}@{attempt}"
        if name == "capture":
            action = rng.choice(("appear", "end", "vanish", "error_on", "replace"))
            self.capture_mutate(action)
            return f"capture={action}"
        if name == "wetype_confirm":
            value = rng.choice((None, True, False))
            self.owner._voice_shortcut.runtime_mic_confirmed = value
            return f"runtime_mic_confirmed={value}"
        if name == "audio":
            payload = bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 200)))
            receiver.notification(0x3c, payload, self.clock())
            return f"audio={len(payload)}B"
        if name == "sync":
            receiver.notification(0x3f, bytes((0x0a, 0, 0, 0, 0, 0, 0)), self.clock())
            return "sync"
        return "tick"

    def deliver_reply(self):
        if not self.replies:
            return False
        reply = self.command_in.decode(self.replies.popleft())
        if "input_epoch" in reply:
            self.receiver.cancel_input(reply["input_epoch"])
        else:
            self.receiver.host(reply)
        return True

    def pump(self):
        for _ in range(64):
            if self.host.events.empty():
                break
            while not self.host.events.empty():
                self.host._handle(self.host.events.get_nowait())
        self.host._poll_host()
        if self.host.state == "stopping" and not self.host.closed:
            self.host._stop_host()

    def device_tick(self):
        self.loop.run_until_complete(self.receiver.tick())

    # ----------------------------------------------------------- invariants
    def snapshot(self):
        gate, host = self.receiver.gate, self.host
        watch = host.capture_watch
        return (f"gate(state={gate.state} attempt={gate.attempt} stream={gate.stream} "
                f"possible_open={gate.possible_open} open_pending={gate.open_pending} "
                f"stop_seen={gate.stop_seen} host_released={gate.host_released} "
                f"reason={gate.reason!r}) host(state={host.state} attempt={host.attempt} "
                f"closed={host.closed} engaged={host.engaged} confirmed={host.confirmed} "
                f"capture={watch.status if watch is not None else 'none'})")

    def violation(self, key, invariant, message, step):
        if any(record[0] == key for record in self.violations):
            return
        self.violations.append((key, invariant, message, step))

    def check_step(self, step):
        gate, host = self.receiver.gate, self.host
        if gate.state == "idle" and gate.stream is not None:
            self.violation("INV5", 5, f"idle gate still owns stream {gate.stream}", step)
        if gate.state == "idle":
            probe = copy.deepcopy(gate)
            effects = probe.begin_host_start(self.clock())
            if (not any(effect.kind == "host_start" for effect in effects)
                    or probe.state != "starting"):
                self.violation("INV2", 2, "begin_host_start refused on an idle gate", step)
        if host.attempt > gate.attempt:
            self.violation("INV3", 3,
                           f"host attempt {host.attempt} ahead of gate attempt {gate.attempt}", step)
        watch = host.capture_watch
        if watch is not None and watch.ended and host.state in ("starting", "recording"):
            self.violation("INV4", 4,
                           f"attempt left {host.state}/engaged={host.engaged} after capture ended", step)
        if (gate.state in ("stopping", "blocked") or gate.possible_open or gate.open_pending):
            if self.shadow_stuck():
                self.violation("INV1", 1,
                               f"gate can never return to idle (state={gate.state} "
                               f"reason={gate.reason!r} possible_open={gate.possible_open})", step)

    def shadow_stuck(self):
        """Settle a gate copy with the world's committed completions.

        The host always releases, device writes succeed, an outstanding
        MIC_OPEN resolves per the device's committed plan (a failed open can
        never produce its stream), every close is acknowledged and the final
        user input is a STOP.  If even then the copy cannot reach idle, the
        real gate is deadlocked.
        """
        gate = copy.deepcopy(self.receiver.gate)
        now, plan = self.clock(), self.open_plan
        open_failure_sent = self.open_failure_sent
        pending = self.receiver.pending
        for _ in range(80):
            if gate.state == "idle" and gate.stream is None and not gate.possible_open:
                return False
            effects = []
            if pending is not None:
                # A write already in flight completes too; a confirmed close
                # releases the open liability just like any later close.
                effects.append(pending[0])
                pending = None
            if gate.state == "starting":
                effects += gate.host_result(gate.attempt, True, now)
            effects += gate.host_stopped(gate.attempt, True, now)
            if gate.possible_open:
                if plan == "failed":
                    if not open_failure_sent:
                        open_failure_sent = True
                        effects += gate.control(OPEN_FAILED, now)
                else:
                    effects += gate.control(SOFTWARE, now)
            if gate.state != "idle":
                effects += gate.control(STOP, now)
            for effect in effects:
                if effect.kind == "device" and gate.command_submitted(effect):
                    gate.command_result(effect, True, now)
            now += 1.0
        return True

    def check_final(self):
        gate, host = self.receiver.gate, self.host
        step = len(self.op_log)
        if gate.state != "idle":
            self.violation("INV1", 1, f"gate stuck in {gate.state} (reason={gate.reason!r})", step)
        host_state = {"idle": "idle", "starting": "starting", "recording": "recording",
                      "stopping": "stopping", "blocked": "stopping"}.get(gate.state)
        if host.state != host_state:
            self.violation("INV3", 3,
                           f"gate {gate.state} diverged from host {host.state}", step)
        if gate.state == "idle" and gate.stream is not None:
            self.violation("INV5", 5, f"idle gate still owns stream {gate.stream}", step)
        if self.owner._voice_shortcut.controller.active:
            self.violation("INV4", 4, "hold shortcut still engaged after input stopped", step)

    # ----------------------------------------------------------------- run
    def settle(self):
        for _ in range(300):
            gate = self.receiver.gate
            quiet = (gate.state == "idle" and self.host.state == "idle"
                     and not self.replies and self.host.events.empty()
                     and not self._due and self.receiver.pending is None
                     and not self.receiver.queue)
            if quiet:
                return
            self.deliver_due(force=True)
            if gate.possible_open:
                if self.open_plan == "failed":
                    if not self.open_failure_sent:
                        self.open_failure_sent = True
                        self.receiver.notification(0x3f, OPEN_FAILED, self.clock())
                else:
                    self.receiver.notification(0x3f, SOFTWARE, self.clock())
            if gate.state != "idle" and (gate.stream is not None or gate.stop_seen is None):
                # One final device STOP is "input stopped"; repeating it would
                # keep resetting the quiet window that reopens the gate.
                self.receiver.notification(0x3f, STOP, self.clock())
            while self.replies:
                self.deliver_reply()
            self.pump()
            self.device_tick()
            self.now += 1.0

    def run(self):
        for step in range(self.ops):
            self.advance()
            try:
                self.deliver_due()
                detail = self.do_op(self.pick_op())
                self.op_log.append(f"{step:04d} t={self.now:.3f} {detail}")
                self.pump()
                self.device_tick()
                self.check_step(step)
            except Exception:
                self.violation(f"INV6:{traceback.format_exc().splitlines()[-1]}", 6,
                               "exception escaped a handler:\n" + traceback.format_exc(), step)
        try:
            self.settle()
            self.check_final()
        except Exception:
            self.violation(f"INV6:{traceback.format_exc().splitlines()[-1]}", 6,
                           "exception escaped during settle:\n" + traceback.format_exc(),
                           len(self.op_log))
        return self.violations


class VoiceChaosTests(unittest.TestCase):
    def test_seeded_voice_state_machine_chaos(self):
        report = []
        for seed in SEEDS:
            world = ChaosWorld(seed, OPS)
            try:
                world.run()
                for key, invariant, message, step in world.violations:
                    report.append((key, invariant, seed, step, message,
                                   world.snapshot(), list(world.op_log)))
            finally:
                world.close()
        if not report:
            return
        seen, lines = set(), []
        for key, invariant, seed, step, message, state, log in report:
            if key in seen:
                continue
            seen.add(key)
            peers = sorted(other[2] for other in report if other[0] == key)
            lines.append(
                f"\n=== invariant {invariant} violated ({key}) ===\n"
                f"seeds: {peers}\nfirst seed: {seed} at step {step}\n"
                f"{message}\n{state}\n"
                f"operation sequence ({len(log)} ops):\n" + "\n".join(log))
        self.fail(f"{len(report)} chaos violation(s), {len(seen)} class(es){''.join(lines)}")


class FailedOpenLiabilityReproTests(unittest.TestCase):
    """Regression guards for the INV1 deadlock the chaos driver found (long
    run seeds 122/194/197 first): a toggle attempt whose MIC_OPEN (0x0c00) was
    submitted and then failed held ``possible_open`` forever and never
    returned to idle - ``begin_host_start`` refused (the keyboard did nothing)
    and remote starts could only emit another close (the remote did nothing).

    The liability is now released when the device confirms the MIC_CLOSE
    (``command_result`` on ``0x0d``), so these tests drive the receiver's real
    completion path (submitted writes are confirmed) and assert the recovery
    contract at both consumer entry points.
    """

    def drive(self, gate, effects, now):
        """Confirm submitted device writes exactly like VoiceReceiver.tick()."""
        for effect in [e for e in effects if e.kind == "device"]:
            if gate.command_submitted(effect):
                gate.command_result(effect, True, now)

    def assert_recovers(self, gate):
        self.drive(gate, gate.host_stopped(gate.attempt, True, 2.0), 2.0)
        gate.tick(30.0)
        self.assertEqual(gate.state, "idle", f"gate stuck in {gate.state} ({gate.reason})")
        self.assertTrue(any(effect.kind == "host_start"
                            for effect in gate.begin_host_start(31.0)),
                        "keyboard start refused after the failed open cleared")
        self.assertEqual(gate.state, "starting")

    def test_device_reported_open_failure_must_not_deadlock_the_gate(self):
        gate = Recording("toggle")
        self.drive(gate, gate.begin_host_start(1.0), 1.0)
        self.drive(gate, gate.host_result(1, True, 1.1), 1.1)  # MIC_OPEN 0x0c00
        self.assertTrue(gate.possible_open)
        self.drive(gate, gate.control(bytes((0x0c, 0)), 1.2), 1.2)  # device: open failed
        self.drive(gate, gate.control(bytes((0, 0)), 1.3), 1.3)  # device: close acknowledged
        self.assert_recovers(gate)

    def test_open_write_failure_must_not_deadlock_the_gate(self):
        gate = Recording("toggle")
        self.drive(gate, gate.begin_host_start(1.0), 1.0)
        command = gate.host_result(1, True, 1.1)[0]  # MIC_OPEN 0x0c00
        self.assertTrue(gate.command_submitted(command))
        self.drive(gate, gate.command_result(command, False, 1.2), 1.2)  # GATT write failed
        self.assert_recovers(gate)

    def test_confirmed_close_releases_a_still_in_flight_open(self):
        # The open never answers (late/unknown), the attempt ends and the
        # device confirms the MIC_CLOSE: the liability must release so the
        # keyboard entry works again instead of waiting for a phantom stream.
        gate = Recording("toggle")
        self.drive(gate, gate.begin_host_start(1.0), 1.0)
        self.drive(gate, gate.host_result(1, True, 1.1), 1.1)  # MIC_OPEN 0x0c00
        self.drive(gate, gate.finish(1.6, "time_limit"), 1.6)  # MIC_CLOSE 0x0d00
        self.drive(gate, gate.control(bytes((0, 0)), 1.7), 1.7)  # device: close acknowledged
        self.assert_recovers(gate)


if __name__ == "__main__":
    unittest.main()
