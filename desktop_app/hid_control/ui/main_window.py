from __future__ import annotations

import time
from copy import deepcopy

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QCloseEvent, QGuiApplication, QPalette, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..fishing import FishingService
from ..hotkeys import GlobalHotkeyService
from ..models import ActionKind, ActionStep, AppState, ControlSettings, DeviceSettings, FishingPreset, FishingSettings, MaterialCaptureSettings, VisionSettings, WorkflowDefinition
from ..mouse_hook import MouseSideButtonService
from ..privilege import is_administrator, restart_as_administrator
from ..protocol import ProtocolError, command_for_step, device_configuration_commands
from ..serial_service import SerialService
from ..storage import SettingsStore
from ..vision import VisionService
from ..window_capture import primary_screen_resolution, window_by_title
from ..workflow import WorkflowRunner
from .ab_flow_page import ABFlowPage
from .action_editor import ActionEditor
from .custom_flow_page import CustomFlowPage
from .dashboard import Dashboard
from .settings import SettingsPage
from .vision_page import VisionPage


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: SettingsStore,
        state: AppState,
        serial_service: SerialService,
        workflow_runner: WorkflowRunner,
        hotkeys: GlobalHotkeyService,
        mouse_buttons: MouseSideButtonService,
    ) -> None:
        super().__init__()
        self._store = store
        self._state = state
        # 初始化 resize 会发生在 app.py 恢复最小化状态之前，期间不得覆盖已保存状态。
        self._restoring_window_state = self._state.window_layout.last_window_state != "normal"
        screen_width, screen_height = primary_screen_resolution()
        self._state.device.screen_width = screen_width
        self._state.device.screen_height = screen_height
        self._serial = serial_service
        self._runner = workflow_runner
        self._hotkeys = hotkeys
        self._mouse_buttons = mouse_buttons
        self._vision = VisionService()
        self._fishing = FishingService()
        self._template_started_at = 0.0
        self._template_triggered = False
        self._workflow_vision_preset_id = ""
        self._active_workflow_vision_settings: VisionSettings | None = None
        self._workflow_fishing_active = False
        self._active_fishing_settings: FishingSettings | None = None
        self._fishing_pending_direction = 0
        self._fishing_direction_frames = 0
        self._last_fishing_tap_at = 0.0
        self._fishing_pressed_key = ""
        self._hotkey_status = "系统级快捷键：未启用"
        self._mouse_status = "鼠标侧键监听：正在检测…"
        self._hotkey_labels: dict[str, str] = {}
        self._hotkey_signature: tuple[tuple[str, str], ...] | None = None
        self._checkbox_texts: dict[QCheckBox, str] = {}
        self._last_template_result_ui_at = 0.0
        self._last_fishing_result_ui_at = 0.0
        self._last_fishing_result_state = ""
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.timeout.connect(self._save_state)

        self.setWindowTitle("祥子の宝贝")
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        width = min(available.width(), max(1180, int(available.width() * self._state.window_layout.width_ratio)))
        height = min(available.height(), max(760, int(available.height() * self._state.window_layout.height_ratio)))
        self.resize(width, height)
        self.setMinimumSize(1180, 760)

        self.dashboard = Dashboard()
        self.actions_page = ActionEditor()
        self.ab_flow_page = ABFlowPage()
        self.custom_flow_page = CustomFlowPage()
        self.vision_page = VisionPage()
        self.settings_page = SettingsPage()
        self.pages = QStackedWidget()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.actions_page)
        self.pages.addWidget(self.ab_flow_page)
        self.pages.addWidget(self.custom_flow_page)
        self.pages.addWidget(self.vision_page)
        self.pages.addWidget(self.settings_page)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setMinimumWidth(98)
        for title in ("控制台", "操作编辑", "AB流程", "自定义流程", "AI识别", "设置"):
            self.navigation.addItem(QListWidgetItem(title))
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation_toggle = QToolButton()
        self.navigation_toggle.setObjectName("navigationToggle")
        self.navigation_toggle.setFixedSize(32, 32)
        self.navigation_toggle.clicked.connect(self._toggle_navigation)
        self._navigation_panel = QWidget()
        navigation_layout = QVBoxLayout(self._navigation_panel)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(0)
        navigation_layout.addWidget(self.navigation, 1)

        shell = QWidget()
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._navigation_panel, 0)
        layout.addWidget(self.pages, 1)
        self.navigation_toggle.setParent(shell)
        self.setCentralWidget(shell)
        self._apply_style()
        self._configure_checkbox_labels()
        self._set_navigation_collapsed(self._state.window_layout.navigation_collapsed)
        self._wire_events()
        self._refresh_ui()
        self._save_state()
        self._refresh_ports()
        self._configure_global_controls()
        self._log("应用已就绪。请连接 Leonardo 后再启动流程。")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_navigation_toggle()
        if not self._restoring_window_state and not self.isMinimized() and not self.isMaximized():
            screen = self.screen() or QGuiApplication.primaryScreen()
            available = screen.availableGeometry() if screen else self.geometry()
            self._state.window_layout.width_ratio = max(0.35, min(1.0, self.width() / max(1, available.width())))
            self._state.window_layout.height_ratio = max(0.35, min(1.0, self.height() / max(1, available.height())))
            self._state.window_layout.last_window_state = "normal"
            self._layout_save_timer.start(350)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._state.window_layout.last_window_state = "minimized" if self.isMinimized() else ("maximized" if self.isMaximized() else "normal")
            self._layout_save_timer.start(0 if self.isMinimized() else 350)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 在 show/showMinimized 结束后再允许常规 resize 保存比例。
        QTimer.singleShot(0, lambda: setattr(self, "_restoring_window_state", False))

    def _position_navigation_toggle(self) -> None:
        shell = self.centralWidget()
        if shell is None:
            return
        collapsed = self._state.window_layout.navigation_collapsed
        seam_x = 6 if collapsed else self._navigation_panel.width() - self.navigation_toggle.width() // 2
        seam_y = 12 if collapsed else max(12, (shell.height() - self.navigation_toggle.height()) // 2)
        self.navigation_toggle.move(seam_x, seam_y)
        self.navigation_toggle.raise_()

    def _apply_style(self) -> None:
        common = """
            QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimSun"; font-size: 13px; }
            #navigation { border: 0; padding: 8px 7px; }
            #navigation::item { padding: 10px 9px; border-radius: 8px; margin: 3px 0; }
            #navigationToggle { border: 1px solid rgba(203, 213, 225, 150); border-radius: 14px; padding: 0; }
            #pageTitle { font-size: 22px; font-weight: 700; padding: 4px 0 9px 0; }
            QPushButton { border-radius: 7px; padding: 6px 10px; min-height: 18px; }
            QPushButton#keyboardKey { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimSun"; font-size: 10px; line-height: 1.15; padding: 1px; min-height: 28px; }
            QPushButton#primaryButton { background: #2563eb; color: white; border: 1px solid #2563eb; font-weight: 700; }
            QPushButton#dangerButton { background: #d84a5a; color: white; border: 1px solid #d84a5a; font-weight: 700; }
            QFrame#statusCard { border-radius: 10px; min-height: 62px; }
            QLabel#statusCardCaption { font-size: 11px; font-weight: 600; }
            QLabel#statusCardValue { font-size: 13px; font-weight: 700; }
            QLabel#pageSubtitle { color: #64748b; }
            QLabel#sectionLabel { font-weight: 700; padding-top: 6px; }
            QGroupBox { border-radius: 9px; margin-top: 10px; padding: 10px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel[connected="true"] { color: #168255; font-weight: 700; }
            QLabel[connected="false"] { color: #b34353; font-weight: 700; }
        """
        colors = self._theme_colors(self._state.window_layout.theme)
        palette = self.palette()
        roles = {
            QPalette.ColorRole.Window: colors["window"],
            QPalette.ColorRole.WindowText: colors["text"],
            QPalette.ColorRole.Base: colors["input"],
            QPalette.ColorRole.AlternateBase: colors["card"],
            QPalette.ColorRole.Text: colors["text"],
            QPalette.ColorRole.Button: colors["button"],
            QPalette.ColorRole.ButtonText: colors["button_text"],
            QPalette.ColorRole.Highlight: colors["selected"],
            QPalette.ColorRole.HighlightedText: colors["selected_text"],
            QPalette.ColorRole.ToolTipBase: colors["card"],
            QPalette.ColorRole.ToolTipText: colors["text"],
        }
        for role, color in roles.items():
            palette.setColor(role, QColor(color))
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet(common + self._theme_style(self._state.window_layout.theme))

    @staticmethod
    def _theme_colors(theme: str) -> dict[str, str]:
        palettes = {
            "light": {
                "window": "#f4f7fb", "text": "#172536", "nav": "#182437", "nav_text": "#e4edf7", "nav_hover": "#243852", "nav_selected": "#2f6fbd", "button": "#d0e0f0", "button_text": "#173c61", "button_hover": "#b8d0e6", "button_pressed": "#9cbedb", "border": "#9cb8d2", "card": "#ffffff", "input": "#ffffff", "focus": "#256fba", "muted": "#405873", "disabled": "#6a7f95", "selected": "#cce0f7", "selected_text": "#123e70", "item_hover": "#e4f0fb", "tab": "#d9e7f4", "primary": "#1f67b8", "primary_hover": "#1559a6", "danger": "#c44355", "danger_hover": "#a93446", "success": "#087a4c", "warning": "#895a06",
            },
            "dark_blue": {
                "window": "#28394d", "text": "#f0f5fa", "nav": "#202f41", "nav_text": "#e0e9f2", "nav_hover": "#3a516b", "nav_selected": "#4d89d8", "button": "#46627f", "button_text": "#f7fbff", "button_hover": "#597897", "button_pressed": "#39546e", "border": "#7590ab", "card": "#354b63", "input": "#2c3e53", "focus": "#8fc0ff", "muted": "#d0dce8", "disabled": "#aab9c8", "selected": "#52749a", "selected_text": "#ffffff", "item_hover": "#405b78", "tab": "#30465d", "primary": "#4d89d8", "primary_hover": "#7badf0", "danger": "#d97682", "danger_hover": "#ee8d99", "success": "#6fc39a", "warning": "#ecc676",
            },
        }
        return palettes.get(theme, palettes["light"])

    @staticmethod
    def _theme_style(theme: str) -> str:
        colors = MainWindow._theme_colors(theme)
        return f"""
            QMainWindow, QDialog, QMessageBox, QStackedWidget {{ background: {colors['window']}; color: {colors['text']}; }}
            QWidget {{ color: {colors['text']}; }}
            QLabel {{ background: transparent; color: {colors['text']}; }}
            QMenu, QToolTip {{ background: {colors['card']}; color: {colors['text']}; border: 1px solid {colors['border']}; }}
            QMenu::item:selected {{ background: {colors['selected']}; color: {colors['selected_text']}; }}
            #navigation {{ background: {colors['nav']}; color: {colors['nav_text']}; }}
            #navigationToggle {{ background: {colors['nav']}; color: {colors['nav_text']}; border-color: {colors['border']}; }}
            #navigationToggle:hover {{ background: {colors['nav_hover']}; }}
            QToolButton {{ background: {colors['button']}; color: {colors['button_text']}; border: 1px solid {colors['border']}; border-radius: 6px; }}
            QToolButton:hover {{ background: {colors['button_hover']}; border-color: {colors['focus']}; }}
            #navigation::item:hover {{ background: {colors['nav_hover']}; }}
            #navigation::item:selected {{ background: {colors['nav_selected']}; color: #ffffff; }}
            QPushButton {{ background: {colors['button']}; color: {colors['button_text']}; border: 1px solid {colors['border']}; }}
            QPushButton:hover {{ background: {colors['button_hover']}; border-color: {colors['focus']}; }}
            QPushButton:pressed {{ background: {colors['button_pressed']}; }}
            QPushButton#primaryButton {{ background: {colors['primary']}; color: #ffffff; border-color: {colors['primary']}; }}
            QPushButton#primaryButton:hover {{ background: {colors['primary_hover']}; border-color: {colors['primary_hover']}; }}
            QPushButton#dangerButton {{ background: {colors['danger']}; color: #ffffff; border-color: {colors['danger']}; }}
            QPushButton#dangerButton:hover {{ background: {colors['danger_hover']}; border-color: {colors['danger_hover']}; }}
            QPushButton[actionRole="primaryAction"] {{ background: {colors['primary']}; color: #ffffff; border-color: {colors['primary']}; font-weight: 600; }}
            QPushButton[actionRole="primaryAction"]:hover {{ background: {colors['primary_hover']}; border-color: {colors['primary_hover']}; }}
            QPushButton[actionRole="successAction"] {{ background: {colors['success']}; color: #ffffff; border-color: {colors['success']}; font-weight: 600; }}
            QPushButton[actionRole="successAction"]:hover {{ background: {colors['primary_hover']}; border-color: {colors['primary_hover']}; }}
            QPushButton[actionRole="dangerAction"] {{ background: {colors['danger']}; color: #ffffff; border-color: {colors['danger']}; font-weight: 600; }}
            QPushButton[actionRole="dangerAction"]:hover {{ background: {colors['danger_hover']}; border-color: {colors['danger_hover']}; }}
            QPushButton[actionRole="secondaryAction"] {{ background: {colors['tab']}; color: {colors['button_text']}; border-color: {colors['border']}; font-weight: 600; }}
            QPushButton[actionRole="secondaryAction"]:hover {{ background: {colors['button_hover']}; border-color: {colors['focus']}; }}
            QPushButton:disabled {{ color: {colors['disabled']}; background: {colors['button_pressed']}; border-color: {colors['border']}; }}
            QCheckBox {{ color: {colors['text']}; padding: 4px 7px 4px 4px; border: 1px solid transparent; border-radius: 6px; spacing: 8px; }}
            QCheckBox:hover {{ background: {colors['item_hover']}; border-color: {colors['border']}; }}
            QCheckBox:checked {{ background: {colors['selected']}; color: {colors['selected_text']}; border-color: {colors['focus']}; font-weight: 700; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 2px solid {colors['muted']}; background: {colors['input']}; }}
            QCheckBox::indicator:hover {{ border-color: {colors['focus']}; }}
            QCheckBox::indicator:checked {{ background: {colors['primary']}; border-color: {colors['primary_hover']}; }}
            QCheckBox:disabled {{ color: {colors['disabled']}; background: transparent; border-color: transparent; }}
            QCheckBox::indicator:disabled {{ background: {colors['button_pressed']}; border-color: {colors['disabled']}; }}
            QFrame#statusCard, QGroupBox {{ background: {colors['card']}; border-color: {colors['border']}; }}
            QLabel#statusCardCaption, QLabel#pageSubtitle {{ color: {colors['muted']}; }}
            QLabel#statusCardValue {{ color: {colors['text']}; }}
            QLabel#statusCardValue[level="success"] {{ color: {colors['success']}; }}
            QLabel#statusCardValue[level="danger"] {{ color: {colors['danger_hover']}; }}
            QLabel#sectionLabel {{ color: {colors['primary_hover']}; }}
            QListWidget::item {{ border-radius: 7px; padding: 3px; }}
            QListWidget::item:selected {{ background: {colors['selected']}; color: {colors['selected_text']}; }}
            QListWidget::item:hover {{ background: {colors['item_hover']}; }}
            QPushButton#keyboardKey {{ background: {colors['button']}; color: {colors['button_text']}; border-color: {colors['border']}; }}
            QPushButton#keyboardKey:hover {{ background: {colors['button_hover']}; border-color: {colors['focus']}; }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTreeWidget, QTableWidget, QPlainTextEdit {{ background: {colors['input']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 7px; padding: 5px; }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {colors['focus']}; background: {colors['input']}; }}
            QComboBox QAbstractItemView {{ background: {colors['input']}; color: {colors['text']}; selection-background-color: {colors['selected']}; selection-color: {colors['selected_text']}; border: 1px solid {colors['border']}; }}
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ border: 0; background: {colors['window']}; }}
            QScrollBar:vertical {{ background: {colors['window']}; width: 10px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {colors['border']}; min-height: 28px; border-radius: 5px; }}
            QScrollBar::handle:vertical:hover {{ background: {colors['button_hover']}; }}
            QTabWidget::pane {{ border: 1px solid {colors['border']}; border-radius: 8px; background: {colors['card']}; }}
            QTabBar::tab {{ background: {colors['tab']}; color: {colors['muted']}; padding: 7px 13px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }}
            QTabBar::tab:selected {{ background: {colors['card']}; color: {colors['primary_hover']}; font-weight: 600; }}
        """

    def _configure_checkbox_labels(self) -> None:
        for checkbox in self.findChildren(QCheckBox):
            if checkbox in self._checkbox_texts:
                continue
            self._checkbox_texts[checkbox] = checkbox.text()
            checkbox.toggled.connect(lambda checked, item=checkbox: self._update_checkbox_label(item, checked))
            self._update_checkbox_label(checkbox, checkbox.isChecked())

    @staticmethod
    def _checkbox_display_text(text: str, checked: bool) -> str:
        return f"{'✓ 已选' if checked else '○ 未选'} · {text}"

    def _update_checkbox_label(self, checkbox: QCheckBox, checked: bool) -> None:
        original = self._checkbox_texts.get(checkbox)
        if original is None:
            return
        checkbox.setText(self._checkbox_display_text(original, checked))
        checkbox.setProperty("selectionState", "checked" if checked else "unchecked")
        checkbox.style().unpolish(checkbox)
        checkbox.style().polish(checkbox)

    def _toggle_navigation(self) -> None:
        self._set_navigation_collapsed(not self._state.window_layout.navigation_collapsed)
        self._save_state()

    def _set_navigation_collapsed(self, collapsed: bool) -> None:
        self._state.window_layout.navigation_collapsed = collapsed
        self.navigation.setVisible(not collapsed)
        self._navigation_panel.setFixedWidth(0 if collapsed else 106)
        self.navigation_toggle.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.LeftArrow)
        self.navigation_toggle.setToolTip("展开主导航" if collapsed else "收起主导航，为工作区腾出空间")
        QTimer.singleShot(0, self._position_navigation_toggle)

    def _wire_events(self) -> None:
        self.dashboard.refresh_requested.connect(self._refresh_ports)
        self.dashboard.connect_requested.connect(self._connect)
        self.dashboard.disconnect_requested.connect(self._serial.disconnect)
        self.dashboard.start_requested.connect(self._start_active_target)
        self.dashboard.stop_requested.connect(self._stop_workflow)
        self.dashboard.target_selected.connect(self._target_selected)
        self.dashboard.sync_requested.connect(self._apply_device_configuration)
        self.dashboard.query_requested.connect(self._serial.request_device_state)
        self.dashboard.preflight_requested.connect(self._run_preflight)

        self.actions_page.actions_changed.connect(self._actions_changed)
        self.actions_page.create_workflow_requested.connect(self._create_workflow_for_action)
        self.actions_page.step_input.move_preview_requested.connect(lambda step: self._preview_move(step, self.actions_page.step_input))
        self.ab_flow_page.workflows_changed.connect(self._workflows_changed)
        self.ab_flow_page.active_workflow_changed.connect(self._active_workflow_changed)
        self.custom_flow_page.workflows_changed.connect(self._workflows_changed)
        self.custom_flow_page.active_workflow_changed.connect(self._active_workflow_changed)
        self.vision_page.template_settings_changed.connect(self._vision_settings_changed)
        self.vision_page.template_enabled_changed.connect(self._vision_enabled_changed)
        self.vision_page.fishing_settings_changed.connect(self._fishing_settings_changed)
        self.vision_page.fishing_enabled_changed.connect(self._fishing_enabled_changed)
        self.vision_page.fishing_presets_changed.connect(self._fishing_presets_changed)
        self.vision_page.materials_changed.connect(self._materials_changed)
        self.vision_page.material_capture_settings_changed.connect(self._material_capture_settings_changed)
        self.vision_page.vision_presets_changed.connect(self._vision_presets_changed)

        self.settings_page.save_requested.connect(self._save_settings)
        self.settings_page.apply_device_requested.connect(self._apply_device_configuration)
        self.settings_page.query_device_requested.connect(self._serial.request_device_state)
        self.settings_page.restore_defaults_requested.connect(self._restore_device_defaults)
        self.settings_page.elevate_requested.connect(self._restart_elevated)
        self.settings_page.theme_changed.connect(self._theme_changed)

        self._serial.message_sent.connect(lambda message: self._log(f"→ {message}"))
        self._serial.message_received.connect(self._serial_message_received)
        self._serial.error_occurred.connect(self._log)
        self._serial.connection_changed.connect(self._connection_changed)
        self._runner.log_message.connect(self._log)
        self._runner.status_changed.connect(self._workflow_status_changed)
        self._vision.status_changed.connect(self._vision_status_changed)
        self._vision.match_updated.connect(self._template_match_updated)
        self._vision.rule_matched.connect(self._vision_rule_matched)
        self._fishing.status_changed.connect(self._fishing_status_changed)
        self._fishing.target_updated.connect(self._fishing_target_updated)
        self._runner.fishing_started.connect(self._workflow_fishing_started)
        self._runner.fishing_stopped.connect(self._workflow_fishing_stopped)
        self._runner.vision_started.connect(self._workflow_vision_started)
        self._runner.vision_stopped.connect(self._workflow_vision_stopped)
        self._hotkeys.activated.connect(self._handle_control)
        self._hotkeys.status_changed.connect(self._log)
        self._hotkeys.bindings_changed.connect(self._hotkey_bindings_changed)
        self._hotkeys.error_occurred.connect(self._hotkey_error)
        self._mouse_buttons.pressed.connect(self._handle_side_button)
        self._mouse_buttons.status_changed.connect(self._mouse_status_changed)
        self._mouse_buttons.error_occurred.connect(self._mouse_error)

    def _refresh_ui(self) -> None:
        self.actions_page.set_actions(self._state.actions)
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.fishing_presets, self._state.vision_presets)
        self.vision_page.set_data(self._state.actions, self._state.vision, self._state.fishing, self._state.fishing_presets, self._state.materials, self._state.material_capture, self._state.vision_presets)
        self.settings_page.set_values(self._state.device, self._state.controls, is_administrator())
        self.settings_page.set_theme(self._state.window_layout.theme)
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)
        self.dashboard.set_targets(self._state.workflows, self._state.actions, self._state.active_target_kind, self._state.active_target_id)

    def _refresh_ports(self) -> None:
        ports = self._serial.available_ports()
        self.dashboard.set_ports(ports, self._state.device.port)
        self._log(f"发现 {len(ports)} 个串口")

    def _connect(self, port: str) -> None:
        if not port:
            self._log("请先选择有效串口")
            return
        if self._serial.connect(port, self._state.device.baud_rate):
            self._state.device.port = port
            self._save_state()
            self._serial.request_device_state()

    def _connection_changed(self, connected: bool, text: str) -> None:
        self.dashboard.set_connection(connected, text)
        self.dashboard.set_runtime_status("设备已连接，等待检查" if connected else "等待连接设备", "success" if connected else "danger")
        self._log(text)
        if connected:
            width, height = primary_screen_resolution()
            self._state.device.screen_width = width
            self._state.device.screen_height = height
            self._save_state()
            self.settings_page.set_values(self._state.device, self._state.controls, is_administrator())
            self._serial.send(f"{{SCR_{width}_{height}}}")
            self._log(f"已自动同步主显示器分辨率到设备：{width}×{height}")

    def _serial_message_received(self, message: str) -> None:
        self._log(f"← {message}")
        self.settings_page.update_device_status(message)

    def _vision_settings_changed(self, settings: VisionSettings) -> None:
        was_running = self._vision.is_running
        self._state.vision = settings
        self._save_state()
        if was_running:
            self._vision.stop()
            if self.vision_page.template_is_enabled():
                self._start_template_recognition()

    def _vision_enabled_changed(self, enabled: bool) -> None:
        if enabled:
            self._fishing.stop()
            self.vision_page._set_fishing_enabled(False)
            self._start_template_recognition()
        else:
            self._vision.stop()

    def _resolve_vision_materials(self, settings: VisionSettings) -> VisionSettings:
        resolved = deepcopy(settings)
        target = next((item for item in self._state.materials if item.id == resolved.target_material_id), None)
        if target is not None and target.kind == "color":
            resolved.source, resolved.color_hex = "color", target.color_hex
        elif target is not None and target.kind == "template":
            resolved.source, resolved.template_path = "template", target.image_path
        else:
            resolved.target_material_id = ""
        region = next((item for item in self._state.materials if item.id == resolved.region_material_id), None)
        if region is not None and region.kind == "region":
            resolved.window_title = region.window_title
            resolved.region_x, resolved.region_y = region.region_x, region.region_y
            resolved.region_width, resolved.region_height = region.region_width, region.region_height
        return resolved

    def _resolve_fishing_materials(self, settings: FishingSettings) -> FishingSettings:
        resolved = deepcopy(settings)
        for material_id, material_id_name, source_name, color_name, template_name in ((resolved.a_material_id, "a_material_id", "a_source", "color_a_hex", "template_a_path"), (resolved.b_material_id, "b_material_id", "b_source", "color_b_hex", "template_b_path")):
            material = next((item for item in self._state.materials if item.id == material_id), None)
            if material is not None and material.kind == "color":
                setattr(resolved, source_name, "color"); setattr(resolved, color_name, material.color_hex)
            elif material is not None and material.kind == "template":
                setattr(resolved, source_name, "template"); setattr(resolved, template_name, material.image_path)
            else:
                setattr(resolved, material_id_name, "")
        region = next((item for item in self._state.materials if item.id == resolved.region_material_id), None)
        if region is not None and region.kind == "region":
            resolved.window_title = region.window_title
            resolved.region_x, resolved.region_y = region.region_x, region.region_y
            resolved.region_width, resolved.region_height = region.region_width, region.region_height
        elif resolved.region_material_id:
            resolved.region_material_id = ""
        return resolved

    def _start_template_recognition(self) -> None:
        settings = self._resolve_vision_materials(self._state.vision)
        automated = any(rule.enabled and rule.action_mode != "report" for rule in settings.rules) if settings.rules else settings.action_mode != "report"
        if automated:
            if self._runner.is_running:
                self.vision_page.set_template_status("普通操作或流程正在运行，不能启用模板自动动作")
                self.vision_page._set_template_enabled(False)
                return
            if not self._serial.is_connected:
                self.vision_page.set_template_status("Leonardo 未连接，不能启用模板自动动作；可改为“仅报告结果”")
                self.vision_page._set_template_enabled(False)
                return
        self._template_started_at = time.monotonic()
        self._template_triggered = False
        self._last_template_result_ui_at = 0.0
        if not self._vision.start(settings):
            self.vision_page._set_template_enabled(False)

    def _workflow_vision_started(self, settings: VisionSettings, duration_ms: int, preset_id: str) -> None:
        self._vision.stop()
        self.vision_page._set_template_enabled(False)
        self._workflow_vision_preset_id = preset_id
        self._last_template_result_ui_at = 0.0
        self._active_workflow_vision_settings = self._resolve_vision_materials(settings)
        if self._vision.start(self._active_workflow_vision_settings):
            duration = "直到匹配" if duration_ms <= 0 else f"最多 {duration_ms / 1000:g} 秒"
            self.vision_page.set_template_status(f"流程识图监测已启动：{duration}")
        else:
            self._runner.notify_vision_match(preset_id)

    def _workflow_vision_stopped(self, preset_id: str) -> None:
        if self._workflow_vision_preset_id == preset_id:
            self._vision.stop()
            self._workflow_vision_preset_id = ""
            self._active_workflow_vision_settings = None

    def _vision_status_changed(self, message: str) -> None:
        self.vision_page.set_template_status(message)
        level = "danger" if any(token in message for token in ("异常", "缺少", "无法", "不存在")) else "success" if "运行中" in message else "neutral"
        self.dashboard.set_runtime_status(f"AI 识别：{message}", level)
        self._log(f"模板识别：{message}")
        if message.startswith(("缺少", "无法读取", "未找到", "模板图片大于", "模板识别异常")):
            self.vision_page._set_template_enabled(False)

    def _vision_rule_matched(self, rule_id: str, score: float, center_x: int, center_y: int, left: int, top: int, width: int, height: int) -> None:
        rule = next((item for item in self._state.vision.rules if item.id == rule_id), None)
        if rule is None or self._runner.is_running or self._fishing.is_running:
            return
        if rule.action_mode == "report":
            self.vision_page.set_template_status(f"规则“{rule.name}”匹配 {score:.3f}（仅报告）")
            return
        if rule.action_mode == "action_once":
            action = next((item for item in self._state.actions if item.id == rule.action_id), None)
            if action:
                self._runner.start_action_once(action, f"ai-rule:{rule.id}")
            return
        if rule.action_step is None or not self._serial.is_connected:
            return
        try:
            command = command_for_step(rule.action_step)
            if command and self._serial.send(command):
                self.vision_page.set_template_status(f"规则“{rule.name}”已匹配，已发送 {command}")
        except ProtocolError as error:
            self.vision_page.set_template_status(f"AI 规则动作无效：{error}")

    @staticmethod
    def _presentation_refresh_due(last_at: float, now: float, minimum_interval: float = 0.12) -> bool:
        """仅限制界面重绘；识图计算、流程通知与输入响应不经过该判断。"""
        return now - last_at >= minimum_interval

    def _set_template_match_result_ui(self, score: float, center_x: int, center_y: int) -> None:
        now = time.monotonic()
        if not self._presentation_refresh_due(self._last_template_result_ui_at, now):
            return
        self._last_template_result_ui_at = now
        self.vision_page.set_template_match_result(score, center_x, center_y)

    def _set_fishing_result_ui(self, text: str, state: str) -> None:
        now = time.monotonic()
        if state == self._last_fishing_result_state and not self._presentation_refresh_due(self._last_fishing_result_ui_at, now):
            return
        self._last_fishing_result_ui_at = now
        self._last_fishing_result_state = state
        self.vision_page.set_fishing_result(text)

    def _template_match_updated(self, score: float, center_x: int, center_y: int, left: int, top: int, width: int, height: int) -> None:
        self._set_template_match_result_ui(score, center_x, center_y)
        if self._workflow_vision_preset_id and self._active_workflow_vision_settings and score >= self._active_workflow_vision_settings.threshold:
            self._runner.notify_vision_match(self._workflow_vision_preset_id)
            return
        settings = self._state.vision
        if settings.rules:
            return
        if not self.vision_page.template_is_enabled() or self._template_triggered:
            return
        if score < settings.threshold:
            if settings.timeout_seconds and time.monotonic() - self._template_started_at >= settings.timeout_seconds:
                self.vision_page.set_template_status("模板识别超时，AI任务已停止")
                self._vision.stop()
                self.vision_page._set_template_enabled(False)
            return
        self._template_triggered = True
        self._run_template_action(center_x, center_y, left, top, width, height)
        self._vision.stop()
        self.vision_page._set_template_enabled(False)

    def _run_template_action(self, center_x: int, center_y: int, left: int, top: int, width: int, height: int) -> None:
        settings = self._state.vision
        if settings.action_mode == "report":
            self.vision_page.set_template_status("已找到目标，仅报告结果后停止模板识别")
            self._log("模板识别已找到目标（仅报告）")
            return
        if settings.action_mode in {"move", "click"}:
            if width <= 0 or height <= 0:
                self.vision_page.set_template_status("识别区域尺寸无效，未执行动作")
                return
            normalized_x = round((center_x - left) * 1000 / width)
            normalized_y = round((center_y - top) * 1000 / height)
            move = command_for_step(ActionStep(ActionKind.MOVE_NORMALIZED, f"{normalized_x}_{normalized_y}"))
            if not move or not self._serial.send(move):
                self.vision_page.set_template_status("目标已找到，但移动命令发送失败")
                return
            if settings.action_mode == "click":
                click = command_for_step(ActionStep(ActionKind.MOUSE_CLICK, "LEFT"))
                if not click or not self._serial.send(click):
                    self.vision_page.set_template_status("目标已找到，但点击命令发送失败")
                    return
                self.vision_page.set_template_status("已找到目标，已移动并左键点击一次")
            else:
                self.vision_page.set_template_status("已找到目标，已移动到目标中心")
            return
        if settings.action_mode == "step":
            if settings.response_step is None:
                self.vision_page.set_template_status("请选择有效的键盘或鼠标动作")
                return
            try:
                command = command_for_step(settings.response_step)
                if command and self._serial.send(command):
                    self.vision_page.set_template_status(f"已找到目标，已执行 {command}")
                else:
                    self.vision_page.set_template_status("目标已找到，但键鼠命令发送失败")
            except ProtocolError as error:
                self.vision_page.set_template_status(f"AI 键鼠动作无效：{error}")
            return
        action = next((item for item in self._state.actions if item.id == settings.action_id), None)
        if action is None:
            self.vision_page.set_template_status("请选择有效的已保存操作后再启用模板动作")
            return
        if self._runner.start_action_once(action, f"ai-template:{action.id}"):
            self.vision_page.set_template_status(f"已找到目标，开始执行一次操作：{action.name}")
        else:
            self.vision_page.set_template_status("目标已找到，但操作未能启动")

    def _fishing_settings_changed(self, settings: FishingSettings) -> None:
        was_running = self._fishing.is_running
        self._state.fishing = settings
        self._save_state()
        self._configure_global_controls()
        if was_running:
            self._fishing.stop()
            self._release_fishing_key()
            if self.vision_page.fishing_is_enabled():
                self._start_fishing_tracking()

    def _materials_changed(self, materials) -> None:
        self._state.materials = materials
        self._save_state()

    def _material_capture_settings_changed(self, settings: MaterialCaptureSettings) -> None:
        self._state.material_capture = settings
        self._save_state()
        self._configure_global_controls()

    def _vision_presets_changed(self, presets) -> None:
        self._state.vision_presets = presets
        self._save_state()
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.fishing_presets, self._state.vision_presets)
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)

    def _fishing_presets_changed(self, presets: list[FishingPreset]) -> None:
        self._state.fishing_presets = presets
        self._save_state()
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.fishing_presets, self._state.vision_presets)
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)

    def _fishing_enabled_changed(self, enabled: bool) -> None:
        if enabled:
            self._vision.stop()
            self.vision_page._set_template_enabled(False)
            self._start_fishing_tracking()
        else:
            self._fishing.stop()
            self._release_fishing_key()
            self._active_fishing_settings = None
            self._serial.send_stop()

    def _fishing_capture_region(self, settings: FishingSettings) -> dict[str, int] | None:
        if not settings.window_title:
            return None
        window = window_by_title(settings.window_title)
        if window is None:
            self.vision_page.set_fishing_status("所选识别窗口不存在，请重新选择窗口")
            return {"invalid": 1}
        width = settings.region_width or window.width
        height = settings.region_height or window.height
        return {"left": window.left + settings.region_x, "top": window.top + settings.region_y, "width": width, "height": height}

    def _start_fishing_tracking(self) -> None:
        if self._runner.is_running:
            self.vision_page.set_fishing_status("普通操作或流程正在运行，不能手动启用钓鱼识别")
            self.vision_page._set_fishing_enabled(False)
            return
        if not self._serial.is_connected:
            self.vision_page.set_fishing_status("Leonardo 未连接，无法启用钓鱼识别")
            self.vision_page._set_fishing_enabled(False)
            return
        self._active_fishing_settings = self._resolve_fishing_materials(self._state.fishing)
        self._last_fishing_result_ui_at = 0.0
        self._last_fishing_result_state = ""
        region = self._fishing_capture_region(self._active_fishing_settings)
        if region and "invalid" in region:
            self.vision_page._set_fishing_enabled(False)
            return
        if not self._fishing.start(self._active_fishing_settings, region):
            self.vision_page._set_fishing_enabled(False)
        else:
            self.vision_page.set_fishing_status("当前运行：手动 F7 钓鱼设置")

    def _release_fishing_key(self) -> None:
        if not self._fishing_pressed_key:
            return
        try:
            command = command_for_step(ActionStep(ActionKind.KEY_UP, self._fishing_pressed_key))
            if command:
                self._serial.send(command)
        except ProtocolError:
            pass
        self._fishing_pressed_key = ""

    def _set_fishing_key(self, key: str) -> None:
        if key == self._fishing_pressed_key:
            return
        self._release_fishing_key()
        try:
            command = command_for_step(ActionStep(ActionKind.KEY_DOWN, key))
            if command and self._serial.send(command):
                self._fishing_pressed_key = key
        except ProtocolError as error:
            self.vision_page.set_fishing_status(f"钓鱼响应按键无效：{error}")

    def _tap_fishing_key(self, key: str, settings: FishingSettings) -> bool:
        now = time.monotonic()
        if now - self._last_fishing_tap_at < settings.tap_interval_ms / 1000:
            return False
        try:
            command = command_for_step(ActionStep(ActionKind.KEY_TAP, key))
            if command and self._serial.send(command):
                self._last_fishing_tap_at = now
                return True
        except ProtocolError as error:
            self.vision_page.set_fishing_status(f"钓鱼点按键无效：{error}")
        return False

    def _fishing_status_changed(self, message: str) -> None:
        self.vision_page.set_fishing_status(message)
        level = "danger" if any(token in message for token in ("异常", "缺少", "无法", "不存在")) else "success" if "运行中" in message else "neutral"
        self.dashboard.set_runtime_status(f"钓鱼识别：{message}", level)
        self._log(f"钓鱼识别：{message}")
        if message.startswith(("缺少", "未找到", "A/B", "钓鱼识别异常")):
            self._release_fishing_key()
            self.vision_page._set_fishing_enabled(False)

    def _workflow_fishing_started(self, settings: FishingSettings, duration_ms: int) -> None:
        self._vision.stop()
        self.vision_page._set_template_enabled(False)
        if self._fishing.is_running:
            self._fishing.stop()
        self._workflow_fishing_active = True
        self._active_fishing_settings = self._resolve_fishing_materials(settings)
        self._last_fishing_result_ui_at = 0.0
        self._last_fishing_result_state = ""
        region = self._fishing_capture_region(self._active_fishing_settings)
        if region and "invalid" in region:
            self._workflow_fishing_active = False
            return
        if self._fishing.start(self._active_fishing_settings, region):
            preset_name = next((item.name for item in self._state.fishing_presets if item.settings == settings), "钓鱼预设")
            self.vision_page.set_fishing_status(f"当前运行：流程预设“{preset_name}”，持续 {duration_ms / 1000:g} 秒")
        else:
            self._workflow_fishing_active = False
            self._log("流程钓鱼预设未能启动")

    def _workflow_fishing_stopped(self) -> None:
        if self._workflow_fishing_active or self._fishing.is_running:
            self._fishing.stop()
            self._release_fishing_key()
            self._serial.send_stop()
        self._workflow_fishing_active = False
        self._active_fishing_settings = None
        self._fishing_pending_direction = 0
        self._fishing_direction_frames = 0

    def _fishing_target_updated(self, a_x: int, a_y: int, a_area: int, b_x: int, b_y: int, b_area: int) -> None:
        if (not self.vision_page.fishing_is_enabled() and not self._workflow_fishing_active) or not self._fishing.is_running:
            return
        if self._runner.is_running and not self._workflow_fishing_active:
            self.vision_page.set_fishing_status("普通流程运行，钓鱼识别已停止")
            self._fishing.stop()
            self._release_fishing_key()
            self.vision_page._set_fishing_enabled(False)
            return
        if a_area <= 0 or b_area <= 0:
            self._fishing_pending_direction = 0
            self._fishing_direction_frames = 0
            self._release_fishing_key()
            missing = "A 长条和 B 细竖条" if a_area <= 0 and b_area <= 0 else ("A 长条" if a_area <= 0 else "B 细竖条")
            self._set_fishing_result_ui(f"未找到 {missing}，已释放响应按键", "missing")
            return
        settings = self._active_fishing_settings or self._state.fishing
        offset_x = b_x - a_x
        direction = FishingService.horizontal_direction(a_x, b_x, settings.dead_zone)
        if direction == 0:
            self._fishing_pending_direction = 0
            self._fishing_direction_frames = 0
            self._release_fishing_key()
            self._set_fishing_result_ui(f"A({a_x}, {a_y}, {a_area} 像素) / B({b_x}, {b_y}, {b_area} 像素)，偏差 {offset_x} px；B 已对齐 A 中心，持续监测保持中", "aligned")
            return
        if direction != self._fishing_pending_direction:
            self._fishing_pending_direction = direction
            self._fishing_direction_frames = 1
        else:
            self._fishing_direction_frames += 1
        if self._fishing_direction_frames < 2:
            self._set_fishing_result_ui(f"A({a_x}, {a_y}) / B({b_x}, {b_y})，偏差 {offset_x} px；正在确认移动方向", "confirming")
            return
        key = settings.right_key if direction < 0 else settings.left_key
        side = "左侧" if direction < 0 else "右侧"
        sent = self._tap_fishing_key(key, settings)
        state = f"已点按 {key}" if sent else f"等待点按间隔（{settings.tap_interval_ms} ms）"
        self._set_fishing_result_ui(f"A({a_x}, {a_y}, {a_area} 像素) / B({b_x}, {b_y}, {b_area} 像素)，偏差 {offset_x} px；B 距 A 中心偏{side}，{state}", "adjusting")

    def _preview_move(self, step: ActionStep, source) -> None:
        if self._runner.is_running:
            message = "试移失败：已有操作或流程正在运行，不能插入手动移动。"
            source.set_move_preview_status(message)
            self._log(message)
            return
        if not self._serial.is_connected:
            message = "试移失败：设备未连接。请先在控制台连接 Leonardo。"
            source.set_move_preview_status(message)
            self._log(message)
            return
        try:
            command = command_for_step(step)
        except ProtocolError as error:
            message = f"试移参数无效：{error}"
            source.set_move_preview_status(message)
            self._log(message)
            return
        if command and self._serial.send(command):
            message = f"已发送试移命令：{command}；该移动不会保存到操作。"
            source.set_move_preview_status(message)
            self._log(message)
        else:
            source.set_move_preview_status("试移发送失败；请查看控制台日志并检查串口连接。")

    def _theme_changed(self, theme: str) -> None:
        if theme not in {"light", "dark_blue"}: 
            return
        self._state.window_layout.theme = theme
        self._apply_style()
        self._save_state()
        self._log(f"界面主题已切换为：{self.settings_page.theme_combo.currentText()}")

    def _save_settings(self, device: DeviceSettings, controls: ControlSettings) -> None:
        device.port = self._state.device.port
        device.baud_rate = self._state.device.baud_rate
        controls.start_side_button = self._state.controls.start_side_button
        controls.stop_side_button = self._state.controls.stop_side_button
        self._state.device = device
        self._state.controls = controls
        self._save_state()
        self._configure_global_controls()
        self._log("本地设置已保存；数值会替换单片机基础延迟，不会叠加默认值")

    def _restore_device_defaults(self) -> None:
        previous = self._state.device
        self._state.device = DeviceSettings.defaults(previous.port, previous.baud_rate)
        self._save_state()
        self.settings_page.set_values(self._state.device, self._state.controls, is_administrator())
        if self._serial.is_connected:
            self._serial.send("{CFG_RESET}")
            self._log("软件和已连接设备已恢复固件默认配置：2560×1440")
        else:
            self._log("本地设备配置已恢复默认值；连接后可点击“保存并下发到设备”同步")

    def _actions_changed(self) -> None:
        self._save_state()
        self._configure_global_controls()
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.fishing_presets, self._state.vision_presets)
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)
        self.vision_page.set_data(self._state.actions, self._state.vision, self._state.fishing, self._state.fishing_presets, self._state.materials, self._state.material_capture, self._state.vision_presets)
        self.dashboard.set_targets(self._state.workflows, self._state.actions, self._state.active_target_kind, self._state.active_target_id)

    def _create_workflow_for_action(self, action_id: str) -> None:
        action = next((item for item in self._state.actions if item.id == action_id), None)
        if action is None:
            return
        workflow = WorkflowDefinition(
            name=f"{action.name} 流程",
            primary_action_id=action.id,
        )
        self._state.workflows.append(workflow)
        self._state.active_workflow_id = workflow.id
        self._state.active_target_kind = "workflow"
        self._state.active_target_id = workflow.id
        self._save_state()
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, workflow.id)
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, workflow.id)
        self.dashboard.set_targets(self._state.workflows, self._state.actions, "workflow", workflow.id)
        self.navigation.setCurrentRow(2)
        self._log(f"已从操作“{action.name}”创建流程")

    def _workflows_changed(self) -> None:
        self._save_state()
        self._configure_global_controls()
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.fishing_presets, self._state.vision_presets)
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, self._state.active_workflow_id, self._state.vision_presets)
        self.dashboard.set_targets(self._state.workflows, self._state.actions, self._state.active_target_kind, self._state.active_target_id)

    def _active_workflow_changed(self, workflow_id: str) -> None:
        self._state.active_workflow_id = workflow_id
        self._state.active_target_kind = "workflow"
        self._state.active_target_id = workflow_id
        self._save_state()
        self.ab_flow_page.set_data(self._state.workflows, self._state.actions, workflow_id)
        self.custom_flow_page.set_data(self._state.workflows, self._state.actions, workflow_id)
        self.dashboard.set_targets(self._state.workflows, self._state.actions, "workflow", workflow_id)

    def _save_state(self) -> None:
        self._store.save(self._state)

    def _active_workflow(self) -> WorkflowDefinition | None:
        return next((workflow for workflow in self._state.workflows if workflow.id == self._state.active_workflow_id), None)

    def _target_selected(self, kind: str, target_id: str) -> None:
        if kind not in {"workflow", "action"} or not target_id:
            return
        self._state.active_target_kind = kind
        self._state.active_target_id = target_id
        if kind == "workflow":
            self._state.active_workflow_id = target_id
        self._save_state()
        self._log(f"当前启用目标已切换为：{'流程' if kind == 'workflow' else '操作'}")

    def _stop_ai_input_modules(self) -> None:
        if self._fishing.is_running:
            self._fishing.stop()
            self.vision_page._set_fishing_enabled(False)
        if self._vision.is_running and self._state.vision.action_mode != "report":
            self._vision.stop()
            self.vision_page._set_template_enabled(False)

    def _validate_vision_preflight(self, settings: VisionSettings, label: str) -> list[str]:
        resolved = self._resolve_vision_materials(settings)
        errors: list[str] = []
        if not resolved.target_material_id:
            errors.append(f"{label}未选择有效识别素材")
        elif resolved.source == "template" and not Path(resolved.template_path).is_file():
            errors.append(f"{label}的模板图片不存在")
        if resolved.region_material_id and resolved.window_title and window_by_title(resolved.window_title) is None:
            errors.append(f"{label}的区域窗口“{resolved.window_title}”不存在")
        return errors

    def _validate_fishing_preflight(self, settings: FishingSettings, label: str) -> list[str]:
        resolved = self._resolve_fishing_materials(settings)
        errors: list[str] = []
        if not resolved.a_material_id or not resolved.b_material_id or not resolved.region_material_id:
            errors.append(f"{label}未完整选择 A、B 或观察区域素材")
        if resolved.a_source == "template" and not Path(resolved.template_a_path).is_file():
            errors.append(f"{label}的 A 模板图片不存在")
        if resolved.b_source == "template" and not Path(resolved.template_b_path).is_file():
            errors.append(f"{label}的 B 模板图片不存在")
        if resolved.region_material_id and resolved.window_title and window_by_title(resolved.window_title) is None:
            errors.append(f"{label}的区域窗口“{resolved.window_title}”不存在")
        return errors

    def _run_preflight(self) -> bool:
        errors: list[str] = []
        target_id = self._state.active_target_id
        kind = self._state.active_target_kind
        if not self._serial.is_connected:
            errors.append("Leonardo 未连接")
        if kind == "action":
            action = next((item for item in self._state.actions if item.id == target_id), None)
            if action is None:
                errors.append("当前启用操作不存在")
            elif not action.steps:
                errors.append(f"操作“{action.name}”没有步骤")
        elif kind == "workflow":
            workflow = next((item for item in self._state.workflows if item.id == target_id), None)
            if workflow is None:
                errors.append("当前启用流程不存在")
            else:
                actions = {item.id: item for item in self._state.actions}
                vision_presets = {item.id: item for item in self._state.vision_presets}
                fishing_presets = {item.id: item for item in self._state.fishing_presets}
                if workflow.mode == "ab":
                    if not workflow.primary_action_id or workflow.primary_action_id not in actions:
                        errors.append("AB 流程未选择有效的 A 操作")
                    if workflow.secondary_action_id and workflow.secondary_action_id not in actions:
                        errors.append("AB 流程的 B 操作不存在")
                    if workflow.secondary_vision_preset_id:
                        preset = vision_presets.get(workflow.secondary_vision_preset_id)
                        if preset is None:
                            errors.append("AB 流程引用的识图预设不存在")
                        else:
                            errors.extend(self._validate_vision_preflight(preset.settings, f"识图预设“{preset.name}”"))
                else:
                    root = workflow.root_step
                    if root is None or not root.children:
                        errors.append("自定义流程尚未添加任务卡片")
                    def inspect_step(step) -> None:
                        if step.kind == "empty":
                            errors.append("自定义流程中存在未配置卡片")
                        elif step.kind == "action" and (not step.action_id or step.action_id not in actions):
                            errors.append(f"卡片“{step.title or '操作'}”未选择有效操作")
                        elif step.kind == "vision":
                            preset = vision_presets.get(step.vision_preset_id)
                            if preset is None:
                                errors.append(f"卡片“{step.title or '识图'}”未选择有效识图预设")
                            else:
                                errors.extend(self._validate_vision_preflight(preset.settings, f"识图预设“{preset.name}”"))
                        elif step.kind == "fishing":
                            preset = fishing_presets.get(step.fishing_preset_id)
                            if preset is None:
                                errors.append(f"卡片“{step.title or '钓鱼'}”未选择有效钓鱼预设")
                            else:
                                errors.extend(self._validate_fishing_preflight(preset.settings, f"钓鱼预设“{preset.name}”"))
                        for child in step.children:
                            inspect_step(child)
                    if root is not None:
                        for step in root.children:
                            inspect_step(step)
        else:
            errors.append("请先选择要运行的流程或操作")
        if errors:
            summary = f"发现 {len(errors)} 项问题：" + "；".join(errors[:3])
            if len(errors) > 3:
                summary += f"；另有 {len(errors) - 3} 项"
            self.dashboard.set_preflight_result(summary, False)
            self.dashboard.set_runtime_status("等待修复配置", "danger")
            self._log(f"运行前检查未通过：{summary}")
            return False
        self.dashboard.set_preflight_result("检查通过：设备、任务与素材引用均可用", True)
        self.dashboard.set_runtime_status("已就绪，可以启动", "success")
        self._log("运行前检查通过")
        return True

    def _start_active_target(self) -> None:
        if not self._run_preflight():
            return
        self._stop_ai_input_modules()
        kind = self._state.active_target_kind
        target_id = self._state.active_target_id
        if kind == "action":
            action = next((item for item in self._state.actions if item.id == target_id), None)
            if action is None:
                self._log("当前启用操作不存在；请在控制台重新选择")
                return
            self._runner.start_action_loop(action, f"action:{action.id}")
            return
        workflow = next((item for item in self._state.workflows if item.id == target_id), None)
        if workflow is None:
            self._log("当前启用流程不存在；请在控制台重新选择")
            return
        self._runner.start(workflow, self._state.actions, f"workflow:{workflow.id}", self._state.fishing_presets, self._state.vision_presets)

    def _stop_workflow(self) -> None:
        self._runner.stop()
        self._log("已请求停止并释放全部按键/鼠标键")

    def _apply_device_configuration(self) -> None:
        if not self._serial.is_connected:
            self._log("请先连接设备，再下发配置")
            return
        try:
            for command in device_configuration_commands(self._state.device):
                self._serial.send(command)
            self._log("设备配置已下发")
        except ProtocolError as error:
            self._log(f"配置无效：{error}")

    def _configure_global_controls(self) -> None:
        controls = self._state.controls
        bindings: dict[str, str] = {}
        labels: dict[str, str] = {}
        used_shortcuts: dict[str, str] = {}

        def add_binding(target: str, shortcut: str, label: str) -> None:
            shortcut = shortcut.strip()
            if not shortcut:
                return
            normalized = shortcut.upper().replace(" ", "")
            if normalized in used_shortcuts:
                self._log(f"快捷键 {shortcut} 同时绑定到“{label}”和“{used_shortcuts[normalized]}”，已忽略后者")
                return
            used_shortcuts[normalized] = label
            bindings[target] = shortcut
            labels[target] = label

        # 通用启动/停止快捷键允许留空；默认依靠鼠标侧键。
        add_binding("start", controls.start_hotkey, "通用启动/恢复")
        add_binding("stop", controls.stop_hotkey, "通用停止")
        capture = self._state.material_capture
        add_binding("material:pick_color", capture.color_pick_hotkey, "素材库：吸色")
        add_binding("material:capture_template", capture.template_capture_hotkey, "素材库：截取模板")
        add_binding("material:capture_region", capture.region_capture_hotkey, "素材库：截取区域")
        add_binding("fishing:detection_toggle", self._state.fishing.detection_hotkey, "钓鱼识别开关")
        for action in self._state.actions:
            add_binding(f"action:{action.id}", action.hotkey, f"操作：{action.name}")
        for workflow in self._state.workflows:
            add_binding(f"workflow:{workflow.id}", workflow.hotkey, f"流程：{workflow.name}")

        signature = tuple(sorted((target, shortcut.upper().replace(" ", "")) for target, shortcut in bindings.items()))
        self._hotkey_labels = labels
        if signature != self._hotkey_signature:
            self._hotkey_signature = signature
            self._hotkey_status = "系统级快捷键：正在逐项注册…" if bindings else "系统级快捷键：未绑定（可使用鼠标侧键）"
            # 保留每个快捷键的详细启用日志；仅跳过相同配置的重复注册。
            self._hotkeys.configure(bindings)
        if controls.side_buttons_enabled:
            self._mouse_status = "鼠标侧键监听：正在安装…"
            self._mouse_buttons.start()
        else:
            self._mouse_buttons.stop()
            self._mouse_status = "鼠标侧键监听：已关闭"
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)

    def _hotkey_bindings_changed(self, bindings: dict) -> None:
        if bindings:
            display = "，".join(f"{self._hotkey_labels.get(name, name)}：{shortcut}" for name, shortcut in bindings.items())
            self._hotkey_status = f"系统级快捷键：已启用（{display}）"
        else:
            self._hotkey_status = "系统级快捷键：未绑定（可使用鼠标侧键）"
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)

    def _hotkey_error(self, message: str) -> None:
        for target, label in self._hotkey_labels.items():
            message = message.replace(target, label)
        self._hotkey_status = f"系统级快捷键：{message}"
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)
        self._log(message)

    def _mouse_status_changed(self, message: str) -> None:
        self._mouse_status = f"鼠标侧键监听：{message}"
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)
        self._log(message)

    def _mouse_error(self, message: str) -> None:
        self._mouse_status = f"鼠标侧键监听：{message}"
        self.settings_page.set_control_status(self._hotkey_status, self._mouse_status)
        self._log(message)

    def _handle_control(self, control: str) -> None:
        if control == "start":
            self._start_active_target()
            return
        if control == "stop":
            self._stop_workflow()
            return
        if control == "material:pick_color":
            self.navigation.setCurrentRow(4)
            self.vision_page.capture_material_color()
            self._log("已通过快捷键打开素材库吸色器")
            return
        if control == "material:capture_template":
            self.navigation.setCurrentRow(4)
            self.vision_page.capture_material_template()
            self._log("已通过快捷键打开素材库模板截取器")
            return
        if control == "material:capture_region":
            self.navigation.setCurrentRow(4)
            self.vision_page.capture_material_region()
            self._log("已通过快捷键打开素材库区域截取器")
            return
        if control == "fishing:detection_toggle":
            self.navigation.setCurrentRow(4)
            self.vision_page.fishing_enabled.setChecked(not self.vision_page.fishing_is_enabled())
            self._log("钓鱼色块检测已" + ("开启" if self.vision_page.fishing_is_enabled() else "关闭"))
            return
        if control.startswith("action:"):
            action_id = control.split(":", 1)[1]
            action = next((item for item in self._state.actions if item.id == action_id), None)
            if action is not None:
                self._toggle_action_hotkey(action)
            return
        if control.startswith("workflow:"):
            workflow_id = control.split(":", 1)[1]
            workflow = next((item for item in self._state.workflows if item.id == workflow_id), None)
            if workflow is not None:
                self._toggle_workflow_hotkey(workflow)

    def _toggle_action_hotkey(self, action) -> None:
        target = f"action:{action.id}"
        if self._runner.is_running:
            if self._runner.active_target == target:
                self._log(f"再次触发“{action.name}”，正在停止循环操作")
            else:
                self._log(f"当前任务仍在运行，已请求停止；请再次触发“{action.name}”启动")
            self._stop_workflow()
            return
        self._stop_ai_input_modules()
        self._log(f"快捷键启动循环操作：“{action.name}”")
        self._runner.start_action_loop(action, target)

    def _toggle_workflow_hotkey(self, workflow: WorkflowDefinition) -> None:
        target = f"workflow:{workflow.id}"
        if self._runner.is_running:
            if self._runner.active_target == target:
                self._log(f"再次触发“{workflow.name}”，正在停止流程")
            else:
                self._log(f"当前任务仍在运行，已请求停止；请再次触发“{workflow.name}”启动")
            self._stop_workflow()
            return
        self._stop_ai_input_modules()
        self._log(f"快捷键启动流程：“{workflow.name}”")
        self._runner.start(workflow, self._state.actions, target)

    def _handle_side_button(self, button: str) -> None:
        controls = self._state.controls
        if not controls.side_buttons_enabled:
            return
        if button == controls.start_side_button:
            self._start_active_target()
        elif button == controls.stop_side_button:
            self._stop_workflow()

    def _workflow_status_changed(self, status: str) -> None:
        level = "danger" if any(token in status for token in ("失败", "异常", "停止")) else "success" if any(token in status for token in ("运行", "启动", "完成")) else "neutral"
        self.dashboard.set_runtime_status(status, level)
        self._log(f"流程状态：{status}")

    def _restart_elevated(self) -> None:
        if is_administrator():
            self._log("当前已经以管理员身份运行")
            return
        if restart_as_administrator():
            self._log("已请求管理员权限重启；请在 UAC 窗口中确认")
        else:
            QMessageBox.warning(self, "无法提权", "未能启动管理员权限实例，可能是 UAC 被取消。")

    def _log(self, message: str) -> None:
        self.dashboard.append_log(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._vision.stop()
        self._fishing.stop()
        self._release_fishing_key()
        self._runner.stop()
        self._serial.send_stop()
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        if available.width() and available.height() and not self.isMaximized():
            self._state.window_layout.width_ratio = max(0.35, min(1.0, self.width() / available.width()))
            self._state.window_layout.height_ratio = max(0.35, min(1.0, self.height() / available.height()))
        self._save_state()
        event.accept()
