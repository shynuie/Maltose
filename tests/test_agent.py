from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from myagent.agent import (
    AgentConfig,
    AgentState,
    EchoBrain,
    MemoryStore,
    LanceMemoryStore,
    OpenAICompatibleTaskModel,
    OpenClawBrain,
    TaskBrain,
    TurnContext,
    ToolRegistry,
    UserProfileStore,
    VoiceAgent,
    TaskManager,
    TaskStore,
)
from myagent.agent.cli import build_parser
from myagent.agent.config import load_cli_defaults
from myagent.voice import (
    ListeningEvent,
    NullSpeakerIdentifier,
    SpeakerResult,
    STTRequest,
    STTResult,
    TTSRequest,
    Utterance,
    VADSettings,
)


class SpeakerFallbackTests(unittest.TestCase):
    def test_trusted_fallback_is_identified(self) -> None:
        result = NullSpeakerIdentifier("default").identify(Path("unused.wav"))

        self.assertEqual(result.user_id, "default")
        self.assertEqual(result.status, "identified")
        self.assertIsNone(result.score)


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


class OpenClawBrainTest(unittest.TestCase):
    @patch("myagent.agent.brain.urllib.request.urlopen")
    def test_sends_openai_compatible_request(self, urlopen) -> None:
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "已完成"}}]}
        ).encode("utf-8")

        result = OpenClawBrain(token="secret", session_id="test-session").process("打開窗簾")

        self.assertEqual(result, "已完成")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18789/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["user"], "test-session")
        self.assertEqual(payload["messages"][0]["content"], "打開窗簾")


