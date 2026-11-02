"""Small, provider-neutral web search interface for TaskBrain."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from maltose.agent.tasks import TaskRecord


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }
        if self.published_at:
            result["published_at"] = self.published_at
        return result


class WebSearchProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        count: int = 5,
        freshness: str | None = None,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        ...


class BraveSearchProvider:
    """Brave Search API adapter without an additional runtime dependency."""

    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 10.0,
        max_results: int = 5,
        max_snippet_chars: int = 1200,
    ) -> None:
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Brave Search requires BRAVE_SEARCH_API_KEY or an explicit API key."
            )
        if timeout <= 0:
            raise ValueError("Search timeout must be positive.")
        if not 1 <= max_results <= 20:
            raise ValueError("max_results must be between 1 and 20.")
        self.timeout = timeout
        self.max_results = max_results
        self.max_snippet_chars = max_snippet_chars

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        freshness: str | None = None,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty.")
        count = max(1, min(count, self.max_results))
        params: dict[str, str] = {"q": query, "count": str(count)}
        if freshness:
            if freshness not in {"pd", "pw", "pm", "py"}:
                raise ValueError("freshness must be one of pd, pw, pm, or py.")
            params["freshness"] = freshness
        if domains:
            params["domains"] = ",".join(domain.strip() for domain in domains if domain.strip())
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Brave Search returned HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to Brave Search: {exc.reason}") from exc

        raw_results = payload.get("web", {}).get("results", [])
        if not isinstance(raw_results, list):
            raise RuntimeError("Brave Search response had an invalid results field.")
        results = []
        for item in raw_results[:count]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            result_url = item.get("url")
            if not isinstance(title, str) or not isinstance(result_url, str):
                continue
            snippet = item.get("description", "")
            results.append(
                SearchResult(
                    title=title[:300],
                    url=result_url,
                    snippet=str(snippet)[: self.max_snippet_chars],
                    published_at=item.get("page_age") or item.get("age"),
                )
            )
        return results


class WebResearchWorker:
    """Run a bounded multi-query search and return deduplicated sources."""

    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        max_queries: int = 5,
        max_results_per_query: int = 5,
        max_output_chars: int = 20000,
    ) -> None:
        if max_queries < 1 or max_results_per_query < 1:
            raise ValueError("Research limits must be positive.")
        self.provider = provider
        self.max_queries = max_queries
        self.max_results_per_query = max_results_per_query
        self.max_output_chars = max_output_chars

    def run(
        self,
        task: TaskRecord,
        report_progress: Callable[[int], None],
    ) -> str:
        queries = task.input.get("queries")
        if isinstance(queries, str):
            queries = [queries]
        if not isinstance(queries, list):
            raise ValueError("web_research input requires a queries list.")
        queries = [
            query.strip()
            for query in queries
            if isinstance(query, str) and query.strip()
        ]
        if not queries:
            raise ValueError("web_research queries cannot be empty.")
        queries = queries[: self.max_queries]
        count = min(
            int(task.input.get("count", self.max_results_per_query)),
            self.max_results_per_query,
        )
        freshness = task.input.get("freshness")
        domains = task.input.get("domains")
        if domains is not None and not isinstance(domains, list):
            raise ValueError("web_research domains must be a list.")

        unique_sources: dict[str, dict[str, Any]] = {}
        report_progress(5)
        for index, query in enumerate(queries, start=1):
            results = self.provider.search(
                query,
                count=count,
                freshness=freshness,
                domains=domains,
            )
            from maltose.tool_observations import observe_tool_return
            observe_tool_return('search_web', dict(query=query, count=count, freshness=freshness, domains=domains),
                dict(sources=[result.as_dict() for result in results], granularity='search_results', complete=True))
            for result in results:
                unique_sources.setdefault(result.url, result.as_dict())
            report_progress(5 + int(index / len(queries) * 90))

        payload = {
            "queries": queries,
            "source_count": len(unique_sources),
            "sources": list(unique_sources.values()),
        }
        return json.dumps(payload, ensure_ascii=False)[: self.max_output_chars]
