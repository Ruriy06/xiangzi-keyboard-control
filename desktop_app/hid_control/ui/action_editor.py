from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStyle,
    QToolButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ActionDefinition, ActionStep, STEP_LABELS
from .duration_input import format_duration
from .step_input import MOUSE_BUTTONS, StepInputPanel


class StepTable(QTableWidget):
    row_dropped = Signal(int, int)

    def __init__(self) -> None:
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels(["步骤类型", "设置", "节奏"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setMinimumHeight(260)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)


class ActionEditor(QWidget):
    actions_changed = Signal()
    create_workflow_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[ActionDefinition] = []
        self._selected_id = ""
        self.action_list = QListWidget()
        self.action_list.setFixedWidth(180)
        self.action_list.setSpacing(0)
        self.action_name = QLineEdit()
        self.action_hotkey = QLineEdit()
        self.action_hotkey.setPlaceholderText("留空不绑定；例如 Ctrl+Alt+1")
        self.step_table = StepTable()
        self.step_input = StepInputPanel(keyboard_height=240)

        new_button = self._action_button("新建", QStyle.StandardPixmap.SP_FileIcon, "primaryAction", "新建操作")
        self.delete_action_button = self._action_button("删除", QStyle.StandardPixmap.SP_TrashIcon, "dangerAction", "删除当前操作")
        create_workflow_button = self._action_button("创建 AB流程", QStyle.StandardPixmap.SP_ArrowRight, "secondaryAction", "根据当前操作创建 AB 流程")
        self.add_step_button = self._action_button("添加步骤", QStyle.StandardPixmap.SP_FileDialogNewFolder, "primaryAction", "将当前编辑内容添加为新步骤")
        self.update_step_button = self._action_button("更新选中步骤", QStyle.StandardPixmap.SP_BrowserReload, "successAction", "用当前编辑内容更新选中步骤")
        self.delete_step_button = self._action_button("删除选中步骤", QStyle.StandardPixmap.SP_TrashIcon, "dangerAction", "删除当前选中步骤")
        self.move_up_button = self._action_button("上移步骤", QStyle.StandardPixmap.SP_ArrowUp, "secondaryAction", "将选中步骤上移")
        self.move_down_button = self._action_button("下移步骤", QStyle.StandardPixmap.SP_ArrowDown, "secondaryAction", "将选中步骤下移")
        self.save_button = self._action_button("保存操作设置", QStyle.StandardPixmap.SP_DialogSaveButton, "successAction", "保存操作名称和快捷键")

        new_button.clicked.connect(self._new_action)
        self.delete_action_button.clicked.connect(self._delete_action)
        create_workflow_button.clicked.connect(self._create_workflow)
        self.add_step_button.clicked.connect(self._add_step)
        self.update_step_button.clicked.connect(self._update_step)
        self.delete_step_button.clicked.connect(self._delete_step)
        self.move_up_button.clicked.connect(lambda: self._move_step(-1))
        self.move_down_button.clicked.connect(lambda: self._move_step(1))
        self.save_button.clicked.connect(self._save_name)
        self.action_list.currentRowChanged.connect(self._select_row)
        self.step_table.itemSelectionChanged.connect(self._load_selected_step)
        self.step_table.row_dropped.connect(self._drag_reorder)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("可复用操作"))
        left_layout.addWidget(self.action_list, 1)
        action_tools = QHBoxLayout()
        action_tools.addWidget(new_button)
        action_tools.addWidget(self.delete_action_button)
        left_layout.addLayout(action_tools)
        left_layout.addWidget(create_workflow_button)

        right_layout = QVBoxLayout()
        title = QLabel("操作编辑")
        title.setObjectName("pageTitle")
        right_layout.addWidget(title)
        right_layout.addWidget(QLabel("按步骤类型选择对应控件。鼠标步骤使用按钮选择器，不需要填写 LEFT、RIGHT 等协议名称。"))
        right_layout.addWidget(QLabel("操作名称"))
        right_layout.addWidget(self.action_name)
        right_layout.addWidget(QLabel("独立切换快捷键（留空不绑定；按一次启动循环，再按一次停止）"))
        right_layout.addWidget(self.action_hotkey)
        right_layout.addWidget(self.step_input)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_step_button)
        buttons.addWidget(self.update_step_button)
        buttons.addWidget(self.delete_step_button)
        buttons.addWidget(self.move_up_button)
        buttons.addWidget(self.move_down_button)
        buttons.addWidget(self.save_button)
        right_layout.addLayout(buttons)
        right_layout.addWidget(QLabel("步骤列表：可直接拖动整行调整顺序。"))
        right_layout.addWidget(self.step_table, 1)

        right_widget = QWidget(); right_widget.setLayout(right_layout)
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setWidget(right_widget)
        layout = QHBoxLayout(self)
        layout.addLayout(left_layout, 0)
        layout.addWidget(right_scroll, 1)

    @staticmethod
    def _action_button(text: str, icon: QStyle.StandardPixmap, role: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(button.style().standardIcon(icon))
        button.setIconSize(QSize(16, 16))
        button.setProperty("actionRole", role)
        button.setToolTip(tooltip)
        return button

    def set_actions(self, actions: list[ActionDefinition]) -> None:
        self._actions = actions
        self._refresh_list()

    def _refresh_list(self) -> None:
        selected_id = self._selected_id
        self.action_list.blockSignals(True)
        self.action_list.clear()
        selected_row = -1
        for row, action in enumerate(self._actions):
            item = QListWidgetItem()
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 1, 2, 1)
            row_layout.addWidget(QLabel(action.name), 1)
            lock_button = QToolButton()
            lock_button.setText("🔒" if action.locked else "🔓")
            lock_button.setToolTip("点击解锁" if action.locked else "点击锁定；锁定后不可修改或删除")
            lock_button.clicked.connect(lambda _checked=False, action_id=action.id: self._toggle_lock(action_id))
            row_layout.addWidget(lock_button)
            item.setSizeHint(QSize(0, 30))
            self.action_list.addItem(item)
            self.action_list.setItemWidget(item, row_widget)
            if action.id == selected_id:
                selected_row = row
        self.action_list.blockSignals(False)
        if selected_row >= 0:
            self.action_list.setCurrentRow(selected_row)
        elif self._actions:
            self.action_list.setCurrentRow(0)
        else:
            self._selected_id = ""
            self.action_name.clear()
            self.action_hotkey.clear()
            self.step_table.setRowCount(0)
            self._set_editing_enabled(False)

    def _toggle_lock(self, action_id: str) -> None:
        action = next((item for item in self._actions if item.id == action_id), None)
        if action is None:
            return
        action.locked = not action.locked
        self._refresh_list()
        self.actions_changed.emit()

    def _set_editing_enabled(self, enabled: bool) -> None:
        for widget in (
            self.action_name,
            self.action_hotkey,
            self.step_input,
            self.add_step_button,
            self.update_step_button,
            self.delete_step_button,
            self.move_up_button,
            self.move_down_button,
            self.save_button,
            self.delete_action_button,
        ):
            widget.setEnabled(enabled)

    def _current_action(self) -> ActionDefinition | None:
        return next((action for action in self._actions if action.id == self._selected_id), None)

    def _select_row(self, row: int) -> None:
        if row < 0 or row >= len(self._actions):
            return
        action = self._actions[row]
        self._selected_id = action.id
        self.action_name.setText(action.name)
        self.action_hotkey.setText(action.hotkey)
        self._refresh_steps(action)
        self._set_editing_enabled(not action.locked)

    def _refresh_steps(self, action: ActionDefinition) -> None:
        self.step_table.blockSignals(True)
        self.step_table.setRowCount(len(action.steps))
        for row, step in enumerate(action.steps):
            self.step_table.setItem(row, 0, QTableWidgetItem(STEP_LABELS.get(step.kind, step.kind)))
            if step.kind == "wait" and step.value.isdigit():
                detail = format_duration(int(step.value))
            elif step.kind in {"mouse_click", "mouse_button_down", "mouse_button_up"} and step.value not in {value for _, value in MOUSE_BUTTONS}:
                detail = f"无效鼠标按钮：{step.value}"
            else:
                detail = step.value
            self.step_table.setItem(row, 1, QTableWidgetItem(detail))
            rhythm_parts = []
            if step.random_wait_max_ms: rhythm_parts.append(f"前随机 {format_duration(step.random_wait_min_ms)}～{format_duration(step.random_wait_max_ms)}")
            if step.delay_after_ms: rhythm_parts.append(f"后 {format_duration(step.delay_after_ms)}")
            self.step_table.setItem(row, 2, QTableWidgetItem("；".join(rhythm_parts) or "默认节奏"))
        self.step_table.blockSignals(False)

    def _new_action(self) -> None:
        action = ActionDefinition(name=f"操作 {len(self._actions) + 1}")
        self._actions.append(action)
        self._selected_id = action.id
        self._refresh_list()
        self.actions_changed.emit()

    def _delete_action(self) -> None:
        action = self._current_action()
        if action is None or action.locked:
            return
        self._actions.remove(action)
        self._selected_id = ""
        self._refresh_list()
        self.actions_changed.emit()

    def _create_workflow(self) -> None:
        action = self._current_action()
        if action:
            self.create_workflow_requested.emit(action.id)

    def _save_name(self) -> None:
        action = self._current_action()
        if action is None or action.locked or not self.action_name.text().strip():
            return
        action.name = self.action_name.text().strip()
        action.hotkey = self.action_hotkey.text().strip()
        self._refresh_list()
        self.actions_changed.emit()

    def _add_step(self) -> None:
        action = self._current_action()
        if action is None or action.locked:
            return
        action.steps.append(self.step_input.build_step())
        self._refresh_steps(action)
        self.step_table.selectRow(len(action.steps) - 1)
        self.actions_changed.emit()

    def _load_selected_step(self) -> None:
        action = self._current_action()
        row = self.step_table.currentRow()
        if action is not None and 0 <= row < len(action.steps):
            self.step_input.set_step(action.steps[row])

    def _update_step(self) -> None:
        action = self._current_action()
        row = self.step_table.currentRow()
        if action is None or action.locked or not 0 <= row < len(action.steps):
            return
        action.steps[row] = self.step_input.build_step()
        self._refresh_steps(action)
        self.step_table.selectRow(row)
        self.actions_changed.emit()

    def _delete_step(self) -> None:
        action = self._current_action()
        row = self.step_table.currentRow()
        if action is None or action.locked or not 0 <= row < len(action.steps):
            return
        del action.steps[row]
        self._refresh_steps(action)
        self.actions_changed.emit()

    def _move_step(self, offset: int) -> None:
        action = self._current_action()
        source_row = self.step_table.currentRow()
        target_row = source_row + offset
        if action is None or action.locked or not (0 <= source_row < len(action.steps) and 0 <= target_row < len(action.steps)):
            return
        action.steps[source_row], action.steps[target_row] = action.steps[target_row], action.steps[source_row]
        self._refresh_steps(action)
        self.step_table.selectRow(target_row)
        self.actions_changed.emit()

    def _drag_reorder(self, source_row: int, target_row: int) -> None:
        # 保留兼容入口；界面已关闭拖动，顺序调整使用上移/下移按钮。
        action = self._current_action()
        if action is None or action.locked or not (0 <= source_row < len(action.steps) and 0 <= target_row < len(action.steps)):
            return
        action.steps.insert(target_row, action.steps.pop(source_row))
        self._refresh_steps(action)
        self.step_table.selectRow(target_row)
        self.actions_changed.emit()
