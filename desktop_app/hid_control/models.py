from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
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
    FISHING = "fishing"


CUSTOM_STEP_LABELS: dict[str, str] = {
    CustomStepKind.ACTION_REF: "执行已保存操作",
    CustomStepKind.ACTION_DURATION: "持续执行操作",
    CustomStepKind.DIRECT_STEP: "直接输入步骤",
    CustomStepKind.WAIT: "等待",
    CustomStepKind.FISHING: "执行钓鱼预设",
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
    fishing_preset_id: str = ""
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
            fishing_preset_id=str(data.get("fishing_preset_id", "")),
            direct_step=ActionStep.from_dict(raw_direct) if isinstance(raw_direct, dict) else None,
            repeat_count=max(1, int(data.get("repeat_count", 1))),
            duration_ms=max(0, min(86_400_000, int(data.get("duration_ms", 0)))),
        )


@dataclass
class FlowStep:
    """自动化流程的唯一步骤模型；同层按列表顺序执行，children 可继续嵌套。"""
    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    kind: str = "group"  # group / action / vision / fishing；旧 kind 仍可读取迁移
    enabled: bool = True
    action_id: str = ""
    vision_preset_id: str = ""
    fishing_preset_id: str = ""
    direct_step: ActionStep | None = None
    repeat_mode: str = "once"  # once / count / duration / forever
    repeat_count: int = 1
    limit_ms: int = 0
    limit_policy: str = "finish_current"  # finish_current / stop_at_boundary
    random_wait_min_ms: int = 0
    random_wait_max_ms: int = 0
    group_mode: str = "sequential"  # sequential / scheduled
    trigger_type: str = "immediate"  # immediate / time / vision / step_complete
    execution_mode: str = "sequence"  # 兼容旧 timed_insert；新逻辑由 trigger_type 表达
    trigger_after_ms: int = 0
    trigger_vision_preset_id: str = ""
    trigger_step_id: str = ""
    pause_target_step_ids: list[str] = field(default_factory=list)
    pause_others: bool = True  # 兼容旧配置
    resume_paused: bool = True
    children: list["FlowStep"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FlowStep":
        raw_step = data.get("direct_step")
        raw_kind = str(data.get("kind", "group"))
        kind_map = {"sequence": "group", "action_ref": "action", "action_duration": "action", "direct_step": "action", "direct": "action", "wait": "group"}
        raw_kind = kind_map.get(raw_kind, raw_kind)
        repeat_mode = str(data.get("repeat_mode", "once"))
        if repeat_mode not in {"once", "count", "duration", "forever"}:
            repeat_mode = "once"
        # 兼容上一版 start_trigger / pause_target_step_id 字段。
        execution_mode = "timed_insert" if str(data.get("execution_mode", data.get("start_trigger", "sequence"))) in {"timed_insert", "after_parent_start"} else "sequence"
        return cls(
            id=str(data.get("id") or uuid4()), title=str(data.get("title", "")), kind=raw_kind,
            enabled=bool(data.get("enabled", True)), action_id=str(data.get("action_id", "")),
            vision_preset_id=str(data.get("vision_preset_id", "")), fishing_preset_id=str(data.get("fishing_preset_id", "")),
            direct_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None,
            repeat_mode=repeat_mode, repeat_count=max(1, int(data.get("repeat_count", 1))),
            limit_ms=max(0, int(data.get("limit_ms", data.get("duration_ms", 0)))),
            limit_policy="stop_at_boundary" if str(data.get("limit_policy")) == "stop_at_boundary" else "finish_current",
            random_wait_min_ms=max(0, int(data.get("random_wait_min_ms", 0))), random_wait_max_ms=max(0, int(data.get("random_wait_max_ms", 0))),
            group_mode="scheduled" if str(data.get("group_mode")) == "scheduled" else "sequential",
            trigger_type=str(data.get("trigger_type", "time" if execution_mode == "timed_insert" else "immediate")) if str(data.get("trigger_type", "time" if execution_mode == "timed_insert" else "immediate")) in {"immediate", "time", "vision", "step_complete"} else "immediate",
            execution_mode=execution_mode, trigger_after_ms=max(0, int(data.get("trigger_after_ms", 0))),
            trigger_vision_preset_id=str(data.get("trigger_vision_preset_id", "")), trigger_step_id=str(data.get("trigger_step_id", "")),
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
    fishing_preset_id: str = ""
    direct_step: ActionStep | None = None
    repeat_count: int = 1
    duration_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LinearTask":
        raw_step = data.get("direct_step")
        return cls(id=str(data.get("id") or uuid4()), title=str(data.get("title", "")), kind=str(data.get("kind", "action")), enabled=bool(data.get("enabled", True)), action_id=str(data.get("action_id", "")), fishing_preset_id=str(data.get("fishing_preset_id", "")), direct_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None, repeat_count=max(1, int(data.get("repeat_count", 1))), duration_ms=max(0, min(86_400_000, int(data.get("duration_ms", 0)))) )


@dataclass
class FlowBlock:
    id: str = field(default_factory=lambda: str(uuid4()))
    kind: str = "action"
    title: str = ""
    action_id: str = ""
    fishing_preset_id: str = ""
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
            fishing_preset_id=str(data.get("fishing_preset_id", "")),
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
            CustomStepKind.FISHING: "fishing",
        }
        return cls(kind=kind_map.get(step.kind, "action"), action_id=step.action_id, fishing_preset_id=step.fishing_preset_id, direct_step=step.direct_step, repeat_count=step.repeat_count, duration_ms=step.duration_ms)


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
        fishing_preset_id=str(data.get("fishing_preset_id", "")),
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
    secondary_vision_preset_id: str = ""  # B 到定时点后可选的识图确认
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
                secondary_vision_preset_id=str(data.get("secondary_vision_preset_id", "")),
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
class VisionRule:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新识别规则"
    enabled: bool = True
    template_path: str = ""
    threshold: float = 0.85
    scan_interval_ms: int = 1_000
    cooldown_ms: int = 1_000
    trigger_mode: str = "once"  # once / repeat
    action_mode: str = "report"  # report / step / action_once
    action_step: ActionStep | None = None
    action_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionRule":
        raw_step = data.get("action_step")
        return cls(
            id=str(data.get("id") or uuid4()), name=str(data.get("name", "新识别规则")), enabled=bool(data.get("enabled", True)),
            template_path=str(data.get("template_path", "")), threshold=max(0.1, min(1.0, float(data.get("threshold", 0.85)))),
            scan_interval_ms=max(100, min(60_000, int(data.get("scan_interval_ms", 1_000)))), cooldown_ms=max(0, min(86_400_000, int(data.get("cooldown_ms", 1_000)))),
            trigger_mode="repeat" if str(data.get("trigger_mode")) == "repeat" else "once",
            action_mode=str(data.get("action_mode", "report")) if str(data.get("action_mode", "report")) in {"report", "step", "action_once"} else "report",
            action_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None, action_id=str(data.get("action_id", "")),
        )


@dataclass
class VisionSettings:
    # rules 仅用于读取上一版配置；新 UI 使用下面的单一识别任务字段。
    rules: list[VisionRule] = field(default_factory=list)
    source: str = "template"
    color_hex: str = "#00FF00"
    hue_tolerance: int = 12
    min_area: int = 20
    window_title: str = ""
    region_x: int = 0
    region_y: int = 0
    region_width: int = 0
    region_height: int = 0
    response_step: ActionStep | None = None
    target_material_id: str = ""
    region_material_id: str = ""
    template_path: str = ""
    threshold: float = 0.85
    scan_interval_ms: int = 1_000
    action_mode: str = "report"
    action_id: str = ""
    timeout_seconds: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionSettings":
        if not isinstance(data, dict):
            data = {}
        try:
            threshold = float(data.get("threshold", 0.85))
        except (TypeError, ValueError):
            threshold = 0.85
        try:
            scan_interval_ms = int(data.get("scan_interval_ms", 1_000))
        except (TypeError, ValueError):
            scan_interval_ms = 1_000
        try:
            timeout_seconds = int(data.get("timeout_seconds", 0))
        except (TypeError, ValueError):
            timeout_seconds = 0
        action_mode = str(data.get("action_mode", "report"))
        if action_mode not in {"report", "move", "click", "action_once"}:
            action_mode = "report"
        rules = [VisionRule.from_dict(item) for item in data.get("rules", []) if isinstance(item, dict)]
        legacy_path = str(data.get("template_path", ""))
        if not rules and legacy_path:
            legacy_mode = action_mode
            legacy_step = None
            if legacy_mode == "click":
                legacy_mode, legacy_step = "step", ActionStep(ActionKind.MOUSE_CLICK, "LEFT")
            rules.append(VisionRule(name="旧模板识别规则", template_path=legacy_path, threshold=max(0.1, min(1.0, threshold)), scan_interval_ms=max(100, min(60_000, scan_interval_ms)), action_mode="action_once" if legacy_mode == "action_once" else ("step" if legacy_mode == "step" else "report"), action_step=legacy_step, action_id=str(data.get("action_id", ""))))
        raw_step = data.get("response_step")
        return cls(
            rules=[],
            source="color" if str(data.get("source")) == "color" else "template",
            color_hex=str(data.get("color_hex", "#00FF00")),
            hue_tolerance=max(1, min(90, int(data.get("hue_tolerance", 12)))),
            min_area=max(1, int(data.get("min_area", 20))),
            window_title=str(data.get("window_title", "")),
            region_x=max(0, int(data.get("region_x", 0))), region_y=max(0, int(data.get("region_y", 0))),
            region_width=max(0, int(data.get("region_width", 0))), region_height=max(0, int(data.get("region_height", 0))),
            response_step=ActionStep.from_dict(raw_step) if isinstance(raw_step, dict) else None,
            target_material_id=str(data.get("target_material_id", "")), region_material_id=str(data.get("region_material_id", "")),
            template_path=legacy_path,
            threshold=max(0.1, min(1.0, threshold)), 
            scan_interval_ms=max(100, min(60_000, scan_interval_ms)),
            action_mode=action_mode,
            action_id=str(data.get("action_id", "")),
            timeout_seconds=max(0, min(86_400, timeout_seconds)),
        )


@dataclass
class VisionPreset:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新识图预设"
    settings: VisionSettings = field(default_factory=VisionSettings)
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionPreset":
        return cls(
            id=str(data.get("id") or uuid4()), name=str(data.get("name", "新识图预设")),
            settings=VisionSettings.from_dict(data.get("settings", {})), locked=bool(data.get("locked", False)),
        )


@dataclass
class FishingSettings:
    mode: str = "ab_keys"
    hide_during_capture: bool = True
    capture_target: str = "a"
    a_source: str = "color"
    b_source: str = "color"
    color_a_hex: str = "#FFD000"
    color_b_hex: str = "#00A0FF"
    template_a_path: str = ""
    template_b_path: str = ""
    a_material_id: str = ""
    b_material_id: str = ""
    region_material_id: str = ""
    template_threshold: float = 0.85
    color_pick_hotkey: str = ""
    region_pick_hotkey: str = ""
    detection_hotkey: str = ""
    left_key: str = "A"
    right_key: str = "D"
    window_title: str = ""
    region_x: int = 0
    region_y: int = 0
    region_width: int = 0
    region_height: int = 0
    region_preview_path: str = ""
    hue_tolerance: int = 12
    min_area: int = 120
    b_min_area: int = 8
    input_mode: str = "tap"
    tap_interval_ms: int = 250
    scan_interval_ms: int = 100
    dead_zone: int = 12
    gain: float = 0.2
    max_step: int = 40

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FishingSettings":
        if not isinstance(data, dict):
            data = {}
        def integer(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                return max(minimum, min(maximum, int(data.get(key, default))))
            except (TypeError, ValueError):
                return default
        try:
            gain = float(data.get("gain", 0.2))
        except (TypeError, ValueError):
            gain = 0.2
        try:
            template_threshold = float(data.get("template_threshold", 0.85))
        except (TypeError, ValueError):
            template_threshold = 0.85
        def color(key: str, default: str) -> str:
            value = str(data.get(key, data.get("color_hex", default)))
            return value if len(value) == 7 and value.startswith("#") else default
        mode = str(data.get("mode", "ab_keys"))
        if mode not in {"ab_keys", "mouse"}:
            mode = "ab_keys"
        a_source = str(data.get("a_source", "color"))
        b_source = str(data.get("b_source", "color"))
        return cls(
            mode=mode,
            hide_during_capture=bool(data.get("hide_during_capture", True)),
            capture_target="b" if str(data.get("capture_target", "a")) == "b" else "a",
            a_source=a_source if a_source in {"color", "template"} else "color",
            b_source=b_source if b_source in {"color", "template"} else "color",
            color_a_hex=color("color_a_hex", "#FFD000"),
            color_b_hex=color("color_b_hex", "#00A0FF"),
            template_a_path=str(data.get("template_a_path", "")),
            template_b_path=str(data.get("template_b_path", "")),
            a_material_id=str(data.get("a_material_id", "")), b_material_id=str(data.get("b_material_id", "")), region_material_id=str(data.get("region_material_id", "")),
            template_threshold=max(0.1, min(1.0, template_threshold)),
            color_pick_hotkey=str(data.get("color_pick_hotkey", "")),
            region_pick_hotkey=str(data.get("region_pick_hotkey", "")),
            detection_hotkey=str(data.get("detection_hotkey", "")),
            left_key=str(data.get("left_key", "A")),
            right_key=str(data.get("right_key", "D")),
            window_title=str(data.get("window_title", "")),
            region_x=integer("region_x", 0, 0, 100_000),
            region_y=integer("region_y", 0, 0, 100_000),
            region_width=integer("region_width", 0, 0, 100_000),
            region_height=integer("region_height", 0, 0, 100_000),
            region_preview_path=str(data.get("region_preview_path", "")),
            hue_tolerance=integer("hue_tolerance", 12, 1, 90),
            min_area=integer("min_area", 120, 1, 1_000_000),
            b_min_area=integer("b_min_area", 8, 1, 1_000_000),
            input_mode=str(data.get("input_mode", "tap")) if str(data.get("input_mode", "tap")) in {"tap", "hold"} else "tap",
            tap_interval_ms=integer("tap_interval_ms", 250, 20, 10_000),
            scan_interval_ms=integer("scan_interval_ms", 100, 50, 10_000),
            dead_zone=integer("dead_zone", 12, 0, 500),
            gain=max(0.01, min(1.0, gain)),
            max_step=integer("max_step", 40, 1, 120),
        )


@dataclass
class FishingPreset:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新钓鱼预设"
    settings: FishingSettings = field(default_factory=FishingSettings)
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FishingPreset":
        return cls(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name", "新钓鱼预设")),
            settings=FishingSettings.from_dict(data.get("settings", {})),
            locked=bool(data.get("locked", False)),
        )


@dataclass
class MaterialMark:
    kind: str = "rect"
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""


@dataclass
class MaterialAsset:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新素材"
    kind: str = "template"  # color / template / region
    image_path: str = ""
    color_hex: str = ""
    window_title: str = ""
    region_x: int = 0
    region_y: int = 0
    region_width: int = 0
    region_height: int = 0
    marks: list[MaterialMark] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    note: str = ""
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaterialAsset":
        return cls(id=str(data.get("id") or uuid4()), name=str(data.get("name", "新素材")), kind=str(data.get("kind", "template")) if str(data.get("kind", "template")) in {"color", "template", "region"} else "template", image_path=str(data.get("image_path", "")), color_hex=str(data.get("color_hex", "")), window_title=str(data.get("window_title", "")), region_x=max(0, int(data.get("region_x", 0))), region_y=max(0, int(data.get("region_y", 0))), region_width=max(0, int(data.get("region_width", 0))), region_height=max(0, int(data.get("region_height", 0))), marks=[MaterialMark(**item) for item in data.get("marks", []) if isinstance(item, dict)], tags=[str(item) for item in data.get("tags", [])], note=str(data.get("note", "")), locked=bool(data.get("locked", False)))


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
class MaterialCaptureSettings:
    """素材库统一管理的采集上下文和全局快捷键。"""
    window_title: str = ""
    hide_during_capture: bool = True
    color_pick_hotkey: str = ""
    template_capture_hotkey: str = ""
    region_capture_hotkey: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaterialCaptureSettings":
        data = data if isinstance(data, dict) else {}
        return cls(
            window_title=str(data.get("window_title", "")), hide_during_capture=bool(data.get("hide_during_capture", True)),
            color_pick_hotkey=str(data.get("color_pick_hotkey", "")),
            template_capture_hotkey=str(data.get("template_capture_hotkey", "")),
            region_capture_hotkey=str(data.get("region_capture_hotkey", "")),
        )


@dataclass
class AppState:
    device: DeviceSettings = field(default_factory=DeviceSettings)
    controls: ControlSettings = field(default_factory=ControlSettings)
    window_layout: WindowLayoutSettings = field(default_factory=WindowLayoutSettings)
    material_capture: MaterialCaptureSettings = field(default_factory=MaterialCaptureSettings)
    vision: VisionSettings = field(default_factory=VisionSettings)
    vision_presets: list[VisionPreset] = field(default_factory=list)
    fishing: FishingSettings = field(default_factory=FishingSettings)
    fishing_presets: list[FishingPreset] = field(default_factory=list)
    materials: list[MaterialAsset] = field(default_factory=list)
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
            "material_capture": asdict(self.material_capture),
            "vision": asdict(self.vision),
            "vision_presets": [asdict(preset) for preset in self.vision_presets],
            "fishing": asdict(self.fishing),
            "fishing_presets": [asdict(preset) for preset in self.fishing_presets],
            "materials": [asdict(material) for material in self.materials],
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
        material_capture_raw = data.get("material_capture", {})
        # 第一次升级时迁移旧钓鱼采集快捷键，避免用户重新设置。
        if not material_capture_raw and isinstance(data.get("fishing"), dict):
            legacy_fishing = data["fishing"]
            material_capture_raw = {
                "window_title": legacy_fishing.get("window_title", ""),
                "hide_during_capture": legacy_fishing.get("hide_during_capture", True),
                "color_pick_hotkey": legacy_fishing.get("color_pick_hotkey", ""),
                "region_capture_hotkey": legacy_fishing.get("region_pick_hotkey", ""),
            }
        state = cls(
            device=DeviceSettings.from_dict(data.get("device", {})),
            controls=ControlSettings.from_dict(data.get("controls", {})),
            window_layout=WindowLayoutSettings.from_dict(data.get("window_layout", {})),
            material_capture=MaterialCaptureSettings.from_dict(material_capture_raw),
            vision=VisionSettings.from_dict(data.get("vision", {})),
            vision_presets=[VisionPreset.from_dict(item) for item in data.get("vision_presets", []) if isinstance(item, dict)],
            fishing=FishingSettings.from_dict(data.get("fishing", {})),
            fishing_presets=[FishingPreset.from_dict(item) for item in data.get("fishing_presets", []) if isinstance(item, dict)],
            materials=[MaterialAsset.from_dict(item) for item in data.get("materials", []) if isinstance(item, dict)],
            actions=[ActionDefinition.from_dict(item) for item in data.get("actions", [])],
            workflows=[WorkflowDefinition.from_dict(item) for item in data.get("workflows", [])],
            active_workflow_id=active_workflow_id,
            active_target_kind=active_target_kind,
            active_target_id=active_target_id,
        )

        def ensure_material(kind: str, *, color_hex: str = "", image_path: str = "", window_title: str = "", region_x: int = 0, region_y: int = 0, region_width: int = 0, region_height: int = 0) -> str:
            for material in state.materials:
                if kind == "color" and material.kind == kind and material.color_hex == color_hex:
                    return material.id
                if kind == "template" and material.kind == kind and material.image_path == image_path:
                    return material.id
                if kind == "region" and material.kind == kind and (material.window_title, material.region_x, material.region_y, material.region_width, material.region_height) == (window_title, region_x, region_y, region_width, region_height):
                    return material.id
            label = color_hex if kind == "color" else Path(image_path).stem if image_path else "区域"
            material = MaterialAsset(name=f"迁移的{'颜色' if kind == 'color' else '模板' if kind == 'template' else '区域'} {label}", kind=kind, color_hex=color_hex, image_path=image_path, window_title=window_title, region_x=region_x, region_y=region_y, region_width=region_width, region_height=region_height)
            state.materials.append(material)
            return material.id

        def migrate_vision(settings: VisionSettings) -> None:
            if not settings.target_material_id:
                if settings.source == "color":
                    settings.target_material_id = ensure_material("color", color_hex=settings.color_hex)
                elif settings.template_path:
                    settings.target_material_id = ensure_material("template", image_path=settings.template_path, window_title=settings.window_title)
            if not settings.region_material_id and settings.region_width and settings.region_height:
                settings.region_material_id = ensure_material("region", window_title=settings.window_title, region_x=settings.region_x, region_y=settings.region_y, region_width=settings.region_width, region_height=settings.region_height)

        def migrate_fishing(settings: FishingSettings) -> None:
            if not settings.a_material_id:
                if settings.a_source == "color": settings.a_material_id = ensure_material("color", color_hex=settings.color_a_hex)
                elif settings.template_a_path: settings.a_material_id = ensure_material("template", image_path=settings.template_a_path, window_title=settings.window_title)
            if not settings.b_material_id:
                if settings.b_source == "color": settings.b_material_id = ensure_material("color", color_hex=settings.color_b_hex)
                elif settings.template_b_path: settings.b_material_id = ensure_material("template", image_path=settings.template_b_path, window_title=settings.window_title)
            if not settings.region_material_id and settings.region_width and settings.region_height:
                settings.region_material_id = ensure_material("region", image_path=settings.region_preview_path, window_title=settings.window_title, region_x=settings.region_x, region_y=settings.region_y, region_width=settings.region_width, region_height=settings.region_height)

        has_legacy_assets = (
            bool(state.materials)
            or bool(state.vision_presets)
            or bool(state.fishing_presets)
            or bool(state.vision.template_path or (state.vision.region_width and state.vision.region_height))
            or any(preset.settings.template_path or (preset.settings.region_width and preset.settings.region_height) for preset in state.vision_presets)
            or bool(state.fishing.template_a_path or state.fishing.template_b_path or (state.fishing.region_width and state.fishing.region_height))
            or any(preset.settings.template_a_path or preset.settings.template_b_path or (preset.settings.region_width and preset.settings.region_height) for preset in state.fishing_presets)
        )
        if has_legacy_assets:
            migrate_vision(state.vision)
            for preset in state.vision_presets:
                migrate_vision(preset.settings)
            migrate_fishing(state.fishing)
            for preset in state.fishing_presets:
                migrate_fishing(preset.settings)
        if not state.vision_presets and (state.vision.template_path or state.vision.target_material_id):
            state.vision_presets.append(VisionPreset(name="当前识图设置", settings=VisionSettings.from_dict(asdict(state.vision))))
        return state
