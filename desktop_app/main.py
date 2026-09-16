from __future__ import annotations

import sys
import traceback
from pathlib import Path

from hid_control.app import run


def _base_dir() -> Path:
    """打包后返回可执行文件所在目录，否则返回项目目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    try:
        return run()
    except Exception:
        log_path = _base_dir() / "data" / "startup-error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
