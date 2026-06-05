"""Provenance-first resource gathering for one chapter.

The invariant: the LLM never produces a URL. It (1) writes search queries and
(2) picks among real, validated candidates by index. Every returned Resource
therefore carries provenance (source + query) and a validation status.
"""

from __future__ import annotations

from ..llm import LLMProvider, Usage
from ..models import BookSpec, ChapterPlan, Resource
from ..prompts import (
    resource_queries_system,
    resource_queries_user,
    resource_rank_system,
    resource_rank_user,
)
from .base import ResourceProvider, SearchResult
from .validate import LinkValidator

_QUERIES_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
}

_RANK_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"index": {"type": "integer"}, "kind": {"type": "string"}},
                "required": ["index", "kind"],
            },
        }
    },
    "required": ["selected"],
}


def gather_resources(
    llm: LLMProvider,
    spec: BookSpec,
    chapter: ChapterPlan,
    *,
    providers: list[ResourceProvider],
    validator: LinkValidator,
    max_results: int = 6,
    queries_per: int = 3,
    per_query_limit: int = 5,
) -> tuple[list[Resource], Usage]:
    total = Usage()

    # 1. LLM writes search queries (no URLs).
    qdata, u = llm.complete_json(
        resource_queries_system(),
        [{"role": "user", "content": resource_queries_user(spec, chapter)}],
        schema=_QUERIES_SCHEMA,
        max_tokens=400,
    )
    total = total + u
    queries = [q.strip() for q in (qdata.get("queries") or []) if isinstance(q, str) and q.strip()]
    queries = queries[:queries_per] or [chapter.title]

    # 2. Gather real candidates from every provider.
    raw: list[SearchResult] = []
    for query in queries:
        for provider in providers:
            for result in provider.search(query, limit=per_query_limit):
                result.query = query
                raw.append(result)
    if not raw:
        return [], total

    # 3. Validate reachability (drops dead links, dedups, keeps bot-blocked as 'unverified').
    validated = validator.validate(raw)
    if not validated:
        return [], total

    # 4. LLM ranks among REAL candidates by index only.
    candidates = "\n".join(
        f"[{i}] ({r.source}) {r.title} — {r.url}\n     {r.snippet[:160]}"
        for i, r in enumerate(validated)
    )
    rdata, u = llm.complete_json(
        resource_rank_system(),
        [{"role": "user", "content": resource_rank_user(spec, chapter, candidates, max_results)}],
        schema=_RANK_SCHEMA,
        max_tokens=600,
    )
    total = total + u

    chosen: list[tuple[SearchResult, str]] = []
    used: set[int] = set()
    for sel in rdata.get("selected") or []:
        idx = sel.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(validated) or idx in used:
            continue
        used.add(idx)
        result = validated[idx]
        chosen.append((result, str(sel.get("kind") or result.kind)))
        if len(chosen) >= max_results:
            break

    # Fallback: if the model returned nothing usable, take the first N validated.
    if not chosen:
        chosen = [(r, r.kind) for r in validated[:max_results]]

    resources = [
        Resource(
            title=r.title,
            url=r.final_url or r.url,
            source=r.source,
            query=r.query,
            kind=kind,
            snippet=r.snippet[:300],
            status=r.status,
        )
        for r, kind in chosen
    ]
    return resources, total
