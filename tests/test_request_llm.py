import asyncio
import sys
from pathlib import Path
import pytest
import functools
def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper
from src.core.request_llm import create_request_llm, RequestModelError

@run_async
async def test_fake_worker_stream_and_invoke(tmp_path):
    worker = tmp_path / 'worker.py'
    worker.write_text('import sys,json\nr=json.loads(sys.stdin.readline())\nprint("noise")\nprint("DFLLM1:"+json.dumps({"type":"start","model_name":"real","metadata":{"determinflow_model_id":"p:real"}}))\nprint("DFLLM1:"+json.dumps({"type":"chunk","content":"hello"}))\nprint("DFLLM1:"+json.dumps({"type":"end"}))\n', encoding='utf8')
    model = create_request_llm(model_override='p:alias', _worker_command=[sys.executable, str(worker)])
    assert (await model.ainvoke('secret prompt')).content == 'hello'
    assert model.model_name == 'p:real'
    assert model.metadata['determinflow_model_id'] == 'p:real'
    await model.aclose()
    await model.aclose()

@run_async
@pytest.mark.parametrize('body', [
    'print("DFLLM1:"+json.dumps({"type":"error","kind":"connection","status_code":None}))',
    'print("DFLLM1:invalid")',
    'sys.exit(3)',
])
async def test_worker_failures(tmp_path, body):
    worker = tmp_path / 'worker.py'
    worker.write_text('import sys,json\nsys.stdin.readline()\n'+body, encoding='utf8')
    model = create_request_llm(_worker_command=[sys.executable, str(worker)])
    with pytest.raises(RequestModelError) as caught:
        await model.ainvoke('secret prompt')
    assert 'secret' not in str(caught.value)
    assert not model._processes

@run_async
async def test_timeout_and_cancel_cleanup(tmp_path):
    worker = tmp_path / 'worker.py'
    worker.write_text('import sys,time\nsys.stdin.readline()\nprint("chatter",file=sys.stderr,flush=True)\ntime.sleep(60)', encoding='utf8')
    model = create_request_llm(timeout=.15, _worker_command=[sys.executable, str(worker)])
    with pytest.raises(TimeoutError):
        await model.ainvoke('private')
    assert not model._processes
    model._deadline = 60
    task = asyncio.create_task(model.ainvoke('private'))
    await asyncio.sleep(.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not model._processes


@run_async
async def test_early_close_and_stderr_chatter(tmp_path):
    worker = tmp_path / 'worker.py'
    worker.write_text('import sys,json,time\nsys.stdin.readline()\nprint("x"*200000,file=sys.stderr,flush=True)\nprint("DFLLM1:"+json.dumps({"type":"start"}),flush=True)\nprint("DFLLM1:"+json.dumps({"type":"chunk","content":"ok"}),flush=True)\ntime.sleep(60)', encoding='utf8')
    model = create_request_llm(_worker_command=[sys.executable, str(worker)])
    stream = model.astream('private')
    assert (await anext(stream)).content == 'ok'
    await stream.aclose()
    assert not model._processes


def test_worker_error_redaction():
    from src.core.request_llm_worker import safe_error
    class AuthError(Exception):
        status_code = 401
    frame = safe_error(AuthError('secret key and private prompt'))
    assert frame['status_code'] == 401
    assert frame['kind'] == 'authentication'
    assert 'secret' not in str(frame)


@run_async
async def test_real_worker_contract(monkeypatch):
    import scripts.start_local
    import src.core.llm_client
    from src.core.request_llm_worker import run
    from langchain_core.messages import HumanMessage, AIMessageChunk, messages_to_dict
    order = []
    monkeypatch.setattr(scripts.start_local, 'load_startup_environment', lambda: order.append('startup'))
    class Model:
        metadata = {'determinflow_model_id': 'provider:actual'}
        model_name = 'actual'
        async def astream(self, messages, **kwargs):
            assert order == ['startup', 'factory']
            assert messages[0].content == 'prompt'
            yield AIMessageChunk(content='answer', additional_kwargs={'reasoning_content': 'private reasoning'})
    def factory(**kwargs):
        order.append('factory')
        return Model()
    monkeypatch.setattr(src.core.llm_client, 'create_llm', factory)
    frames = []
    await run({'options': {}, 'messages': messages_to_dict([HumanMessage(content='prompt')])}, frames.append)
    assert [f['type'] for f in frames] == ['start', 'chunk', 'end']
    assert frames[1] == {'type': 'chunk', 'content': 'answer'}
    assert 'prompt' not in str(frames)
    assert 'reasoning' not in str(frames)


@run_async
async def test_plugin_tuple_trajectory(tmp_path):
    from langchain_core.messages import AIMessage
    worker = tmp_path / 'worker.py'
    worker.write_text('''import sys,json
r=json.loads(sys.stdin.readline())
assert [m["type"] for m in r["messages"]]==["system","human","ai","human"]
print('DFLLM1:{"type":"start"}')
print('DFLLM1:{"type":"end"}')''',encoding='utf8')
    model=create_request_llm(_worker_command=[sys.executable,str(worker)])
    await model.ainvoke([('system','rules'),('human','draft'),AIMessage(content='answer'),('human','correct')])


def test_error_hierarchy_and_option_credentials():
    from src.core.request_llm_worker import safe_error
    assert safe_error(BrokenPipeError('private'))['kind']=='connection'
    outer=RuntimeError('private')
    outer.__cause__=TimeoutError('private')
    assert safe_error(outer)['kind']=='timeout'
    with pytest.raises(ValueError):
        create_request_llm(api_key='private')


@run_async
async def test_malformed_start_metadata(tmp_path):
    worker=tmp_path/'worker.py'
    worker.write_text('''import sys
sys.stdin.readline()
print('DFLLM1:{"type":"start","metadata":["bad"]}')''',encoding='utf8')
    with pytest.raises(RequestModelError):
        await create_request_llm(_worker_command=[sys.executable,str(worker)]).ainvoke('private')
