from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class ActionKind(StrEnum):
    KEY_TAP = "key_tap"
    KEY_COMBO = "key_combo"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_CLICK = "mouse_click"
    MOUSE_BUTTON_DOWN = "mouse_button_down"
    MOUSE_BUTTON_UP = "mouse_button_up"
    MOVE_PIXEL = "move_pixel"
    MOVE_NORMALIZED = "move_normalized"
    MOVE_RELATIVE = "move_relative"
    WHEEL = "wheel"
    WAIT = "wait"
    RAW = "raw"


STEP_LABELS: dict[str, str] = {
    ActionKind.KEY_TAP: "单击按键（key_tap）",
    ActionKind.KEY_COMBO: "组合键（key_combo）",
    ActionKind.KEY_DOWN: "按住按键（key_down）",
    ActionKind.KEY_UP: "松开按键（key_up）",
    ActionKind.MOUSE_CLICK: "鼠标单击（mouse_click）",
    ActionKind.MOUSE_BUTTON_DOWN: "按住鼠标键（mouse_button_down）",
    ActionKind.MOUSE_BUTTON_UP: "松开鼠标键（mouse_button_up）",
    ActionKind.MOVE_PIXEL: "移动到像素坐标（move_pixel）",
    ActionKind.MOVE_NORMALIZED: "移动到屏幕比例位置（move_normalized）",
    ActionKind.MOVE_RELATIVE: "相对移动鼠标（move_relative）",
    ActionKind.WHEEL: "滚动滚轮（wheel）",
    ActionKind.WAIT: "单独等待（wait）",
    ActionKind.RAW: "高级原始命令（raw）",
}


class FlowMode(StrEnum):
    AB = "ab"
    CUSTOM = "custom"


class CustomStepKind(StrEnum):
    ACTION_REF = "action_ref"
    ACTION_DURATION = "action_duration"
    DIRECT_STEP = "direct_step"
    WAIT = "wait"


CUSTOM_STEP_LABELS: dict[str, str] = {
    CustomStepKind.ACTION_REF: "执行已保存操作",
    CustomStepKind.ACTION_DURATION: "持续执行操作",
    CustomStepKind.DIRECT_STEP: "直接输入步骤",
    CustomStepKind.WAIT: "等待",
}


@dataclass
class ActionStep:
    kind: str
    value: str = ""
    delay_after_ms: int = 0
    random_wait_min_ms: int = 0
    random_wait_max_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionStep":
        try:
            delay_after_ms = max(0, min(3_600_000, int(data.get("delay_after_ms", 0))))
        except (TypeError, ValueError):
            delay_after_ms = 0
        try:
            random_wait_min_ms = max(0, min(3_600_000, int(data.get("random_wait_min_ms", 0))))
            random_wait_max_ms = max(0, min(3_600_000, int(data.get("random_wait_max_ms", 0))))
        except (TypeError, ValueError):
            random_wait_min_ms = random_wait_max_ms = 0
        if random_wait_min_ms > random_wait_max_ms:
            random_wait_min_ms, random_wait_max_ms = random_wait_max_ms, random_wait_min_ms
        return cls(kind=str(data.get("kind", ActionKind.KEY_TAP)), value=str(data.get("value", "")), delay_after_ms=delay_after_ms, random_wait_min_ms=random_wait_min_ms, random_wait_max_ms=random_wait_max_ms)


@dataclass
class ActionDefinition:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新操作"
    hotkey: str = ""
    steps: list[ActionStep] = field(default_factory=list)
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionDefinition":
        return cls(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name", "新操作")),
            hotkey=str(data.get("hotkey", "")),
            steps=[ActionStep.from_dict(item) for item in data.get("steps", [])],
            locked=bool(data.get("locked", False)),
        )


@dataclass
class CustomFlowStep:
    kind: str = CustomStepKind.ACTION_REF
    action_id: str = ""
    direct_step: ActionStep | None = None
    repeat_count: int = 1
    duration_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CustomFlowStep":
        # 兼容上一版的 action / wait 自定义流程步骤。
        raw_kind = str(data.get("kind", CustomStepKind.ACTION_REF))
        if raw_kind == "action":
            raw_kind = CustomStepKind.ACTION_REF
        if raw_kind == "wait":
            raw_kind = CustomStepKind.WAIT
        raw_direct = data.get("direct_step")
        return cls(
            kind=raw_kind,
            action_id=str(data.get("action_id", "")),
            direct_step=ActionStep.from_dict(raw_direct) if isinstance(raw_direct, dict) else None,
            repeat_count=max(1, int(data.get("repeat_count", 1))),
            duration_ms=max(0, min(86_400_000, int(data.get("duration_ms", 0)))),
        )


