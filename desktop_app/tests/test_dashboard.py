import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from hid_control.models import ActionDefinition, ActionKind, ActionStep, AppState, WorkflowDefinition
from hid_control.ui.dashboard import Dashboard
from hid_control.ui.main_window import MainWindow
from hid_control.ui.settings import SettingsPage
from hid_control.ui.step_input import StepInputPanel


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_active_workflow_migrates_to_current_target(self) -> None:
        state = AppState.from_dict({"active_workflow_id": "workflow-1"})
        self.assertEqual((state.active_target_kind, state.active_target_id), ("workflow", "workflow-1"))

    def test_dashboard_lists_workflows_and_actions_as_targets(self) -> None:
        dashboard = Dashboard()
        dashboard.set_targets([WorkflowDefinition(id="W", name="流程 A")], [ActionDefinition(id="A", name="操作 A")], "action", "A")
        self.assertEqual(dashboard.target_combo.count(), 2)
        self.assertEqual(dashboard.target_combo.currentData(), ("action", "A"))
        self.assertIn("操作：操作 A", dashboard.target_combo.currentText())

    def test_keyboard_workspace_uses_outer_editor_scroll_and_full_height(self) -> None:
        panel = StepInputPanel(keyboard_height=300)
        panel.kind_combo.setCurrentIndex(panel.kind_combo.findData(ActionKind.KEY_TAP))
        self.assertFalse(hasattr(panel, "keyboard_scroll"))
        self.assertGreaterEqual(panel.stack.minimumHeight(), panel.keyboard_picker.sizeHint().height() + 42)

    def test_dashboard_exposes_runtime_and_preflight_status_cards(self) -> None:
        dashboard = Dashboard()
        dashboard.set_runtime_status("流程运行中", "success")
        dashboard.set_preflight_result("检查通过", True)
        self.assertEqual(dashboard.runtime_label.text(), "流程运行中")
        self.assertEqual(dashboard.runtime_label.property("level"), "success")
        self.assertEqual(dashboard.preflight_label.text(), "检查通过")
        self.assertEqual(dashboard.preflight_label.property("level"), "success")

    def test_presentation_refresh_limiter_only_controls_ui_updates(self) -> None:
        self.assertFalse(MainWindow._presentation_refresh_due(10.0, 10.11))
        self.assertTrue(MainWindow._presentation_refresh_due(10.0, 10.13))

    def test_log_view_keeps_user_scroll_position_when_reading_history(self) -> None:
        dashboard = Dashboard()
        dashboard.resize(400, 180)
        dashboard.show()
        self.app.processEvents()
        for index in range(40):
            dashboard.append_log(f"日志 {index}")
        scrollbar = dashboard.log_view.verticalScrollBar()
        scrollbar.setValue(0)
        dashboard.append_log("查看历史时的新日志")
        self.assertEqual(scrollbar.value(), 0)
        dashboard.close()

    def test_checkbox_display_text_makes_selection_explicit(self) -> None:
        self.assertEqual(MainWindow._checkbox_display_text("启用钓鱼识别", False), "○ 未选 · 启用钓鱼识别")
        self.assertEqual(MainWindow._checkbox_display_text("启用钓鱼识别", True), "✓ 已选 · 启用钓鱼识别")

    def test_settings_theme_selector_emits_and_loads_saved_value(self) -> None:
        page = SettingsPage()
        emitted: list[str] = []
        page.theme_changed.connect(emitted.append)
        page.set_theme("warm_gray")
        self.assertEqual(page.theme_combo.count(), 2)
        self.assertEqual(page.theme_combo.currentData(), "dark_blue")
        self.assertEqual(emitted, [])
        page.theme_combo.setCurrentIndex(page.theme_combo.findData("light"))
        self.assertEqual(emitted, ["light"])

    def test_preflight_requires_connection_and_valid_active_action(self) -> None:
        state = AppState(actions=[ActionDefinition(id="A", name="操作", steps=[ActionStep(ActionKind.KEY_TAP, "A")])], active_target_kind="action", active_target_id="A")
        window = type("PreflightWindow", (), {})()
        window._state = state
        window._serial = type("Serial", (), {"is_connected": True})()
        window.dashboard = Dashboard()
        window._log = lambda _message: None
        self.assertTrue(MainWindow._run_preflight(window))
        window._serial.is_connected = False
        self.assertFalse(MainWindow._run_preflight(window))


if __name__ == "__main__":
    unittest.main()
