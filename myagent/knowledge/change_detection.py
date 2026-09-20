"""Compare a filesystem scan with KDB metadata."""

from __future__ import annotations

from myagent.knowledge.models import ScannedFile
from myagent.knowledge.repositories.metadata import MetadataRepository
from myagent.knowledge.scanner import ScanPlan, ScanResult


class DocumentChangeDetector:
    def plan(self, scan: ScanResult, repository: MetadataRepository) -> ScanPlan:
        new_files: list[ScannedFile] = []
        changed_files: list[ScannedFile] = []
        unchanged_files: list[ScannedFile] = []
        moved_ids: list[str] = []
        active_paths = {str(scanned.path) for scanned in scan.files}

        for scanned in scan.files:
            existing = repository.get_by_path(scanned.path)
            if existing is not None:
                if existing["content_hash"] == scanned.content_hash:
                    unchanged_files.append(scanned)
                else:
                    changed_files.append(scanned)
                continue

            same_content = repository.get_by_content_hash(scanned.content_hash)
            if same_content is not None and same_content["status"] != "deleted":
                repository.update_path(same_content["id"], scanned.path)
                moved_ids.append(same_content["id"])
                unchanged_files.append(scanned)
            else:
                new_files.append(scanned)

        deleted_ids = repository.mark_missing(active_paths)
        return ScanPlan(
            new_files=tuple(new_files),
            changed_files=tuple(changed_files),
            unchanged_files=tuple(unchanged_files),
            moved_document_ids=tuple(moved_ids),
            deleted_document_ids=tuple(deleted_ids),
        )
