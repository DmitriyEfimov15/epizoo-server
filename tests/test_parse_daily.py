import json
from datetime import date
from pathlib import Path

import pymupdf
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_manually_transcribed_events():
    from etl.parse_daily import parse_daily

    reference = json.loads((FIXTURES / "daily_expected.json").read_text())
    for filename, expected in reference.items():
        report_date = date.fromisoformat(filename[6:16])
        result = parse_daily(FIXTURES / filename, report_date)
        for row in expected:
            matches = [
                event
                for event in result.events
                if all(getattr(event, key) == value for key, value in row.items())
            ]
            assert len(matches) == 1, (filename, row, result.events)


@pytest.mark.parametrize(
    "filename,count",
    [
        ("daily_2026-08-31.pdf", 12),
        ("daily_2026-06-15.pdf", 23),
        ("daily_2026-10-09.pdf", 26),
    ],
)
def test_full_event_counts(filename, count):
    from etl.parse_daily import parse_daily

    assert len(parse_daily(FIXTURES / filename, date(2026, 10, 9)).events) == count


def test_common_score_continues_across_page_and_regions():
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-10-09.pdf", date(2026, 10, 9))
    events = [
        event
        for event in result.events
        if event.disease == "Лейкоз КРС" and event.kind == "quarantine_set"
    ]
    assert len(events) == 5
    assert all(event.scores == [1, 3, 4, 3, 0, 4] and event.total == 2.5 for event in events)
    lifted = next(event for event in result.events if event.locality == "Петропавловская")
    assert lifted.scores == [0, 2, 2, 0, 0, 4]
    assert lifted.total == 1.3


def test_footnotes_and_act_date_are_attached_to_correct_locality():
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-10-09.pdf", date(2026, 10, 9))
    event = next(event for event in result.events if event.locality == "Солнечное")
    assert event.source_urls == ["http://publication.pravo.gov.ru/document/2200202610070001"]
    assert event.date == date(2026, 10, 7)
    event = next(event for event in result.events if event.locality == "Черная Грязь")
    assert event.date == date(2026, 9, 29)


def test_partial_pdf_preserves_events_and_reports_page_issue(tmp_path):
    from etl.parse_daily import parse_daily

    path = tmp_path / "partial.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_htmlbox(
            (20, 20, 560, 700),
            "Бешенство животных<br>• Алтайский край1:<br>"
            "Алейский район, с. Толстая Дуброва – лошадь.<br>"
            "ОЦЕНКА: 1 4 2<br>",
        )
        doc.save(path)
    result = parse_daily(path, date(2026, 10, 9))
    assert result.issues
    assert any("1" in issue for issue in result.issues)
    assert len(result.events) == 1
    assert result.events[0].locality == "Толстая Дуброва"


def test_invalid_pdf_returns_issue(tmp_path):
    from etl.parse_daily import parse_daily

    path = tmp_path / "broken.pdf"
    path.write_bytes(b"broken pdf")
    result = parse_daily(path, date(2026, 10, 9))
    assert result.events == []
    assert result.issues


def test_normalize_locality_ignores_type_case_and_yo():
    from etl.normalize import normalize_locality

    assert normalize_locality("  с. БЕРЁЗОВКА ") == normalize_locality("село Березовка")
    assert normalize_locality("п. Новый Кутулук") == "новый кутулук"


def test_alternative_bullet_and_non_disease_prose():
    from etl.normalize import disease_heading
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-04-29.pdf", date(2026, 4, 29))
    assert any(event.locality == "Богослово" for event in result.events)
    assert disease_heading("бруцеллез, лейкоз, грипп птиц и другие болезни") is None


@pytest.mark.parametrize("filename", ["daily_2026-03-27.pdf", "daily_2026-08-19.pdf"])
def test_prevention_and_lab_activity_do_not_create_quarantines(filename):
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / filename, date(2026, 8, 19))
    assert all("профилактические" not in event.disease for event in result.events)
    assert all("ФГБУ" not in event.region for event in result.events)


