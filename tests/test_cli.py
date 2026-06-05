import pytest
import typer
from typer.testing import CliRunner

from skillbook.cli import _ask_list, _require_api_key, app

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "new", "resume", "list", "config"):
        assert cmd in result.output


def test_require_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(typer.Exit):
        _require_api_key("anthropic/claude-opus-4-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _require_api_key("anthropic/claude-opus-4-8")  # no raise
    _require_api_key("mock/x")  # mock never needs a key
    _require_api_key("ollama/llama3")  # local provider has no env mapping -> allowed


def test_ask_list_parses_csv(monkeypatch):
    import skillbook.cli as cli

    monkeypatch.setattr(cli.Prompt, "ask", lambda *a, **k: "python,  sql , , git")
    assert _ask_list("x") == ["python", "sql", "git"]


def test_config_show_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLBOOK_RUNS_DIR", str(tmp_path / "runs"))
    result = runner.invoke(app, ["config", "--show"])
    assert result.exit_code == 0


def test_list_empty_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLBOOK_RUNS_DIR", str(tmp_path / "runs"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0


def test_new_mock_generates_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLBOOK_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("SKILLBOOK_BOOKS_DIR", str(tmp_path / "books"))
    out = tmp_path / "out.pdf"
    result = runner.invoke(
        app,
        ["new", "--mock", "--yes", "--topic", "Learn SQL", "--depth", "primer", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
