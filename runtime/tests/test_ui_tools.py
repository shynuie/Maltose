from __future__ import annotations

import unittest

from myagent.agent.taskbrain import TaskBrain
from myagent.runtime import PresentationStore


class UIToolTest(unittest.TestCase):
    def test_ui_tools_are_opt_in_and_publish_typed_blocks(self) -> None:
        published: list[tuple[str, dict[str, object]]] = []
        brain = TaskBrain(
            model=object(),
            ui_publisher=lambda block_type, payload: published.append((block_type, payload)),
        )

        self.assertTrue(brain.tools.has("display_ui_links"))
        self.assertTrue(brain.tools.has("display_ui_timeline"))
        self.assertTrue(brain.tools.has("display_ui_table"))
        self.assertTrue(brain.tools.has("display_ui_canvas"))
        result = brain.tools.execute(
            "display_ui_links",
            {
                "title": "资料",
                "links": [{"url": "https://example.com", "label": "Example"}],
            },
        )

        self.assertEqual(result["status"], "displayed")
        self.assertEqual(published[0][0], "ui_links")
        self.assertEqual(published[0][1]["title"], "资料")

    def test_published_block_uses_one_ui_event_type(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        brain = TaskBrain(
            model=object(),
            ui_publisher=lambda block_type, payload: events.append(
                ("ui_block", {"block_type": block_type, **payload})
            ),
        )

        brain.tools.execute(
            "display_ui_card",
            {"title": "测试卡片", "content": "已显示"},
        )

        self.assertEqual(events, [(
            "ui_block",
            {"block_type": "ui_card", "title": "测试卡片", "content": "已显示"},
        )])

    def test_ui_tools_are_not_added_without_a_ui_publisher(self) -> None:
        brain = TaskBrain(model=object())
        self.assertFalse(brain.tools.has("display_ui_card"))

    def test_brain_can_read_current_canvas_state(self) -> None:
        store = PresentationStore()
        brain = TaskBrain(
            model=object(),
            ui_publisher=lambda block_type, payload: store.upsert(block_type, payload),
            ui_state_provider=store.snapshot,
        )
        brain.tools.execute(
            "display_ui_canvas",
            {"scene_id": "scene-1", "elements": [{"type": "node", "id": "a", "label": "A"}]},
        )

        scene = brain.tools.execute("get_canvas_scene", {"scene_id": "scene-1"})

        self.assertEqual(scene["block_id"], "scene-1")
        self.assertEqual(scene["elements"][0]["label"], "A")
