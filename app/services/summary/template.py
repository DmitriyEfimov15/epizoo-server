"""Детерминированная сводка из цитат без новых медицинских рекомендаций."""

from app.services.summary.base import bounded_facts


class TemplateSummaryProvider:
    name = "template"

    async def summarize(self, texts: list[str], news_titles: list[str]) -> str:
        facts = bounded_facts(texts, news_titles)
        events = facts["texts"]
        news = facts["news_titles"]
        if not events and not news:
            return "За выбранный период сообщений нет. Заголовки новостей не переданы."

        def quote(value: str) -> str:
            # Берём только первое предложение источника, длинные цитаты явно сокращаем.
            first = value.split(". ", 1)[0].rstrip(".!?…")
            excerpt = first[:300].rstrip()
            if len(first) > 300:
                excerpt += "…"
            return f"«{excerpt}»"

        if events:
            sentences = ["В сводке приведены выдержки из переданных сообщений."]
            sentences.append(f"Из сообщения: {quote(events[0])}.")
            if news:
                sentences.append(f"Из заголовков новостей: {quote(news[0])}.")
            elif len(events) > 1:
                sentences.append(f"Из другого сообщения: {quote(events[1])}.")
            return " ".join(sentences)
        return f"В сводке приведены переданные заголовки новостей. Из заголовков: {quote(news[0])}."
