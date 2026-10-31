import json
import unittest
from unittest.mock import patch

from maltose.agent.environment import EnvironmentTools


class EnvironmentToolsTest(unittest.TestCase):
    def test_current_datetime_supports_explicit_timezone(self) -> None:
        result = EnvironmentTools().current_datetime("Asia/Taipei")

        self.assertEqual(result["timezone"], "Asia/Taipei")
        self.assertRegex(result["iso8601"], r"^20\d\d-")
        self.assertIn(result["weekday"], {
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
        })

    def test_location_uses_configured_value(self) -> None:
        self.assertEqual(
            EnvironmentTools(location="Taipei").get_location(),
            {"location": "Taipei", "source": "configured"},
        )

    @patch("maltose.agent.environment.urllib.request.urlopen")
    def test_ip_addresses_validate_external_response(self, urlopen) -> None:
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"ip": "203.0.113.10"}).encode()

        result = EnvironmentTools().get_ip_addresses()

        self.assertEqual(result["ip"], "203.0.113.10")
        self.assertEqual(result["external_ip"], "203.0.113.10")
        self.assertIn("internal_ips", result)

    @patch("maltose.agent.environment.urllib.request.urlopen")
    def test_ip_addresses_keep_internal_result_when_external_lookup_fails(self, urlopen) -> None:
        urlopen.side_effect = TimeoutError("TLS handshake timed out")

        result = EnvironmentTools().get_ip_addresses()

        self.assertEqual(result["external_ip"], "unknown")
        self.assertIn("internal_ips", result)
        self.assertIn("external_error", result)


if __name__ == "__main__":
    unittest.main()
