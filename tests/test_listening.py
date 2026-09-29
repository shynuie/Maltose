import tempfile
import unittest
from pathlib import Path

from myagent.voice import (
    GainWakeWordDetector,
    SmoothRMSGainWakeWordDetector,
    UtteranceSegmenter,
    VADSettings,
    measure_utterance,
    normalize_pcm_peak,
    normalize_utterance_peak,
)
from myagent.voice.listening import KWSFrameAccumulator, Utterance, write_utterance_wav
from myagent.voice.wake import WakeWordGate, WakeWordHit, load_wake_word_config


class FakeDetector:
    def __init__(self, values: list[bool]) -> None:
        self._values = values

    def is_speech(self, _pcm_frame: bytes, _sample_rate: int) -> bool:
        if not self._values:
            return False
        return self._values.pop(0)


class FakeWakeDetector:
    def __init__(self) -> None:
        self.reset_count = 0

    def process_frame(self, _pcm_frame: bytes, _sample_rate: int) -> WakeWordHit:
        return WakeWordHit(keyword="小助手")

    def reset(self) -> None:
        self.reset_count += 1


class CapturingWakeDetector:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def process_frame(self, pcm_frame: bytes, _sample_rate: int) -> WakeWordHit | None:
        self.frames.append(pcm_frame)
        return None

    def reset(self) -> None:
        pass


class UtteranceSegmenterTest(unittest.TestCase):
    def test_kws_frame_accumulator_rechunks_vad_frames(self) -> None:
        accumulator = KWSFrameAccumulator(frame_byte_count=6)

        self.assertEqual(accumulator.push(b"1234"), [])
        self.assertEqual(accumulator.push(b"5678"), [b"123456"])
        self.assertEqual(accumulator.push(b"90ab"), [b"7890ab"])

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

    def test_tracks_in_speech_state(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=20,
            end_silence_ms=20,
            pre_roll_ms=0,
        )
        detector = FakeDetector([True, False])
        segmenter = UtteranceSegmenter(detector, settings)
        frame = b"\0" * settings.frame_byte_count

        self.assertFalse(segmenter.in_speech)
        segmenter.process_frame(frame)
        self.assertTrue(segmenter.in_speech)
        segmenter.process_frame(frame)
        self.assertFalse(segmenter.in_speech)

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

    def test_can_seed_utterance_with_wake_buffer_frames(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=20,
            end_silence_ms=20,
            pre_roll_ms=0,
        )
        detector = FakeDetector([False])
        segmenter = UtteranceSegmenter(detector, settings)
        wake_frame = b"\1" * settings.frame_byte_count
        silence_frame = b"\0" * settings.frame_byte_count

        events = segmenter.start_with_frames([wake_frame])
        events.extend(segmenter.process_frame(silence_frame))

        self.assertEqual([event.kind for event in events], ["speech_started", "speech_ended"])
        assert events[1].utterance is not None
        self.assertTrue(events[1].utterance.pcm.startswith(wake_frame))

    def test_can_prepend_wake_buffer_after_speech_starts(self) -> None:
        settings = VADSettings(
            frame_ms=20,
            start_trigger_ms=20,
            end_silence_ms=20,
            pre_roll_ms=0,
        )
        detector = FakeDetector([True, False])
        segmenter = UtteranceSegmenter(detector, settings)
        wake_frame = b"\1" * settings.frame_byte_count
        speech_frame = b"\2" * settings.frame_byte_count
        silence_frame = b"\0" * settings.frame_byte_count

        events = segmenter.process_frame(speech_frame)
        segmenter.prepend_frames([wake_frame])
        events.extend(segmenter.process_frame(silence_frame))

        self.assertEqual([event.kind for event in events], ["speech_started", "speech_ended"])
        assert events[1].utterance is not None
        self.assertTrue(events[1].utterance.pcm.startswith(wake_frame + speech_frame))


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


