import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from hid_control.models import (
    ActionDefinition,
    ActionKind,
    ActionStep,
    AppState,
    CustomFlowStep,
    CustomStepKind,
    FlowBlock,
    FlowMode,
    FlowStep,
    LinearTask,
    WorkflowDefinition,
)
from hid_control.ui.ab_flow_page import ABFlowPage
from hid_control.ui.custom_flow_page import CustomFlowPage
from hid_control.ui.main_window import MainWindow
from hid_control.workflow import WorkflowRunner


class FakeSerial:
    is_connected = True

    def __init__(self) -> None:
        self.commands: list[str] = []

    def send(self, command: str) -> bool:
        self.commands.append(command)
        return True

    def send_stop(self) -> None:
        self.commands.append("{STOP}")


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_finish_current_action_controls_deadline_behavior(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(steps=[ActionStep(ActionKind.KEY_TAP, "A")])
        runner._run_action(action, time.monotonic() - 1, finish_current=False)
        self.assertEqual(serial.commands, [])
        runner._run_action(action, time.monotonic() - 1, finish_current=True)
        self.assertEqual(serial.commands, ["{A}"])

    def test_action_steps_are_sent_in_order(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(steps=[ActionStep(ActionKind.KEY_TAP, "A"), ActionStep(ActionKind.KEY_COMBO, "CTRL+C")])
        runner._run_action(action, time.monotonic() + 1)
        self.assertEqual(serial.commands, ["{A}", "{CTRL+C}"])

    def test_single_action_runs_once_then_stops(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(name="单次", steps=[ActionStep(ActionKind.KEY_TAP, "A")])
        self.assertTrue(runner.start_action_once(action))
        for _ in range(50):
            if not runner.is_running:
                break
            time.sleep(0.01)
        self.assertFalse(runner.is_running)
        self.assertEqual(serial.commands, ["{A}", "{STOP}"])

    def test_move_preview_sends_command_to_connected_device(self) -> None:
        serial = FakeSerial()
        messages: list[str] = []

        class PreviewSource:
            def set_move_preview_status(self, message: str) -> None:
                messages.append(message)

        class PreviewWindow:
            def _log(self, message: str) -> None:
                messages.append(message)

        window = PreviewWindow()
        window._runner = type("Runner", (), {"is_running": False})()
        window._serial = serial
        MainWindow._preview_move(window, ActionStep(ActionKind.MOVE_NORMALIZED, "500_500"), PreviewSource())

        self.assertEqual(serial.commands, ["{MOVE_NORM_500_500}"])
        self.assertTrue(any("已发送试移命令" in message for message in messages))

    def test_step_delay_runs_after_hid_command(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        waits: list[int] = []
        runner._wait_until_stop_or_deadline = lambda milliseconds, deadline: waits.append(milliseconds)  # type: ignore[method-assign]
        runner._run_action(ActionDefinition(steps=[ActionStep(ActionKind.KEY_TAP, "A", delay_after_ms=250)]), time.monotonic() + 1)
        self.assertEqual(serial.commands, ["{A}"])
        self.assertEqual(waits, [250])

    def test_object_hotkeys_are_loaded_from_configuration(self) -> None:
        state = AppState.from_dict({"actions": [{"id": "A", "name": "操作", "hotkey": "Ctrl+Alt+1"}], "workflows": [{"id": "W", "mode": "ab", "name": "流程", "hotkey": "Ctrl+Alt+2", "primary_action_id": "A"}]})
        self.assertEqual(state.actions[0].hotkey, "Ctrl+Alt+1")
        self.assertEqual(state.workflows[0].hotkey, "Ctrl+Alt+2")

    def test_current_ab_flow_migrates_to_millisecond_durations(self) -> None:
        state = AppState.from_dict({"workflows": [{"primary_action_id": "A", "secondary_action_id": "B", "secondary_trigger_seconds": 60, "active_minutes": 10, "rest_minutes": 5}]})
        workflow = state.workflows[0]
        self.assertEqual(workflow.secondary_trigger_ms, 60_000)
        self.assertEqual(workflow.active_duration_ms, 600_000)
        self.assertEqual(workflow.rest_duration_ms, 300_000)

    def test_scheduled_group_queues_trigger_before_background_round_robin(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action_a = ActionDefinition(id="A", steps=[ActionStep(ActionKind.KEY_TAP, "A")])
        action_b = ActionDefinition(id="B", steps=[ActionStep(ActionKind.KEY_TAP, "B")])
        group = FlowStep(kind="group", group_mode="scheduled", children=[
            FlowStep(id="background", kind="action", action_id="A"),
            FlowStep(id="trigger", kind="action", action_id="B", trigger_type="time", trigger_after_ms=0, pause_target_step_ids=["background"]),
        ])
        runner._run_flow_step(group, WorkflowDefinition(), {"A": action_a, "B": action_b}, time.monotonic() + 0.01, {})
        self.assertEqual(serial.commands[0], "{B}")
        self.assertIn("{A}", serial.commands)

    def test_action_step_random_wait_runs_before_hid_command(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        waits: list[int] = []
        runner._wait_until_stop_or_deadline = lambda milliseconds, deadline: waits.append(milliseconds)  # type: ignore[method-assign]
        runner._run_step(ActionStep(ActionKind.KEY_TAP, "A", random_wait_min_ms=222, random_wait_max_ms=222), None)
        self.assertEqual(serial.commands, ["{A}"])
        self.assertEqual(waits[0], 222)

    def test_flow_step_random_wait_runs_before_task(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        waits: list[int] = []
        runner._wait_until_stop_or_deadline = lambda milliseconds, deadline: waits.append(milliseconds)  # type: ignore[method-assign]
        step = FlowStep(kind="action", action_id="A", random_wait_min_ms=321, random_wait_max_ms=321)
        runner._run_flow_step(step, WorkflowDefinition(), {"A": ActionDefinition(id="A", steps=[ActionStep(ActionKind.KEY_TAP, "A")])}, time.monotonic() + 1, {})
        self.assertIn(321, waits)
        self.assertEqual(serial.commands, ["{A}"])

    def test_task_card_runs_its_downstream_card_after_completion(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        first = FlowStep(kind="action", action_id="A", children=[FlowStep(kind="action", action_id="B")])
        runner._run_flow_step(first, WorkflowDefinition(), {"A": ActionDefinition(id="A", steps=[ActionStep(ActionKind.KEY_TAP, "A")]), "B": ActionDefinition(id="B", steps=[ActionStep(ActionKind.KEY_TAP, "B")])}, time.monotonic() + 1, {})
        self.assertEqual(serial.commands, ["{A}", "{B}"])

    def test_tree_flow_runs_nested_steps_in_strict_order(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        root = FlowStep(kind="sequence", children=[
            FlowStep(kind="sequence", title="A", children=[
                FlowStep(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "A")),
                FlowStep(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "B")),
            ]),
            FlowStep(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "C")),
        ])
        runner._run_flow_step(root, WorkflowDefinition(finish_current_action=True), {}, time.monotonic() + 1, {})
        self.assertEqual(serial.commands, ["{A}", "{B}", "{C}"])

    def test_custom_flow_repeats_referenced_operation(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(id="A", steps=[ActionStep(ActionKind.KEY_TAP, "A", delay_after_ms=20)])
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.ACTION_REF, action_id="A", repeat_count=2)])
        runner._run_custom_stage(flow, {"A": action}, time.monotonic() + 0.05)
        self.assertGreaterEqual(serial.commands.count("{A}"), 2)

    def test_custom_flow_runs_action_for_configured_duration(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(id="A", steps=[ActionStep(ActionKind.KEY_TAP, "A", delay_after_ms=15)])
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.ACTION_DURATION, action_id="A", duration_ms=35)])
        runner._run_custom_stage(flow, {"A": action}, time.monotonic() + 0.05)
        self.assertGreaterEqual(serial.commands.count("{A}"), 2)

    def test_custom_flow_repeats_direct_step(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.DIRECT_STEP, direct_step=ActionStep(ActionKind.KEY_TAP, "A", delay_after_ms=20), repeat_count=2)])
        runner._run_custom_stage(flow, {}, time.monotonic() + 0.05)
        self.assertGreaterEqual(serial.commands.count("{A}"), 2)

    def test_custom_flow_executes_direct_mouse_step(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.DIRECT_STEP, direct_step=ActionStep(ActionKind.MOUSE_CLICK, "LEFT", delay_after_ms=20))])
        runner._run_custom_stage(flow, {}, time.monotonic() + 0.03)
        self.assertIn("{LEFT_CLICK}", serial.commands)

    def test_nested_flow_blocks_execute_group_and_loop_in_order(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        blocks = [
            FlowBlock(kind="group", children=[FlowBlock(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "A"))]),
            FlowBlock(kind="loop", repeat_count=2, children=[FlowBlock(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "B"))]),
        ]
        runner._run_block_sequence(blocks, WorkflowDefinition(finish_current_action=True), {}, time.monotonic() + 1, {})

        self.assertEqual(serial.commands, ["{A}", "{B}", "{B}"])

    def test_disabled_flow_block_skips_its_entire_subtree(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        blocks = [
            FlowBlock(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "A")),
            FlowBlock(kind="group", enabled=False, children=[FlowBlock(kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "B"))]),
        ]
        runner._run_block_sequence(blocks, WorkflowDefinition(finish_current_action=True), {}, time.monotonic() + 1, {})
        self.assertEqual(serial.commands, ["{A}"])
        restored = AppState.from_dict(AppState(workflows=[WorkflowDefinition(mode=FlowMode.CUSTOM, blocks=blocks)]).to_dict())
        self.assertFalse(restored.workflows[0].blocks[1].enabled)

    def test_custom_wait_step_uses_milliseconds(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        waits: list[int] = []
        def stop_after_wait(milliseconds: int, deadline: float) -> None:
            waits.append(milliseconds)
            runner._stop_event.set()
        runner._wait_until_stop_or_deadline = stop_after_wait  # type: ignore[method-assign]
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.WAIT, duration_ms=2_000)])
        runner._run_custom_stage(flow, {}, time.monotonic() + 0.001)
        self.assertEqual(waits, [2_000])

    def test_finish_current_completes_all_steps_after_deadline(self) -> None:
        serial = FakeSerial()
        runner = WorkflowRunner(serial)  # type: ignore[arg-type]
        action = ActionDefinition(steps=[ActionStep(ActionKind.KEY_TAP, "A", 100), ActionStep(ActionKind.KEY_TAP, "B", 200)])
        waits: list[int] = []
        runner._wait_until_stop_or_deadline = lambda milliseconds, deadline: waits.append(milliseconds)  # type: ignore[method-assign]

        runner._run_action(action, time.monotonic() - 1, finish_current=True)

        self.assertEqual(serial.commands, ["{A}", "{B}"])
        self.assertEqual(waits, [100, 200])

    def test_custom_flow_page_creates_blank_root_and_next_card(self) -> None:
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM)
        page = CustomFlowPage()
        page.set_data([flow], [], "")
        page._add_root_card()
        first = flow.root_step.children[0]
        page._add_child_card(first.id)
        self.assertEqual(first.kind, "empty")
        self.assertEqual(len(flow.root_step.children), 1)
        self.assertEqual(len(first.children), 1)

    def test_custom_flow_page_migrates_legacy_steps_to_cards(self) -> None:
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, custom_steps=[CustomFlowStep(kind=CustomStepKind.ACTION_REF, action_id="A")])
        restored = AppState.from_dict(AppState(workflows=[flow]).to_dict()).workflows[0]
        page = CustomFlowPage()
        page.set_data([restored], [ActionDefinition(id="A", name="操作")], "")
        self.app.processEvents()
        self.assertEqual([(step.kind, step.action_id) for step in restored.root_step.children], [("action", "A")])
        self.assertIn("操作", page._title(restored.root_step.children[0]))

    def test_custom_flow_page_copies_card_with_unique_id(self) -> None:
        step = FlowStep(kind="action", action_id="A", limit_ms=500)
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, root_step=FlowStep(kind="group", children=[step]))
        page = CustomFlowPage()
        page.set_data([flow], [ActionDefinition(id="A", name="操作")], "")
        page._selected_step_id = step.id
        page._copy_card()
        self.assertEqual(len(flow.root_step.children), 2)
        self.assertNotEqual(flow.root_step.children[0].id, flow.root_step.children[1].id)
        self.assertEqual([(item.kind, item.limit_ms) for item in flow.root_step.children], [("action", 500), ("action", 500)])

    def test_custom_flow_tasks_round_trip_in_order(self) -> None:
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, tasks=[LinearTask(id="A", kind="direct", direct_step=ActionStep(ActionKind.KEY_TAP, "A")), LinearTask(id="B", kind="wait", duration_ms=500)])
        restored = AppState.from_dict(AppState(workflows=[flow]).to_dict()).workflows[0]
        self.assertEqual([(task.id, task.kind, task.duration_ms) for task in restored.tasks], [("A", "direct", 0), ("B", "wait", 500)])
        self.assertEqual([step.id for step in restored.root_step.children], ["A", "B"])

    def test_custom_flow_card_adds_downstream_branch(self) -> None:
        first = FlowStep(id="A", kind="action", action_id="action-A")
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, root_step=FlowStep(kind="group", children=[first]))
        page = CustomFlowPage()
        page.set_data([flow], [ActionDefinition(id="action-A", name="操作")], "")
        page._add_child_card("A")
        self.assertEqual(flow.root_step.children[0].id, "A")
        self.assertEqual(len(first.children), 1)
        self.assertEqual(first.children[0].kind, "empty")

    def test_locked_custom_flow_disables_blank_card_addition(self) -> None:
        flow = WorkflowDefinition(mode=FlowMode.CUSTOM, root_step=FlowStep(kind="group", children=[FlowStep(kind="action")]), locked=True)
        page = CustomFlowPage()
        page.set_data([flow], [], "")
        self.assertFalse(page.add_blank_button.isEnabled())
        self.assertFalse(page.save_button.isEnabled())

    def test_locked_items_load_from_configuration(self) -> None:
        state = AppState.from_dict({
            "actions": [{"id": "A", "name": "操作", "locked": True}],
            "workflows": [{"id": "W", "mode": "ab", "name": "流程", "primary_action_id": "A", "locked": True}],
        })

        self.assertTrue(state.actions[0].locked)
        self.assertTrue(state.workflows[0].locked)
        self.assertTrue(state.to_dict()["actions"][0]["locked"])
        self.assertTrue(state.to_dict()["workflows"][0]["locked"])

    def test_locked_ab_and_custom_flows_cannot_be_edited_or_deleted(self) -> None:
        action = ActionDefinition(id="A", name="操作")
        ab_flow = WorkflowDefinition(id="AB", mode=FlowMode.AB, primary_action_id="A", locked=True)
        ab_page = ABFlowPage()
        ab_page.set_data([ab_flow], [action], "")
        self.app.processEvents()
        self.assertFalse(ab_page.save_button.isEnabled())
        self.assertFalse(ab_page.delete_button.isEnabled())
        ab_page._delete_flow()
        self.assertEqual([ab_flow], ab_page._workflows)
        ab_page._toggle_lock("AB")
        self.assertTrue(ab_page.save_button.isEnabled())

        custom_flow = WorkflowDefinition(id="CUSTOM", mode=FlowMode.CUSTOM, locked=True)
        custom_page = CustomFlowPage()
        custom_page.set_data([custom_flow], [action], "")
        self.app.processEvents()
        self.assertFalse(custom_page.save_button.isEnabled())
        self.assertFalse(custom_page.add_blank_button.isEnabled())
        self.assertEqual([custom_flow], custom_page._workflows)


if __name__ == "__main__":
    unittest.main()