class TaskBrainTest(unittest.TestCase):
    @patch("myagent.agent.taskbrain.urllib.request.urlopen")
    def test_openai_model_disables_reasoning_for_chat_tools(self, urlopen) -> None:
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "完成"}}]}
        ).encode("utf-8")

        OpenAICompatibleTaskModel(token="secret").complete([], [])

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["tool_choice"], "auto")

    def test_memory_store_persists_and_searches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryStore(Path(tmpdir) / "memory.json")
            memory.remember("使用者喜歡熱咖啡", ["preference"])
            self.assertEqual(memory.search("熱咖啡")[0]["text"], "使用者喜歡熱咖啡")

    def test_memory_search_matches_natural_chinese_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryStore(Path(tmpdir) / "memory.json")
            memory.remember("使用者是工程師", ["職業"])
            self.assertEqual(
                memory.search("請回想一下我的職業是什麼？")[0]["text"],
                "使用者是工程師",
            )

    def test_embedding_memory_searches_semantically(self) -> None:
        class FakeEmbedder:
            def embed(self, text, *, is_query=False):
                return [1.0, 0.0] if any(word in text for word in ("職業", "工程師", "工作")) else [0.0, 1.0]

        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryStore(Path(tmpdir) / "memory.json", embedder=FakeEmbedder())
            memory.remember("使用者是工程師", ["職業"])
            memory.remember("使用者喜歡熱咖啡", ["偏好"])
            self.assertEqual(memory.search("我的工作是什麼")[0]["text"], "使用者是工程師")

    def test_backfills_embeddings_for_existing_entries(self) -> None:
        class FakeEmbedder:
            def embed(self, text, *, is_query=False):
                return [1.0, 0.0]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memory.json"
            memory = MemoryStore(path)
            memory.remember("舊記憶")
            memory = MemoryStore(path, embedder=FakeEmbedder())
            self.assertEqual(memory.backfill_embeddings(), 1)
            self.assertEqual(len(memory._load()[0]["embedding"]), 2)

    def test_prompt_requires_recall_for_personal_facts(self) -> None:
        class FakeModel:
            def complete(self, messages, tools):
                assert {tool["function"]["name"] for tool in tools} == {
                    "remember",
                    "recall",
                    "return_to_standby",
                    "get_current_datetime",
                    "get_location",
                    "get_ip_addresses",
                }
                self.assert_memory(messages)
                return {"choices": [{"message": {"content": "你是工程師。"}}]}

            @staticmethod
            def assert_memory(messages) -> None:
                assert "call the recall tool" in messages[0]["content"]

        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryStore(Path(tmpdir) / "memory.json")
            memory.remember("使用者是工程師", ["職業"])
            self.assertEqual(
                TaskBrain(FakeModel(), memory=memory).process("我的職業是什麼？"),
                "你是工程師。",
            )

    def test_executes_tool_then_returns_final_response(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, messages, tools):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "tool_calls": [{
                                    "id": "call-1",
                                    "function": {
                                        "name": "remember",
                                        "arguments": json.dumps({"text": "喜歡綠茶"}),
                                    },
                                }],
                            }
                        }]
                    }
                self.assert_tool_result(messages)
                return {"choices": [{"message": {"content": "我記住了。"}}]}

            @staticmethod
            def assert_tool_result(messages) -> None:
                assert messages[-1]["role"] == "tool"
                assert "喜歡綠茶" in messages[-1]["content"]

        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryStore(Path(tmpdir) / "memory.json")
            brain = TaskBrain(FakeModel(), memory=memory)
            self.assertEqual(brain.process("請記住我喜歡綠茶"), "我記住了。")
            self.assertEqual(memory.search("綠茶")[0]["text"], "喜歡綠茶")

    def test_short_term_session_context_is_reused_and_cleared(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.user_messages: list[list[str]] = []

            def complete(self, messages, tools):
                self.user_messages.append([
                    message["content"]
                    for message in messages
                    if message.get("role") == "user"
                ])
                return {"choices": [{"message": {"content": "收到。"}}]}

        model = FakeModel()
        brain = TaskBrain(model, max_session_turns=2)
        brain.begin_session()
        brain.process("我剛才說我喜歡藍色。")
        brain.process("你記得我的偏好嗎？")
        self.assertEqual(model.user_messages[-1], [
            "我剛才說我喜歡藍色。",
            "你記得我的偏好嗎？",
        ])
        brain.end_session()
        brain.process("這是新對話。")
        self.assertEqual(model.user_messages[-1], ["這是新對話。"])

    def test_custom_tool_can_be_registered(self) -> None:
        registry = ToolRegistry()
        registry.register(
            "add",
            "Add two numbers.",
            {"type": "object"},
            lambda args: args["a"] + args["b"],
        )
        self.assertEqual(registry.execute("add", {"a": 2, "b": 3}), 5)

    def test_return_to_standby_tool_requests_conversation_control(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, messages, tools):
                self.calls += 1
                if self.calls == 1:
                    return {"choices": [{"message": {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "call-standby",
                            "function": {
                                "name": "return_to_standby",
                                "arguments": "{}",
                            },
                        }],
                    }}]}
                return {"choices": [{"message": {"content": "好的，我先待命。"}}]}

        brain = TaskBrain(FakeModel())
        self.assertEqual(brain.process("退下吧"), "好的，我先待命。")
        self.assertTrue(brain.consume_return_to_standby())
        self.assertFalse(brain.consume_return_to_standby())

    def test_user_profile_is_stored_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = UserProfileStore(Path(tmpdir) / "memory.lancedb")
            store.set_profile(
                display_name="Marvin",
                full_name="Marvin Fan",
                chinese_name="范育銜",
            )
            self.assertEqual(store.get_profile()["display_name"], "Marvin")
            self.assertEqual(store.get_profile()["chinese_name"], "范育銜")

    def test_lance_memories_are_scoped_to_user_id(self) -> None:
        class FakeEmbedder:
            def embed(self, text, *, is_query=False):
                return [1.0, 0.0]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memory.lancedb"
            LanceMemoryStore(path, FakeEmbedder(), user_id="alice").remember("Alice 的記憶")
            LanceMemoryStore(path, FakeEmbedder(), user_id="bob").remember("Bob 的記憶")
            results = LanceMemoryStore(path, FakeEmbedder(), user_id="alice").search("記憶")
            self.assertEqual([result["text"] for result in results], ["Alice 的記憶"])

    def test_taskbrain_exposes_user_profile_tool(self) -> None:
        class NoopModel:
            def complete(self, messages, tools):
                return {"choices": [{"message": {"content": "ok"}}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            profile = UserProfileStore(Path(tmpdir) / "memory.lancedb")
            profile.set_profile(display_name="Marvin")
            brain = TaskBrain(NoopModel(), profile=profile)
            self.assertEqual(brain.tools.execute("get_user_profile", {}), {
                "id": "default",
                "display_name": "Marvin",
            })

    def test_taskbrain_exposes_task_tools_and_scopes_plan_to_user(self) -> None:
        class NoopModel:
            def complete(self, messages, tools):
                return {"choices": [{"message": {"content": "ok"}}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            task_manager = TaskManager(TaskStore(Path(tmpdir) / "tasks.sqlite3"))
            brain = TaskBrain(NoopModel(), task_manager=task_manager)
            result = brain.tools.execute(
                "create_task_plan",
                {
                    "tasks": [
                        {"task_id": "one", "title": "分析檔案", "worker_type": "codex_readonly"}
                    ]
                },
            )
            self.assertEqual(result["tasks"][0]["user_id"], "default")
            self.assertEqual(
                {tool["function"]["name"] for tool in brain.tools.schemas()},
                {
                    "remember",
                    "recall",
                    "return_to_standby",
                    "create_task_plan",
                    "get_task_status",
                    "list_tasks",
                    "list_active_tasks",
                    "cancel_task",
                    "retry_task",
                    "get_current_datetime",
                    "get_location",
                    "get_ip_addresses",
                },
            )
            task_manager.shutdown()
            task_manager.store.close()


class VoiceAgentTest(unittest.TestCase):
    def test_interruptible_speech_stops_and_queues_followup_utterance(self) -> None:
        class InterruptibleTTS:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.stopped = threading.Event()

            def synthesize(self, _request: TTSRequest) -> None:
                self.started.set()
                self.stopped.wait(timeout=1.0)

            def stop(self) -> bool:
                self.stopped.set()
                return True

        fake_tts = InterruptibleTTS()
        fake_utterance = _make_fake_utterance()

        class InterruptSTT:
            def transcribe(self, _request: STTRequest) -> STTResult:
                return STTResult("等等", "zh", 1.0, [])

        class InterruptBrain:
            def should_interrupt_speech(self, text: str) -> bool:
                return text == "等等"

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            fake_tts.started.wait(timeout=1.0)
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        agent = VoiceAgent(
            config=AgentConfig(),
            brain=InterruptBrain(),
            transcriber=InterruptSTT(),
            speaker=fake_tts,
            listener_factory=fake_listener,
        )

        interrupted = agent._speak_reply(TTSRequest(text="長篇回答"))

        self.assertIsNotNone(interrupted)
        self.assertEqual(interrupted.transcript, "等等")
        self.assertIs(interrupted.utterance, fake_utterance)
        self.assertEqual(interrupted.speaker_result.status, "unknown")
        self.assertTrue(fake_tts.stopped.is_set())

    def test_explicit_stop_phrase_uses_fast_path(self) -> None:
        agent = VoiceAgent(brain=EchoBrain())
        self.assertTrue(agent._should_interrupt_speech("等等，先別說了。"))

    def test_keeps_monitoring_after_non_interrupting_barge_in(self) -> None:
        class InterruptibleTTS:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.stopped = threading.Event()

            def synthesize(self, _request: TTSRequest) -> None:
                self.started.set()
                self.stopped.wait(timeout=1.0)

            def stop(self) -> bool:
                self.stopped.set()
                return True

        class ClassifierBrain:
            def __init__(self) -> None:
                self.transcripts = iter([False, True])

            def should_interrupt_speech(self, _text: str) -> bool:
                return next(self.transcripts)

        class InterruptSTT:
            def __init__(self) -> None:
                self.calls = 0

            def transcribe(self, _request: STTRequest) -> STTResult:
                self.calls += 1
                return STTResult(
                    "普通插話" if self.calls == 1 else "等等",
                    "zh",
                    1.0,
                    [],
                )

        fake_tts = InterruptibleTTS()
        utterance = _make_fake_utterance()

        def listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            fake_tts.started.wait(timeout=1.0)
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=utterance)
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=utterance)

        agent = VoiceAgent(
            config=AgentConfig(),
            brain=ClassifierBrain(),
            transcriber=InterruptSTT(),
            speaker=fake_tts,
            listener_factory=listener,
        )

        result = agent._speak_reply(TTSRequest(text="長篇回答"))

        self.assertIsNotNone(result)
        self.assertEqual(result.transcript, "等等")
        self.assertTrue(fake_tts.stopped.is_set())

    def test_wake_only_transcript_replies_without_brain_call(self) -> None:
        fake_stt = FakeSTT(transcript="麦芽糖。")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        class FailingBrain:
            def process(self, _text, context=None):
                raise AssertionError("wake-only transcript should bypass the brain")

        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(output_dir=Path(tmpdir)),
                brain=FailingBrain(),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )
            agent.run()

        self.assertEqual(fake_tts.synthesize_calls[-1].text, "我在")

    def test_stt_and_speaker_identification_run_for_same_turn(self) -> None:
        fake_stt = FakeSTT(transcript="你好")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        class FakeSpeaker:
            def __init__(self) -> None:
                self.paths = []

            def identify(self, audio_path):
                self.paths.append(audio_path)
                return SpeakerResult("marvin", 0.97, "identified")

        class ContextBrain:
            def __init__(self) -> None:
                self.context = None

            def process(self, _text, context=None):
                self.context = context
                return "收到"

        fake_speaker = FakeSpeaker()
        brain = ContextBrain()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(output_dir=Path(tmpdir)),
                brain=brain,
                transcriber=fake_stt,
                speaker=fake_tts,
                speaker_identifier=fake_speaker,
                listener_factory=fake_listener,
            )
            agent.run()

        self.assertEqual(len(fake_speaker.paths), 1)
        self.assertEqual(brain.context.user_id, "marvin")
        self.assertEqual(brain.context.speaker_status, "identified")

    def test_unknown_speaker_does_not_reuse_previous_user(self) -> None:
        class NoopModel:
            def complete(self, messages, tools):
                return {"choices": [{"message": {"content": "ok"}}]}

        memory = MemoryStore()
        brain = TaskBrain(NoopModel(), memory=memory)
        brain.process("第一個人", context=TurnContext(user_id="marvin", speaker_status="identified"))
        brain.process("未辨識的人", context=TurnContext(user_id=None, speaker_status="unknown"))
        self.assertEqual(brain._active_user_id, "unknown")

    def test_unknown_speaker_cannot_access_personal_memory(self) -> None:
        class NoopModel:
            def complete(self, messages, tools):
                return {"choices": [{"message": {"content": "ok"}}]}

        memory = MemoryStore()
        memory.remember("使用者是工程師", user_id="default")
        brain = TaskBrain(NoopModel(), memory=memory)
        brain.process("我不知道你是誰", context=TurnContext(user_id=None, speaker_status="unknown"))

        result = brain.tools.execute("recall", {"query": "職業"})

        self.assertTrue(result["requires_speaker_identification"])
        self.assertNotIn("工程師", str(result))

    def test_standby_timeout_returns_to_standby_until_interrupted(self) -> None:
        fake_stt = FakeSTT()
        fake_tts = FakeTTS()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
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
        self.assertEqual(call_count, 2)

    def test_replies_when_speech_detected_in_single_turn(self) -> None:
        fake_stt = FakeSTT(transcript="今天天氣很好")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
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
            self.assertEqual(call_count, 2)

    def test_silence_returns_to_wake_standby_without_shutdown(self) -> None:
        fake_stt = FakeSTT(transcript="第一句")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()

        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield ListeningEvent(kind="speech_started")
                yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)
            elif call_count == 2:
                yield ListeningEvent(kind="standby_timeout")
            else:
                raise KeyboardInterrupt

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
            self.assertEqual(call_count, 3)
            self.assertEqual(len(fake_tts.synthesize_calls), 1)

    def test_wake_word_is_required_again_after_conversation_timeout(self) -> None:
        fake_stt = FakeSTT(transcript="你好")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()
        wake_detector = object()
        listener_args = []
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            timeout: float | None,
            detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            listener_args.append((timeout, detector))
            if call_count == 1:
                yield ListeningEvent(kind="wake_detected", keyword="麥芽糖")
                yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)
            elif call_count == 2:
                yield ListeningEvent(kind="standby_timeout")
            else:
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=10.0,
                    wake_word_detector=wake_detector,
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )
            agent.run()

        self.assertIs(listener_args[0][1], wake_detector)
        self.assertIsNone(listener_args[0][0])
        self.assertIsNone(listener_args[1][1])
        self.assertEqual(listener_args[1][0], 10.0)
        self.assertIs(listener_args[2][1], wake_detector)
        self.assertIsNone(listener_args[2][0])

    def test_ignores_empty_transcript(self) -> None:
        fake_stt = FakeSTT(transcript="   ")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
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

    def test_speaks_wake_ack_when_requested_before_followup_listening(self) -> None:
        fake_stt = FakeSTT(transcript="打開窗簾")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            yield ListeningEvent(kind="wake_detected", keyword="麥芽糖")
            yield ListeningEvent(kind="wake_ack_requested")
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=5.0,
                    wake_ack_text="我在",
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(prefix="Echo: "),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )

            agent.run()

            self.assertEqual(
                [call.text for call in fake_tts.synthesize_calls],
                ["我在", "Echo: 打開窗簾"],
            )

    def test_does_not_speak_wake_ack_when_followup_starts_immediately(self) -> None:
        fake_stt = FakeSTT(transcript="打開窗簾")
        fake_tts = FakeTTS()
        fake_utterance = _make_fake_utterance()
        call_count = 0

        def fake_listener(
            _settings: VADSettings,
            _device: str | int | None,
            _timeout: float | None,
            _wake_word_detector,
            _wake_ack_delay: float,
            _wake_buffer_ms: int,
        ) -> Iterator[ListeningEvent]:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            yield ListeningEvent(kind="wake_detected", keyword="麥芽糖")
            yield ListeningEvent(kind="speech_started")
            yield ListeningEvent(kind="speech_ended", utterance=fake_utterance)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = VoiceAgent(
                config=AgentConfig(
                    standby_timeout=5.0,
                    wake_ack_text="我在",
                    output_dir=Path(tmpdir),
                ),
                brain=EchoBrain(prefix="Echo: "),
                transcriber=fake_stt,
                speaker=fake_tts,
                listener_factory=fake_listener,
            )

            agent.run()

            self.assertEqual(
                [call.text for call in fake_tts.synthesize_calls],
                ["Echo: 打開窗簾"],
            )


