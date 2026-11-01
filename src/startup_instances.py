"""Manage only an authenticated idle runtime of this exact local profile."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import (HTTPRedirectHandler, ProxyHandler, Request, build_opener)

from .startup_identity import StartupProfile


class StartupNotice(RuntimeError):
    """Expected, actionable startup pause; shown without a traceback."""


def _owned_path(profile, path):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(profile.root):
        raise StartupNotice('启动记录路径不在本项目内，已保留现有服务，请检查 logs 目录。')
    return path


class StartupLock:
    def __init__(self, profile):
        self.profile, self.handle = profile, None

    def __enter__(self):
        path = _owned_path(self.profile, self.profile.lock_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open('a+b')
        try:
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise StartupNotice('本项目正在启动或重启，请稍候；本次双击没有创建第二个服务。') from error
        self.handle = handle
        return self

    def release(self):
        handle, self.handle = self.handle, None
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def __exit__(self, *args):
        self.release()


def write_record(profile, record):
    path = _owned_path(profile, profile.record_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.startup-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(record, handle)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_record(profile):
    path = _owned_path(profile, profile.record_file)
    try:
        if path.stat().st_size > 16384:
            return None
        record = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(record, dict) or record.get('protocol') != 1
                or not isinstance(record.get('host'), str)
                or record.get('profile_id') != profile.profile_id
                or Path(record.get('project_root', '')).resolve() != profile.root
                or not isinstance(record.get('pid'), int) or isinstance(record['pid'], bool) or record['pid'] <= 0
                or not isinstance(record.get('port'), int) or isinstance(record['port'], bool) or not 1 <= record['port'] <= 65535
                or not all(isinstance(record.get(key), str) and len(record[key]) >= 16 for key in ('token', 'secret'))):
            return None
        _local_host(record['host'])
        return record
    except (OSError, ValueError, TypeError, StartupNotice):
        return None


def cleanup_record(profile, token):
    record = read_record(profile)
    if record and record.get('token') == token:
        _owned_path(profile, profile.record_file).unlink(missing_ok=True)
    # The guard path is unique to this launch. Never clear another instance's gate.
    _owned_path(profile, profile.guard_file(token)).unlink(missing_ok=True)


def _port_free(host, port):
    from .startup import ensure_port_available
    try:
        ensure_port_available(host, port)
        return True
    except RuntimeError:
        return False


def _process_exited(pid):
    """Read-only liveness proof. Access failures never authorize a restart."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: no such PID
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except (OSError, PermissionError):
        return False


def _local_host(host):
    if host in ('0.0.0.0', '', 'localhost'):
        return '127.0.0.1'
    if host == '::':
        return '::1'
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise StartupNotice('自动重启仅管理本机回环地址上的服务；现有服务已保留，请检查 WEB_HOST。')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request_json(record, path, *, body=None):
    host = _local_host(record['host'])
    address = f'[{host}]' if ':' in host else host
    request = Request(f'http://{address}:{record["port"]}{path}',
                      data=json.dumps(body).encode('utf-8') if body is not None else None,
                      headers={'X-DeterminFlow-Control': record['secret'], 'Content-Type': 'application/json'})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        response = opener.open(request, timeout=30)
    except HTTPError as error:
        if error.code != 409:
            raise
        response = error
    with response:
        raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError('oversized control response')
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('invalid control response')
    return data


def _verified(profile, record, state):
    try:
        same_root = isinstance(state.get('project_root'), str) and Path(state['project_root']).resolve() == profile.root
    except (OSError, ValueError):
        same_root = False
    return (state.get('protocol') == 1 and same_root
            and state.get('profile_id') == profile.profile_id and state.get('token') == record['token']
            and state.get('pid') == record['pid'] and isinstance(state.get('busy'), bool)
            and isinstance(state.get('can_restart'), bool)
            and isinstance(state.get('reasons'), list) and all(isinstance(item, str) for item in state['reasons']))


def _busy_notice(state):
    reasons = state.get('reasons') or ['服务正在处理任务或暂时无法可靠确认任务状态']
    reasons = [reason.rstrip('。；; \t') for reason in reasons]
    return StartupNotice('本项目原服务已保留，没有重启：' + '；'.join(reasons) + '。请等任务完成后再次双击。')


def prepare_service_slot(profile, host, port, *, prepare_only=False, timeout=45):
    """Return whether an idle incumbent was stopped, or pause without mutations."""
    record = read_record(profile)
    if record is None:
        if _port_free(host, port):
            return False
        raise StartupNotice(f'端口 {port} 已有服务，但无法安全确认它的项目归属和任务状态，原服务已保留。'
                            '若是本项目旧版启动窗口，请先按 Ctrl+C 退出一次，再重新双击；新版后续会自动处理。')
    try:
        state = _request_json(record, '/api/startup-control')
    except (OSError, ValueError, StartupNotice) as error:
        if _port_free(record['host'], record['port']) and _port_free(host, port) and _process_exited(record['pid']):
            return False
        raise StartupNotice('检测到已有服务，但无法确认安全重启条件，已保留原服务。'
                            '旧版服务请先在原启动窗口按 Ctrl+C 退出一次，再重新双击。') from error
    if not _verified(profile, record, state):
        raise StartupNotice('当前服务身份与本项目启动记录不一致，已保留服务；请检查旧启动窗口或端口设置。')
    if state['busy'] or not state['can_restart']:
        raise _busy_notice(state)
    if prepare_only:
        raise StartupNotice('本项目服务仍在运行，准备模式不会关闭它。请先退出原服务，或正常双击启动器进行空闲重启。')
    print(f'检测到本项目空闲服务（PID {record["pid"]}），正在正常重启以加载最新代码…', flush=True)
    try:
        result = _request_json(record, '/api/startup-restart', body={'token': record['token'], 'profile_id': profile.profile_id})
    except (OSError, ValueError, StartupNotice) as error:
        raise StartupNotice('重启请求未得到确认，未强制结束任何进程。请稍后再次双击查看服务状态。') from error
    if result.get('status') == 'busy':
        raise _busy_notice(result)
    if (result.get('status') != 'restarting' or result.get('token') != record['token']
            or result.get('profile_id') != profile.profile_id):
        raise StartupNotice('服务未确认本次安全重启请求，已保留进程，请稍后重试。')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_free(record['host'], record['port']) and _port_free(host, port) and _process_exited(record['pid']):
            return True
        time.sleep(0.1)
    raise StartupNotice('旧服务正在正常关闭，端口尚未释放；本次没有强制终止进程，请稍后再次双击。')
