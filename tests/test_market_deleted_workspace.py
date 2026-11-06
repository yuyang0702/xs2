import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import src.config as config
from src.core.workspace_manager import WorkspaceManager
from src.web import workflow_routes


def manager_for(monkeypatch, tmp_path, override):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    manager = SimpleNamespace(
        _ws_manager=WorkspaceManager(str(tmp_path / "workspaces")),
        _load_task=lambda workflow_id, task_id: SimpleNamespace(workspace_override=override),
    )
    monkeypatch.setattr(workflow_routes, "_get_manager", lambda request: manager)
    return manager


@pytest.mark.parametrize("override", [True, False])
def test_reading_a_deleted_snapshot_never_recreates_its_workspace(monkeypatch, tmp_path, override):
    deleted = tmp_path / "books/deleted-book" if override else tmp_path / "workspaces/market"
    manager_for(monkeypatch, tmp_path, str(deleted) if override else None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(workflow_routes.get_task_workspace_file("market", "old", None, "market/zhihu-ranking.json"))
    assert error.value.status_code == 404
    assert not deleted.exists()


def test_existing_market_snapshots_remain_readable(monkeypatch, tmp_path):
    workspace = tmp_path / "market-data"
    manager_for(monkeypatch, tmp_path, str(workspace))
    file = workspace / "market/zhihu-ranking.json"
    file.parent.mkdir(parents=True)
    file.write_text('{"works":["公开榜单"]}', encoding="utf-8")
    result = asyncio.run(workflow_routes.get_task_workspace_file("market", "old", None, "market/zhihu-ranking.json"))
    assert result["content"] == '{"works":["公开榜单"]}'