def test_explicit_order_in_text_wins_over_contradicting_heading(tmp_path):
    from etl.parse_daily import parse_daily

    path = tmp_path / "contradiction.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_htmlbox(
            (20, 20, 560, 700),
            "Лейкоз КРС<br>• Алтайский край:<br>"
            "Приказом от 01.10.2026 отменены ограничительные мероприятия "
            "(карантин) на территории с. Березовка.<br>"
            "ОЦЕНКА: 0 2 2 0 0 2<br>ИТОГ: 1",
        )
        doc.save(path)
    result = parse_daily(path, date(2026, 10, 9))
    assert len(result.events) == 1
    assert result.events[0].kind == "quarantine_lifted"
    assert any("противоречит" in issue for issue in result.issues)


def test_shared_district_applies_to_all_places_in_same_address_line():
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-03-11.pdf", date(2026, 3, 11))
    events = [event for event in result.events if event.locality in {"Горный", "Ленина"}]
    assert len(events) == 2
    assert all(event.district == "Оренбургский район" for event in events)


def test_district_names_are_not_species():
    from etl.normalize import extract_species

    assert extract_species("Лейкоз КРС") == ["cattle"]
    assert extract_species("Козельский район") == []


@pytest.mark.parametrize("place", ["Быковский район", "Коровино", "Лисицыно", "Удалось"])
def test_place_names_do_not_imply_animal_species(place):
    from etl.normalize import extract_species

    assert extract_species(place) == []


def test_relative_outbreak_address_is_not_collapsed_to_nearest_village():
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-10-09.pdf", date(2026, 10, 9))
    events = [event for event in result.events if event.region == "Забайкальский край"]
    assert len(events) == 2
    assert all("км" in event.locality for event in events)
    assert any("границы" in issue for issue in result.issues)


def test_unknown_section_does_not_inherit_previous_disease(tmp_path):
    from etl.parse_daily import parse_daily

    path = tmp_path / "unknown.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_htmlbox(
            (20, 20, 560, 700),
            "Лейкоз КРС<br>• Алтайский край:<br>"
            "с. Березовка.<br>ОЦЕНКА: 1 3 4 3 0 4<br>ИТОГ: 2,5<br>"
            "Неизвестная болезнь<br>• Самарская область:<br>с. Высокое.",
        )
        doc.save(path)
    result = parse_daily(path, date(2026, 10, 9))
    assert len(result.events) == 1
    assert any("Неизвестная болезнь" in issue for issue in result.issues)


@pytest.mark.parametrize(
    "heading,disease,kind",
    [
        ("Парагрипп-3 КРС, снятие карантина", "Парагрипп-3 КРС", "quarantine_lifted"),
        ("Пироплазмоз собак", "Пироплазмоз собак", "quarantine_set"),
        ("Лептоспироз КРС, продление карантина", "Лептоспироз КРС", "quarantine_set"),
    ],
)
def test_additional_daily_headings(heading, disease, kind):
    from etl.normalize import disease_heading

    assert disease_heading(heading) == (disease, kind)


def test_act_date_written_with_month_name(tmp_path):
    from etl.parse_daily import parse_daily

    path = tmp_path / "date.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_htmlbox(
            (20, 20, 560, 700),
            "Лейкоз КРС<br>• Алтайский край:<br>"
            "Приказом от 1 октября 2026 года установлены ограничительные "
            "мероприятия (карантин) в селе Березовка.<br>"
            "ОЦЕНКА: 1 3 4 3 0 4<br>ИТОГ: 2,5",
        )
        doc.save(path)
    result = parse_daily(path, date(2026, 10, 9))
    assert result.events[0].date == date(2026, 10, 1)


def test_district_only_address_is_retained_among_other_localities():
    from etl.parse_daily import parse_daily

    result = parse_daily(FIXTURES / "daily_2026-03-11.pdf", date(2026, 3, 11))
    events = [
        event
        for event in result.events
        if event.region == "Оренбургская область" and event.kind == "quarantine_lifted"
    ]
    assert len(events) == 3
    assert any(event.district == "Красногвардейский район" for event in events)
