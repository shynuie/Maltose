from pathlib import Path
from unittest.mock import patch
import unittest

from myagent.voice import MacOSSayTTS, TTSRequest


class MacOSSayTTSTest(unittest.TestCase):
    def test_rejects_empty_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            MacOSSayTTS().synthesize(TTSRequest(text=" "))

    @patch("myagent.voice.tts.platform.system", return_value="Darwin")
    @patch("myagent.voice.tts.subprocess.run")
    def test_builds_say_command(self, run, _system) -> None:
        MacOSSayTTS().synthesize(
            TTSRequest(
                text="hello",
                voice="Samantha",
                rate=180,
                output_path=Path("hello.aiff"),
            )
        )

        run.assert_called_once_with(
            ["say", "-v", "Samantha", "-r", "180", "-o", "hello.aiff", "hello"],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
