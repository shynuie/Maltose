"""Planning helpers for repairing incomplete document indexing."""

from __future__ import annotations

from maltose.knowledge.models import ScannedFile
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.scanner import ScanResult
from maltose.knowledge.repositories.base import VectorRepository


REPAIRABLE_STATUSES = frozenset({"indexing_failed", "pending_index", "indexing"})


def find_repair_candidates(
    scan: ScanResult,
    metadata: MetadataRepository,
    *,
    force: bool = False,
) -> tuple[ScannedFile, ...]:
    """Return existing source files whose metadata indicates incomplete work."""
    if force:
        return scan.files

    candidates: list[ScannedFile] = []
    for scanned in scan.files:
        record = metadata.get_by_path(scanned.path)
        if record is not None and record.get("status") in REPAIRABLE_STATUSES:
            candidates.append(scanned)
    return tuple(candidates)


def find_orphan_vector_ids(
    metadata: MetadataRepository,
    vectors: VectorRepository,
) -> tuple[str, ...]:
    """Find vectors whose metadata is absent or no longer retrievable."""
    orphan_ids = []
    for document_id in sorted(vectors.list_document_ids()):
        record = metadata.get_by_id(document_id)
        if record is None or record.get("status") == "deleted":
            orphan_ids.append(document_id)
    return tuple(orphan_ids)
