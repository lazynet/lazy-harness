import hashlib

from lazy_harness.monitoring.event_id import derive_event_id


def test_event_id_pins_the_canonical_string_format() -> None:
    """The exact bytes hashed, independently derived here, so the Postgres
    sink's `left(encode(sha256(convert_to(profile || chr(31) || session ||
    chr(31) || model, 'UTF8')), 'hex'), 32)` can be checked against this test
    rather than against `derive_event_id`'s own source."""
    profile, session, model = "claude-lazy", "s1", "sonnet"
    expected = hashlib.sha256(f"{profile}\x1f{session}\x1f{model}".encode()).hexdigest()[:32]

    assert derive_event_id(profile=profile, session=session, model=model) == expected


def test_event_id_is_deterministic() -> None:
    a = derive_event_id(profile="p", session="s", model="m")
    b = derive_event_id(profile="p", session="s", model="m")
    assert a == b


def test_event_id_differs_by_input() -> None:
    a = derive_event_id(profile="p", session="s", model="m")
    b = derive_event_id(profile="p", session="s", model="other")
    assert a != b


def test_event_id_is_fixed_length() -> None:
    assert len(derive_event_id(profile="p", session="s", model="m")) == 32
