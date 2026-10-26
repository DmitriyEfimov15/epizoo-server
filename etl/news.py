import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.time import today_moscow
from app.models import News
from etl.fetch import make_client
from etl.load import lookup_tables, name_key

FEED_URL = "https://fsvps.gov.ru/feed/"


def parse_feed(xml: str):
    root = ET.fromstring(xml)
    items = []
    seen = set()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or urlparse(url).scheme not in ("http", "https") or url in seen:
            continue
        published = item.findtext("pubDate")
        try:
            when = parsedate_to_datetime(published).date() if published else today_moscow()
        except (ValueError, TypeError):
            when = today_moscow()
        items.append({"title": title, "url": url, "date": when})
        seen.add(url)
    return items


async def load_news(session):
    async with make_client() as client:
        response = await client.get(FEED_URL)
        response.raise_for_status()
    regions, diseases = await lookup_tables(session)
    known = set((await session.scalars(select(News.url))).all())
    count = 0
    for item in parse_feed(response.text):
        if item["url"] in known:
            continue
        title = name_key(item["title"])
        # Не присваиваем регион по неоднозначному совпадению нескольких названий.
        region_matches = {
            value.code for key, value in regions.items() if len(key) >= 5 and key in title
        }
        disease_matches = {
            value.id for key, value in diseases.items() if len(key) >= 5 and key in title
        }
        session.add(
            News(
                **item,
                region_code=next(iter(region_matches)) if len(region_matches) == 1 else None,
                disease_id=next(iter(disease_matches)) if len(disease_matches) == 1 else None,
            )
        )
        known.add(item["url"])
        count += 1
    await session.flush()
    return count
