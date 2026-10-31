import unittest

from myagent.voice.loop_cli import build_parser


class VoiceLoopCLITest(unittest.TestCase):
    def test_parses_max_turns_and_reply_prefix(self) -> None:
        args = build_parser().parse_args(
            ["--max-turns", "1", "--reply-prefix", "收到：", "--device", "4"]
        )

        self.assertEqual(args.max_turns, 1)
        self.assertEqual(args.reply_prefix, "收到：")
        self.assertEqual(args.device, "4")


if __name__ == "__main__":
    unittest.main()
