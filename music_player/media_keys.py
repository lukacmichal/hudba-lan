"""Global media-key listener for Windows (low-level keyboard hook via ctypes)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading

from PySide6.QtCore import QObject, Signal

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_VK_MEDIA_PLAY_PAUSE = 0xB3
_VK_Y = 0x59

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
_user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
_user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
_user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# LRESULT (pointer-sized) — must match CallNextHookEx return type on 64-bit.
_HOOKPROC = ctypes.CFUNCTYPE(
    ctypes.wintypes.LPARAM,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class MediaKeyListener(QObject):
    """Emits ``play_pause_pressed`` whenever the global Play/Pause media key is hit."""

    play_pause_pressed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hook: ctypes.wintypes.HHOOK | None = None
        self._hook_proc_ref: _HOOKPROC | None = None  # prevent GC
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="media-key-hook")
        self._thread.start()

    def _run(self) -> None:
        def _low_level_handler(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and w_param == _WM_KEYDOWN:
                kb = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == _VK_Y:
                    ctrl = _user32.GetAsyncKeyState(0xA2) & 0x8000 or _user32.GetAsyncKeyState(0xA3) & 0x8000
                    alt = _user32.GetAsyncKeyState(0xA4) & 0x8000 or _user32.GetAsyncKeyState(0xA5) & 0x8000
                    if ctrl and alt:
                        self.play_pause_pressed.emit()
            return _user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._hook_proc_ref = _HOOKPROC(_low_level_handler)
        self._hook = _user32.SetWindowsHookExW(
            _WH_KEYBOARD_LL, self._hook_proc_ref, None, 0,
        )
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
