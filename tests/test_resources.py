import httpx

from skillbook.llm.base import Usage
from skillbook.models import BookSpec, ChapterPlan, Section
from skillbook.resources import LinkValidator, gather_resources, normalize_url
from skillbook.resources.base import SearchResult
from skillbook.resources.validate import classify_status


def test_normalize_url_strips_tracking_fragment_and_trailing_slash():
    assert normalize_url("HTTPS://Ex.COM/Path/?utm_source=x&q=1#frag") == "https://ex.com/Path?q=1"
    assert normalize_url("https://ex.com/") == "https://ex.com/"  # root slash kept
    assert normalize_url("https://ex.com/a/") == "https://ex.com/a"


def test_classify_status():
    assert classify_status(404) == "dead"
    assert classify_status(410) == "dead"
    assert classify_status(200) == "ok"
    assert classify_status(204) == "ok"
    assert classify_status(403) == "unverified"
    assert classify_status(429) == "unverified"
    assert classify_status(500) == "unverified"


def _mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "ok.example":
            return httpx.Response(200, text="ok")
        if host == "dead.example":
            return httpx.Response(404, text="nope")
        if host == "blocked.example":
            return httpx.Response(403, text="forbidden")
        if host == "redirect.example":
            return httpx.Response(301, headers={"Location": "https://final.example/page"})
        if host == "final.example":
            return httpx.Response(200, text="final")
        return httpx.Response(200)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_validator_rejects_non_http_schemes():
    results = [
        SearchResult(url="javascript:alert(1)", title="js"),
        SearchResult(url="ftp://example.com/file", title="ftp"),
        SearchResult(url="https://ok.example/a", title="ok"),
    ]
    validator = LinkValidator(user_agent="t", concurrency=3)
    with _mock_client() as client:
        kept = validator.validate(results, client=client)
    assert [r.title for r in kept] == ["ok"]


def test_validator_survives_a_malformed_url_without_dropping_the_batch():
    results = [
        SearchResult(url="http://[::1zzz]/bad", title="bad"),  # raises httpx.InvalidURL
        SearchResult(url="https://ok.example/a", title="ok"),
    ]
    validator = LinkValidator(user_agent="t", concurrency=2)
    with _mock_client() as client:
        kept = validator.validate(results, client=client)
    assert [r.title for r in kept] == ["ok"]  # the bad URL is dropped, not the whole batch


def test_validator_drops_dead_keeps_blocked_dedups_and_follows_redirects():
    results = [
        SearchResult(url="https://ok.example/a?utm_source=x", title="A", source="wikipedia"),
        SearchResult(url="https://OK.example/a", title="A dup", source="web"),  # dup after normalize
        SearchResult(url="https://dead.example/x", title="Dead"),
        SearchResult(url="https://blocked.example/y", title="Blocked"),
        SearchResult(url="https://redirect.example/z", title="Redir"),
    ]
    validator = LinkValidator(user_agent="test", concurrency=3)
    with _mock_client() as client:
        kept = validator.validate(results, client=client)

    assert not any("dead.example" in r.url for r in kept), "dead link must be dropped"
    assert sum(1 for r in kept if "ok.example" in r.url) == 1, "duplicate must collapse"
    assert sorted(r.status for r in kept) == ["ok", "ok", "unverified"]
    assert any("final.example" in (r.final_url or "") for r in kept), "redirect should resolve"
    blocked = next(r for r in kept if "blocked.example" in r.url)
    assert blocked.status == "unverified"


# --- gather_resources (provenance-first) with injected fakes -------------------


class FakeLLM:
    model = "fake"

    def __init__(self, queries, selected):
        self.queries = queries
        self.selected = selected

    def complete_json(self, system, messages, *, schema, max_tokens, cacheable_system=False):
        if "queries" in schema["properties"]:
            return {"queries": self.queries}, Usage(1, 1, 0.0)
        return {"selected": self.selected}, Usage(1, 1, 0.0)


class FakeProvider:
    def __init__(self, name, urls):
        self.name = name
        self._urls = urls

    def search(self, query, *, limit=5):
        return [SearchResult(url=u, title=u, source=self.name) for u in self._urls]


class FakeValidator:
    def validate(self, results, *, client=None):
        for r in results:
            r.status = "ok"
            r.final_url = r.url
        return results


def _chapter():
    return ChapterPlan(id="ch01", title="C1", sections=[Section(title="S", key_points=["k"])])


def test_gather_respects_llm_index_selection_and_records_provenance():
    llm = FakeLLM(
        queries=["q1"],
        selected=[{"index": 2, "kind": "doc"}, {"index": 0, "kind": "article"}, {"index": 99, "kind": "x"}],
    )
    prov = FakeProvider("web", ["https://a.com", "https://b.com", "https://c.com"])
    res, usage = gather_resources(
        llm, BookSpec(topic="T"), _chapter(),
        providers=[prov], validator=FakeValidator(), max_results=6,
    )
    assert [r.url for r in res] == ["https://c.com", "https://a.com"]  # index order honored, 99 skipped
    assert res[0].kind == "doc" and res[1].kind == "article"
    assert all(r.query == "q1" and r.source == "web" for r in res), "provenance recorded"
    assert usage.input_tokens == 2  # queries call + rank call


def test_gather_falls_back_to_first_n_when_llm_picks_nothing():
    llm = FakeLLM(queries=["q1"], selected=[])
    prov = FakeProvider("web", ["https://a.com", "https://b.com", "https://c.com"])
    res, _ = gather_resources(
        llm, BookSpec(topic="T"), _chapter(),
        providers=[prov], validator=FakeValidator(), max_results=6,
    )
    assert [r.url for r in res] == ["https://a.com", "https://b.com", "https://c.com"]
