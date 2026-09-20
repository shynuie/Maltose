from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.agent.taskbrain import MemoryStore, TaskBrain
from myagent.knowledge.ingestion import DocumentIngestionService
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.tools import DocumentToolAdapter


class RecordingModel:
    def __init__(self) -> None:
        self.messages = []
        self.tool_names = []

    def complete(self, messages, tools):
        self.messages = messages
        self.tool_names = [tool["function"]["name"] for tool in tools]
        return {"choices": [{"message": {"role": "assistant", "content": "收到"}}]}


class FakeKnowledgeService:
    def search_documents(self, query, top_k=5):
        return []

    def search_in_document(self, document_id, query, top_k=10):
        return []

    def read_document(self, document_id, location=None):
        raise KeyError(document_id)


class FakeIngestion:
    pass


class KnowledgeTaskBrainIntegrationTests(unittest.TestCase):
    def test_memory_and_kdb_tools_are_registered_together(self):
        model = RecordingModel()
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(
                model,
                memory=MemoryStore(Path(directory) / "memory.json"),
                capability_adapters=[
                    DocumentToolAdapter(
                        DocumentKnowledgeService.__new__(DocumentKnowledgeService),
                        ingestion=FakeIngestion(),
                    )
                ],
            )

            brain.process("hello")

        self.assertIn("remember", model.tool_names)
        self.assertIn("recall", model.tool_names)
        self.assertIn("search_documents", model.tool_names)
        self.assertIn("search_in_document", model.tool_names)
        self.assertIn("read_document", model.tool_names)
        self.assertIn("create_document", model.tool_names)
        self.assertIn("Document Knowledge Base", model.messages[0]["content"])
        self.assertIn("Speaker verification status for this turn: unverified", model.messages[0]["content"])

    def test_verified_context_is_explicitly_passed_to_model(self):
        model = RecordingModel()
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(
                model,
                memory=MemoryStore(Path(directory) / "memory.json"),
            )
            from myagent.agent.brain import TurnContext

            brain.process(
                "查詢文件",
                context=TurnContext(user_id="user-001", speaker_status="identified"),
            )

        self.assertIn("Speaker verification status for this turn: verified", model.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
