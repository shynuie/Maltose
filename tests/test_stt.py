from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import tempfile
import unittest

from myagent.voice import FasterWhisperSTT, STTRequest, normalize_mandarin_transcript


class NormalizeMandarinTranscriptTest(unittest.TestCase):
    def test_normalizes_ascii_punctuation(self) -> None:
        self.assertEqual(
            normalize_mandarin_transcript("好,來工作吧! OK?"),
            "好，來工作吧！ OK？",
        )


class FasterWhisperSTTTest(unittest.TestCase):
    def test_rejects_missing_audio_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            FasterWhisperSTT().transcribe(STTRequest(audio_path=Path("missing.wav")))

    def test_rejects_invalid_beam_size(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with self.assertRaisesRegex(ValueError, "beam_size"):
                FasterWhisperSTT().transcribe(
                    STTRequest(audio_path=Path(audio.name), beam_size=0)
                )

    @patch("faster_whisper.WhisperModel")
    def test_transcribes_with_mandarin_defaults(self, whisper_model) -> None:
        model = MagicMock()
        model.transcribe.return_value = (
            [
                SimpleNamespace(start=0.0, end=1.2, text=" 你好"),
                SimpleNamespace(start=1.2, end=2.4, text=",今天測試."),
            ],
            SimpleNamespace(language="zh", duration=2.4),
        )
        whisper_model.return_value = model

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            result = FasterWhisperSTT().transcribe(STTRequest(audio_path=Path(audio.name)))

        whisper_model.assert_called_once_with("small", device="cpu", compute_type="int8")
        model.transcribe.assert_called_once()
        _, kwargs = model.transcribe.call_args
        self.assertEqual(kwargs["language"], "zh")
        self.assertEqual(kwargs["beam_size"], 5)
        self.assertEqual(result.text, "你好，今天測試。")
        self.assertEqual(result.language, "zh")
        self.assertEqual(result.duration, 2.4)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[1].text, "，今天測試。")


if __name__ == "__main__":
    unittest.main()
