"""Transport adapter for the enabled novel plugin's adviser service."""
import asyncio
from src.core.request_llm import create_request_llm as create_llm
from .novel_story_support import story_support
from .novel_plugin import console_service


async def _receive_model_reply(llm, messages, on_output):
    return await console_service()._receive_model_reply(llm, messages, on_output)


class NovelAssistantJobs:
    def __init__(self):
        self._delegate = None

    @property
    def delegate(self):
        service = console_service()  # Recheck enabled owner even with an existing instance.
        if self._delegate is None:
            from .novel_reference_adoption import reference_catalog
            self._delegate = service.create_assistant(
                lambda **kwargs: create_llm(**kwargs),
                lambda required=False: story_support(required=required),
                catalog_loader=reference_catalog,
            )
        return self._delegate

    @property
    def tasks(self):
        return self.delegate.tasks

    @property
    def support_loader(self):
        return self.delegate.support_loader

    def history(self, root):
        return self.delegate.history(root)

    def start(self, root, request_id, payload):
        from src.runtime_admission import activity_scope
        with activity_scope("小说助手正在准备分析。"):
            return self.delegate.start(root, request_id, payload)

    def _write(self, root, entries):
        return self.delegate._write(root, entries)
