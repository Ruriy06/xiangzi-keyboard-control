from __future__ import annotations

import traceback
from pathlib import Path

from hid_control.app import run


def main() -> int:
    try:
        return run()
    except Exception:
        log_path = Path(__file__).resolve().parent / "data" / "startup-error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
