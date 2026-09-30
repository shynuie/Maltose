from __future__ import annotations

import unittest

from myagent.agent.taskbrain import TaskBrain


class UIToolTest(unittest.TestCase):
    def test_ui_tools_are_opt_in_and_publish_typed_blocks(self) -> None:
        published: list[tuple[str, dict[str, object]]] = []
        brain = TaskBrain(
            model=object(),
            ui_publisher=lambda block_type, payload: published.append((block_type, payload)),
        )

        self.assertTrue(brain.tools.has("display_ui_links"))
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

    def test_ui_tools_are_not_added_without_a_ui_publisher(self) -> None:
        brain = TaskBrain(model=object())
        self.assertFalse(brain.tools.has("display_ui_card"))

