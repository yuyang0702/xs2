"""Opt-in chat transport whose SDK and connections live in a request child."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from langchain_core.messages import AIMessage, AIMessageChunk, messages_to_dict, convert_to_messages

PREFIX = b'DFLLM1:'
ROOT = Path(__file__).resolve().parents[2]


class RequestModelError(RuntimeError):
    def __init__(self, kind='protocol', status_code=None):
        self.status_code = status_code if isinstance(status_code, int) else None
        self.provider_diagnostics = {}
        self.kind = kind if kind in {'connection', 'timeout', 'authentication', 'provider', 'protocol'} else 'provider'
        super().__init__(f'Model request {self.kind} failure' + (f' (HTTP {self.status_code})' if self.status_code else ''))


class RequestConnectionError(RequestModelError, ConnectionError):
    pass


class RequestModel:
    def __init__(self, options, command=None):
        self._options = options
        self._command = command or [sys.executable, '-m', 'src.core.request_llm_worker']
        timeout = options.get('timeout', 600)
        self._deadline = float(timeout) if isinstance(timeout, (int, float)) else 600.0
        self.model_name = options.get('model_override') or options.get('model') or ''
        self.metadata = {}
        self._processes = set()
        self._closed = False

    async def astream(self, messages, **kwargs):
        if self._closed:
            raise RequestModelError()
        if isinstance(messages, str):
            from langchain_core.messages import HumanMessage
            messages = [HumanMessage(content=messages)]
        if set(kwargs) - {'stop'}:
            raise ValueError('Unsupported isolated invocation option')
        request = json.dumps({'options': self._options, 'messages': messages_to_dict(convert_to_messages(messages)), 'invoke': kwargs}, ensure_ascii=False).encode('utf8') + b'\n'
        process = await asyncio.create_subprocess_exec(
            *self._command, cwd=str(ROOT), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
        self._processes.add(process)
        try:
            if self._closed:
                raise RequestModelError()
            async with asyncio.timeout(self._deadline):
                process.stdin.write(request)
                await process.stdin.drain()
                process.stdin.close()
                started = False
                noise = 0
                while True:
                    try:
                        line = await process.stdout.readline()
                    except (ValueError, UnicodeError):
                        raise RequestModelError() from None
                    if not line:
                        raise RequestModelError()
                    if not line.startswith(PREFIX):
                        noise += len(line)
                        if noise > 65536:
                            raise RequestModelError()
                        continue
                    try:
                        frame = json.loads(line[len(PREFIX):])
                    except (ValueError, UnicodeError):
                        raise RequestModelError() from None
                    if not isinstance(frame, dict):
                        raise RequestModelError()
                    kind = frame.get('type')
                    if kind == 'start' and not started:
                        started = True
                        name = frame.get('model_name', '')
                        metadata = frame.get('metadata', {})
                        if not isinstance(name, str) or not isinstance(metadata, dict):
                            raise RequestModelError()
                        resolved = metadata.get('determinflow_model_id', '')
                        if not isinstance(resolved, str):
                            raise RequestModelError()
                        self.metadata = {'determinflow_model_id': resolved}
                        self.model_name = resolved or name
                    elif kind == 'chunk' and started and isinstance(frame.get('content'), (str, list)):
                        yield AIMessageChunk(content=frame['content'])
                    elif kind == 'end' and started:
                        if await process.wait() != 0:
                            raise RequestModelError()
                        return
                    elif kind == 'error':
                        if frame.get('kind') == 'timeout':
                            raise TimeoutError('Model request timed out')
                        error_class = RequestConnectionError if frame.get('kind') == 'connection' else RequestModelError
                        error = error_class(frame.get('kind'), frame.get('status_code'))
                        diagnostic = frame.get('diagnostics') or {}
                        if isinstance(diagnostic, dict):
                            import re
                            names = diagnostic.get('types', [])
                            if isinstance(names, list):
                                error.provider_diagnostics = {'types': [n for n in names[:12] if isinstance(n, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', n)]}
                        raise error
                    else:
                        raise RequestModelError()
        finally:
            await self._stop(process)

    async def _stop(self, process):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        self._processes.discard(process)

    async def ainvoke(self, messages, **kwargs):
        result = None
        async for chunk in self.astream(messages, **kwargs):
            result = chunk if result is None else result + chunk
        return AIMessage(content=result.content if result is not None else '')

    async def aclose(self):
        self._closed = True
        await asyncio.gather(*(self._stop(p) for p in tuple(self._processes)))


def create_request_llm(*, _worker_command=None, **kwargs):
    if set(kwargs) - {'model_override', 'model', 'timeout', 'model_params', 'streaming', 'provider_retries_enabled'}:
        raise ValueError('Unsupported isolated model option')
    params = kwargs.get('model_params')
    if params is not None and (not isinstance(params, dict) or set(params) - {'thinking_enabled', 'reasoning_effort', 'temperature', 'top_p', 'max_tokens'}):
        raise ValueError('Unsupported isolated model parameter')
    return RequestModel(kwargs, _worker_command)
