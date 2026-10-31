"""Explicit Agent tool adapter for the isolated execution broker."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from maltose.agent.capabilities import CapabilityTool
from maltose.execution.backend import MountSpec
from maltose.execution.broker import ExecutionBroker
from maltose.execution.models import ExecutionLimits, ExecutionProfile, ExecutionRequest, NetworkPolicy, OutputArtifact


class ExecutionToolAdapter:
    def __init__(
        self,
        broker: ExecutionBroker,
        *,
        working_root: str | None = None,
        readable_roots: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.broker = broker
        self.working_root = working_root
        self.readable_roots = readable_roots

    def tools(self) -> list[CapabilityTool]:
        return [CapabilityTool(
            name="execute_command",
            description="Run an argv command only inside the configured isolated execution sandbox.",
            parameters={
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "profile": {"type": "string", "enum": ["safe", "workspace", "privileged"]},
                    "network": {"type": "string", "enum": ["off", "restricted", "approved"]},
                    "allowed_domains": {"type": "array", "items": {"type": "string"}},
                    "input_paths": {"type": "array", "items": {"type": "string"}},
                    "outputs": {"type": "array", "items": {"type": "object"}},
                    "timeout_seconds": {"type": "number", "minimum": 1},
                    "approval_id": {"type": "string"},
                },
                "required": ["argv"],
            },
            handler=self._execute,
        )]

    def _execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_argv = arguments.get("argv")
        if not isinstance(raw_argv, list) or not all(isinstance(item, str) for item in raw_argv):
            raise ValueError("argv must be a list of strings.")
        raw_outputs = arguments.get("outputs", [])
        if not isinstance(raw_outputs, list):
            raise ValueError("outputs must be a list.")
        if not all(isinstance(item, dict) for item in raw_outputs):
            raise ValueError("each output must be an object.")
        outputs = tuple(OutputArtifact(
            path=item["path"],
            destination_root=item.get("destination_root"),
            destination_path=item.get("destination_path"),
            sha256=item.get("sha256"),
            content_type=item.get("content_type"),
        ) for item in raw_outputs)
        timeout = float(arguments.get("timeout_seconds", 30.0))
        request = ExecutionRequest(
            tuple(raw_argv),
            profile=ExecutionProfile(arguments.get("profile", "workspace")),
            network=NetworkPolicy(arguments.get("network", "off")),
            allowed_domains=tuple(arguments.get("allowed_domains", [])),
            input_paths=tuple(arguments.get("input_paths", [])),
            outputs=outputs,
            limits=ExecutionLimits(timeout_seconds=timeout),
            approval_id=arguments.get("approval_id"),
        )
        mounts: tuple[MountSpec, ...] = ()
        if request.profile is ExecutionProfile.WORKSPACE and self.working_root is not None:
            mounts = (MountSpec(Path(self.working_root).resolve(), "/workspace", read_only=False),)
            roots = dict(self.readable_roots)
            for reference in request.input_paths:
                name, separator, relative = reference.partition(":")
                if not separator or name not in roots or not relative:
                    raise ValueError("input_paths must use an allowed root:path reference.")
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise PermissionError("input path must stay inside its readable root.")
                root_path = Path(roots[name]).resolve()
                source = (root_path / relative_path).resolve(strict=False)
                try:
                    source.relative_to(root_path)
                except ValueError as exc:
                    raise PermissionError("input path escapes its readable root.") from exc
                target_relative = relative_path.as_posix()
                if target_relative == ".":
                    target_relative = ""
                mounts += (MountSpec(source, f"/inputs/{name}/{target_relative}".rstrip("/"), read_only=True),)
        return asdict(self.broker.execute(request, mounts=mounts))
