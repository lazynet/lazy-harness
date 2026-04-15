from lazy_harness.monitoring.event_id import derive_event_id


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
