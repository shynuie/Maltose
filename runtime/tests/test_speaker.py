from __future__ import annotations

import tempfile
import time
import unittest
from array import array
from pathlib import Path

from myagent.voice import (
    ProfileSpeakerIdentifier,
    SpeakerIdentityManager,
    SpeakerProfileStore,
    SpeakerResult,
    Utterance,
    evaluate_enrollment_utterance,
)


class FakeEncoder:
    model_name = "fake-model"

    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding

    def encode(self, _audio_path: Path) -> list[float]:
        return self.embedding


class SpeakerProfileStoreTest(unittest.TestCase):
    def test_next_user_id_is_sequential_and_does_not_reuse_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                self.assertEqual(store.next_user_id(), "user-001")
                store.enroll("user-001", [[1.0, 0.0]], model_name="fake-model")
                self.assertEqual(store.next_user_id(), "user-002")
                store.enroll("user-009", [[0.0, 1.0]], model_name="fake-model")
                self.assertEqual(store.next_user_id(), "user-003")
                self.assertEqual(store.next_user_id(), "user-004")
            finally:
                store.close()

    def test_identity_manager_applies_hysteresis_without_blocking_submit(self) -> None:
        class SequenceIdentifier:
            def __init__(self) -> None:
                self.results = [
                    SpeakerResult("marvin", 0.45, "identified"),
                    SpeakerResult("alice", 0.30, "identified"),
                    SpeakerResult("alice", 0.10, "identified"),
                ]

            def identify(self, _audio_path: Path) -> SpeakerResult:
                return self.results.pop(0)

        manager = SpeakerIdentityManager(
            SequenceIdentifier(), low_threshold=0.2, high_threshold=0.4
        )
        try:
            for expected in (
                SpeakerResult("marvin", 0.45, "identified"),
                SpeakerResult("marvin", 0.30, "ambiguous"),
                SpeakerResult(None, 0.10, "unknown"),
            ):
                future = manager.submit(Path("unused.wav"))
                future.result(timeout=1)
                deadline = time.monotonic() + 1
                while manager.snapshot() != expected and time.monotonic() < deadline:
                    time.sleep(0.001)
                self.assertEqual(manager.snapshot(), expected)
        finally:
            manager.close()

    def test_peek_does_not_consume_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                self.assertEqual(store.peek_next_user_id(), "user-001")
                self.assertEqual(store.peek_next_user_id(), "user-001")
                self.assertEqual(store.next_user_id(), "user-001")
                self.assertEqual(store.peek_next_user_id(), "user-002")
            finally:
                store.close()

    def test_enroll_averages_and_replaces_a_user_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                result = store.enroll(
                    "marvin",
                    [[1.0, 0.0], [0.8, 0.6]],
                    model_name="fake-model",
                )
                self.assertEqual(result["user_id"], "marvin")
                self.assertEqual(result["sample_count"], 2)
                self.assertEqual(len(store.profiles()), 1)
                self.assertEqual(len(store.profile_embeddings()[0][1]), 2)

                replacement = store.enroll(
                    "marvin", [[0.0, 1.0]], model_name="fake-model"
                )
                self.assertEqual(replacement["sample_count"], 1)
                self.assertEqual(len(store.profiles()), 1)
            finally:
                store.close()

    def test_enrollment_quality_rejects_short_and_quiet_audio(self) -> None:
        short = Utterance(array("h", [5000] * 400).tobytes(), 16000, 2, 1)
        quiet = Utterance(array("h", [10] * 32000).tobytes(), 16000, 2, 1)
        self.assertFalse(evaluate_enrollment_utterance(short).valid)
        self.assertFalse(evaluate_enrollment_utterance(quiet).valid)

    def test_enrollment_quality_accepts_clear_audio(self) -> None:
        clear = Utterance(array("h", [5000] * 32000).tobytes(), 16000, 2, 1)
        result = evaluate_enrollment_utterance(clear)
        self.assertTrue(result.valid)
        self.assertIsNone(result.reason)

    def test_identifier_returns_unknown_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                store.enroll("marvin", [[1.0, 0.0]], model_name="fake-model")
                unknown = ProfileSpeakerIdentifier(
                    store, FakeEncoder([0.0, 1.0]), threshold=0.8
                ).identify(Path("unused.wav"))
                self.assertIsNone(unknown.user_id)
                self.assertEqual(unknown.status, "unknown")
                self.assertAlmostEqual(unknown.score or 0.0, 0.0)
            finally:
                store.close()

    def test_identifier_matches_best_known_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                store.enroll("marvin", [[1.0, 0.0]], model_name="fake-model")
                store.enroll("alice", [[0.0, 1.0]], model_name="fake-model")
                result = ProfileSpeakerIdentifier(
                    store, FakeEncoder([0.9, 0.1]), threshold=0.8
                ).identify(Path("unused.wav"))
                self.assertEqual(result.user_id, "marvin")
                self.assertEqual(result.status, "identified")
                self.assertGreater(result.score or 0.0, 0.8)
            finally:
                store.close()

    def test_identifier_uses_highest_enrollment_sample_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.sqlite3")
            try:
                store.enroll(
                    "marvin",
                    [[1.0, 0.0], [0.0, 1.0]],
                    model_name="fake-model",
                )
                result = ProfileSpeakerIdentifier(
                    store, FakeEncoder([0.0, 1.0]), threshold=0.8
                ).identify(Path("unused.wav"))
                self.assertEqual(result.user_id, "marvin")
                self.assertAlmostEqual(result.score or 0.0, 1.0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
