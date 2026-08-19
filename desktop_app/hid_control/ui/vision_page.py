from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

from ..models import ActionDefinition, ActionStep, FishingPreset, FishingSettings, MaterialAsset, MaterialCaptureSettings, VisionPreset, VisionRule, VisionSettings
from .step_input import StepInputPanel
from ..window_capture import list_visible_windows


class ScreenColorPicker(QWidget):
    color_picked = Signal(str)
    picker_closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        screen = QGuiApplication.primaryScreen()
        self._image = screen.grabWindow(0).toImage() if screen else QPixmap().toImage()
        self._pixmap = QPixmap.fromImage(self._image)
        if screen:
            self.setGeometry(screen.geometry())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.fillRect(0, 0, self.width(), 38, QColor(0, 0, 0, 170))
        painter.setPen(QColor("white"))
        painter.drawText(12, 25, "点击屏幕上的目标色块以吸取颜色；按 Escape 取消")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._image.isNull():
            return
        x = min(self._image.width() - 1, max(0, round(event.position().x() * self._image.width() / self.width())))
        y = min(self._image.height() - 1, max(0, round(event.position().y() * self._image.height() / self.height())))
        self.color_picked.emit(self._image.pixelColor(x, y).name().upper())
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event) -> None:
        self.picker_closed.emit()
        super().closeEvent(event)


class WindowRegionPicker(QWidget):
    region_selected = Signal(int, int, int, int)
    picker_closed = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        try:
            import mss
            import numpy as np
            with mss.mss() as capture:
                frame = np.asarray(capture.grab({"left": window.left, "top": window.top, "width": window.width, "height": window.height}))
            self._image = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format.Format_ARGB32).copy()
        except Exception:
            self._image = QImage()
        self._pixmap = QPixmap.fromImage(self._image)
        self._start: QPoint | None = None
        self._selection = QRect()
        self.resize(min(1200, window.width), min(800, window.height))
        self.setWindowTitle("拖拽选择钓鱼识别区域")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        if not self._selection.isNull():
            painter.setPen(QColor("#00E5FF"))
            painter.drawRect(self._selection)
        painter.fillRect(0, 0, self.width(), 28, QColor(0, 0, 0, 170))
        painter.setPen(QColor("white"))
        painter.drawText(10, 20, "拖拽选择识别区域；按 Escape 取消")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect(self._start, self._start)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start:
            self._selection = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._start or self._selection.width() < 3 or self._selection.height() < 3:
            return
        x = round(self._selection.x() * self._image.width() / self.width())
        y = round(self._selection.y() * self._image.height() / self.height())
        width = round(self._selection.width() * self._image.width() / self.width())
        height = round(self._selection.height() * self._image.height() / self.height())
        self.region_selected.emit(x, y, width, height)
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event) -> None:
        self.picker_closed.emit()
        super().closeEvent(event)