class NormalizeUtterancePeakTest(unittest.TestCase):
    def test_amplifies_quiet_utterance_to_target_peak(self) -> None:
        utterance = Utterance(
            pcm=(1000).to_bytes(2, "little", signed=True) * 10,
            sample_rate=16000,
            sample_width=2,
            channels=1,
        )

        result = normalize_utterance_peak(
            utterance,
            target_peak=12000,
            min_peak=6000,
            max_gain=4.0,
        )

        self.assertEqual(result.before.peak, 1000)
        self.assertEqual(result.after.peak, 4000)
        self.assertEqual(result.gain, 4.0)

    def test_keeps_loud_enough_utterance_unchanged(self) -> None:
        utterance = Utterance(
            pcm=(7000).to_bytes(2, "little", signed=True) * 10,
            sample_rate=16000,
            sample_width=2,
            channels=1,
        )

        result = normalize_utterance_peak(utterance)

        self.assertEqual(result.gain, 1.0)
        self.assertEqual(result.utterance, utterance)
        self.assertEqual(measure_utterance(result.utterance).peak, 7000)

    def test_normalizes_raw_pcm_peak(self) -> None:
        pcm = (1000).to_bytes(2, "little", signed=True) * 10

        normalized, gain, before_peak, after_peak = normalize_pcm_peak(
            pcm,
            target_peak=12000,
            min_peak=6000,
            max_gain=4.0,
        )

        self.assertEqual(gain, 4.0)
        self.assertEqual(before_peak, 1000)
        self.assertEqual(after_peak, 4000)
        self.assertNotEqual(normalized, pcm)


class WakeWordGateTest(unittest.TestCase):
    def test_resets_detector_after_wake_hit(self) -> None:
        detector = FakeWakeDetector()
        gate = WakeWordGate(detector)

        hit = gate.process_frame(b"\0" * 320, 16000)

        self.assertEqual(hit, WakeWordHit(keyword="小助手"))
        self.assertEqual(detector.reset_count, 1)

    def test_loads_wake_word_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "wake.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[wake]",
                        'provider = "sherpa-onnx"',
                        "",
                        "[wake.sherpa_onnx]",
                        'tokens = "tokens.txt"',
                        'encoder = "encoder.onnx"',
                        'decoder = "decoder.onnx"',
                        'joiner = "joiner.onnx"',
                        'keywords_file = "keywords.txt"',
                        "keywords_threshold = 0.35",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_wake_word_config(config_path)

            self.assertTrue(config.enabled)
            self.assertEqual(config.provider, "sherpa-onnx")
            self.assertIsNotNone(config.sherpa_onnx)
            assert config.sherpa_onnx is not None
            self.assertEqual(config.sherpa_onnx.tokens, Path(directory) / "tokens.txt")
            self.assertEqual(config.sherpa_onnx.keywords_threshold, 0.35)
            self.assertTrue(config.normalize_audio)
            self.assertEqual(config.target_peak, 12000)

    def test_gain_wake_detector_normalizes_before_detection(self) -> None:
        detector = CapturingWakeDetector()
        gain_detector = GainWakeWordDetector(
            detector,
            target_peak=12000,
            min_peak=6000,
            max_gain=4.0,
        )
        pcm = (1000).to_bytes(2, "little", signed=True) * 10

        gain_detector.process_frame(pcm, 16000)

        self.assertEqual(len(detector.frames), 1)
        normalized_utterance = Utterance(detector.frames[0], 16000, 2, 1)
        self.assertEqual(measure_utterance(normalized_utterance).peak, 4000)

    def test_smooth_rms_gain_changes_gradually_and_resets(self) -> None:
        detector = CapturingWakeDetector()
        gain_detector = SmoothRMSGainWakeWordDetector(
            detector,
            target_rms=3000,
            noise_floor=80,
            max_gain=4.0,
            attack=0.5,
            release=0.5,
        )
        quiet_frame = (500).to_bytes(2, "little", signed=True) * 320

        gain_detector.process_frame(quiet_frame, 16000)

        self.assertGreater(gain_detector.gain, 1.0)
        self.assertLess(gain_detector.gain, 4.0)
        self.assertNotEqual(detector.frames[0], quiet_frame)

        gain_detector.reset()
        self.assertEqual(gain_detector.gain, 1.0)


if __name__ == "__main__":
    unittest.main()
