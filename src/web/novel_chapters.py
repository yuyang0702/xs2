"""Recover chapter production independently of the chapter currently being read."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import re
import shutil
from uuid import uuid4

from .novel_library import read_json
from .novel_repair import ensure_idle

PRODUCTION = ("mvp", "polish", "reader-sim", "post-hoc", "export")


def chapter_id(value):
    if not re.fullmatch(r"[0-9]{4}", str(value)) or value == "0000":
        raise ValueError("请选择 1 至 9999 之间的有效章节。")
    return value


def chapter_tasks(root, workflows_dir, chapter):
    result = {}
    reset_dates = [read_json(path, {}).get("reset_at") for path in
                   (root / "archive/chapter_resets").glob("[0-9][0-9][0-9][0-9].json")
                   if path.stem <= chapter]
    def timestamp(value):
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    reset_at = max((timestamp(value) for value in reset_dates if value), default=None)
    for stage in PRODUCTION:
        tasks = []
        for path in (workflows_dir / f"xs2-novel-flywheel-{stage}/tasks").glob("*.json"):
            task = read_json(path, {})
            workspace = task.get("workspace_override")
            if not workspace or Path(workspace).resolve() != root.resolve():
                continue
            if reset_at and (not task.get("created_at") or
                    timestamp(task["created_at"]) <= reset_at):
                continue
            task_chapter = task.get("parameter_values", {}).get("chapter_number", "")
            if stage == "export" and not task_chapter:
                manifest = read_json(root / "export/manifest.json", {})
                manuscript = root / "export/manuscript.md"
                body = root / f"story/{chapter}/chapter.md"
                exported = any(item.get("chapter") == chapter for item in manifest.get("chapters", []) if isinstance(item, dict))
                if not exported or not manuscript.is_file() or not body.is_file() or body.stat().st_mtime > manuscript.stat().st_mtime:
                    continue
            elif str(task_chapter).zfill(4) != chapter:
                continue
            if task.get("task_id"):
                tasks.append(task)
        if tasks:
            result[stage] = max(tasks, key=lambda task: task.get("created_at") or "")
    return result


def chapter_context(root, workflows_dir, chapter, action="write"):
    chapter_id(chapter)
    ensure_idle(root, workflows_dir)
    body = root / f"story/{chapter}/chapter.md"
    has_body = body.is_file() and bool(body.read_text(encoding="utf-8").strip())
    if action != "write" and not has_body:
        raise ValueError("本章还没有正文，请先完成正文生成。")
    tasks = chapter_tasks(root, workflows_dir, chapter)
    refs = {stage: {"workflow_id": f"xs2-novel-flywheel-{stage}", "task_id": task["task_id"]}
            for stage, task in tasks.items()}
    completed = [stage for stage, task in tasks.items() if task.get("status") == "completed"]
    if has_body and "mvp" not in completed:
        completed.insert(0, "mvp")
    # Never restore another chapter's intent or approved revision instructions.
    values = {}
    for stage in PRODUCTION:
        params = tasks.get(stage, {}).get("parameter_values", {})
        for key in ("human_intent", "world_intent", "target_word_count", "chapter_ending_mode"):
            if key in params:
                values[key] = params[key]
    plan = read_json(root / f"planning/chapters/{chapter}.json", {})
    if not has_body and isinstance(plan, dict) and plan.get("goal"):
        values["human_intent"] = plan["goal"]
    target = {"assess": "reader-sim", "audit": "post-hoc", "repair": "polish"}.get(action)
    if target:
        invalidated = PRODUCTION[PRODUCTION.index(target):]
        refs = {stage: ref for stage, ref in refs.items() if stage not in invalidated}
        completed = [stage for stage in completed if stage not in invalidated]
    later = sorted(path.parent.name for path in (root / "story").glob("[0-9][0-9][0-9][0-9]/chapter.md")
                   if path.parent.name > chapter and path.stat().st_size)
    return {"chapter": chapter, "has_body": has_body, "refs": refs, "completed": completed,
            "values": values, "later_chapters": later,
            "message": (f"修改第 {int(chapter)} 章后，第 " + "、".join(str(int(n)) for n in later[:10]) +
                        " 章的衔接、人物状态与伏笔需复核；后续正文会保留，不会自动重写。") if later else ""}


def _inside(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("章节路径不能离开当前作品。")
    return target


def chapter_removal_preview(root, workflows_dir, chapter):
    chapter_id(chapter)
    root = root.resolve()
    ensure_idle(root, workflows_dir)
    folder = _inside(root, f"story/{chapter}")
    body = folder / "chapter.md"
    if not body.is_file() or not body.read_text(encoding="utf-8").strip():
        raise ValueError("本章还没有正文，无需删除或重新生成。")
    if (root / f"story/{chapter}").is_symlink():
        raise ValueError("不支持操作指向其他目录的章节链接。")
    if any(path.is_symlink() for path in folder.rglob("*")):
        raise ValueError("章节含有链接文件，请先移除链接再操作。")
    state = read_json(root / ".novel-project.json", {})
    later = sorted(path.parent.name for path in (root / "story").glob("[0-9][0-9][0-9][0-9]/chapter.md")
                   if path.parent.name > chapter and path.stat().st_size)
    return {"chapter": chapter, "body_sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
            "revision": state.get("_revision", 0), "later_chapters": later,
            "file_count": sum(path.is_file() for path in folder.rglob("*")),
            "message": ("本章正文、评估和确认档案将移入备份，章节计划、本书设定与采用写法保留。"
                        "现有导出将移入备份，完成流程后重新导出。") +
                       (f"第{'、'.join(str(int(n)) for n in later)}章的衔接、人物状态和伏笔需要重新审核；后续正文保留。"
                        if later else "")}


def remove_chapter(root, workflows_dir, chapter, operation, expected_sha256, expected_revision,
                   support, save_json):
    """Move the actual chapter out of production and invalidate its old tasks."""
    if operation not in {"delete", "regenerate"}:
        raise ValueError("请选择删除或重新生成章节。")
    root = root.resolve()
    preview = chapter_removal_preview(root, workflows_dir, chapter)
    if preview["body_sha256"] != expected_sha256 or preview["revision"] != expected_revision:
        raise ValueError("正文或作品进度已更新，请重新确认操作范围。")
    if operation == "regenerate":
        check = support.preflight(root, chapter)
        if not check["ready"]:
            raise ValueError(check.get("next_step") or check["message"])
    context = chapter_context(root, workflows_dir, chapter)
    # Resolve every source/destination before moving any directory.
    backup_rel = f"quality/chapter-revisions/{chapter}/{uuid4().hex}"
    backup = _inside(root, backup_rel)
    sources = [f"story/{chapter}"]
    if (root / "export").exists():
        sources.append("export")
    legacy = read_json(root / "quality/reader_report.json", {})
    if str(legacy.get("chapter_number")) == chapter:
        sources.append("quality/reader_report.json")
    moves = [(_inside(root, relative), _inside(root, f"{backup_rel}/{relative}"))
             for relative in sources]
    state_path = _inside(root, ".novel-project.json")
    snapshots = [state_path] + [_inside(root, relative) for relative in (
        "archive/hooks.json", "archive/debts.json", "archive/current_status.json",
        "meta/hooks.md", "meta/debts.md", "meta/current_characters.md",
        "meta/current_world.md", "meta/story_timeline.md")]
    state = read_json(state_path, {})
    missing_snapshots = [path for path in snapshots if not path.exists()]
    moved = []
    backup.mkdir(parents=True)
    for source in snapshots:
        if source.is_file():
            target = backup / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    marker = _inside(root, f"archive/chapter_resets/{chapter}.json")
    previous_marker = marker.read_bytes() if marker.is_file() else None
    try:
        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            moved.append((source, target))
        receipt = {**preview, "operation": operation, "backup_path": backup_rel,
                   "reset_at": datetime.now(timezone.utc).isoformat()}
        save_json(marker, receipt)
        status = support.refresh_archive(root)
        current = str(state.get("values", {}).get("chapter_number", chapter)).zfill(4)
        state.setdefault("values", {})["latest_chapter"] = status.get("updated_chapter") or "0000"
        if operation == "regenerate" or chapter <= current:
            state["refs"] = {key: value for key, value in state.get("refs", {}).items() if key not in PRODUCTION}
            state["completed"] = [key for key in state.get("completed", []) if key not in PRODUCTION]
            state.update(stageId="mvp", index=5, autoNext=False, autoScope="manual",
                         autoLaunchStage="", autoPauseReason="", readerRepairCount=0,
                         repairModel="", repairReviewOnly=False, assessmentOnly=False,
                         autoRepairPlanId="", continuationIssue=None)
        if operation == "regenerate" or chapter == current:
            if chapter != current:
                state["values"].update(human_intent="", world_intent="", chapter_ending_mode="continue")
            state["values"].update(context["values"], chapter_number=chapter,
                                   prev_chapter=f"{int(chapter)-1:04d}",
                                   author_feedback_file=f"{backup_rel}/regeneration-instructions.md")
            plan = read_json(root / f"planning/chapters/{chapter}.json", {})
            if plan.get("goal"):
                state["values"]["human_intent"] = plan["goal"]
            ending = ("短篇应完成本篇主要冲突、关键伏笔与人物选择，保留余味。"
                      if state.get("mode") == "short" else
                      "本章是全书终章，应完成全书主要冲突与关键伏笔的收尾。"
                      if state["values"].get("chapter_ending_mode") == "book_final" else
                      "普通长篇章节仅完成局部目标，保留后续推进，不提前完结整本书。")
            support.write(root, state["values"]["author_feedback_file"],
                          f"# 第{chapter}章重新生成要求\n\n"
                          "本次从正文生产开始完整重写，只沿用本书设定、采用写法、有效章节方案及前文已确认事实。"
                          "不用旧稿或旧报告代替新正文，遵守本书叙事视角和角色知识边界，"
                          "不把未经核实的消息写成事实。"
                          "人物按自身处境作出选择，保留资源、能力和信息边界。"
                          f"\n叙事视角：{state['values'].get('narrative_pov', '沿用本书设置')}。"
                          f"\n目标字数：{state['values'].get('target_word_count', '使用本书设置')}。"
                          f"\n本章目标：{state['values'].get('human_intent', '')}。"
                          f"\n章节标题：{plan.get('title', '沿用现有大纲')}。"
                          f"\n保留章节号、标题、中文对白引号和自然段落。{ending}"
                          "完成后按原有流程润色、读者评估、必要返修、质量审核与导出。")
        state["_revision"] = state.get("_revision", 0) + 1
        save_json(state_path, state)
        return {**receipt, "state": state}
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                target.rename(source)
        for source in snapshots:
            saved = backup / source.relative_to(root)
            if saved.is_file():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, source)
        for source in missing_snapshots:
            source.unlink(missing_ok=True)
        if previous_marker is None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_bytes(previous_marker)
        raise
