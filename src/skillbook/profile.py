"""Persistent learner profile load/save."""

from __future__ import annotations

from .config import APP_DIR, PROFILE_PATH
from .models import Profile


def load_profile() -> Profile | None:
    if PROFILE_PATH.exists():
        return Profile.model_validate_json(PROFILE_PATH.read_text(encoding="utf-8"))
    return None


def save_profile(profile: Profile) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
