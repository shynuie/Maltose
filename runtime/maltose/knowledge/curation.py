"""Candidate knowledge storage and review state machine."""

from __future__ import annotations

import hashlib
import json
import os
import re
from time import time
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


PROPOSAL_TYPES = frozenset({
    "fact", "procedure", "summary", "preference", "hypothesis", "observation",
})
PROPOSAL_STATUSES = frozenset({"pending", "approved", "rejected", "expired"})
SOURCE_REQUIRED_TYPES = frozenset({"fact", "procedure", "summary"})
UNCERTAIN_TYPES = frozenset({"hypothesis", "observation"})


class CurationAuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None

    def record(self, event: str, **payload: Any) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")

    def repair(self) -> dict[str, int]:
        if self.path is None or not self.path.exists():
            return {"valid": 0, "invalid": 0}
        valid = invalid = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                    raise ValueError
                valid += 1
            except (json.JSONDecodeError, ValueError):
                invalid += 1
        return {"valid": valid, "invalid": invalid}

    def rotate(self, *, max_bytes: int) -> Path | None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive.")
        if self.path is None or not self.path.exists() or self.path.stat().st_size <= max_bytes:
            return None
        archive = self.path.with_name(f"{self.path.name}.{int(time())}")
        self.path.rename(archive)
        return archive


@dataclass(frozen=True)
class KnowledgeProposal:
    proposal_id: str
    type: str
    content: str
    sources: tuple[dict[str, str], ...]
    confidence: float
    created_by: str
    status: str
    created_at: str
    expires_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    rejection_reason: str | None = None


class KnowledgeQualityPolicy:
    def __init__(self, *, max_content_chars: int = 12_000, max_sources: int = 8) -> None:
        if max_content_chars <= 0 or max_sources <= 0:
            raise ValueError("Knowledge proposal limits must be positive.")
        self.max_content_chars = max_content_chars
        self.max_sources = max_sources

    def validate(
        self,
        *,
        proposal_type: str,
        content: str,
        sources: list[dict[str, str]],
        confidence: float,
    ) -> None:
        if proposal_type not in PROPOSAL_TYPES:
            raise ValueError(f"Unknown knowledge proposal type: {proposal_type}")
        if not content.strip() or len(content) > self.max_content_chars:
            raise ValueError("Knowledge proposal content is empty or too long.")
        if not 0 <= confidence <= 1:
            raise ValueError("Knowledge proposal confidence must be between 0 and 1.")
        if len(sources) > self.max_sources:
            raise ValueError("Too many knowledge proposal sources.")
        for source in sources:
            if not isinstance(source, dict) or not source.get("root") or not source.get("path"):
                raise ValueError("Each knowledge source needs root and path.")
        if proposal_type in SOURCE_REQUIRED_TYPES and not sources:
            raise ValueError(f"Knowledge type '{proposal_type}' requires a source.")

    def can_publish(self, proposal: KnowledgeProposal) -> bool:
        return proposal.status == "approved" and (
            proposal.type not in SOURCE_REQUIRED_TYPES or bool(proposal.sources)
        )


class KnowledgeSourcePolicy:
    """Allow provenance only from explicitly configured source roots."""

    def __init__(
        self,
        allowed_roots: Mapping[str, str | Path],
        *,
        blocked_root_names: tuple[str, ...] = (
            "dev", "tests", "data", "models", "recordings", ".git"
        ),
    ) -> None:
        if not allowed_roots:
            raise ValueError("At least one knowledge source root is required.")
        self.allowed_roots = {
            name: Path(path).expanduser().resolve()
            for name, path in allowed_roots.items()
        }
        self.blocked_root_names = frozenset(blocked_root_names)

    def validate(self, sources: list[dict[str, str]]) -> None:
        for source in sources:
            root_name = source["root"]
            if root_name in self.blocked_root_names or root_name not in self.allowed_roots:
                raise PermissionError(f"Knowledge source root is not allowed: {root_name}")
            relative = Path(source["path"])
            if relative.is_absolute() or any(part == ".." for part in relative.parts):
                raise PermissionError("Knowledge source path must stay inside its root.")
            candidate = (self.allowed_roots[root_name] / relative).resolve(strict=False)
            try:
                candidate.relative_to(self.allowed_roots[root_name])
            except ValueError as exc:
                raise PermissionError("Knowledge source path escapes its root.") from exc
            if not candidate.is_file():
                raise FileNotFoundError(candidate)


