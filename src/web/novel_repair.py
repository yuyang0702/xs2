"""Bind repair advice to the chapter and reader report it actually analysed."""
import hashlib
import json
from pathlib import Path
import re
import tempfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_idle(root: Path, workflows_dir: Path) -> None:
    for stage in ('build', 'character', 'story-plan', 'outline', 'mvp', 'polish', 'reader-sim', 'post-hoc', 'export'):
        for file in (workflows_dir / f'xs2-novel-flywheel-{stage}/tasks').glob('*.json'):
            task = json.loads(file.read_text(encoding='utf-8'))
            if task.get('status') in {'pending', 'running', 'preparing', 'pre_running', 'retry_waiting', 'resume_pending'} and task.get('workspace_override') and Path(task['workspace_override']).resolve() == root.resolve():
                raise ValueError('本书仍有创作或评估任务正在处理，请完成后再规划或启动返修。')


def reader_report_path(root: Path, chapter: str) -> Path:
    scoped = root / f"story/{chapter}/reader_report.json"
    return scoped if scoped.is_file() else root / 'quality/reader_report.json'


def preserve_legacy_report(root: Path, workflows_dir: Path) -> None:
    """One-time migration before switching production; do not invent an evaluation."""
    report = root / 'quality/reader_report.json'
    if not report.is_file():
        return
    data = json.loads(report.read_text(encoding='utf-8'))
    tasks = []
    for path in (workflows_dir / 'xs2-novel-flywheel-reader-sim/tasks').glob('*.json'):
        task = json.loads(path.read_text(encoding='utf-8'))
        if (task.get('status') == 'completed' and task.get('workspace_override')
                and Path(task['workspace_override']).resolve() == root.resolve()):
            tasks.append(task)
    latest = max(tasks, key=lambda task: task.get('completed_at') or '', default={})
    chapter = str(data.get('chapter_number') or latest.get('parameter_values', {}).get('chapter_number') or '')
    if not re.fullmatch(r'[0-9]{4}', chapter) or chapter == '0000':
        return
    target = root / f'story/{chapter}/reader_report.json'
    if target.exists():
        return
    try:
        context = repair_context(root, chapter, workflows_dir, require_idle=False)
    except ValueError:
        return
    data.update(chapter_number=chapter, body_sha256=context['chapter_sha256'])
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    temp_path.replace(target)


def repair_context(root: Path, chapter: str, workflows_dir: Path, require_idle=True) -> dict:
    if require_idle:
        ensure_idle(root, workflows_dir)
    if not re.fullmatch(r'[0-9]{4}', chapter) or chapter == '0000':
        raise ValueError('请选择有效的章节。')
    body = root / f'story/{chapter}/chapter.md'
    report = reader_report_path(root, chapter)
    if not body.is_file() or not body.read_text(encoding='utf-8').strip():
        raise ValueError('本章还没有正文，暂时不能规划返修。')
    if not report.is_file():
        raise ValueError('还没有读者评估，请先运行模拟读者。')
    data = json.loads(report.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not data.get('verdict'):
        raise ValueError('读者报告不完整，请重新评估。')
    # The existing reader workflow writes one shared report. Never apply another
    # chapter's most recent evaluation to the chapter currently being browsed.
    tasks = []
    for file in (workflows_dir / 'xs2-novel-flywheel-reader-sim/tasks').glob('*.json'):
        task = json.loads(file.read_text(encoding='utf-8'))
        if task.get('status') == 'completed' and task.get('workspace_override') and Path(task['workspace_override']).resolve() == root.resolve():
            tasks.append(task)
    scoped = report != root / 'quality/reader_report.json'
    if scoped:
        tasks = [task for task in tasks
                 if str(task.get('parameter_values', {}).get('chapter_number', '')).zfill(4) == chapter]
    latest = max(tasks, key=lambda t: t.get('completed_at') or '', default=None)
    report_chapter = str(data.get('chapter_number') or (latest or {}).get('parameter_values', {}).get('chapter_number') or '')
    if report_chapter != chapter:
        raise ValueError('当前读者报告属于其他章节或无法确认归属，请先评估本章。')
    if (data.get('body_sha256') and data['body_sha256'] != digest(body)) or (
            not data.get('body_sha256') and body.stat().st_mtime > report.stat().st_mtime):
        raise ValueError('正文在读者评估后已有修改，请重新评估再规划返修。')
    return {'chapter': chapter, 'chapter_sha256': digest(body), 'report_sha256': digest(report),
            'report_path': report.relative_to(root).as_posix(),
            'reader_task_id': (latest or {}).get('task_id', ''), 'report': data,
            'content': body.read_text(encoding='utf-8'), 'summary': str(data.get('summary') or '')}


def verify_source(root: Path, source: dict) -> None:
    chapter = source.get('chapter', '')
    if not re.fullmatch(r'[0-9]{4}', chapter):
        raise ValueError('这条建议没有绑定章节，请重新规划返修。')
    body = root / f'story/{chapter}/chapter.md'
    report_path = source.get('report_path', 'quality/reader_report.json')
    if report_path not in ('quality/reader_report.json', f'story/{chapter}/reader_report.json'):
        raise ValueError('返修报告路径无效，请重新规划。')
    report = root / report_path
    if not body.is_file() or not report.is_file() or digest(body) != source.get('chapter_sha256') or digest(report) != source.get('report_sha256'):
        raise ValueError('正文或读者报告已更新，这份方案已过期，请重新规划返修。')


def prepare_repair(root: Path, entry: dict, plan: str) -> dict:
    if entry.get('status') != 'completed' or entry.get('purpose') != 'reader_repair':
        raise ValueError('请先完成读者返修方案分析。')
    if entry.get('applied_at'):
        return {'feedback_path': entry['feedback_path'], 'already_applied': True}
    source = entry.get('repair_source', {})
    verify_source(root, source)
    if not plan.strip():
        raise ValueError('返修方案不能为空。')
    chapter = source['chapter']
    folder = root / f"quality/repairs/{chapter}/{entry['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    # Retain the original chapter and report before the existing polish workflow
    # overwrites the body. The plan is chapter-scoped, never a global instruction.
    (folder / 'before.md').write_bytes((root / f'story/{chapter}/chapter.md').read_bytes())
    (folder / 'reader-before.json').write_bytes((root / source.get('report_path', 'quality/reader_report.json')).read_bytes())
    confirmed = root / f"story/{chapter}/confirmed_state.json"
    if confirmed.is_file():
        (folder / 'confirmed-state-before.json').write_bytes(confirmed.read_bytes())
    text = f'# 第{chapter}章 · 用户确认的返修方案\n\n{plan.strip()}\n\n执行要求：按上述意见修改完整正文，不以计划代替正文；维护既定事实、人物、视角与本书风格。只处理本章，短篇收束全文，长篇普通章不提前完结全书。读者复评要检查修改是否落实，独立判断，不因采用方案而默认通过。\n'
    target = folder / 'instructions.md'
    target.write_text(text, encoding='utf-8')
    return {'feedback_path': target.relative_to(root).as_posix(), 'already_applied': False}
