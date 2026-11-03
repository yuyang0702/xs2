"""Forward persisted workbench task facts to the installed novel plugin."""
from pathlib import Path

from src.workflow.token_usage import aggregate_token_usage

from .novel_chapters import chapter_tasks
from .novel_library import read_json
from .novel_plugin import console_service


def _measured_usage(task):
    def recorded(states):
        return {
            key: {**row, 'child_states': recorded(row.get('child_states') or {})}
            for key, row in states.items()
            if isinstance(row, dict) and row.get('status') != 'skipped' and not row.get('is_skipped')
        }

    aggregate = aggregate_token_usage(recorded(task.get('node_states') or {}), {}, pricing_config={})
    calls = aggregate['calls']
    if calls:
        models = {call['model_id'] for call in calls if call['model_id'] != 'unknown'}
        total = sum(call['total_tokens'] for call in calls)
        count = sum(call['call_count'] for call in calls)
        basis = 'ledger'
    else:
        models = set(aggregate['by_model']) - {'unknown'}
        total = aggregate['total']['total_tokens']
        count = aggregate['total']['call_count']
        basis = 'summary'
    if not models and not total and not count:
        return None
    return {'basis': basis, 'models': sorted(models), **({'total_tokens': total} if total else {}),
            **({'call_count': count} if count else {})}


def progress(root, state, workflows_dir, *, chapter='', include_details=True, service=None):
    service = service or console_service().progress
    tasks = {}
    usages = {}
    workflows = Path(workflows_dir).resolve()
    for stage, reference in (state.get('refs') or {}).items():
        if not isinstance(reference, dict):
            continue
        workflow, task_id = reference.get('workflow_id'), reference.get('task_id')
        if not all(isinstance(value, str) and value and value not in {'.', '..'}
                   and '/' not in value and '\\' not in value and ':' not in value
                   for value in (workflow, task_id)):
            continue
        directory = (workflows / workflow / 'tasks').resolve()
        path = (directory / (task_id + '.json')).resolve()
        if not directory.is_relative_to(workflows) or path.parent != directory:
            continue
        task = read_json(path, {})
        if not isinstance(task, dict) or task.get('workflow_id', workflow) != workflow or task.get('task_id', task_id) != task_id:
            continue
        workspace = task.get('workspace_override')
        if workspace and (not isinstance(workspace, str) or Path(workspace).resolve() != root.resolve()):
            continue
        if isinstance(workspace, str) and Path(workspace).is_absolute():
            tasks[stage] = task
        else:
            # Keep legacy stage status without disclosing an unbound task's details.
            tasks[stage] = {key: task[key] for key in ('status', 'started_at', 'completed_at', 'parameter_values') if key in task}
    archived = {}
    if chapter and include_details:
        selected = service.chapter_id(chapter)
        current = service.chapter_id(state.get('values', {}).get('chapter_number', '1')) or '0001'
        if selected and selected != current:
            archived = chapter_tasks(root, workflows, selected)
    if include_details:
        for stage, task in (tasks | archived).items():
            if task.get('workspace_override') and (usage := _measured_usage(task)):
                usages[stage] = usage
    return service.project_progress(root, state, tasks, usages, selected=chapter,
                                    include_details=include_details, archived=archived)
