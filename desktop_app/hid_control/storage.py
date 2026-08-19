from __future__ import annotations

import json
from pathlib import Path

from .models import AppState


class SettingsStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path(__file__).resolve().parents[1] / "data" / "config.json"

    def load(self) -> AppState:
        if not self.config_path.exists():
            return AppState()
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            migrated = self._backup_legacy_workflows(raw)
            state = AppState.from_dict(raw)
            if migrated:
                self.save(state)
            return state
        except (OSError, ValueError, TypeError):
            return AppState()

    def _backup_legacy_workflows(self, raw: dict) -> bool:
        workflows = raw.get("workflows", []) if isinstance(raw, dict) else []
        if not isinstance(workflows, list):
            return False
        if any(("nodes" in item or "action_ids" in item) for item in workflows if isinstance(item, dict)):
            backup_path = self.config_path.with_name("config.before-simple-workflow.json")
        elif any("mode" not in item for item in workflows if isinstance(item, dict)):
            backup_path = self.config_path.with_name("config.before-duration-custom-flow.json")
        else:
            return False
        if not backup_path.exists():
            backup_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def save(self, state: AppState) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.config_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.config_path)
