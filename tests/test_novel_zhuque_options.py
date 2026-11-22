import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import config
from src.core.workspace_manager import WorkspaceManager
from src.web import novel_routes


@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    root = tmp_path / "data/workspaces/books/这本书"
    app = FastAPI()
    app.state.workflow_manager = SimpleNamespace(
        _ws_manager=WorkspaceManager(str(tmp_path / "data/workspaces")),
        get_workflow_owner=lambda _: "xs2-novel-flywheel",
        is_workflow_owner_enabled=lambda _: True,
        get_workflow_execution_policy=lambda _: "public",
    )
    app.include_router(novel_routes.router)
    return TestClient(app), root, {"workflow_id": "custom-build", "workspace": str(root)}


URL = "/api/novel-console/zhuque-options"


def test_default_and_saved_options_are_per_book_and_can_be_cleared(console):
    client, root, params = console
    default = {"enabled": False, "reference_text": ""}
    assert client.get(URL, params=params).json() == default
    assert not root.exists()
    selected = {"enabled": True, "reference_text": "工号 017。\n\n她收起钥匙。"}
    assert client.patch(URL, json={**params, **selected}).json() == selected
    assert json.loads((root / "zhuque-options.json").read_text(encoding="utf-8")) == selected
    assert client.get(URL, params=params).json() == selected
    assert client.get(URL, params={**params, "workspace": str(root.parent / "另一本")}).json() == default
    assert client.patch(URL, json={**params, "enabled": False}).json() == {**selected, "enabled": False}
    # A stale tab editing the manuscript must never re-enable paid detection.
    assert client.patch(URL, json={**params, "reference_text": "新段落"}).json() == {
        "enabled": False, "reference_text": "新段落",
    }
    assert client.patch(URL, json={**params, **default}).json() == default
    assert client.get(URL, params=params).json() == default


def test_invalid_reference_or_workspace_cannot_overwrite_preferences(console):
    client, root, params = console
    options = {"enabled": True, "reference_text": "参考"}
    assert client.patch(URL, json={**params, **options}).status_code == 200
    for invalid in ({"enabled": "false"}, {"reference_text": "正文\x00"}, {"reference_text": ["段落"]}):
        assert client.patch(URL, json={**params, **options, **invalid}).status_code == 422
    assert client.patch(URL, json={**params, **options, "workspace": "../escape"}).status_code == 400
    assert client.get(URL, params=params).json() == options
