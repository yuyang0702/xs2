import asyncio

from test_novel_automation import setup, state, write


def test_failed_operational_stage_restarts_without_state_surgery_or_losing_book_models(tmp_path):
    root, manager, service = setup(tmp_path)
    current=state(root)
    current.update(analysisModel='default:analysis',writerModel='volcengine:body',polishModel='anthropic:polish')
    write(root/'.novel-project.json',current)
    marker=root/'story/0001/accepted-scene.txt';marker.parent.mkdir(parents=True);marker.write_bytes(b'accepted scene')
    asyncio.run(service.tick(root))
    first=manager.created[0]
    failed={**manager.get_task(first['workflow_id'],first['task_id']),'status':'failed',
            'node_states':{'writer':{'status':'failed','error':'Script Library 已漂移'}}}
    manager.save(failed)
    asyncio.run(service.tick(root))
    assert state(root)['autoArmed'] is True
    assert 'build' not in state(root)['refs']
    asyncio.run(service.tick(root))
    assert len(manager.created)==2
    assert manager.created[1]['node_model_overrides']==first['node_model_overrides']
    assert marker.read_bytes()==b'accepted scene'
    assert state(root)['polishModel']=='anthropic:polish'


def test_content_failure_stays_paused_and_does_not_create_a_replacement(tmp_path):
    root,manager,service=setup(tmp_path)
    asyncio.run(service.tick(root));first=manager.created[0]
    manager.save({**manager.get_task(first['workflow_id'],first['task_id']),'status':'failed','error':'人物提前知道账目，检查拒绝'})
    asyncio.run(service.tick(root));asyncio.run(service.tick(root))
    assert not state(root)['autoArmed']
    assert len(manager.created)==1
