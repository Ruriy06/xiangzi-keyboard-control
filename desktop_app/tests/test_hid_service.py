import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hid_control import hid_service


def _entry(path, usage_page, usage):
    """构造一条 hid.enumerate() 返回的记录（字段与真实 hidapi 对齐）。"""
    return {
        "path": path,
        "vendor_id": hid_service.VENDOR_ID,
        "product_id": hid_service.PRODUCT_ID,
        "product_string": "USB Keyboard",
        "interface_number": 0,
        "usage_page": usage_page,
        "usage": usage,
    }


class FakeHid:
    """只提供 available_ports() 用到的 enumerate()。"""

    def __init__(self, entries):
        self._entries = entries

    def enumerate(self, vid=None, pid=None):
        return list(self._entries)


class HidServicePortsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._real_hid = hid_service.hid

    def tearDown(self) -> None:
        hid_service.hid = self._real_hid

    def test_available_ports_skips_mouse_and_keyboard_collections(self) -> None:
        """最终固件是「单接口 + 3 个顶层集合」，只有厂商集合才是本通道。

        三个集合的 interface_number 都是 0，仅靠 VID/PID 无法区分；若不按
        usage_page 过滤，下拉框里会出现鼠标和键盘两个假设备，自动选择还会打开
        鼠标集合导致下行 Feature report 直接失败。
        """
        vendor_path = b"path-vendor-col03"
        hid_service.hid = FakeHid(
            [
                _entry(b"path-mouse-col01", 0x0001, 0x0002),
                _entry(b"path-keyboard-col02", 0x0001, 0x0006),
                _entry(vendor_path, hid_service.VENDOR_USAGE_PAGE, 0x0001),
            ]
        )

        ports = hid_service.HidService.available_ports()

        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0].device, os.fsdecode(vendor_path))

    def test_available_ports_returns_empty_without_hidapi(self) -> None:
        hid_service.hid = None
        self.assertEqual(hid_service.HidService.available_ports(), [])

    def test_available_ports_skips_vendor_entry_without_path(self) -> None:
        hid_service.hid = FakeHid([_entry(b"", hid_service.VENDOR_USAGE_PAGE, 0x0001)])
        self.assertEqual(hid_service.HidService.available_ports(), [])

    def test_available_ports_survives_enumerate_failure(self) -> None:
        class BrokenHid:
            def enumerate(self, vid=None, pid=None):
                raise OSError("hidapi 未就绪")

        hid_service.hid = BrokenHid()
        self.assertEqual(hid_service.HidService.available_ports(), [])


if __name__ == "__main__":
    unittest.main()
