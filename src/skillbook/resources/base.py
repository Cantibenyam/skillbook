"""Resource provider contract and the search-result value type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    """One candidate resource returned by a provider, enriched by the validator."""

    url: str
    title: str
    snippet: str = ""
    source: str = "web"  # which provider returned it (provenance)
    kind: str = "article"  # course | doc | book | article | video | repo | reference
    query: str = ""  # which search query surfaced it (provenance)
    status: str = "ok"  # set by the validator: ok | unverified
    final_url: str = ""  # post-redirect URL (set by the validator)


class ResourceProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]: ...
