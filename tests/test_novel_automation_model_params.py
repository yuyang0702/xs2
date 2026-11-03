import asyncio
from test_novel_automation import setup,policy


def test_optional_policy_model_params_are_forwarded_to_real_task_creation(tmp_path):
    root,manager,service=setup(tmp_path);p=policy();calls=[]
    def overrides(state,definition,stage):
        calls.append(stage);return {'writer':{'thinking_enabled':True,'reasoning_effort':'high'}}
    p.model_params_overrides=overrides;service.policy=lambda:p
    asyncio.run(service.tick(root))
    assert calls==['build']
    assert manager.created[0]['node_model_params_overrides']=={'writer':{'thinking_enabled':True,'reasoning_effort':'high'}}


def test_legacy_policy_without_optional_method_keeps_creation_unchanged(tmp_path):
    root,manager,service=setup(tmp_path);p=policy()
    if hasattr(p,'model_params_overrides'):delattr(p,'model_params_overrides')
    service.policy=lambda:p
    asyncio.run(service.tick(root))
    assert len(manager.created)==1 and 'node_model_params_overrides' not in manager.created[0]
