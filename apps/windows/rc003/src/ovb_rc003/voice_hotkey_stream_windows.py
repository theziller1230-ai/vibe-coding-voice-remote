"""Open the remote microphone stream when the voice hotkey is pressed.

The remote's microphone is the only audio source behind ``CABLE Output``, so
the stream must already be running before Doubao records.  The remote's own
button path opens it, but a physical keyboard shortcut does not - Doubao starts
recording against a silent virtual cable.  Watching the configured hotkey with
a low-level keyboard hook closes that gap without polling and without adding
latency: the open command goes out on the same key edge that starts Doubao.

Only the app's own synthesised Right Alt is ignored - identified by the
``dwExtraInfo`` voice-event marker rather than by ``LLKHF_INJECTED``.  That
keeps the physicalizer's tap from closing a stream it just opened, while real
hardware edges still count.  Ignoring every injected edge would also make the
path untestable, since a test driver can only send injected input.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Iterable, Optional

from . import voice_key_physicalizer_windows

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
DOWN_EVENTS = (WM_KEYDOWN, WM_SYSKEYDOWN)
UP_EVENTS = (WM_KEYUP, WM_SYSKEYUP)
LLKHF_INJECTED = 0x10


def _is_own_voice_edge(extra_info: int) -> bool:
    """True for the marker this app stamps on its own synthesised voice keys."""

    return voice_key_physicalizer_windows._is_voice_event_marker(extra_info)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class VoiceHotkeyStreamWatcher:
    """Watch one hotkey's physical edges and report press/release."""

    def __init__(
        self,
        vk_codes: Iterable[int],
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        *,
        logger=None,
    ) -> None:
        self._vk_codes = frozenset(int(code) for code in vk_codes)
        self._on_press = on_press
        self._on_release = on_release
        self._logger = logger
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._callback = None
        self._held = False

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        if not self._vk_codes:
            return False
        if self._thread is not None:
            return True
        self._thread = threading.Thread(
            target=self._run, name="voice-hotkey-stream", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        thread_id = self._thread_id
        self._thread = None
        if thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)
            except OSError:
                pass

    # -- hook ------------------------------------------------------------
    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self._thread_id = kernel32.GetCurrentThreadId()

        def callback(ncode, wparam, lparam):
            if ncode == 0 and wparam in DOWN_EVENTS + UP_EVENTS:
                try:
                    info = ctypes.cast(
                        lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)
                    ).contents
                    if info.vkCode in self._vk_codes:
                        own = _is_own_voice_edge(int(info.dwExtraInfo))
                        self._log(
                            f"hotkey raw edge vk={info.vkCode} wp={wparam} "
                            f"injected={bool(info.flags & LLKHF_INJECTED)} own={own}")
                        if not own:
                            if wparam in DOWN_EVENTS and not self._held:
                                self._held = True
                                self._safe(self._on_press)
                            elif wparam in UP_EVENTS and self._held:
                                self._held = False
                                self._safe(self._on_release)
                except Exception:
                    pass
            return user32.CallNextHookEx(None, ncode, wparam, lparam)

        self._callback = _HOOKPROC(callback)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._callback, None, 0)
        if not hook:
            self._log(f"voice hotkey hook failed err={ctypes.get_last_error()}")
            return
        self._log("voice hotkey stream watcher installed")
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWindowsHookEx(hook)

    def _safe(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # never break the hook chain
            self._log(f"voice hotkey action failed: {exc}")

    def _log(self, message: str) -> None:
        if self._logger is not None:
            try:
                self._logger.info(message)
            except Exception:
                pass
