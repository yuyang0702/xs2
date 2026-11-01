import hashlib
import json
from copy import deepcopy

from src.extension_api.registrar import OwnedPath
from src.extension_host.workflow_provisioning import provision_plugin_workflows
from src.workflow.definition import WorkflowDef
from src.workflow.manager import WorkflowManager


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path):
    source = tmp_path / "source" / "custom-pipeline" / "definition.json"
    target = tmp_path / "workflows" / "custom-pipeline" / "definition.json"
    base = {"workflow_id": "custom-pipeline", "name": "Pipeline", "nodes": [
        {"id": "writer", "agent_type": "writer", "model_override": "p:default"}], "edges": []}
    write(source, base)
    roots = [OwnedPath("novel-owner", source.parent.parent)]
    def sync(**kwargs):
        return provision_plugin_workflows(roots, target.parent.parent, active_owners={"novel-owner"}, **kwargs)
    sync()
    return source, target, base, sync


def test_model_only_legacy_edit_upgrades_nodes_and_keeps_backup(tmp_path):
    source, target, base, sync = fixture(tmp_path)
    edited = WorkflowDef.from_dict(base).to_dict()
    edited["version"] = 6
    edited["nodes"][0]["model_override"] = "p:mine"
    write(target, edited)
    before = target.read_bytes()
    upstream = deepcopy(base)
    upstream["nodes"].append({"id": "new-check", "agent_type": "checker"})
    write(source, upstream)
    assert sync() == []
    assert json.loads(target.read_text()) == upstream
    assert json.loads((target.parent / ".user-models.json").read_text())["node_models"] == {"writer": "p:mine"}
    assert any(path.read_bytes() == before for path in (target.parent / ".upgrade-backups").glob("*/definition.json"))


def test_unknown_definition_edit_and_script_edit_are_preserved_and_reported(tmp_path):
    source, target, base, sync = fixture(tmp_path)
    source_script = source.parent / "script" / "run.py"
    source_script.parent.mkdir()
    source_script.write_text("old")
    sync()
    target_script = target.parent / "script" / "run.py"
    target_script.write_text("user logic")
    source_script.write_text("new logic")
    base["unknown_user_setting"] = {"important": True}
    write(target, base)
    original = target.read_bytes()
    warnings = sync()
    assert target.read_bytes() == original
    assert target_script.read_text() == "user logic"
    assert any("definition.json" in warning for warning in warnings)
    assert any("script/run.py" in warning for warning in warnings)
    assert json.loads((target.parent / ".extension.json").read_text())["conflicts"]


def test_untrusted_legacy_base_cannot_authorize_upgrade(tmp_path):
    source, target, base, sync = fixture(tmp_path)
    (target.parent / ".extension-base.json").unlink()
    base["nodes"][0]["first_message"] = "local prompt"
    write(target, base)
    fake_base = tmp_path / "fake.json"
    write(fake_base, base)
    before = target.read_bytes()
    assert sync(legacy_bases={"custom-pipeline": fake_base})
    assert target.read_bytes() == before


def test_hash_verified_legacy_base_supports_old_installation(tmp_path):
    source, target, base, sync = fixture(tmp_path)
    legacy = tmp_path / "trusted.json"
    legacy.write_bytes(target.read_bytes())
    (target.parent / ".extension-base.json").unlink()
    base["nodes"][0]["model_override"] = "p:mine"
    write(target, base)
    assert sync(legacy_bases={"custom-pipeline": legacy}) == []
    assert json.loads((target.parent / ".user-models.json").read_text())["node_models"]["writer"] == "p:mine"


def test_manager_model_choices_do_not_edit_template_or_task_snapshots(tmp_path, monkeypatch):
    source, target, base, sync = fixture(tmp_path)
    monkeypatch.setattr("src.workflow.manager.WORKFLOWS_DIR", target.parent.parent)
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._extension_manager = None
    snapshot = target.parent / "tasks" / "old.json"
    write(snapshot, {"definition_snapshot": base})
    before, task_before = target.read_bytes(), snapshot.read_bytes()
    current = manager.get_workflow("custom-pipeline")["definition"]
    saved = manager.save_workflow_model_overrides("custom-pipeline", {"writer": "p:mine"}, expected_definition=current)
    assert saved["definition"]["nodes"][0]["model_override"] == "p:mine"
    assert target.read_bytes() == before
    assert snapshot.read_bytes() == task_before
    assert manager.get_workflow_owner("custom-pipeline") == "novel-owner"
    base["nodes"].append({"id": "new-node", "agent_type": "checker"})
    write(source, base)
    sync()
    assert len(manager.get_workflow("custom-pipeline")["definition"]["nodes"]) == 2
    assert manager.get_workflow_model_overrides("custom-pipeline") == {"writer": "p:mine"}
    assert manager.save_workflow_model_overrides("custom-pipeline", {"writer": "p:default"}, expected_definition=current) is None
    assert snapshot.read_bytes() == task_before


