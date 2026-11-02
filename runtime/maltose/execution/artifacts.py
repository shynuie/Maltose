"""Validate and promote sandbox artifacts through FileService."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from maltose.execution.models import ExecutionRequest, OutputArtifact
from maltose.filesystem.approval import ApprovalManager, ApprovalRecord
from maltose.filesystem.service import FileService


class ArtifactPromotionApprovalRequired(PermissionError):
    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message)
        self.approval_id = approval_id


@dataclass(frozen=True)
class PromotionPlan:
    source_path: Path
    source_relative_path: str
    source_sha256: str
    size_bytes: int
    destination_root: str
    destination_path: str

    def scope(self) -> str:
        return f"{self.source_sha256}:{self.destination_root}:{self.destination_path}"


class ArtifactPromoter:
    """Move bytes from a live sandbox session into a controlled FileService root."""

    def __init__(
        self,
        file_service: FileService,
        *,
        approval_manager: ApprovalManager | None = None,
        session_id: str = "default",
        approval_notifier: Callable[[ApprovalRecord], None] | None = None,
        max_bytes: int = 64 * 1024 * 1024,
        max_total_bytes: int = 256 * 1024 * 1024,
        allowed_content_types: frozenset[str] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("Artifact size limit must be positive.")
        if max_total_bytes <= 0:
            raise ValueError("Total artifact size limit must be positive.")
        self.file_service = file_service
        self.approval_manager = approval_manager
        self.session_id = session_id
        self.approval_notifier = approval_notifier
        self.max_bytes = max_bytes
        self.max_total_bytes = max_total_bytes
        self.allowed_content_types = allowed_content_types

    def validate_plans(self, plans: tuple[PromotionPlan, ...]) -> None:
        total = sum(plan.size_bytes for plan in plans)
        if total > self.max_total_bytes:
            raise PermissionError("Artifacts exceed the configured total promotion quota.")

    def plan(self, session_dir: str | Path, artifact: OutputArtifact) -> PromotionPlan:
        if artifact.destination_root is None or artifact.destination_path is None:
            raise ValueError("Artifact promotion requires an explicit destination.")
        session = Path(session_dir).expanduser().resolve()
        relative = PurePosixPath(artifact.path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in artifact.path:
            raise PermissionError("Artifact source path must stay inside the execution session.")
        source = (session / relative).resolve(strict=False)
        try:
            source.relative_to(session)
        except ValueError as exc:
            raise PermissionError("Artifact source path escapes the execution session.") from exc
        current = session
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise PermissionError("Artifact source cannot contain symlink components.")
        if not source.is_file():
            raise FileNotFoundError(source)
        size = source.stat().st_size
        if size > self.max_bytes:
            raise PermissionError("Artifact exceeds the configured promotion size limit.")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if artifact.sha256 is not None and digest != artifact.sha256:
            raise RuntimeError("Artifact hash does not match the declared hash.")
        guessed_type = mimetypes.guess_type(source.name)[0]
        if artifact.content_type is not None and guessed_type is not None and artifact.content_type != guessed_type:
            raise RuntimeError("Artifact content type does not match the declared type.")
        if self.allowed_content_types is not None:
            if guessed_type is None or guessed_type not in self.allowed_content_types:
                raise PermissionError("Artifact content type is not allowed by promotion policy.")
        return PromotionPlan(source, relative.as_posix(), digest, size, artifact.destination_root, artifact.destination_path)

    def promote(self, plan: PromotionPlan, *, approval_id: str | None = None) -> dict[str, object]:
        return self.promote_many((plan,), approval_id=approval_id)[0]

    def promote_many(
        self,
        plans: tuple[PromotionPlan, ...],
        *,
        approval_id: str | None = None,
    ) -> list[dict[str, object]]:
        if not plans:
            return []
        self.validate_plans(plans)
        if self.approval_manager is None:
            raise ArtifactPromotionApprovalRequired("Artifact promotion requires approval.")
        scope = hashlib.sha256("|".join(plan.scope() for plan in plans).encode()).hexdigest()
        if approval_id is None:
            record = self.approval_manager.create(
                session_id=self.session_id,
                operation="promote",
                root="execution",
                path=scope,
                expected_sha256=scope,
                destination_path="batch",
            )
            if self.approval_notifier is not None:
                self.approval_notifier(record)
            raise ArtifactPromotionApprovalRequired(
                f"Artifact promotion requires approval: {scope}", approval_id=record.approval_id
            )
        self.approval_manager.consume(
            approval_id,
            session_id=self.session_id,
            operation="promote",
            root="execution",
            path=scope,
            expected_sha256=scope,
            destination_path="batch",
        )
        prepared: list[tuple[PromotionPlan, bytes, str | None]] = []
        for plan in plans:
            data = plan.source_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != plan.source_sha256:
                raise RuntimeError("Artifact changed after approval.")
            destination = self.file_service.resolver.resolve(plan.destination_root, plan.destination_path)
            expected_destination = None
            if destination.path.exists():
                expected_destination = hashlib.sha256(destination.path.read_bytes()).hexdigest()
            prepared.append((plan, data, expected_destination))
        results: list[dict[str, object]] = []
        for plan, data, expected_destination in prepared:
            result = self.file_service.write_bytes(
                plan.destination_root, plan.destination_path, data,
                expected_sha256=expected_destination,
            )
            result["source_sha256"] = plan.source_sha256
            results.append(result)
        return results
