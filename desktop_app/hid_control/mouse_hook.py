from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal


WH_MOUSE_LL = 14
WM_XBUTTONDOWN = 0x020B
WM_QUIT = 0x0012
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MouseSideButtonService(QObject):
    pressed = Signal(str)
    error_occurred = Signal(str)
    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._callback = None
        self._ready = threading.Event()
        self._hook = None

    @property
    def is_running(self) -> bool:
        return self._hook is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if sys.platform != "win32" or (self._thread and self._thread.is_alive()):
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._message_loop, name="mouse-side-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=1)
        self._thread = None
        self._thread_id = 0
        self._callback = None
        self._hook = None

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        self._thread_id = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

        @HOOKPROC
        def hook_proc(code: int, message_id: int, l_param: int) -> int:
            if code >= 0 and message_id == WM_XBUTTONDOWN:
                data = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                button = (data.mouseData >> 16) & 0xFFFF
                if button == 1:
                    self.pressed.emit("XBUTTON1")
                elif button == 2:
                    self.pressed.emit("XBUTTON2")
            return user32.CallNextHookEx(self._hook, code, message_id, l_param)

        self._callback = hook_proc
        # 低级钩子回调运行在当前进程，hmod 应为 NULL；避免 64 位模块句柄兼容问题。
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._callback, None, 0)
        if not self._hook:
            error_code = kernel32.GetLastError()
            self.error_occurred.emit(f"无法安装鼠标侧键监听钩子（Windows 错误码 {error_code}）")
            self._ready.set()
            return

        self.status_changed.emit("鼠标侧键监听已启用：前进侧键启动/恢复，后退侧键停止")
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
