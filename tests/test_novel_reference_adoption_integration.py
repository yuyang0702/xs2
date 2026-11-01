"""Actual host routes -> enabled plugin -> reference CLI, with isolated books.

Only the model/provider boundary is replaced. No installed plugin or real book
is read: script resources are copied from the sibling development repository.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import shutil
import sys
import threading
import time
import traceback
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.workspace_manager import WorkspaceManager
from src.extension_api.registrar import OwnedPath
from src.extension_host.resource_ids import ResourceIdResolver, build_resource_id_plan
from src.workflow.script_library import ScriptLibraryCatalog


PLUGIN = Path(__file__).resolve().parents[2] / "DeterminFlow-Plugins/plugins/xs2-novel-flywheel"
OWNER = "xs2-novel-flywheel"
API = "/api/novel-console/reference-adoption"
PREMISE = "许青追查矿井事故，为救妹妹选择公开证据并承担失业的代价。"
ADAPTATION = "许青先确认妹妹的伤情，再公开矿井证据；在第三人称短篇中以失去工作回收选择的代价。"
PROFILES = "# 人物\n\n## 许青\n矿工之女，谨慎、重情；对妹妹温和，对矿长克制质疑。\n\n## 许宁\n妹妹，敏锐，常以反问掩饰恐惧。\n"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class DeferredModel:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.messages = []
        self.closed = False
        self.response = {"decisions": [{"library_id": "correct", "candidate_id": "correct-rule",
            "decision": "adapt", "reason": "与本书救亲人和公开真相的目标相符，短篇需要回收职业代价。",
            "adaptation": ADAPTATION}], "voice_adaptations": []}

    async def ainvoke(self, messages):
        self.messages.append(messages)
        self.entered.set()
        for _ in range(2000):
            if self.release.is_set():
                return SimpleNamespace(content=json.dumps(self.response, ensure_ascii=False))
            await asyncio.sleep(0.005)
        raise TimeoutError("Test model was not released")

    async def aclose(self):
        self.closed = True


@pytest.fixture
def integration(tmp_path_factory, monkeypatch):
    # Keep Windows journal paths under the platform path limit even when the
    # caller chooses a long external verification/backup directory.
    tmp_path = tmp_path_factory.mktemp("book")
    if not (PLUGIN / "resources/script-library/xs2/console_service/adoption.py").is_file():
        pytest.skip("requires sibling DeterminFlow-Plugins quick-adoption implementation")
    from src import config
    from src.core import model_manager
    from src.web import novel_assistant, novel_plugin, novel_reference_adoption, novel_reference_adoption_routes, novel_routes
    from src.web import novel_workflow_models
    from src.workflow import script_library

    # Deliberately rename the script group; adapters must use enabled ownership.
    plugin_root = tmp_path / "plugin-scripts"
    for name in ("console_service", "reference_distill"):
        shutil.copytree(PLUGIN / "resources/script-library/xs2" / name,
                        plugin_root / "renamed-group" / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    flags = SimpleNamespace(enabled=True, running=True)
    catalog = ScriptLibraryCatalog(tmp_path / "user-scripts", [OwnedPath(OWNER, plugin_root)],
                                   owner_enabled=lambda _: flags.enabled)
    monkeypatch.setattr(script_library, "_catalog", catalog)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "WORKFLOWS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(novel_routes, "_library_root", tmp_path / "library")
    monkeypatch.setattr(novel_routes, "_index", tmp_path / "index.json")
    monkeypatch.setattr(novel_workflow_models, "get_agent_definition", lambda _: None)
    monkeypatch.setattr(model_manager, "get_model_manager", lambda: SimpleNamespace(
        get_all_models=lambda: ["fake:advisor"], get_default_model=lambda: "fake:unused"))
    model = DeferredModel()
    calls = []

    def create_model(**kwargs):
        calls.append(kwargs)
        return model

    monkeypatch.setattr(novel_reference_adoption, "create_llm", create_model)
    monkeypatch.setattr(novel_assistant, "create_llm", lambda **kwargs: pytest.fail("adviser history must not invoke a model"))

    def create(prefix=OWNER, recommendation=None, layer="narrative_lens"):
        root = tmp_path / "data/workspaces/books" / prefix
        root.mkdir(parents=True)
        project = {"_revision": 2, "mode": "short", "values": {"premise": PREMISE,
            "genre": "现实悬疑", "target_word_count": "8000", "narrative_pov": "third_person",
            "conflict_plan_mode": "short_full"}, "refs": {}}
        write_json(root / ".novel-project.json", project)
        entry = {"id": str(uuid4()), "purpose": "advisor", "status": "completed", "question": PREMISE,
            "configuration_base": copy.deepcopy(project), "advisor_sections": {
                "mechanism_recommendations": {"adopted_from_library": [recommendation or
                    {"library_id": "correct", "candidate_id": "correct-rule", "mechanism": "代价推动"}]}}}
        write_json(root / "learning/assistant-history.json", {"version": 1, "entries": [entry]})
        (root / "meta").mkdir()
        (root / "meta/character_profiles.md").write_text(PROFILES, encoding="utf-8")
        (root / "meta/character_voice.md").write_text("原有角色声音，不能覆盖。", encoding="utf-8")
        (root / "story/0001").mkdir(parents=True)
        (root / "story/0001/chapter.md").write_text("测试小说的现有正文。", encoding="utf-8")
        for library in ("aaa-wrong", "correct"):
            folder = tmp_path / "library" / library
            items = [{"candidate_id": library + "-rule", "mechanism": "代价推动", "transfer_guidance": "来源的抽象规则",
                "layer": layer, "scopes": ["mvp", "polish"], "application_scope": ["general"],
                "target_pov": ["third_person"], "evidence": [{"excerpt": "来源测试证据"}]}]
            write_json(folder / "manifest.json", {"id": library, "name": library})
            write_json(folder / "candidates.json", {"source": {"text_sha256": library}, "candidates": items,
                "candidates_sha256": novel_routes.fingerprint(items), "style_observations": [], "conflict_patterns": []})
            write_json(folder / "profile.json", {"markdown": "第三人称短篇；用职业代价推动亲情悬疑。"})
        resolver = ResourceIdResolver()
        resolver.register(build_resource_id_plan(OWNER, prefix, {"workflows": ["build", "novel-advisor"]}))
        build, adviser = f"{prefix}-build", f"{prefix}-novel-advisor"
        definition = {"workflow_id": adviser, "nodes": [{"id": "advisor", "node_type": "agent",
            "agent_type": "test-do-not-load", "model_override": "fake:advisor"}]}
        manager = SimpleNamespace(_ws_manager=WorkspaceManager(str(tmp_path / "data/workspaces")),
            get_workflow_execution_policy=lambda _: "public", is_workflow_owner_enabled=lambda _: flags.enabled,
            list_workflows=lambda: [{"workflow_id": build}, {"workflow_id": adviser}],
            get_workflow_owner=lambda _: OWNER, get_workflow=lambda _: {"definition": definition})
        app = FastAPI()
        app.state.workflow_manager = manager
        app.state.extension_manager = SimpleNamespace(is_running=lambda _: flags.running, resource_resolver=resolver)
        app.state.novel_automation = SimpleNamespace(has_active=lambda _: False)
        app.include_router(novel_reference_adoption_routes.router)
        errors = []
        implementation = sys.modules[novel_plugin.console_service().ReferenceAdoptionJobs.__module__]
        error_details = implementation._error_details

        def record_error(error):
            errors.append("".join(traceback.format_exception(error)))
            return error_details(error)

        monkeypatch.setattr(implementation, "_error_details", record_error)
        return SimpleNamespace(app=app, root=root, entry=entry, project=project, build=build,
            flags=flags, model=model, calls=calls, library=tmp_path / "library", tasks=tmp_path / "tasks", errors=errors)

    yield create
    model.release.set()
    novel_plugin._load.cache_clear()


def request_body(book, **updates):
    return {"workflow_id": book.build, "workspace": str(book.root), "entry_id": book.entry["id"],
            "request_id": str(uuid4()), "expected_revision": 2, **updates}


def query(book, identifier=None):
    return {"workflow_id": book.build, "workspace": str(book.root), **({"request_id": identifier} if identifier else {})}


def finish(client, book, identifier):
    book.model.release.set()
    for _ in range(200):
        response = client.get(API, params=query(book, identifier))
        assert response.status_code == 200, response.text
        job = response.json()["job"]
        if job["status"] != "checking":
            return job
        time.sleep(0.01)
    pytest.fail("adoption job did not finish")


@pytest.mark.parametrize("prefix", [OWNER, "renamed-novel"])
def test_real_plugin_cli_deferred_applied_idempotent_and_restart(integration, prefix):
    book = integration(prefix)
    protected = {relative: (book.root / relative).read_bytes() for relative in (
        ".novel-project.json", "meta/character_profiles.md", "meta/character_voice.md", "story/0001/chapter.md")}
    with TestClient(book.app) as client:
        body = request_body(book, recommendations=[{"library_id": "aaa-wrong"}])
        first = client.post(API, json=body)
        assert first.status_code == 200, first.text
        initial = first.json()["job"]
        assert initial["status"] == "checking"
        assert book.model.entered.wait(2)
        assert not (book.root / "learning/active.json").exists()
        assert client.post(API, json=body).json()["job"]["id"] == initial["id"]
        assert client.post(API, json=request_body(book)).json()["job"]["id"] == initial["id"]
        assert len(book.calls) == 1
        assert book.calls[0]["model_override"] == "fake:advisor"
        result = finish(client, book, initial["id"])
        assert result["status"] == "applied", (result, book.errors)
        assert [item["library_id"] for item in result["selected_references"]] == ["correct"]
        active = read_json(book.root / "learning/active.json")
        blueprint = read_json(book.root / active["blueprint_path"])
        assert blueprint["mechanisms"][0]["transfer_guidance"] == ADAPTATION
        assert ADAPTATION in (book.root / "learning/active_context.md").read_text(encoding="utf-8")
        assert read_json(book.root / "learning/library_refs.json")["items"] == ["correct"]
        assert book.model.closed
        assert client.post(API, json=body).json()["job"]["status"] == "applied"
        book.app.state.novel_reference_adoption_jobs = None
        assert client.get(API + "/latest", params=query(book)).json()["job"]["status"] == "applied"
        assert client.post(API, json=body).json()["job"]["status"] == "applied"
        assert len(list((book.root / "learning/blueprints").glob("*.json"))) == 1
        assert len(book.calls) == 1
    assert protected == {relative: (book.root / relative).read_bytes() for relative in protected}


def test_ambiguous_legacy_name_is_no_match_without_model_or_attachment(integration):
    book = integration(recommendation={"mechanism": "代价推动"})
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        assert response.json()["job"]["status"] == "no_match"
        assert not book.calls
        assert not (book.root / "learning/active.json").exists()
        assert not (book.root / "learning/library_refs.json").exists()


@pytest.mark.parametrize("change", ["project", "candidates", "profile"])
def test_deferred_check_rejects_stale_book_or_source(integration, change):
    book = integration()
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        identifier = response.json()["job"]["id"]
        assert book.model.entered.wait(2)
        if change == "project":
            updated = copy.deepcopy(book.project)
            updated["values"]["premise"] = "用户检查期间重新确定的故事定位。"
            write_json(book.root / ".novel-project.json", updated)
        elif change == "candidates":
            target = book.library / "correct/candidates.json"
            data = read_json(target)
            data["candidates"][0]["transfer_guidance"] = "来源已在检查期间重新分析。"
            write_json(target, data)
        else:
            write_json(book.library / "correct/profile.json", {"markdown": "新分析：第一人称长篇，原风格判断已失效。"})
        result = finish(client, book, identifier)
        assert result["status"] == "review_required", result
        assert result["error_code"] == "stale", result
        assert not (book.root / "learning/active.json").exists()
        assert not (book.root / "learning/library_refs.json").exists()


@pytest.mark.parametrize("boundary", ["disabled", "busy-task", "automation"])
def test_publication_rechecks_runtime_ownership_and_workspace_activity(integration, boundary):
    book = integration()
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        identifier = response.json()["job"]["id"]
        assert book.model.entered.wait(2)
        if boundary == "disabled":
            book.flags.enabled = False
        elif boundary == "busy-task":
            write_json(book.tasks / "any-workflow/tasks/active.json", {"status": "running", "workspace_override": str(book.root)})
        else:
            book.app.state.novel_automation.has_active = lambda _: True
        if boundary == "disabled":
            book.model.release.set()
            for _ in range(200):
                if book.model.closed:
                    break
                time.sleep(0.01)
            assert book.model.closed
            # Disabled resources are intentionally unavailable over HTTP. Read
            # the persisted terminal result after enabling the same owner again.
            book.flags.enabled = True
        result = finish(client, book, identifier)
        assert result["status"] in {"review_required", "failed"}, result
        assert not (book.root / "learning/active.json").exists()
        assert not (book.root / "learning/library_refs.json").exists()


def test_voice_is_adapted_for_evidenced_book_role_and_original_is_preserved(integration):
    book = integration(layer="dialogue")
    original = (book.root / "meta/character_voice.md").read_bytes()
    guidance = "面对妹妹先问伤情再谈矿井证据；面对矿长用短问句追责，压住愤怒，不套用妹妹的反问习惯。"
    book.model.response["voice_adaptations"] = [{"character_name": "许青", "guidance": guidance,
        "profile_evidence": "对妹妹温和，对矿长克制质疑", "reference_ids": ["correct-rule"]}]
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        assert book.model.entered.wait(2)
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "applied", result
        assert result["voice_status"] == "adapted"
        assert [voice["character_name"] for voice in result["voice_adaptations"]] == ["许青"]
        assert guidance in (book.root / "meta/character_voice_adaptations.md").read_text(encoding="utf-8")
        context = json.loads(book.model.messages[0][1][1])
        assert "对妹妹温和" in context["book_characters"]["许青"]
    assert (book.root / "meta/character_voice.md").read_bytes() == original


def test_distinct_source_candidate_id_collision_never_claims_both_applied(integration):
    book = integration()
    other_path = book.library / "aaa-wrong/candidates.json"
    other = read_json(other_path)
    other["candidates"][0]["candidate_id"] = "correct-rule"
    write_json(other_path, other)
    book.entry["advisor_sections"]["mechanism_recommendations"]["adopted_from_library"].append(
        {"library_id": "aaa-wrong", "candidate_id": "correct-rule", "mechanism": "代价推动"})
    write_json(book.root / "learning/assistant-history.json", {"version": 1, "entries": [book.entry]})
    book.model.response["decisions"].append({**book.model.response["decisions"][0], "library_id": "aaa-wrong",
        "adaptation": "另一来源独有的适配：许青以向妹妹说谎的关系代价引出最终和解。"})
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "review_required", result
        assert not (book.root / "learning/active.json").exists()
        assert not (book.root / "learning/library_refs.json").exists()


def test_changed_canonical_role_cache_cannot_publish_old_voice_evidence(integration):
    book = integration(layer="dialogue")
    role_path = book.root / "cache/sync/characters.json"
    write_json(role_path, {"characters": [{"name": "许青", "occupation": "矿工之女，面对矿长克制质疑"}]})
    book.model.response["voice_adaptations"] = [{"character_name": "许青",
        "guidance": "面对妹妹先问伤情再谈矿井证据；面对矿长用短问句追责，克制愤怒。",
        "profile_evidence": "矿工之女", "reference_ids": ["correct-rule"]}]
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        assert book.model.entered.wait(2)
        write_json(role_path, {"characters": [{"name": "许青", "occupation": "用户已改写为记者，不是矿工之女"}]})
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "review_required", result
        assert result["error_code"] == "stale", result
        assert not (book.root / "learning/active.json").exists()
        assert not (book.root / "meta/character_voice_adaptations.md").exists()


@pytest.mark.parametrize("kind", ["style", "conflict"])
def test_style_and_conflict_choice_ids_reach_real_blueprint_with_adaptation(integration, kind):
    from src.web.novel_reference_adoption import reference_catalog
    book = integration()
    target = book.library / "correct/candidates.json"
    data = read_json(target)
    data["style_observations" if kind == "style" else "conflict_patterns"] = [{
        "name": "克制节奏" if kind == "style" else "公开证据的代价链", "transfer_guidance": "来源的抽象方法",
        "application_scope": ["general"], "evidence": [{"excerpt": "参考文本证据"}]}]
    write_json(target, data)
    library = next(item for item in reference_catalog() if item["library_id"] == "correct")
    choice = library["candidates"][kind + "_choices"][0]["choice_id"]
    section = "style_recommendations" if kind == "style" else "conflict_recommendations"
    key = "adopted_styles" if kind == "style" else "adopted_conflicts"
    book.entry["advisor_sections"] = {section: {key: [{"library_id": "correct", "choice_id": choice,
        kind: "克制节奏" if kind == "style" else "公开证据的代价链"}]}}
    write_json(book.root / "learning/assistant-history.json", {"version": 1, "entries": [book.entry]})
    book.model.response["decisions"] = [{"library_id": "correct", "choice_id": choice, "decision": "adapt",
        "reason": "适合本书第三人称短篇与人物的选择代价。", "adaptation": ADAPTATION}]
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "applied", result
        active = read_json(book.root / "learning/active.json")
        blueprint = read_json(book.root / active["blueprint_path"])
        assert blueprint["selected_" + kind + "_ids"] == [choice]
        assert blueprint["styles" if kind == "style" else "conflicts"][0]["guidance"] == ADAPTATION
        assert ADAPTATION in (book.root / "learning/active_context.md").read_text(encoding="utf-8")


def test_new_adoption_preserves_previously_published_rules_and_source_receipts(integration):
    book = integration()
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        assert finish(client, book, response.json()["job"]["id"])["status"] == "applied"
        active = read_json(book.root / "learning/active.json")
        first_blueprint = (book.root / active["blueprint_path"]).read_bytes()
        first = read_json(book.root / active["blueprint_path"])
        book.entry["advisor_sections"]["mechanism_recommendations"]["adopted_from_library"] = [
            {"library_id": "aaa-wrong", "candidate_id": "aaa-wrong-rule", "mechanism": "代价推动"}]
        write_json(book.root / "learning/assistant-history.json", {"version": 1, "entries": [book.entry]})
        book.model.response["decisions"] = [{"library_id": "aaa-wrong", "candidate_id": "aaa-wrong-rule",
            "decision": "adapt", "reason": "不同来源增加妹妹视角下的关系代价。", "adaptation": "用对妹妹隐瞒线索的代价补充职业代价，最后以坦白回收姐妹关系。"}]
        book.model.entered.clear()
        book.model.release.clear()
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "applied", (result, book.errors)
        updated_active = read_json(book.root / "learning/active.json")
        second = read_json(book.root / updated_active["blueprint_path"])
        assert updated_active["version"] == 2
        assert (book.root / active["blueprint_path"]).read_bytes() == first_blueprint
        assert second["mechanisms"][0] == first["mechanisms"][0]
        assert second["selected_candidate_ids"] == ["correct-rule", "aaa-wrong-rule"]
        assert read_json(book.root / "learning/library_refs.json")["items"] == ["correct", "aaa-wrong"]


def test_existing_attached_candidate_id_from_another_source_is_not_relabelled(integration):
    book = integration()
    attached = read_json(book.library / "aaa-wrong/candidates.json")
    attached["candidates"][0]["candidate_id"] = "correct-rule"
    write_json(book.root / "learning/candidates.json", attached)
    original = (book.root / "learning/candidates.json").read_bytes()
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        result = finish(client, book, response.json()["job"]["id"])
        assert result["status"] == "review_required", result
        assert not (book.root / "learning/active.json").exists()
    assert (book.root / "learning/candidates.json").read_bytes() == original


@pytest.mark.parametrize("committed", [True, False])
def test_real_publication_journal_recovers_after_restart_without_losing_author_edits(integration, committed):
    book = integration()
    with TestClient(book.app) as client:
        response = client.post(API, json=request_body(book))
        assert response.status_code == 200, response.text
        identifier = response.json()["job"]["id"]
        assert finish(client, book, identifier)["status"] == "applied"
        active_path = book.root / "learning/active.json"
        active = active_path.read_bytes()
        folder = book.root / "learning/adoption-jobs" / identifier
        publication = read_json(folder / "publication.json")
        assert publication["state"] == "committed"
        context = book.root / "learning/active_context.md"
        author_edit = context.read_text(encoding="utf-8") + "\n作者重启前新增的节奏要求。\n"
        context.write_text(author_edit, encoding="utf-8")
        if not committed:
            # Model the exact on-disk state of a killed publisher before its
            # final receipt and commit marker, using the real generated journal.
            publication["state"] = "publishing"
            write_json(folder / "publication.json", publication)
            active_path.unlink()
        job = read_json(folder / "job.json")
        job["status"] = "checking"
        write_json(folder / "job.json", job)
        book.app.state.novel_reference_adoption_jobs = None
        response = client.get(API, params=query(book, identifier))
        assert response.status_code == 200, response.text
        recovered = response.json()["job"]
        assert context.read_text(encoding="utf-8") == author_edit
        if committed:
            assert recovered["status"] == "applied", recovered
            assert active_path.read_bytes() == active
            assert (book.root / read_json(active_path)["blueprint_path"]).is_file()
            assert read_json(book.root / "learning/library_refs.json")["items"] == ["correct"]
        else:
            assert recovered["status"] == "review_required", recovered
            assert not active_path.exists()
            assert not list((book.root / "learning/blueprints").glob("*.json"))
            assert not (book.root / "learning/library_refs.json").exists()
        assert len(book.calls) == 1
