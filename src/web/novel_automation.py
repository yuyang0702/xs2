"""Durable dispatch adapter for plugin-owned novel production policy."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from uuid import uuid4

from src.workflow.model_preferences import atomic_write
from src.runtime_admission import admitted_activity
from .novel_repair import repair_context, prepare_repair

logger = logging.getLogger(__name__)
STATE_FILE = ".novel-project.json"
ACTIVE = {"pending", "running", "preparing", "pre_running", "retry_waiting", "resume_pending", "paused"}


def _read(root):
    file = Path(root) / STATE_FILE
    return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}


def _armed(state):
    return state.get("autoNext") is True and state.get("autoController") == "server-v1" and state.get("autoArmed") is True


class NovelAutomation:
    def __init__(self, manager, resources, roots, policy, assistant_jobs, lock, workflows_dir):
        self.manager, self.resources, self.roots, self.policy = manager, resources, roots, policy
        self.assistant_jobs, self.lock, self.workflows_dir = assistant_jobs, lock, Path(workflows_dir)
        self._runner = None
        self._root_locks = {}

    @staticmethod
    def has_active(root):
        return _armed(_read(root))

    def _save(self, root, state):
        state["_revision"] = int(state.get("_revision") or 0) + 1
        atomic_write(Path(root) / STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))

    def _pause(self, root, state, reason):
        state.update(autoNext=False, autoArmed=False, autoScope="manual", autoLaunchStage="", autoPauseReason=reason)
        self._save(root, state)
        return state

    def pause(self, root):
        with self.lock:
            return self._pause(root, _read(root), "自动创作已暂停；已启动的任务继续执行。")

    async def start(self):
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._loop(), name="novel-production")

    async def stop(self):
        if self._runner is not None:
            self._runner.cancel()
            with suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None

    async def _loop(self):
        while True:
            try:
                for root in await asyncio.to_thread(self.roots):
                    if (Path(root) / STATE_FILE).is_file():
                        await self.tick(root)
            except Exception:
                logger.exception("后台小说创作轮询失败")
            await asyncio.sleep(1)

    def _tasks(self, root):
        tasks = []
        for path in self.workflows_dir.glob("*/tasks/*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            workspace = data.get("workspace_override")
            if workspace and Path(workspace).resolve() == Path(root).resolve():
                data.setdefault("workflow_id", path.parent.parent.name)
                tasks.append(data)
        return tasks

    def _apply_action(self, root, state, action):
        state.update(action.get("updates", {}))
        # This action follows a verified terminal task; its launch receipt must
        # not be recovered as a new revision after the controller stops.
        state.pop("autoPending", None)
        kind = action["action"]
        if kind in {"pause", "finish"}:
            return self._pause(root, state, action.get("reason", "自动创作已结束。"))
        if kind == "repair":
            state["autoRepairPlanId"] = state.get("autoRepairPlanId") or str(uuid4())
            state["autoLaunchStage"] = ""
        elif kind == "advance":
            stage = action["stage"]
            reset = set(action.get("reset", []))
            state["refs"] = {key: value for key, value in state.get("refs", {}).items() if key not in reset}
            state["completed"] = [key for key in state.get("completed", []) if key not in reset]
            state.update(stageId=stage, autoLaunchStage=stage, autoPauseReason="")
            stages = self.policy().STAGES
            if stage in stages:
                state["index"] = stages.index(stage)
        self._save(root, state)
        return state

    def _repair(self, root, state, policy):
        request_id = state["autoRepairPlanId"]
        entry = next((item for item in self.assistant_jobs.history(root) if item.get("id") == request_id), None)
        if entry is None:
            payload = policy.repair_request(state)
            payload["_repair_context"] = repair_context(root, payload["chapter"], self.workflows_dir)
            started = self.assistant_jobs.start(root, request_id, payload)
            if started.get("id") != request_id:
                raise ValueError("本书另有助手分析正在进行，请完成后再继续自动返修。")
            return
        if entry.get("status") == "running":
            return
        if entry.get("status") != "completed":
            raise ValueError(entry.get("message") or "返修方案生成失败或被重启中断，请重新规划。")
        result = prepare_repair(root, entry, str(entry.get("reply") or ""))
        if not result["already_applied"]:
            entries = self.assistant_jobs.history(root)
            saved = next(item for item in entries if item["id"] == request_id)
            saved.update(applied_at=datetime.now(timezone.utc).isoformat(), feedback_path=result["feedback_path"], applied_plan=entry["reply"])
            self.assistant_jobs._write(root, entries)
        self._apply_action(root, state, policy.repair_ready(state, result["feedback_path"]))

    def _next_dispatch(self, root):
        from src.runtime_admission import is_closed
        if is_closed():
            return None
        state = _read(root)
        if not _armed(state):
            return None
        policy = self.policy()
        resources = self.resources()
        stage = state.get("stageId") or state.get("autoLaunchStage")
        workflow_id = resources.get(stage)
        if not workflow_id:
            raise ValueError("当前步骤的小说工作流不可用，请检查插件。")
        checkpoint_check = getattr(policy, 'validate_checkpoint', None)
        if callable(checkpoint_check):
            checkpoint_check(root, state, stage)
        if state.get("autoRepairPlanId"):
            self._repair(root, state, policy)
            return None
        tasks = self._tasks(root)
        intent = state.get("autoPending")
        ref = state.get("refs", {}).get(stage)
        if intent and not ref:
            if intent.get("stage") != stage or intent.get("workflow_id") != workflow_id:
                raise ValueError("待启动任务与当前步骤不一致，请检查自动创作状态。")
            candidates = [item for item in tasks if item["workflow_id"] == workflow_id
                          and item["task_id"] not in intent.get("before_task_ids", [])
                          and all(item.get("parameter_values", {}).get(key) == value for key, value in intent["parameters"].items())]
            if len(candidates) > 1:
                raise ValueError("发现多个可能属于上次启动的任务，请手动确认，避免重复执行。")
            if candidates:
                ref = {"workflow_id": workflow_id, "task_id": candidates[0]["task_id"]}
                state.setdefault("refs", {})[stage] = ref
                self._save(root, state)
        if ref:
            if ref.get("workflow_id") != workflow_id:
                raise ValueError("当前步骤的任务归属已变化，请核对插件资源与历史任务。")
            task = self.manager.get_task(ref["workflow_id"], ref["task_id"])
            if task is None:
                raise ValueError("当前步骤的任务不存在，自动流程已暂停。")
            if task.get("workspace_override") and Path(task["workspace_override"]).resolve() != root:
                raise ValueError("当前任务不属于这本作品，不能继续自动执行。")
            others = [item for item in tasks if item["status"] in ACTIVE and item["task_id"] != ref["task_id"]]
            if others:
                raise ValueError("本书有其他任务正在处理，自动创作已暂停以避免并发修改。")
            dispatch_check = getattr(policy, 'validate_dispatch', None)
            if callable(dispatch_check):
                dispatch_check(root, state, stage, task)
            status = task.get("status")
            if status in {"pending", "resume_pending"}:
                return ref
            if status in {"running", "preparing", "pre_running", "retry_waiting"}:
                return None
            if status != "completed":
                recover = getattr(policy, "recovery_action", None)
                action = recover(state, stage, task, root=root) if callable(recover) else None
                if action:
                    self._apply_action(root, state, action)
                    return None
                raise ValueError(f"当前任务状态为 {status}，请检查任务后重新启用自动创作。")
            policy.verify_completion(root, state, stage, task)
            state["completed"] = list(dict.fromkeys([*state.get("completed", []), stage]))
            self._apply_action(root, state, policy.next_action(root, state, stage))
            return None
        if any(item["status"] in ACTIVE for item in tasks):
            raise ValueError("本书仍有创作或评估任务正在处理，自动创作已暂停。")
        workflow = self.manager.get_workflow(workflow_id)
        if not workflow:
            raise ValueError("当前工作流不可用，请检查插件状态。")
        definition = workflow["definition"]
        checkpoint_options = {}
        checkpoint = state.get('automaticCheckpoint') or {}
        checkpoint_policy = getattr(policy, 'checkpoint_options', None)
        if checkpoint.get('stage') == stage and callable(checkpoint_policy):
            source = self.manager.get_task(workflow_id, checkpoint['source_task_id'])
            checkpoint_options = checkpoint_policy(root, state, stage, definition, source)
        loader = getattr(self.assistant_jobs, "support_loader", None)
        support = loader(required=True) if callable(loader) else None
        policy.launch_check(root, state, stage, support)
        parameters = policy.parameters(state, definition)
        parameters = {**checkpoint_options.get('parameter_values', {}), **parameters}
        feedback = parameters.get("author_feedback_file")
        if feedback:
            file = (root / feedback).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                raise ValueError("已确认的返修要求文件不可用，请重新选择。")
        if intent is None:
            intent = {"id": str(uuid4()), "stage": stage, "workflow_id": workflow_id,
                      "before_task_ids": [item["task_id"] for item in tasks if item["workflow_id"] == workflow_id],
                      "parameters": parameters}
            if checkpoint_options.get('selected_node_ids'):
                intent['selected_node_ids'] = checkpoint_options['selected_node_ids']
                intent['checkpoint_source_task_id'] = checkpoint['source_task_id']
            state["autoPending"] = intent
            self._save(root, state)
        elif parameters != intent["parameters"]:
            raise ValueError("待启动任务的参数发生变化，请检查后重新启用。")
        task_options = {"parameter_values": parameters, "workspace_override": str(root),
                        "node_model_overrides": policy.model_overrides(state, definition, stage)}
        if intent.get('selected_node_ids'):
            if (intent['selected_node_ids'] != checkpoint_options.get('selected_node_ids')
                    or intent.get('checkpoint_source_task_id') != checkpoint.get('source_task_id')):
                raise ValueError('待恢复任务的检查点发生变化')
            task_options['selected_node_ids'] = intent['selected_node_ids']
        params_policy = getattr(policy, "model_params_overrides", None)
        if callable(params_policy):
            params_overrides = params_policy(state, definition, stage)
            if params_overrides is not None:
                task_options["node_model_params_overrides"] = params_overrides
        created = self.manager.create_task(workflow_id, **task_options)
        if not created or not created.get("task_id") or created.get("success") is False:
            raise ValueError((created or {}).get("message") or "创建任务失败，自动创作已暂停。")
        ref = {"workflow_id": workflow_id, "task_id": created["task_id"]}
        state.setdefault("refs", {})[stage] = ref
        state.update(persisted=True, autoLaunchStage="", autoPauseReason="")
        state["autoPending"]["task_id"] = created["task_id"]
        self._save(root, state)
        return ref

    @admitted_activity("后台自动创作正在推进。", closed_result=None)
    async def tick(self, root):
        root = Path(root).resolve()
        guard = self._root_locks.setdefault(str(root), asyncio.Lock())
        async with guard:
            try:
                with self.lock:
                    ref = self._next_dispatch(root)
                if ref is None:
                    return
                # Re-read after preparing dispatch; a concurrent pause cancels
                # future launches while retaining the durable pending Task.
                with self.lock:
                    if not _armed(_read(root)):
                        return
                result = await self.manager.run_task(ref["workflow_id"], ref["task_id"])
                from src.runtime_admission import is_closed
                if is_closed():
                    return
                if result and result.get("success") is False:
                    raise ValueError(result.get("message") or "启动任务失败。")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("自动创作暂停: %s", root)
                with self.lock:
                    state = _read(root)
                    if _armed(state):
                        self._pause(root, state, str(error) or "自动创作发生错误，请检查任务。")
