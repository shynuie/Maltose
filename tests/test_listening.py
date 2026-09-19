import tempfile
import unittest
from pathlib import Path

from myagent.voice import UtteranceSegmenter, VADSettings
from myagent.voice.listening import Utterance, write_utterance_wav


class FakeDetector:
    def __init__(self, values: list[bool]) -> None:
        self._values = values

    def is_speech(self, _pcm_frame: bytes, _sample_rate: int) -> bool:
        if not self._values:
            return False
        return self._values.pop(0)


class UtteranceSegmenterTest(unittest.TestCase):
    def test_rejects_unsupported_frame_ms(self) -> None:
        with self.assertRaisesRegex(ValueError, "frame_ms"):
            VADSettings(frame_ms=25)

    def test_rounds_thresholds_up_to_frames(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=161,
            end_silence_ms=701,
            pre_roll_ms=301,
        )

        self.assertEqual(settings.start_trigger_frames, 9)
        self.assertEqual(settings.end_silence_frames, 36)
        self.assertEqual(settings.pre_roll_frames, 16)

    def test_segments_speech_after_silence_threshold(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=40,
            end_silence_ms=40,
            pre_roll_ms=40,
        )
        detector = FakeDetector([False, True, True, True, False, False])
        segmenter = UtteranceSegmenter(detector, settings)
        frame = b"\0" * settings.frame_byte_count

        events = []
        for _ in range(6):
            events.extend(segmenter.process_frame(frame))

        self.assertEqual([event.kind for event in events], ["speech_started", "speech_ended"])
        self.assertIsNotNone(events[1].utterance)
        self.assertEqual(len(events[1].utterance.pcm), settings.frame_byte_count * 5)

    def test_rejects_wrong_frame_size(self) -> None:
        settings = VADSettings()
        segmenter = UtteranceSegmenter(FakeDetector([]), settings)

        with self.assertRaisesRegex(ValueError, "Expected"):
            segmenter.process_frame(b"\0")

    def test_keeps_trigger_frames_without_pre_roll(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=40,
            end_silence_ms=20,
            pre_roll_ms=0,
        )
        detector = FakeDetector([True, True, False])
        segmenter = UtteranceSegmenter(detector, settings)
        frame = b"\0" * settings.frame_byte_count

        events = []
        for _ in range(3):
            events.extend(segmenter.process_frame(frame))

        self.assertEqual([event.kind for event in events], ["speech_started", "speech_ended"])
        self.assertEqual(len(events[1].utterance.pcm), settings.frame_byte_count * 3)


class WriteUtteranceWavTest(unittest.TestCase):
    def test_writes_wav_file(self) -> None:
        utterance = Utterance(
            pcm=b"\0" * 320,
            sample_rate=16000,
            sample_width=2,
            channels=1,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utterance.wav"
            write_utterance_wav(path, utterance)

            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, len(utterance.pcm))


if __name__ == "__main__":
    unittest.main()
