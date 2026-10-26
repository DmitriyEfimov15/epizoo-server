from datetime import date
from types import SimpleNamespace

from etl.news import parse_feed
from etl.reconcile import compare_counts


def test_rss_parses_dates_and_deduplicates_links():
    feed = """<rss><channel>
    <item><title>Бешенство в Московской области</title>
    <link>https://fsvps.gov.ru/news/1</link>
    <pubDate>Mon, 12 Oct 2026 12:00:00 +0300</pubDate></item>
    <item><title>Дубль</title>
    <link>https://fsvps.gov.ru/news/1</link></item></channel></rss>"""
    items = parse_feed(feed)
    assert len(items) == 1
    assert items[0]["date"] == date(2026, 10, 12)
    assert items[0]["title"] == "Бешенство в Московской области"


def test_reconciliation_uses_report_publication_week_not_act_date():
    week = date(2026, 10, 2)
    reports = [SimpleNamespace(id=1, date=date(2026, 10, 5), type="daily")]
    events = [
        SimpleNamespace(
            report_id=1,
            date=date(2026, 9, 30),
            disease_id=1,
            region_code="50",
            kind="quarantine_set",
        )
    ]
    weekly = [
        SimpleNamespace(
            week_start=week,
            week_end=date(2026, 10, 8),
            disease_id=1,
            region_code="50",
            kind="quarantine_set",
            count=2,
        )
    ]
    result = compare_counts(reports, events, weekly)
    assert len(result) == 1
    assert result[0]["daily_count"] == 1
    assert result[0]["weekly_count"] == 2
    assert result[0]["difference"] == -1