@dataclass
class FlowStep:
    """自动化流程的唯一步骤模型；同层按列表顺序执行，children 可继续嵌套。"""
    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    kind: str = "group"  # group / action / direct / empty；旧 kind 仍可读取迁移
    enabled: bool = True
    action_id: str = ""
    direct_step: ActionStep | None = None
    repeat_mode: str = "once"  # once / count / duration / forever
    repeat_count: int = 1
    limit_ms: int = 0
    limit_policy: str = "finish_current"  # finish_current / stop_at_boundary
    random_wait_min_ms: int = 0
    random_wait_max_ms: int = 0
    group_mode: str = "sequential"  # sequential / scheduled
    trigger_type: str = "immediate"  # immediate / time / step_complete
    execution_mode: str = "sequence"  # 兼容旧 timed_insert；新逻辑由 trigger_type 表达
    trigger_after_ms: int = 0
    trigger_step_id: str = ""
    pause_target_step_ids: list[str] = field(default_factory=list)
    pause_others: bool = True  # 兼容旧配置
    resume_paused: bool = True
    children: list["FlowStep"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FlowStep":
        raw_step = data.get("direct_step")
        raw_kind = str(data.get("kind", "group"))
        kind_map = {"sequence": "group", "action_ref": "action", "action_duration": "action", "direct_step": "action", "direct": "action", "wait": "group", "vision": "empty", "fishing": "empty"}
        raw_kind = kind_map.get(raw_kind, raw_kind)
        repeat_mode = str(data.get("repeat_mode", "once"))
        if repeat_mode not in {"once", "count", "duration", "forever"}:
            repeat_mode = "once"
        # 兼容上一版 start_trigger / pause_target_step_id 字段。
        execution_mode = "timed_insert" if str(data.get("execution_mode", data.get("start_trigger", "sequence"))) in {"timed_insert", "after_parent_start"} else "sequence"
        return cls(
            id=str(data.get("id") or uuid4()), title=str(data.get("title", "")), kind=raw_kind,
            enabled=bool(data.get("enabled", True)), action_id=str(data.get("action_id", "")),
            direct_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None,
            repeat_mode=repeat_mode, repeat_count=max(1, int(data.get("repeat_count", 1))),
            limit_ms=max(0, int(data.get("limit_ms", data.get("duration_ms", 0)))),
            limit_policy="stop_at_boundary" if str(data.get("limit_policy")) == "stop_at_boundary" else "finish_current",
            random_wait_min_ms=max(0, int(data.get("random_wait_min_ms", 0))), random_wait_max_ms=max(0, int(data.get("random_wait_max_ms", 0))),
            group_mode="scheduled" if str(data.get("group_mode")) == "scheduled" else "sequential",
            trigger_type=str(data.get("trigger_type", "time" if execution_mode == "timed_insert" else "immediate")) if str(data.get("trigger_type", "time" if execution_mode == "timed_insert" else "immediate")) in {"immediate", "time", "step_complete"} else "immediate",
            execution_mode=execution_mode, trigger_after_ms=max(0, int(data.get("trigger_after_ms", 0))),
            trigger_step_id=str(data.get("trigger_step_id", "")),
            pause_target_step_ids=[str(item) for item in data.get("pause_target_step_ids", []) if item],
            pause_others=bool(data.get("pause_others", bool(data.get("pause_target_step_id", True)))),
            resume_paused=bool(data.get("resume_paused", True)),
            children=[cls.from_dict(item) for item in data.get("children", []) if isinstance(item, dict)],
        )


@dataclass
class LinearTask:
    """新自定义流程的线性任务；列表顺序就是执行顺序。"""
    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    kind: str = "action"
    enabled: bool = True
    action_id: str = ""
    direct_step: ActionStep | None = None
    repeat_count: int = 1
    duration_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LinearTask":
        raw_step = data.get("direct_step")
        return cls(id=str(data.get("id") or uuid4()), title=str(data.get("title", "")), kind=str(data.get("kind", "action")), enabled=bool(data.get("enabled", True)), action_id=str(data.get("action_id", "")), direct_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None, repeat_count=max(1, int(data.get("repeat_count", 1))), duration_ms=max(0, min(86_400_000, int(data.get("duration_ms", 0)))) )


@dataclass
class FlowBlock:
    id: str = field(default_factory=lambda: str(uuid4()))
    kind: str = "action"
    title: str = ""
    action_id: str = ""
    direct_step: ActionStep | None = None
    repeat_count: int = 1
    duration_ms: int = 0
    loop_mode: str = "count"
    children: list["FlowBlock"] = field(default_factory=list)
    enabled: bool = True
    canvas_x: float | None = None
    canvas_y: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FlowBlock":
        raw_direct = data.get("direct_step")

        def canvas_coordinate(key: str) -> float | None:
            try:
                value = float(data[key])
            except (KeyError, TypeError, ValueError):
                return None
            return max(-10_000.0, min(10_000.0, value))

        return cls(
            id=str(data.get("id") or uuid4()),
            kind=str(data.get("kind", "action")),
            title=str(data.get("title", "")),
            action_id=str(data.get("action_id", "")),
            direct_step=ActionStep.from_dict(raw_direct) if isinstance(raw_direct, dict) else None,
            repeat_count=max(1, int(data.get("repeat_count", 1))),
            duration_ms=max(0, min(86_400_000, int(data.get("duration_ms", 0)))),
            loop_mode=str(data.get("loop_mode")) if str(data.get("loop_mode")) in {"count", "duration", "forever"} else "count",
            children=[cls.from_dict(item) for item in data.get("children", []) if isinstance(item, dict)],
            enabled=bool(data.get("enabled", True)),
            canvas_x=canvas_coordinate("canvas_x"),
            canvas_y=canvas_coordinate("canvas_y"),
        )

    @classmethod
    def from_step(cls, step: CustomFlowStep) -> "FlowBlock":
        kind_map = {
            CustomStepKind.ACTION_REF: "action",
            CustomStepKind.ACTION_DURATION: "action_duration",
            CustomStepKind.DIRECT_STEP: "direct",
            CustomStepKind.WAIT: "wait",
        }
        return cls(kind=kind_map.get(step.kind, "action"), action_id=step.action_id, direct_step=step.direct_step, repeat_count=step.repeat_count, duration_ms=step.duration_ms)


def _legacy_action_targets(nodes: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for node in nodes:
        if str(node.get("kind")) == "action" and node.get("target_id"):
            targets.append(str(node["target_id"]))
        children = node.get("children", [])
        if isinstance(children, list):
            targets.extend(_legacy_action_targets(children))
    return targets


def _flow_step_from_legacy_task(data: dict[str, Any]) -> FlowStep:
    """将旧线性任务转换为新树形流程的叶子节点。"""
    kind = str(data.get("kind", "action"))
    kind = {"action_ref": "action", "direct_step": "direct"}.get(kind, kind)
    return FlowStep(
        id=str(data.get("id") or uuid4()), title=str(data.get("title", "")), kind=kind,
        enabled=bool(data.get("enabled", True)), action_id=str(data.get("action_id", "")),
        direct_step=ActionStep.from_dict(data["direct_step"]) if isinstance(data.get("direct_step"), dict) else None,
        repeat_mode="count" if int(data.get("repeat_count", 1)) > 1 else "once",
        repeat_count=max(1, int(data.get("repeat_count", 1))), limit_ms=max(0, int(data.get("duration_ms", data.get("limit_ms", 0)))),
    )


def _root_step_from_legacy(data: dict[str, Any]) -> FlowStep | None:
    """将可解释的旧线性数据迁移为根容器；复杂旧画布继续保留原数据。"""
    raw_tasks = data.get("tasks", [])
    if isinstance(raw_tasks, list) and raw_tasks:
        return FlowStep(title="整个流程", kind="sequence", children=[_flow_step_from_legacy_task(item) for item in raw_tasks if isinstance(item, dict)])
    raw_steps = data.get("custom_steps", [])
    if isinstance(raw_steps, list) and raw_steps:
        return FlowStep(title="整个流程", kind="sequence", children=[_flow_step_from_legacy_task(item) for item in raw_steps if isinstance(item, dict)])
    raw_blocks = data.get("blocks", [])
    if isinstance(raw_blocks, list) and raw_blocks and all(isinstance(item, dict) and not item.get("children") and item.get("kind") not in {"group", "loop"} for item in raw_blocks):
        return FlowStep(title="整个流程", kind="sequence", children=[_flow_step_from_legacy_task(item) for item in raw_blocks])
    return None


@dataclass
class WorkflowDefinition:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新流程"
    hotkey: str = ""
    mode: str = FlowMode.AB
    primary_action_id: str = ""
    secondary_action_id: str = ""
    secondary_trigger_ms: int = 0
    custom_steps: list[CustomFlowStep] = field(default_factory=list)
    tasks: list[LinearTask] = field(default_factory=list)
    root_step: FlowStep | None = None
    blocks: list[FlowBlock] = field(default_factory=list)
    active_duration_ms: int = 600_000
    rest_duration_ms: int = 300_000
    repeats: int = 0
    finish_current_action: bool = True
    custom_scheduler_enabled: bool = False
    scheduler_primary_block_id: str = ""
    scheduler_secondary_block_id: str = ""
    scheduler_trigger_ms: int = 0
    scheduler_resume_primary: bool = True
    requires_reconfiguration: bool = False
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDefinition":
        if "mode" in data or "active_duration_ms" in data or "secondary_trigger_ms" in data:
            return cls(
                id=str(data.get("id") or uuid4()),
                name=str(data.get("name", "新流程")),
                hotkey=str(data.get("hotkey", "")),
                mode=str(data.get("mode", FlowMode.AB)),
                primary_action_id=str(data.get("primary_action_id", "")),
                secondary_action_id=str(data.get("secondary_action_id", "")),
                secondary_trigger_ms=max(0, int(data.get("secondary_trigger_ms", 0))),
                custom_steps=[CustomFlowStep.from_dict(item) for item in data.get("custom_steps", [])],
                tasks=[LinearTask.from_dict(item) for item in data.get("tasks", []) if isinstance(item, dict)],
                root_step=FlowStep.from_dict(data["root_step"]) if isinstance(data.get("root_step"), dict) else _root_step_from_legacy(data),
                blocks=[FlowBlock.from_dict(item) for item in data.get("blocks", []) if isinstance(item, dict)],
                active_duration_ms=max(0, int(data.get("active_duration_ms", 600_000))),
                rest_duration_ms=max(0, int(data.get("rest_duration_ms", 300_000))),
                repeats=max(0, int(data.get("repeats", 0))),
                finish_current_action=bool(data.get("finish_current_action", True)),
                custom_scheduler_enabled=bool(data.get("custom_scheduler_enabled", False)),
                scheduler_primary_block_id=str(data.get("scheduler_primary_block_id", "")),
                scheduler_secondary_block_id=str(data.get("scheduler_secondary_block_id", "")),
                scheduler_trigger_ms=max(0, int(data.get("scheduler_trigger_ms", 0))),
                scheduler_resume_primary=bool(data.get("scheduler_resume_primary", True)),
                requires_reconfiguration=bool(data.get("requires_reconfiguration", False)),
                locked=bool(data.get("locked", False)),
            )
        if "primary_action_id" in data or "secondary_action_id" in data:
            return cls(
                id=str(data.get("id") or uuid4()),
                name=str(data.get("name", "新流程")),
                mode=FlowMode.AB,
                primary_action_id=str(data.get("primary_action_id", "")),
                secondary_action_id=str(data.get("secondary_action_id", "")),
                secondary_trigger_ms=max(0, int(data.get("secondary_trigger_seconds", 0))) * 1_000,
                active_duration_ms=max(1, int(round(float(data.get("active_minutes", 10.0)) * 60_000))),
                rest_duration_ms=max(0, int(round(float(data.get("rest_minutes", data.get("pause_minutes", 5.0))) * 60_000))),
                repeats=max(0, int(data.get("repeats", 0))),
                finish_current_action=bool(data.get("finish_current_action", True)),
                requires_reconfiguration=bool(data.get("requires_reconfiguration", False)),
                locked=bool(data.get("locked", False)),
            )
        targets = [str(item) for item in data.get("action_ids", [])]
        raw_nodes = data.get("nodes", [])
        if isinstance(raw_nodes, list):
            targets.extend(_legacy_action_targets(raw_nodes))
        unique_targets = list(dict.fromkeys(targets))
        return cls(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name", "新流程")),
            primary_action_id=unique_targets[0] if unique_targets else "",
            secondary_action_id=unique_targets[1] if len(unique_targets) > 1 else "",
            active_duration_ms=max(1, int(round(float(data.get("active_minutes", 10.0)) * 60_000))),
            rest_duration_ms=max(0, int(round(float(data.get("pause_minutes", 5.0)) * 60_000))),
            repeats=max(0, int(data.get("repeats", 0))),
            requires_reconfiguration=bool(raw_nodes and len(unique_targets) > 2),
        )


@dataclass
class DeviceSettings:
    port: str = "COM5"
    baud_rate: int = 115200
    screen_width: int = 2560
    screen_height: int = 1440
    key_press_delay: int = 100
    key_release_delay: int = 10
    combo_hold_delay: int = 50
    mouse_press_delay: int = 30
    mouse_click_delay: int = 50
    mouse_move_delay: int = 50
    max_jump: int = 80

    @classmethod
    def defaults(cls, port: str = "COM5", baud_rate: int = 115200) -> "DeviceSettings":
        return cls(port=port, baud_rate=baud_rate)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceSettings":
        defaults = asdict(cls())
        defaults.update({key: value for key, value in data.items() if key in defaults})
        return cls(**defaults)


@dataclass
class ControlSettings:
    start_hotkey: str = ""
    stop_hotkey: str = ""
    side_buttons_enabled: bool = True
    start_side_button: str = "XBUTTON2"
    stop_side_button: str = "XBUTTON1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlSettings":
        defaults = asdict(cls())
        defaults.update({key: value for key, value in data.items() if key in defaults})
        return cls(**defaults)


@dataclass
class WindowLayoutSettings:
    width_ratio: float = 0.9
    height_ratio: float = 0.9
    navigation_collapsed: bool = False
    last_window_state: str = "normal"
    theme: str = "light"  # light / dark_blue / warm_gray

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WindowLayoutSettings":
        if not isinstance(data, dict):
            data = {}
        try:
            width_ratio = float(data.get("width_ratio", 0.9))
        except (TypeError, ValueError):
            width_ratio = 0.9
        try:
            height_ratio = float(data.get("height_ratio", 0.9))
        except (TypeError, ValueError):
            height_ratio = 0.9
        theme = str(data.get("theme", "light"))
        if theme == "warm_gray":
            theme = "dark_blue"
        if theme not in {"light", "dark_blue"}:
            theme = "light"
        return cls(
            width_ratio=max(0.35, min(1.0, width_ratio)),
            height_ratio=max(0.35, min(1.0, height_ratio)),
            navigation_collapsed=bool(data.get("navigation_collapsed", False)),
            last_window_state=str(data.get("last_window_state", "normal")) if str(data.get("last_window_state", "normal")) in {"normal", "minimized", "maximized"} else "normal",
            theme=theme,
        )


@dataclass
class AppState:
    device: DeviceSettings = field(default_factory=DeviceSettings)
    controls: ControlSettings = field(default_factory=ControlSettings)
    window_layout: WindowLayoutSettings = field(default_factory=WindowLayoutSettings)
    actions: list[ActionDefinition] = field(default_factory=list)
    workflows: list[WorkflowDefinition] = field(default_factory=list)
    active_workflow_id: str = ""
    active_target_kind: str = "workflow"
    active_target_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": asdict(self.device),
            "controls": asdict(self.controls),
            "window_layout": asdict(self.window_layout),
            "actions": [asdict(action) for action in self.actions],
            "workflows": [asdict(workflow) for workflow in self.workflows],
            "active_workflow_id": self.active_workflow_id,
            "active_target_kind": self.active_target_kind,
            "active_target_id": self.active_target_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppState":
        active_workflow_id = str(data.get("active_workflow_id", ""))
        active_target_id = str(data.get("active_target_id", "") or active_workflow_id)
        active_target_kind = str(data.get("active_target_kind", "workflow" if active_target_id else ""))
        return cls(
            device=DeviceSettings.from_dict(data.get("device", {})),
            controls=ControlSettings.from_dict(data.get("controls", {})),
            window_layout=WindowLayoutSettings.from_dict(data.get("window_layout", {})),
            actions=[ActionDefinition.from_dict(item) for item in data.get("actions", [])],
            workflows=[WorkflowDefinition.from_dict(item) for item in data.get("workflows", [])],
            active_workflow_id=active_workflow_id,
            active_target_kind=active_target_kind,
            active_target_id=active_target_id,
        )
