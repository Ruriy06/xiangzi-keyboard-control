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

    def test_dashboard_shows_hid_description_without_device_path_prefix(self) -> None:
        """HID 迁移回归：device 是上百字符的设备路径，不能直接拼进下拉框显示文本。"""
        from hid_control.hid_service import PortInfo

        dashboard = Dashboard()
        path = "\\\\?\\HID#VID_046A&PID_0001&Col03#9&2b8005e8&0&0002#{4d1e55b2-f16f-11cf-88cb-001111000030}"
        dashboard.set_ports([PortInfo(path, "USB Keyboard（VID:0x046A PID:0x0001，接口 0）", "HID VID:PID=046A:0001")])
        self.assertEqual(dashboard.port_combo.count(), 1)
        self.assertEqual(dashboard.port_combo.currentText(), "USB Keyboard（VID:0x046A PID:0x0001，接口 0）")
        self.assertNotIn("HID#", dashboard.port_combo.currentText())
        # 路径仍作为 item data 保留，connect() 依赖它
        self.assertEqual(dashboard.port_combo.currentData(), path)
        # 完整路径放进悬浮提示，保留多台同型设备时的区分信息
        self.assertEqual(dashboard.port_combo.itemData(0, Qt.ItemDataRole.ToolTipRole), path)

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
        self.assertEqual(MainWindow._checkbox_display_text("启用边界切换保护", False), "○ 未选 · 启用边界切换保护")
        self.assertEqual(MainWindow._checkbox_display_text("启用边界切换保护", True), "✓ 已选 · 启用边界切换保护")

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
        window._hid = type("Serial", (), {"is_connected": True})()
        window.dashboard = Dashboard()
        window._log = lambda _message: None
        self.assertTrue(MainWindow._run_preflight(window))
        window._hid.is_connected = False
        self.assertFalse(MainWindow._run_preflight(window))


if __name__ == "__main__":
    unittest.main()
