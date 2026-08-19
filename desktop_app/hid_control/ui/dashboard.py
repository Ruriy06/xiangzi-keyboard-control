from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import ActionDefinition, WorkflowDefinition
from ..serial_service import PortInfo


class StatusCard(QFrame):
    """轻量状态卡片：仅使用原生控件，不引入动画或额外绘制开销。"""

    def __init__(self, title: str, value: QLabel) -> None:
        super().__init__()
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        caption = QLabel(title)
        caption.setObjectName("statusCardCaption")
        value.setObjectName("statusCardValue")
        value.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(value, 1)


class Dashboard(QWidget):
    refresh_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    start_requested = Signal()
    stop_requested = Signal()
    sync_requested = Signal()
    query_requested = Signal()
    preflight_requested = Signal()
    target_selected = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.port_combo = QComboBox()
        self.connection_label = QLabel("未连接")
        self.target_combo = QComboBox()
        self.runtime_label = QLabel("待命")
        self.preflight_label = QLabel("尚未执行运行前检查")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setPlaceholderText("设备、流程和识图状态会显示在这里")

        refresh_button = QPushButton("刷新端口")
        connect_button = QPushButton("连接设备")
        disconnect_button = QPushButton("断开")
        self.start_button = QPushButton("启动当前目标")
        self.start_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("停止并释放")
        self.stop_button.setObjectName("dangerButton")
        self.preflight_button = QPushButton("运行前检查")
        self.sync_button = QPushButton("下发设备配置")
        self.query_button = QPushButton("读取设备状态")

        refresh_button.clicked.connect(self.refresh_requested)
        connect_button.clicked.connect(lambda: self.connect_requested.emit(self.port_combo.currentData() or self.port_combo.currentText()))
        disconnect_button.clicked.connect(self.disconnect_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.preflight_button.clicked.connect(self.preflight_requested)
        self.sync_button.clicked.connect(self.sync_requested)
        self.query_button.clicked.connect(self.query_requested)
        self.target_combo.currentIndexChanged.connect(self._emit_target_selected)

        title = QLabel("控制台")
        title.setObjectName("pageTitle")
        subtitle = QLabel("选择任务、确认设备和素材状态后即可启动；高频日志保留最近 500 条，避免长期运行占用内存。")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(StatusCard("设备连接", self.connection_label), 1)
        status_row.addWidget(StatusCard("当前目标", self._target_summary_label()), 2)
        status_row.addWidget(StatusCard("运行状态", self.runtime_label), 2)
        status_row.addWidget(StatusCard("检查结果", self.preflight_label), 2)

        device_form = QFormLayout()
        device_form.addRow("串口", self.port_combo)
        device_form.addRow("当前启用目标", self.target_combo)
        device_buttons = QHBoxLayout()
        device_buttons.addWidget(refresh_button)
        device_buttons.addWidget(connect_button)
        device_buttons.addWidget(disconnect_button)

        action_buttons = QHBoxLayout()
        action_buttons.addWidget(self.start_button, 2)
        action_buttons.addWidget(self.stop_button, 1)
        action_buttons.addWidget(self.preflight_button, 1)

        device_group = QGroupBox("设备与任务")
        device_layout = QVBoxLayout(device_group)
        device_layout.addLayout(device_form)
        device_layout.addLayout(device_buttons)
        device_layout.addLayout(action_buttons)

        config_group = QGroupBox("设备配置")
        config_layout = QHBoxLayout(config_group)
        config_layout.addWidget(self.sync_button)
        config_layout.addWidget(self.query_button)
        config_layout.addStretch()

        log_group = QGroupBox("设备与流程日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(self.log_view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(status_row)
        layout.addWidget(device_group)
        layout.addWidget(config_group)
        layout.addWidget(log_group, 1)

    def _target_summary_label(self) -> QLabel:
        self.target_summary_label = QLabel("未选择")
        return self.target_summary_label

    def set_ports(self, ports: list[PortInfo], preferred: str = "") -> None:
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            self.port_combo.addItem(f"{port.device} — {port.description}", port.device)
        if not ports:
            self.port_combo.addItem("未发现串口", "")
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == preferred:
                self.port_combo.setCurrentIndex(index)
                break
        self.port_combo.blockSignals(False)

    def set_targets(self, workflows: list[WorkflowDefinition], actions: list[ActionDefinition], kind: str, target_id: str) -> None:
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        selected = -1
        for workflow in workflows:
            row = self.target_combo.count()
            self.target_combo.addItem(f"流程：{workflow.name}", ("workflow", workflow.id))
            if kind == "workflow" and workflow.id == target_id:
                selected = row
        for action in actions:
            row = self.target_combo.count()
            self.target_combo.addItem(f"操作：{action.name}", ("action", action.id))
            if kind == "action" and action.id == target_id:
                selected = row
        if self.target_combo.count() == 0:
            self.target_combo.addItem("未选择目标", ("", ""))
        self.target_combo.setCurrentIndex(max(0, selected))
        self.target_combo.blockSignals(False)
        self._update_target_summary()

    def _emit_target_selected(self) -> None:
        self._update_target_summary()
        data = self.target_combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            self.target_selected.emit(str(data[0]), str(data[1]))

    def _update_target_summary(self) -> None:
        self.target_summary_label.setText(self.target_combo.currentText() or "未选择")

    def set_connection(self, connected: bool, text: str) -> None:
        self.connection_label.setText(text)
        self.connection_label.setProperty("connected", connected)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def set_runtime_status(self, text: str, level: str = "neutral") -> None:
        self.runtime_label.setText(text)
        self.runtime_label.setProperty("level", level)
        self.runtime_label.style().unpolish(self.runtime_label)
        self.runtime_label.style().polish(self.runtime_label)

    def set_preflight_result(self, text: str, passed: bool | None) -> None:
        self.preflight_label.setText(text)
        self.preflight_label.setProperty("level", "success" if passed else "danger" if passed is False else "neutral")
        self.preflight_label.style().unpolish(self.preflight_label)
        self.preflight_label.style().polish(self.preflight_label)

    def append_log(self, message: str) -> None:
        scrollbar = self.log_view.verticalScrollBar()
        # 用户正在查看旧日志时不抢走滚动位置，减少无意义的滚动重绘。
        follow_latest = scrollbar.value() >= scrollbar.maximum() - 2
        self.log_view.appendPlainText(message)
        if follow_latest:
            scrollbar.setValue(scrollbar.maximum())
