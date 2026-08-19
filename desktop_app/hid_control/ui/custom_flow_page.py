from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..models import ActionDefinition, FishingPreset, FlowMode, FlowStep, VisionPreset, WorkflowDefinition
from .duration_input import DurationInput


# 使用短中文徽章，不依赖 Windows 对特殊 Unicode 图形的字体支持。
STEP_TYPES = {
    "empty": ("未配置", "+", "#94a3b8"),
    "group": ("步骤组", "组", "#7c3aed"),
    "action": ("操作", "操", "#2563eb"),
    "vision": ("识图", "识", "#0f766e"),
    "fishing": ("钓鱼", "钓", "#b45309"),
}
RELATION_TYPES = {
    "immediate": ("直接进入", ">", "#64748b"),
    "time": ("延迟后进入", "时", "#d97706"),
    "vision": ("识图确认后进入", "识", "#0f766e"),
    "step_complete": ("指定卡片完成后进入", "完", "#7c3aed"),
}


class FlowCard(QFrame):
    selected = Signal(str)
    add_next = Signal(str)

    def __init__(self, step: FlowStep, title: str, detail: str, color: str, relation_hint: str = "") -> None:
        super().__init__()
        self.step_id = step.id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("flowCard")
        # 只匹配卡片本体，避免 QFrame 通用选择器影响内部布局而出现两侧蓝色“括号”。
        self.setStyleSheet(f"QFrame#flowCard {{ background:#f8fafc; border:1px solid #dbe4ef; border-top:4px solid {color}; border-radius:10px; }} QFrame#flowCard:hover {{ background:#eef6ff; border-color:{color}; }}")
        layout = QVBoxLayout(self); layout.setContentsMargins(10, 8, 10, 6); layout.setSpacing(4)
        header = QHBoxLayout(); icon = QLabel(STEP_TYPES.get(step.kind, STEP_TYPES['empty'])[1]); icon.setFixedSize(28, 28); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color:white; background:{color}; border-radius:14px; font-weight:700;")
        name = QLabel(title); name.setStyleSheet("font-size:14px; font-weight:700; color:#0f172a;")
        status = QLabel("未配置" if step.kind == "empty" else "就绪" if step.enabled else "已停用")
        status.setStyleSheet("color:#475569; background:#e2e8f0; border-radius:8px; padding:2px 6px;")
        header.addWidget(icon); header.addWidget(name, 1); header.addWidget(status); layout.addLayout(header)
        detail_label = QLabel(detail); detail_label.setStyleSheet("color:#64748b;"); detail_label.setWordWrap(True); layout.addWidget(detail_label)
        if relation_hint:
            hint = QLabel(relation_hint); hint.setStyleSheet("color:#b45309; background:#fff7ed; border-radius:6px; padding:3px 6px;"); layout.addWidget(hint)
        footer = QHBoxLayout(); footer.addStretch(); add = QToolButton(); add.setText("+"); add.setToolTip("从此卡片创建后续流程卡片"); add.setFixedSize(24, 22)
        add.setStyleSheet("QToolButton { color:#2563eb; background:#eff6ff; border:1px solid #93c5fd; border-radius:5px; font-weight:700; } QToolButton:hover { background:#dbeafe; border-color:#2563eb; } QToolButton:pressed { background:#bfdbfe; padding-top:1px; }")
        add.clicked.connect(lambda: self.add_next.emit(self.step_id)); footer.addWidget(add); layout.addLayout(footer)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.step_id)
        super().mousePressEvent(event)


class RelationWidget(QFrame):
    selected = Signal(str, str)

    def __init__(self, source_id: str, target: FlowStep, text: str, icon: str, color: str, depth: int) -> None:
        super().__init__()
        self.source_id, self.target_id = source_id, target.id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self); layout.setContentsMargins(20 + depth * 26, 0, 0, 0); layout.setSpacing(7)
        line = QLabel("|\nV"); line.setStyleSheet(f"color:{color}; font-size:16px; font-weight:700;"); line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge = QLabel(f"{icon}  {text}  · 点击设置关系")
        badge.setStyleSheet(f"color:{color}; background:#f8fafc; border:1px dashed {color}; border-radius:8px; padding:4px 8px;")
        layout.addWidget(line); layout.addWidget(badge); layout.addStretch()

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.source_id, self.target_id)
        super().mousePressEvent(event)


