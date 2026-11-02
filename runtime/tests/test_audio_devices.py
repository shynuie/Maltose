from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from maltose.agent.taskbrain import TaskBrain, ToolRegistry
from maltose.voice.devices import AudioInputDeviceController, AudioInputDeviceError


class AudioDeviceControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sounddevice = types.SimpleNamespace(
            default=types.SimpleNamespace(device=(2, 4)),
            query_devices=lambda: [
                {"name": "Speaker", "hostapi": "Core Audio", "max_input_channels": 0},
                {"name": "MacBook Mic", "hostapi": "Core Audio", "max_input_channels": 1},
                {"name": "Xiaomi", "hostapi": "Core Audio", "max_input_channels": 1},
            ],
        )

    def test_none_follows_system_default(self) -> None:
        controller = AudioInputDeviceController()
        with patch.dict(sys.modules, {"sounddevice": self.sounddevice}):
            current = controller.current()

        self.assertEqual(current["mode"], "system_default")
        self.assertEqual(current["device"]["index"], 2)

    def test_can_select_by_name_and_reset_to_default(self) -> None:
        controller = AudioInputDeviceController()
        with patch.dict(sys.modules, {"sounddevice": self.sounddevice}):
            selected = controller.set_device("xiaomi")
            reset = controller.set_device("default")

        self.assertEqual(selected["mode"], "explicit")
        self.assertEqual(selected["selected_device"], 2)
        self.assertEqual(reset["mode"], "system_default")

    def test_rejects_output_only_or_unknown_devices(self) -> None:
        controller = AudioInputDeviceController()
        with patch.dict(sys.modules, {"sounddevice": self.sounddevice}):
            with self.assertRaises(AudioInputDeviceError):
                controller.set_device(0)
            with self.assertRaises(AudioInputDeviceError):
                controller.set_device("not found")


class AudioDeviceToolTests(unittest.TestCase):
    def test_taskbrain_exposes_device_tools_when_controller_attached(self) -> None:
        controller = AudioInputDeviceController()
        controller.current = lambda: {"mode": "system_default"}  # type: ignore[method-assign]
        controller.set_device = lambda value: {"selected_device": value}  # type: ignore[method-assign]
        brain = TaskBrain(
            model=types.SimpleNamespace(),
            tools=ToolRegistry(),
            audio_device_controller=controller,
        )

        self.assertTrue(brain.tools.has("get_audio_input_device"))
        self.assertTrue(brain.tools.has("set_audio_input_device"))
        self.assertEqual(brain.tools.execute("get_audio_input_device", {}), {"mode": "system_default"})
        self.assertEqual(
            brain.tools.execute("set_audio_input_device", {"device": 2}),
            {"selected_device": 2},
        )


if __name__ == "__main__":
    unittest.main()
