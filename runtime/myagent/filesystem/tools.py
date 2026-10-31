"""Capability adapter for read-only filesystem tools."""

from __future__ import annotations

from typing import Any

from myagent.agent.capabilities import CapabilityTool
from myagent.filesystem.service import FileService


class FileToolAdapter:
    def __init__(self, service: FileService) -> None:
        self.service = service

    def tools(self) -> list[CapabilityTool]:
        return [
            CapabilityTool(
                name="read_file",
                description="Read UTF-8 text from an explicitly configured filesystem root.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer", "minimum": 1},
                    },
                    "required": ["root", "path"],
                },
                handler=self._read_file,
            ),
            CapabilityTool(
                name="list_files",
                description="List files and directories below an explicitly configured filesystem root.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "recursive": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "required": ["root"],
                },
                handler=self._list_files,
            ),
            CapabilityTool(
                name="search_files",
                description="Search UTF-8 text files below an explicitly configured filesystem root.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "query": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "required": ["root", "query"],
                },
                handler=self._search_files,
            ),
            CapabilityTool(
                name="create_file",
                description="Create a UTF-8 text file inside the session working root.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["root", "path", "content"],
                },
                handler=self._create_file,
            ),
            CapabilityTool(
                name="write_file",
                description="Overwrite or create a UTF-8 file in the working root; overwrites require expected_sha256.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                    },
                    "required": ["root", "path", "content"],
                },
                handler=self._write_file,
            ),
            CapabilityTool(
                name="replace_file_text",
                description="Replace one exact text occurrence in a working-root file using an expected hash.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                    },
                    "required": ["root", "path", "old_text", "new_text", "expected_sha256"],
                },
                handler=self._replace_file_text,
            ),
            CapabilityTool(
                name="copy_file",
                description="Copy a readable file into the session working root; never deletes the source.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source_root": {"type": "string"},
                        "source_path": {"type": "string"},
                        "destination_root": {"type": "string"},
                        "destination_path": {"type": "string"},
                    },
                    "required": ["source_root", "source_path", "destination_root", "destination_path"],
                },
                handler=self._copy_file,
            ),
            CapabilityTool(
                name="move_file",
                description="Move a file within the working root; first call requests UI approval because the source is removed.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source_root": {"type": "string"}, "source_path": {"type": "string"},
                        "destination_root": {"type": "string"}, "destination_path": {"type": "string"},
                        "approval_id": {"type": "string"},
                    },
                    "required": ["source_root", "source_path", "destination_root", "destination_path"],
                },
                handler=self._move_file,
            ),
            CapabilityTool(
                name="delete_file",
                description="Delete a file inside the working root by moving it to trash; first call requests UI approval.",
                parameters={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "path": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                        "approval_id": {"type": "string"},
                    },
                    "required": ["root", "path"],
                },
                handler=self._delete_file,
            ),
            CapabilityTool(
                name="restore_file",
                description="Restore a previously trashed file using its operation_id.",
                parameters={
                    "type": "object",
                    "properties": {"operation_id": {"type": "string"}},
                    "required": ["operation_id"],
                },
                handler=self._restore_file,
            ),
        ]

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.read_file(
            arguments["root"], arguments["path"], max_bytes=arguments.get("max_bytes")
        )

    def _list_files(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return self.service.list_files(
            arguments["root"],
            arguments.get("path", "."),
            recursive=bool(arguments.get("recursive", False)),
            limit=int(arguments.get("limit", 100)),
        )

    def _search_files(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return self.service.search_files(
            arguments["root"],
            arguments["query"],
            arguments.get("path", "."),
            limit=int(arguments.get("limit", 20)),
        )

    def _create_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_file(arguments["root"], arguments["path"], arguments["content"])

    def _write_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.write_file(
            arguments["root"], arguments["path"], arguments["content"],
            expected_sha256=arguments.get("expected_sha256"),
        )

    def _replace_file_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.replace_text(
            arguments["root"], arguments["path"], arguments["old_text"], arguments["new_text"],
            expected_sha256=arguments["expected_sha256"],
        )

    def _copy_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.copy_file(
            arguments["source_root"], arguments["source_path"],
            arguments["destination_root"], arguments["destination_path"],
        )

    def _delete_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.delete_file(
            arguments["root"], arguments["path"],
            expected_sha256=arguments.get("expected_sha256"),
            approval_id=arguments.get("approval_id"),
        )

    def _move_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.move_file(
            arguments["source_root"], arguments["source_path"],
            arguments["destination_root"], arguments["destination_path"],
            approval_id=arguments.get("approval_id"),
        )

    def _restore_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.service.restore_file(arguments["operation_id"])
