import unittest

from hid_control.models import ActionKind, ActionStep, DeviceSettings, STEP_LABELS
from hid_control.protocol import ProtocolError, command_for_step, device_configuration_commands


class ProtocolTests(unittest.TestCase):
    def test_common_key_and_combo(self) -> None:
        self.assertEqual(command_for_step(ActionStep(ActionKind.KEY_TAP, "tab")), "{TAB}")
        self.assertEqual(command_for_step(ActionStep(ActionKind.KEY_COMBO, "ctrl+c")), "{CTRL+C}")

    def test_75_percent_named_keys(self) -> None:
        self.assertEqual(command_for_step(ActionStep(ActionKind.KEY_TAP, "DELETE")), "{DELETE}")
        self.assertEqual(command_for_step(ActionStep(ActionKind.KEY_TAP, "LBRACKET")), "{LBRACKET}")
        self.assertEqual(command_for_step(ActionStep(ActionKind.KEY_DOWN, "CAPS_LOCK")), "{KEY_DOWN_CAPS_LOCK}")

    def test_step_label_is_chinese_first(self) -> None:
        self.assertEqual(STEP_LABELS[ActionKind.KEY_TAP], "单击按键（key_tap）")

    def test_normalized_movement(self) -> None:
        self.assertEqual(command_for_step(ActionStep(ActionKind.MOVE_NORMALIZED, "500_500")), "{MOVE_NORM_500_500}")

    def test_invalid_normalized_movement_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            command_for_step(ActionStep(ActionKind.MOVE_NORMALIZED, "1001_0"))

    def test_device_configuration_has_new_firmware_commands(self) -> None:
        commands = device_configuration_commands(DeviceSettings(screen_width=3840, screen_height=2160, key_press_delay=120))
        self.assertIn("{SCR_3840_2160}", commands)
        self.assertIn("{CFG_KEY_PRESS_120}", commands)
        self.assertIn("{CFG_MAX_JUMP_80}", commands)


if __name__ == "__main__":
    unittest.main()
