"""Repeat launches must never interrupt work or guess a foreign service's identity."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def instance(tmp_path, monkeypatch):
    from src.startup_identity import StartupProfile
    from src import startup_instances as client
    monkeypatch.delenv('DETERMINFLOW_DATA_DIR', raising=False)
    monkeypatch.delenv('DETERMINFLOW_CONFIG_DIR', raising=False)
    monkeypatch.delenv('AI_COMPANY_DATA_DIR', raising=False)
    monkeypatch.delenv('AI_COMPANY_CONFIG_DIR', raising=False)
    profile = StartupProfile.from_root(tmp_path / 'project with spaces')
    record = {'protocol': 1, 'project_root': str(profile.root), 'profile_id': profile.profile_id,
              'host': '0.0.0.0', 'port': 8020, 'token': 'a' * 32, 'secret': 'b' * 64, 'pid': 12345}
    client.write_record(profile, record)
    monkeypatch.setattr(client, '_process_exited', lambda pid: True, raising=False)
    state = {key: value for key, value in record.items() if key != 'secret'}
    state.update(busy=False, can_restart=True, reasons=[])
    return client, profile, record, state


def test_profile_scopes_process_management_to_exact_data_and_config(tmp_path, monkeypatch):
    from src.startup_identity import StartupProfile
    for key in ['DETERMINFLOW_DATA_DIR', 'DETERMINFLOW_CONFIG_DIR', 'AI_COMPANY_DATA_DIR', 'AI_COMPANY_CONFIG_DIR']:
        monkeypatch.delenv(key, raising=False)
    default = StartupProfile.from_root(tmp_path)
    monkeypatch.setenv('AI_COMPANY_DATA_DIR', 'alternate-data')
    alternate = StartupProfile.from_root(tmp_path)
    assert default.profile_id != alternate.profile_id
    assert alternate.data_dir == (tmp_path / 'alternate-data').resolve()
    monkeypatch.setenv('DETERMINFLOW_DATA_DIR', 'current-data')
    assert StartupProfile.from_root(tmp_path).data_dir == (tmp_path / 'current-data').resolve()


def test_busy_instance_is_preserved_without_restart_or_registry_mutation(instance, monkeypatch):
    client, profile, record, state = instance
    original = profile.record_file.read_bytes()
    calls = []
    def request(record, path, **kwargs):
        calls.append(path)
        return {**state, 'busy': True, 'can_restart': False, 'reasons': ['有工作流正在执行']}
    monkeypatch.setattr(client, '_request_json', request)
    monkeypatch.setattr(client, '_port_free', lambda *args: False)
    with pytest.raises(client.StartupNotice, match='工作流'):
        client.prepare_service_slot(profile, '0.0.0.0', 8020)
    assert calls == ['/api/startup-control']
    assert profile.record_file.read_bytes() == original


def test_idle_instance_is_rechecked_and_restarted_without_force_kill(instance, monkeypatch):
    client, profile, record, state = instance
    calls = []
    free = False
    def request(record, path, **kwargs):
        nonlocal free
        calls.append((path, kwargs))
        if path.endswith('restart'):
            free = True
            return {**state, 'status': 'restarting'}
        return state
    monkeypatch.setattr(client, '_request_json', request)
    monkeypatch.setattr(client, '_port_free', lambda *args: free)
    assert client.prepare_service_slot(profile, '0.0.0.0', 8020) is True
    assert [path for path, _ in calls] == ['/api/startup-control', '/api/startup-restart']
    assert calls[1][1]['body'] == {'token': record['token'], 'profile_id': profile.profile_id}


def test_port_release_does_not_skip_old_runtime_cleanup(instance, monkeypatch):
    client, profile, record, state = instance
    calls = []
    monkeypatch.setattr(client, '_request_json', lambda record, path, **kwargs:
                        state if path.endswith('control') else {**state, 'status': 'restarting'})
    monkeypatch.setattr(client, '_port_free', lambda *args: True)
    monkeypatch.setattr(client, '_process_exited', lambda pid: calls.append(pid) or len(calls) > 1)
    monkeypatch.setattr(client.time, 'sleep', lambda _: None)
    assert client.prepare_service_slot(profile, '0.0.0.0', 8020) is True
    assert len(calls) >= 2


@pytest.mark.parametrize('field,value', [('token', 'wrong'), ('profile_id', 'other'), ('pid', 54321), ('project_root', 'C:/other-project')])
def test_changed_or_foreign_identity_never_receives_stop(instance, monkeypatch, field, value):
    client, profile, record, state = instance
    calls = []
    monkeypatch.setattr(client, '_port_free', lambda *args: False)
    monkeypatch.setattr(client, '_request_json', lambda record, path, **kwargs: calls.append(path) or {**state, field: value})
    with pytest.raises(client.StartupNotice):
        client.prepare_service_slot(profile, '0.0.0.0', 8020)
    assert calls == ['/api/startup-control']


def test_task_started_after_idle_observation_blocks_restart(instance, monkeypatch):
    client, profile, record, state = instance
    monkeypatch.setattr(client, '_port_free', lambda *args: False)
    monkeypatch.setattr(client, '_request_json', lambda record, path, **kwargs:
                        state if path.endswith('control') else {'status': 'busy', 'reasons': ['聊天正在生成']})
    with pytest.raises(client.StartupNotice, match='聊天'):
        client.prepare_service_slot(profile, '0.0.0.0', 8020)


def test_prepare_only_does_not_restart_live_service(instance, monkeypatch):
    client, profile, record, state = instance
    calls = []
    monkeypatch.setattr(client, '_port_free', lambda *args: False)
    monkeypatch.setattr(client, '_request_json', lambda record, path, **kwargs: calls.append(path) or state)
    with pytest.raises(client.StartupNotice):
        client.prepare_service_slot(profile, '0.0.0.0', 8020, prepare_only=True)
    assert '/api/startup-restart' not in calls


@pytest.mark.parametrize('host', [None, 123, 'example.com', '192.168.1.2'])
def test_malformed_or_remote_registry_never_sends_control_secret(instance, monkeypatch, host):
    client, profile, record, state = instance
    record['host'] = host
    client.write_record(profile, record)
    monkeypatch.setattr(client, '_port_free', lambda *args: False)
    monkeypatch.setattr(client, '_request_json', lambda *args, **kwargs: pytest.fail('unvalidated registry contacted'))
    with pytest.raises(client.StartupNotice):
        client.prepare_service_slot(profile, '0.0.0.0', 8020)


def test_concurrent_launch_lock_is_nonblocking_and_released(instance):
    client, profile, record, state = instance
    with client.StartupLock(profile):
        with pytest.raises(client.StartupNotice, match='启动|重启'):
            with client.StartupLock(profile):
                pytest.fail('second startup was admitted')
    with client.StartupLock(profile):
        pass


def test_busy_launcher_checks_before_dependencies_assets_or_config(tmp_path, monkeypatch):
    import importlib.util
    from src import startup_instances, startup
    from setup_plugins import PluginManager
    path = Path(__file__).resolve().parents[1] / 'scripts/start_local.py'
    spec = importlib.util.spec_from_file_location('test_local_launcher', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    calls = []
    monkeypatch.setattr(startup, 'ensure_python_dependencies', lambda *args, **kwargs: calls.append('dependencies'))
    monkeypatch.setattr(startup, 'ensure_frontend', lambda *args, **kwargs: calls.append('frontend'))
    monkeypatch.setattr(PluginManager, 'check_and_install_required_plugins', lambda *args: calls.append('plugins'))
    def busy(*args, **kwargs):
        raise startup_instances.StartupNotice('有工作流正在执行')
    monkeypatch.setattr(startup_instances, 'prepare_service_slot', busy)
    with pytest.raises(startup_instances.StartupNotice, match='工作流'):
        module.run_startup(prepare_only=False, no_browser=True, log=None)
    assert calls == []
    assert not (tmp_path / '.env').exists()
    assert not (tmp_path / 'config').exists()
