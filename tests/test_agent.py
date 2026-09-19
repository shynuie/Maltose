from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Iterator

from myagent.agent import AgentConfig, AgentState, EchoBrain, VoiceAgent
from myagent.agent.cli import build_parser
from myagent.voice import ListeningEvent, STTRequest, STTResult, TTSRequest, Utterance, VADSettings


class FakeSTT:
    def __init__(self, transcript: str = "測試文字") -> None:
        self.transcript = transcript
        self.transcribe_calls: list[STTRequest] = []

    def transcribe(self, request: STTRequest) -> STTResult:
        self.transcribe_calls.append(request)
        return STTResult(
            text=self.transcript,
            language="zh",
            duration=1.0,
            segments=[],
        )


class FakeTTS:
    def __init__(self) -> None:
        self.synthesize_calls: list[TTSRequest] = []

    def synthesize(self, request: TTSRequest) -> None:
        self.synthesize_calls.append(request)


def _make_fake_utterance() -> Utterance:
    return Utterance(
        pcm=b"\0" * 320,
        sample_rate=16000,
        sample_width=2,
        channels=1,
    )


class EchoBrainTest(unittest.TestCase):
    def test_echoes_with_prefix(self) -> None:
        brain = EchoBrain(prefix="測試前綴：")
        self.assertEqual(brain.process("你好"), "測試前綴：你好")


class VoiceAgentTest(unittest.TestCase):
    def test_shuts_down_on_standby_timeout(self) -> None:
        fake_stt = FakeSTT()
        fake_tts = FakeTTS()

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
        ) -> Iterator[ListeningEvent]:
            yield ListeningEvent(kind="standby_timeout")

        agent = VoiceAgent(
            config=AgentConfig(standby_timeout=5.0),
            brain=EchoBrain(),
            transcriber=fake_stt,
            speaker=fake_tts,
            listener_factory=fake_listener,
        )

        agent.run()

        self.assertEqual(agent.state, AgentState.SHUTDOWN)
        self.assertEqual(agent.turn_count, 0)
        self.assertEqual(len(fake_stt.transcribe_calls), 0)
        self.assertEqual(len(fake_tts.synthesize_calls), 0)

    def test_replies_when_speech_detected_in_single_turn(self) -> None:
        fake_stt = FakeSTT(transcript="今天天氣很好")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
        ) -> Iterator[ListeningEvent]:
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=10.0,
                    continuous=False,
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(prefix="Echo: "),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )

            agent.run()

            self.assertEqual(agent.state, AgentState.SHUTDOWN)
            self.assertEqual(agent.turn_count, 1)
            self.assertEqual(len(fake_stt.transcribe_calls), 1)
            self.assertEqual(len(fake_tts.synthesize_calls), 1)
            self.assertEqual(fake_tts.synthesize_calls[0].text, "Echo: 今天天氣很好")

    def test_continuous_mode_returns_to_standby_then_times_out(self) -> None:
        fake_stt = FakeSTT(transcript="第一句")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield ListeningEvent(kind="speech_started")
                yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)
            else:
                yield ListeningEvent(kind="standby_timeout")

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=5.0,
                    continuous=True,
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )

            agent.run()

            self.assertEqual(agent.state, AgentState.SHUTDOWN)
            self.assertEqual(agent.turn_count, 1)
            self.assertEqual(call_count, 2)
            self.assertEqual(len(fake_tts.synthesize_calls), 1)

    def test_ignores_empty_transcript(self) -> None:
        fake_stt = FakeSTT(transcript="   ")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
        ) -> Iterator[ListeningEvent]:
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=5.0,
                    continuous=False,
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )

            agent.run()

            self.assertEqual(agent.state, AgentState.SHUTDOWN)
            self.assertEqual(len(fake_tts.synthesize_calls), 0)


class AgentCLITest(unittest.TestCase):
    def test_parses_cli_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--timeout",
                "15.5",
                "--continuous",
                "--max-turns",
                "3",
                "--reply-prefix",
                "回覆：",
            ]
        )
        self.assertEqual(args.timeout, 15.5)
        self.assertTrue(args.continuous)
        self.assertEqual(args.max_turns, 3)
        self.assertEqual(args.reply_prefix, "回覆：")


if __name__ == "__main__":
    unittest.main()