class CustomFlowPage(QWidget):
    """轻量 RPA 编排：卡片定义任务，箭头定义触发、暂停与恢复关系。"""

    workflows_changed = Signal()
    active_workflow_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._workflows: list[WorkflowDefinition] = []; self._actions: list[ActionDefinition] = []
        self._fishing_presets: list[FishingPreset] = []; self._vision_presets: list[VisionPreset] = []
        self._active_id = ""; self._selected_id = ""; self._selected_step_id = ""; self._selected_relation: tuple[str, str] | None = None

        self.flow_selector = QComboBox(); self.name_input = QLineEdit(); self.hotkey_input = QLineEdit(); self.run_once = QCheckBox("边界切换保护：等待当前操作完成再切换")
        self.run_once.setToolTip("到达定时触发点或本轮结束点时，不从中间打断正在执行的操作，避免键鼠顺序紊乱。")
        self.active_duration = DurationInput(maximum_milliseconds=86_400_000, allow_zero=True)
        self.add_blank_button = QPushButton("＋ 添加空白卡片"); self.add_blank_button.clicked.connect(self._add_root_card)
        self.canvas_hint = QLabel("卡片表示任务，箭头表示关系。点击卡片编辑任务；点击箭头设置触发、暂停和恢复。")
        self.canvas_hint.setWordWrap(True); self.canvas_hint.setStyleSheet("color:#475569; background:#f8fafc; border-radius:8px; padding:8px;")
        self.cards_layout = QVBoxLayout(); self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.execution_preview = QLabel(); self.execution_preview.setWordWrap(True); self.execution_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.execution_preview.setMinimumHeight(116)
        self.execution_preview.setFont(QFont("Microsoft YaHei UI", 10))
        self.execution_preview.setStyleSheet("QLabel { color:#334155; background:#f8fafc; border:1px solid #dbe4ef; border-radius:8px; padding:8px; font-family:'Microsoft YaHei UI'; font-size:10pt; }")
        self.preview_toggle = QPushButton("隐藏执行预览"); self.preview_toggle.setMinimumSize(136, 32); self.preview_toggle.setFont(QFont("Microsoft YaHei UI", 9))
        self.preview_toggle.setStyleSheet("QPushButton { color:#1e3a5f; background:#eff6ff; border:1px solid #93c5fd; border-radius:6px; padding:3px 12px; } QPushButton:hover { background:#dbeafe; border-color:#2563eb; } QPushButton:pressed { background:#bfdbfe; }")
        self.preview_toggle.clicked.connect(self._toggle_execution_preview)
        self.preview_panel = QFrame(); preview_layout = QVBoxLayout(self.preview_panel); preview_layout.setContentsMargins(0, 6, 0, 0); preview_layout.addWidget(self.execution_preview); preview_layout.addWidget(self.preview_toggle, alignment=Qt.AlignmentFlag.AlignRight)
        cards_holder = QWidget(); cards_holder.setLayout(self.cards_layout); self.cards_scroll = QScrollArea(); self.cards_scroll.setWidgetResizable(True); self.cards_scroll.setWidget(cards_holder)

        self.object_title = QLabel("选择一个流程卡片或箭头"); self.object_title.setStyleSheet("font-size:15px; font-weight:700; color:#1e293b;")
        self.feedback = QLabel("新增空白卡片后，在右侧选择它要执行的任务。"); self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet("color:#475569; background:#f8fafc; border-radius:6px; padding:7px;")

        self.step_title = QLineEdit(); self.step_enabled = QCheckBox("启用此卡片")
        self.step_kind = QComboBox(); self.step_kind.addItem("＋ 选择任务类型", "empty")
        for kind in ("action", "vision", "fishing", "group"):
            label, icon, _ = STEP_TYPES[kind]; self.step_kind.addItem(f"{icon} {label}", kind)
        self.group_mode = QComboBox(); self.group_mode.addItem("顺序执行子卡片", "sequential"); self.group_mode.addItem("调度执行子卡片", "scheduled")
        self.action_combo = QComboBox(); self.vision_combo = QComboBox(); self.fishing_combo = QComboBox()
        self.repeat_mode = QComboBox(); self.repeat_mode.addItem("执行一次", "once"); self.repeat_mode.addItem("重复指定次数", "count"); self.repeat_mode.addItem("持续到时限", "duration"); self.repeat_mode.addItem("持续到手动停止", "forever")
        self.repeat_count = QSpinBox(); self.repeat_count.setRange(1, 100_000); self.limit = DurationInput(maximum_milliseconds=86_400_000, allow_zero=True)
        self.random_wait_min = DurationInput(maximum_milliseconds=86_400_000, allow_zero=True); self.random_wait_max = DurationInput(maximum_milliseconds=86_400_000, allow_zero=True)
        self.save_card = QPushButton("保存卡片"); self.copy_card = QPushButton("复制卡片"); self.delete_card = QPushButton("删除卡片")
        self.step_kind.currentIndexChanged.connect(self._update_card_editor); self.repeat_mode.currentIndexChanged.connect(self._update_card_editor)
        self.save_card.clicked.connect(self._save_card); self.copy_card.clicked.connect(self._copy_card); self.delete_card.clicked.connect(self._delete_card)
        self.card_editor = QFrame(); card_form = QFormLayout(self.card_editor)
        card_form.addRow("卡片显示名称", self.step_title); card_form.addRow(self.step_enabled); card_form.addRow("卡片任务类型", self.step_kind); card_form.addRow("使用已保存操作", self.action_combo); card_form.addRow("使用识图预设", self.vision_combo); card_form.addRow("使用钓鱼预设", self.fishing_combo); card_form.addRow("步骤组方式", self.group_mode); card_form.addRow("此卡片的执行方式", self.repeat_mode); card_form.addRow("重复次数", self.repeat_count); card_form.addRow("此卡片最长运行时间", self.limit); card_form.addRow("执行前随机等待（最小）", self.random_wait_min); card_form.addRow("执行前随机等待（最大）", self.random_wait_max)
        card_buttons = QHBoxLayout(); card_buttons.addWidget(self.save_card); card_buttons.addWidget(self.copy_card); card_buttons.addWidget(self.delete_card); card_form.addRow(card_buttons)

        self.relation_type = QComboBox()
        for key, (label, icon, _color) in RELATION_TYPES.items(): self.relation_type.addItem(f"{icon} {label}", key)
        self.relation_delay = DurationInput(maximum_milliseconds=86_400_000, allow_zero=True); self.relation_vision = QComboBox(); self.relation_step = QComboBox()
        self.pause_targets = QListWidget(); self.pause_targets.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection); self.pause_targets.setMaximumHeight(100)
        self.resume_paused = QCheckBox("当前处理完成后，恢复被暂停的卡片"); self.resume_paused.setToolTip("关闭后，目标卡片会保持暂停，直到流程结束或被后续关系重新启用。"); self.resume_paused.setChecked(True); self.save_relation = QPushButton("保存箭头关系")
        self.relation_type.currentIndexChanged.connect(self._update_relation_editor); self.save_relation.clicked.connect(self._save_relation)
        self.relation_editor = QFrame(); relation_form = QFormLayout(self.relation_editor)
        relation_form.addRow("进入此卡片的条件", self.relation_type); relation_form.addRow("延迟多久后进入", self.relation_delay); relation_form.addRow("使用哪个识图确认", self.relation_vision); relation_form.addRow("等待哪张卡片完成", self.relation_step); relation_form.addRow("进入前暂停哪些卡片", self.pause_targets); relation_form.addRow(self.resume_paused); relation_form.addRow(self.save_relation)

        self.editor_stack = QStackedWidget(); self.editor_stack.addWidget(self.card_editor); self.editor_stack.addWidget(self.relation_editor)
        top = QHBoxLayout(); top.addWidget(QLabel("当前自定义流程")); top.addWidget(self.flow_selector, 1)
        self.new_button = QPushButton("新建流程"); self.save_button = QPushButton("保存流程"); self.delete_button = QPushButton("删除流程"); self.lock_button = QPushButton("锁定流程")
        top.addWidget(self.new_button); top.addWidget(self.save_button); top.addWidget(self.delete_button); top.addWidget(self.lock_button)
        self.new_button.clicked.connect(self._new_flow); self.save_button.clicked.connect(self._save_flow); self.delete_button.clicked.connect(self._delete_flow); self.lock_button.clicked.connect(self._toggle_lock); self.flow_selector.currentIndexChanged.connect(self._select_flow)
        left = QWidget(); left_layout = QVBoxLayout(left); tools = QHBoxLayout(); tools.addWidget(QLabel("流程卡片")); tools.addStretch(); tools.addWidget(self.add_blank_button); left_layout.addLayout(tools); left_layout.addWidget(self.canvas_hint); left_layout.addWidget(self.cards_scroll, 1); left_layout.addWidget(self.preview_panel)
        right = QFrame(); right.setMinimumWidth(430); right_layout = QVBoxLayout(right); flow_box = QFrame(); flow_form = QFormLayout(flow_box); flow_form.addRow("流程名称", self.name_input); flow_form.addRow("独立快捷键", self.hotkey_input); flow_form.addRow("本轮最大运行时长", self.active_duration); flow_form.addRow(self.run_once)
        right_layout.addWidget(QLabel("流程设置")); right_layout.addWidget(flow_box); right_layout.addWidget(self.object_title); right_layout.addWidget(self.editor_stack); right_layout.addWidget(self.feedback); right_layout.addStretch()
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setWidget(right); right_scroll.setMinimumWidth(430)
        body = QHBoxLayout(); body.addWidget(left, 1); body.addWidget(right_scroll)
        layout = QVBoxLayout(self); layout.addLayout(top); layout.addLayout(body, 1)
        self._set_editors(False)

    def set_data(self, workflows: list[WorkflowDefinition], actions: list[ActionDefinition], active_id: str, fishing_presets: list[FishingPreset] | None = None, vision_presets: list[VisionPreset] | None = None) -> None:
        self._workflows, self._actions, self._active_id = workflows, actions, active_id; self._fishing_presets, self._vision_presets = fishing_presets or [], vision_presets or []; self._refresh_flows()
    def _flows(self) -> list[WorkflowDefinition]: return [item for item in self._workflows if item.mode == FlowMode.CUSTOM]
    def _current(self) -> WorkflowDefinition | None: return next((item for item in self._workflows if item.id == self._selected_id), None)
    def _root(self, create: bool = False) -> FlowStep | None:
        flow = self._current()
        if flow and flow.root_step is None and create: flow.root_step = FlowStep(title="整个流程", kind="group")
        return flow.root_step if flow else None
    def _walk(self, root: FlowStep | None = None):
        root = root or self._root()
        if root is None: return
        yield root
        for child in root.children: yield from self._walk(child)
    def _step(self, step_id: str | None = None) -> FlowStep | None: return next((item for item in self._walk() if item.id == (step_id or self._selected_step_id)), None)
    def _parent_index(self, step_id: str):
        for parent in self._walk():
            for index, child in enumerate(parent.children):
                if child.id == step_id: return parent, index
        return None, -1

    def _refresh_flows(self) -> None:
        current = self._selected_id; self.flow_selector.blockSignals(True); self.flow_selector.clear()
        for flow in self._flows(): self.flow_selector.addItem(flow.name + ("（当前）" if flow.id == self._active_id else ""), flow.id)
        self.flow_selector.blockSignals(False); index = self.flow_selector.findData(current)
        if index < 0 and self.flow_selector.count(): index = 0
        if index >= 0: self.flow_selector.setCurrentIndex(index); self._select_flow(index)
    def _select_flow(self, index: int) -> None:
        if index < 0: return
        self._selected_id = str(self.flow_selector.itemData(index)); self._selected_step_id = ""; self._selected_relation = None; flow = self._current()
        if flow is None: return
        self._root(True); self.name_input.setText(flow.name); self.hotkey_input.setText(flow.hotkey); self.run_once.setChecked(flow.finish_current_action); self.active_duration.set_milliseconds(flow.active_duration_ms)
        self._refresh_references(); self._refresh_cards(); self._set_editors(not flow.locked)
        editable = not flow.locked
        for widget in (self.save_button, self.delete_button, self.add_blank_button, self.name_input, self.hotkey_input, self.run_once, self.active_duration): widget.setEnabled(editable)
        self.lock_button.setEnabled(True); self.lock_button.setText("已锁定 · 点击解锁" if flow.locked else "锁定流程")
        self.lock_button.setStyleSheet("QPushButton { color:#5b4b75; background:#f1edf7; border:1px solid #c4b5d8; border-radius:6px; padding:4px 9px; }" if flow.locked else "QPushButton { color:#36546f; background:#f5f8fb; border:1px solid #b9cad9; border-radius:6px; padding:4px 9px; } QPushButton:hover { background:#e8f0f7; border-color:#6b8aa5; }")
    def _refresh_references(self) -> None:
        for combo, values, placeholder in ((self.action_combo, self._actions, "请选择已保存操作"), (self.vision_combo, self._vision_presets, "请选择识图预设"), (self.fishing_combo, self._fishing_presets, "请选择钓鱼预设")):
            combo.blockSignals(True); combo.clear(); combo.addItem(placeholder, "")
            for item in values: combo.addItem(item.name, item.id)
            combo.blockSignals(False)
        self.relation_vision.blockSignals(True); self.relation_vision.clear(); self.relation_vision.addItem("请选择识图预设", "")
        for item in self._vision_presets: self.relation_vision.addItem(item.name, item.id)
        self.relation_vision.blockSignals(False); self.relation_step.blockSignals(True); self.relation_step.clear(); self.relation_step.addItem("请选择前置卡片", "")
        for item in self._walk():
            if item is not self._root(): self.relation_step.addItem(self._title(item), item.id)
        self.relation_step.blockSignals(False)
    def _title(self, step: FlowStep) -> str:
        if step.title and step.title != "未配置卡片": return step.title
        if step.kind == "action": return next((item.name for item in self._actions if item.id == step.action_id), "未选择操作")
        if step.kind == "vision": return next((item.name for item in self._vision_presets if item.id == step.vision_preset_id), "未选择识图预设")
        if step.kind == "fishing": return next((item.name for item in self._fishing_presets if item.id == step.fishing_preset_id), "未选择钓鱼预设")
        return STEP_TYPES.get(step.kind, STEP_TYPES['empty'])[0]
    def _detail(self, step: FlowStep) -> str:
        if step.kind == "empty": return "点击此卡片，在右侧选择操作、识图预设或钓鱼预设"
        if step.kind == "group": return "顺序步骤组" if step.group_mode == "sequential" else "调度步骤组"
        return STEP_TYPES.get(step.kind, STEP_TYPES['empty'])[0] + "任务"
    def _relation_text(self, step: FlowStep) -> tuple[str, str, str]:
        label, icon, color = RELATION_TYPES.get(step.trigger_type, RELATION_TYPES['immediate'])
        if step.trigger_type == "time": label = f"等待 {step.trigger_after_ms / 1000:g} 秒后"
        elif step.trigger_type == "vision": label = "识图匹配后"
        elif step.trigger_type == "step_complete": label = "指定卡片完成后"
        if step.pause_target_step_ids: label += f" · 暂停 {len(step.pause_target_step_ids)} 张卡片"
        return label, icon, color
    def _clear_layout(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0); widget = item.widget()
            if widget and widget is not self.preview_panel: widget.deleteLater()
    def _refresh_cards(self) -> None:
        self._clear_layout(); root = self._root()
        if root:
            for card in root.children: self._render_card(card, root.id, 0)
        self._refresh_execution_preview()
        self.cards_layout.addStretch()
    def _render_card(self, step: FlowStep, parent_id: str, depth: int) -> None:
        if parent_id != self._root().id:
            label, icon, color = self._relation_text(step); relation = RelationWidget(parent_id, step, label, icon, color, depth); relation.selected.connect(self._select_relation); self.cards_layout.addWidget(relation)
        holder = QWidget(); row = QHBoxLayout(holder); row.setContentsMargins(depth * 28, 2, 10, 2); card = FlowCard(step, self._title(step), self._detail(step), STEP_TYPES.get(step.kind, STEP_TYPES['empty'])[2], "")
        card.selected.connect(self._select_card); card.add_next.connect(self._add_child_card); row.addWidget(card, 1); self.cards_layout.addWidget(holder)
        for child in step.children: self._render_card(child, step.id, depth + 1)
    def _toggle_execution_preview(self) -> None:
        visible = not self.execution_preview.isVisible()
        self.execution_preview.setVisible(visible)
        self.preview_toggle.setText("隐藏执行预览" if visible else "显示执行预览")

    def _refresh_execution_preview(self) -> None:
        flow = self._current(); lines = ["本轮流程执行预览"]
        if flow is None or not self._root() or not self._root().children:
            lines.append("尚未添加流程卡片。")
        else:
            for index, card in enumerate(self._walk(), start=0):
                if card is self._root(): continue
                wait = ""
                if card.random_wait_max_ms:
                    wait = f"；执行前随机等待 {card.random_wait_min_ms / 1000:g}～{card.random_wait_max_ms / 1000:g} 秒"
                relation = ""
                if card.trigger_type != "immediate": relation = f"；{self._relation_text(card)[0]}"
                lines.append(f"{len(lines)}. {self._title(card)}{wait}{relation}。")
            if flow.finish_current_action:
                lines.append("边界切换保护：当前操作会完成后再切换。")
        self.execution_preview.setText("\n".join(lines))

    def _add_root_card(self) -> None:
        root = self._root(True); flow = self._current()
        if not root or not flow or flow.locked: return
        card = FlowStep(kind="empty", title="未配置卡片"); root.children.append(card); self._selected_step_id = card.id; self._selected_relation = None; self._feedback("已添加空白卡片", "#2563eb"); self._refresh_references(); self._refresh_cards(); self._load_card()
    def _add_child_card(self, parent_id: str) -> None:
        parent = self._step(parent_id); flow = self._current()
        if not parent or not flow or flow.locked: return
        card = FlowStep(kind="empty", title="未配置卡片"); parent.children.append(card); self._selected_step_id = card.id; self._selected_relation = None; self._feedback("已创建后续空白卡片，请选择箭头关系或配置任务", "#2563eb"); self._refresh_references(); self._refresh_cards(); self._load_card()
    def _select_card(self, step_id: str) -> None:
        self._selected_step_id = step_id; self._selected_relation = None; self._load_card()
    def _select_relation(self, source_id: str, target_id: str) -> None:
        self._selected_relation = (source_id, target_id); self._selected_step_id = ""; self._load_relation()
    def _load_card(self) -> None:
        step = self._step(); flow = self._current()
        if not step or not flow: return
        self.object_title.setText(f"卡片：{self._title(step)}"); self.editor_stack.setCurrentWidget(self.card_editor); self._set_editors(not flow.locked)
        self.step_title.setText("" if step.title == "未配置卡片" else step.title); self.step_enabled.setChecked(step.enabled); self.step_kind.setCurrentIndex(max(0, self.step_kind.findData(step.kind)))
        self.action_combo.setCurrentIndex(max(0, self.action_combo.findData(step.action_id))); self.vision_combo.setCurrentIndex(max(0, self.vision_combo.findData(step.vision_preset_id))); self.fishing_combo.setCurrentIndex(max(0, self.fishing_combo.findData(step.fishing_preset_id))); self.group_mode.setCurrentIndex(max(0, self.group_mode.findData(step.group_mode))); self.repeat_mode.setCurrentIndex(max(0, self.repeat_mode.findData(step.repeat_mode))); self.repeat_count.setValue(step.repeat_count); self.limit.set_milliseconds(step.limit_ms); self.random_wait_min.set_milliseconds(step.random_wait_min_ms); self.random_wait_max.set_milliseconds(step.random_wait_max_ms); self._update_card_editor()
    def _load_relation(self) -> None:
        if not self._selected_relation: return
        source = self._step(self._selected_relation[0]); target = self._step(self._selected_relation[1]); flow = self._current()
        if not source or not target or not flow: return
        self.object_title.setText(f"关系：{self._title(source)}  →  {self._title(target)}"); self.editor_stack.setCurrentWidget(self.relation_editor); self._set_editors(not flow.locked)
        self.relation_type.setCurrentIndex(max(0, self.relation_type.findData(target.trigger_type))); self.relation_delay.set_milliseconds(target.trigger_after_ms); self.relation_vision.setCurrentIndex(max(0, self.relation_vision.findData(target.trigger_vision_preset_id))); self.relation_step.setCurrentIndex(max(0, self.relation_step.findData(target.trigger_step_id))); self.resume_paused.setChecked(target.resume_paused)
        self.pause_targets.clear()
        for candidate in self._walk():
            if candidate.id in {target.id, self._root().id}: continue
            item = QListWidgetItem(self._title(candidate)); item.setData(Qt.ItemDataRole.UserRole, candidate.id); item.setSelected(candidate.id in target.pause_target_step_ids); self.pause_targets.addItem(item)
        self._update_relation_editor()
    def _update_card_editor(self) -> None:
        kind = str(self.step_kind.currentData() or "empty"); self.action_combo.setVisible(kind == "action"); self.vision_combo.setVisible(kind == "vision"); self.fishing_combo.setVisible(kind == "fishing"); self.group_mode.setVisible(kind == "group"); self.repeat_count.setVisible(self.repeat_mode.currentData() == "count")
    def _update_relation_editor(self) -> None:
        kind = str(self.relation_type.currentData() or "immediate"); self.relation_delay.setVisible(kind == "time"); self.relation_vision.setVisible(kind == "vision"); self.relation_step.setVisible(kind == "step_complete")
    def _save_card(self) -> None:
        step = self._step(); flow = self._current()
        if not step or not flow or flow.locked: return
        old_kind = step.kind; step.kind = str(self.step_kind.currentData()); step.enabled = self.step_enabled.isChecked(); step.action_id = str(self.action_combo.currentData() or ""); step.vision_preset_id = str(self.vision_combo.currentData() or ""); step.fishing_preset_id = str(self.fishing_combo.currentData() or ""); step.group_mode = str(self.group_mode.currentData()); step.repeat_mode = str(self.repeat_mode.currentData()); step.repeat_count = self.repeat_count.value(); step.limit_ms = self.limit.milliseconds(); step.random_wait_min_ms = self.random_wait_min.milliseconds(); step.random_wait_max_ms = self.random_wait_max.milliseconds()
        if step.random_wait_min_ms > step.random_wait_max_ms:
            step.random_wait_min_ms, step.random_wait_max_ms = step.random_wait_max_ms, step.random_wait_min_ms
            self._feedback("随机等待范围已自动调整为最小值到最大值", "#d97706")
        explicit = self.step_title.text().strip()
        if explicit: step.title = explicit
        elif step.kind == "action": step.title = next((item.name for item in self._actions if item.id == step.action_id), "未选择操作")
        elif step.kind == "vision": step.title = next((item.name for item in self._vision_presets if item.id == step.vision_preset_id), "未选择识图预设")
        elif step.kind == "fishing": step.title = next((item.name for item in self._fishing_presets if item.id == step.fishing_preset_id), "未选择钓鱼预设")
        elif step.kind == "empty": step.title = "未配置卡片"
        elif not step.title: step.title = "步骤组"
        self._feedback("已保存卡片", "#16a34a"); self._refresh_references(); self._refresh_cards(); self.workflows_changed.emit()
    def _save_relation(self) -> None:
        if not self._selected_relation: return
        target = self._step(self._selected_relation[1]); flow = self._current()
        if not target or not flow or flow.locked: return
        target.trigger_type = str(self.relation_type.currentData()); target.trigger_after_ms = self.relation_delay.milliseconds(); target.trigger_vision_preset_id = str(self.relation_vision.currentData() or ""); target.trigger_step_id = str(self.relation_step.currentData() or ""); target.pause_target_step_ids = [self.pause_targets.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.pause_targets.count()) if self.pause_targets.item(index).isSelected()]; target.resume_paused = self.resume_paused.isChecked()
        self._feedback("已保存箭头关系", "#d97706"); self._refresh_cards(); self.workflows_changed.emit()
    def _copy_card(self) -> None:
        step = self._step(); parent, index = self._parent_index(self._selected_step_id); flow = self._current()
        if not step or not parent or not flow or flow.locked: return
        duplicate = deepcopy(step)
        def renew(item: FlowStep) -> None:
            item.id = FlowStep().id
            for child in item.children: renew(child)
        renew(duplicate); parent.children.insert(index + 1, duplicate); self._selected_step_id = duplicate.id; self._feedback("已复制卡片", "#7c3aed"); self._refresh_references(); self._refresh_cards(); self._load_card(); self.workflows_changed.emit()
    def _delete_card(self) -> None:
        parent, index = self._parent_index(self._selected_step_id); flow = self._current()
        if not parent or not flow or flow.locked: return
        del parent.children[index]; self._selected_step_id = ""; self._feedback("已删除卡片", "#dc2626"); self._refresh_references(); self._refresh_cards(); self.workflows_changed.emit()
    def _feedback(self, text: str, color: str) -> None: self.feedback.setText(text); self.feedback.setStyleSheet(f"color:white; background:{color}; border-radius:6px; padding:7px; font-weight:700;")
    def _new_flow(self) -> None:
        flow = WorkflowDefinition(name=f"自定义流程 {len(self._flows()) + 1}", mode=FlowMode.CUSTOM, root_step=FlowStep(title="整个流程", kind="group")); self._workflows.append(flow); self._selected_id = flow.id; self._refresh_flows(); self.workflows_changed.emit()
    def _save_flow(self) -> None:
        flow = self._current()
        if not flow or flow.locked: return
        flow.name = self.name_input.text().strip() or flow.name; flow.hotkey = self.hotkey_input.text().strip(); flow.finish_current_action = self.run_once.isChecked(); flow.active_duration_ms = self.active_duration.milliseconds(); flow.tasks = []; flow.blocks = []; flow.custom_steps = []; flow.requires_reconfiguration = False; self._refresh_flows(); self.workflows_changed.emit()
    def _delete_flow(self) -> None:
        flow = self._current()
        if not flow or flow.locked: return
        self._workflows.remove(flow)
        if flow.id == self._active_id:
            self._active_id = ""; self.active_workflow_changed.emit("")
        self._selected_id = ""; self._selected_step_id = ""; self._selected_relation = None
        self._feedback("已删除自定义流程", "#dc2626"); self._refresh_flows(); self.workflows_changed.emit()

    def _toggle_lock(self) -> None:
        flow = self._current()
        if not flow: return
        flow.locked = not flow.locked
        self._feedback("流程已锁定，编辑已关闭" if flow.locked else "流程已解锁，可以继续编辑", "#64748b" if flow.locked else "#16a34a")
        self._refresh_flows(); self.workflows_changed.emit()

    def _activate(self) -> None:
        flow = self._current()
        if flow: self._active_id = flow.id; self.active_workflow_changed.emit(flow.id); self._refresh_flows()
    def _set_editors(self, enabled: bool) -> None: self.card_editor.setEnabled(enabled); self.relation_editor.setEnabled(enabled)

    # 兼容旧测试/自动化调用：创建的是空白卡片，而不再直接创建任务类型。
    def _add_step(self, after_id: str | None) -> None:
        if after_id: self._add_child_card(after_id)
        else: self._add_root_card()
