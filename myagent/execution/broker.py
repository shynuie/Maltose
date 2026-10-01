"""Control plane for isolated command execution."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Callable

from myagent.execution.backend import MountSpec, SandboxBackend
from myagent.execution.models import ExecutionRequest, ExecutionResult
from myagent.execution.policy import ExecutionPolicy
from myagent.filesystem.approval import ApprovalManager, ApprovalRecord
from myagent.execution.events import ExecutionEvent, ExecutionEventPublisher, ExecutionEventType
from myagent.execution.metrics import ExecutionRuntimeMetrics
from myagent.filesystem.approval import AuditLog
from myagent.execution.artifacts import ArtifactPromoter, ArtifactPromotionApprovalRequired, PromotionPlan


@dataclass
class _PendingPromotion:
    session_dir: Path
    plans: tuple[PromotionPlan, ...]
    approval_id: str | None = None


class ExecutionApprovalRequired(PermissionError):
    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message)
        self.approval_id = approval_id


class ExecutionBroker:
    """Prepare and run one request through an OS-enforced backend."""

    _ALLOWED_MOUNT_PREFIXES = ("/execution", "/inputs", "/workspace", "/tmp")

    def __init__(
        self,
        backend: SandboxBackend,
        policy: ExecutionPolicy | None = None,
        *,
        approval_manager: ApprovalManager | None = None,
        session_id: str = "default",
        approval_notifier: Callable[[ApprovalRecord], None] | None = None,
        session_parent: str | Path | None = None,
        event_publisher: ExecutionEventPublisher | None = None,
        metrics: ExecutionRuntimeMetrics | None = None,
        audit_log: AuditLog | None = None,
        artifact_promoter: ArtifactPromoter | None = None,
        pending_store: str | Path | None = None,
    ) -> None:
        self.backend = backend
        self.policy = policy or ExecutionPolicy()
        self.approval_manager = approval_manager
        self.session_id = session_id
        self.approval_notifier = approval_notifier
        self.session_parent = Path(session_parent).resolve() if session_parent else None
        self.event_publisher = event_publisher
        self.metrics = metrics or ExecutionRuntimeMetrics()
        self.audit_log = audit_log or AuditLog()
        self.artifact_promoter = artifact_promoter
        self._pending_promotions: dict[str, _PendingPromotion] = {}
        self.pending_store = Path(pending_store).expanduser().resolve() if pending_store else None
        self._load_pending_promotions()

    def execute(
        self,
        request: ExecutionRequest,
        *,
        mounts: tuple[MountSpec, ...] = (),
    ) -> ExecutionResult:
        execution_id = uuid.uuid4().hex
        self.metrics.increment("queued")
        self._emit(ExecutionEventType.QUEUED, execution_id, {"scope": request.approval_scope()})
        self._validate_mounts(mounts)
        decision = self.policy.evaluate(request)
        if decision.action == "deny":
            self.metrics.increment("failed")
            self._emit(ExecutionEventType.FAILED, execution_id, {"reason": decision.reason})
            raise PermissionError(decision.reason)
        if decision.action == "approval_required":
            try:
                self._require_approval(request)
            except ExecutionApprovalRequired as exc:
                self.metrics.increment("approval_required")
                self._emit(ExecutionEventType.APPROVAL_REQUIRED, execution_id, {
                    "approval_id": exc.approval_id, "scope": request.approval_scope(),
                })
                raise
        capabilities = self.backend.capabilities
        if request.network.value != "off" and not capabilities.supports_network_isolation:
            self.metrics.increment("failed")
            raise PermissionError("Selected backend cannot enforce network isolation.")
        if request.network.value == "restricted" and not capabilities.supports_restricted_network:
            self.metrics.increment("failed")
            raise PermissionError("Selected backend cannot enforce restricted network allowlists.")
        if not capabilities.supports_read_only_mounts:
            self.metrics.increment("failed")
            raise PermissionError("Selected backend cannot enforce read-only mounts.")
        if request.outputs and self.artifact_promoter is None:
            self.metrics.increment("failed")
            raise PermissionError("Artifact promotion is not configured for this execution session.")
        session_dir = Path(tempfile.mkdtemp(prefix="myagent-exec-", dir=self.session_parent))
        retain_session = False
        self.metrics.increment("running")
        self._emit(ExecutionEventType.RUNNING, execution_id, {"backend": capabilities.name})
        try:
            result = replace(
                self.backend.execute(request, mounts=mounts, session_dir=session_dir),
                execution_id=execution_id,
            )
            if self.artifact_promoter is not None and request.outputs:
                plans = tuple(
                    self.artifact_promoter.plan(session_dir, artifact)
                    for artifact in request.outputs
                )
                self.artifact_promoter.validate_plans(plans)
                try:
                    self.artifact_promoter.promote_many(plans)
                except ArtifactPromotionApprovalRequired as exc:
                    self._pending_promotions[execution_id] = _PendingPromotion(
                        session_dir, plans, exc.approval_id
                    )
                    self._save_pending_promotions()
                    retain_session = True
                    self.metrics.increment("approval_required")
                    self._emit(ExecutionEventType.APPROVAL_REQUIRED, execution_id, {
                        "approval_id": exc.approval_id, "promotion": "pending",
                    })
                    self.audit_log.record(
                        execution_id=execution_id, operation="promote",
                        status="approval_required", approval_id=exc.approval_id,
                    )
                    raise
            self.metrics.increment(result.status)
            event_type = {
                "completed": ExecutionEventType.COMPLETED,
                "timed_out": ExecutionEventType.TIMED_OUT,
                "output_limit_exceeded": ExecutionEventType.OUTPUT_LIMIT_EXCEEDED,
            }.get(result.status, ExecutionEventType.FAILED)
            self._emit(event_type, execution_id, {"exit_code": result.exit_code})
            self.audit_log.record(
                execution_id=execution_id, operation="execute", status=result.status,
                exit_code=result.exit_code, approval_scope=request.approval_scope(),
            )
            return result
        except Exception as exc:
            self.metrics.increment("failed")
            self._emit(ExecutionEventType.FAILED, execution_id, {"error": str(exc)})
            self.audit_log.record(
                execution_id=execution_id, operation="execute", status="failed",
                error=str(exc), approval_scope=request.approval_scope(),
            )
            raise
        finally:
            if not retain_session:
                shutil.rmtree(session_dir, ignore_errors=True)

    def resume_promotion(self, execution_id: str, *, approval_id: str) -> dict[str, object]:
        """Finish a promotion approval while retaining the original session."""
        pending = self._pending_promotions.get(execution_id)
        if pending is None:
            raise KeyError(f"Unknown pending execution promotion: {execution_id}")
        try:
            results = self.artifact_promoter.promote_many(  # type: ignore[union-attr]
                pending.plans, approval_id=approval_id
            )
            self.audit_log.record(
                execution_id=execution_id, operation="promote", status="completed",
                artifact_count=len(results),
            )
            self._emit(ExecutionEventType.COMPLETED, execution_id, {
                "promotion": "completed", "artifact_count": len(results),
            })
            self._pending_promotions.pop(execution_id, None)
            self._save_pending_promotions()
            return {"execution_id": execution_id, "status": "promoted", "artifacts": results}
        except Exception:
            self._save_pending_promotions()
            raise
        else:
            shutil.rmtree(pending.session_dir, ignore_errors=True)

    def resume_promotion_by_approval(self, approval_id: str) -> dict[str, object]:
        for execution_id, pending in self._pending_promotions.items():
            if pending.approval_id == approval_id:
                return self.resume_promotion(execution_id, approval_id=approval_id)
        raise KeyError(f"Unknown pending promotion approval: {approval_id}")

    def _save_pending_promotions(self) -> None:
        if self.pending_store is None:
            return
        self.pending_store.parent.mkdir(parents=True, exist_ok=True)
        data = {
            execution_id: {
                        "session_dir": str(pending.session_dir),
                        "approval_id": pending.approval_id,
                "plans": [
                    {
                        "source_path": str(plan.source_path),
                        "source_relative_path": plan.source_relative_path,
                        "source_sha256": plan.source_sha256,
                        "size_bytes": plan.size_bytes,
                        "destination_root": plan.destination_root,
                        "destination_path": plan.destination_path,
                    }
                    for plan in pending.plans
                ],
            }
            for execution_id, pending in self._pending_promotions.items()
        }
        temporary = self.pending_store.with_suffix(self.pending_store.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.pending_store)

    def _load_pending_promotions(self) -> None:
        if self.pending_store is None or not self.pending_store.exists():
            return
        data = json.loads(self.pending_store.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("Execution pending store must contain a JSON object.")
        for execution_id, raw in data.items():
            if not isinstance(execution_id, str) or not isinstance(raw, dict):
                continue
            session_dir = Path(raw.get("session_dir", ""))
            raw_plans = raw.get("plans", [])
            if not session_dir.is_absolute() or not isinstance(raw_plans, list):
                continue
            plans: list[PromotionPlan] = []
            for item in raw_plans:
                if not isinstance(item, dict):
                    continue
                plans.append(PromotionPlan(
                    source_path=Path(item["source_path"]),
                    source_relative_path=item["source_relative_path"],
                    source_sha256=item["source_sha256"],
                    size_bytes=int(item["size_bytes"]),
                    destination_root=item["destination_root"],
                    destination_path=item["destination_path"],
                ))
            if plans:
                self._pending_promotions[execution_id] = _PendingPromotion(
                    session_dir, tuple(plans), raw.get("approval_id")
                )

    def _emit(self, event_type: ExecutionEventType, execution_id: str, payload: dict[str, object]) -> None:
        if self.event_publisher is not None:
            self.event_publisher(ExecutionEvent(event_type, execution_id, payload))

    def _require_approval(self, request: ExecutionRequest) -> None:
        if self.approval_manager is None:
            raise ExecutionApprovalRequired("Execution requires approval.")
        scope = request.approval_scope()
        if request.approval_id is None:
            record = self.approval_manager.create(
                session_id=self.session_id,
                operation="execute",
                root="execution",
                path=scope,
                destination_path=f"network:{request.network.value}",
            )
            if self.approval_notifier is not None:
                self.approval_notifier(record)
            raise ExecutionApprovalRequired("Execution requires approval.", approval_id=record.approval_id)
        self.approval_manager.consume(
            request.approval_id,
            session_id=self.session_id,
            operation="execute",
            root="execution",
            path=scope,
            destination_path=f"network:{request.network.value}",
        )

    @classmethod
    def _validate_mounts(cls, mounts: tuple[MountSpec, ...]) -> None:
        for mount in mounts:
            if not any(
                mount.target == prefix or mount.target.startswith(prefix + "/")
                for prefix in cls._ALLOWED_MOUNT_PREFIXES
            ):
                raise PermissionError(f"Mount target is outside the execution namespace: {mount.target}")