class AgentCLITest(unittest.TestCase):
    def test_loads_unified_toml_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "myagent.toml"
            path.write_text(
                """[agent]\nbrain = \"taskbrain\"\ndevice = \"3\"\n\n[voice]\nnormalize_stt_audio = false\n\n[taskbrain]\nmemory_backend = \"lancedb\"\nmcp_command = [\"python server.py\"]\n""",
                encoding="utf-8",
            )
            defaults = load_cli_defaults(path)

        self.assertEqual(defaults["brain"], "taskbrain")
        self.assertEqual(defaults["device"], "3")
        self.assertTrue(defaults["no_normalize_stt_audio"])
        self.assertEqual(defaults["taskbrain_memory_backend"], "lancedb")
        self.assertEqual(defaults["taskbrain_mcp_command"], ["python server.py"])

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
                "--wake-ack",
                "我在",
                "--wake-ack-delay",
                "0.6",
            ]
        )
        self.assertEqual(args.timeout, 15.5)
        self.assertTrue(args.continuous)
        self.assertEqual(args.max_turns, 3)
        self.assertEqual(args.reply_prefix, "回覆：")
        self.assertEqual(args.wake_ack, "我在")
        self.assertEqual(args.wake_ack_delay, 0.6)

    def test_wake_ack_defaults_to_i_am_here(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.wake_ack, "我在")


if __name__ == "__main__":
    unittest.main()
