from types import SimpleNamespace

from skillbook.llm import MockProvider, Usage, get_provider
from skillbook.llm.base import fake_from_schema
from skillbook.llm import litellm_provider as llm_mod
from skillbook.llm.litellm_provider import LiteLLMProvider, _loads_lenient, _norm_stop


def _fake_resp(content=None, tool_args=None):
    func = SimpleNamespace(arguments=tool_args) if tool_args is not None else None
    tool_calls = [SimpleNamespace(function=func)] if func else None
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_get_provider_returns_mock():
    assert isinstance(get_provider(mock=True), MockProvider)
    assert isinstance(get_provider("mock/x"), MockProvider)


def test_mock_stream_uses_title_hint_and_matches_full_text():
    p = get_provider(mock=True)
    chunks: list[str] = []
    c = p.stream_complete(
        "sys",
        [{"role": "user", "content": "TITLE: Borrowing in Rust"}],
        max_tokens=500,
        on_delta=chunks.append,
    )
    assert "Borrowing in Rust" in c.text
    assert "".join(chunks) == c.text
    assert c.stop_reason == "stop" and not c.truncated


def test_mock_markdown_has_required_sections():
    c = get_provider(mock=True).complete("sys", [{"role": "user", "content": "x"}], max_tokens=500)
    for needle in ("### Worked example", "### Exercises", "### Quiz", "**Answers:**", "```python"):
        assert needle in c.text


def test_fake_from_schema_builds_valid_nested_object():
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"target_words": {"type": "integer"}},
                            },
                        },
                    },
                },
            },
            "style": {"type": "string", "enum": ["casual", "scientific"]},
        },
        "required": ["title", "chapters"],
    }
    data = fake_from_schema(schema)
    assert data["style"] == "casual"
    assert isinstance(data["chapters"], list) and data["chapters"]
    assert data["chapters"][0]["sections"]
    assert isinstance(data["chapters"][0]["sections"][0]["target_words"], int)


def test_usage_addition():
    u = Usage(1, 2, 0.5) + Usage(3, 4, 0.5)
    assert (u.input_tokens, u.output_tokens, u.cost_usd) == (4, 6, 1.0)


def test_extract_json_from_content_or_tool_calls():
    assert LiteLLMProvider._extract_json(_fake_resp(content='{"a": 1}')) == {"a": 1}
    # content empty -> read the structured-output tool call instead
    assert LiteLLMProvider._extract_json(_fake_resp(content=None, tool_args='{"b": 2}')) == {"b": 2}
    assert LiteLLMProvider._extract_json(_fake_resp(content="not json")) is None
    assert LiteLLMProvider._extract_json(SimpleNamespace(choices=[])) is None


def test_complete_json_falls_back_to_plain_retry(monkeypatch):
    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1
        # 1st call (structured) yields nothing readable; 2nd (plain retry) returns JSON.
        return _fake_resp(content=None) if calls["n"] == 1 else _fake_resp(content='{"ok": true}')

    monkeypatch.setattr(llm_mod.litellm, "completion", fake_completion)
    provider = LiteLLMProvider("anthropic/claude-opus-4-8")
    data, _usage = provider.complete_json(
        "sys", [{"role": "user", "content": "x"}], schema={"type": "object"}, max_tokens=100
    )
    assert data == {"ok": True}
    assert calls["n"] == 2  # fell back to a second, schema-free call


def test_litellm_helpers_and_cache_control():
    lp = LiteLLMProvider("anthropic/claude-opus-4-8")
    assert lp._is_anthropic()
    msgs = lp._messages("PREFIX", [{"role": "user", "content": "hi"}], cacheable_system=True)
    assert msgs[0]["content"][0]["cache_control"]["type"] == "ephemeral"
    # Non-anthropic models keep a plain string system message.
    op = LiteLLMProvider("openai/gpt-5.5")
    assert op._messages("P", [], cacheable_system=True)[0]["content"] == "P"
    assert _norm_stop("length") == "max_tokens"
    assert _norm_stop("end_turn") == "stop"
    assert _loads_lenient('noise {"a": 1} trailing') == {"a": 1}
