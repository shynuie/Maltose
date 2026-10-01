from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.curation import CurationAuditLog


class CurationAuditPolicyTests(unittest.TestCase):
    def test_repair_counts_invalid_events_and_rotation_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            path.write_text(json.dumps({"event": "ok"}) + "\nnot-json\n", encoding="utf-8")
            audit = CurationAuditLog(path)
            self.assertEqual(audit.repair(), {"valid": 1, "invalid": 1})
            archive = audit.rotate(max_bytes=1)
            self.assertIsNotNone(archive)
            self.assertTrue(archive.exists())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
