from datetime import date
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "filename,total,rows",
    [
        ("weekly_2026-05-29_2026-06-04.pdf", 84, 51),
        ("weekly_2026-08-28_2026-09-03.pdf", 64, 33),
        ("weekly_2026-09-04_2026-09-10.pdf", 50, 31),
        ("weekly_2026-06-05_2026-06-11.pdf", 81, 40),
        ("weekly_2026-09-11_2026-09-17.pdf", 54, 32),
    ],
)
def test_hand_counted_weekly_totals(filename, total, rows):
    from etl.parse_weekly import parse_weekly

    result = parse_weekly(FIXTURES / filename, date.fromisoformat(filename[7:17]))
    assert len(result.counts) == rows
    assert sum(row.count for row in result.counts) == total
    assert not result.issues


def test_weekly_disease_survives_page_break():
    from etl.parse_weekly import parse_weekly

    result = parse_weekly(FIXTURES / "weekly_2026-08-28_2026-09-03.pdf", date(2026, 8, 28))
    row = next(row for row in result.counts if row.region == "Калужская область")
    assert row.disease == "Лейкоз КРС"
    assert row.kind == "quarantine_lifted"
    assert row.species == ["cattle"]
    assert row.count == 1


def test_weekly_header_without_date():
    from etl.parse_weekly import parse_weekly

    result = parse_weekly(FIXTURES / "weekly_2026-06-12_2026-06-18.pdf", date(2026, 6, 12))
    assert result.counts
    assert not result.issues


@pytest.mark.parametrize(
    "filename,disease",
    [
        ("weekly_2026-05-22_2026-05-28.pdf", "Хламидиоз животных/птиц"),
        ("weekly_2026-09-25_2026-10-01.pdf", "Заразный узелковый дерматит"),
    ],
)
def test_additional_disease_headings(filename, disease):
    from etl.parse_weekly import parse_weekly

    result = parse_weekly(FIXTURES / filename, date(2026, 9, 25))
    assert any(row.disease == disease for row in result.counts)
    assert not result.issues
