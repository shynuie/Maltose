"""Compare a filesystem scan with KDB metadata."""

from __future__ import annotations

import logging

from myagent.knowledge.models import ScannedFile
from myagent.knowledge.repositories.metadata import MetadataRepository
from myagent.knowledge.scanner import ScanPlan, ScanResult

logger = logging.getLogger(__name__)


class DocumentChangeDetector:
    def plan(self, scan: ScanResult, repository: MetadataRepository) -> ScanPlan:
        logger.info("kdb_change_detection_started scanned_files=%d", len(scan.files))
        new_files: list[ScannedFile] = []
        changed_files: list[ScannedFile] = []
        unchanged_files: list[ScannedFile] = []
        moved_ids: list[str] = []
        active_paths = {str(scanned.path) for scanned in scan.files}

        for scanned in scan.files:
            existing = repository.get_by_path(scanned.path)
            if existing is not None:
                if existing["content_hash"] == scanned.content_hash:
                    if existing["status"] == "pending_index" and existing.get("indexed_at"):
                        repository.restore_indexed_status(existing["id"])
                    unchanged_files.append(scanned)
                else:
                    changed_files.append(scanned)
                continue

            same_content = repository.get_by_content_hash(scanned.content_hash)
            if same_content is not None and same_content["status"] != "deleted":
                status = same_content["status"]
                if status == "pending_index" and same_content.get("indexed_at"):
                    status = "indexed"
                repository.update_path(same_content["id"], scanned.path, status=status)
                moved_ids.append(same_content["id"])
                unchanged_files.append(scanned)
            else:
                new_files.append(scanned)

        deleted_ids = repository.mark_missing(active_paths)
        plan = ScanPlan(
            new_files=tuple(new_files),
            changed_files=tuple(changed_files),
            unchanged_files=tuple(unchanged_files),
            moved_document_ids=tuple(moved_ids),
            deleted_document_ids=tuple(deleted_ids),
        )
        logger.info(
            "kdb_change_detection_completed new=%d changed=%d unchanged=%d moved=%d deleted=%d",
            len(plan.new_files),
            len(plan.changed_files),
            len(plan.unchanged_files),
            len(plan.moved_document_ids),
            len(plan.deleted_document_ids),
        )
        return plan
