import hashlib
import json

from sqlalchemy.exc import IntegrityError

from app.models import Summary
from app.schemas.api import SummaryOut
from app.services.summary import make_provider, summarize_with_fallback


async def region_summary(session, monitor, code, species, period, settings, provider=None):
    monitor.region(code)
    region = monitor.region_out(code, species, period=period)
    texts = [e.text for e in region.events]
    dates = {e.id: e.date for e in region.events}
    news = [
        n
        for n in monitor.news
        if n.region_code == code
        and (monitor.today - n.date).days < period
        and n.date <= monitor.today
        and (not species or n.disease_id and species in monitor.diseases[n.disease_id].species)
    ]
    titles = [n.title for n in sorted(news, key=lambda n: (n.date, n.id))]
    urls = sorted({url for e in region.events for url in e.source_urls} | {n.url for n in news})
    raw = json.dumps(
        {
            "code": code,
            "species": species,
            "period": period,
            "texts": texts,
            "dates": dates,
            "news": titles,
            "urls": urls,
            "provider": settings.summary_provider,
            "model": settings.yandex_model if settings.summary_provider == "yandex" else None,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    key = hashlib.sha256(raw.encode()).hexdigest()
    cached = await session.get(Summary, key)
    if cached is None:
        provider = provider or configured_provider(settings)
        text, name = await summarize_with_fallback(
            provider, texts, titles, timeout=settings.summary_timeout
        )
        cached = Summary(key=key, text=text, provider=name)
        try:
            async with session.begin_nested():
                session.add(cached)
                await session.flush()
        except IntegrityError:
            cached = await session.get(Summary, key)
    return SummaryOut(
        text=cached.text, provider=cached.provider, source_urls=urls, created_at=cached.created_at
    )


def configured_provider(settings):
    kwargs = {"timeout": settings.summary_timeout}
    if settings.summary_provider == "yandex":
        kwargs.update(
            api_key=settings.yandex_api_key,
            folder_id=settings.yandex_folder_id,
            model=settings.yandex_model,
        )
    return make_provider(settings.summary_provider, **kwargs)
