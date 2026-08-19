import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hid_control.models import ActionDefinition, ActionKind, ActionStep, FishingSettings, VisionSettings
from hid_control.ui.action_editor import ActionEditor
from hid_control.ui.duration_input import DurationInput
from hid_control.ui.settings import SettingsPage
from hid_control.ui.step_input import StepInputPanel
from hid_control.ui.vision_page import VisionPage


class ActionEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_adding_step_preserves_existing_delays(self) -> None:
        action = ActionDefinition(steps=[ActionStep(ActionKind.KEY_TAP, "A", 100), ActionStep(ActionKind.KEY_TAP, "B", 200)])
        editor = ActionEditor()
        editor.set_actions([action])
        self.app.processEvents()
        editor.step_input.kind_combo.setCurrentIndex(editor.step_input.kind_combo.findData(ActionKind.KEY_TAP))
        editor.step_input._key_value = "C"
        editor.step_input.after_duration.set_milliseconds(300)
        editor._add_step()
        self.assertEqual([step.delay_after_ms for step in action.steps], [100, 200, 300])

    def test_move_buttons_preserve_wait_duration_and_post_delay(self) -> None:
        action = ActionDefinition(steps=[
            ActionStep(ActionKind.KEY_TAP, "A", 1_000),
            ActionStep(ActionKind.WAIT, "120000", 0),
            ActionStep(ActionKind.KEY_TAP, "B", 500),
        ])
        editor = ActionEditor()
        editor.set_actions([action])
        self.app.processEvents()
        editor.step_table.selectRow(1)
        editor._move_step(-1)
        self.assertEqual([(step.kind, step.value, step.delay_after_ms) for step in action.steps], [
            (ActionKind.WAIT, "120000", 0),
            (ActionKind.KEY_TAP, "A", 1_000),
            (ActionKind.KEY_TAP, "B", 500),
        ])

    def test_mouse_step_uses_button_picker_not_raw_text(self) -> None:
        panel = StepInputPanel()
        panel.kind_combo.setCurrentIndex(panel.kind_combo.findData(ActionKind.MOUSE_CLICK))
        panel.mouse_combo.setCurrentIndex(panel.mouse_combo.findData("RIGHT"))
        self.assertEqual(panel.build_step().value, "RIGHT")

    def test_key_down_and_up_have_no_implicit_software_delay(self) -> None:
        panel = StepInputPanel()
        panel.kind_combo.setCurrentIndex(panel.kind_combo.findData(ActionKind.KEY_DOWN))
        panel._key_value = "W"
        panel.after_duration.set_milliseconds(0)
        step = panel.build_step()
        self.assertEqual((step.kind, step.value, step.delay_after_ms), (ActionKind.KEY_DOWN, "W", 0))

    def test_invalid_legacy_mouse_value_is_not_silently_converted(self) -> None:
        panel = StepInputPanel()
        panel.set_step(ActionStep(ActionKind.MOUSE_CLICK, "2"))
        self.assertEqual(panel.build_step().value, "2")
        self.assertIn("无效", panel.mouse_warning.text())
        panel.mouse_combo.setCurrentIndex(panel.mouse_combo.findData("RIGHT"))
        self.assertEqual(panel.build_step().value, "RIGHT")

    def test_duration_input_preserves_time_when_unit_changes(self) -> None:
        duration = DurationInput()
        duration.set_milliseconds(2_000)
        duration.unit.setCurrentIndex(2)
        self.assertEqual(duration.milliseconds(), 2_000)

    def test_locked_action_cannot_be_edited_or_deleted(self) -> None:
        action = ActionDefinition(name="已锁定", steps=[ActionStep(ActionKind.KEY_TAP, "A")], locked=True)
        editor = ActionEditor()
        editor.set_actions([action])
        self.app.processEvents()

        self.assertFalse(editor.action_name.isEnabled())
        self.assertFalse(editor.save_button.isEnabled())
        self.assertFalse(editor.delete_action_button.isEnabled())
        editor._delete_step()
        editor._delete_action()
        self.assertEqual(len(action.steps), 1)
        self.assertEqual(editor._actions, [action])

        editor._toggle_lock(action.id)
        self.assertFalse(action.locked)
        self.assertTrue(editor.action_name.isEnabled())
        self.assertTrue(editor.save_button.isEnabled())

    def test_move_preview_emits_unsaved_step_and_explains_zero_position(self) -> None:
        panel = StepInputPanel()
        captured: list[ActionStep] = []
        panel.move_preview_requested.connect(captured.append)
        panel.kind_combo.setCurrentIndex(panel.kind_combo.findData(ActionKind.MOVE_NORMALIZED))
        panel.x_input.setValue(500)
        panel.y_input.setValue(250)
        panel._emit_move_preview()

        zero_panel = StepInputPanel()
        zero_panel.kind_combo.setCurrentIndex(zero_panel.kind_combo.findData(ActionKind.MOVE_PIXEL))
        zero_panel._emit_move_preview()

        self.assertEqual([(step.kind, step.value) for step in captured], [
            (ActionKind.MOVE_NORMALIZED, "500_250"),
        ])
        self.assertIn("0,0", zero_panel.move_status_label.text())

    def test_operation_buttons_have_icons_and_semantic_colors(self) -> None:
        editor = ActionEditor()
        self.assertFalse(editor.add_step_button.icon().isNull())
        self.assertFalse(editor.delete_step_button.icon().isNull())
        self.assertFalse(editor.save_button.icon().isNull())
        self.assertEqual(editor.add_step_button.property("actionRole"), "primaryAction")
        self.assertEqual(editor.delete_step_button.property("actionRole"), "dangerAction")
        self.assertEqual(editor.save_button.property("actionRole"), "successAction")

    def test_rhythm_labels_wrap_and_keep_minimum_width(self) -> None:
        panel = StepInputPanel()
        self.assertTrue(panel.random_wait_min_label.wordWrap())
        self.assertTrue(panel.random_wait_max_label.wordWrap())
        self.assertGreaterEqual(panel.random_wait_min_label.minimumWidth(), 128)
        self.assertIn("下限", panel.random_wait_min_label.toolTip())

    def test_vision_page_starts_disabled_and_emits_settings(self) -> None:
        page = VisionPage()
        page.set_data([], VisionSettings(template_path="D:/target.png", threshold=0.91, scan_interval_ms=700), FishingSettings())
        self.assertFalse(page.template_enabled.isChecked())
        self.assertFalse(page.fishing_enabled.isChecked())
        self.assertEqual(page.template_path.text(), "D:/target.png")
        self.assertEqual(page.template_threshold.value(), 0.91)

        captured: list[VisionSettings] = []
        page.template_settings_changed.connect(captured.append)
        page.template_interval.setValue(800)
        self.assertEqual(captured[-1].scan_interval_ms, 800)

    def test_device_status_panel_shows_firmware_reported_values(self) -> None:
        page = SettingsPage()
        self.assertEqual(page.device_status_group.title(), "单片机状态（设备实际回传）")
        page.update_device_status("{SCR:2560x1600}")
        page.update_device_status("{CFG:KEY_PRESS_BASE=120}")
        page.update_device_status("{CFG:MOUSE_MAX_JUMP=80}")

        self.assertIn("屏幕分辨率：2560x1600", page.device_status_label.text())
        self.assertIn("普通按键按住：120", page.device_status_label.text())
        self.assertIn("绝对移动最大步长：80", page.device_status_label.text())


if __name__ == "__main__":
    unittest.main()
