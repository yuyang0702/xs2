import unittest

from fastapi import HTTPException

from src.web.novel_workflow_models import (
    definition_digest,
    model_settings,
    save_model_settings,
)


class _Models:
    def get_all_models(self):
        return ["p:first", "p:second"]

    def get_default_model(self):
        return "p:first"

    def get_provider(self, provider_id):
        return {"models": ["first", "second"]} if provider_id == "p" else None

    def get_model_provider_type(self, provider_id, model_name):
        return "openai"


class _Manager:
    def __init__(self):
        self.definition = {
            "workflow_id": "xs2-novel-flywheel-test",
            "version": 2,
            "name": "测试步骤",
            "nodes": [
                {
                    "id": "writer",
                    "label": "写手",
                    "node_type": "agent",
                    "agent_type": "missing-agent",
                    "first_message": "保留",
                },
                {"id": "script", "label": "脚本", "node_type": "script", "script": "保留"},
            ],
            "edges": [{"id": "edge", "source": "writer", "target": "script"}],
        }

    def get_workflow(self, workflow_id):
        return {"definition": self.definition} if workflow_id == self.definition["workflow_id"] else None

    def update_workflow(self, workflow_id, definition):
        self.definition = definition
        return {"definition": definition}


class NovelWorkflowModelTests(unittest.TestCase):
    def test_save_changes_only_node_model_and_keeps_definition(self):
        manager = _Manager()
        models = _Models()
        current = model_settings(manager.definition, models)
        saved = save_model_settings(
            manager,
            manager.definition["workflow_id"],
            current["digest"],
            {"writer": "p:second"},
            models,
        )
        self.assertEqual(manager.definition["nodes"][0]["model_override"], "p:second")
        self.assertEqual(manager.definition["edges"], [{"id": "edge", "source": "writer", "target": "script"}])
        self.assertEqual(saved["nodes"][0]["effective_model"], "p:second")

    def test_stale_digest_is_rejected_without_mutation(self):
        manager = _Manager()
        before = definition_digest(manager.definition)
        with self.assertRaises(HTTPException) as failure:
            save_model_settings(manager, manager.definition["workflow_id"], "0" * 64, {"writer": "p:second"}, _Models())
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(definition_digest(manager.definition), before)


if __name__ == "__main__":
    unittest.main()
