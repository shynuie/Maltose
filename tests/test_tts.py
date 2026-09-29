from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest

from myagent.voice import MacOSAudioPlayer, MacOSSayAudioRenderer, MacOSSayTTS, TTSRequest


class MacOSSayTTSTest(unittest.TestCase):
    def test_rejects_empty_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            MacOSSayTTS().synthesize(TTSRequest(text=" "))

    @patch("myagent.voice.tts.platform.system", return_value="Darwin")
    @patch("myagent.voice.tts.subprocess.Popen")
    def test_builds_say_command(self, popen, _system) -> None:
        process = MagicMock()
        process.wait.return_value = 0
        process.poll.return_value = None
        popen.return_value = process
        MacOSSayTTS().synthesize(
            TTSRequest(
                text="hello",
                voice="Samantha",
                rate=180,
                output_path=Path("hello.aiff"),
            )
        )

        popen.assert_called_once_with(
            ["say", "-v", "Samantha", "-r", "180", "-o", "hello.aiff", "hello"],
        )

    @patch("myagent.voice.tts.platform.system", return_value="Darwin")
    @patch("myagent.voice.tts.subprocess.Popen")
    def test_stop_terminates_the_active_speech(self, popen, _system) -> None:
        process = MagicMock()
        process.wait.side_effect = lambda: 0
        process.poll.return_value = None
        popen.return_value = process
        speaker = MacOSSayTTS()

        with patch.object(process, "poll", return_value=None):
            speaker._process = process
            self.assertTrue(speaker.stop())

        process.terminate.assert_called_once_with()
        self.assertFalse(speaker.stop())

    @patch("myagent.voice.tts.platform.system", return_value="Darwin")
    @patch("myagent.voice.tts.subprocess.Popen")
    @patch("myagent.voice.tts.os.close")
    @patch("myagent.voice.tts.tempfile.mkstemp", return_value=(3, "/tmp/myagent-tts.aiff"))
    def test_renderer_creates_owned_audio_artifact(self, mkstemp, close, popen, _system) -> None:
        process = MagicMock()
        process.wait.return_value = 0
        process.poll.return_value = None
        popen.return_value = process
        rendered = MacOSSayAudioRenderer().render(TTSRequest(text="hello", rate=180))

        self.assertEqual(rendered.path, Path("/tmp/myagent-tts.aiff"))
        self.assertTrue(rendered.cleanup_after_use)
        popen.assert_called_once_with(
            ["say", "-r", "180", "-o", "/tmp/myagent-tts.aiff", "hello"],
        )
        rendered.cleanup()

    @patch("myagent.voice.tts.platform.system", return_value="Darwin")
    @patch("myagent.voice.tts.subprocess.Popen")
    def test_audio_player_uses_afplay_and_can_stop(self, popen, _system) -> None:
        process = MagicMock()
        process.wait.side_effect = lambda: 0
        process.poll.return_value = None
        popen.return_value = process
        player = MacOSAudioPlayer()

        player.play(type("Audio", (), {"path": Path("hello.aiff")})())

        popen.assert_called_once_with(["afplay", "hello.aiff"])

    def test_renderer_rejects_non_macos(self) -> None:
        with patch("myagent.voice.tts.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(RuntimeError, "only works on macOS"):
                MacOSSayAudioRenderer().render(TTSRequest(text="hello"))


if __name__ == "__main__":
    unittest.main()
