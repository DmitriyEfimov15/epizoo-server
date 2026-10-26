from app.services.summary.base import SummaryProvider, summarize_with_fallback
from app.services.summary.template import TemplateSummaryProvider
from app.services.summary.yandex import YandexSummaryProvider

__all__ = [
    "SummaryProvider",
    "TemplateSummaryProvider",
    "YandexSummaryProvider",
    "summarize_with_fallback",
    "make_provider",
]


def make_provider(provider: str, **kwargs: object) -> SummaryProvider:
    if provider == "template":
        return TemplateSummaryProvider()
    if provider == "yandex":
        return YandexSummaryProvider(**kwargs)
    raise ValueError(f"Неизвестный провайдер сводок: {provider}")
