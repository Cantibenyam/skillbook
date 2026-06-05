from skillbook.config import DEFAULT_MODEL
from skillbook.models import BookSpec, Depth, Profile, RunState, Style


def test_default_model_is_opus():
    assert DEFAULT_MODEL == "anthropic/claude-opus-4-8"


def test_bookspec_compact_includes_profile_and_interview():
    spec = BookSpec(
        topic="Learn Rust",
        profile=Profile(name="Iman", current_level="intermediate", goals=["backend role"]),
        outcome="ship a CLI tool",
        must_cover=["ownership"],
        depth=Depth.comprehensive,
        style=Style.scientific,
    )
    text = spec.compact()
    assert "TOPIC: Learn Rust" in text
    assert "DEPTH: comprehensive" in text
    assert "REGISTER: scientific" in text
    assert "Iman" in text
    assert "backend role" in text
    assert "ship a CLI tool" in text
    assert "ownership" in text


def test_runstate_roundtrips_through_json():
    spec = BookSpec(topic="X")
    rs = RunState(run_id="r1", spec=spec)
    restored = RunState.model_validate_json(rs.model_dump_json())
    assert restored.run_id == "r1"
    assert restored.stage == "created"
    assert restored.spec.topic == "X"
