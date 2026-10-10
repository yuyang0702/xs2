import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.workflow.definition import WorkflowDef, WorkflowEdge, WorkflowGateway, WorkflowNode, WorkflowTask
from src.workflow.engine import WorkflowEngine
from src.workflow.failure_policy import activate_scheduled_retry
from src.workflow.nodes import BaseNodePlugin, NodeResult, registry


class ResumeBoundaryTests(unittest.TestCase):
    def test_partial_start_at_default_writer_branch_survives_retry(self):
        calls = []

        class Probe(BaseNodePlugin):
            node_type = "condition_resume_boundary_probe"

            async def execute(self, context):
                node = context.node_def.id
                calls.append(node)
                if node == "single_writer" and calls.count(node) == 1:
                    return NodeResult(status="failed", error="temporary output failure")
                return NodeResult(status="success", summary=node)

        with tempfile.TemporaryDirectory() as directory:
            manager = SimpleNamespace(sessions={"main": object()}, main_session_id="main")
            engine = WorkflowEngine(manager)
            engine._ws_manager = SimpleNamespace(
                resolve_workflow_workspace=lambda *args, **kwargs: Path(directory)
            )
            definition = WorkflowDef(
                workflow_id="test-condition-boundary",
                nodes=[
                    WorkflowNode(id="prefix", node_type=Probe.node_type),
                    WorkflowNode(id="multi_writer", node_type=Probe.node_type),
                    WorkflowNode(id="single_writer", node_type=Probe.node_type,
                                 auto_retry_count=1, auto_retry_interval_seconds=0),
                    WorkflowNode(id="export", node_type=Probe.node_type),
                ],
                gateways=[WorkflowGateway(id="writer_choice", gateway_type="condition")],
                edges=[
                    WorkflowEdge(source="prefix", target="writer_choice"),
                    WorkflowEdge(source="writer_choice", target="multi_writer",
                                 condition={"expression": "{{writer_type}}==muti",
                                            "is_default": False}),
                    WorkflowEdge(source="writer_choice", target="single_writer",
                                 condition={"expression": "", "is_default": True}),
                    WorkflowEdge(source="multi_writer", target="export"),
                    WorkflowEdge(source="single_writer", target="export"),
                ],
            )
            task = WorkflowTask(
                workflow_id=definition.workflow_id,
                snapshot_definition=definition.to_dict(),
                parameter_values={"writer_type": "single"},
            )
            with patch.dict(registry._plugins, {Probe.node_type: Probe}), \
                 patch.object(engine, "_save_task_state", new=AsyncMock()), \
                 patch.object(engine, "_finalize_run_artifacts", new=AsyncMock()), \
                 patch.object(engine, "_push_wf_task_update"):
                first = asyncio.run(engine.execute_task(
                    definition, task, from_node_id="single_writer",
                    pre_created_session_id="main",
                ))
                self.assertEqual(first.status, "retry_waiting")
                restored = WorkflowTask.from_dict(first.to_dict())
                restored.node_states["single_writer"] = activate_scheduled_retry(
                    restored.node_states["single_writer"]
                )
                result = asyncio.run(engine.execute_task(
                    definition, restored, pre_created_session_id="main",
                ))
                self.assertEqual(result.status, "completed")
                self.assertEqual(calls, ["single_writer", "single_writer", "export"])

    def test_retry_after_partial_start_does_not_execute_excluded_prefix(self):
        calls = []

        class Probe(BaseNodePlugin):
            node_type = "resume_boundary_probe"

            async def execute(self, context):
                node = context.node_def.id
                calls.append(node)
                if node == "writer" and calls.count(node) == 1:
                    return NodeResult(status="failed", error="temporary connection error")
                return NodeResult(status="success", summary=node)

        with tempfile.TemporaryDirectory() as directory:
            manager = SimpleNamespace(sessions={"main": object()}, main_session_id="main")
            engine = WorkflowEngine(manager)
            engine._ws_manager = SimpleNamespace(resolve_workflow_workspace=lambda *args, **kwargs: Path(directory))
            definition = WorkflowDef(workflow_id="test-boundary", nodes=[
                WorkflowNode(id="prefix", node_type=Probe.node_type),
                WorkflowNode(id="writer", node_type=Probe.node_type, auto_retry_count=1, auto_retry_interval_seconds=0),
                WorkflowNode(id="export", node_type=Probe.node_type),
            ], edges=[WorkflowEdge(source="prefix", target="writer"), WorkflowEdge(source="writer", target="export")])
            task = WorkflowTask(workflow_id=definition.workflow_id, snapshot_definition=definition.to_dict())
            with patch.dict(registry._plugins, {Probe.node_type: Probe}), \
                 patch.object(engine, "_save_task_state", new=AsyncMock()), \
                 patch.object(engine, "_finalize_run_artifacts", new=AsyncMock()), \
                 patch.object(engine, "_push_wf_task_update"):
                first = asyncio.run(engine.execute_task(definition, task, from_node_id="writer", pre_created_session_id="main"))
                self.assertEqual(first.status, "retry_waiting")
                restored = WorkflowTask.from_dict(first.to_dict())
                restored.node_states["writer"] = activate_scheduled_retry(restored.node_states["writer"])
                result = asyncio.run(engine.execute_task(definition, restored, pre_created_session_id="main"))
                self.assertEqual(result.status, "completed")
                self.assertEqual(calls, ["writer", "writer", "export"])
                self.assertEqual(result.node_states["writer"].automatic_retry_count, 1)


if __name__ == "__main__":
    unittest.main()
