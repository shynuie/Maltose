from __future__ import annotations

import threading
import time
import unittest
from typing import Iterator

from myagent.agent import AgentConfig, VoiceAgent
from myagent.agent.agent import AgentState
from myagent.runtime import EventHub
from myagent.voice import ListeningEvent, STTResult, TTSRequest, VADSettings


class QuietSTT:
    def transcribe(self, _request) -> STTResult:
        return STTResult("不应走语音转写", "zh", 0.0, [])


class QuietTTS:
    def synthesize(self, _request: TTSRequest) -> None:
        return None


class WebAgentIntegrationTest(unittest.TestCase):
    def test_streaming_reply_publishes_deltas_before_completion(self) -> None:
        hub = EventHub()
        subscription = hub.subscribe()
        agent = VoiceAgent(
            config=AgentConfig(interruptible_tts=False),
            speaker=QuietTTS(),
            event_hub=hub,
        )

        reply, interrupted = agent._speak_stream(iter(["第一", "句。", "第二句！"]))

        events = []
        subscription.close()
        while True:
            try:
                events.append(next(subscription))
            except StopIteration:
                break
        self.assertIsNone(interrupted)
        self.assertEqual(reply, "第一句。第二句！")
        self.assertEqual(
            [event.type for event in events],
            ["state_changed", "assistant_start", "assistant_delta", "assistant_delta", "assistant_delta", "assistant_end"],
        )
        self.assertEqual(
            "".join(event.payload["content"] for event in events if event.type == "assistant_delta"),
            reply,
        )

    def test_web_text_uses_same_agent_brain_session_and_events(self) -> None:
        hub = EventHub()
        subscription = hub.subscribe()
        listener_calls = 0

        def listener(
            _settings: VADSettings,
            _device,
            _timeout,
            _wake_word_detector,
            _wake_ack_delay,
            _wake_buffer_ms,
            stop_event: threading.Event,
        ) -> Iterator[ListeningEvent]:
            nonlocal listener_calls
            listener_calls += 1
            if listener_calls > 1:
                raise KeyboardInterrupt
            while not stop_event.wait(0.01):
                yield ListeningEvent(kind="speech_started")

        agent = VoiceAgent(
            config=AgentConfig(vad_settings=VADSettings()),
            transcriber=QuietSTT(),
            speaker=QuietTTS(),
            listener_factory=listener,
            event_hub=hub,
        )
        thread = threading.Thread(target=agent.run)
        thread.start()
        deadline = time.monotonic() + 1
        while agent.state != AgentState.STANDBY and time.monotonic() < deadline:
            time.sleep(0.01)
        agent.submit_text("网页指令")
        thread.join(timeout=2)
        subscription.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(agent.state, AgentState.SHUTDOWN)
        events = []
        while True:
            try:
                events.append(next(subscription))
            except StopIteration:
                break
            except Exception:
                break
        event_types = [event.type for event in events]
        self.assertIn("user_message", event_types)
        self.assertIn("assistant_message", event_types)
        self.assertIn("state_changed", event_types)
        self.assertGreaterEqual(listener_calls, 2)