def test_explicit_three_way_upgrade_keeps_local_prompts_and_adds_upstream_graph(tmp_path):
    from src.extension_host.workflow_upgrade import plan_reviewed_upgrade, apply_reviewed_upgrade
    source, target, base, sync = fixture(tmp_path)
    base["nodes"][0]["first_message"] = "original"
    write(source, base)
    sync()
    local = deepcopy(base)
    local["nodes"][0]["first_message"] = "my prompt"
    local["nodes"][0]["model_override"] = "p:mine"
    local["custom_setting"] = {"keep": True}
    write(target, local)
    upstream = deepcopy(base)
    upstream["nodes"].append({"id": "smart-context", "node_type": "script"})
    upstream["edges"] = [{"id": "e1", "source": "smart-context", "target": "writer"}]
    write(source, upstream)
    original = target.read_bytes()
    plan = plan_reviewed_upgrade(target, source, base)
    assert plan["conflicts"] == []
    apply_reviewed_upgrade(target, source, plan)
    result = json.loads(target.read_text())
    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["first_message"] == "my prompt"
    assert result["custom_setting"] == {"keep": True}
    assert result["nodes"][0]["model_override"] == "p:default"
    assert json.loads((target.parent / ".user-models.json").read_text())["node_models"]["writer"] == "p:mine"
    assert any(p.read_bytes() == original for p in (target.parent / ".upgrade-backups").glob("*/definition.json"))


def test_explicit_upgrade_reports_competing_prompt_edit_and_rejects_stale_plan(tmp_path):
    import pytest
    from src.extension_host.workflow_upgrade import plan_reviewed_upgrade, apply_reviewed_upgrade
    source, target, base, sync = fixture(tmp_path)
    local = deepcopy(base)
    local["nodes"][0]["first_message"] = "mine"
    write(target, local)
    upstream = deepcopy(base)
    upstream["nodes"][0]["first_message"] = "plugin"
    write(source, upstream)
    plan = plan_reviewed_upgrade(target, source, base)
    assert plan["conflicts"] == ["/nodes/writer/first_message"]
    before = target.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        apply_reviewed_upgrade(target, source, plan)
    assert target.read_bytes() == before
    plan = plan_reviewed_upgrade(target, source, base, resolutions={"/nodes/writer/first_message": "local"})
    local["name"] = "changed after review"
    write(target, local)
    with pytest.raises(ValueError, match="changed"):
        apply_reviewed_upgrade(target, source, plan)


def test_reviewed_upgrade_matches_regenerated_edge_ids_without_duplicate_routes(tmp_path):
    from src.extension_host.workflow_upgrade import plan_reviewed_upgrade
    source, target, base, sync = fixture(tmp_path)
    base["edges"] = [{"id": "old", "source": "start", "target": "writer"}]
    local = deepcopy(base)
    local["edges"][0]["id"] = "editor-generated"
    write(target, local)
    upstream = deepcopy(base)
    upstream["edges"][0]["id"] = "plugin-generated"
    write(source, upstream)
    plan = plan_reviewed_upgrade(target, source, base)
    assert plan["conflicts"] == []
    assert len(plan["definition"]["edges"]) == 1


def test_provision_marker_records_explicit_local_identity(tmp_path):
    from src.extension_host.resource_ids import ResourceIdResolver, build_resource_id_plan
    source, target, base, sync = fixture(tmp_path)
    resolver = ResourceIdResolver()
    resolver.register(build_resource_id_plan("novel-owner", "custom", {"workflow": ["pipeline"]}))
    sync(resource_resolver=resolver)
    assert json.loads((target.parent / ".extension.json").read_text())["local_id"] == "pipeline"


def test_workflow_editor_model_change_replaces_existing_user_preference(tmp_path, monkeypatch):
    source, target, base, sync = fixture(tmp_path)
    monkeypatch.setattr("src.workflow.manager.WORKFLOWS_DIR", target.parent.parent)
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._extension_manager = None
    manager.save_workflow_model_overrides("custom-pipeline", {"writer": "p:mine"})
    edited = manager.get_workflow("custom-pipeline")["definition"]
    edited["nodes"][0]["model_override"] = "p:editor-choice"
    manager.update_workflow("custom-pipeline", edited)
    assert manager.get_workflow("custom-pipeline")["definition"]["nodes"][0]["model_override"] == "p:editor-choice"
    assert manager.get_workflow_model_overrides("custom-pipeline")["writer"] == "p:editor-choice"
