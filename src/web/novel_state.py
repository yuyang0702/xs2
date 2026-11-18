"""Normalize project routing after the standalone reader left the workbench."""

RETIRED_READER_STAGE = "reader-sim"
AUDIT_STAGE = "post-hoc"
AUDIT_INDEX = 7
RETIRED_READER_PAUSE = "上一轮任务已暂停。可查看正文、运行质量审核或进入润色。"
LEGACY_READER_REASONS = (
    "已达到本章自动返修次数上限，请查看正文与读者报告。",
    "本次返修复评尚未通过，请查看报告后决定后续操作。",
    "整篇审稿仍有超出或未明确属于本次修改范围的问题，请先确认修改范围。",
    "本章读者评估已完成。",
    "旧版读者评估已退出创作流程。请重新选择本章操作。",
)


def _reader_selected(state):
    return RETIRED_READER_STAGE in (state.get("stageId"), state.get("autoLaunchStage"))


def _reader_intent(state):
    intent = state.get("autoPending")
    return intent if isinstance(intent, dict) and intent.get("stage") == RETIRED_READER_STAGE else None


def requires_new_chapter_action(state):
    """The old request did not authorize restarting a manuscript workflow."""
    return state.get("assessmentOnly") is True or (
        bool(state.get("autoRepairPlanId") or _reader_intent(state)) and not _reader_selected(state)
        and state.get("stageId") not in (AUDIT_STAGE, "export")
    )


def normalize_project_state(state):
    if not isinstance(state, dict):
        return state
    result = dict(state)
    reader_selected = _reader_selected(state)
    if reader_selected:
        result.update(stageId=AUDIT_STAGE, index=AUDIT_INDEX)
        if state.get("autoLaunchStage") == RETIRED_READER_STAGE:
            result["autoLaunchStage"] = AUDIT_STAGE

    intent = _reader_intent(state)
    if intent:
        token = state.get("productionLaunchLease")
        if isinstance(token, dict) and token.get("stage") == RETIRED_READER_STAGE:
            result["retiredReaderLaunchIntent"] = intent
        # Retain the old native reference for history and lease reconciliation.
        if intent.get("task_id") and intent.get("workflow_id"):
            previous_refs = state.get("refs")
            refs = dict(previous_refs) if isinstance(previous_refs, dict) else {}
            refs.setdefault(RETIRED_READER_STAGE, {key: intent[key] for key in ("workflow_id", "task_id")})
            result["refs"] = refs
        result.pop("autoPending")
    for key in ("automaticCheckpoint", "productionLaunchContext"):
        saved = state.get(key)
        if isinstance(saved, dict) and saved.get("stage") == RETIRED_READER_STAGE:
            result.pop(key)

    if requires_new_chapter_action(state):
        result.update(autoNext=False, autoArmed=False, autoScope="manual",
                      autoLaunchStage="", autoPauseReason=RETIRED_READER_PAUSE)
    elif state.get("autoPauseReason") in LEGACY_READER_REASONS:
        result["autoPauseReason"] = RETIRED_READER_PAUSE
    result.pop("autoRepairPlanId", None)
    result.pop("assessmentOnly", None)
    return result


def preserve_reader_launch_history(existing, incoming):
    """Only the native guard may release an old execution reservation."""
    token = existing.get("productionLaunchLease")
    if isinstance(token, dict) and token.get("stage") == RETIRED_READER_STAGE:
        incoming["productionLaunchLease"] = token
        intent = existing.get("retiredReaderLaunchIntent")
        if intent:
            incoming["retiredReaderLaunchIntent"] = intent
        old_ref = (existing.get("refs") or {}).get(RETIRED_READER_STAGE)
        if old_ref:
            incoming["refs"] = {**(incoming.get("refs") or {}), RETIRED_READER_STAGE: old_ref}
