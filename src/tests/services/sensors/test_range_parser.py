import pytest

from app.services.sensors.range_parser import matches_range, parse_range


def test_parse_simple_range() -> None:
    segments = parse_range("1-3")
    assert len(segments) == 1
    assert segments[0].lo == 1.0
    assert segments[0].hi == 3.0


def test_parse_multi_segment() -> None:
    segments = parse_range("1-3, 7-10")
    assert len(segments) == 2
    assert (segments[0].lo, segments[0].hi) == (1.0, 3.0)
    assert (segments[1].lo, segments[1].hi) == (7.0, 10.0)


def test_parse_open_upper() -> None:
    segments = parse_range("4-")
    assert segments[0].lo == 4.0
    assert segments[0].hi is None


def test_parse_open_lower() -> None:
    segments = parse_range("-10")
    assert segments[0].lo is None
    assert segments[0].hi == 10.0


def test_parse_combined_open_segments() -> None:
    segments = parse_range("-3, 10-")
    assert (segments[0].lo, segments[0].hi) == (None, 3.0)
    assert (segments[1].lo, segments[1].hi) == (10.0, None)


def test_parse_single_value() -> None:
    segments = parse_range("5")
    assert segments[0].lo == 5.0
    assert segments[0].hi == 5.0


def test_parse_invalid_empty() -> None:
    with pytest.raises(ValueError):
        parse_range("")


def test_parse_invalid_dash_only() -> None:
    with pytest.raises(ValueError):
        parse_range("-")


def test_parse_invalid_lo_gt_hi() -> None:
    with pytest.raises(ValueError):
        parse_range("10-3")


def test_matches_inclusive_bounds() -> None:
    assert matches_range(1, "1-3")
    assert matches_range(3, "1-3")
    assert not matches_range(0.99, "1-3")
    assert not matches_range(3.01, "1-3")


def test_matches_open_upper() -> None:
    assert matches_range(4, "4-")
    assert matches_range(9999, "4-")
    assert not matches_range(3.99, "4-")


def test_matches_open_lower() -> None:
    assert matches_range(10, "-10")
    assert matches_range(-100, "-10")
    assert not matches_range(10.01, "-10")


def test_matches_disjoint_ranges() -> None:
    assert matches_range(2, "1-3, 7-10")
    assert matches_range(8, "1-3, 7-10")
    assert not matches_range(5, "1-3, 7-10")


def test_matches_none_spec() -> None:
    assert matches_range(123.4, None)
