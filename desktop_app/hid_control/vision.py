from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .models import VisionRule, VisionSettings
from .window_capture import window_by_title


class VisionService(QObject):
    """独立运行的 OpenCV 模板识别服务，不执行任何输入操作。"""

    status_changed = Signal(str)
    match_updated = Signal(float, int, int, int, int, int, int)
    rule_matched = Signal(str, float, int, int, int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, settings: VisionSettings) -> bool:
        if self.is_running:
            self.status_changed.emit("模板识别已在运行")
            return False
        if not settings.target_material_id:
            self.status_changed.emit("请先在素材库选择识别颜色或图片模板")
            return False
        if settings.source == "template":
            if not settings.template_path:
                self.status_changed.emit("请选择要识别的模板图片后再启用模板识别")
                return False
            if not Path(settings.template_path).is_file():
                self.status_changed.emit("模板图片不存在，请重新选择")
                return False
        elif len(settings.color_hex) != 7 or not settings.color_hex.startswith("#"):
            self.status_changed.emit("识别颜色无效，请重新选择颜色素材")
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, args=(settings,), name="opencv-template-vision", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        self.status_changed.emit("模板识别已关闭")

    def _run(self, settings: VisionSettings) -> None:
        try:
            import cv2
            import mss
            import numpy as np
        except ImportError:
            self.status_changed.emit("缺少 OpenCV 识别依赖；请安装 requirements.txt 中的 opencv-python 和 mss")
            return

        if settings.source == "color":
            self._run_color(settings, cv2, mss, np)
            return
        rules = [rule for rule in settings.rules if rule.enabled and rule.template_path]
        if not rules and settings.template_path:
            rules = [VisionRule(name="旧模板识别规则", template_path=settings.template_path, threshold=settings.threshold, scan_interval_ms=settings.scan_interval_ms, action_mode=settings.action_mode, action_id=settings.action_id)]
        templates: list[tuple[VisionRule, object, int, int]] = []
        for rule in rules:
            try:
                template = cv2.imdecode(np.fromfile(rule.template_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            except OSError:
                template = None
            if template is None:
                self.status_changed.emit(f"无法读取规则“{rule.name}”的模板图片")
                continue
            height, width = template.shape[:2]
            templates.append((rule, template, width, height))
        if not templates:
            self.status_changed.emit("没有可用的启用识别规则，请选择有效模板图片")
            return
        try:
            with mss.mss() as capture:
                if len(capture.monitors) < 2:
                    self.status_changed.emit("未找到可截图的主显示器")
                    return
                monitor = capture.monitors[1]
                window = window_by_title(settings.window_title) if settings.window_title else None
                if window:
                    monitor = {"left": window.left + settings.region_x, "top": window.top + settings.region_y, "width": settings.region_width or window.width, "height": settings.region_height or window.height}
                elif settings.region_width and settings.region_height:
                    monitor = {"left": monitor["left"] + settings.region_x, "top": monitor["top"] + settings.region_y, "width": settings.region_width, "height": settings.region_height}
                self.status_changed.emit("AI 识别运行中：正在监测目标范围")
                fired: set[str] = set()
                last_trigger: dict[str, float] = {}
                interval_ms = min(rule.scan_interval_ms for rule, _template, _width, _height in templates)
                while not self._stop_event.is_set():
                    frame = np.asarray(capture.grab(monitor))
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    for rule, template, template_width, template_height in templates:
                        if gray.shape[0] < template_height or gray.shape[1] < template_width:
                            continue
                        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                        _, score, _, location = cv2.minMaxLoc(result)
                        center_x = monitor["left"] + location[0] + template_width // 2
                        center_y = monitor["top"] + location[1] + template_height // 2
                        self.match_updated.emit(float(score), center_x, center_y, monitor["left"], monitor["top"], monitor["width"], monitor["height"])
                        if score < rule.threshold:
                            if rule.trigger_mode == "once":
                                fired.discard(rule.id)
                            continue
                        now = __import__("time").monotonic()
                        if rule.trigger_mode == "once" and rule.id in fired:
                            continue
                        if now - last_trigger.get(rule.id, 0.0) < rule.cooldown_ms / 1000:
                            continue
                        fired.add(rule.id)
                        last_trigger[rule.id] = now
                        self.rule_matched.emit(rule.id, float(score), center_x, center_y, monitor["left"], monitor["top"], monitor["width"], monitor["height"])
                    self._stop_event.wait(interval_ms / 1000)
        except Exception as error:
            self.status_changed.emit(f"模板识别异常：{error}")

    def _run_color(self, settings: VisionSettings, cv2, mss, np) -> None:
        try:
            with mss.mss() as capture:
                monitor = capture.monitors[1]
                window = window_by_title(settings.window_title) if settings.window_title else None
                if window:
                    monitor = {"left": window.left + settings.region_x, "top": window.top + settings.region_y, "width": settings.region_width or window.width, "height": settings.region_height or window.height}
                elif settings.region_width and settings.region_height:
                    monitor = {"left": monitor["left"] + settings.region_x, "top": monitor["top"] + settings.region_y, "width": settings.region_width, "height": settings.region_height}
                target = cv2.cvtColor(np.uint8([[[int(settings.color_hex[1:3], 16), int(settings.color_hex[3:5], 16), int(settings.color_hex[5:7], 16)]]]), cv2.COLOR_RGB2HSV)[0][0][0]
                self.status_changed.emit("AI 颜色识别运行中")
                while not self._stop_event.is_set():
                    frame = np.asarray(capture.grab(monitor))
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGRA2HSV)
                    lower = np.array([max(0, int(target) - settings.hue_tolerance), 70, 50])
                    upper = np.array([min(179, int(target) + settings.hue_tolerance), 255, 255])
                    mask = cv2.inRange(hsv, lower, upper)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contour = max(contours, key=cv2.contourArea) if contours else None
                    if contour is not None and cv2.contourArea(contour) >= settings.min_area:
                        moments = cv2.moments(contour)
                        if moments["m00"]:
                            x = monitor["left"] + int(moments["m10"] / moments["m00"])
                            y = monitor["top"] + int(moments["m01"] / moments["m00"])
                            self.match_updated.emit(1.0, x, y, monitor["left"], monitor["top"], monitor["width"], monitor["height"])
                    self._stop_event.wait(settings.scan_interval_ms / 1000)
        except Exception as error:
            self.status_changed.emit(f"颜色识别异常：{error}")
