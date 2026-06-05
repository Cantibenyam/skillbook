"""Provenance-first resource gathering and validation."""

from __future__ import annotations

from ..config import Config
from .base import ResourceProvider, SearchResult
from .gather import gather_resources
from .validate import LinkValidator, normalize_url
from .web import WebProvider
from .wikipedia import WikipediaProvider

__all__ = [
    "ResourceProvider",
    "SearchResult",
    "LinkValidator",
    "normalize_url",
    "WebProvider",
    "WikipediaProvider",
    "gather_resources",
    "default_providers",
    "default_validator",
]


def default_providers(config: Config) -> list[ResourceProvider]:
    ua = config.effective_user_agent()
    return [
        WikipediaProvider(user_agent=ua, timeout=config.request_timeout),
        WebProvider(),
    ]


def default_validator(config: Config) -> LinkValidator:
    return LinkValidator(
        user_agent=config.effective_user_agent(),
        timeout=config.request_timeout,
        concurrency=config.validation_concurrency,
    )
