from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import ActionKind, ActionStep, STEP_LABELS
from .duration_input import DurationInput
from .keyboard_picker import KeyboardPicker


MOUSE_BUTTONS = [
    ("左键", "LEFT"),
    ("右键", "RIGHT"),
    ("中键", "MIDDLE"),
    ("后退侧键", "BACK"),
    ("前进侧键", "FORWARD"),
]


class StepInputPanel(QWidget):
    """按步骤类型显示专用输入控件，并产生固件可识别的 ActionStep。"""

    changed = Signal()
    move_preview_requested = Signal(ActionStep)

    def __init__(self, keyboard_height: int = 240) -> None:
        super().__init__()
        self.kind_combo = QComboBox()
        for kind in ActionKind:
            self.kind_combo.addItem(STEP_LABELS[kind], kind.value)

        self._keyboard_height = max(270, keyboard_height)
        self.keyboard_picker = KeyboardPicker()
        self.keyboard_picker.setMinimumHeight(self._keyboard_height)
        self.mouse_combo = QComboBox()
        for label, value in MOUSE_BUTTONS:
            self.mouse_combo.addItem(label, value)
        self._invalid_mouse_value = ""
        self.mouse_warning = QLabel()
        self.mouse_warning.setWordWrap(True)
        self.mouse_warning.setStyleSheet("color: #b33b46;")
        self.mouse_combo.currentIndexChanged.connect(self._clear_invalid_mouse)
        self.x_input = QSpinBox()
        self.y_input = QSpinBox()
        self.move_hint = QLabel()
        self.move_hint.setWordWrap(True)
        self.move_status_label = QLabel("手动移动仅发送一次命令，不会保存步骤。")
        self.move_status_label.setWordWrap(True)
        self.test_move_button = QPushButton("按当前参数试移（不保存）")
        self.test_move_button.clicked.connect(self._emit_move_preview)
        self.wheel_input = QSpinBox()
        self.wheel_input.setRange(-127, 127)
        self.wheel_up_button = QPushButton("滚轮上")
        self.wheel_down_button = QPushButton("滚轮下")
        self.wheel_up_button.clicked.connect(lambda: self._use_wheel_shortcut(1))
        self.wheel_down_button.clicked.connect(lambda: self._use_wheel_shortcut(-1))
        self.wait_duration = DurationInput(maximum_milliseconds=86_400_000)
        self.raw_input = QLineEdit()
        self.raw_input.setPlaceholderText("例如 {CTRL+C}；仅用于调试")
        self.after_duration = DurationInput(maximum_milliseconds=3_600_000)
        self.random_wait_min = DurationInput(maximum_milliseconds=3_600_000, allow_zero=True)
        self.random_wait_max = DurationInput(maximum_milliseconds=3_600_000, allow_zero=True)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._keyboard_page())  # 0
        self.stack.addWidget(self._mouse_page())     # 1
        self.stack.addWidget(self._move_page())      # 2
        self.stack.addWidget(self._wheel_page())     # 3
        self.stack.addWidget(self._wait_page())      # 4
        self.stack.addWidget(self._raw_page())       # 5

        self.rhythm_toggle = QToolButton(); self.rhythm_toggle.setCheckable(True); self.rhythm_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.rhythm_toggle.clicked.connect(self._toggle_rhythm_panel)
        type_row = QHBoxLayout(); type_row.addWidget(self.kind_combo, 1); type_row.addWidget(self.rhythm_toggle)
        type_form = QFormLayout(); type_form.addRow("步骤类型", type_row)
        self.rhythm_panel = QFrame(); self.rhythm_panel.setObjectName("rhythmPanel")
        self.rhythm_panel.setStyleSheet("QFrame#rhythmPanel { background:#f8fafc; border:1px solid #dbe4ef; border-radius:7px; }")
        rhythm_form = QFormLayout(self.rhythm_panel)
        rhythm_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        rhythm_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rhythm_form.setHorizontalSpacing(12)
        self.random_wait_min_label = self._rhythm_label("执行前随机等待（最小）", "随机等待区间的下限；设为 0 表示可立即执行。")
        self.random_wait_max_label = self._rhythm_label("执行前随机等待（最大）", "随机等待区间的上限；小于最小值时会自动按有效区间处理。")
        self.after_label = self._rhythm_label("步骤后固定等待", "当前步骤执行完成后，再等待指定时长。")
        rhythm_form.addRow(self.random_wait_min_label, self.random_wait_min)
        rhythm_form.addRow(self.random_wait_max_label, self.random_wait_max)
        rhythm_form.addRow(self.after_label, self.after_duration)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(type_form)
        wheel_shortcuts = QHBoxLayout()
        wheel_shortcuts.addWidget(QLabel("快速滚轮"))
        wheel_shortcuts.addWidget(self.wheel_up_button)
        wheel_shortcuts.addWidget(self.wheel_down_button)
        wheel_shortcuts.addStretch()
        layout.addLayout(wheel_shortcuts)
        layout.addWidget(QLabel("步骤设置"))
        layout.addWidget(self.stack)
        layout.addWidget(self.rhythm_panel)

        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.random_wait_min.value_changed.connect(self._update_rhythm_summary)
        self.random_wait_max.value_changed.connect(self._update_rhythm_summary)
        self.after_duration.value_changed.connect(self._update_rhythm_summary)
        self.keyboard_picker.key_selected.connect(self._use_key)
        self._kind_changed()
        self.rhythm_panel.setVisible(False)
        self._update_rhythm_summary()

    @staticmethod
    def _rhythm_label(text: str, tooltip: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(128)
        label.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        label.setToolTip(tooltip)
        return label

    def _keyboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("点击键帽选择按键；组合键可依次点击 Ctrl、Shift、Alt、Win 和主键。键盘完整显示，页面右侧统一滚动。"))
        layout.addWidget(self.keyboard_picker)
        return page

    def _mouse_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("鼠标按钮", self.mouse_combo)
        form.addRow(self.mouse_warning)
        return page

    def _move_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.addRow("X", self.x_input)
        form.addRow("Y", self.y_input)
        layout.addLayout(form)
        layout.addWidget(self.move_hint)
        layout.addWidget(self.test_move_button)
        layout.addWidget(self.move_status_label)
        return page

    def _wheel_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("滚动格数（正/负方向）", self.wheel_input)
        return page

    def _wait_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("等待时长", self.wait_duration)
        return page

    def _raw_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("原始串口命令", self.raw_input)
        return page

    def _use_wheel_shortcut(self, amount: int) -> None:
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(ActionKind.WHEEL)))
        self.wheel_input.setValue(amount)
        self.changed.emit()

    def _toggle_rhythm_panel(self, checked: bool) -> None:
        self.rhythm_panel.setVisible(checked)
        self._update_rhythm_summary()

    def _update_rhythm_summary(self) -> None:
        minimum, maximum, after = self.random_wait_min.milliseconds(), self.random_wait_max.milliseconds(), self.after_duration.milliseconds()
        if minimum > maximum: minimum, maximum = maximum, minimum
        if not minimum and not maximum and not after:
            text = "节奏设置：未设置"
        else:
            parts = []
            if maximum: parts.append(f"前 {minimum / 1000:g}～{maximum / 1000:g} 秒")
            if after: parts.append(f"后 {after / 1000:g} 秒")
            text = "节奏：" + "，".join(parts)
        self.rhythm_toggle.setText(("收起 " if self.rhythm_panel.isVisible() else "") + text + " ▾")

    def _kind_changed(self) -> None:
        kind = str(self.kind_combo.currentData())
        self.stack.setMinimumHeight(64)
        self.stack.setMaximumHeight(16_777_215)
        if kind in {ActionKind.KEY_TAP, ActionKind.KEY_COMBO, ActionKind.KEY_DOWN, ActionKind.KEY_UP}:
            self.stack.setCurrentIndex(0)
            # 内层不滚动：给提示文字与完整键盘选择器预留真实高度，由外层编辑区统一滚动。
            keyboard_height = self.keyboard_picker.sizeHint().height() + 42
            self.stack.setMinimumHeight(keyboard_height)
            self.stack.setMaximumHeight(keyboard_height)
            self.after_label.setVisible(True)
            self.after_duration.setVisible(True)
        elif kind in {ActionKind.MOUSE_CLICK, ActionKind.MOUSE_BUTTON_DOWN, ActionKind.MOUSE_BUTTON_UP}:
            self.stack.setCurrentIndex(1)
            self.after_label.setVisible(True)
            self.after_duration.setVisible(True)
        elif kind in {ActionKind.MOVE_PIXEL, ActionKind.MOVE_NORMALIZED, ActionKind.MOVE_RELATIVE}:
            self.stack.setCurrentIndex(2)
            self._configure_move_inputs(kind)
            self.after_label.setVisible(True)
            self.after_duration.setVisible(True)
        elif kind == ActionKind.WHEEL:
            self.stack.setCurrentIndex(3)
            self.after_label.setVisible(True)
            self.after_duration.setVisible(True)
        elif kind == ActionKind.WAIT:
            self.stack.setCurrentIndex(4)
            self.after_label.setVisible(False)
            self.after_duration.setVisible(False)
        else:
            self.stack.setCurrentIndex(5)
            self.after_label.setVisible(True)
            self.after_duration.setVisible(True)
        self._update_rhythm_summary()
        self.changed.emit()

    def _configure_move_inputs(self, kind: str) -> None:
        if kind == ActionKind.MOVE_NORMALIZED:
            self.x_input.setRange(0, 1000)
            self.y_input.setRange(0, 1000)
            self.move_hint.setText("比例绝对定位：X/Y 范围 0～1000；0,0 为左上，500,500 为屏幕中心，1000,1000 为右下。更换分辨率后仍保持相同相对位置。")
        elif kind == ActionKind.MOVE_PIXEL:
            self.x_input.setRange(0, 16384)
            self.y_input.setRange(0, 16384)
            self.move_hint.setText("像素绝对定位：X/Y 使用“设置”中的屏幕宽高；0,0 为左上角。实体鼠标手动移动会与单片机的内部位置记录脱节，可能使绝对定位不准。")
        else:
            self.x_input.setRange(-32767, 32767)
            self.y_input.setRange(-32767, 32767)
            self.move_hint.setText("相对移动：从当前位置偏移 DX/DY；右、下为正，左、上为负。不依赖屏幕分辨率，适合镜头转向或固定距离移动。")

    def set_move_preview_status(self, message: str) -> None:
        self.move_status_label.setText(message)

    def _emit_move_preview(self) -> None:
        kind = str(self.kind_combo.currentData())
        if kind in {ActionKind.MOVE_PIXEL, ActionKind.MOVE_NORMALIZED, ActionKind.MOVE_RELATIVE}:
            x, y = self.x_input.value(), self.y_input.value()
            if x == 0 and y == 0:
                self.set_move_preview_status("已请求试移：当前参数为 0,0；若光标或单片机记录已在左上，视觉上不会产生位移。")
            else:
                self.set_move_preview_status("正在请求按当前参数试移…")
            self.move_preview_requested.emit(ActionStep(kind=kind, value=f"{x}_{y}"))


    def _clear_invalid_mouse(self) -> None:
        if self._invalid_mouse_value:
            self._invalid_mouse_value = ""
            self.mouse_warning.clear()

    def _use_key(self, key_code: str) -> None:
        kind = str(self.kind_combo.currentData())
        if kind == ActionKind.KEY_COMBO:
            current = getattr(self, "_key_value", "")
            self._key_value = f"{current}+{key_code}" if current else key_code
        else:
            self._key_value = key_code
        self.changed.emit()

    def build_step(self) -> ActionStep:
        kind = str(self.kind_combo.currentData())
        if kind in {ActionKind.KEY_TAP, ActionKind.KEY_COMBO, ActionKind.KEY_DOWN, ActionKind.KEY_UP}:
            value = getattr(self, "_key_value", "")
        elif kind in {ActionKind.MOUSE_CLICK, ActionKind.MOUSE_BUTTON_DOWN, ActionKind.MOUSE_BUTTON_UP}:
            value = self._invalid_mouse_value or str(self.mouse_combo.currentData())
        elif kind in {ActionKind.MOVE_PIXEL, ActionKind.MOVE_NORMALIZED, ActionKind.MOVE_RELATIVE}:
            value = f"{self.x_input.value()}_{self.y_input.value()}"
        elif kind == ActionKind.WHEEL:
            value = str(self.wheel_input.value())
        elif kind == ActionKind.WAIT:
            return ActionStep(kind=kind, value=str(self.wait_duration.milliseconds()), delay_after_ms=0, random_wait_min_ms=self.random_wait_min.milliseconds(), random_wait_max_ms=self.random_wait_max.milliseconds())
        else:
            value = self.raw_input.text().strip()
        return ActionStep(kind=kind, value=value, delay_after_ms=self.after_duration.milliseconds(), random_wait_min_ms=self.random_wait_min.milliseconds(), random_wait_max_ms=self.random_wait_max.milliseconds())

    def set_step(self, step: ActionStep) -> None:
        self.random_wait_min.set_milliseconds(step.random_wait_min_ms)
        self.random_wait_max.set_milliseconds(step.random_wait_max_ms)
        index = self.kind_combo.findData(step.kind)
        self.kind_combo.setCurrentIndex(max(0, index))
        kind = step.kind
        if kind in {ActionKind.KEY_TAP, ActionKind.KEY_COMBO, ActionKind.KEY_DOWN, ActionKind.KEY_UP}:
            self._key_value = step.value
        elif kind in {ActionKind.MOUSE_CLICK, ActionKind.MOUSE_BUTTON_DOWN, ActionKind.MOUSE_BUTTON_UP}:
            mouse_index = self.mouse_combo.findData(step.value)
            if mouse_index >= 0:
                self._invalid_mouse_value = ""
                self.mouse_warning.clear()
                self.mouse_combo.setCurrentIndex(mouse_index)
            else:
                self._invalid_mouse_value = step.value
                self.mouse_warning.setText(f"历史配置中的鼠标按钮“{step.value}”无效；请选择正确按钮后再更新该步骤。")
        elif kind in {ActionKind.MOVE_PIXEL, ActionKind.MOVE_NORMALIZED, ActionKind.MOVE_RELATIVE}:
            try:
                x_value, y_value = step.value.split("_", 1)
                self.x_input.setValue(int(x_value))
                self.y_input.setValue(int(y_value))
            except (ValueError, TypeError):
                self.x_input.setValue(0)
                self.y_input.setValue(0)
        elif kind == ActionKind.WHEEL:
            try:
                self.wheel_input.setValue(int(step.value))
            except ValueError:
                self.wheel_input.setValue(0)
        elif kind == ActionKind.WAIT:
            try:
                self.wait_duration.set_milliseconds(int(step.value))
            except ValueError:
                self.wait_duration.set_milliseconds(0)
        else:
            self.raw_input.setText(step.value)
        self.after_duration.set_milliseconds(step.delay_after_ms)
        self._update_rhythm_summary()