class KnowledgeProposalStore:
    """Persist proposals separately from truth documents and KDB indexes."""

    def __init__(
        self,
        path: str | Path,
        policy: KnowledgeQualityPolicy | None = None,
        source_policy: KnowledgeSourcePolicy | None = None,
        audit_log: CurationAuditLog | None = None,
    ) -> None:
        self.path = Path(path)
        self.policy = policy or KnowledgeQualityPolicy()
        self.source_policy = source_policy
        self.audit_log = audit_log or CurationAuditLog()

    def create(
        self,
        *,
        proposal_type: str,
        content: str,
        sources: list[dict[str, str]] | None = None,
        confidence: float = 0.5,
        created_by: str = "agent",
        expires_at: str | None = None,
    ) -> KnowledgeProposal:
        normalized_sources = [
            {str(key): str(value) for key, value in source.items()}
            for source in (sources or [])
        ]
        self.policy.validate(
            proposal_type=proposal_type,
            content=content,
            sources=normalized_sources,
            confidence=confidence,
        )
        if self.source_policy is not None:
            self.source_policy.validate(normalized_sources)
        proposals = self._load()
        digest = self._content_digest(proposal_type, content)
        if any(self._content_digest(item.type, item.content) == digest for item in proposals):
            raise ValueError("Duplicate knowledge proposal.")
        proposal = KnowledgeProposal(
            proposal_id=uuid.uuid4().hex,
            type=proposal_type,
            content=content.strip(),
            sources=tuple(normalized_sources),
            confidence=float(confidence),
            created_by=created_by,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=expires_at,
        )
        proposals.append(proposal)
        self._save(proposals)
        self.audit_log.record("proposal_created", proposal_id=proposal.proposal_id, proposal_type=proposal.type)
        return proposal

    def list(self, *, status: str | None = None) -> list[KnowledgeProposal]:
        if status is not None and status not in PROPOSAL_STATUSES:
            raise ValueError(f"Unknown proposal status: {status}")
        proposals = self._expire_pending(self._load())
        if status is not None:
            proposals = [item for item in proposals if item.status == status]
        return proposals

    def get(self, proposal_id: str) -> KnowledgeProposal:
        for proposal in self._expire_pending(self._load()):
            if proposal.proposal_id == proposal_id:
                return proposal
        raise KeyError(f"Unknown proposal: {proposal_id}")

    def approve(self, proposal_id: str, *, reviewer: str) -> KnowledgeProposal:
        return self._review(proposal_id, reviewer=reviewer, status="approved")

    def reject(self, proposal_id: str, *, reviewer: str, reason: str) -> KnowledgeProposal:
        if not reason.strip():
            raise ValueError("A rejection reason is required.")
        return self._review(
            proposal_id, reviewer=reviewer, status="rejected", rejection_reason=reason.strip()
        )

    def _review(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        status: str,
        rejection_reason: str | None = None,
    ) -> KnowledgeProposal:
        if status not in {"approved", "rejected"}:
            raise ValueError("Invalid review status.")
        proposals = self._expire_pending(self._load())
        try:
            index = next(i for i, item in enumerate(proposals) if item.proposal_id == proposal_id)
        except StopIteration as exc:
            raise KeyError(f"Unknown proposal: {proposal_id}") from exc
        current = proposals[index]
        if current.status != "pending":
            raise ValueError(f"Proposal is not pending: {proposal_id}")
        reviewed = KnowledgeProposal(
            **{
                **asdict(current),
                "status": status,
                "reviewed_by": reviewer,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "rejection_reason": rejection_reason,
            }
        )
        proposals[index] = reviewed
        self._save(proposals)
        self.audit_log.record("proposal_reviewed", proposal_id=reviewed.proposal_id, status=status, reviewer=reviewer)
        return reviewed

    def _load(self) -> list[KnowledgeProposal]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise RuntimeError("Knowledge proposal store must contain a JSON list.")
        return [
            KnowledgeProposal(
                **{
                    **item,
                    "sources": tuple(item.get("sources", [])),
                }
            )
            for item in raw
            if isinstance(item, dict)
        ]

    def _save(self, proposals: list[KnowledgeProposal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps([asdict(item) for item in proposals], ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            dir=self.path.parent, prefix=f".{self.path.name}.", mode="w", encoding="utf-8", delete=False
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        try:
            os.replace(temporary_path, self.path)
        finally:
            Path(temporary_path).unlink(missing_ok=True)

    def _expire_pending(self, proposals: list[KnowledgeProposal]) -> list[KnowledgeProposal]:
        now = datetime.now(timezone.utc)
        changed = False
        result: list[KnowledgeProposal] = []
        for proposal in proposals:
            if proposal.status == "pending" and proposal.expires_at:
                expires = datetime.fromisoformat(proposal.expires_at)
                if expires <= now:
                    proposal = KnowledgeProposal(**{**asdict(proposal), "status": "expired"})
                    changed = True
            result.append(proposal)
        if changed:
            self._save(result)
            for proposal in result:
                if proposal.status == "expired":
                    self.audit_log.record("proposal_expired", proposal_id=proposal.proposal_id)
        return result

    @staticmethod
    def _content_digest(proposal_type: str, content: str) -> str:
        normalized = f"{proposal_type}:{' '.join(content.casefold().split())}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CuratedKnowledgeEntry:
    curated_id: str
    proposal_id: str
    source_type: str
    type: str
    content: str
    sources: tuple[dict[str, str], ...]
    confidence: float
    published_by: str
    published_at: str
    embedding: tuple[float, ...] = ()
    status: str = "active"
    revoked_by: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None


class CuratedKnowledgeStore:
    """Store approved Agent knowledge separately from truth and proposals."""

    def __init__(
        self,
        path: str | Path,
        *,
        embedder: Any | None = None,
        stale_after_days: float | None = None,
        audit_log: CurationAuditLog | None = None,
    ) -> None:
        self.path = Path(path)
        self.embedder = embedder
        if stale_after_days is not None and stale_after_days <= 0:
            raise ValueError("stale_after_days must be positive.")
        self.stale_after_days = stale_after_days
        self.audit_log = audit_log or CurationAuditLog()

    def publish(
        self,
        proposal: KnowledgeProposal,
        *,
        publisher: str,
    ) -> CuratedKnowledgeEntry:
        if proposal.status != "approved":
            raise ValueError("Only approved knowledge proposals can be published.")
        entries = self._load()
        existing = next(
            (entry for entry in entries if entry.proposal_id == proposal.proposal_id and entry.status == "active"),
            None,
        )
        if existing is not None:
            raise ValueError("Knowledge proposal is already published.")
        conflicts = self.find_potential_conflicts(proposal.content, proposal_type=proposal.type)
        if conflicts:
            raise ValueError("Knowledge proposal conflicts with active curated knowledge.")
        entry = CuratedKnowledgeEntry(
            curated_id=uuid.uuid4().hex,
            proposal_id=proposal.proposal_id,
            source_type="agent_curated",
            type=proposal.type,
            content=proposal.content,
            sources=proposal.sources,
            confidence=proposal.confidence,
            published_by=publisher,
            published_at=datetime.now(timezone.utc).isoformat(),
            embedding=tuple(
                float(value) for value in self.embedder.embed(proposal.content)
            ) if self.embedder is not None else (),
        )
        entries.append(entry)
        self._save(entries)
        self.audit_log.record("curated_published", curated_id=entry.curated_id, proposal_id=entry.proposal_id, publisher=publisher)
        return entry

    def list(
        self,
        *,
        active_only: bool = True,
        include_uncertain: bool = False,
    ) -> list[CuratedKnowledgeEntry]:
        entries = self._load()
        if active_only:
            entries = [entry for entry in entries if entry.status == "active" and not self.is_stale(entry)]
        if active_only and not include_uncertain:
            entries = [entry for entry in entries if entry.type not in UNCERTAIN_TYPES]
        return entries
        return entries

    def find_conflicts(self, content: str, *, proposal_type: str) -> list[CuratedKnowledgeEntry]:
        normalized = _normalize_content(content)
        return [
            entry
            for entry in self.list(include_uncertain=True)
            if entry.type == proposal_type and _normalize_content(entry.content) == normalized
        ]

    def find_potential_conflicts(
        self,
        content: str,
        *,
        proposal_type: str,
        minimum_overlap: float = 0.5,
    ) -> list[CuratedKnowledgeEntry]:
        if not 0 < minimum_overlap <= 1:
            raise ValueError("minimum_overlap must be between 0 and 1.")
        candidate_terms = set(_tokens(content))
        conflicts: list[CuratedKnowledgeEntry] = []
        for entry in self.list(include_uncertain=True):
            if entry.type != proposal_type:
                continue
            existing_terms = set(_tokens(entry.content))
            overlap = len(candidate_terms & existing_terms) / max(
                len(candidate_terms | existing_terms), 1
            )
            if overlap >= minimum_overlap:
                conflicts.append(entry)
        return conflicts

    def is_stale(self, entry: CuratedKnowledgeEntry, *, now: datetime | None = None) -> bool:
        if self.stale_after_days is None:
            return False
        published_at = datetime.fromisoformat(entry.published_at)
        current = now or datetime.now(timezone.utc)
        return published_at + timedelta(days=self.stale_after_days) <= current

    def repair(self, *, proposals: KnowledgeProposalStore | None = None) -> dict[str, int]:
        """Validate the durable store and report active/revoked/stale entries."""
        entries = self._load()
        active_ids: set[str] = set()
        duplicate_active = 0
        stale = 0
        orphaned = 0
        proposal_ids = {item.proposal_id for item in proposals.list()} if proposals is not None else set()
        for entry in entries:
            if entry.status == "active":
                if entry.proposal_id in active_ids:
                    duplicate_active += 1
                active_ids.add(entry.proposal_id)
                if self.is_stale(entry):
                    stale += 1
                if proposals is not None and entry.proposal_id not in proposal_ids:
                    orphaned += 1
        return {
            "total": len(entries),
            "active": sum(entry.status == "active" for entry in entries),
            "revoked": sum(entry.status == "revoked" for entry in entries),
            "stale": stale,
            "duplicate_active": duplicate_active,
            "orphaned": orphaned,
        }

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        include_uncertain: bool = False,
    ) -> list[dict[str, Any]]:
        query = query.strip().casefold()
        if not query:
            raise ValueError("Curated knowledge query cannot be empty.")
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        terms = [term for term in query.split() if term]
        query_embedding = (
            tuple(float(value) for value in self.embedder.embed(query, is_query=True))
            if self.embedder is not None else None
        )
        scored: list[tuple[float, int, CuratedKnowledgeEntry]] = []
        for index, entry in enumerate(self.list(include_uncertain=include_uncertain)):
            haystack = entry.content.casefold()
            lexical_score = sum(1 for term in terms if term in haystack)
            semantic_score = (
                _cosine_similarity(query_embedding, entry.embedding)
                if query_embedding and entry.embedding else None
            )
            score = semantic_score if semantic_score is not None else float(lexical_score)
            if score:
                scored.append((score, index, entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                "curated_id": entry.curated_id,
                "proposal_id": entry.proposal_id,
                "content": entry.content,
                "type": entry.type,
                "sources": list(entry.sources),
                "confidence": entry.confidence,
                "source_type": entry.source_type,
                "similarity_score": score,
            }
            for score, _, entry in scored[:top_k]
        ]

    def revoke(self, curated_id: str, *, reviewer: str, reason: str) -> CuratedKnowledgeEntry:
        if not reason.strip():
            raise ValueError("A revocation reason is required.")
        entries = self._load()
        try:
            index = next(i for i, entry in enumerate(entries) if entry.curated_id == curated_id)
        except StopIteration as exc:
            raise KeyError(f"Unknown curated knowledge entry: {curated_id}") from exc
        current = entries[index]
        if current.status != "active":
            raise ValueError("Curated knowledge entry is already revoked.")
        revoked = CuratedKnowledgeEntry(
            **{
                **asdict(current),
                "status": "revoked",
                "revoked_by": reviewer,
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revocation_reason": reason.strip(),
            }
        )
        entries[index] = revoked
        self._save(entries)
        self.audit_log.record("curated_revoked", curated_id=revoked.curated_id, reviewer=reviewer, reason=reason.strip())
        return revoked

    def _load(self) -> list[CuratedKnowledgeEntry]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise RuntimeError("Curated knowledge store must contain a JSON list.")
        return [
            CuratedKnowledgeEntry(
                **{
                    **item,
                    "sources": tuple(item.get("sources", [])),
                    "embedding": tuple(item.get("embedding", [])),
                }
            )
            for item in raw
            if isinstance(item, dict)
        ]

    def _save(self, entries: list[CuratedKnowledgeEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps([asdict(item) for item in entries], ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            dir=self.path.parent, prefix=f".{self.path.name}.", mode="w", encoding="utf-8", delete=False
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        try:
            os.replace(temporary_path, self.path)
        finally:
            Path(temporary_path).unlink(missing_ok=True)


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def _normalize_content(content: str) -> str:
    return " ".join(content.casefold().split())


def _tokens(content: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", content.casefold())
