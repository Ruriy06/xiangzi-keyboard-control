from __future__ import annotations

import colorsys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .models import FishingSettings


class FishingService(QObject):
    """仅负责在指定屏幕区域检测 A/B 色块；输入响应由主窗口决定。"""

    status_changed = Signal(str)
    target_updated = Signal(int, int, int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, settings: FishingSettings, capture_region: dict[str, int] | None = None) -> bool:
        if self.is_running:
            self.status_changed.emit("钓鱼识别已在运行")
            return False
        if not settings.a_material_id or not settings.b_material_id or not settings.region_material_id:
            self.status_changed.emit("请先在素材库选择 A、B 目标和观察区域素材")
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, args=(settings, capture_region), name="opencv-fishing-color", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        self.status_changed.emit("钓鱼识别已关闭")

    @staticmethod
    def _hue_from_hex(color_hex: str) -> int:
        red = int(color_hex[1:3], 16) / 255
        green = int(color_hex[3:5], 16) / 255
        blue = int(color_hex[5:7], 16) / 255
        hue, _, _ = colorsys.rgb_to_hsv(red, green, blue)
        return round(hue * 179)

    @staticmethod
    def _mask_for_hue(cv2, np, hsv, hue: int, tolerance: int):
        lower_hue, upper_hue = hue - tolerance, hue + tolerance
        if lower_hue < 0:
            return cv2.bitwise_or(
                cv2.inRange(hsv, np.array([0, 80, 80]), np.array([upper_hue, 255, 255])),
                cv2.inRange(hsv, np.array([180 + lower_hue, 80, 80]), np.array([179, 255, 255])),
            )
        if upper_hue > 179:
            return cv2.bitwise_or(
                cv2.inRange(hsv, np.array([lower_hue, 80, 80]), np.array([179, 255, 255])),
                cv2.inRange(hsv, np.array([0, 80, 80]), np.array([upper_hue - 180, 255, 255])),
            )
        return cv2.inRange(hsv, np.array([lower_hue, 80, 80]), np.array([upper_hue, 255, 255]))

    @staticmethod
    def horizontal_direction(a_x: int, b_x: int, dead_zone: int) -> int:
        """返回 -1 表示 B 在 A 左侧、1 表示 B 在 A 右侧、0 表示居中。"""
        offset = b_x - a_x
        if abs(offset) <= dead_zone:
            return 0
        return -1 if offset < 0 else 1

    @staticmethod
    def _largest_component(cv2, mask, minimum_area: int) -> tuple[int, int, int, int, int, int, int] | None:
        """返回最大连通色块的中心、像素数与完整矩形范围。"""
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates = [(int(stats[index, cv2.CC_STAT_AREA]), index) for index in range(1, count) if int(stats[index, cv2.CC_STAT_AREA]) >= minimum_area]
        if not candidates:
            return None
        area, index = max(candidates)
        return (
            round(float(centroids[index][0])), round(float(centroids[index][1])), area,
            int(stats[index, cv2.CC_STAT_LEFT]), int(stats[index, cv2.CC_STAT_TOP]),
            int(stats[index, cv2.CC_STAT_WIDTH]), int(stats[index, cv2.CC_STAT_HEIGHT]),
        )

    @staticmethod
    def _horizontal_bar_component(cv2, mask, minimum_pixels: int) -> tuple[int, int, int, int, int, int, int] | None:
        """合并同一水平带且被短竖线切开的绿色 A 长方形。"""
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        components = []
        for index in range(1, count):
            pixels = int(stats[index, cv2.CC_STAT_AREA])
            width = int(stats[index, cv2.CC_STAT_WIDTH])
            height = int(stats[index, cv2.CC_STAT_HEIGHT])
            if pixels >= minimum_pixels and width >= height:
                components.append((int(stats[index, cv2.CC_STAT_LEFT]), int(stats[index, cv2.CC_STAT_TOP]), width, height, pixels))
        if not components:
            return None
        components.sort()
        groups: list[list[tuple[int, int, int, int, int]]] = []
        for component in components:
            left, top, width, height, _pixels = component
            if not groups:
                groups.append([component])
                continue
            group = groups[-1]
            group_left = min(item[0] for item in group)
            group_top = min(item[1] for item in group)
            group_right = max(item[0] + item[2] for item in group)
            group_bottom = max(item[1] + item[3] for item in group)
            vertical_overlap = max(0, min(top + height, group_bottom) - max(top, group_top))
            required_overlap = min(height, group_bottom - group_top) * 0.6
            gap = left - group_right
            allowed_gap = max(24, (group_bottom - group_top) * 2)
            if vertical_overlap >= required_overlap and gap <= allowed_gap:
                group.append(component)
            else:
                groups.append([component])
        best = max(groups, key=lambda group: sum(item[4] for item in group))
        left = min(item[0] for item in best)
        top = min(item[1] for item in best)
        right = max(item[0] + item[2] for item in best)
        bottom = max(item[1] + item[3] for item in best)
        width, height = right - left, bottom - top
        return left + width // 2, top + height // 2, sum(item[4] for item in best), left, top, width, height

    @staticmethod
    def _largest_center(cv2, mask, minimum_area: int) -> tuple[int, int, int] | None:
        component = FishingService._largest_component(cv2, mask, minimum_area)
        return component[:3] if component else None

    @staticmethod
    def _vertical_bar_center(cv2, mask, minimum_pixels: int, container: tuple[int, int, int, int] | None = None) -> tuple[int, int, int] | None:
        """优先选择容器内部窄而高的组件，可检测一像素宽的 B 竖条。"""
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates: list[tuple[float, int, int]] = []
        for index in range(1, count):
            pixels = int(stats[index, cv2.CC_STAT_AREA])
            width = max(1, int(stats[index, cv2.CC_STAT_WIDTH]))
            height = int(stats[index, cv2.CC_STAT_HEIGHT])
            center_x, center_y = float(centroids[index][0]), float(centroids[index][1])
            if pixels < minimum_pixels or height < width:
                continue
            if container is not None:
                left, top, container_width, container_height = container
                if not (left <= center_x <= left + container_width and top <= center_y <= top + container_height):
                    continue
            score = pixels * (height / width)
            candidates.append((score, pixels, index))
        if not candidates:
            return None
        _score, pixels, index = max(candidates)
        return round(float(centroids[index][0])), round(float(centroids[index][1])), pixels

    @staticmethod
    def _load_template(cv2, np, path: str):
        if not path or not Path(path).is_file():
            return None
        try:
            return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        except OSError:
            return None

    @staticmethod
    def _template_center(cv2, gray, template, threshold: float) -> tuple[int, int, int, int, int, int, int] | None:
        if template is None or gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
            return None
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < threshold:
            return None
        height, width = template.shape[:2]
        return location[0] + width // 2, location[1] + height // 2, width * height, location[0], location[1], width, height

    def _run(self, settings: FishingSettings, capture_region: dict[str, int] | None) -> None:
        try:
            import cv2
            import mss
            import numpy as np
        except ImportError:
            self.status_changed.emit("缺少 OpenCV 识别依赖；请安装 requirements.txt 中的 opencv-python 和 mss")
            return
        try:
            hue_a = self._hue_from_hex(settings.color_a_hex)
            hue_b = self._hue_from_hex(settings.color_b_hex)
        except (TypeError, ValueError):
            self.status_changed.emit("A/B 色块颜色格式无效")
            return
        template_a = self._load_template(cv2, np, settings.template_a_path) if settings.a_source == "template" else None
        template_b = self._load_template(cv2, np, settings.template_b_path) if settings.b_source == "template" else None
        if settings.a_source == "template" and template_a is None:
            self.status_changed.emit("无法读取 A 图片模板")
            return
        if settings.b_source == "template" and template_b is None:
            self.status_changed.emit("无法读取 B 图片模板")
            return
        try:
            with mss.mss() as capture:
                monitor = capture_region or (capture.monitors[1] if len(capture.monitors) > 1 else None)
                if not monitor:
                    self.status_changed.emit("未找到可截图的主显示器")
                    return
                self.status_changed.emit("钓鱼识别运行中：正在检测 A/B 色块")
                while not self._stop_event.is_set():
                    frame = np.asarray(capture.grab(monitor))
                    bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
                    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                    mask_a = cv2.morphologyEx(self._mask_for_hue(cv2, np, hsv, hue_a, settings.hue_tolerance), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                    # B 可能是一两像素宽的竖条，不能做开运算，否则会被直接擦掉。
                    mask_b = self._mask_for_hue(cv2, np, hsv, hue_b, settings.hue_tolerance)
                    target_a = self._template_center(cv2, gray, template_a, settings.template_threshold) if settings.a_source == "template" else self._horizontal_bar_component(cv2, mask_a, settings.min_area)
                    target_b = self._template_center(cv2, gray, template_b, settings.template_threshold) if settings.b_source == "template" else self._vertical_bar_center(cv2, mask_b, settings.b_min_area, target_a[3:] if target_a else None)
                    if target_a and target_b:
                        left, top, width, height = target_a[3:]
                        if not (left <= target_b[0] <= left + width and top <= target_b[1] <= top + height):
                            target_b = None
                    if target_a and target_b:
                        self.target_updated.emit(target_a[0] + monitor["left"], target_a[1] + monitor["top"], target_a[2], target_b[0] + monitor["left"], target_b[1] + monitor["top"], target_b[2])
                    else:
                        self.target_updated.emit(-1, -1, 0, -1, -1, 0)
                    self._stop_event.wait(settings.scan_interval_ms / 1000)
        except Exception as error:
            self.status_changed.emit(f"钓鱼识别异常：{error}")
