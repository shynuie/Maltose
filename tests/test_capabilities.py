import unittest
import tempfile
from pathlib import Path

from myagent.agent.capabilities import (
    MCPToolAdapter,
    SkillManifestLoader,
    StaticSkillAdapter,
)
from myagent.agent.taskbrain import ToolRegistry


class FakeMCPClient:
    def __init__(self) -> None:
        self.calls = []

    def list_tools(self):
        return [{
            "name": "calendar_create",
            "description": "Create a calendar event.",
            "inputSchema": {"type": "object", "required": ["title"]},
        }]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True}


class CapabilityAdapterTest(unittest.TestCase):
    def test_static_skill_requires_explicit_handler(self) -> None:
        adapter = StaticSkillAdapter(
            [{"name": "greet", "description": "Greet the user."}],
            {"greet": lambda args: f"hello {args['name']}"},
        )
        registry = ToolRegistry()
        from myagent.agent.capabilities import register_capability_adapter

        register_capability_adapter(registry, adapter, prefix="skill_")
        self.assertEqual(registry.execute("skill_greet", {"name": "Marvin"}), "hello Marvin")

    def test_mcp_tools_are_forwarded_to_client(self) -> None:
        client = FakeMCPClient()
        adapter = MCPToolAdapter(client)
        registry = ToolRegistry()
        from myagent.agent.capabilities import register_capability_adapter

        register_capability_adapter(registry, adapter, prefix="mcp_")
        self.assertEqual(registry.execute("mcp_calendar_create", {"title": "Demo"}), {"ok": True})
        self.assertEqual(client.calls, [("calendar_create", {"title": "Demo"})])

    def test_skill_manifest_uses_explicit_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "skill.toml"
            path.write_text(
                """[skill]\nname = \"demo\"\n\n[[skill.tools]]\nname = \"demo_echo\"\ndescription = \"Echo text.\"\n""",
                encoding="utf-8",
            )
            adapter = SkillManifestLoader.load(
                path,
                {"demo_echo": lambda args: args["text"]},
            )
            registry = ToolRegistry()
            from myagent.agent.capabilities import register_capability_adapter

            register_capability_adapter(registry, adapter)
            self.assertEqual(registry.execute("demo_echo", {"text": "ok"}), "ok")


if __name__ == "__main__":
    unittest.main()
