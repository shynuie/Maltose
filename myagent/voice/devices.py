from __future__ import annotations

from typing import Any


class AudioInputDeviceError(ValueError):
    """Raised when an audio input device cannot be selected."""


class AudioInputDeviceController:
    """Resolve and select the input device used by MyAgent.

    ``None`` deliberately means the operating-system default input. Selecting a
    concrete device only changes MyAgent's next input stream; it does not alter
    macOS's global audio preference.
    """

    def __init__(self, selected_device: str | int | None = None) -> None:
        self._selected_device = self._normalize_selection(selected_device)

    @property
    def selected_device(self) -> str | int | None:
        return self._selected_device

    def _sounddevice(self) -> Any:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioInputDeviceError(
                "Audio device control requires the sounddevice package."
            ) from exc
        return sd

    @staticmethod
    def _normalize_selection(value: str | int | None) -> str | int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        value = str(value).strip()
        if not value or value.lower() in {"default", "system", "system_default", "auto"}:
            return None
        if value.isdigit():
            return int(value)
        return value

    @staticmethod
    def _device_info(index: int, device: dict[str, Any], default_index: int | None) -> dict[str, Any]:
        return {
            "index": index,
            "name": str(device.get("name", "")),
            "hostapi": str(device.get("hostapi", "")),
            "max_input_channels": int(device.get("max_input_channels", 0)),
            "is_default": default_index == index,
        }

    def list_input_devices(self) -> list[dict[str, Any]]:
        sd = self._sounddevice()
        devices = sd.query_devices()
        default_device = sd.default.device
        default_input = default_device[0] if isinstance(default_device, (tuple, list)) else default_device
        try:
            default_index = int(default_input)
        except (TypeError, ValueError):
            default_index = None
        return [
            self._device_info(index, device, default_index)
            for index, device in enumerate(devices)
            if int(device.get("max_input_channels", 0)) > 0
        ]

    def _resolve(self, selection: str | int | None) -> str | int | None:
        selection = self._normalize_selection(selection)
        if selection is None:
            return None
        devices = self.list_input_devices()
        if isinstance(selection, int):
            match = next((item for item in devices if item["index"] == selection), None)
        else:
            wanted = selection.casefold()
            match = next(
                (item for item in devices if item["name"].casefold() == wanted),
                next((item for item in devices if wanted in item["name"].casefold()), None),
            )
        if match is None:
            available = ", ".join(f'{item["index"]}: {item["name"]}' for item in devices)
            raise AudioInputDeviceError(
                f"Input device {selection!r} was not found. Available inputs: {available or 'none'}"
            )
        return int(match["index"])

    def set_device(self, selection: str | int | None) -> dict[str, Any]:
        self._selected_device = self._resolve(selection)
        return self.current()

    def current(self) -> dict[str, Any]:
        devices = self.list_input_devices()
        if self._selected_device is None:
            default = next((item for item in devices if item["is_default"]), None)
            return {
                "mode": "system_default",
                "selected_device": None,
                "device": default,
                "available_devices": devices,
            }
        selected = next(
            (item for item in devices if item["index"] == self._selected_device),
            None,
        )
        if selected is None:
            self._selected_device = self._resolve(self._selected_device)
            selected = next(item for item in devices if item["index"] == self._selected_device)
        return {
            "mode": "explicit",
            "selected_device": self._selected_device,
            "device": selected,
            "available_devices": devices,
        }

    def device_for_stream(self) -> str | int | None:
        return self._selected_device
