from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 先应用 CPU-only 软件渲染策略，再导入任何 Qt 相关模块。
from hid_control.runtime_policy import apply_software_render_environment

apply_software_render_environment()

from hid_control.app import run  # noqa: E402  （必须晚于渲染策略）


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
