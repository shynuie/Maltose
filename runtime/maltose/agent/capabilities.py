"""Adapters for exposing explicitly registered external capabilities as tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import selectors
import subprocess
import threading
import tomllib
from pathlib import Path
from typing import Any, Callable, Protocol


CapabilityHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class CapabilityTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: CapabilityHandler


class CapabilityAdapter(Protocol):
    def tools(self) -> list[CapabilityTool]:
        """Return explicitly exposed tools."""
        ...


def register_capability_adapter(
    registry: Any,
    adapter: CapabilityAdapter,
    *,
    prefix: str = "",
) -> None:
    """Expose adapter tools without allowing duplicate or implicit capabilities."""
    for tool in adapter.tools():
        name = f"{prefix}{tool.name}" if prefix else tool.name
        registry.register(name, tool.description, tool.parameters, tool.handler)


class StaticSkillAdapter:
    """Expose application-owned skill handlers described by explicit metadata."""

    def __init__(
        self,
        definitions: list[dict[str, Any]],
        handlers: dict[str, CapabilityHandler],
    ) -> None:
        self._tools: list[CapabilityTool] = []
        for definition in definitions:
            name = definition.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("Skill tool name must be a non-empty string.")
            handler = handlers.get(name)
            if handler is None:
                raise ValueError(f"No registered handler for skill tool: {name}")
            parameters = definition.get("parameters", {"type": "object"})
            if not isinstance(parameters, dict):
                raise ValueError(f"Skill tool parameters must be an object: {name}")
            self._tools.append(
                CapabilityTool(
                    name=name,
                    description=str(definition.get("description", name)),
                    parameters=parameters,
                    handler=handler,
                )
            )

    def tools(self) -> list[CapabilityTool]:
        return list(self._tools)


class MCPClient(Protocol):
    def list_tools(self) -> list[dict[str, Any]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...


class MCPToolAdapter:
    """Map an already-connected MCP client into the local tool registry."""

    def __init__(self, client: MCPClient, *, prefix: str = "") -> None:
        self.client = client
        self.prefix = prefix

    def tools(self) -> list[CapabilityTool]:
        result: list[CapabilityTool] = []
        for definition in self.client.list_tools():
            name = definition.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("MCP tool name must be a non-empty string.")
            schema = definition.get("inputSchema", {"type": "object"})
            if not isinstance(schema, dict):
                raise ValueError(f"MCP inputSchema must be an object: {name}")

            def call(arguments: dict[str, Any], tool_name: str = name) -> Any:
                return self.client.call_tool(tool_name, arguments)

            result.append(
                CapabilityTool(
                    name=f"{self.prefix}{name}" if self.prefix else name,
                    description=str(definition.get("description", name)),
                    parameters=schema,
                    handler=call,
                )
            )
        return result


class MCPStdioClient:
    """Small stdio JSON-RPC MCP client using an explicit argv command."""

    def __init__(
        self,
        command: list[str],
        *,
        timeout: float = 15.0,
        protocol_version: str = "2024-11-05",
    ) -> None:
        if not command:
            raise ValueError("MCP command cannot be empty.")
        if timeout <= 0:
            raise ValueError("MCP timeout must be positive.")
        self.timeout = timeout
        self.protocol_version = protocol_version
        self._lock = threading.RLock()
        self._next_id = 0
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start MCP server: {exc}") from exc
        self._initialize()

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "maltose", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise RuntimeError("MCP server stdin is unavailable.")
        self._process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        )
        self._process.stdin.flush()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            if self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("MCP server pipes are unavailable.")
            self._process.stdin.write(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }) + "\n"
            )
            self._process.stdin.flush()
            selector = selectors.DefaultSelector()
            try:
                selector.register(self._process.stdout, selectors.EVENT_READ)
                while True:
                    ready = selector.select(self.timeout)
                    if not ready:
                        raise TimeoutError(f"MCP request timed out: {method}")
                    line = self._process.stdout.readline()
                    if not line:
                        raise RuntimeError("MCP server closed its stdout.")
                    message = json.loads(line)
                    if message.get("id") != request_id:
                        continue
                    if "error" in message:
                        raise RuntimeError(f"MCP error for {method}: {message['error']}")
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise RuntimeError(f"MCP response was not an object: {method}")
                    return result
            finally:
                selector.close()

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list returned an invalid tools field.")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if "structuredContent" in result:
            return result["structuredContent"]
        return result.get("content", result)

    def close(self) -> None:
        process = self._process
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


class SkillManifestLoader:
    """Load TOML tool metadata while requiring handlers from application code."""

    @staticmethod
    def load(path: str | Path, handlers: dict[str, CapabilityHandler]) -> StaticSkillAdapter:
        manifest_path = Path(path)
        with manifest_path.open("rb") as stream:
            document = tomllib.load(stream)
        skill = document.get("skill")
        if not isinstance(skill, dict) or not skill.get("name"):
            raise ValueError(f"Skill manifest needs [skill].name: {manifest_path}")
        definitions = skill.get("tools", document.get("tools", []))
        if not isinstance(definitions, list):
            raise ValueError(f"Skill manifest tools must be an array: {manifest_path}")
        return StaticSkillAdapter(definitions, handlers)

    @staticmethod
    def load_directory(
        directory: str | Path,
        handlers: dict[str, CapabilityHandler],
    ) -> list[StaticSkillAdapter]:
        return [
            SkillManifestLoader.load(path, handlers)
            for path in sorted(Path(directory).glob("*.toml"))
        ]
