from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.agent import AgentConfig, EchoBrain, VoiceAgent
from myagent.voice import RenderedAudio, TTSRequest


class PreRenderedSpeaker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.rendered: list[str] = []
        self.played: list[str] = []
        self.artifacts: list[Path] = []

    def render(self, request: TTSRequest) -> RenderedAudio:
        path = self.root / f"audio-{len(self.rendered)}.aiff"
        path.write_bytes(request.text.encode())
        self.rendered.append(request.text)
        self.artifacts.append(path)
        return RenderedAudio(path)

    def play(self, audio: RenderedAudio) -> None:
        self.played.append(audio.path.read_bytes().decode())

    def stop(self) -> bool:
        return False


class StreamingAudioPipelineTests(unittest.TestCase):
    def test_renders_ahead_and_plays_all_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            speaker = PreRenderedSpeaker(Path(directory))
            agent = VoiceAgent(
                config=AgentConfig(interruptible_tts=False),
                brain=EchoBrain(),
                speaker=speaker,
            )

            spoken, deferred = agent._speak_stream(iter(["第一句。", "第二句。", "第三句。"]))

            self.assertEqual(spoken, "第一句。第二句。第三句。")
            self.assertIsNone(deferred)
            self.assertEqual(speaker.rendered, speaker.played)
            self.assertTrue(all(not path.exists() for path in speaker.artifacts))


if __name__ == "__main__":
    unittest.main()
