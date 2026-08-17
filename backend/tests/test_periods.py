from datetime import date

import pytest

from app.core.periods import DateRange, intersect, make_range, split_at, subtract


def r(a: str, b: str) -> DateRange:
    return DateRange(date.fromisoformat(a), date.fromisoformat(b))


def as_tuples(ranges):
    return [(item.start.isoformat(), item.end.isoformat()) for item in ranges]


def test_days_include_both_boundaries():
    assert r("2022-01-01", "2022-01-01").days == 1
    assert r("2022-01-01", "2022-01-31").days == 31


def test_reversed_range_is_rejected():
    with pytest.raises(ValueError):
        r("2022-02-01", "2022-01-01")


def test_make_range_returns_none_for_empty_period():
    assert make_range(date(2022, 2, 1), date(2022, 1, 1)) is None


def test_subtract_cut_in_the_middle_gives_two_pieces():
    result = subtract(r("2022-01-01", "2022-12-31"), [r("2022-06-01", "2022-08-31")])
    assert as_tuples(result) == [
        ("2022-01-01", "2022-05-31"),
        ("2022-09-01", "2022-12-31"),
    ]


def test_subtract_covering_cut_gives_nothing():
    assert subtract(r("2022-06-05", "2022-07-05"), [r("2022-06-01", "2022-08-31")]) == []


def test_subtract_non_overlapping_cut_changes_nothing():
    result = subtract(r("2022-01-01", "2022-03-01"), [r("2022-06-01", "2022-08-31")])
    assert as_tuples(result) == [("2022-01-01", "2022-03-01")]


def test_subtract_multiple_cuts():
    result = subtract(
        r("2022-01-01", "2022-12-31"),
        [r("2022-03-01", "2022-03-31"), r("2022-06-01", "2022-08-31")],
    )
    assert as_tuples(result) == [
        ("2022-01-01", "2022-02-28"),
        ("2022-04-01", "2022-05-31"),
        ("2022-09-01", "2022-12-31"),
    ]


def test_subtract_touching_boundaries_keeps_adjacent_days():
    result = subtract(r("2022-05-31", "2022-09-01"), [r("2022-06-01", "2022-08-31")])
    assert as_tuples(result) == [
        ("2022-05-31", "2022-05-31"),
        ("2022-09-01", "2022-09-01"),
    ]


def test_split_at_uses_boundary_as_first_day_of_new_piece():
    result = split_at(r("2021-12-02", "2022-01-31"), [date(2022, 1, 1)])
    assert as_tuples(result) == [
        ("2021-12-02", "2021-12-31"),
        ("2022-01-01", "2022-01-31"),
    ]


def test_split_at_ignores_boundaries_outside_the_segment():
    result = split_at(r("2022-02-01", "2022-02-28"), [date(2021, 1, 1), date(2023, 1, 1)])
    assert as_tuples(result) == [("2022-02-01", "2022-02-28")]


def test_split_at_boundary_equal_to_start_does_not_create_empty_piece():
    result = split_at(r("2022-01-01", "2022-01-31"), [date(2022, 1, 1)])
    assert as_tuples(result) == [("2022-01-01", "2022-01-31")]


def test_intersect():
    assert as_tuples([intersect(r("2022-01-01", "2022-06-30"), r("2022-05-01", "2022-12-31"))]) == [
        ("2022-05-01", "2022-06-30")
    ]
    assert intersect(r("2022-01-01", "2022-02-01"), r("2022-05-01", "2022-12-31")) is None
