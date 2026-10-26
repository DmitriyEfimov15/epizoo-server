"""Список и скачивание оперативных сводок ИАЦ Россельхознадзора."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

import httpx

INDEX_URL = (
    "https://fsvps.gov.ru/jepizooticheskaja-situacija/rossija/"
    "operativnye-informacionnye-soobshhenija/"
)
USER_AGENT = "epizoo-monitor/0.1 (student project; daily update)"  # только ASCII
REQUEST_INTERVAL = 1.0  # не чаще одного запроса в секунду

ReportKind = Literal["daily", "weekly"]

_ITEM_RE = re.compile(
    r"<li\b[^>]*>\s*<strong[^>]*>(\d{2}\.\d{2}\.\d{4})</strong>\s*<br\s*/?>\s*"
    r"<a[^>]*href=[\"']([^\"']+\.pdf(?:\?[^\"']*)?)[\"'][^>]*>(.*?)</a>",
    re.S | re.I,
)
_PERIOD_RE = re.compile(r"с\s+(\d{2}\.\d{2}\.\d{4})\s+по\s+(\d{2}\.\d{2}\.\d{4})")


@dataclass(frozen=True)
class ReportRef:
    """Ссылка на сводку со страницы-индекса."""

    published: date
    kind: ReportKind
    url: str
    title: str
    period_from: date | None = None
    period_to: date | None = None

    @property
    def filename(self) -> str:
        if self.kind == "weekly" and self.period_from and self.period_to:
            return f"weekly_{self.period_from:%Y-%m-%d}_{self.period_to:%Y-%m-%d}.pdf"
        return f"{self.kind}_{self.published:%Y-%m-%d}.pdf"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def parse_index(page: str) -> list[ReportRef]:
    """Достаёт из HTML индекса все сводки, от новых к старым."""
    refs: list[ReportRef] = []
    for published, url, raw_title in _ITEM_RE.findall(page):
        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        period = _PERIOD_RE.search(title)
        url = urljoin(INDEX_URL, html.unescape(url))
        if "сводн" in title.casefold():
            refs.append(
                ReportRef(
                    published=_parse_date(published),
                    kind="weekly",
                    url=url,
                    title=title,
                    period_from=_parse_date(period.group(1)) if period else None,
                    period_to=_parse_date(period.group(2)) if period else None,
                )
            )
        else:
            refs.append(
                ReportRef(published=_parse_date(published), kind="daily", url=url, title=title)
            )
    return refs


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def fetch_index(client: httpx.AsyncClient) -> list[ReportRef]:
    await asyncio.sleep(REQUEST_INTERVAL)
    response = await client.get(INDEX_URL)
    response.raise_for_status()
    return parse_index(response.text)


class DownloadResult(list):
    """Успешные файлы и отдельная диагностика недоступных публикаций."""

    def __init__(self):
        super().__init__()
        self.issues: list[str] = []


def atomic_write(path: Path, content: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            tmp.write(content)
            tmp.flush()
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)


async def download_reports(refs, cache_dir: Path, client: httpx.AsyncClient, *, refresh=False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = DownloadResult()
    semaphore = asyncio.Semaphore(3)
    gate = asyncio.Lock()
    last_request = time.monotonic()

    async def get(ref):
        nonlocal last_request
        target = cache_dir / ref.filename
        meta_path = target.with_suffix(".pdf.meta.json")
        valid = target.exists() and target.read_bytes().startswith(b"%PDF")
        try:
            metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        except (ValueError, OSError):
            metadata = {}
        if valid and not refresh and metadata.get("url", ref.url) == ref.url:
            if not metadata:
                atomic_write(meta_path, json.dumps({"url": ref.url, "legacy": True}).encode())
            return ref, target
        headers = {}
        if valid and metadata.get("url") == ref.url:
            if metadata.get("etag"):
                headers["If-None-Match"] = metadata["etag"]
            if metadata.get("last_modified"):
                headers["If-Modified-Since"] = metadata["last_modified"]
        try:
            async with semaphore:
                async with gate:
                    await asyncio.sleep(max(0, last_request + REQUEST_INTERVAL - time.monotonic()))
                    last_request = time.monotonic()
                response = await client.get(ref.url, headers=headers)
            if response.status_code == 304 and valid:
                return ref, target
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("Источник вернул не PDF")
            digest = hashlib.sha256(response.content).hexdigest()
            blobs = cache_dir / "blobs"
            blobs.mkdir(exist_ok=True)
            blob = blobs / f"{digest}.pdf"
            if not blob.exists():
                atomic_write(blob, response.content)
            atomic_write(target, response.content)
            atomic_write(
                meta_path,
                json.dumps(
                    {
                        "url": ref.url,
                        "sha256": digest,
                        "etag": response.headers.get("etag"),
                        "last_modified": response.headers.get("last-modified"),
                    }
                ).encode(),
            )
            return ref, target
        except (httpx.HTTPError, ValueError, OSError) as error:
            result.issues.append(f"{ref.url}: ошибка {type(error).__name__}")
            return None

    # В индексе более новая версия одной публикации идёт первой.
    unique = {}
    for ref in refs:
        unique.setdefault(ref.filename, ref)
    downloaded = await asyncio.gather(*(get(ref) for ref in unique.values()))
    result.extend(pair for pair in downloaded if pair is not None)
    return result


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(180.0, connect=30.0),
        follow_redirects=True,
    )


async def fetch_since(
    since: date, cache_dir: Path, *, refresh=True
) -> list[tuple[ReportRef, Path]]:
    """Скачивает все сводки, опубликованные начиная с даты `since`."""
    async with make_client() as client:
        refs = [ref for ref in await fetch_index(client) if ref.published >= since]
        return await download_reports(refs, cache_dir, client, refresh=refresh)
