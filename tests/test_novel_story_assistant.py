import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.web.novel_assistant import NovelAssistantJobs

PLUGIN = Path(__file__).resolve().parents[2] / 'DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/script-library/xs2/story_support/story_support.py'
spec = importlib.util.spec_from_file_location('assistant_support_test', PLUGIN)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class StoryAssistantTest(unittest.IsolatedAsyncioTestCase):
    async def test_support_resolves_installed_owner_with_custom_namespace(self):
        from src.web.novel_story_support import story_support
        from src.workflow.script_library import ScriptLibraryCatalog
        from src.extension_api.registrar import OwnedPath
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            package=root/'extension'/'custom-prefix-xs2'/'story_support'
            package.mkdir(parents=True)
            (package/'story_support.py').write_text('VALUE = "loaded-owner"',encoding='utf-8')
            catalog=ScriptLibraryCatalog(root/'user',[OwnedPath('xs2-novel-flywheel',root/'extension')])
            with patch('src.workflow.script_library.get_script_library',return_value=catalog):
                self.assertEqual(story_support(required=True).VALUE,'loaded-owner')

    async def test_durable_sourced_proposal_reads_real_state_and_can_be_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support.write(root, 'meta/world_foundation.md', '所有人依赖共享通风。')
            captured=[]
            class Model:
                model_name='test-model'
                async def ainvoke(self,messages):
                    captured.extend(messages)
                    return SimpleNamespace(content=json.dumps({'reply':'从资源控制与信任展开。','options':[{'id':'A','title':'共享通风',
                        'chapters':[{'chapter':'0001','goal':'恢复通风','conflict':'责任隐瞒','choice':'交换记录','payoff':'识破隐瞒',
                                     'setup':[{'source_id':'meta/world_foundation.md','quote':'依赖共享通风','use':'制造合作压力'}]}]}]},ensure_ascii=False))
            jobs=NovelAssistantJobs()
            with patch('src.web.novel_assistant.story_support',return_value=support), patch('src.web.novel_assistant.create_llm',return_value=Model()):
                entry=jobs.start(root,'e716295d-6d70-4fdb-bc1e-2f7e3c9b9787',{'question':'讨论人性与合作','purpose':'plot','scope':'chapter','chapter':'0001','project':{'mode':'serial'}})
                await jobs.tasks[entry['id']]
            result=jobs.history(root)[0]
            self.assertEqual(result['status'],'completed')
            self.assertEqual(len(result['integration_projects']),3)
            self.assertIn('D15',captured[1][1])
            self.assertTrue(result['plot_source'])
            self.assertFalse((root/'planning/chapters/0001.json').exists())
            support.apply_plan(root,result,'A')
            support.prepare_context(root,'0001',check=True)
            self.assertIn('交换记录',support.read(root,'cache/story-support/context.md'))

    async def test_bad_model_anchor_is_visible_failure_and_never_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            class Model:
                async def ainvoke(self,messages):
                    return SimpleNamespace(content='{"reply":"建议","options":[{"id":"A","chapters":[{"chapter":"0001","goal":"救人","conflict":"断电","choice":"留下","payoff":"合作","setup":[{"source_id":"user_brief","quote":"不存在的事实"}]}]}]}')
            jobs=NovelAssistantJobs()
            with patch('src.web.novel_assistant.story_support',return_value=support),patch('src.web.novel_assistant.create_llm',return_value=Model()):
                entry=jobs.start(root,'c0938ed0-d48b-4c14-a4f8-6d54d4fc9846',{'question':'原创末日','purpose':'plot','chapter':'0001'})
                await jobs.tasks[entry['id']]
            result=jobs.history(root)[0]
            self.assertEqual(result['error_code'],'plot_format')
            self.assertIn('无法核实',result['message'])
            self.assertFalse((root/'planning').exists())
