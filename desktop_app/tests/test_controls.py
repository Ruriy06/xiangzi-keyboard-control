import unittest
from pathlib import Path

from hid_control import APP_NAME
from hid_control.hotkeys import FALLBACK_SHORTCUTS, GlobalHotkeyService
from hid_control.models import ActionDefinition, ActionStep, AppState, ControlSettings, FlowMode, FlowStep, WorkflowDefinition


class ControlTests(unittest.TestCase):
    def test_hotkey_candidates_keep_requested_shortcut_first(self) -> None:
        service = GlobalHotkeyService()
        candidates = service._candidates("start", "Ctrl+Alt+F8")
        self.assertEqual(candidates[0], "Ctrl+Alt+F8")
        self.assertIn("Ctrl+Shift+F8", candidates)

    def test_fallbacks_exist_for_start_and_stop(self) -> None:
        self.assertTrue(FALLBACK_SHORTCUTS["start"])
        self.assertTrue(FALLBACK_SHORTCUTS["stop"])

    def test_side_button_defaults_start_with_forward_and_stop_with_back(self) -> None:
        settings = ControlSettings()
        self.assertEqual(settings.start_side_button, "XBUTTON2")
        self.assertEqual(settings.stop_side_button, "XBUTTON1")

    def test_application_name_and_icon_asset(self) -> None:
        self.assertEqual(APP_NAME, "祥子の宝贝")
        self.assertTrue((Path(__file__).resolve().parents[2] / "xiangzi.png").exists())

    def test_generic_hotkeys_default_to_blank(self) -> None:
        settings = ControlSettings()
        self.assertEqual(settings.start_hotkey, "")
        self.assertEqual(settings.stop_hotkey, "")

    def test_object_shortcut_has_no_automatic_fallback(self) -> None:
        service = GlobalHotkeyService()
        self.assertEqual(service._candidates("action:abc", "Ctrl+Alt+1"), ["Ctrl+Alt+1"])

    def test_window_layout_ratios_and_navigation_state_are_persisted(self) -> None:
        state = AppState.from_dict({"window_layout": {"width_ratio": 2, "height_ratio": 0.1, "navigation_collapsed": True}})
        self.assertEqual(state.window_layout.width_ratio, 1.0)
        self.assertEqual(state.window_layout.height_ratio, 0.35)
        self.assertTrue(state.window_layout.navigation_collapsed)
        self.assertEqual(state.to_dict()["window_layout"]["width_ratio"], 1.0)
        self.assertTrue(state.to_dict()["window_layout"]["navigation_collapsed"])

    def test_window_layout_preserves_last_minimized_state(self) -> None:
        state = AppState.from_dict({"window_layout": {"width_ratio": 0.62, "height_ratio": 0.74, "last_window_state": "minimized"}})
        self.assertEqual(state.window_layout.last_window_state, "minimized")
        self.assertEqual(state.to_dict()["window_layout"]["last_window_state"], "minimized")

    def test_window_layout_persists_only_supported_themes(self) -> None:
        state = AppState.from_dict({"window_layout": {"theme": "dark_blue"}})
        self.assertEqual(state.window_layout.theme, "dark_blue")
        self.assertEqual(AppState.from_dict({"window_layout": {"theme": "warm_gray"}}).window_layout.theme, "dark_blue")
        self.assertEqual(AppState.from_dict({"window_layout": {"theme": "unknown"}}).window_layout.theme, "light")
        self.assertEqual(state.to_dict()["window_layout"]["theme"], "dark_blue")

    def test_action_step_random_wait_is_serialized_and_normalized(self) -> None:
        step = ActionStep.from_dict({"kind": "key_tap", "value": "A", "random_wait_min_ms": 900, "random_wait_max_ms": 300})
        self.assertEqual((step.random_wait_min_ms, step.random_wait_max_ms), (300, 900))
        restored = AppState.from_dict(AppState(actions=[ActionDefinition(steps=[step])]).to_dict())
        self.assertEqual(restored.actions[0].steps[0].random_wait_max_ms, 900)

    def test_flow_step_random_wait_is_serialized(self) -> None:
        step = FlowStep(kind="action", action_id="A", random_wait_min_ms=300, random_wait_max_ms=900)
        workflow = WorkflowDefinition(mode=FlowMode.AB)
        restored = AppState.from_dict(AppState(workflows=[workflow, WorkflowDefinition(mode=FlowMode.CUSTOM, root_step=FlowStep(kind="group", children=[step]))]).to_dict())
        self.assertEqual(restored.workflows[1].root_step.children[0].random_wait_max_ms, 900)


if __name__ == "__main__":
    unittest.main()
