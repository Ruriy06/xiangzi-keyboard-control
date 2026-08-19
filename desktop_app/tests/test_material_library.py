import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hid_control.models import AppState, FishingSettings, MaterialAsset, VisionSettings
from hid_control.ui.vision_page import VisionPage


class MaterialLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_recognition_settings_migrate_to_material_references(self) -> None:
        state = AppState.from_dict({
            "vision": {
                "source": "color",
                "color_hex": "#12AB34",
                "window_title": "游戏窗口",
                "region_x": 10,
                "region_y": 20,
                "region_width": 300,
                "region_height": 200,
            },
            "vision_presets": [{
                "id": "vision-preset",
                "name": "旧识图预设",
                "settings": {"source": "color", "color_hex": "#102030"},
            }],
            "fishing": {
                "color_a_hex": "#FFD000",
                "color_b_hex": "#00A0FF",
                "window_title": "游戏窗口",
                "region_x": 10,
                "region_y": 20,
                "region_width": 300,
                "region_height": 200,
            },
        })

        self.assertTrue(state.vision.target_material_id)
        self.assertTrue(state.vision.region_material_id)
        self.assertTrue(state.vision_presets[0].settings.target_material_id)
        self.assertTrue(state.fishing.a_material_id)
        self.assertTrue(state.fishing.b_material_id)
        self.assertTrue(state.fishing.region_material_id)
        self.assertEqual({material.kind for material in state.materials}, {"color", "region"})

    def test_material_library_lists_regions_and_flows_store_selected_ids(self) -> None:
        color = MaterialAsset(id="color", name="绿色", kind="color", color_hex="#00FF00")
        template = MaterialAsset(id="template", name="图标", kind="template", image_path="missing.png")
        region = MaterialAsset(id="region", name="观察范围", kind="region", image_path="missing-region.png", window_title="游戏", region_x=1, region_y=2, region_width=30, region_height=40)
        page = VisionPage()
        page.set_data([], VisionSettings(), FishingSettings(), materials=[color, template, region])

        page.material_category_filter.setCurrentIndex(page.material_category_filter.findData("region"))
        self.assertEqual(page.material_list.count(), 1)
        self.assertEqual(page.material_list.item(0).data(256), "region")
        page.material_category_filter.setCurrentIndex(page.material_category_filter.findData(""))
        page.material_search.setText("绿色")
        self.assertEqual(page.material_list.count(), 1)
        self.assertGreaterEqual(len(page._material_thumbnail_cache), 3)
        page._materials = [color]
        page._refresh_materials()
        self.assertEqual(set(page._material_thumbnail_cache), {page._material_thumbnail_key(color)})
        page._materials = [color, template, region]
        page._refresh_materials()

        page.template_target_material.setCurrentIndex(page.template_target_material.findData("template"))
        self.assertTrue(page.template_color_parameters.isHidden())
        self.assertFalse(page.template_template_parameters.isHidden())
        page.template_region_material.setCurrentIndex(page.template_region_material.findData("region"))
        page.fishing_a_material.setCurrentIndex(page.fishing_a_material.findData("color"))
        page.fishing_b_material.setCurrentIndex(page.fishing_b_material.findData("template"))
        page.fishing_region_material.setCurrentIndex(page.fishing_region_material.findData("region"))

        vision = page._template_settings_value()
        fishing = page._fishing_settings_value()
        self.assertEqual((vision.target_material_id, vision.region_material_id), ("template", "region"))
        self.assertEqual((fishing.a_material_id, fishing.b_material_id, fishing.region_material_id), ("color", "template", "region"))


if __name__ == "__main__":
    unittest.main()
