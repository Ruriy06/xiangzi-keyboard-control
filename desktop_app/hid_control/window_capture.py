from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    left: int
    top: int
    width: int
    height: int


def list_visible_windows() -> list[WindowInfo]:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass
    if ctypes.sizeof(ctypes.c_void_p) == 0:
        return []
    user32 = ctypes.windll.user32
    windows: list[WindowInfo] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(handle, _lparam):
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, title, len(title))
        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width >= 80 and height >= 80:
            windows.append(WindowInfo(int(handle), title.value, rect.left, rect.top, width, height))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def primary_screen_resolution() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        width, height = int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        if width > 0 and height > 0:
            return width, height
    except (AttributeError, OSError):
        pass
    return 1920, 1080


def window_by_title(title: str) -> WindowInfo | None:
    return next((window for window in list_visible_windows() if window.title == title), None)
