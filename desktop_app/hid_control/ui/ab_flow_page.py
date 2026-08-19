from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget

from ..models import ActionDefinition, FlowMode, VisionPreset, WorkflowDefinition
from .duration_input import DurationInput, format_duration


class ABFlowPage(QWidget):
    workflows_changed = Signal()
    active_workflow_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._workflows: list[WorkflowDefinition] = []
        self._actions: list[ActionDefinition] = []
        self._vision_presets: list[VisionPreset] = []
        self._active_id = ""
        self._selected_id = ""

        self.flow_list = QListWidget()
        self.flow_list.setFixedWidth(180)
        self.flow_list.setSpacing(0)
        self.name_input = QLineEdit()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("留空不绑定；例如 Ctrl+Alt+2")
        self.primary_action = QComboBox()
        self.secondary_action = QComboBox()
        self.secondary_vision = QComboBox()
        self.trigger_duration = DurationInput(maximum_milliseconds=86_400_000)
        self.active_duration = DurationInput(maximum_milliseconds=86_400_000, allow_zero=False)
        self.rest_duration = DurationInput(maximum_milliseconds=86_400_000)
        self.repeats = QSpinBox()
        self.repeats.setRange(0, 100000)
        self.repeats.setSpecialValueText("无限循环")
        self.finish_current = QCheckBox("边界切换保护：等待当前操作完成再切换")
        self.finish_current.setChecked(True)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setObjectName("flowPreview")
        self.preview_toggle = QPushButton("显示流程说明")
        self.preview.setVisible(False)
        self.preview_toggle.clicked.connect(self._toggle_preview)

        self.flow_list.currentRowChanged.connect(self._select_row)
        self.primary_action.currentIndexChanged.connect(self._refresh_preview)
        self.secondary_action.currentIndexChanged.connect(self._refresh_preview)
        self.secondary_vision.currentIndexChanged.connect(self._refresh_preview)
        self.trigger_duration.value_changed.connect(self._refresh_preview)
        self.active_duration.value_changed.connect(self._refresh_preview)
        self.rest_duration.value_changed.connect(self._refresh_preview)
        self.repeats.valueChanged.connect(self._refresh_preview)
        self.finish_current.toggled.connect(self._refresh_preview)

        new_button = QPushButton("新建")
        new_button.setToolTip("新建 AB 流程")
        self.delete_button = QPushButton("删除")
        self.delete_button.setToolTip("删除当前 AB 流程")
        self.save_button = QPushButton("保存 AB流程")
        active_button = QPushButton("设为当前启用流程")
        new_button.clicked.connect(self._new_flow)
        self.delete_button.clicked.connect(self._delete_flow)
        self.save_button.clicked.connect(self._save_flow)
        active_button.clicked.connect(self._activate_flow)

        left = QVBoxLayout()
        left.addWidget(QLabel("AB流程"))
        left.addWidget(self.flow_list, 1)
        flow_tools = QHBoxLayout()
        flow_tools.addWidget(new_button)
        flow_tools.addWidget(self.delete_button)
        left.addLayout(flow_tools)

        form = QFormLayout()
        form.addRow("流程名称", self.name_input)
        form.addRow("独立切换快捷键（留空不绑定）", self.hotkey_input)
        form.addRow("A：主要循环操作", self.primary_action)
        form.addRow("B：定时插入操作（可选）", self.secondary_action)
        form.addRow("B 触发时间", self.trigger_duration)
        form.addRow("B 执行前识图确认（可选）", self.secondary_vision)
        form.addRow("本次运行总时长", self.active_duration)
        form.addRow("本次休息时长", self.rest_duration)
        form.addRow("周期次数", self.repeats)
        form.addRow(self.finish_current)

        right = QVBoxLayout()
        title = QLabel("AB流程")
        title.setObjectName("pageTitle")
        right.addWidget(title)
        right.addWidget(QLabel("A 会连续循环；B 到设定时间后完整执行一次。B 执行时 A 暂停，B 完成后 A 自动恢复。"))
        right.addLayout(form)
        right.addWidget(self.preview_toggle)
        right.addWidget(self.preview)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(active_button)
        right.addLayout(buttons)
        right.addStretch()

        right_widget = QWidget(); right_widget.setLayout(right)
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setWidget(right_widget)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 0)
        layout.addWidget(right_scroll, 1)

    def _toggle_preview(self) -> None:
        visible = not self.preview.isVisible()
        self.preview.setVisible(visible)
        self.preview_toggle.setText("隐藏流程说明" if visible else "显示流程说明")

    def set_data(self, workflows: list[WorkflowDefinition], actions: list[ActionDefinition], active_id: str, vision_presets: list[VisionPreset] | None = None) -> None:
        self._workflows = workflows
        self._actions = actions
        self._vision_presets = vision_presets or []
        self._active_id = active_id
        self._refresh_list()

    def _flows(self) -> list[WorkflowDefinition]:
        return [flow for flow in self._workflows if flow.mode == FlowMode.AB]

    def _current(self) -> WorkflowDefinition | None:
        return next((flow for flow in self._workflows if flow.id == self._selected_id), None)

    def _refresh_list(self) -> None:
        selected_id = self._selected_id
        self.flow_list.blockSignals(True)
        self.flow_list.clear()
        selected_row = -1
        for row, flow in enumerate(self._flows()):
            item = QListWidgetItem()
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 1, 2, 1)
            marker = "  [当前]" if flow.id == self._active_id else ""
            row_layout.addWidget(QLabel(flow.name + marker), 1)
            lock_button = QToolButton()
            lock_button.setText("🔒" if flow.locked else "🔓")
            lock_button.setToolTip("点击解锁" if flow.locked else "点击锁定；锁定后不可修改或删除")
            lock_button.clicked.connect(lambda _checked=False, flow_id=flow.id: self._toggle_lock(flow_id))
            row_layout.addWidget(lock_button)
            item.setSizeHint(QSize(0, 30))
            self.flow_list.addItem(item)
            self.flow_list.setItemWidget(item, row_widget)
            if flow.id == selected_id:
                selected_row = row
        self.flow_list.blockSignals(False)
        if selected_row >= 0:
            self.flow_list.setCurrentRow(selected_row)
        elif self._flows():
            self.flow_list.setCurrentRow(0)
        else:
            self._set_editing_enabled(False)

    def _toggle_lock(self, flow_id: str) -> None:
        flow = next((item for item in self._workflows if item.id == flow_id), None)
        if flow is None:
            return
        flow.locked = not flow.locked
        self._refresh_list()
        self.workflows_changed.emit()

    def _set_editing_enabled(self, enabled: bool) -> None:
        for widget in (
            self.name_input,
            self.hotkey_input,
            self.primary_action,
            self.secondary_action,
            self.secondary_vision,
            self.trigger_duration,
            self.active_duration,
            self.rest_duration,
            self.repeats,
            self.finish_current,
            self.save_button,
            self.delete_button,
        ):
            widget.setEnabled(enabled)

    def _fill_action_combos(self, flow: WorkflowDefinition) -> None:
        for combo, placeholder in ((self.primary_action, "请选择 A 操作"), (self.secondary_action, "不启用 B")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(placeholder, "")
            for action in self._actions:
                combo.addItem(action.name, action.id)
            combo.blockSignals(False)
        self.primary_action.setCurrentIndex(max(0, self.primary_action.findData(flow.primary_action_id)))
        self.secondary_action.setCurrentIndex(max(0, self.secondary_action.findData(flow.secondary_action_id)))
        self.secondary_vision.blockSignals(True); self.secondary_vision.clear(); self.secondary_vision.addItem("不需要识图确认", "")
        for preset in self._vision_presets: self.secondary_vision.addItem(preset.name, preset.id)
        self.secondary_vision.setCurrentIndex(max(0, self.secondary_vision.findData(flow.secondary_vision_preset_id))); self.secondary_vision.blockSignals(False)

    def _select_row(self, row: int) -> None:
        flows = self._flows()
        if not 0 <= row < len(flows):
            return
        flow = flows[row]
        self._selected_id = flow.id
        self.name_input.setText(flow.name)
        self.hotkey_input.setText(flow.hotkey)
        self._fill_action_combos(flow)
        self.trigger_duration.set_milliseconds(flow.secondary_trigger_ms)
        self.active_duration.set_milliseconds(flow.active_duration_ms)
        self.rest_duration.set_milliseconds(flow.rest_duration_ms)
        self.repeats.setValue(flow.repeats)
        self.finish_current.setChecked(flow.finish_current_action)
        self._set_editing_enabled(not flow.locked)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        flow = self._current()
        if flow is None:
            self.preview.setText("新建 AB流程后，这里会显示执行顺序。")
            return
        primary = self.primary_action.currentText() or "未选择 A"
        active = format_duration(self.active_duration.milliseconds())
        rest = format_duration(self.rest_duration.milliseconds())
        cycle = "无限重复" if self.repeats.value() == 0 else f"重复 {self.repeats.value()} 个周期"
        lines = [f"1. 循环执行 A：“{primary}”。"]
        if self.secondary_action.currentData() and self.trigger_duration.milliseconds() > 0:
            lines.append(f"2. 从周期开始经过 {format_duration(self.trigger_duration.milliseconds())} 后，B 获得执行资格。")
            if self.secondary_vision.currentData(): lines.append(f"3. 等待识图预设“{self.secondary_vision.currentText()}”确认；未确认则保持循环 A。")
            lines += [f"4. 在安全边界暂停 A，执行 B：“{self.secondary_action.currentText()}”一次。", "5. B 完成后继续循环 A。"]
        else:
            lines.append("2. 不插入 B，只持续循环 A。")
        completion = "到达时间后不再开始新操作；当前整次操作（含步骤后等待）完成后，再进入下一阶段。" if self.finish_current.isChecked() else "到达时间后不再开始后续步骤；当前单条 HID 命令完成后立即进入下一阶段。"
        lines += [f"5. 从周期开始满 {active} 后，停止启动新操作并休息 {rest}。", f"6. {completion}", f"7. {cycle}。"]
        self.preview.setText("\n".join(lines))

    def _new_flow(self) -> None:
        flow = WorkflowDefinition(name=f"AB流程 {len(self._flows()) + 1}", mode=FlowMode.AB)
        self._workflows.append(flow)
        self._selected_id = flow.id
        self._refresh_list()
        self.workflows_changed.emit()

    def _delete_flow(self) -> None:
        flow = self._current()
        if flow is None or flow.locked:
            return
        self._workflows.remove(flow)
        if flow.id == self._active_id:
            self.active_workflow_changed.emit("")
        self._selected_id = ""
        self._refresh_list()
        self.workflows_changed.emit()

    def _save_flow(self) -> None:
        flow = self._current()
        if flow is None or flow.locked or not self.name_input.text().strip() or not self.primary_action.currentData():
            return
        flow.name = self.name_input.text().strip()
        flow.hotkey = self.hotkey_input.text().strip()
        flow.primary_action_id = str(self.primary_action.currentData())
        flow.secondary_action_id = str(self.secondary_action.currentData() or "")
        flow.secondary_trigger_ms = self.trigger_duration.milliseconds()
        flow.secondary_vision_preset_id = str(self.secondary_vision.currentData() or "")
        flow.active_duration_ms = self.active_duration.milliseconds()
        flow.rest_duration_ms = self.rest_duration.milliseconds()
        flow.repeats = self.repeats.value()
        flow.finish_current_action = self.finish_current.isChecked()
        flow.requires_reconfiguration = False
        self._refresh_list()
        self.workflows_changed.emit()

    def _activate_flow(self) -> None:
        flow = self._current()
        if flow:
            self._active_id = flow.id
            self._refresh_list()
            self.active_workflow_changed.emit(flow.id)
