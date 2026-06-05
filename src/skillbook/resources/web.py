"""General web search via ddgs (the renamed duckduckgo-search).

Best-effort breadth: ddgs is known to rate-limit intermittently (202s), so this
retries with exponential backoff + jitter and degrades to an empty list rather
than raising. It is never the sole source — Wikipedia is the reliable backbone.
The piracy-prone 'books' backend is never used.
"""

from __future__ import annotations

import random
import time

from .base import SearchResult


class WebProvider:
    name = "web"

    def __init__(self, *, max_retries: int = 3, base_delay: float = 1.0) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except Exception:
            return []

        for attempt in range(self.max_retries):
            try:
                with DDGS() as ddgs:
                    rows = ddgs.text(query, max_results=limit)
                results: list[SearchResult] = []
                for row in rows or []:
                    url = row.get("href") or row.get("url") or ""
                    if not url:
                        continue
                    results.append(
                        SearchResult(
                            url=url,
                            title=row.get("title") or url,
                            snippet=row.get("body") or "",
                            source="web",
                            kind="article",
                            query=query,
                        )
                    )
                return results
            except Exception:
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay * (2**attempt) + random.uniform(0, 0.5))
        return []
