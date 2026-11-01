import asyncio
import importlib.util
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest


def policy():
    path = Path(__file__).resolve().parents[2] / "DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/script-library/xs2/console_service/production.py"
    spec = importlib.util.spec_from_file_location("test_production_policy", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class Manager:
    def __init__(self, directory):
        self.directory = directory
        self.created = []
        self.started = []

    def get_workflow(self, workflow_id):
        return {"definition": {"workflow_id": workflow_id, "nodes": [{"id": "writer", "node_type": "agent"}], "variables": [
            {"key": "chapter_number", "default": "0001", "type": "string"},
            {"key": "premise", "required": True, "type": "string"},
            {"key": "source_file", "type": "file", "default": "input.md"},
            {"key": "author_feedback_file", "type": "file"},
            {"key": "output", "source_type": "output"},
            {"key": "conflict_plan_mode", "type": "string"},
            {"key": "chapter_ending_mode", "type": "string"},
        ]}}

    def create_task(self, workflow_id, **kwargs):
        task = {"task_id": f"task-{len(self.created)+1}", "workflow_id": workflow_id, "status": "pending", **kwargs}
        self.created.append(task)
        self.save(task)
        return task

    def save(self, task):
        write(self.directory / task["workflow_id"] / "tasks" / (task["task_id"] + ".json"), task)

    def get_task(self, workflow_id, task_id):
        path = self.directory / workflow_id / "tasks" / (task_id + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    async def run_task(self, workflow_id, task_id):
        self.started.append(task_id)
        task = self.get_task(workflow_id, task_id)
        task["status"] = "running"
        self.save(task)
        return {"success": True}


def setup(tmp_path):
    from src.web.novel_automation import NovelAutomation
    root = tmp_path / "book"
    state = {"_revision": 0, "autoNext": True, "autoController": "server-v1", "autoArmed": True,
             "autoScope": "short_full", "mode": "short", "stageId": "build", "refs": {}, "completed": [],
             "values": {"premise": "test premise", "chapter_number": "0001"}}
    write(root / ".novel-project.json", state)
    manager = Manager(tmp_path / "workflows")
    jobs = SimpleNamespace(support_loader=lambda **kwargs: SimpleNamespace(preflight=lambda root, chapter: {"ready": True}))
    resources = lambda: {stage: "custom-" + stage for stage in policy().STAGES}
    service = NovelAutomation(manager, resources, lambda: [root], policy, jobs, RLock(), manager.directory)
    return root, manager, service


def state(root):
    return json.loads((root / ".novel-project.json").read_text(encoding="utf-8"))


def test_legacy_auto_flag_does_not_start_on_deployment(tmp_path):
    root, manager, service = setup(tmp_path)
    data = state(root); data.pop("autoArmed"); write(root / ".novel-project.json", data)
    asyncio.run(service.tick(root))
    assert manager.created == []


def test_backend_dispatch_survives_restart_and_advances_without_browser(tmp_path):
    root, manager, service = setup(tmp_path)
    asyncio.run(service.tick(root))
    assert len(manager.created) == 1
    assert state(root)["refs"]["build"]["task_id"] == "task-1"
    asyncio.run(service.tick(root))
    assert len(manager.created) == 1
    task = manager.get_task("custom-build", "task-1"); task["status"] = "completed"; manager.save(task)
    artifact = root / "meta/world_foundation.md"; artifact.parent.mkdir(); artifact.write_text("world")
    asyncio.run(service.tick(root))
    assert state(root)["stageId"] == "character"
    asyncio.run(service.tick(root))
    assert len(manager.created) == 2


def test_failure_pauses_and_does_not_launch_next_stage(tmp_path):
    root, manager, service = setup(tmp_path)
    asyncio.run(service.tick(root))
    task = manager.get_task("custom-build", "task-1"); task["status"] = "failed"; manager.save(task)
    asyncio.run(service.tick(root))
    assert not state(root)["autoNext"]
    assert state(root)["autoPauseReason"]
    assert len(manager.created) == 1


def test_launch_intent_reconciles_created_task_before_ref_was_persisted(tmp_path):
    root, manager, service = setup(tmp_path)
    data = state(root)
    data["autoPending"] = {"workflow_id": "custom-build", "stage": "build", "before_task_ids": [],
                           "parameters": {"premise": "test premise", "chapter_number": "0001"}}
    write(root / ".novel-project.json", data)
    manager.create_task("custom-build", parameter_values=data["autoPending"]["parameters"], workspace_override=str(root))
    asyncio.run(service.tick(root))
    assert len(manager.created) == 1
    assert manager.started == ["task-1"]


def test_pause_and_other_workspace_task_prevent_new_launch(tmp_path):
    root, manager, service = setup(tmp_path)
    manager.create_task("unrelated-workflow", parameter_values={}, workspace_override=str(root))
    asyncio.run(service.tick(root))
    assert len(manager.created) == 1
    assert not state(root)["autoNext"]
    service.pause(root)
    assert not service.has_active(root)


def test_parameter_contract_filters_outputs_files_and_keeps_approved_feedback(tmp_path):
    root, manager, service = setup(tmp_path)
    data = state(root); (root / "instructions.md").write_text("approved repair")
    data["values"].update(source_file="evil.txt", output="bad", author_feedback_file="instructions.md", chapter_ending_mode="continue")
    write(root / ".novel-project.json", data)
    asyncio.run(service.tick(root))
    params = manager.created[0]["parameter_values"]
    assert "source_file" not in params and "output" not in params
    assert params["author_feedback_file"] == "instructions.md"
    assert params["conflict_plan_mode"] == "short_full"


def test_reader_reject_blocks_archive_and_missing_artifact_blocks_advance(tmp_path):
    root, manager, service = setup(tmp_path)
    asyncio.run(service.tick(root))
    task = manager.get_task("custom-build", "task-1"); task["status"] = "completed"; manager.save(task)
    asyncio.run(service.tick(root))
    assert not state(root)["autoNext"]
    assert state(root)["stageId"] == "build"
    data = state(root); data.update(stageId="reader-sim", autoNext=True, autoArmed=True, readerRepairCount=2, autoRepairLimit=2)
    folder = root / "story/0001"; folder.mkdir(parents=True); (folder / "chapter.md").write_text("body")
    write(folder / "reader_report.json", {"verdict": "reject", "chapter_number": "0001"})
    decision = policy().next_action(root, data, "reader-sim")
    assert decision["action"] == "pause"


def test_serial_limits_final_chapter_and_existing_body_stop_batch(tmp_path):
    root, _, _ = setup(tmp_path)
    data = state(root)
    data.update(mode="serial", autoScope="serial_batch", autoChapterStarted=1, autoChapterLimit=3)
    assert policy().next_action(root, data, "export")["stage"] == "mvp"
    data["values"]["chapter_ending_mode"] = "book_final"
    assert policy().next_action(root, data, "export")["action"] == "finish"
    data["values"]["chapter_ending_mode"] = "continue"
    file = root / "story/0002/chapter.md"; file.parent.mkdir(parents=True); file.write_text("existing")
    assert policy().next_action(root, data, "export")["action"] == "pause"
    data["autoChapterStarted"] = 3
    assert policy().next_action(root, data, "export")["action"] == "finish"


def test_assessment_only_and_repair_review_only_stop_at_requested_boundary(tmp_path):
    root, _, _ = setup(tmp_path)
    folder = root / "story/0001"; folder.mkdir(parents=True); (folder / "chapter.md").write_text("body")
    write(folder / "reader_report.json", {"verdict": "pass", "chapter_number": "0001"})
    data = state(root); data["assessmentOnly"] = True
    assert policy().next_action(root, data, "reader-sim")["action"] == "finish"
    data.update(assessmentOnly=False, repairReviewOnly=True)
    assert policy().next_action(root, data, "reader-sim")["stage"] == "post-hoc"
    assert policy().next_action(root, data, "post-hoc")["action"] == "finish"


def test_reader_repair_plan_is_durable_and_restarts_polish_with_feedback(tmp_path):
    root, manager, service = setup(tmp_path)
    class Jobs:
        entries = []
        support_loader = staticmethod(lambda **kwargs: SimpleNamespace(preflight=lambda *args: {"ready": True}))
        def history(self, root): return self.entries
        def _write(self, root, entries): self.entries = entries
        def start(self, root, request_id, payload):
            self.entries.append({"id": request_id, "status": "running", "purpose": "reader_repair",
                                 "repair_source": payload["_repair_context"], "reply": "", "chapter": "0001"})
            return self.entries[-1]
    service.assistant_jobs = Jobs()
    data = state(root); data.update(stageId="reader-sim", readerRepairCount=0, autoRepairLimit=2)
    task = manager.create_task("custom-reader-sim", parameter_values={"chapter_number": "0001"}, workspace_override=str(root))
    task["status"] = "completed"; manager.save(task)
    write(manager.directory / "custom-reader-sim/.extension.json", {"owner": "xs2-novel-flywheel", "local_id": "reader-sim"})
    data["refs"] = {"reader-sim": {"workflow_id": "custom-reader-sim", "task_id": task["task_id"]}}
    write(root / ".novel-project.json", data)
    folder = root / "story/0001"; folder.mkdir(parents=True); (folder / "chapter.md").write_text("body")
    write(folder / "reader_report.json", {"verdict": "revise", "chapter_number": "0001", "summary": "needs work"})
    asyncio.run(service.tick(root))
    request_id = state(root)["autoRepairPlanId"]
    asyncio.run(service.tick(root))
    assert service.assistant_jobs.entries[0]["id"] == request_id
    service.assistant_jobs.entries[0].update(status="completed", reply="Revise the scene.")
    asyncio.run(service.tick(root))
    updated = state(root)
    assert updated["stageId"] == "polish"
    assert updated["readerRepairCount"] == 1
    assert "reader-sim" not in updated["refs"]
    assert (root / updated["values"]["author_feedback_file"]).is_file()
    asyncio.run(service.tick(root))
    assert manager.created[-1]["workflow_id"] == "custom-polish"
    assert manager.created[-1]["parameter_values"]["author_feedback_file"] == updated["values"]["author_feedback_file"]


def test_two_ticks_cannot_create_duplicate_tasks_and_missing_inputs_pause(tmp_path):
    root, manager, service = setup(tmp_path)
    async def concurrent():
        await asyncio.gather(service.tick(root), service.tick(root))
    asyncio.run(concurrent())
    assert len(manager.created) == 1 and len(manager.started) == 1
    service.pause(root)
    asyncio.run(service.tick(root))
    assert len(manager.started) == 1
    data = state(root); data.update(autoNext=True, autoArmed=True, refs={}, autoPending=None)
    data["values"]["premise"] = ""
    task = manager.get_task("custom-build", "task-1"); task["status"] = "stopped"; manager.save(task)
    write(root / ".novel-project.json", data)
    asyncio.run(service.tick(root))
    assert not state(root)["autoNext"] and len(manager.created) == 1


def test_parameters_preserve_world_direction_and_adopted_adviser_guidance(tmp_path):
    root, manager, service = setup(tmp_path)
    data = state(root)
    data["values"].update(world_direction="world rules", source_idea="original details", advisor_guidance="approved advice")
    write(root / ".novel-project.json", data)
    asyncio.run(service.tick(root))
    premise = manager.created[0]["parameter_values"]["premise"]
    assert all(text in premise for text in ("test premise", "world rules", "original details", "approved advice"))


def test_actual_assistant_adapter_exposes_support_for_continuation(tmp_path, monkeypatch):
    from src.web.novel_assistant import NovelAssistantJobs
    root, manager, service = setup(tmp_path)
    delegate = SimpleNamespace(tasks={}, support_loader=lambda **kwargs: SimpleNamespace(preflight=lambda *args: {"ready": True}))
    monkeypatch.setattr("src.web.novel_assistant.console_service", lambda: SimpleNamespace(create_assistant=lambda *args, **kwargs: delegate))
    service.assistant_jobs = NovelAssistantJobs()
    data = state(root); data["stageId"] = "mvp"; write(root / ".novel-project.json", data)
    asyncio.run(service.tick(root))
    assert len(manager.created) == 1
    assert manager.created[0]["workflow_id"] == "custom-mvp"
