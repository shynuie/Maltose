from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.watcher import (
    DocumentWatchEventType,
    PollingDocumentWatcher,
)


class PollingDocumentWatcherTests(unittest.TestCase):
    def test_first_poll_only_initializes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "note.txt").write_text("one", encoding="utf-8")
            watcher = PollingDocumentWatcher(root)

            self.assertEqual(watcher.poll(), ())

            (root / "new.md").write_text("new", encoding="utf-8")
            events = watcher.poll()
            self.assertEqual([event.type for event in events], [DocumentWatchEventType.CREATED])
            self.assertEqual(events[0].path.name, "new.md")

    def test_poll_reports_modify_delete_and_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.txt"
            note.write_text("one", encoding="utf-8")
            watcher = PollingDocumentWatcher(root)
            watcher.start()

            note.write_text("two", encoding="utf-8")
            events = watcher.poll()
            self.assertEqual(events[0].type, DocumentWatchEventType.MODIFIED)

            moved = root / "archive" / "note.txt"
            moved.parent.mkdir()
            note.rename(moved)
            events = watcher.poll()
            self.assertEqual(events[0].type, DocumentWatchEventType.MOVED)
            self.assertEqual(events[0].previous_path, note.resolve())
            self.assertEqual(events[0].path, moved.resolve())

            moved.unlink()
            events = watcher.poll()
            self.assertEqual(events[0].type, DocumentWatchEventType.DELETED)
            self.assertEqual(events[0].path, moved.resolve())

    def test_stop_causes_next_poll_to_reinitialize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watcher = PollingDocumentWatcher(root)
            watcher.start()
            (root / "note.txt").write_text("one", encoding="utf-8")
            watcher.stop()

            self.assertEqual(watcher.poll(), ())
            (root / "new.txt").write_text("two", encoding="utf-8")
            self.assertEqual(
                watcher.poll()[0].type,
                DocumentWatchEventType.CREATED,
            )


if __name__ == "__main__":
    unittest.main()
