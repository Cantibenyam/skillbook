"""Configuration: defaults, filesystem locations, and persisted (non-secret) settings.

API keys are intentionally NOT stored here. The LLM layer reads them from the
environment (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ...) the same way LiteLLM
and the provider SDKs do. This module only holds preferences and paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_MODEL = "anthropic/claude-opus-4-8"
CHEAPER_MODEL = "anthropic/claude-sonnet-4-6"

APP_DIR = Path.home() / ".skillbook"
CONFIG_PATH = APP_DIR / "config.json"
PROFILE_PATH = APP_DIR / "profile.json"

DEFAULT_USER_AGENT = "SkillBook/0.1 (+https://github.com/imangaliduisebayev/skillbook)"


class Config(BaseModel):
    """Non-secret, user-tunable settings, persisted at ``~/.skillbook/config.json``."""

    model: str = DEFAULT_MODEL
    user_agent: str = DEFAULT_USER_AGENT
    # Appended to the User-Agent for politeness with Wikipedia / Open Library, which
    # ask for a contact in the UA. Optional; left blank by default.
    contact_email: str = ""
    request_timeout: float = 10.0
    validation_concurrency: int = 8
    max_resources_per_chapter: int = 6
    # Relative to the current working directory.
    runs_dir: str = "runs"
    books_dir: str = "books"

    def effective_user_agent(self) -> str:
        if self.contact_email:
            return f"{self.user_agent} ({self.contact_email})"
        return self.user_agent


def load_config() -> Config:
    """Load config from disk (or defaults), then apply environment overrides."""
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = Config.model_validate(data)
    else:
        cfg = Config()
    if value := os.getenv("SKILLBOOK_MODEL"):
        cfg.model = value
    if value := os.getenv("SKILLBOOK_RUNS_DIR"):
        cfg.runs_dir = value
    if value := os.getenv("SKILLBOOK_BOOKS_DIR"):
        cfg.books_dir = value
    return cfg


def save_config(cfg: Config) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
