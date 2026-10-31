import tempfile
import unittest
import wave
from pathlib import Path

from myagent.voice.kws_record_cli import append_metadata, next_recording_path, write_pcm_wav


class KWSRecordTest(unittest.TestCase):
    def test_writes_mono_16_bit_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            pcm = b"\x01\x00" * 160
            write_pcm_wav(path, pcm, sample_rate=16000)

            with wave.open(str(path), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 16000)
                self.assertEqual(wav_file.readframes(160), pcm)

    def test_uses_indexed_positive_filename(self) -> None:
        path = next_recording_path(Path("recordings/kws/positive"), 3)
        self.assertEqual(path.parent, Path("recordings/kws/positive"))
        self.assertIn("kws-positive-003-", path.name)
        self.assertTrue(path.name.endswith(".wav"))

    def test_uses_indexed_negative_filename(self) -> None:
        path = next_recording_path(Path("recordings/kws/negative"), 2, kind="negative")
        self.assertIn("kws-negative-002-", path.name)

    def test_appends_jsonl_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.jsonl"
            append_metadata(path, {"path": "sample.wav", "distance": "far"})
            self.assertEqual(path.read_text(encoding="utf-8").strip(), '{"path": "sample.wav", "distance": "far"}')