class VisionPage(QWidget):
    template_settings_changed = Signal(VisionSettings)
    template_enabled_changed = Signal(bool)
    fishing_settings_changed = Signal(FishingSettings)
    fishing_enabled_changed = Signal(bool)
    fishing_presets_changed = Signal(list)
    materials_changed = Signal(list)
    material_capture_settings_changed = Signal(MaterialCaptureSettings)
    vision_presets_changed = Signal(list)
    def __init__(self) -> None:
        super().__init__()
        self._actions: list[ActionDefinition] = []
        self._vision_presets: list[VisionPreset] = []
        self._fishing_presets: list[FishingPreset] = []
        self._materials: list[MaterialAsset] = []
        self._material_thumbnail_cache: dict[str, QPixmap] = {}
        self._material_capture = MaterialCaptureSettings()
        self._template_settings = VisionSettings()
        self._template_rules: list[VisionRule] = []
        self._fishing_settings = FishingSettings()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scrollable_tab(self._build_materials_tab()), "素材库")
        self.tabs.addTab(self._scrollable_tab(self._build_template_tab()), "自定义AI识别")
        self.tabs.addTab(self._scrollable_tab(self._build_fishing_tab()), "钓鱼")

        layout = QVBoxLayout(self)
        title = QLabel("AI识别")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("模板识别和钓鱼追踪默认关闭。模板识别可按规则执行一次动作；钓鱼仅根据色块发送相对移动，不执行点击或按键。"))
        layout.addWidget(self.tabs, 1)

    @staticmethod
    def _scrollable_tab(content: QWidget) -> QScrollArea:
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _build_materials_tab(self) -> QWidget:
        tab = QWidget()
        self.material_category_filter = QComboBox()
        self.material_category_filter.addItem("全部素材", "")
        self.material_category_filter.addItem("颜色", "color")
        self.material_category_filter.addItem("图片模板", "template")
        self.material_category_filter.addItem("识别区域", "region")
        self.material_search = QLineEdit()
        self.material_search.setPlaceholderText("搜索名称、备注或类型")
        self.material_list = QListWidget()
        self.material_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.material_list.setIconSize(QSize(96, 72))
        self.material_list.setGridSize(QSize(128, 120))
        self.material_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.material_list.setWordWrap(True)
        self.material_list.setSpacing(6)
        self.material_preview = QLabel("选择素材后在此预览")
        self.material_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.material_preview.setMinimumSize(360, 240)
        self.material_name = QLineEdit()
        self.material_note = QLineEdit()
        self.material_kind = QLabel("-")
        self.material_save = QPushButton("保存名称和备注")
        self.material_delete = QPushButton("删除素材记录")
        self.material_list.currentRowChanged.connect(self._select_material)
        self.material_save.clicked.connect(self._save_material)
        self.material_delete.clicked.connect(self._delete_material)
        detail = QFormLayout()
        detail.addRow("类型", self.material_kind)
        detail.addRow("名称", self.material_name)
        detail.addRow("备注", self.material_note)
        detail.addRow(self.material_save)
        detail.addRow(self.material_delete)
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.addWidget(self.material_preview, 1); right_layout.addLayout(detail)
        self.material_window_combo = QComboBox()
        self.material_refresh_windows = QPushButton("刷新窗口")
        self.material_hide_during_capture = QCheckBox("采集时隐藏软件")
        self.material_color_hotkey = QLineEdit(); self.material_color_hotkey.setPlaceholderText("吸色快捷键，例如 F6")
        self.material_template_hotkey = QLineEdit(); self.material_template_hotkey.setPlaceholderText("截取模板快捷键")
        self.material_region_hotkey = QLineEdit(); self.material_region_hotkey.setPlaceholderText("截取区域快捷键")
        self.material_pick_color = QPushButton("● 吸色")
        self.material_import_template = QPushButton("▣ 导入本地图片")
        self.material_capture_template = QPushButton("▣ 从窗口截取模板")
        self.material_capture_region = QPushButton("▤ 从窗口框选区域")
        self.material_save_capture = QPushButton("保存素材采集设置")
        self.material_category_filter.currentIndexChanged.connect(self._refresh_materials)
        self.material_search.textChanged.connect(self._refresh_materials)
        self.material_refresh_windows.clicked.connect(self._refresh_material_capture_windows)
        self.material_pick_color.clicked.connect(self.capture_material_color)
        self.material_import_template.clicked.connect(self.import_material_template)
        self.material_capture_template.clicked.connect(self.capture_material_template)
        self.material_capture_region.clicked.connect(self.capture_material_region)
        self.material_save_capture.clicked.connect(self._emit_material_capture_settings)
        for widget in (self.material_color_hotkey, self.material_template_hotkey, self.material_region_hotkey):
            widget.editingFinished.connect(self._emit_material_capture_settings)
        self.material_window_combo.currentIndexChanged.connect(self._emit_material_capture_settings)
        self.material_hide_during_capture.toggled.connect(self._emit_material_capture_settings)
        capture_form = QFormLayout()
        window_row = QWidget(); window_layout = QHBoxLayout(window_row); window_layout.setContentsMargins(0, 0, 0, 0); window_layout.addWidget(self.material_window_combo, 1); window_layout.addWidget(self.material_refresh_windows)
        capture_form.addRow("采集目标窗口", window_row)
        capture_form.addRow(self.material_hide_during_capture)
        capture_form.addRow("吸色快捷键", self.material_color_hotkey)
        capture_form.addRow("截取模板快捷键", self.material_template_hotkey)
        capture_form.addRow("截取区域快捷键", self.material_region_hotkey)
        capture_buttons = QHBoxLayout(); capture_buttons.addWidget(self.material_pick_color); capture_buttons.addWidget(self.material_import_template); capture_buttons.addWidget(self.material_capture_template); capture_buttons.addWidget(self.material_capture_region)
        capture_form.addRow(capture_buttons); capture_form.addRow(self.material_save_capture)
        capture_group = QGroupBox("素材采集与快捷键（统一保存）"); capture_group.setLayout(capture_form)
        list_panel = QWidget(); list_layout = QVBoxLayout(list_panel); list_layout.setContentsMargins(0, 0, 0, 0); list_layout.setSpacing(6); list_layout.addWidget(self.material_search); list_layout.addWidget(self.material_category_filter); list_layout.addWidget(self.material_list, 1)
        body = QHBoxLayout(); body.addWidget(list_panel, 1); body.addWidget(right, 2)
        layout = QVBoxLayout(tab); layout.addWidget(QLabel("颜色、图片模板和识别区域均在此集中创建、导入、分类和预览；AI 识别与钓鱼页面只需选择已保存素材。")); layout.addWidget(capture_group); layout.addLayout(body, 1)
        return tab

    def _refresh_materials(self) -> None:
        selected_id = ""
        current = self.material_list.currentItem()
        if current is not None:
            selected_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        active_thumbnail_keys = {self._material_thumbnail_key(material) for material in self._materials}
        self._material_thumbnail_cache = {key: pixmap for key, pixmap in self._material_thumbnail_cache.items() if key in active_thumbnail_keys}
        category = str(self.material_category_filter.currentData() or "")
        query = self.material_search.text().strip().casefold()
        self.material_list.blockSignals(True)
        self.material_list.clear()
        selected_row = -1
        icons = {"color": "●", "template": "▣", "region": "▤"}
        for material in self._materials:
            if category and material.kind != category:
                continue
            searchable = f"{material.name} {material.note} {material.kind}".casefold()
            if query and query not in searchable:
                continue
            item = QListWidgetItem(f"{icons.get(material.kind, '·')} {material.name}")
            item.setData(Qt.ItemDataRole.UserRole, material.id)
            item.setIcon(QIcon(self._material_thumbnail(material)))
            item.setToolTip(f"{material.name}\n{self._material_summary(material)}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.material_list.addItem(item)
            if material.id == selected_id:
                selected_row = self.material_list.count() - 1
        self.material_list.blockSignals(False)
        if selected_row >= 0:
            self.material_list.setCurrentRow(selected_row)
        elif self.material_list.count():
            self.material_list.setCurrentRow(0)
        else:
            self.material_preview.setText("当前分类没有素材")
            self.material_preview.setPixmap(QPixmap())

    @staticmethod
    def _material_thumbnail_key(material: MaterialAsset) -> str:
        return f"{material.id}:{material.kind}:{material.image_path}:{material.color_hex}"

    def _material_thumbnail(self, material: MaterialAsset) -> QPixmap:
        key = self._material_thumbnail_key(material)
        cached = self._material_thumbnail_cache.get(key)
        if cached is not None:
            return cached
        thumbnail = QPixmap(96, 72)
        if material.kind == "color":
            thumbnail.fill(QColor(material.color_hex or "#94a3b8"))
        else:
            source = QPixmap(material.image_path)
            if source.isNull():
                thumbnail.fill(QColor("#e2e8f0"))
                painter = QPainter(thumbnail)
                painter.setPen(QColor("#64748b"))
                painter.drawText(thumbnail.rect(), Qt.AlignmentFlag.AlignCenter, "图片缺失")
                painter.end()
            else:
                thumbnail.fill(QColor("#f8fafc"))
                painter = QPainter(thumbnail)
                scaled = source.scaled(thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap((thumbnail.width() - scaled.width()) // 2, (thumbnail.height() - scaled.height()) // 2, scaled)
                painter.end()
        self._material_thumbnail_cache[key] = thumbnail
        return thumbnail

    @staticmethod
    def _material_summary(material: MaterialAsset) -> str:
        if material.kind == "color":
            return material.color_hex
        if material.kind == "region":
            return f"区域 {material.region_width} × {material.region_height} · {material.window_title or '主屏幕'}"
        return f"模板 · {Path(material.image_path).name}" if Path(material.image_path).is_file() else "图片文件不存在"

    def _refresh_material_references(self, template: VisionSettings | None = None, fishing: FishingSettings | None = None) -> None:
        template = template or self._template_settings
        fishing = fishing or self._fishing_settings
        target_assets = [item for item in self._materials if item.kind in {"color", "template"}]
        region_assets = [item for item in self._materials if item.kind == "region"]
        for combo, assets, selected, placeholder in (
            (self.template_target_material, target_assets, template.target_material_id, "请选择识别素材"),
            (self.template_region_material, region_assets, template.region_material_id, "使用整个目标窗口或主屏幕"),
            (self.fishing_a_material, target_assets, fishing.a_material_id, "请选择 A 目标素材"),
            (self.fishing_b_material, target_assets, fishing.b_material_id, "请选择 B 目标素材"),
            (self.fishing_region_material, region_assets, fishing.region_material_id, "请选择观察区域素材"),
        ):
            combo.blockSignals(True); combo.clear(); combo.addItem(placeholder, "")
            for asset in assets: combo.addItem(("● " if asset.kind == "color" else "▣ " if asset.kind == "template" else "▤ ") + asset.name, asset.id)
            combo.setCurrentIndex(max(0, combo.findData(selected))); combo.blockSignals(False)

    def _apply_template_material(self) -> None:
        material = next((item for item in self._materials if item.id == self.template_target_material.currentData()), None)
        if material is None: return
        if material.kind == "color": self.template_source.setCurrentIndex(self.template_source.findData("color")); self._apply_template_color(material.color_hex)
        elif material.kind == "template": self.template_source.setCurrentIndex(self.template_source.findData("template")); self.template_path.setText(material.image_path)
        self._update_template_parameter_visibility()
        self._emit_template_settings()

    def _apply_template_region_material(self) -> None:
        material = next((item for item in self._materials if item.id == self.template_region_material.currentData()), None)
        if material is None: return
        self._template_region = (material.region_x, material.region_y, material.region_width, material.region_height)
        self._refresh_template_windows(); self.template_window_combo.setCurrentIndex(max(0, self.template_window_combo.findData(material.window_title)))
        self._emit_template_settings()

    def _apply_fishing_material(self, target: str) -> None:
        combo = self.fishing_a_material if target == "a" else self.fishing_b_material
        material = next((item for item in self._materials if item.id == combo.currentData()), None)
        if material is None: return
        if material.kind == "color": self._set_fishing_color_button(material.color_hex, target)
        else:
            if target == "a": self._fishing_settings.template_a_path = material.image_path; self.a_source_combo.setCurrentIndex(self.a_source_combo.findData("template"))
            else: self._fishing_settings.template_b_path = material.image_path; self.b_source_combo.setCurrentIndex(self.b_source_combo.findData("template"))
        self._emit_fishing_settings()

    def _apply_fishing_a_material(self) -> None:
        self._apply_fishing_material("a")

    def _apply_fishing_b_material(self) -> None:
        self._apply_fishing_material("b")

    def _apply_fishing_region_material(self) -> None:
        material = next((item for item in self._materials if item.id == self.fishing_region_material.currentData()), None)
        if material is None: return
        self._refresh_windows(material.window_title); self.region_x.setValue(material.region_x); self.region_y.setValue(material.region_y); self.region_width.setValue(material.region_width); self.region_height.setValue(material.region_height)
        self._emit_fishing_settings()

    def _select_material(self, row: int) -> None:
        item = self.material_list.item(row)
        material = next((entry for entry in self._materials if item is not None and entry.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if material is None:
            return
        self.material_name.setText(material.name); self.material_note.setText(material.note); self.material_kind.setText({"color": "颜色素材", "template": "图片模板", "region": "识别区域"}.get(material.kind, material.kind))
        if material.kind == "color":
            self.material_preview.setText(material.color_hex); self.material_preview.setStyleSheet(f"background: {material.color_hex}; font-size: 32px;")
        else:
            pixmap = QPixmap(material.image_path)
            self.material_preview.setStyleSheet("")
            self.material_preview.setPixmap(pixmap.scaled(self.material_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if not pixmap.isNull() else QPixmap())
            if pixmap.isNull(): self.material_preview.setText("素材图片不存在或尚未保存")

    def _save_material(self) -> None:
        row = self.material_list.currentRow(); item = self.material_list.item(row)
        material = next((entry for entry in self._materials if item is not None and entry.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if material is None or material.locked: return
        material.name = self.material_name.text().strip() or material.name; material.note = self.material_note.text().strip()
        self.materials_changed.emit(self._materials); self._refresh_materials(); self.material_list.setCurrentRow(row)

    def _delete_material(self) -> None:
        row = self.material_list.currentRow(); item = self.material_list.item(row)
        material = next((entry for entry in self._materials if item is not None and entry.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if material is None or material.locked: return
        references = [self._template_settings.target_material_id, self._template_settings.region_material_id, self._fishing_settings.a_material_id, self._fishing_settings.b_material_id, self._fishing_settings.region_material_id]
        for preset in self._fishing_presets:
            references.extend([preset.settings.a_material_id, preset.settings.b_material_id, preset.settings.region_material_id])
        if material.id in references:
            self.material_preview.setText("该素材仍被 AI 识别、钓鱼设置或预设引用；请先在对应面板改选其他素材。")
            return
        self._materials.remove(material); self.materials_changed.emit(self._materials); self._refresh_materials(); self._refresh_material_references()

    def _build_template_tab(self) -> QWidget:
        tab = QWidget()
        self.template_enabled = QCheckBox("启用 OpenCV 模板识别")
        self.template_source = QComboBox()
        self.template_source.addItem("图片模板", "template")
        self.template_source.addItem("颜色色块", "color")
        self.template_target_material = QComboBox()
        self.template_region_material = QComboBox()
        self.template_open_materials = QPushButton("在素材库管理和预览")
        self.template_open_materials.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        self.template_path = QLineEdit()
        self.template_path.setReadOnly(True)
        self.template_path.setPlaceholderText("请选择需要监测的模板图片")
        self.template_threshold = QDoubleSpinBox()
        self.template_threshold.setRange(0.1, 1.0)
        self.template_threshold.setSingleStep(0.01)
        self.template_threshold.setDecimals(2)
        self.template_threshold.setValue(0.85)
        self.template_color_button = QPushButton("#00FF00")
        self.template_pick_color_button = QPushButton("吸取识别颜色")
        self.template_hue_tolerance = QSpinBox()
        self.template_hue_tolerance.setRange(1, 90)
        self.template_hue_tolerance.setValue(12)
        self.template_min_area = QSpinBox()
        self.template_min_area.setRange(1, 1_000_000)
        self.template_min_area.setValue(20)
        self.template_color_parameters = QWidget()
        template_color_form = QFormLayout(self.template_color_parameters)
        template_color_form.setContentsMargins(0, 0, 0, 0)
        template_color_form.addRow("颜色容差", self.template_hue_tolerance)
        template_color_form.addRow("最小色块面积", self.template_min_area)
        self.template_template_parameters = QWidget()
        template_image_form = QFormLayout(self.template_template_parameters)
        template_image_form.setContentsMargins(0, 0, 0, 0)
        template_image_form.addRow("最低匹配分数", self.template_threshold)
        self.template_window_combo = QComboBox()
        self.template_refresh_windows = QPushButton("刷新窗口")
        self.template_select_region = QPushButton("拖拽选择识别区域")
        self.template_full_region = QPushButton("使用整个窗口")
        self.template_region_summary = QLabel("识别主屏幕全部区域")
        self.template_region_summary.setWordWrap(True)
        self._template_region = (0, 0, 0, 0)
        self.template_interval = QSpinBox()
        self.template_interval.setRange(100, 60_000)
        self.template_interval.setSingleStep(100)
        self.template_interval.setValue(1_000)
        self.template_interval.setSuffix(" ms")
        self.template_action = QComboBox()
        self.template_action.addItem("仅报告结果", "report")
        self.template_action.addItem("移动到目标中心", "move")
        self.template_action.addItem("移动到目标中心并左键点击一次", "click")
        self.template_action.addItem("执行一次已保存操作", "action_once")
        self.template_action.addItem("执行指定键盘/鼠标动作", "step")
        self.template_action_combo = QComboBox()
        self.template_rule_combo = QComboBox()
        self.template_rule_enabled = QCheckBox("启用当前识别规则")
        self.template_rule_name = QLineEdit()
        self.template_cooldown = QSpinBox()
        self.template_cooldown.setRange(0, 86_400_000)
        self.template_cooldown.setSuffix(" ms")
        self.template_trigger_mode = QComboBox()
        self.template_trigger_mode.addItem("首次匹配后触发一次", "once")
        self.template_trigger_mode.addItem("持续匹配时按冷却重复触发", "repeat")
        self.template_step_input = StepInputPanel(keyboard_height=180)
        self.template_timeout = QSpinBox()
        self.template_timeout.setRange(0, 86_400)
        self.template_timeout.setSpecialValueText("不超时")
        self.template_timeout.setSuffix(" 秒")
        self.vision_preset_combo = QComboBox()
        self.vision_preset_name = QLineEdit(); self.vision_preset_name.setPlaceholderText("识图预设名称")
        self.vision_preset_save = QPushButton("保存为识图预设")
        self.vision_preset_update = QPushButton("更新预设")
        self.vision_preset_delete = QPushButton("删除预设")
        self.vision_preset_lock = QPushButton("锁定预设")
        self.template_status = QLabel("模板识别未启用")
        self.template_status.setWordWrap(True)
        self.template_result = QLabel("尚未执行识别")
        self.template_result.setWordWrap(True)

        choose_button = QPushButton("选择模板图片")
        clear_button = QPushButton("清除模板")
        add_rule_button = QPushButton("新建识别规则")
        delete_rule_button = QPushButton("删除当前规则")
        add_rule_button.clicked.connect(self._add_template_rule)
        delete_rule_button.clicked.connect(self._delete_template_rule)
        self.template_rule_combo.currentIndexChanged.connect(self._load_template_rule)
        self.template_rule_enabled.toggled.connect(self._emit_template_settings)
        self.template_rule_name.editingFinished.connect(self._emit_template_settings)
        self.template_cooldown.valueChanged.connect(self._emit_template_settings)
        self.template_trigger_mode.currentIndexChanged.connect(self._emit_template_settings)
        self.template_step_input.changed.connect(self._emit_template_settings)
        choose_button.clicked.connect(self._choose_template)
        clear_button.clicked.connect(self._clear_template)
        self.template_pick_color_button.clicked.connect(self._pick_template_color)
        self.template_color_button.clicked.connect(self._choose_template_color)
        self.template_refresh_windows.clicked.connect(self._refresh_template_windows)
        self.template_select_region.clicked.connect(self._select_template_region)
        self.template_full_region.clicked.connect(self._use_full_template_region)
        self.template_source.currentIndexChanged.connect(self._template_source_changed)
        self.template_target_material.currentIndexChanged.connect(self._apply_template_material)
        self.template_region_material.currentIndexChanged.connect(self._apply_template_region_material)
        self.template_enabled.toggled.connect(self.template_enabled_changed)
        self.template_threshold.valueChanged.connect(self._emit_template_settings)
        self.template_interval.valueChanged.connect(self._emit_template_settings)
        self.template_action.currentIndexChanged.connect(self._template_action_changed)
        self.template_action_combo.currentIndexChanged.connect(self._emit_template_settings)
        self.template_timeout.valueChanged.connect(self._emit_template_settings)
        self.vision_preset_combo.currentIndexChanged.connect(self._load_selected_vision_preset)
        self.vision_preset_save.clicked.connect(self._save_new_vision_preset)
        self.vision_preset_update.clicked.connect(self._update_selected_vision_preset)
        self.vision_preset_delete.clicked.connect(self._delete_selected_vision_preset)
        self.vision_preset_lock.clicked.connect(self._toggle_selected_vision_preset_lock)

        form = QFormLayout()
        rule_buttons = QHBoxLayout()
        rule_buttons.addWidget(add_rule_button)
        rule_buttons.addWidget(delete_rule_button)
        template_buttons = QHBoxLayout()
        template_buttons.addWidget(choose_button)
        template_buttons.addWidget(QPushButton("从窗口截取模板"))
        self.template_capture_button = template_buttons.itemAt(1).widget()
        self.template_capture_button.clicked.connect(self._capture_template_from_window)
        color_buttons = QHBoxLayout()
        color_buttons.addWidget(self.template_color_button)
        color_buttons.addWidget(self.template_pick_color_button)
        window_buttons = QHBoxLayout()
        window_buttons.addWidget(self.template_window_combo, 1)
        window_buttons.addWidget(self.template_refresh_windows)
        region_buttons = QHBoxLayout()
        region_buttons.addWidget(self.template_select_region)
        region_buttons.addWidget(self.template_full_region)
        form.addRow("识别素材（颜色或模板）", self.template_target_material)
        form.addRow("识别区域素材（可选）", self.template_region_material)
        form.addRow(self.template_open_materials)
        form.addRow("颜色识别参数", self.template_color_parameters)
        form.addRow("模板识别参数", self.template_template_parameters)
        form.addRow("扫描间隔", self.template_interval)
        form.addRow("触发冷却", self.template_cooldown)
        form.addRow("触发方式", self.template_trigger_mode)
        form.addRow("找到目标后", self.template_action)
        form.addRow("执行的已保存操作", self.template_action_combo)
        form.addRow("键盘/鼠标动作", self.template_step_input)
        form.addRow("识别超时", self.template_timeout)
        settings_group = QGroupBox("模板识别参数")
        settings_group.setLayout(form)
        preset_group = QGroupBox("识图预设（可在自定义流程中选择）")
        preset_form = QFormLayout(preset_group)
        preset_form.addRow("当前预设", self.vision_preset_combo)
        preset_form.addRow("预设名称", self.vision_preset_name)
        preset_buttons = QHBoxLayout(); preset_buttons.addWidget(self.vision_preset_save); preset_buttons.addWidget(self.vision_preset_update); preset_buttons.addWidget(self.vision_preset_delete); preset_buttons.addWidget(self.vision_preset_lock)
        preset_form.addRow(preset_buttons)
        status_group = QGroupBox("模板识别状态")
        status_layout = QVBoxLayout(status_group)
        status_layout.addWidget(self.template_status)
        status_layout.addWidget(self.template_result)

        layout = QVBoxLayout(tab)
        layout.addWidget(self.template_enabled)
        layout.addWidget(settings_group)
        layout.addWidget(preset_group)
        layout.addWidget(status_group)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        return scroll

    def _build_fishing_tab(self) -> QWidget:
        tab = QWidget()
        self.fishing_enabled = QCheckBox("启用钓鱼识别")
        self.hide_during_capture = QCheckBox("吸色、截取模板或选择区域时隐藏软件")
        self.hide_during_capture.setChecked(True)
        self.capture_target_combo = QComboBox()
        self.capture_target_combo.addItem("A：选色", "a:color")
        self.capture_target_combo.addItem("A：选模板", "a:template")
        self.capture_target_combo.addItem("B：选色", "b:color")
        self.capture_target_combo.addItem("B：选模板", "b:template")
        self.fishing_a_material = QComboBox()
        self.fishing_b_material = QComboBox()
        self.fishing_region_material = QComboBox()
        self.fishing_open_materials = QPushButton("在素材库管理和预览")
        self.fishing_open_materials.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        self.fishing_color_pick_hotkey = QLineEdit()
        self.fishing_color_pick_hotkey.setPlaceholderText("留空不绑定；例如 F6")
        self.fishing_region_pick_hotkey = QLineEdit()
        self.fishing_region_pick_hotkey.setPlaceholderText("留空不绑定；例如 F7")
        self.fishing_detection_hotkey = QLineEdit()
        self.fishing_detection_hotkey.setPlaceholderText("留空不绑定；例如 F7")
        self.fishing_color_button = QPushButton()
        self.fishing_color_b_button = QPushButton()
        self.a_source_combo = QComboBox()
        self.b_source_combo = QComboBox()
        for combo in (self.a_source_combo, self.b_source_combo):
            combo.addItem("颜色色块", "color")
            combo.addItem("截图模板", "template")
        self.capture_template_a_button = QPushButton("截取 A 模板")
        self.capture_template_b_button = QPushButton("截取 B 模板")
        self.view_template_a_button = QPushButton("查看 A 模板")
        self.view_template_b_button = QPushButton("查看 B 模板")
        self.template_a_label = QLabel("未截取模板")
        self.template_b_label = QLabel("未截取模板")
        self.fishing_template_threshold = QDoubleSpinBox()
        self.fishing_template_threshold.setRange(0.1, 1.0)
        self.fishing_template_threshold.setSingleStep(0.01)
        self.fishing_template_threshold.setValue(0.85)
        self.fishing_pick_color_button = QPushButton("吸取 A 色块")
        self.fishing_pick_color_b_button = QPushButton("吸取 B 色块")
        self.fishing_left_key = QLineEdit("A")
        self.fishing_right_key = QLineEdit("D")
        self.window_combo = QComboBox()
        self.refresh_windows_button = QPushButton("刷新窗口")
        self.select_region_button = QPushButton("拖拽选择窗口区域")
        self.use_full_window_button = QPushButton("使用整个窗口")
        self.view_region_button = QPushButton("查看区域截图")
        self.region_summary = QLabel("识别整个窗口")
        self.area_hint_a = QLabel()
        self.area_hint_b = QLabel()
        self.dead_zone_hint = QLabel()
        self.filter_light_button = QPushButton("少过滤")
        self.filter_standard_button = QPushButton("标准过滤")
        self.filter_strong_button = QPushButton("强过滤")
        self.dead_zone_precise_button = QPushButton("精确 ±4")
        self.dead_zone_standard_button = QPushButton("标准 ±12")
        self.dead_zone_stable_button = QPushButton("稳定 ±24")
        self.region_x = QSpinBox()
        self.region_y = QSpinBox()
        self.region_width = QSpinBox()
        self.region_height = QSpinBox()
        for control in (self.region_x, self.region_y, self.region_width, self.region_height):
            control.setRange(0, 100000)
        self.region_width.setSpecialValueText("窗口全宽")
        self.region_height.setSpecialValueText("窗口全高")
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText("钓鱼预设名称")
        self.preset_combo = QComboBox()
        self.preset_lock_button = QPushButton("锁定预设")
        self.preset_save_button = QPushButton("保存为新预设")
        self.preset_update_button = QPushButton("更新当前预设")
        self.preset_delete_button = QPushButton("删除当前预设")
        self.fishing_hue_tolerance = QSpinBox()
        self.fishing_hue_tolerance.setRange(1, 90)
        self.fishing_hue_tolerance.setValue(12)
        self.hue_percent_label = QLabel()
        self.fishing_min_area = QSpinBox()
        self.fishing_min_area.setRange(1, 1_000_000)
        self.fishing_min_area.setValue(120)
        self.fishing_b_min_area = QSpinBox()
        self.fishing_b_min_area.setRange(1, 1_000_000)
        self.fishing_b_min_area.setValue(8)
        self.fishing_input_mode = QComboBox()
        self.fishing_input_mode.addItem("点按（推荐细竖条）", "tap")
        self.fishing_input_mode.addItem("按住（持续移动）", "hold")
        self.fishing_tap_interval = QSpinBox()
        self.fishing_tap_interval.setRange(20, 10_000)
        self.fishing_tap_interval.setValue(250)
        self.fishing_tap_interval.setSuffix(" ms")
        self.tap_slow_button = QPushButton("慢 400 ms")
        self.tap_standard_button = QPushButton("标准 250 ms")
        self.tap_fast_button = QPushButton("快 120 ms")
        self.fishing_interval = QSpinBox()
        self.fishing_interval.setRange(50, 10_000)
        self.fishing_interval.setValue(100)
        self.fishing_interval.setSuffix(" ms")
        self.fishing_dead_zone = QSpinBox()
        self.fishing_dead_zone.setRange(0, 500)
        self.fishing_dead_zone.setValue(12)
        self.fishing_dead_zone.setSuffix(" px")
        self.fishing_gain = QDoubleSpinBox()
        self.fishing_gain.setRange(0.01, 1.0)
        self.fishing_gain.setSingleStep(0.05)
        self.fishing_gain.setDecimals(2)
        self.fishing_gain.setValue(0.2)
        self.fishing_max_step = QSpinBox()
        self.fishing_max_step.setRange(1, 120)
        self.restore_fishing_defaults_button = QPushButton("恢复识别默认参数")
        self.fishing_max_step.setValue(40)
        self.fishing_max_step.setSuffix(" px")
        self.fishing_status = QLabel("钓鱼色块追踪未启用")
        self.fishing_status.setWordWrap(True)
        self.fishing_result = QLabel("尚未找到色块")
        self.fishing_result.setWordWrap(True)

        self.fishing_enabled.toggled.connect(self.fishing_enabled_changed)
        self.hide_during_capture.toggled.connect(self._emit_fishing_settings)
        self.capture_target_combo.currentIndexChanged.connect(self._capture_target_changed)
        self.fishing_a_material.currentIndexChanged.connect(self._apply_fishing_a_material)
        self.fishing_b_material.currentIndexChanged.connect(self._apply_fishing_b_material)
        self.fishing_region_material.currentIndexChanged.connect(self._apply_fishing_region_material)
        self.fishing_color_pick_hotkey.editingFinished.connect(self._emit_fishing_settings)
        self.fishing_region_pick_hotkey.editingFinished.connect(self._emit_fishing_settings)
        self.fishing_detection_hotkey.editingFinished.connect(self._emit_fishing_settings)
        self.fishing_left_key.editingFinished.connect(self._emit_fishing_settings)
        self.fishing_right_key.editingFinished.connect(self._emit_fishing_settings)
        self.window_combo.currentIndexChanged.connect(self._emit_fishing_settings)
        self.refresh_windows_button.clicked.connect(self._refresh_windows)
        self.select_region_button.clicked.connect(self._select_window_region)
        self.use_full_window_button.clicked.connect(self._use_full_window)
        self.view_region_button.clicked.connect(self._view_region_preview)
        self.filter_light_button.clicked.connect(lambda: self._set_filter_levels(50, 3))
        self.filter_standard_button.clicked.connect(lambda: self._set_filter_levels(120, 8))
        self.filter_strong_button.clicked.connect(lambda: self._set_filter_levels(500, 20))
        self.dead_zone_precise_button.clicked.connect(lambda: self.fishing_dead_zone.setValue(4))
        self.dead_zone_standard_button.clicked.connect(lambda: self.fishing_dead_zone.setValue(12))
        self.dead_zone_stable_button.clicked.connect(lambda: self.fishing_dead_zone.setValue(24))
        self.fishing_color_button.clicked.connect(lambda: self._choose_fishing_color("a"))
        self.fishing_color_b_button.clicked.connect(lambda: self._choose_fishing_color("b"))
        self.a_source_combo.currentIndexChanged.connect(self._emit_fishing_settings)
        self.b_source_combo.currentIndexChanged.connect(self._emit_fishing_settings)
        self.capture_template_a_button.clicked.connect(lambda: self._capture_template("a"))
        self.capture_template_b_button.clicked.connect(lambda: self._capture_template("b"))
        self.view_template_a_button.clicked.connect(lambda: self._view_template("a"))
        self.view_template_b_button.clicked.connect(lambda: self._view_template("b"))
        self.fishing_template_threshold.valueChanged.connect(self._emit_fishing_settings)
        self.fishing_input_mode.currentIndexChanged.connect(self._emit_fishing_settings)
        self.fishing_tap_interval.valueChanged.connect(self._emit_fishing_settings)
        self.tap_slow_button.clicked.connect(lambda: self.fishing_tap_interval.setValue(400))
        self.tap_standard_button.clicked.connect(lambda: self.fishing_tap_interval.setValue(250))
        self.tap_fast_button.clicked.connect(lambda: self.fishing_tap_interval.setValue(120))
        self.fishing_pick_color_button.clicked.connect(lambda: self._pick_screen_color("a"))
        self.fishing_pick_color_b_button.clicked.connect(lambda: self._pick_screen_color("b"))
        self.preset_combo.currentIndexChanged.connect(self._load_selected_preset)
        self.preset_save_button.clicked.connect(self._save_new_preset)
        self.preset_update_button.clicked.connect(self._update_selected_preset)
        self.preset_delete_button.clicked.connect(self._delete_selected_preset)
        self.preset_lock_button.clicked.connect(self._toggle_selected_preset_lock)
        self.restore_fishing_defaults_button.clicked.connect(self._restore_fishing_defaults)
        self.fishing_hue_tolerance.valueChanged.connect(self._update_hue_hint)
        self.fishing_min_area.valueChanged.connect(self._update_fishing_hints)
        self.fishing_b_min_area.valueChanged.connect(self._update_fishing_hints)
        self.fishing_dead_zone.valueChanged.connect(self._update_fishing_hints)
        for widget in (self.fishing_hue_tolerance, self.fishing_min_area, self.fishing_b_min_area, self.fishing_interval, self.fishing_dead_zone, self.fishing_gain, self.fishing_max_step, self.region_x, self.region_y, self.region_width, self.region_height):
            widget.valueChanged.connect(self._emit_fishing_settings)

        form = QFormLayout()
        color_a_buttons = QHBoxLayout()
        color_a_buttons.addWidget(self.fishing_color_button)
        color_a_buttons.addWidget(self.fishing_pick_color_button)
        color_b_buttons = QHBoxLayout()
        color_b_buttons.addWidget(self.fishing_color_b_button)
        color_b_buttons.addWidget(self.fishing_pick_color_b_button)
        window_buttons = QHBoxLayout()
        window_buttons.addWidget(self.window_combo, 1)
        window_buttons.addWidget(self.refresh_windows_button)
        material_section = QLabel("素材与观察范围")
        material_section.setObjectName("sectionLabel")
        form.addRow(material_section)
        form.addRow("A 目标素材", self.fishing_a_material)
        form.addRow("B 目标素材", self.fishing_b_material)
        form.addRow("观察区域素材", self.fishing_region_material)
        form.addRow(self.fishing_open_materials)
        recognition_section = QLabel("识别与操作参数")
        recognition_section.setObjectName("sectionLabel")
        form.addRow(recognition_section)
        form.addRow("模板最低匹配分数", self.fishing_template_threshold)
        form.addRow("B 偏离 A 中心时修正键（左偏 / 右偏）", self._pair_row(self.fishing_right_key, self.fishing_left_key))
        form.addRow("颜色匹配范围", self._pair_row(self.fishing_hue_tolerance, self.hue_percent_label))
        filter_buttons = QHBoxLayout()
        filter_buttons.addWidget(self.filter_light_button)
        filter_buttons.addWidget(self.filter_standard_button)
        filter_buttons.addWidget(self.filter_strong_button)
        form.addRow("A 长条杂点过滤", self._pair_row(self.fishing_min_area, self.area_hint_a))
        form.addRow("B 细竖条杂点过滤", self._pair_row(self.fishing_b_min_area, self.area_hint_b))
        form.addRow("杂点过滤建议", filter_buttons)
        tap_buttons = QHBoxLayout()
        tap_buttons.addWidget(self.tap_slow_button)
        tap_buttons.addWidget(self.tap_standard_button)
        tap_buttons.addWidget(self.tap_fast_button)
        form.addRow("点按间隔（20–10000 ms）", self.fishing_tap_interval)
        form.addRow("常用点按档位", tap_buttons)
        dead_buttons = QHBoxLayout()
        dead_buttons.addWidget(self.dead_zone_precise_button)
        dead_buttons.addWidget(self.dead_zone_standard_button)
        dead_buttons.addWidget(self.dead_zone_stable_button)
        form.addRow("扫描间隔", self.fishing_interval)
        form.addRow("居中允许偏差", self._pair_row(self.fishing_dead_zone, self.dead_zone_hint))
        form.addRow("居中偏差建议", dead_buttons)
        form.addRow("调整倍率", self.fishing_gain)
        form.addRow("最大单次移动", self.fishing_max_step)
        form.addRow(self.restore_fishing_defaults_button)
        settings_group = QGroupBox("钓鱼色块追踪参数")
        settings_group.setLayout(form)
        preset_group = QGroupBox("钓鱼预设（可在自定义流程中使用）")
        preset_form = QFormLayout(preset_group)
        preset_form.addRow("当前预设", self.preset_combo)
        preset_form.addRow("预设名称", self.preset_name)
        preset_buttons = QHBoxLayout()
        preset_buttons.addWidget(self.preset_save_button)
        preset_buttons.addWidget(self.preset_update_button)
        preset_buttons.addWidget(self.preset_delete_button)
        preset_buttons.addWidget(self.preset_lock_button)
        preset_form.addRow(preset_buttons)
        status_group = QGroupBox("钓鱼追踪状态")
        status_layout = QVBoxLayout(status_group)
        status_layout.addWidget(self.fishing_status)
        status_layout.addWidget(self.fishing_result)

        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("持续监测 A 长条与 B 竖条，让 B 的中心持续保持在 A 的水平中心；当前对齐时继续监测，偏离后立即修正。颜色、模板和观察区域均从素材库选择。"))
        toggle_layout = QHBoxLayout()
        toggle_layout.addWidget(self.fishing_enabled)
        toggle_layout.addWidget(QLabel("识别开关快捷键"))
        toggle_layout.addWidget(self.fishing_detection_hotkey)
        layout.addLayout(toggle_layout)
        layout.addWidget(settings_group)
        layout.addWidget(preset_group)
        layout.addWidget(status_group)
        layout.addStretch()
        self._set_fishing_color_button()
        self._update_hue_hint()
        self._update_fishing_hints()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        return scroll

    @staticmethod
    def _template_row(button: QWidget, label: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(button)
        layout.addWidget(label, 1)
        return row

    @staticmethod
    def _pair_row(first: QWidget, second: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(first)
        layout.addWidget(second)
        return row

    def set_data(self, actions: list[ActionDefinition], template: VisionSettings, fishing: FishingSettings, fishing_presets: list[FishingPreset] | None = None, materials: list[MaterialAsset] | None = None, material_capture: MaterialCaptureSettings | None = None, vision_presets: list[VisionPreset] | None = None) -> None:
        self._actions = actions
        self._vision_presets = vision_presets or []
        self._refresh_vision_preset_combo()
        self._materials = materials or []
        self._material_capture = material_capture or MaterialCaptureSettings()
        self._refresh_materials()
        self._refresh_material_references(template, fishing)
        self._refresh_material_capture_windows(self._material_capture.window_title)
        for widget in (self.material_color_hotkey, self.material_template_hotkey, self.material_region_hotkey, self.material_hide_during_capture): widget.blockSignals(True)
        self.material_color_hotkey.setText(self._material_capture.color_pick_hotkey)
        self.material_template_hotkey.setText(self._material_capture.template_capture_hotkey)
        self.material_region_hotkey.setText(self._material_capture.region_capture_hotkey)
        self.material_hide_during_capture.setChecked(self._material_capture.hide_during_capture)
        for widget in (self.material_color_hotkey, self.material_template_hotkey, self.material_region_hotkey, self.material_hide_during_capture): widget.blockSignals(False)
        self._template_settings = template
        self._template_rules = []
        self._fishing_settings = fishing
        self._fishing_presets = fishing_presets or []
        self.template_action_combo.blockSignals(True)
        self.template_action_combo.clear()
        self.template_action_combo.addItem("请选择操作", "")
        for action in actions:
            self.template_action_combo.addItem(action.name, action.id)
        self.template_action_combo.setCurrentIndex(max(0, self.template_action_combo.findData(template.action_id)))
        self.template_action_combo.blockSignals(False)
        self.template_threshold.blockSignals(True)
        self.template_interval.blockSignals(True)
        self.template_action.blockSignals(True)
        self.template_timeout.blockSignals(True)
        self.template_source.setCurrentIndex(max(0, self.template_source.findData(template.source)))
        self.template_path.setText(template.template_path)
        self.template_color_button.setText(template.color_hex)
        self.template_color_button.setStyleSheet(f"background: {template.color_hex}; color: {'#000' if QColor(template.color_hex).lightness() > 128 else '#fff'};")
        self.template_hue_tolerance.setValue(template.hue_tolerance)
        self.template_min_area.setValue(template.min_area)
        self._template_region = (template.region_x, template.region_y, template.region_width, template.region_height)
        self.template_region_summary.setText("使用整个目标窗口或主屏幕" if not template.region_width or not template.region_height else f"已选区域：{template.region_width} × {template.region_height}（窗口内）")
        self._refresh_template_windows()
        self.template_window_combo.setCurrentIndex(max(0, self.template_window_combo.findData(template.window_title)))
        self.template_threshold.setValue(template.threshold)
        self.template_interval.setValue(template.scan_interval_ms)
        self.template_action.setCurrentIndex(max(0, self.template_action.findData(template.action_mode)))
        self.template_timeout.setValue(template.timeout_seconds)
        if template.response_step:
            self.template_step_input.set_step(template.response_step)
        self.template_threshold.blockSignals(False)
        self.template_interval.blockSignals(False)
        self.template_action.blockSignals(False)
        self.template_timeout.blockSignals(False)
        self._update_template_action_state()
        self._template_source_changed()

        self.hide_during_capture.blockSignals(True)
        self.hide_during_capture.setChecked(fishing.hide_during_capture)
        self.hide_during_capture.blockSignals(False)
        selected_capture = f"{fishing.capture_target}:{fishing.a_source if fishing.capture_target == 'a' else fishing.b_source}"
        self.capture_target_combo.setCurrentIndex(max(0, self.capture_target_combo.findData(selected_capture)))
        self.a_source_combo.setCurrentIndex(max(0, self.a_source_combo.findData(fishing.a_source)))
        self.b_source_combo.setCurrentIndex(max(0, self.b_source_combo.findData(fishing.b_source)))
        self.fishing_template_threshold.setValue(fishing.template_threshold)
        self.template_a_label.setText(Path(fishing.template_a_path).name if fishing.template_a_path else "未截取模板")
        self.template_b_label.setText(Path(fishing.template_b_path).name if fishing.template_b_path else "未截取模板")
        self.fishing_color_pick_hotkey.setText(fishing.color_pick_hotkey)
        self.fishing_region_pick_hotkey.setText(fishing.region_pick_hotkey)
        self.fishing_detection_hotkey.setText(fishing.detection_hotkey)
        self.fishing_left_key.setText(fishing.left_key)
        self.fishing_right_key.setText(fishing.right_key)
        self._refresh_windows(fishing.window_title)
        self.region_x.setValue(fishing.region_x)
        self.region_y.setValue(fishing.region_y)
        self.region_width.setValue(fishing.region_width)
        self.region_height.setValue(fishing.region_height)
        self._refresh_region_summary()
        self._update_fishing_hints()
        self._refresh_preset_combo()
        self.fishing_hue_tolerance.blockSignals(True)
        self.fishing_min_area.blockSignals(True)
        self.fishing_b_min_area.blockSignals(True)
        self.fishing_interval.blockSignals(True)
        self.fishing_dead_zone.blockSignals(True)
        self.fishing_gain.blockSignals(True)
        self.fishing_max_step.blockSignals(True)
        self.fishing_hue_tolerance.setValue(fishing.hue_tolerance)
        self.fishing_min_area.setValue(fishing.min_area)
        self.fishing_b_min_area.setValue(fishing.b_min_area)
        self.fishing_input_mode.setCurrentIndex(max(0, self.fishing_input_mode.findData(fishing.input_mode)))
        self.fishing_tap_interval.setValue(fishing.tap_interval_ms)
        self.fishing_interval.setValue(fishing.scan_interval_ms)
        self.fishing_dead_zone.setValue(fishing.dead_zone)
        self.fishing_gain.setValue(fishing.gain)
        self.fishing_max_step.setValue(fishing.max_step)
        self.fishing_hue_tolerance.blockSignals(False)
        self.fishing_min_area.blockSignals(False)
        self.fishing_b_min_area.blockSignals(False)
        self.fishing_interval.blockSignals(False)
        self.fishing_dead_zone.blockSignals(False)
        self.fishing_gain.blockSignals(False)
        self.fishing_max_step.blockSignals(False)
        self._set_fishing_color_button(fishing.color_a_hex, "a")
        self._set_fishing_color_button(fishing.color_b_hex, "b")

    def _refresh_material_capture_windows(self, selected_title: str = "") -> None:
        current = selected_title or str(self.material_window_combo.currentData() or "")
        self.material_window_combo.blockSignals(True); self.material_window_combo.clear()
        self.material_window_combo.addItem("请选择可见窗口", "")
        for window in list_visible_windows():
            self.material_window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window.title)
        self.material_window_combo.setCurrentIndex(max(0, self.material_window_combo.findData(current)))
        self.material_window_combo.blockSignals(False)

    def _material_capture_settings_value(self) -> MaterialCaptureSettings:
        return MaterialCaptureSettings(
            window_title=str(self.material_window_combo.currentData() or ""),
            hide_during_capture=self.material_hide_during_capture.isChecked(),
            color_pick_hotkey=self.material_color_hotkey.text().strip(),
            template_capture_hotkey=self.material_template_hotkey.text().strip(),
            region_capture_hotkey=self.material_region_hotkey.text().strip(),
        )

    def _emit_material_capture_settings(self) -> None:
        self._material_capture = self._material_capture_settings_value()
        self.material_capture_settings_changed.emit(self._material_capture)

    def _material_window(self):
        title = str(self.material_window_combo.currentData() or "")
        return next((item for item in list_visible_windows() if item.title == title), None)

    def _material_capture_done(self) -> None:
        self._restore_after_capture()
        new_material_id = self._materials[-1].id if self._materials else ""
        self._refresh_materials()
        for row in range(self.material_list.count()):
            if self.material_list.item(row).data(Qt.ItemDataRole.UserRole) == new_material_id:
                self.material_list.setCurrentRow(row)
                break
        self.materials_changed.emit(self._materials)

    def capture_material_color(self) -> None:
        self._emit_material_capture_settings()
        self._material_color_picker = ScreenColorPicker()
        self._material_color_picker.color_picked.connect(self._save_material_color)
        self._material_color_picker.picker_closed.connect(self._restore_after_capture)
        self._launch_capture(self._material_color_picker.showFullScreen, self._material_capture.hide_during_capture)

    def _save_material_color(self, color_hex: str) -> None:
        self._materials.append(MaterialAsset(name=f"颜色 {color_hex}", kind="color", color_hex=color_hex))
        self._material_capture_done()

    def import_material_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入本地模板图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        image = QPixmap(path)
        if image.isNull():
            self.material_preview.setText("无法读取所选图片，请选择有效的图片文件")
            return
        self._materials.append(MaterialAsset(name=f"模板 {Path(path).stem}", kind="template", image_path=path))
        self._material_capture_done()

    def capture_material_template(self) -> None:
        self._emit_material_capture_settings(); window = self._material_window()
        if window is None:
            self.set_template_status("请先在素材库选择可见窗口，再截取模板")
            return
        self._material_picker_window = window
        self._launch_capture(self._show_material_template_picker, self._material_capture.hide_during_capture)

    def _show_material_template_picker(self) -> None:
        self._material_template_picker = WindowRegionPicker(self._material_picker_window)
        self._material_template_picker.region_selected.connect(self._save_material_template)
        self._material_template_picker.picker_closed.connect(self._restore_after_capture)
        self._material_template_picker.show(); self._material_template_picker.activateWindow()

    def _save_material_template(self, x: int, y: int, width: int, height: int) -> None:
        image = self._material_template_picker._image.copy(x, y, width, height)
        if image.isNull():
            self.set_template_status("模板截取失败"); return
        directory = Path(__file__).resolve().parents[2] / "data" / "vision_templates"; directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"material_{uuid4().hex}.png"
        if image.save(str(path), "PNG"):
            self._materials.append(MaterialAsset(name=f"模板 {path.stem}", kind="template", image_path=str(path), window_title=self._material_picker_window.title))
            self._material_capture_done()

    def capture_material_region(self) -> None:
        self._emit_material_capture_settings(); window = self._material_window()
        if window is None:
            self.set_template_status("请先在素材库选择可见窗口，再截取区域")
            return
        self._material_picker_window = window
        self._launch_capture(self._show_material_region_picker, self._material_capture.hide_during_capture)

    def _show_material_region_picker(self) -> None:
        self._material_region_picker = WindowRegionPicker(self._material_picker_window)
        self._material_region_picker.region_selected.connect(self._save_material_region)
        self._material_region_picker.picker_closed.connect(self._restore_after_capture)
        self._material_region_picker.show(); self._material_region_picker.activateWindow()

    def _save_material_region(self, x: int, y: int, width: int, height: int) -> None:
        image = self._material_region_picker._image.copy(x, y, width, height)
        if image.isNull():
            self.set_template_status("区域截取失败"); return
        directory = Path(__file__).resolve().parents[2] / "data" / "vision_regions"; directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"region_{uuid4().hex}.png"
        if image.save(str(path), "PNG"):
            self._materials.append(MaterialAsset(name=f"区域 {path.stem}", kind="region", image_path=str(path), window_title=self._material_picker_window.title, region_x=x, region_y=y, region_width=width, region_height=height))
            self._material_capture_done()

    def template_is_enabled(self) -> bool:
        return self.template_enabled.isChecked()

    def fishing_is_enabled(self) -> bool:
        return self.fishing_enabled.isChecked()

    def set_template_status(self, message: str) -> None:
        self.template_status.setText(message)

    def set_template_match_result(self, score: float, center_x: int, center_y: int) -> None:
        if score >= self.template_threshold.value():
            self.template_result.setText(f"已找到目标：匹配分数 {score:.3f}，中心坐标 ({center_x}, {center_y})")
        else:
            self.template_result.setText(f"暂未达到阈值：最佳分数 {score:.3f}，候选中心 ({center_x}, {center_y})")

    def set_fishing_status(self, message: str) -> None:
        self.fishing_status.setText(message)

    def set_fishing_result(self, message: str) -> None:
        self.fishing_result.setText(message)

    def _selected_template_rule(self) -> VisionRule | None:
        rule_id = str(self.template_rule_combo.currentData() or "")
        return next((rule for rule in self._template_rules if rule.id == rule_id), None)

    def _save_rule_editor(self) -> None:
        rule = self._selected_template_rule()
        if rule is None:
            return
        rule.name = self.template_rule_name.text().strip() or "未命名识别规则"
        rule.enabled = self.template_rule_enabled.isChecked()
        rule.template_path = self.template_path.text().strip()
        rule.threshold = self.template_threshold.value()
        rule.scan_interval_ms = self.template_interval.value()
        rule.cooldown_ms = self.template_cooldown.value()
        rule.trigger_mode = str(self.template_trigger_mode.currentData())
        rule.action_mode = str(self.template_action.currentData())
        rule.action_id = str(self.template_action_combo.currentData() or "")
        rule.action_step = self.template_step_input.build_step() if rule.action_mode == "step" else None

    def _load_template_rule(self) -> None:
        rule = self._selected_template_rule()
        if rule is None:
            return
        for widget in (self.template_rule_name, self.template_path, self.template_threshold, self.template_interval, self.template_cooldown, self.template_trigger_mode, self.template_action, self.template_action_combo, self.template_timeout):
            widget.blockSignals(True)
        self.template_rule_name.setText(rule.name)
        self.template_rule_enabled.setChecked(rule.enabled)
        self.template_path.setText(rule.template_path)
        self.template_threshold.setValue(rule.threshold)
        self.template_interval.setValue(rule.scan_interval_ms)
        self.template_cooldown.setValue(rule.cooldown_ms)
        self.template_trigger_mode.setCurrentIndex(max(0, self.template_trigger_mode.findData(rule.trigger_mode)))
        self.template_action.setCurrentIndex(max(0, self.template_action.findData(rule.action_mode)))
        self.template_action_combo.setCurrentIndex(max(0, self.template_action_combo.findData(rule.action_id)))
        if rule.action_step:
            self.template_step_input.set_step(rule.action_step)
        for widget in (self.template_rule_name, self.template_path, self.template_threshold, self.template_interval, self.template_cooldown, self.template_trigger_mode, self.template_action, self.template_action_combo, self.template_timeout):
            widget.blockSignals(False)
        self._update_template_action_state()

    def _refresh_template_rule_combo(self, selected_id: str = "") -> None:
        self.template_rule_combo.blockSignals(True)
        self.template_rule_combo.clear()
        for rule in self._template_rules:
            self.template_rule_combo.addItem(("● " if rule.enabled else "○ ") + rule.name, rule.id)
        self.template_rule_combo.setCurrentIndex(max(0, self.template_rule_combo.findData(selected_id)))
        self.template_rule_combo.blockSignals(False)
        self._load_template_rule()

    def _add_template_rule(self) -> None:
        rule = VisionRule(name=f"识别规则 {len(self._template_rules) + 1}")
        self._template_rules.append(rule)
        self._refresh_template_rule_combo(rule.id)
        self._emit_template_settings()

    def _delete_template_rule(self) -> None:
        rule = self._selected_template_rule()
        if rule is None:
            return
        self._template_rules.remove(rule)
        self._refresh_template_rule_combo()
        self._emit_template_settings()

    def _template_settings_value(self) -> VisionSettings:
        self._save_rule_editor()
        # 新版页面只保存一个明确的识别任务；旧多规则不再继续参与运行。
        region_x, region_y, region_width, region_height = self._template_region
        return VisionSettings(
            rules=[],
            source=str(self.template_source.currentData()),
            color_hex=self.template_color_button.text(), hue_tolerance=self.template_hue_tolerance.value(), min_area=self.template_min_area.value(),
            window_title=str(self.template_window_combo.currentData() or ""),
            region_x=region_x, region_y=region_y, region_width=region_width, region_height=region_height,
            template_path=self.template_path.text().strip(),
            threshold=self.template_threshold.value(),
            scan_interval_ms=self.template_interval.value(),
            action_mode=str(self.template_action.currentData()),
            action_id=str(self.template_action_combo.currentData() or ""),
            response_step=self.template_step_input.build_step() if self.template_action.currentData() == "step" else None,
            target_material_id=str(self.template_target_material.currentData() or ""),
            region_material_id=str(self.template_region_material.currentData() or ""),
            timeout_seconds=self.template_timeout.value(),
        )

    def _fishing_settings_value(self) -> FishingSettings:
        return FishingSettings(
            mode="ab_keys",
            hide_during_capture=self.hide_during_capture.isChecked(),
            capture_target=str(self.capture_target_combo.currentData() or "a:color").split(":", 1)[0],
            a_source=str(self.a_source_combo.currentData()),
            b_source=str(self.b_source_combo.currentData()),
            color_a_hex=self._fishing_settings.color_a_hex,
            color_b_hex=self._fishing_settings.color_b_hex,
            template_a_path=self._fishing_settings.template_a_path,
            template_b_path=self._fishing_settings.template_b_path,
            a_material_id=str(self.fishing_a_material.currentData() or ""),
            b_material_id=str(self.fishing_b_material.currentData() or ""),
            region_material_id=str(self.fishing_region_material.currentData() or ""),
            template_threshold=self.fishing_template_threshold.value(),
            color_pick_hotkey=self.fishing_color_pick_hotkey.text().strip(),
            region_pick_hotkey=self.fishing_region_pick_hotkey.text().strip(),
            detection_hotkey=self.fishing_detection_hotkey.text().strip(),
            left_key=self.fishing_left_key.text().strip().upper(),
            right_key=self.fishing_right_key.text().strip().upper(),
            window_title=str(self.window_combo.currentData() or ""),
            region_x=self.region_x.value(),
            region_y=self.region_y.value(),
            region_width=self.region_width.value(),
            region_height=self.region_height.value(),
            region_preview_path=self._fishing_settings.region_preview_path,
            hue_tolerance=self.fishing_hue_tolerance.value(),
            min_area=self.fishing_min_area.value(),
            b_min_area=self.fishing_b_min_area.value(),
            input_mode=str(self.fishing_input_mode.currentData()),
            tap_interval_ms=self.fishing_tap_interval.value(),
            scan_interval_ms=self.fishing_interval.value(),
            dead_zone=self.fishing_dead_zone.value(),
            gain=self.fishing_gain.value(),
            max_step=self.fishing_max_step.value(),
        )

    def _restore_fishing_defaults(self) -> None:
        self.fishing_hue_tolerance.setValue(12)
        self.fishing_min_area.setValue(120)
        self.fishing_b_min_area.setValue(8)
        self.fishing_input_mode.setCurrentIndex(self.fishing_input_mode.findData("tap"))
        self.fishing_tap_interval.setValue(250)
        self.fishing_interval.setValue(100)
        self.fishing_dead_zone.setValue(12)
        self.fishing_template_threshold.setValue(0.85)
        self._emit_fishing_settings()
        self.set_fishing_status("已恢复识别默认参数；A/B、窗口、区域、按键和快捷键未改变")

    def _emit_template_settings(self) -> None:
        self._template_settings = self._template_settings_value()
        self.template_settings_changed.emit(self._template_settings)

    def _emit_fishing_settings(self) -> None:
        self._fishing_settings = self._fishing_settings_value()
        self.fishing_settings_changed.emit(self._fishing_settings)

    def _template_action_changed(self) -> None:
        self._update_template_action_state()
        self._emit_template_settings()

    def _update_template_action_state(self) -> None:
        self.template_action_combo.setEnabled(self.template_action.currentData() == "action_once")
        self.template_step_input.setVisible(self.template_action.currentData() == "step")

    def _template_source_changed(self) -> None:
        is_template = self.template_source.currentData() == "template"
        self.template_path.setEnabled(is_template)
        self.template_capture_button.setEnabled(is_template)
        self.template_threshold.setEnabled(is_template)
        for widget in (self.template_color_button, self.template_pick_color_button, self.template_hue_tolerance, self.template_min_area):
            widget.setEnabled(not is_template)
        self._update_template_parameter_visibility()
        self._emit_template_settings()

    def _update_template_parameter_visibility(self) -> None:
        material_id = str(self.template_target_material.currentData() or "")
        material = next((item for item in self._materials if item.id == material_id), None)
        self.template_color_parameters.setVisible(material is not None and material.kind == "color")
        self.template_template_parameters.setVisible(material is not None and material.kind == "template")

    def _refresh_template_windows(self) -> None:
        current = str(self.template_window_combo.currentData() or "")
        self.template_window_combo.clear()
        self.template_window_combo.addItem("主屏幕（默认）", "")
        for window in list_visible_windows():
            self.template_window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window.title)
        self.template_window_combo.setCurrentIndex(max(0, self.template_window_combo.findData(current)))

    def _pick_template_color(self) -> None:
        self._template_color_picker = ScreenColorPicker()
        self._template_color_picker.color_picked.connect(self._apply_template_color)
        self._template_color_picker.showFullScreen()
        self._template_color_picker.activateWindow()

    def _choose_template_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.template_color_button.text()), self, "选择 AI 识别颜色")
        if color.isValid():
            self._apply_template_color(color.name().upper())

    def _apply_template_color(self, color_hex: str) -> None:
        self.template_color_button.setText(color_hex)
        self.template_color_button.setStyleSheet(f"background: {color_hex}; color: {'#000' if QColor(color_hex).lightness() > 128 else '#fff'};")
        if not any(item.kind == "color" and item.color_hex == color_hex for item in self._materials):
            self._materials.append(MaterialAsset(name=f"AI 颜色 {color_hex}", kind="color", color_hex=color_hex))
            self.materials_changed.emit(self._materials)
            self._refresh_materials()
        self._emit_template_settings()

    def _select_template_region(self) -> None:
        title = str(self.template_window_combo.currentData() or "")
        window = next((item for item in list_visible_windows() if item.title == title), None)
        if window is None:
            self.set_template_status("请先选择一个可见窗口，再框选识别区域")
            return
        self._template_region_window = window
        self._template_region_picker = WindowRegionPicker(window)
        self._template_region_picker.region_selected.connect(self._apply_template_region)
        self._template_region_picker.show()
        self._template_region_picker.activateWindow()

    def _apply_template_region(self, x: int, y: int, width: int, height: int) -> None:
        self._template_region = (x, y, width, height)
        self.template_region_summary.setText(f"已选区域：{width} × {height}（窗口内）")
        self._emit_template_settings()

    def _use_full_template_region(self) -> None:
        self._template_region = (0, 0, 0, 0)
        self.template_region_summary.setText("使用整个目标窗口或主屏幕")
        self._emit_template_settings()

    def _capture_template_from_window(self) -> None:
        title = str(self.template_window_combo.currentData() or "")
        window = next((item for item in list_visible_windows() if item.title == title), None)
        if window is None:
            self.set_template_status("请选择可见窗口后再截取模板")
            return
        self._template_capture_picker = WindowRegionPicker(window)
        self._template_capture_picker.region_selected.connect(self._save_template_capture_for_ai)
        self._template_capture_picker.show()
        self._template_capture_picker.activateWindow()

    def _save_template_capture_for_ai(self, x: int, y: int, width: int, height: int) -> None:
        image = self._template_capture_picker._image.copy(x, y, width, height)
        if image.isNull():
            self.set_template_status("模板截取失败")
            return
        directory = Path(__file__).resolve().parents[2] / "data" / "vision_templates"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"ai_{uuid4().hex}.png"
        if image.save(str(path), "PNG"):
            self.template_path.setText(str(path))
            self._materials.append(MaterialAsset(name=f"AI 模板 {path.stem}", kind="template", image_path=str(path), window_title=str(self.template_window_combo.currentData() or "")))
            self.materials_changed.emit(self._materials)
            self._refresh_materials()
            self.set_template_status(f"已保存模板：{path.name}")
            self._emit_template_settings()

    def _choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择模板图片", self.template_path.text().strip(), "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.template_path.setText(path)
            self._emit_template_settings()

    def _clear_template(self) -> None:
        if self.template_path.text():
            self.template_path.clear()
            self._emit_template_settings()

    def _launch_capture(self, show_picker, hide: bool | None = None) -> None:
        hide = self.hide_during_capture.isChecked() if hide is None else hide
        self._capture_should_restore = hide
        if not hide:
            show_picker()
            return
        window = self.window()
        self._restore_capture_minimized = window.isMinimized()
        window.hide()
        QTimer.singleShot(120, show_picker)

    def _restore_after_capture(self) -> None:
        if not getattr(self, "_capture_should_restore", False):
            return
        window = self.window()
        if self._restore_capture_minimized:
            window.showMinimized()
        else:
            window.showNormal()
        window.activateWindow()

    def _capture_target_changed(self) -> None:
        target, source = str(self.capture_target_combo.currentData() or "a:color").split(":", 1)
        combo = self.a_source_combo if target == "a" else self.b_source_combo
        if combo.currentData() != source:
            combo.setCurrentIndex(max(0, combo.findData(source)))
        self._emit_fishing_settings()

    def capture_current_target(self) -> None:
        target, source = str(self.capture_target_combo.currentData() or "a:color").split(":", 1)
        if source == "template":
            self._capture_template(target)
        else:
            self._pick_screen_color(target)

    def _pick_screen_color(self, target: str = "a") -> None:
        self.capture_target_combo.setCurrentIndex(max(0, self.capture_target_combo.findData(f"{target}:color")))
        self._color_picker_target = target
        self._launch_capture(self._show_color_picker)

    def _show_color_picker(self) -> None:
        self._color_picker = ScreenColorPicker()
        self._color_picker.color_picked.connect(self._apply_picked_color)
        self._color_picker.picker_closed.connect(self._restore_after_capture)
        self._color_picker.showFullScreen()
        self._color_picker.activateWindow()
        self._color_picker.setFocus()

    def _apply_picked_color(self, color_hex: str) -> None:
        self._set_fishing_color_button(color_hex, getattr(self, "_color_picker_target", "a"))
        self._emit_fishing_settings()

    def _refresh_windows(self, selected_title: str = "") -> None:
        current = selected_title or str(self.window_combo.currentData() or "")
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        self.window_combo.addItem("主屏幕全屏（默认）", "")
        for window in list_visible_windows():
            self.window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window.title)
        self.window_combo.setCurrentIndex(max(0, self.window_combo.findData(current)))
        self.window_combo.blockSignals(False)

    def _select_window_region(self) -> None:
        title = str(self.window_combo.currentData() or "")
        window = next((item for item in list_visible_windows() if item.title == title), None)
        if window is None:
            self.set_fishing_status("请先选择可见窗口，再拖拽选择区域")
            return
        self._region_picker_window = window
        self._launch_capture(self._show_region_picker)

    def _show_region_picker(self) -> None:
        self._region_picker = WindowRegionPicker(self._region_picker_window)
        self._region_picker.region_selected.connect(self._apply_window_region)
        self._region_picker.picker_closed.connect(self._restore_after_capture)
        self._region_picker.show()
        self._region_picker.activateWindow()

    def _update_hue_hint(self) -> None:
        percent = round(self.fishing_hue_tolerance.value() / 90 * 100)
        level = "严格" if percent <= 15 else ("标准" if percent <= 35 else "宽松")
        self.hue_percent_label.setText(f"{percent}%（{level}，最大 90）")

    def _update_fishing_hints(self) -> None:
        total = self.region_width.value() * self.region_height.value()
        if total > 0:
            self.area_hint_a.setText(f"{self.fishing_min_area.value()} / {total:,} px（{self.fishing_min_area.value() / total * 100:.3f}%）")
            self.area_hint_b.setText(f"{self.fishing_b_min_area.value()} / {total:,} px（{self.fishing_b_min_area.value() / total * 100:.3f}%）")
        else:
            self.area_hint_a.setText(f"{self.fishing_min_area.value()} px（请先框选 C 区域）")
            self.area_hint_b.setText(f"{self.fishing_b_min_area.value()} px（请先框选 C 区域）")
        self.dead_zone_hint.setText(f"±{self.fishing_dead_zone.value()} px（范围 0–500 px）")

    def _set_filter_levels(self, a_pixels: int, b_pixels: int) -> None:
        self.fishing_min_area.setValue(a_pixels)
        self.fishing_b_min_area.setValue(b_pixels)
        self._update_fishing_hints()

    def _refresh_region_summary(self) -> None:
        if self.region_width.value() <= 0 or self.region_height.value() <= 0:
            self.region_summary.setText("识别整个窗口")
        else:
            self.region_summary.setText(f"已选区域：{self.region_width.value()} × {self.region_height.value()}（窗口内）")

    def _use_full_window(self) -> None:
        self.region_x.setValue(0)
        self.region_y.setValue(0)
        self.region_width.setValue(0)
        self.region_height.setValue(0)
        self._refresh_region_summary()
        self._emit_fishing_settings()

    def _apply_window_region(self, x: int, y: int, width: int, height: int) -> None:
        self.region_x.setValue(x)
        self.region_y.setValue(y)
        self.region_width.setValue(width)
        self.region_height.setValue(height)
        self._refresh_region_summary()
        self._update_fishing_hints()
        self._save_region_preview()
        self._emit_fishing_settings()

    def _view_template(self, target: str) -> None:
        path = Path(self._fishing_settings.template_a_path if target == "a" else self._fishing_settings.template_b_path)
        if not path.is_file():
            self.set_fishing_status(f"请先截取 {target.upper()} 模板")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{target.upper()} 模板预览：{path.name}")
        layout = QVBoxLayout(dialog)
        pixmap = QPixmap(str(path))
        image = QLabel(f"{path.name}｜{pixmap.width()}×{pixmap.height()} px")
        preview = QLabel()
        preview.setPixmap(pixmap.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(image)
        layout.addWidget(preview)
        dialog.resize(preview.sizeHint())
        dialog.exec()

    def _save_region_preview(self) -> None:
        picker = getattr(self, "_region_picker", None)
        if picker is None:
            return
        image = picker._image.copy(self.region_x.value(), self.region_y.value(), self.region_width.value(), self.region_height.value())
        if image.isNull():
            return
        preview_dir = Path(__file__).resolve().parents[2] / "data" / "fishing_regions"
        preview_dir.mkdir(parents=True, exist_ok=True)
        path = preview_dir / f"region_{uuid4().hex}.png"
        if image.save(str(path), "PNG"):
            self._fishing_settings.region_preview_path = str(path)
            self._materials.append(MaterialAsset(name=f"钓鱼观察区域 {path.stem}", kind="region", image_path=str(path), window_title=self._fishing_settings.window_title, region_x=self.region_x.value(), region_y=self.region_y.value(), region_width=self.region_width.value(), region_height=self.region_height.value()))
            self.materials_changed.emit(self._materials)
            self._refresh_materials()

    def _view_region_preview(self) -> None:
        path = Path(self._fishing_settings.region_preview_path)
        if not path.is_file():
            self.set_fishing_status("请先拖拽选择 C 识别区域，才能查看截图")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("当前 C 识别区域截图")
        layout = QVBoxLayout(dialog)
        image = QPixmap(str(path))
        label = QLabel()
        label.setPixmap(image.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(label)
        dialog.resize(label.sizeHint())
        dialog.exec()

    def _capture_template(self, target: str) -> None:
        self.capture_target_combo.setCurrentIndex(max(0, self.capture_target_combo.findData(f"{target}:template")))
        title = str(self.window_combo.currentData() or "")
        window = next((item for item in list_visible_windows() if item.title == title), None)
        if window is None:
            self.set_fishing_status("请先选择可见窗口，再截取图片模板")
            return
        self._template_picker_target = target
        self._template_picker_window = window
        self._launch_capture(self._show_template_picker)

    def _show_template_picker(self) -> None:
        self._template_picker = WindowRegionPicker(self._template_picker_window)
        self._template_picker.region_selected.connect(self._save_template_capture)
        self._template_picker.picker_closed.connect(self._restore_after_capture)
        self._template_picker.show()
        self._template_picker.activateWindow()

    def _save_template_capture(self, x: int, y: int, width: int, height: int) -> None:
        picker = self._template_picker
        image = picker._image.copy(x, y, width, height)
        if image.isNull():
            self.set_fishing_status("模板截取失败，请重试")
            return
        template_dir = Path(__file__).resolve().parents[2] / "data" / "fishing_templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        target = getattr(self, "_template_picker_target", "a")
        path = template_dir / f"{target}_{uuid4().hex}.png"
        if not image.save(str(path), "PNG"):
            self.set_fishing_status("模板图片保存失败")
            return
        settings = self._fishing_settings_value()
        if target == "a":
            settings.template_a_path = str(path)
            settings.a_source = "template"
            self.a_source_combo.setCurrentIndex(self.a_source_combo.findData("template"))
            self.template_a_label.setText(path.name)
        else:
            settings.template_b_path = str(path)
            settings.b_source = "template"
            self.b_source_combo.setCurrentIndex(self.b_source_combo.findData("template"))
            self.template_b_label.setText(path.name)
        self._fishing_settings = settings
        self._materials.append(MaterialAsset(name=f"钓鱼 {target.upper()} 模板 {path.stem}", kind="template", image_path=str(path), window_title=settings.window_title))
        self.materials_changed.emit(self._materials)
        self._refresh_materials()
        self._emit_fishing_settings()
        self.set_fishing_status(f"已保存 {target.upper()} 图片模板：{path.name}")

    def _selected_vision_preset(self) -> VisionPreset | None:
        preset_id = str(self.vision_preset_combo.currentData() or "")
        return next((item for item in self._vision_presets if item.id == preset_id), None)

    def _refresh_vision_preset_combo(self) -> None:
        selected = self.vision_preset_combo.currentData()
        self.vision_preset_combo.blockSignals(True); self.vision_preset_combo.clear()
        for preset in self._vision_presets:
            self.vision_preset_combo.addItem(preset.name + (" 🔒" if preset.locked else ""), preset.id)
        self.vision_preset_combo.setCurrentIndex(max(0, self.vision_preset_combo.findData(selected)))
        self.vision_preset_combo.blockSignals(False); self._update_vision_preset_controls()

    def _load_selected_vision_preset(self) -> None:
        preset = self._selected_vision_preset()
        if preset is None:
            self._update_vision_preset_controls(); return
        self.vision_preset_name.setText(preset.name)
        self._template_settings = preset.settings
        self.set_data(self._actions, preset.settings, self._fishing_settings, self._fishing_presets, self._materials, self._material_capture, self._vision_presets)
        self._update_vision_preset_controls()

    def _update_vision_preset_controls(self) -> None:
        preset = self._selected_vision_preset(); editable = preset is None or not preset.locked
        self.vision_preset_update.setEnabled(preset is not None and editable); self.vision_preset_delete.setEnabled(preset is not None and editable)
        self.vision_preset_lock.setEnabled(preset is not None); self.vision_preset_lock.setText("解锁预设" if preset and preset.locked else "锁定预设")

    def _emit_vision_presets(self) -> None:
        self.vision_presets_changed.emit(self._vision_presets); self._refresh_vision_preset_combo()

    def _save_new_vision_preset(self) -> None:
        name = self.vision_preset_name.text().strip()
        if not name: self.set_template_status("请输入识图预设名称后再保存"); return
        self._vision_presets.append(VisionPreset(name=name, settings=self._template_settings_value()))
        self._emit_vision_presets(); self.vision_preset_combo.setCurrentIndex(self.vision_preset_combo.count() - 1)

    def _update_selected_vision_preset(self) -> None:
        preset = self._selected_vision_preset(); name = self.vision_preset_name.text().strip()
        if preset is None or preset.locked or not name: return
        preset.name = name; preset.settings = self._template_settings_value(); self._emit_vision_presets()

    def _delete_selected_vision_preset(self) -> None:
        preset = self._selected_vision_preset()
        if preset is None or preset.locked: return
        self._vision_presets.remove(preset); self._emit_vision_presets()

    def _toggle_selected_vision_preset_lock(self) -> None:
        preset = self._selected_vision_preset()
        if preset is None: return
        preset.locked = not preset.locked; self._emit_vision_presets()

    def _refresh_preset_combo(self) -> None:
        selected = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset in self._fishing_presets:
            lock = " 🔒" if preset.locked else ""
            self.preset_combo.addItem(preset.name + lock, preset.id)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(selected)))
        self.preset_combo.blockSignals(False)
        self._update_preset_controls()

    def _selected_preset(self) -> FishingPreset | None:
        preset_id = str(self.preset_combo.currentData() or "")
        return next((item for item in self._fishing_presets if item.id == preset_id), None)

    def _load_selected_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            self._update_preset_controls()
            return
        self.preset_name.setText(preset.name)
        self._fishing_settings = preset.settings
        selected_capture = f"{preset.settings.capture_target}:{preset.settings.a_source if preset.settings.capture_target == 'a' else preset.settings.b_source}"
        self.capture_target_combo.setCurrentIndex(max(0, self.capture_target_combo.findData(selected_capture)))
        self.a_source_combo.setCurrentIndex(max(0, self.a_source_combo.findData(preset.settings.a_source)))
        self.b_source_combo.setCurrentIndex(max(0, self.b_source_combo.findData(preset.settings.b_source)))
        self.fishing_template_threshold.setValue(preset.settings.template_threshold)
        self.template_a_label.setText(Path(preset.settings.template_a_path).name if preset.settings.template_a_path else "未截取模板")
        self.template_b_label.setText(Path(preset.settings.template_b_path).name if preset.settings.template_b_path else "未截取模板")
        self.fishing_color_pick_hotkey.setText(preset.settings.color_pick_hotkey)
        self.fishing_region_pick_hotkey.setText(preset.settings.region_pick_hotkey)
        self.fishing_detection_hotkey.setText(preset.settings.detection_hotkey)
        self.fishing_left_key.setText(preset.settings.left_key)
        self.fishing_right_key.setText(preset.settings.right_key)
        self._refresh_windows(preset.settings.window_title)
        self.region_x.setValue(preset.settings.region_x)
        self.region_y.setValue(preset.settings.region_y)
        self.region_width.setValue(preset.settings.region_width)
        self.region_height.setValue(preset.settings.region_height)
        self._refresh_region_summary()
        self.fishing_hue_tolerance.setValue(preset.settings.hue_tolerance)
        self.fishing_min_area.setValue(preset.settings.min_area)
        self.fishing_b_min_area.setValue(preset.settings.b_min_area)
        self.fishing_input_mode.setCurrentIndex(max(0, self.fishing_input_mode.findData(preset.settings.input_mode)))
        self.fishing_tap_interval.setValue(preset.settings.tap_interval_ms)
        self.fishing_interval.setValue(preset.settings.scan_interval_ms)
        self.fishing_dead_zone.setValue(preset.settings.dead_zone)
        self.fishing_gain.setValue(preset.settings.gain)
        self.fishing_max_step.setValue(preset.settings.max_step)
        self._set_fishing_color_button(preset.settings.color_a_hex, "a")
        self._set_fishing_color_button(preset.settings.color_b_hex, "b")
        self._update_preset_controls()
        self._emit_fishing_settings()

    def _update_preset_controls(self) -> None:
        preset = self._selected_preset()
        editable = preset is None or not preset.locked
        self.preset_update_button.setEnabled(preset is not None and editable)
        self.preset_delete_button.setEnabled(preset is not None and editable)
        self.preset_lock_button.setEnabled(preset is not None)
        self.preset_lock_button.setText("解锁预设" if preset and preset.locked else "锁定预设")

    def _emit_presets(self) -> None:
        self.fishing_presets_changed.emit(self._fishing_presets)
        self._refresh_preset_combo()

    def _save_new_preset(self) -> None:
        name = self.preset_name.text().strip()
        if not name:
            self.set_fishing_status("请输入钓鱼预设名称后再保存")
            return
        self._fishing_presets.append(FishingPreset(name=name, settings=self._fishing_settings_value()))
        self._emit_presets()
        self.preset_combo.setCurrentIndex(self.preset_combo.count() - 1)

    def _update_selected_preset(self) -> None:
        preset = self._selected_preset()
        name = self.preset_name.text().strip()
        if preset is None or preset.locked or not name:
            return
        preset.name = name
        preset.settings = self._fishing_settings_value()
        self._emit_presets()

    def _delete_selected_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None or preset.locked:
            return
        self._fishing_presets.remove(preset)
        self._emit_presets()

    def _toggle_selected_preset_lock(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        preset.locked = not preset.locked
        self._emit_presets()

    def _choose_fishing_color(self, target: str) -> None:
        self.capture_target_combo.setCurrentIndex(max(0, self.capture_target_combo.findData(f"{target}:color")))
        current = self._fishing_settings.color_a_hex if target == "a" else self._fishing_settings.color_b_hex
        color = QColorDialog.getColor(QColor(current), self, f"选择色块 {target.upper()} 的颜色")
        if color.isValid():
            self._set_fishing_color_button(color.name().upper(), target)
            self._emit_fishing_settings()

    def _set_fishing_color_button(self, color_hex: str | None = None, target: str = "a") -> None:
        if color_hex is not None:
            settings = self._fishing_settings_value()
            if target == "a":
                settings.color_a_hex = color_hex
            else:
                settings.color_b_hex = color_hex
            self._fishing_settings = settings
        color_a, color_b = self._fishing_settings.color_a_hex, self._fishing_settings.color_b_hex
        if color_hex is not None and not any(item.kind == "color" and item.color_hex == color_hex for item in self._materials):
            self._materials.append(MaterialAsset(name=f"钓鱼颜色 {color_hex}", kind="color", color_hex=color_hex))
            self.materials_changed.emit(self._materials)
            self._refresh_materials()
        for button, color in ((self.fishing_color_button, color_a), (self.fishing_color_b_button, color_b)):
            button.setText(color)
            button.setStyleSheet(f"background: {color}; color: {'#000000' if QColor(color).lightness() > 128 else '#ffffff'};")

    def _set_template_enabled(self, enabled: bool) -> None:
        self.template_enabled.blockSignals(True)
        self.template_enabled.setChecked(enabled)
        self.template_enabled.blockSignals(False)

    def _set_fishing_enabled(self, enabled: bool) -> None:
        self.fishing_enabled.blockSignals(True)
        self.fishing_enabled.setChecked(enabled)
        self.fishing_enabled.blockSignals(False)
