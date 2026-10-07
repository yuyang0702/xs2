import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src.web.novel_repair import repair_context, prepare_repair
from src.web.novel_assistant import NovelAssistantJobs


class RepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'book'
        self.wfs = Path(self.temp.name) / 'workflows'
        self.body = self.root / 'story/0001/chapter.md'
        self.body.parent.mkdir(parents=True)
        self.body.write_text('原稿：他还没送到水。', encoding='utf-8')
        self.report = self.root / 'quality/reader_report.json'
        self.report.parent.mkdir()
        self.report.write_text(json.dumps({'verdict':'revise', 'summary':'缺少现场结果', 'issues':[{'priority':'high','goal':'写出水到户'}], 'repair_constraints':['保留人物承诺']}), encoding='utf-8')
        os.utime(self.body, (100,100)); os.utime(self.report,(200,200))
        self.task = self.wfs / 'xs2-novel-flywheel-reader-sim/tasks/one.json'
        self.task.parent.mkdir(parents=True)
        self.task.write_text(json.dumps({'task_id':'one','status':'completed', 'workspace_override':str(self.root), 'completed_at':'2026-10-07', 'parameter_values':{'chapter_number':'0001'}}),encoding='utf-8')

    def tearDown(self): self.temp.cleanup()

    async def test_model_receives_report_constraints_and_body_not_just_question(self):
        context = repair_context(self.root, '0001', self.wfs)
        captured = []
        class FakeModel:
            model_name = 'test-model'
            async def ainvoke(self, messages):
                captured.extend(messages)
                return SimpleNamespace(content='在结尾写出送水现场，并保留承诺。')
        jobs = NovelAssistantJobs()
        with patch('src.web.novel_assistant.create_llm', return_value=FakeModel()):
            entry = jobs.start(self.root,'5cc02f02-55b6-435b-9361-322cf814dd62',{'question':'规划返修','purpose':'reader_repair','chapter':'0001','_repair_context':context})
            await jobs.tasks[entry['id']]
        self.assertIn('写出水到户', captured[1][1])
        self.assertIn('保留人物承诺', captured[1][1])
        self.assertIn('原稿：他还没送到水。', captured[1][1])
        stored = jobs.history(self.root)[0]
        self.assertEqual(stored['repair_source']['reader_task_id'],'one')
        self.assertEqual(stored['purpose'],'reader_repair')

    def test_prepare_preserves_body_and_copies_edited_plan_with_chapter_scope(self):
        source = repair_context(self.root,'0001',self.wfs)
        entry = {'id':'5cc02f02-55b6-435b-9361-322cf814dd62','status':'completed','purpose':'reader_repair','repair_source':source}
        before = self.body.read_bytes()
        result = prepare_repair(self.root,entry,'用户调整：压缩中段，保留结尾互动。')
        instructions = self.root / result['feedback_path']
        self.assertIn('用户调整：压缩中段',instructions.read_text(encoding='utf-8'))
        self.assertEqual(self.body.read_bytes(),before)
        self.assertEqual((instructions.parent/'before.md').read_bytes(),before)
        self.assertFalse((self.root/'quality/author_feedback.md').exists())
        entry.update(applied_at='now',feedback_path=result['feedback_path'])
        self.assertTrue(prepare_repair(self.root,entry,'再次改')['already_applied'])

    def test_stale_or_other_chapter_report_cannot_drive_revision(self):
        source = repair_context(self.root,'0001',self.wfs)
        with self.assertRaisesRegex(ValueError,'有效的章节'):repair_context(self.root,'../1',self.wfs)
        d=json.loads(self.task.read_text());d['parameter_values']['chapter_number']='0002';self.task.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'其他章节'):repair_context(self.root,'0001',self.wfs)
        self.body.write_text('正文已改变',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'已过期'):prepare_repair(self.root,{'id':'one','status':'completed','purpose':'reader_repair','repair_source':source},'旧方案')

    def test_active_workflow_prevents_new_plan(self):
        d=json.loads(self.task.read_text());d['status']='running';self.task.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'任务正在处理'):repair_context(self.root,'0001',self.wfs)
