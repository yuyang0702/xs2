"""Private JSONL worker. Credentials and SDK objects never cross the process boundary."""
import asyncio
import contextlib
import json
import sys
from src.core.request_llm import PREFIX


def safe_error(exc):
    chain = []
    seen = set()
    current = exc
    status = None
    connection = False
    timeout = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(type(current).__name__)
        connection = connection or isinstance(current, ConnectionError)
        timeout = timeout or isinstance(current, TimeoutError)
        candidate = getattr(current, 'status_code', None)
        if isinstance(candidate, int):
            status = candidate
        current = current.__cause__ or current.__context__
    names = ' '.join(chain).lower()
    kind = 'authentication' if status in (401, 403) else 'timeout' if timeout or 'timeout' in names else 'connection' if connection or any(x in names for x in ('connection', 'connecterror', 'ssl', 'endofstream')) else 'provider'
    return {'type': 'error', 'kind': kind, 'status_code': status, 'diagnostics': {'types': chain[:12]}}


async def run(request, emit):
    from scripts.start_local import load_startup_environment
    load_startup_environment()
    from src.core.llm_client import create_llm
    from langchain_core.messages import messages_from_dict
    model = create_llm(**request['options'])
    metadata = getattr(model, 'metadata', None) or {}
    emit({'type': 'start', 'model_name': getattr(model, 'model_name', getattr(model, 'model', '')), 'metadata': {'determinflow_model_id': metadata.get('determinflow_model_id', '')}})
    async for chunk in model.astream(messages_from_dict(request['messages']), **request.get('invoke', {})):
        content = getattr(chunk, 'content', '')
        if content:
            emit({'type': 'chunk', 'content': content})
    emit({'type': 'end'})


def main():
    output = sys.stdout
    def emit(frame):
        output.write(PREFIX.decode() + json.dumps(frame, ensure_ascii=True) + '\n')
        output.flush()
    # All imports/startup/SDK chatter are diverted away from the protocol pipe.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            request = json.loads(sys.stdin.buffer.readline())
            asyncio.run(run(request, emit))
        except BaseException as exc:
            emit(safe_error(exc))


if __name__ == '__main__':
    main()
