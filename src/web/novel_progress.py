"""Production progress from saved tasks and real artifacts, never chapter * 5%."""
from pathlib import Path
from .novel_library import read_json

STAGES = [('build', '建立世界观'), ('character', '创建角色'), ('story-plan', '规划故事'),
          ('outline', '生成大纲'), ('mvp', '生成正文'), ('polish', '润色正文'),
          ('reader-sim', '读者评估'), ('post-hoc', '质量审核'), ('export', '导出成品')]
ACTIVE = {'pending', 'preparing', 'running', 'retry_waiting', 'resume_pending'}


def progress(root, state, workflows_dir):
    raw_chapter = str(state.get('values', {}).get('chapter_number', '1'))
    chapter = raw_chapter.zfill(4) if raw_chapter.isdigit() and len(raw_chapter) <= 4 else '0001'
    artifacts = {'build': 'meta/world_foundation.md', 'character': 'meta/character_profiles.md',
                 'story-plan': 'meta/story_plan.md', 'outline': 'outline/near_term_outline.md',
                 'mvp': f'story/{chapter}/chapter.md', 'polish': f'story/{chapter}/chapter.md',
                 'reader-sim': 'quality/reader_report.json', 'post-hoc': f'story/{chapter}/diff_story_confirmed.md',
                 'export': 'export/manuscript.md'}
    results = []
    current = ''
    refs = state.get('refs', {})
    newest_upstream = ''
    for stage, label in STAGES:
        reference = refs.get(stage, {})
        workflow = str(reference.get('workflow_id', ''))
        task_id = str(reference.get('task_id', ''))
        path = (workflows_dir / workflow / 'tasks' / (task_id + '.json')).resolve()
        task = read_json(path, {}) if workflow and task_id and path.is_relative_to(workflows_dir.resolve()) else {}
        status = task.get('status', '')
        artifact = root / artifacts[stage]
        exists = artifact.is_file() and artifact.stat().st_size > 0
        complete = exists and (status == 'completed' or not reference and stage in state.get('completed', []))
        if task.get('completed_at', '') and task['completed_at'] < newest_upstream:
            complete = False
        newest_upstream = max(newest_upstream, task.get('started_at') or '')
        if status in ACTIVE:
            current = label + '处理中'
            complete = False
        elif status in {'failed', 'interrupted', 'stopped', 'cancelled'}:
            current = label + '未完成，请处理任务提示'
        if stage == 'export' and exists:
            bodies = list((root / 'story').glob('[0-9][0-9][0-9][0-9]/chapter.md'))
            if any(body.stat().st_mtime > artifact.stat().st_mtime for body in bodies):
                complete = False
        results.append({'id': stage, 'label': label, 'completed': complete, 'status': status or ('completed' if complete else 'not_started')})
    completed = sum(item['completed'] for item in results)
    exported = results[-1]['completed']
    report = read_json(root / 'quality/reader_report.json', {})
    if exported:
        label = current or ('本篇已导出' if state.get('mode') == 'short' else f'第{int(chapter)}章已导出')
    else:
        label = current or next((item['label'] + '未完成' for item in results if not item['completed']), '尚未开始')
    return {'percent': round(completed / len(results) * 100), 'completed_count': completed,
            'total_count': len(results), 'label': label, 'stages': results,
            'chapter_count': len(list((root / 'story').glob('[0-9][0-9][0-9][0-9]/chapter.md'))),
            'can_download': (root / 'export/manuscript.md').is_file(),
            'export_current': exported, 'reader_verdict': report.get('verdict', '')}
