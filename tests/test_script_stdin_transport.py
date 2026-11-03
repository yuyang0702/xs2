from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from pathlib import Path

import pytest

import src.config as config
import src.workflow.nodes.script as script_module
from src.workflow.definition import NodeExecutionState, WorkflowDef, WorkflowNode
from src.workflow.nodes.base import NodeContext
from src.workflow.nodes.script import ScriptNode


def script_context(tmp_path, monkeypatch, *, values=None, params=None, body=None):
    workflow_id = "wf-stdin-transport"
    script_dir = tmp_path / "workflows" / workflow_id / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "capture.py").write_text(
        body or (
            "import hashlib, sys\n"
            "from pathlib import Path\n"
            "payload = sys.stdin.buffer.read()\n"
            "Path('received.bin').write_bytes(payload)\n"
            "print('<script_out>' + hashlib.sha256(payload).hexdigest() + '</script_out>')\n"
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(config, "WORKFLOWS_DIR", tmp_path / "workflows")
    node_params = {"script_type": "python", "script_name": "capture"}
    node_params.update(params or {})
    node = WorkflowNode(id="capture", node_type="script", node_params=node_params)
    return NodeContext(
        definition=WorkflowDef(workflow_id=workflow_id, nodes=[node]),
        node_def=node,
        node_state=NodeExecutionState(node_id=node.id),
        shared_ws=workspace,
        parameter_values=values or {},
        workflow_id=workflow_id,
        task_id="task-stdin-transport",
    )


def observe_launch(monkeypatch):
    original = asyncio.create_subprocess_exec
    launches = []

    async def launch(*args, **kwargs):
        if args[0] != "taskkill":
            stdin = kwargs.get("stdin")
            launches.append((args, kwargs, stdin))
            if stdin is not None:
                assert not stdin.closed
                assert stat.S_ISREG(os.fstat(stdin.fileno()).st_mode)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    return launches


@pytest.mark.parametrize("payload", [
    '  中文 “quoted” \'single\' "double"\r\nnext\n{{unchanged}} 😀  ',
    '中文 "large"\n' * 12000,
    "",
    "界" * (8 * 1024 * 1024 // 3) + "ab",
], ids=["unicode-quotes-newlines", "beyond-windows-argv", "empty", "eight-mib-boundary"])
def test_selected_string_reaches_real_child_exactly(tmp_path, monkeypatch, caplog, payload):
    ctx = script_context(tmp_path, monkeypatch,
                         values={"payload": payload},
                         params={"script_stdin_variable": "payload"})
    launches = observe_launch(monkeypatch)

    result = asyncio.run(ScriptNode().execute(ctx))

    expected = payload.encode("utf-8")
    assert result.status == "success"
    assert (ctx.shared_ws / "received.bin").read_bytes() == expected
    assert result.summary == hashlib.sha256(expected).hexdigest()
    assert launches[0][2] is not None
    assert launches[0][2].closed
    if payload:
        assert payload not in caplog.text


@pytest.mark.parametrize(("value", "expected"), [
    ({"z": [True, None, "中\n文"], "a": {"x": 2}},
     b'{"a":{"x":2},"z":[true,null,"\xe4\xb8\xad\\n\xe6\x96\x87"]}'),
    ([1, False, None], b'[1,false,null]'),
    (None, b'null'),
    (False, b'false'),
    (2.5, b'2.5'),
])
def test_json_values_are_deterministically_serialized(tmp_path, monkeypatch, value, expected):
    ctx = script_context(tmp_path, monkeypatch,
                         values={"selected": value},
                         params={"script_stdin_variable": "selected"})

    result = asyncio.run(ScriptNode().execute(ctx))

    assert result.status == "success"
    assert (ctx.shared_ws / "received.bin").read_bytes() == expected


@pytest.mark.parametrize("selector", ["missing", "{{payload}}", " payload ", "", None, 7, []])
def test_selector_requires_an_exact_existing_variable_before_launch(tmp_path, monkeypatch, selector):
    ctx = script_context(tmp_path, monkeypatch,
                         values={"payload": "secret payload"},
                         params={"script_stdin_variable": selector})

    result = asyncio.run(ScriptNode().execute(ctx))

    assert result.status == "failed"
    assert "script_stdin_variable" in result.error
    assert not (ctx.shared_ws / "received.bin").exists()
    assert "secret payload" not in result.error


@pytest.mark.parametrize("value", [
    b"secret payload", {"bad": object()}, {1: "secret payload"},
    ("secret payload",), float("nan"), float("inf"), "\ud800",
    "界" * (8 * 1024 * 1024 // 3 + 1),
], ids=["bytes", "object", "nonstring-key", "tuple", "nan", "infinity", "surrogate", "over-eight-mib"])
def test_invalid_or_oversize_values_fail_before_launch(tmp_path, monkeypatch, value):
    ctx = script_context(tmp_path, monkeypatch,
                         values={"selected": value},
                         params={"script_stdin_variable": "selected"})

    result = asyncio.run(ScriptNode().execute(ctx))

    assert result.status == "failed"
    assert "script_stdin_variable" in result.error
    assert not (ctx.shared_ws / "received.bin").exists()
    assert "secret payload" not in result.error


def test_launch_failure_closes_spooled_stdin(tmp_path, monkeypatch):
    ctx = script_context(tmp_path, monkeypatch, values={"selected": "payload"},
                         params={"script_stdin_variable": "selected"})
    streams = []

    async def fail_launch(*args, **kwargs):
        streams.append(kwargs.get("stdin"))
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_launch)
    with pytest.raises(OSError, match="synthetic launch failure"):
        asyncio.run(ScriptNode().execute(ctx))

    assert streams[0] is not None
    assert streams[0].closed


@pytest.mark.parametrize("completion", ["cancel", "timeout"])
def test_stdin_closes_after_real_process_cleanup(tmp_path, monkeypatch, completion):
    ctx = script_context(
        tmp_path, monkeypatch, values={"selected": "payload"},
        params={"script_stdin_variable": "selected", "timeout": "1"},
        body="import time\nfrom pathlib import Path\nPath('ready').touch()\ntime.sleep(60)\n",
    )
    launches = observe_launch(monkeypatch)
    original = script_module._terminate_process_tree
    cleaned = []

    async def terminate(process):
        stream = launches[0][2]
        was_open = stream is not None and not stream.closed
        await original(process)
        assert process.returncode is not None
        assert was_open and not stream.closed
        cleaned.append(process.pid)

    monkeypatch.setattr(script_module, "_terminate_process_tree", terminate)

    async def scenario():
        execution = asyncio.create_task(ScriptNode().execute(ctx))
        if completion == "cancel":
            for _ in range(500):
                if (ctx.shared_ws / "ready").exists():
                    break
                await asyncio.sleep(0.01)
            assert (ctx.shared_ws / "ready").exists()
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        else:
            result = await execution
            assert result.status == "failed"
            assert "超时" in result.error

    asyncio.run(scenario())
    assert len(cleaned) == 1
    assert launches[0][2].closed


def test_no_stdin_option_preserves_subprocess_arguments(tmp_path, monkeypatch):
    ctx = script_context(tmp_path, monkeypatch, body="print('legacy')\n",
                         params={"script_args": "--old value"})
    launches = observe_launch(monkeypatch)

    result = asyncio.run(ScriptNode().execute(ctx))

    assert result.status == "success"
    args, kwargs, stdin = launches[0]
    assert args[-2:] == ("--old", "value")
    assert stdin is None
    assert "stdin" not in kwargs
    assert set(kwargs) in (
        {"stdout", "stderr", "cwd", "env", "creationflags"},
        {"stdout", "stderr", "cwd", "env", "start_new_session"},
        {"stdout", "stderr", "cwd", "env"},
    )
