from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import tempfile
import unittest

from myagent.voice import (
    FasterWhisperSTT,
    FunASRNanoSTT,
    Qwen3ASRSTT,
    STTRequest,
    create_stt_provider,
    normalize_mandarin_transcript,
)


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


class FunASRNanoSTTTest(unittest.TestCase):
    def test_generates_transcript_and_caches_model(self) -> None:
        model = MagicMock()
        model.generate.return_value = [{"text": "你好,今天測試."}]
        auto_model = MagicMock(return_value=model)

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with patch.dict(sys.modules, {"funasr": SimpleNamespace(AutoModel=auto_model)}):
                provider = FunASRNanoSTT()
                result = provider.transcribe(STTRequest(audio_path=Path(audio.name)))
                provider.transcribe(STTRequest(audio_path=Path(audio.name)))

        auto_model.assert_called_once()
        self.assertEqual(model.generate.call_count, 2)
        self.assertEqual(result.text, "你好，今天測試。")

    def test_factory_uses_nano_default_model(self) -> None:
        provider = create_stt_provider(provider="fun-asr-nano")
        self.assertIsInstance(provider, FunASRNanoSTT)
        self.assertEqual(provider.model_name, "FunAudioLLM/Fun-ASR-Nano-2512")


class Qwen3ASRSTTTest(unittest.TestCase):
    def test_transcribes_with_lazy_qwen_model(self) -> None:
        model = MagicMock()
        model.transcribe.return_value = [
            SimpleNamespace(language="English", text="My aunt opened the curtains.")
        ]
        qwen_class = MagicMock()
        qwen_class.from_pretrained.return_value = model
        qwen_module = SimpleNamespace(Qwen3ASRModel=qwen_class)
        torch_module = SimpleNamespace(float16="float16", float32="float32")

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with patch.dict(
                sys.modules,
                {"qwen_asr": qwen_module, "torch": torch_module},
            ):
                provider = Qwen3ASRSTT()
                result = provider.transcribe(
                    STTRequest(audio_path=Path(audio.name), language="en")
                )

        qwen_class.from_pretrained.assert_called_once()
        _, kwargs = qwen_class.from_pretrained.call_args
        self.assertEqual(kwargs["device_map"], "cpu")
        model.transcribe.assert_called_once_with(
            audio=str(Path(audio.name)), language="English"
        )
        self.assertEqual(result.text, "My aunt opened the curtains。")

    def test_warmup_runs_silent_inference(self) -> None:
        provider = Qwen3ASRSTT()
        provider.transcribe = MagicMock()  # type: ignore[method-assign]
        provider.warmup()
        provider.transcribe.assert_called_once()
        request = provider.transcribe.call_args.args[0]
        self.assertEqual(request.language, "zh")


if __name__ == "__main__":
    unittest.main()
