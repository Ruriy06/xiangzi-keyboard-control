from __future__ import annotations

import ctypes


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
