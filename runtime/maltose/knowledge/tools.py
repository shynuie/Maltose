"""Agent capability adapter for document retrieval."""

from __future__ import annotations

from typing import Any

from maltose.agent.capabilities import CapabilityTool
from maltose.knowledge.ingestion import DocumentIngestionService
from maltose.knowledge.models import DocumentLocation
from maltose.knowledge.retrieval import DocumentKnowledgeService


class DocumentToolAdapter:
    def __init__(
        self,
        service: DocumentKnowledgeService,
        ingestion: DocumentIngestionService | None = None,
    ) -> None:
        self.service = service
        self.ingestion = ingestion

    def tools(self) -> list[CapabilityTool]:
        tools = [
            CapabilityTool(
                name="search_documents",
                description="Find documents relevant to a question using document-level semantic search.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
                handler=self._search_documents,
            ),
            CapabilityTool(
                name="search_in_document",
                description="Find relevant locations inside one document. Use read_document before answering precisely.",
                parameters={
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["document_id", "query"],
                },
                handler=self._search_in_document,
            ),
            CapabilityTool(
                name="read_document",
                description="Read authoritative content from the original document at a location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "location": {
                            "type": "object",
                            "properties": {
                                "page": {"type": "integer"},
                                "section": {"type": "string"},
                                "start_offset": {"type": "integer"},
                                "end_offset": {"type": "integer"},
                            },
                        },
                    },
                    "required": ["document_id"],
                },
                handler=self._read_document,
            ),
        ]
        if self.ingestion is not None:
            tools.extend([
                CapabilityTool(
                    name="import_document",
                    description="Copy an existing file into the managed document root and index it. Do not overwrite files.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "source_path": {"type": "string"},
                            "destination": {"type": "string"},
                        },
                        "required": ["source_path", "destination"],
                    },
                    handler=self._import_document,
                ),
                CapabilityTool(
                    name="create_document",
                    description="Create a Markdown or text document inside the managed root and index it.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "directory": {"type": "string", "default": "inbox"},
                            "content": {"type": "string"},
                        },
                        "required": ["filename", "content"],
                    },
                    handler=self._create_document,
                ),
            ])
        return tools

    def _search_documents(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._as_dict(result) for result in self.service.search_documents(
            arguments["query"], int(arguments.get("top_k", 5))
        )]

    def _search_in_document(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._as_dict(result) for result in self.service.search_in_document(
            arguments["document_id"], arguments["query"], int(arguments.get("top_k", 10))
        )]

    def _read_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_location = arguments.get("location")
        location = DocumentLocation(**raw_location) if isinstance(raw_location, dict) else None
        result = self.service.read_document(arguments["document_id"], location)
        return {
            "document_id": result.document_id,
            "path": str(result.path),
            "text": result.text,
            "location": self._as_dict(result.location) if result.location else None,
        }

    def _import_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.ingestion is None:
            raise RuntimeError("Document ingestion is not enabled")
        result = self.ingestion.import_file(arguments["source_path"], arguments["destination"])
        return {
            "path": str(result.path),
            "document_id": result.index.document_id,
            "status": result.index.status,
            "chunk_count": result.index.chunk_count,
        }

    def _create_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.ingestion is None:
            raise RuntimeError("Document ingestion is not enabled")
        result = self.ingestion.create_document(
            content=arguments["content"],
            filename=arguments["filename"],
            directory=arguments.get("directory", "inbox"),
        )
        return {
            "path": str(result.path),
            "document_id": result.index.document_id,
            "status": result.index.status,
            "chunk_count": result.index.chunk_count,
        }

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if hasattr(value, "__dataclass_fields__"):
            return {
                name: DocumentToolAdapter._as_dict(getattr(value, name))
                for name in value.__dataclass_fields__
            }
        return value
