from datetime import date

import httpx

import etl.fetch as fetch


def test_index_accepts_relative_urls_and_html_entities():
    page = """
    <li class='report'><strong>12.10.2026</strong><br/>
    <a href='/docs/report.pdf?download=1'>Оперативное &amp; сообщение</a></li>
    <li><strong>09.10.2026</strong><br>
    <a href='https://fsvps.gov.ru/week.pdf'>Сводное сообщение с 02.10.2026 по 08.10.2026</a></li>"""
    refs = fetch.parse_index(page)
    assert len(refs) == 2
    assert refs[0].url == "https://fsvps.gov.ru/docs/report.pdf?download=1"
    assert refs[0].title == "Оперативное & сообщение"
    assert refs[1].kind == "weekly"
    assert refs[1].period_from == date(2026, 10, 2)


async def test_invalid_download_does_not_pollute_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "REQUEST_INTERVAL", 0)
    ref = fetch.ReportRef(date(2026, 10, 12), "daily", "https://example.org/report.pdf", "Сводка")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"<html>error</html>"))
    ) as client:
        result = await fetch.download_reports([ref], tmp_path, client)
        assert result.issues
        assert result == []
    assert not (tmp_path / ref.filename).exists()


async def test_corrupt_cached_pdf_is_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "REQUEST_INTERVAL", 0)
    ref = fetch.ReportRef(date(2026, 10, 12), "daily", "https://example.org/report.pdf", "Сводка")
    (tmp_path / ref.filename).write_bytes(b"incomplete")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"%PDF-1.7\nvalid"))
    ) as client:
        await fetch.download_reports([ref], tmp_path, client)
    assert (tmp_path / ref.filename).read_bytes().startswith(b"%PDF")


async def test_changed_source_url_replaces_same_dated_cached_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "REQUEST_INTERVAL", 0)
    old = fetch.ReportRef(date(2026, 10, 12), "daily", "https://example.org/original.pdf", "Сводка")
    new = fetch.ReportRef(
        date(2026, 10, 12), "daily", "https://example.org/corrected.pdf", "Сводка"
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"%PDF-" + r.url.path.encode())
        )
    ) as client:
        await fetch.download_reports([old], tmp_path, client)
        result = await fetch.download_reports([new], tmp_path, client)
    assert result[0][1].read_bytes() == b"%PDF-/corrected.pdf"


async def test_broken_report_does_not_block_successful_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "REQUEST_INTERVAL", 0)
    good = fetch.ReportRef(date(2026, 10, 12), "daily", "https://example.org/good.pdf", "Сводка")
    bad = fetch.ReportRef(date(2026, 10, 11), "daily", "https://example.org/bad.pdf", "Сводка")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(404)
                if "bad" in r.url.path
                else httpx.Response(200, content=b"%PDF-good")
            )
        )
    ) as client:
        result = await fetch.download_reports([good, bad], tmp_path, client)
    assert len(result) == 1
    assert result.issues and "bad.pdf" in result.issues[0]
