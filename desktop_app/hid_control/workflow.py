from __future__ import annotations

import threading
import time
from copy import deepcopy
import random

from PySide6.QtCore import QObject, Signal

from .models import ActionDefinition, ActionKind, CustomFlowStep, CustomStepKind, FlowBlock, FlowMode, FlowStep, LinearTask, WorkflowDefinition
from .protocol import ProtocolError, command_for_step, wait_milliseconds
from .hid_service import HidService
from .ui.duration_input import format_duration


class WorkflowRunner(QObject):
    status_changed = Signal(str)
    log_message = Signal(str)
    finished = Signal()

    def __init__(self, hid_service: HidService) -> None:
        super().__init__()
        self._hid_service = hid_service
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._active_target = ""

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def active_target(self) -> str:
        return self._active_target

    def start(self, workflow: WorkflowDefinition, actions: list[ActionDefinition], target_id: str | None = None) -> bool:
        with self._state_lock:
            if self.is_running:
                self.log_message.emit("流程已在运行")
                return False
            if workflow.requires_reconfiguration:
                self.log_message.emit("该旧流程需要重新保存后才能运行")
                return False
            if workflow.mode == FlowMode.AB and not workflow.primary_action_id:
                self.log_message.emit("请先为 A/B 流程选择 A：主要循环操作")
                return False
            if workflow.mode == FlowMode.CUSTOM and not (workflow.root_step and workflow.root_step.children) and not (workflow.tasks or workflow.blocks or workflow.custom_steps):
                self.log_message.emit("请至少为自动化流程添加一个流程步骤")
                return False
            if not self._hid_service.is_connected:
                self.log_message.emit("设备未连接，无法启动流程")
                return False
            self._stop_event.clear()
            self._active_target = target_id or f"workflow:{workflow.id}"
            self._thread = threading.Thread(target=self._run, args=(workflow, actions), name="workflow-runner", daemon=True)
            self._thread.start()
        return True

    def start_action_loop(self, action: ActionDefinition, target_id: str | None = None) -> bool:
        with self._state_lock:
            if not action.steps:
                self.log_message.emit("操作没有步骤，无法启动循环")
                return False
            if self.is_running:
                self.log_message.emit("已有任务正在运行")
                return False
            if not self._hid_service.is_connected:
                self.log_message.emit("设备未连接，无法启动操作")
                return False
            self._stop_event.clear()
            self._active_target = target_id or f"action:{action.id}"
            self._thread = threading.Thread(target=self._run_action_loop, args=(action,), name="action-loop-runner", daemon=True)
            self._thread.start()
        return True

    def start_action_once(self, action: ActionDefinition, target_id: str | None = None) -> bool:
        with self._state_lock:
            if not action.steps:
                self.log_message.emit("操作没有步骤，无法执行")
                return False
            if self.is_running:
                self.log_message.emit("已有任务正在运行")
                return False
            if not self._hid_service.is_connected:
                self.log_message.emit("设备未连接，无法执行操作")
                return False
            self._stop_event.clear()
            self._active_target = target_id or f"action-once:{action.id}"
            self._thread = threading.Thread(target=self._run_action_once, args=(action,), name="action-once-runner", daemon=True)
            self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._hid_service.send_stop()
        self.status_changed.emit("正在停止…")

    def _run_action_once(self, action: ActionDefinition) -> None:
        self.status_changed.emit("运行中")
        try:
            self.log_message.emit(f"执行一次操作：{action.name}")
            self._run_action(action, None, finish_current=True)
        except ProtocolError as error:
            self.log_message.emit(f"操作参数错误：{error}")
        except RuntimeError as error:
            self.log_message.emit(f"操作执行错误：{error}")
        except Exception as error:
            self.log_message.emit(f"操作异常：{error}")
        finally:
            self._hid_service.send_stop()
            self._active_target = ""
            self.status_changed.emit("已停止")
            self.finished.emit()

    def _run_action_loop(self, action: ActionDefinition) -> None:
        self.status_changed.emit("运行中")
        try:
            self.log_message.emit(f"开始循环操作：{action.name}")
            while not self._stop_event.is_set():
                self._run_action(action, None, finish_current=True)
        except ProtocolError as error:
            self.log_message.emit(f"操作参数错误：{error}")
        except RuntimeError as error:
            self.log_message.emit(f"操作执行错误：{error}")
        except Exception as error:
            self.log_message.emit(f"操作异常：{error}")
        finally:
            self._hid_service.send_stop()
            self._active_target = ""
            self.status_changed.emit("已停止")
            self.finished.emit()

    def _run(self, workflow: WorkflowDefinition, actions: list[ActionDefinition]) -> None:
        action_map = {action.id: action for action in actions}
        completed_cycles = 0
        self.status_changed.emit("运行中")
        try:
            while not self._stop_event.is_set() and (workflow.repeats == 0 or completed_cycles < workflow.repeats):
                started_at = time.monotonic()
                deadline = float("inf") if workflow.active_duration_ms == 0 else started_at + workflow.active_duration_ms / 1000
                limit_text = "无限，直到手动停止" if workflow.active_duration_ms == 0 else format_duration(workflow.active_duration_ms)
                self.log_message.emit(f"开始第 {completed_cycles + 1} 个周期，运行上限：{limit_text}")
                if workflow.mode == FlowMode.AB:
                    self._run_ab_stage(workflow, action_map, deadline)
                elif workflow.mode == FlowMode.CUSTOM:
                    if workflow.root_step:
                        self._run_flow_step(workflow.root_step, workflow, action_map, deadline)
                    elif workflow.tasks:
                        self._run_task_sequence(workflow.tasks, workflow, action_map, deadline)
                    elif workflow.blocks and workflow.custom_scheduler_enabled:
                        self._run_custom_scheduler(workflow, action_map, deadline)
                    elif workflow.blocks:
                        self._run_blocks(workflow.blocks, workflow, action_map, deadline)
                    else:
                        self._run_custom_stage(workflow, action_map, deadline)
                else:
                    raise RuntimeError("未知流程模式")
                if self._stop_event.is_set():
                    break

                completed_cycles += 1
                if workflow.rest_duration_ms > 0:
                    self.status_changed.emit("休息中")
                    self.log_message.emit(f"运行阶段结束，休息 {format_duration(workflow.rest_duration_ms)}")
                    if self._stop_event.wait(workflow.rest_duration_ms / 1000):
                        break
                    self.status_changed.emit("运行中")
        except ProtocolError as error:
            self.log_message.emit(f"流程参数错误：{error}")
        except RuntimeError as error:
            self.log_message.emit(f"流程执行错误：{error}")
        except Exception as error:
            self.log_message.emit(f"流程异常：{error}")
        finally:
            self._hid_service.send_stop()
            self._active_target = ""
            self.status_changed.emit("已停止")
            self.finished.emit()

    def _run_ab_stage(self, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        primary = action_map.get(workflow.primary_action_id)
        secondary = action_map.get(workflow.secondary_action_id) if workflow.secondary_action_id else None
        if primary is None: raise RuntimeError("A 操作已被删除，请重新选择")
        if workflow.secondary_action_id and secondary is None: raise RuntimeError("B 操作已被删除，请重新选择")
        trigger_at = time.monotonic() + workflow.secondary_trigger_ms / 1000 if secondary and workflow.secondary_trigger_ms > 0 else None
        secondary_done = trigger_at is None
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            boundary = min(deadline, trigger_at) if not secondary_done and trigger_at is not None and time.monotonic() < trigger_at else deadline
            self._run_action(primary, boundary, workflow.finish_current_action)
            if self._stop_event.is_set(): return
            now = time.monotonic()
            if not secondary_done and trigger_at is not None and now >= trigger_at:
                self.log_message.emit(f"暂停 A，执行 B：{secondary.name}")
                self._run_action(secondary, deadline, workflow.finish_current_action)
                secondary_done = True; self.log_message.emit("B 已完成，恢复 A 循环")
                continue
            if now >= deadline: return

    def _run_custom_scheduler(self, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        primary = next((block for block in workflow.blocks if block.id == workflow.scheduler_primary_block_id), None)
        secondary = next((block for block in workflow.blocks if block.id == workflow.scheduler_secondary_block_id), None)
        if primary is None or secondary is None or primary is secondary:
            raise RuntimeError("总流程 A/B 调度需要选择两个不同的根方块")
        trigger_at = time.monotonic() + workflow.scheduler_trigger_ms / 1000
        triggered = False
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            boundary = min(deadline, trigger_at) if not triggered else deadline
            self._run_block_sequence([primary], workflow, action_map, boundary)
            if self._stop_event.is_set():
                return
            if not triggered and time.monotonic() >= trigger_at:
                self.log_message.emit("暂停持续任务，执行定时插入任务")
                self._run_block_sequence([secondary], workflow, action_map, deadline)
                triggered = True
                if not workflow.scheduler_resume_primary:
                    return
                self.log_message.emit("插入任务已完成，恢复持续任务")

    def _run_scheduled_group(self, step: FlowStep, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        """协作式调度：任务只在操作边界轮转，暂停目标不会再取得下一次 HID 发送机会。"""
        started_at = time.monotonic()
        backgrounds = [child for child in step.children if child.enabled and child.trigger_type == "immediate"]
        triggers = [child for child in step.children if child.enabled and child.trigger_type in {"time", "step_complete"}]
        completed: set[str] = set(); paused: set[str] = set(); queued: list[FlowStep] = []; fired: set[str] = set(); cursor = 0
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            now = time.monotonic()
            for trigger in triggers:
                if trigger.id in fired:
                    continue
                ready = (trigger.trigger_type == "time" and now >= started_at + trigger.trigger_after_ms / 1000) or (trigger.trigger_type == "step_complete" and trigger.trigger_step_id in completed)
                if ready:
                    fired.add(trigger.id); queued.append(trigger)
                    self.log_message.emit(f"条件已满足，任务已进入执行队列：{trigger.title or trigger.kind}")
            if queued:
                trigger = queued.pop(0)
                targets = set(trigger.pause_target_step_ids)
                if targets:
                    paused.update(targets); self.log_message.emit(f"暂停 {len(targets)} 个目标任务，执行：{trigger.title or trigger.kind}")
                run_once = deepcopy(trigger); run_once.trigger_type = "immediate"; run_once.repeat_mode = "once"
                self._run_flow_step(run_once, workflow, action_map, deadline)
                completed.add(trigger.id)
                if targets and trigger.resume_paused:
                    paused.difference_update(targets); self.log_message.emit("触发任务完成，已恢复暂停目标")
                elif targets:
                    self.log_message.emit("触发任务完成，目标保持暂停")
                continue
            if backgrounds:
                current = backgrounds[cursor % len(backgrounds)]; cursor += 1
                if current.id in paused:
                    self.log_message.emit(f"任务保持暂停：{current.title or current.kind}")
                    self._stop_event.wait(0.02); continue
                run_once = deepcopy(current); run_once.repeat_mode = "once"; run_once.trigger_type = "immediate"
                self._run_flow_step(run_once, workflow, action_map, deadline)
                completed.add(current.id)
            else:
                self._stop_event.wait(0.05)

    def _run_flow_step(self, step: FlowStep, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        """执行树形流程。普通同级步骤严格顺序；定时插入在安全边界接管。"""
        if self._stop_event.is_set() or not step.enabled:
            return
        step_deadline = min(deadline, time.monotonic() + step.limit_ms / 1000) if step.limit_ms else deadline
        wait_min, wait_max = max(0, step.random_wait_min_ms), max(0, step.random_wait_max_ms)
        if wait_min or wait_max:
            if wait_min > wait_max: wait_min, wait_max = wait_max, wait_min
            wait_ms = random.randint(wait_min, wait_max)
            if wait_ms:
                self.log_message.emit(f"流程步骤“{step.title or step.kind}”执行前随机等待 {wait_ms / 1000:g} 秒")
                self._wait_until_stop_or_deadline(wait_ms, step_deadline)
                if self._stop_event.is_set() or time.monotonic() >= step_deadline: return
        if step.kind == "group" and step.group_mode == "scheduled":
            self._run_scheduled_group(step, workflow, action_map, step_deadline)
            return
        count = step.repeat_count if step.repeat_mode == "count" else (2_147_483_647 if step.repeat_mode in {"duration", "forever"} else 1)
        for _ in range(count):
            if self._stop_event.is_set() or time.monotonic() >= step_deadline:
                return
            if step.kind in {"sequence", "group"}:
                parent_started_at = time.monotonic()
                normal_children = [child for child in step.children if child.trigger_type == "immediate" and child.execution_mode != "timed_insert"]
                timed_children = [child for child in step.children if child.trigger_type == "time" or child.execution_mode == "timed_insert"]
                completion_children = [child for child in step.children if child.trigger_type == "step_complete"]
                pending = list(timed_children)
                for child in normal_children:
                    # 在操作边界处理已到点的插入步骤，保证不会并发发送 HID 命令。
                    due = [item for item in pending if time.monotonic() >= parent_started_at + item.trigger_after_ms / 1000]
                    for inserted in due:
                        pending.remove(inserted)
                        if inserted.pause_others:
                            self.log_message.emit(f"暂停当前序列，执行定时插入步骤：{inserted.title or inserted.kind}")
                        else:
                            self.log_message.emit(f"在安全边界执行定时插入步骤：{inserted.title or inserted.kind}")
                        self._run_flow_step(inserted, workflow, action_map, step_deadline)
                        if self._stop_event.is_set() or time.monotonic() >= step_deadline:
                            return
                    self._run_flow_step(child, workflow, action_map, step_deadline)
                    if self._stop_event.is_set() or time.monotonic() >= step_deadline:
                        return
                # 完成条件的前置步骤已在本组顺序分支结束后满足。
                for conditioned in completion_children:
                    self._run_flow_step(conditioned, workflow, action_map, step_deadline)
                    if self._stop_event.is_set() or time.monotonic() >= step_deadline: return
                # 主序列结束后，执行已到时但尚未到达安全边界的插入步骤。
                for inserted in pending:
                    if time.monotonic() >= parent_started_at + inserted.trigger_after_ms / 1000:
                        self._run_flow_step(inserted, workflow, action_map, step_deadline)
                        if self._stop_event.is_set() or time.monotonic() >= step_deadline:
                            return
            else:
                if step.kind == "empty":
                    self.log_message.emit("跳过未配置流程卡片")
                else:
                    block = FlowBlock(id=step.id, title=step.title, kind=step.kind, enabled=step.enabled, action_id=step.action_id, direct_step=step.direct_step, repeat_count=1, duration_ms=step.limit_ms)
                    previous_finish = workflow.finish_current_action
                    workflow.finish_current_action = step.limit_policy == "finish_current"
                    try:
                        self._run_leaf_block(block, workflow, action_map, step_deadline)
                    finally:
                        workflow.finish_current_action = previous_finish
                # 任务卡片本身完成后，沿其输出关系继续执行后续卡片。
                if step.children and not self._stop_event.is_set() and time.monotonic() < step_deadline:
                    connector = FlowStep(kind="group", children=step.children)
                    self._run_flow_step(connector, workflow, action_map, step_deadline)

    def _run_task_sequence(self, tasks: list[LinearTask], workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        for index, task in enumerate(tasks, start=1):
            if self._stop_event.is_set() or time.monotonic() >= deadline:
                return
            if not task.enabled:
                self.log_message.emit(f"跳过任务 {index}：{task.title or task.kind}")
                continue
            block = FlowBlock(id=task.id, title=task.title, kind=task.kind, enabled=task.enabled, action_id=task.action_id, direct_step=task.direct_step, repeat_count=task.repeat_count, duration_ms=task.duration_ms)
            try:
                self._run_leaf_block(block, workflow, action_map, deadline)
            except RuntimeError as error:
                raise RuntimeError(f"任务 {index}（{task.title or task.kind}）：{error}") from error

    def _run_blocks(self, blocks: list[FlowBlock], workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        """按旧 custom_steps 相同的语义重复根序列，容器只执行其自身的一轮。"""
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            self._run_block_sequence(blocks, workflow, action_map, deadline)

    def _run_block_sequence(self, blocks: list[FlowBlock], workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        for block in blocks:
            if self._stop_event.is_set() or time.monotonic() >= deadline:
                return
            if not block.enabled:
                self.log_message.emit(f"跳过已禁用方块：{block.title or block.kind}")
                continue
            if block.kind == "group":
                self._run_block_sequence(block.children, workflow, action_map, deadline)
            elif block.kind == "loop":
                loop_deadline = min(deadline, time.monotonic() + block.duration_ms / 1000) if block.loop_mode == "duration" else deadline
                count = block.repeat_count if block.loop_mode == "count" else (1_000_000 if block.loop_mode == "duration" else 2_147_483_647)
                for _ in range(count):
                    self._run_block_sequence(block.children, workflow, action_map, loop_deadline)
                    if self._stop_event.is_set() or time.monotonic() >= loop_deadline:
                        return
            else:
                self._run_leaf_block(block, workflow, action_map, deadline)

    def _run_leaf_block(self, block: FlowBlock, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        if block.kind == "action":
            action = action_map.get(block.action_id)
            if action is None:
                raise RuntimeError("自定义流程引用的操作已被删除")
            for _ in range(block.repeat_count):
                if self._stop_event.is_set() or time.monotonic() >= deadline:
                    return
                self._run_action(action, deadline, workflow.finish_current_action)
        elif block.kind == "action_duration":
            action = action_map.get(block.action_id)
            if action is None:
                raise RuntimeError("自定义流程引用的持续操作已被删除")
            action_deadline = min(deadline, time.monotonic() + block.duration_ms / 1000)
            while not self._stop_event.is_set() and time.monotonic() < action_deadline:
                self._run_action(action, action_deadline, workflow.finish_current_action)
        elif block.kind == "direct":
            if block.direct_step is None:
                raise RuntimeError("直接输入步骤为空")
            for _ in range(block.repeat_count):
                self._run_step(block.direct_step, None if workflow.finish_current_action else deadline)
                if self._stop_event.is_set() or time.monotonic() >= deadline:
                    return
        elif block.kind == "wait":
            self.log_message.emit(f"自定义等待：{format_duration(block.duration_ms)}，重复 {block.repeat_count} 次")
            for _ in range(block.repeat_count):
                self._wait_until_stop_or_deadline(block.duration_ms, deadline)
                if self._stop_event.is_set() or time.monotonic() >= deadline:
                    return
        else:
            raise RuntimeError("未知流程方块")

    def _run_custom_stage(self, workflow: WorkflowDefinition, action_map: dict[str, ActionDefinition], deadline: float) -> None:
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            for step in workflow.custom_steps:
                if self._stop_event.is_set() or time.monotonic() >= deadline:
                    return
                if step.kind == CustomStepKind.ACTION_REF:
                    action = action_map.get(step.action_id)
                    if action is None:
                        raise RuntimeError("自定义流程引用的操作已被删除")
                    for _ in range(step.repeat_count):
                        if self._stop_event.is_set() or time.monotonic() >= deadline:
                            return
                        self._run_action(action, deadline, workflow.finish_current_action)
                elif step.kind == CustomStepKind.ACTION_DURATION:
                    action = action_map.get(step.action_id)
                    if action is None:
                        raise RuntimeError("自定义流程引用的持续操作已被删除")
                    action_deadline = min(deadline, time.monotonic() + step.duration_ms / 1000)
                    while not self._stop_event.is_set() and time.monotonic() < action_deadline:
                        self._run_action(action, action_deadline, workflow.finish_current_action)
                elif step.kind == CustomStepKind.DIRECT_STEP:
                    if step.direct_step is None:
                        raise RuntimeError("直接输入步骤为空")
                    for _ in range(step.repeat_count):
                        self._run_step(step.direct_step, None if workflow.finish_current_action else deadline)
                        if self._stop_event.is_set() or time.monotonic() >= deadline:
                            return
                elif step.kind == CustomStepKind.WAIT:
                    self.log_message.emit(f"自定义等待：{format_duration(step.duration_ms)}，重复 {step.repeat_count} 次")
                    for _ in range(step.repeat_count):
                        self._wait_until_stop_or_deadline(step.duration_ms, deadline)
                        if self._stop_event.is_set() or time.monotonic() >= deadline:
                            return
                else:
                    raise RuntimeError("未知自定义流程步骤")

    def _run_action(self, action: ActionDefinition, deadline: float | None, finish_current: bool = False) -> bool:
        self.log_message.emit(f"执行操作：{action.name}")
        for step in action.steps:
            if self._stop_event.is_set():
                return False
            if deadline is not None and time.monotonic() >= deadline and not finish_current:
                return False
            # finish_current=True 时，已经开始的操作完整执行，不再被时间边界截断。
            step_deadline = None if finish_current else deadline
            self._run_step(step, step_deadline)
            if self._stop_event.is_set():
                return False
        return True

    def _run_step(self, step, deadline: float | None) -> None:
        if self._stop_event.is_set() or (deadline is not None and time.monotonic() >= deadline):
            return
        wait_min, wait_max = max(0, step.random_wait_min_ms), max(0, step.random_wait_max_ms)
        if wait_min or wait_max:
            if wait_min > wait_max: wait_min, wait_max = wait_max, wait_min
            random_wait = random.randint(wait_min, wait_max)
            if random_wait:
                self.log_message.emit(f"操作步骤执行前随机等待 {random_wait / 1000:g} 秒")
                self._wait_until_stop_or_deadline(random_wait, deadline)
                if self._stop_event.is_set() or (deadline is not None and time.monotonic() >= deadline): return
        if ActionKind(step.kind) is ActionKind.WAIT:
            self._wait_until_stop_or_deadline(wait_milliseconds(step), deadline)
            return
        command = command_for_step(step)
        if command is not None and not self._hid_service.send(command):
            raise RuntimeError("设备命令未发送成功")
        self._wait_until_stop_or_deadline(step.delay_after_ms, deadline)

    def _wait_until_stop_or_deadline(self, milliseconds: int, deadline: float | None) -> None:
        if milliseconds <= 0:
            return
        if deadline is None:
            self._stop_event.wait(milliseconds / 1000)
            return
        remaining_seconds = max(0, deadline - time.monotonic())
        self._stop_event.wait(min(milliseconds / 1000, remaining_seconds))

    def close(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
