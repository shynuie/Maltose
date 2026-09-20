"""Narrow local environment information tools."""

from __future__ import annotations

import ipaddress
import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class EnvironmentTools:
    def __init__(
        self,
        *,
        location: str | None = None,
        location_helper: str | None = None,
        external_ip_url: str = "https://api.ipify.org?format=json",
        timeout: float = 5.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Environment timeout must be positive.")
        self.location = location
        self.location_helper = location_helper
        self.external_ip_url = external_ip_url
        self.timeout = timeout

    def current_datetime(self, timezone_name: str | None = None) -> dict[str, str]:
        if timezone_name:
            try:
                current = datetime.now(ZoneInfo(timezone_name))
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown timezone: {timezone_name}") from exc
        else:
            current = datetime.now().astimezone()
        return {
            "timezone": str(current.tzinfo),
            "iso8601": current.isoformat(),
            "date": current.date().isoformat(),
            "time": current.strftime("%H:%M:%S"),
            "weekday": current.strftime("%A"),
        }

    def get_location(self) -> dict[str, str]:
        if self.location:
            return {"location": self.location, "source": "configured"}
        if self.location_helper:
            try:
                completed = subprocess.run(
                    [str(Path(self.location_helper))],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout + 1,
                )
                payload = json.loads(completed.stdout)
                if completed.returncode != 0:
                    return {
                        "location": "unknown",
                        "source": "macos_core_location",
                        "error": str(payload.get("error", "Location helper failed")),
                    }
                if not isinstance(payload, dict) or "latitude" not in payload:
                    raise ValueError("Location helper returned an invalid response.")
                return {str(key): str(value) for key, value in payload.items()}
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
                return {
                    "location": "unknown",
                    "source": "macos_core_location",
                    "error": str(exc),
                }
        return {
            "location": "unknown",
            "source": "none",
            "message": "No location has been configured.",
        }

    def _get_internal_ips(self) -> list[str]:
        """Return non-loopback addresses reported by the local network stack."""
        try:
            completed = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return []

        addresses: list[str] = []
        for line in completed.stdout.splitlines():
            fields = line.split()
            if not fields or fields[0] not in {"inet", "inet6"} or len(fields) < 2:
                continue
            candidate = fields[1].split("%", 1)[0]
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local:
                continue
            if candidate not in addresses:
                addresses.append(candidate)
        return addresses

    def get_ip_addresses(self) -> dict[str, object]:
        internal_ips = self._get_internal_ips()
        result: dict[str, object] = {
            "internal_ips": internal_ips,
            "external_ip": "unknown",
            "external_source": self.external_ip_url,
            # Keep the old fields for callers that consumed the original result.
            "ip": "unknown",
            "source": self.external_ip_url,
        }
        request = urllib.request.Request(
            self.external_ip_url,
            headers={"Accept": "application/json, text/plain"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8").strip()
            try:
                payload = json.loads(raw)
                value = payload.get("ip") if isinstance(payload, dict) else payload
            except json.JSONDecodeError:
                value = raw
            if not isinstance(value, str):
                raise ValueError("External IP endpoint returned an invalid response.")
            external_ip = value.strip()
            ipaddress.ip_address(external_ip)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            result["external_error"] = str(exc)
            return result

        result["external_ip"] = external_ip
        result["ip"] = external_ip
        return result
