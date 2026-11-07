from test_novel_automation_routes import control, payload, saved


def test_browser_reload_or_save_cannot_reset_automatic_recovery_budget(control):
    current=saved(control)
    current['automaticRecovery']={'0001/build':[{'task_id':'failed-1'},{'task_id':'failed-2'}]}
    control.service._save(control.root,current)
    incoming=saved(control);incoming.pop('automaticRecovery')
    response=control.client.put('/api/novel-console/projects',json=payload(control,incoming))
    assert response.status_code==200,response.text
    assert saved(control)['automaticRecovery']==current['automaticRecovery']
    incoming=saved(control);incoming['automaticRecovery']={}
    response=control.client.post('/api/novel-console/automation/start',json=payload(control,incoming))
    assert response.status_code==200,response.text
    assert saved(control)['automaticRecovery']==current['automaticRecovery']


def test_browser_cannot_inject_or_erase_server_checkpoint(control):
    current = saved(control)
    incoming = {**current, 'automaticCheckpoint': {'stage': 'mvp', 'source_task_id': 'forged'}}
    response = control.client.put('/api/novel-console/projects', json=payload(control, incoming))
    assert response.status_code == 200, response.text
    assert not saved(control).get('automaticCheckpoint')
    current = saved(control)
    current['automaticCheckpoint'] = {'stage': 'mvp', 'source_task_id': 'server-owned'}
    control.service._save(control.root, current)
    incoming = {**saved(control), 'automaticCheckpoint': None}
    response = control.client.put('/api/novel-console/projects', json=payload(control, incoming))
    assert response.status_code == 200, response.text
    assert saved(control)['automaticCheckpoint'] == current['automaticCheckpoint']
