import json
import unittest
from unittest.mock import patch

from maltose.agent import BraveSearchProvider, SearchResult, WebResearchWorker


class SearchProviderTest(unittest.TestCase):
    def test_requires_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "BRAVE_SEARCH_API_KEY"):
                BraveSearchProvider()

    @patch("maltose.agent.search.urllib.request.urlopen")
    def test_parses_brave_results_and_bounds_snippets(self, urlopen) -> None:
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(
            {
                "web": {
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com",
                            "description": "A result",
                            "page_age": "2026-09-20",
                        }
                    ]
                }
            }
        ).encode("utf-8")
        provider = BraveSearchProvider(api_key="secret", max_results=5)

        results = provider.search("latest test", count=2, freshness="pw", domains=["example.com"])

        self.assertEqual(results, [SearchResult("Example", "https://example.com", "A result", "2026-09-20")])
        request = urlopen.call_args.args[0]
        self.assertIn("q=latest+test", request.full_url)
        self.assertIn("freshness=pw", request.full_url)
        self.assertEqual(request.get_header("X-subscription-token"), "secret")

    def test_research_worker_deduplicates_sources_and_reports_progress(self) -> None:
        class FakeProvider:
            def search(self, query, *, count, freshness, domains):
                return [
                    SearchResult("Shared", "https://example.com/shared", query),
                    SearchResult(query, f"https://example.com/{query}", "details"),
                ]

        record = type("Record", (), {
            "title": "Research",
            "input": {"queries": ["one", "two"], "count": 2},
        })()
        progress = []
        result = WebResearchWorker(FakeProvider()).run(record, progress.append)

        self.assertEqual(progress, [5, 50, 95])
        self.assertIn('"source_count": 3', result)
        self.assertNotIn('"source_count": 4', result)


if __name__ == "__main__":
    unittest.main()
