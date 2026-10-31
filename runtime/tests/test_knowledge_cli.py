from __future__ import annotations

import unittest

from maltose.knowledge.cli import build_parser


class KnowledgeCliParserTests(unittest.TestCase):
    def test_watch_command_accepts_runtime_options(self) -> None:
        args = build_parser().parse_args([
            "--documents-root", "documents",
            "--queue", "data/knowledge/queue.sqlite3",
            "watch",
            "--poll-interval", "2.5",
            "--max-attempts", "4",
        ])

        self.assertEqual(args.command, "watch")
        self.assertEqual(args.poll_interval, 2.5)
        self.assertEqual(args.max_attempts, 4)
        self.assertEqual(args.queue.name, "queue.sqlite3")

    def test_queue_command_accepts_status_filter(self) -> None:
        args = build_parser().parse_args(["queue", "--status", "failed"])
        self.assertEqual(args.command, "queue")
        self.assertEqual(args.status, "failed")


if __name__ == "__main__":
    unittest.main()
