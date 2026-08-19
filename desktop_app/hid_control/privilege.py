from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def is_administrator() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def restart_as_administrator() -> bool:
    """通过 UAC 重新启动当前应用；用户取消 UAC 时返回 False。"""
    if sys.platform != "win32":
        return False
    executable = sys.executable
    script = str(Path(sys.argv[0]).resolve())
    arguments = f'"{script}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, arguments, None, 1)
    return result > 32
