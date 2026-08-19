from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import ControlSettings, DeviceSettings


class SettingsPage(QWidget):
    save_requested = Signal(DeviceSettings, ControlSettings)
    apply_device_requested = Signal()
    query_device_requested = Signal()
    restore_defaults_requested = Signal()
    elevate_requested = Signal()
    theme_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.screen_width = self._spin(1, 16384)
        self.screen_height = self._spin(1, 16384)
        self.key_press = self._spin(0, 250)
        self.key_release = self._spin(0, 250)
        self.combo_hold = self._spin(0, 250)
        self.mouse_press = self._spin(0, 250)
        self.mouse_click = self._spin(0, 250)
        self.mouse_move = self._spin(0, 250)
        self.max_jump = self._spin(1, 255)
        self.start_hotkey = QLineEdit()
        self.start_hotkey.setPlaceholderText("留空不注册；鼠标前进侧键可启动")
        self.stop_hotkey = QLineEdit()
        self.stop_hotkey.setPlaceholderText("留空不注册；鼠标后退侧键可停止")
        self.side_buttons = QCheckBox("启用鼠标侧键全局控制（前进启动/恢复，后退停止）")
        self.hotkey_status_label = QLabel("系统级快捷键：正在检测…")
        self.mouse_status_label = QLabel("鼠标侧键监听：正在检测…")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色清爽", "light")
        self.theme_combo.addItem("深蓝灰护眼（推荐）", "dark_blue")
        self.theme_combo.currentIndexChanged.connect(lambda: self.theme_changed.emit(str(self.theme_combo.currentData())))
        self.permission_label = QLabel()
        self._device_status: dict[str, str] = {
            "屏幕分辨率": "未读取",
            "普通按键按住": "—",
            "按键释放间隔": "—",
            "组合键修饰键预按": "—",
            "鼠标按住": "—",
            "鼠标点击间隔": "—",
            "移动后间隔": "—",
            "绝对移动最大步长": "—",
        }
        self.device_status_label = QLabel()
        self.device_status_label.setWordWrap(True)
        self._render_device_status()

        device_form = QFormLayout()
        device_form.addRow("屏幕宽度", self.screen_width)
        device_form.addRow("屏幕高度", self.screen_height)
        device_form.addRow("普通按键按住", self.key_press)
        device_form.addRow("按键释放间隔", self.key_release)
        device_form.addRow("组合键修饰键预按", self.combo_hold)
        device_form.addRow("鼠标按住", self.mouse_press)
        device_form.addRow("鼠标点击间隔", self.mouse_click)
        device_form.addRow("移动后间隔", self.mouse_move)
        device_form.addRow("绝对移动最大步长", self.max_jump)

        explanation = QLabel(
            "下发配置会替换单片机的基础延迟，并保留固件已有微抖动；"
            "MC/MCR 使用独立快速点击时序，不受普通鼠标点击延迟影响。\n"
            "恢复默认设置会恢复固件默认值：2560×1440、100/10/50/30/50/50ms、最大步长80px。"
        )
        explanation.setWordWrap(True)

        control_form = QFormLayout()
        control_form.addRow("通用启动/恢复快捷键", self.start_hotkey)
        control_form.addRow("通用停止快捷键", self.stop_hotkey)
        control_form.addRow("侧键控制", self.side_buttons)
        control_form.addRow("快捷键状态", self.hotkey_status_label)
        control_form.addRow("侧键状态", self.mouse_status_label)

        save_button = QPushButton("保存本地设置")
        apply_button = QPushButton("保存并下发到设备")
        query_button = QPushButton("刷新单片机状态")
        reset_button = QPushButton("恢复默认设置")
        reset_button.setObjectName("dangerButton")
        elevate_button = QPushButton("以管理员身份重新启动")
        save_button.clicked.connect(self._emit_save)
        apply_button.clicked.connect(self._save_and_apply)
        query_button.clicked.connect(self.query_device_requested)
        reset_button.clicked.connect(self.restore_defaults_requested)
        elevate_button.clicked.connect(self.elevate_requested)

        device_group = QGroupBox("单片机配置")
        device_layout = QVBoxLayout(device_group)
        device_content = QHBoxLayout()
        local_settings_layout = QVBoxLayout()
        local_settings_layout.addLayout(device_form)
        local_settings_layout.addWidget(explanation)
        self.device_status_group = QGroupBox("单片机状态（设备实际回传）")
        device_status_layout = QVBoxLayout(self.device_status_group)
        device_status_layout.addWidget(QLabel("仅用于和左侧本地编辑值对照，不会自动覆盖本地设置。"))
        device_status_layout.addWidget(self.device_status_label)
        device_status_layout.addStretch()
        device_content.addLayout(local_settings_layout, 2)
        device_content.addWidget(self.device_status_group, 1)
        device_layout.addLayout(device_content)
        control_group = QGroupBox("系统级控制")
        control_group.setLayout(control_form)
        appearance_group = QGroupBox("界面外观")
        appearance_form = QFormLayout(appearance_group)
        appearance_form.addRow("护眼主题", self.theme_combo)
        appearance_form.addRow(QLabel("主题会立即应用并自动保存；不影响正在运行的识图或流程。"))
        permission_group = QGroupBox("应用权限")
        permission_layout = QVBoxLayout(permission_group)
        permission_layout.addWidget(self.permission_label)
        permission_layout.addWidget(elevate_button)
        buttons = QHBoxLayout()
        buttons.addWidget(save_button)
        buttons.addWidget(apply_button)
        buttons.addWidget(query_button)
        buttons.addWidget(reset_button)

        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(device_group)
        layout.addWidget(control_group)
        layout.addWidget(appearance_group)
        layout.addWidget(permission_group)
        layout.addLayout(buttons)
        layout.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.addWidget(scroll)

    @staticmethod
    def _spin(minimum: int, maximum: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setSuffix(" ms" if maximum == 250 else "")
        return box

    def _render_device_status(self) -> None:
        self.device_status_label.setText("\n".join(f"{label}：{value}" for label, value in self._device_status.items()))

    def update_device_status(self, message: str) -> None:
        value_mappings = {
            "{CFG:KEY_PRESS_BASE=": ("普通按键按住", " ms"),
            "{CFG:KEY_RELEASE_BASE=": ("按键释放间隔", " ms"),
            "{CFG:COMBO_MODIFIER_HOLD=": ("组合键修饰键预按", " ms"),
            "{CFG:MOUSE_PRESS_BASE=": ("鼠标按住", " ms"),
            "{CFG:MOUSE_CLICK_GAP=": ("鼠标点击间隔", " ms"),
            "{CFG:MOUSE_MOVE_GAP=": ("移动后间隔", " ms"),
            "{CFG:MOUSE_MAX_JUMP=": ("绝对移动最大步长", " px"),
            "{CFG:SCREEN=": ("屏幕分辨率", ""),
            "{SCR:": ("屏幕分辨率", ""),
        }
        for prefix, (label, suffix) in value_mappings.items():
            if message.startswith(prefix) and message.endswith("}"):
                self._device_status[label] = message[len(prefix):-1] + suffix
                self._render_device_status()
                return

    def set_values(self, device: DeviceSettings, controls: ControlSettings, is_admin: bool) -> None:
        self.screen_width.setValue(device.screen_width)
        self.screen_height.setValue(device.screen_height)
        self.key_press.setValue(device.key_press_delay)
        self.key_release.setValue(device.key_release_delay)
        self.combo_hold.setValue(device.combo_hold_delay)
        self.mouse_press.setValue(device.mouse_press_delay)
        self.mouse_click.setValue(device.mouse_click_delay)
        self.mouse_move.setValue(device.mouse_move_delay)
        self.max_jump.setValue(device.max_jump)
        self.start_hotkey.setText(controls.start_hotkey)
        self.stop_hotkey.setText(controls.stop_hotkey)
        self.side_buttons.setChecked(controls.side_buttons_enabled)
        self.permission_label.setText("当前权限：管理员" if is_admin else "当前权限：普通用户（推荐）")

    def set_theme(self, theme: str) -> None:
        if theme == "warm_gray":
            theme = "dark_blue"
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme)))
        self.theme_combo.blockSignals(False)

    def set_control_status(self, hotkeys: str, mouse_side_buttons: str) -> None:
        self.hotkey_status_label.setText(hotkeys)
        self.mouse_status_label.setText(mouse_side_buttons)

    def _device_settings(self) -> DeviceSettings:
        return DeviceSettings(
            screen_width=self.screen_width.value(),
            screen_height=self.screen_height.value(),
            key_press_delay=self.key_press.value(),
            key_release_delay=self.key_release.value(),
            combo_hold_delay=self.combo_hold.value(),
            mouse_press_delay=self.mouse_press.value(),
            mouse_click_delay=self.mouse_click.value(),
            mouse_move_delay=self.mouse_move.value(),
            max_jump=self.max_jump.value(),
        )

    def _control_settings(self) -> ControlSettings:
        return ControlSettings(
            start_hotkey=self.start_hotkey.text().strip(),
            stop_hotkey=self.stop_hotkey.text().strip(),
            side_buttons_enabled=self.side_buttons.isChecked(),
        )

    def _emit_save(self) -> None:
        self.save_requested.emit(self._device_settings(), self._control_settings())

    def _save_and_apply(self) -> None:
        self._emit_save()
        self.apply_device_requested.emit()
