"""Link validation — the backstop against dead/rotted links.

Provenance (the model never emits URLs) is the primary anti-hallucination guard;
this is the second line: normalize, de-dupe, and check reachability. The key rule
from research: 403/429/503/challenge responses are *bot-blocks*, not dead links —
they are kept at lower confidence ("unverified"), never discarded, so we don't
throw away real WAF-protected docs/Medium/.edu pages.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .base import SearchResult

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "ref", "ref_src", "spm", "mc_cid", "mc_eid", "igshid"}
_DEAD_CODES = {404, 410}


def normalize_url(url: str) -> str:
    """Canonicalize for de-duplication: lowercase scheme/host, strip tracking params,
    drop the fragment, and remove a trailing slash on non-root paths."""
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return url.strip()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith(_TRACKING_PREFIXES) or k.lower() in _TRACKING_KEYS)
    ]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def classify_status(code: int) -> str:
    """Map an HTTP status onto: dead | ok | unverified."""
    if code in _DEAD_CODES:
        return "dead"
    if 200 <= code < 300:
        return "ok"
    # 401/403/429/5xx and anything else: real page we just can't fetch — keep, low confidence.
    return "unverified"


class LinkValidator:
    def __init__(self, *, user_agent: str, timeout: float = 10.0, concurrency: int = 8) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.concurrency = concurrency

    def _check_one(self, client: httpx.Client, result: SearchResult) -> SearchResult | None:
        """Return the result with status/final_url set, or None if the link is unusable."""
        # Only fetch web URLs; anything else (mailto:, javascript:, file:, malformed) is dropped.
        if not result.url.lower().startswith(("http://", "https://")):
            return None
        try:
            resp = client.head(result.url)
            # Some servers reject HEAD or hide the real status behind it.
            if resp.status_code in (405, 501) or resp.status_code >= 400:
                resp = client.get(result.url)
        except Exception:
            # Any failure on a single link (HTTP error, malformed/invalid URL, DNS/TLS,
            # encoding) drops only that candidate — never the whole batch.
            try:
                resp = client.get(result.url)
            except Exception:
                return None
        status = classify_status(resp.status_code)
        if status == "dead":
            return None
        result.status = "ok" if status == "ok" else "unverified"
        result.final_url = str(resp.url)
        return result

    def validate(
        self, results: list[SearchResult], *, client: httpx.Client | None = None
    ) -> list[SearchResult]:
        # De-duplicate by normalized URL (pre-fetch), keeping the first occurrence.
        seen: set[str] = set()
        deduped: list[SearchResult] = []
        for r in results:
            key = normalize_url(r.url)
            if key in seen:
                continue
            seen.add(key)
            r.url = key
            deduped.append(r)
        if not deduped:
            return []

        owns_client = client is None
        if client is None:
            client = httpx.Client(
                follow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
            )
        try:
            with ThreadPoolExecutor(max_workers=max(1, self.concurrency)) as pool:
                checked = list(pool.map(lambda r: self._check_one(client, r), deduped))
        finally:
            if owns_client:
                client.close()

        # Post-fetch de-dup by final (post-redirect) URL.
        seen_final: set[str] = set()
        kept: list[SearchResult] = []
        for r in checked:
            if r is None:
                continue
            key = normalize_url(r.final_url or r.url)
            if key in seen_final:
                continue
            seen_final.add(key)
            kept.append(r)
        return kept
