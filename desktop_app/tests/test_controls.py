import unittest
from pathlib import Path

from hid_control import APP_NAME
from hid_control.fishing import FishingService
from hid_control.hotkeys import FALLBACK_SHORTCUTS, GlobalHotkeyService
from hid_control.models import ActionDefinition, ActionStep, AppState, ControlSettings, CustomFlowStep, CustomStepKind, FishingPreset, FishingSettings, FlowMode, FlowStep, MaterialCaptureSettings, VisionPreset, VisionSettings, WorkflowDefinition


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

    def test_material_capture_settings_migrate_legacy_fishing_shortcuts(self) -> None:
        state = AppState.from_dict({"fishing": {"color_pick_hotkey": "F6", "region_pick_hotkey": "F7", "window_title": "游戏"}})
        self.assertEqual(state.material_capture, MaterialCaptureSettings(window_title="游戏", color_pick_hotkey="F6", region_capture_hotkey="F7"))
        restored = AppState.from_dict(state.to_dict())
        self.assertEqual(restored.material_capture.color_pick_hotkey, "F6")

    def test_vision_settings_are_persisted_and_clamped(self) -> None:
        state = AppState.from_dict({"vision": {"template_path": "D:/target.png", "threshold": 2, "scan_interval_ms": 10}})
        self.assertEqual((state.vision.template_path, state.vision.threshold, state.vision.scan_interval_ms), ("D:/target.png", 1.0, 100))
        self.assertEqual(state.vision.rules, [])
        self.assertEqual(state.to_dict()["vision"]["template_path"], "D:/target.png")

    def test_vision_preset_is_serialized(self) -> None:
        preset = VisionPreset(name="找目标", settings=VisionSettings(source="color", color_hex="#11AA22"))
        restored = AppState.from_dict(AppState(vision_presets=[preset]).to_dict())
        self.assertEqual(restored.vision_presets[0].name, "找目标")
        self.assertEqual(restored.vision_presets[0].settings.color_hex, "#11AA22")

    def test_action_step_random_wait_is_serialized_and_normalized(self) -> None:
        step = ActionStep.from_dict({"kind": "key_tap", "value": "A", "random_wait_min_ms": 900, "random_wait_max_ms": 300})
        self.assertEqual((step.random_wait_min_ms, step.random_wait_max_ms), (300, 900))
        restored = AppState.from_dict(AppState(actions=[ActionDefinition(steps=[step])]).to_dict())
        self.assertEqual(restored.actions[0].steps[0].random_wait_max_ms, 900)

    def test_ab_vision_confirmation_and_random_wait_are_serialized(self) -> None:
        step = FlowStep(kind="action", action_id="A", random_wait_min_ms=300, random_wait_max_ms=900)
        workflow = WorkflowDefinition(mode=FlowMode.AB, secondary_vision_preset_id="vision-confirm")
        restored = AppState.from_dict(AppState(workflows=[workflow, WorkflowDefinition(mode=FlowMode.CUSTOM, root_step=FlowStep(kind="group", children=[step]))]).to_dict())
        self.assertEqual(restored.workflows[0].secondary_vision_preset_id, "vision-confirm")
        self.assertEqual(restored.workflows[1].root_step.children[0].random_wait_max_ms, 900)

    def test_fishing_settings_are_persisted_and_clamped(self) -> None:
        state = AppState.from_dict({"fishing": {"color_a_hex": "#00FF00", "color_b_hex": "#0000FF", "color_pick_hotkey": "F6", "detection_hotkey": "F7", "hue_tolerance": 200, "scan_interval_ms": 1, "gain": 4, "max_step": 200}})
        self.assertEqual(state.fishing, FishingSettings(color_a_hex="#00FF00", color_b_hex="#0000FF", color_pick_hotkey="F6", detection_hotkey="F7", hue_tolerance=90, scan_interval_ms=50, gain=1.0, max_step=120))
        self.assertEqual(state.to_dict()["fishing"]["color_a_hex"], "#00FF00")

    def test_fishing_template_settings_are_persisted(self) -> None:
        state = AppState.from_dict({"fishing": {"a_source": "template", "template_a_path": "data/fishing_templates/a.png", "template_threshold": 2, "hide_during_capture": False}})
        self.assertEqual(state.fishing.a_source, "template")
        self.assertFalse(state.fishing.hide_during_capture)
        self.assertEqual(state.fishing.template_a_path, "data/fishing_templates/a.png")
        self.assertEqual(state.fishing.template_threshold, 1.0)

    def test_fishing_preset_and_flow_step_are_serialized(self) -> None:
        preset = FishingPreset(name="金色鱼", settings=FishingSettings(color_a_hex="#FFD000"))
        state = AppState(fishing_presets=[preset])
        restored = AppState.from_dict(state.to_dict())
        self.assertEqual(restored.fishing_presets[0].name, "金色鱼")
        step = CustomFlowStep.from_dict({"kind": CustomStepKind.FISHING, "fishing_preset_id": preset.id, "duration_ms": 5_000})
        self.assertEqual((step.kind, step.fishing_preset_id, step.duration_ms), (CustomStepKind.FISHING, preset.id, 5_000))

    def test_fishing_vertical_bar_detects_one_pixel_wide_component(self) -> None:
        import cv2
        import numpy as np
        mask = np.zeros((24, 24), dtype=np.uint8)
        mask[3:21, 11] = 255
        self.assertEqual(FishingService._vertical_bar_center(cv2, mask, 8), (11, 12, 18))

    def test_fishing_horizontal_a_bar_merges_segments_split_by_b(self) -> None:
        import cv2
        import numpy as np
        mask = np.zeros((30, 80), dtype=np.uint8)
        mask[10:16, 10:38] = 255
        mask[10:16, 42:70] = 255
        result = FishingService._horizontal_bar_component(cv2, mask, 20)
        self.assertEqual(result, (40, 13, 336, 10, 10, 60, 6))

    def test_fishing_vertical_bar_must_be_inside_a_range(self) -> None:
        import cv2
        import numpy as np
        mask = np.zeros((30, 30), dtype=np.uint8)
        mask[2:26, 3] = 255
        mask[8:20, 16] = 255
        self.assertEqual(FishingService._vertical_bar_center(cv2, mask, 8, (10, 5, 12, 20)), (16, 14, 12))

    def test_fishing_ab_direction_respects_dead_zone(self) -> None:
        self.assertEqual(FishingService.horizontal_direction(100, 85, 10), -1)
        self.assertEqual(FishingService.horizontal_direction(100, 115, 10), 1)
        self.assertEqual(FishingService.horizontal_direction(100, 108, 10), 0)

    def test_fishing_color_is_converted_to_opencv_hue(self) -> None:
        self.assertEqual(FishingService._hue_from_hex("#FF0000"), 0)
        self.assertEqual(FishingService._hue_from_hex("#00FF00"), 60)


if __name__ == "__main__":
    unittest.main()
