"""Wikipedia / MediaWiki opensearch provider — no API key, canonical low-rot URLs.

The reliable backbone of the resource layer. Wikimedia policy asks for a
descriptive User-Agent, which we send from config.
"""

from __future__ import annotations

import httpx

from .base import SearchResult


class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, *, user_agent: str, lang: str = "en", timeout: float = 10.0) -> None:
        self.user_agent = user_agent
        self.lang = lang
        self.timeout = timeout

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        url = f"https://{self.lang}.wikipedia.org/w/api.php"
        params = {
            "action": "opensearch",
            "search": query,
            "limit": limit,
            "namespace": 0,
            "format": "json",
        }
        try:
            resp = httpx.get(
                url, params=params, headers={"User-Agent": self.user_agent}, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        # opensearch -> [query, [titles], [descriptions], [urls]]
        titles = data[1] if len(data) > 1 else []
        descriptions = data[2] if len(data) > 2 else []
        urls = data[3] if len(data) > 3 else []
        results: list[SearchResult] = []
        for i, link in enumerate(urls):
            results.append(
                SearchResult(
                    url=link,
                    title=titles[i] if i < len(titles) else link,
                    snippet=descriptions[i] if i < len(descriptions) else "",
                    source="wikipedia",
                    kind="reference",
                    query=query,
                )
            )
        return results
