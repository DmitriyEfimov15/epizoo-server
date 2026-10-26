import httpx

from app.services.summary.base import (
    SYSTEM_PROMPT,
    bounded_facts,
    facts_message,
    http_client,
    validate_summary,
)
from app.services.summary.template import TemplateSummaryProvider


class YandexSummaryProvider:
    name = "yandex"
    endpoint = "https://ai.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "yandexgpt-5-lite",
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.model = model
        self.timeout = timeout
        self.client = client

    async def summarize(self, texts: list[str], news_titles: list[str]) -> str:
        facts = bounded_facts(texts, news_titles)
        if not any(facts.values()):
            return await TemplateSummaryProvider().summarize([], [])
        model_uri = self.model
        if not model_uri.startswith("gpt://"):
            model_uri = f"gpt://{self.folder_id}/{model_uri}"
            if self.model in {"yandexgpt", "yandexgpt-lite"}:
                model_uri += "/latest"
        async with http_client(self.client, self.timeout) as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Api-Key {self.api_key}",
                    "x-folder-id": self.folder_id,
                },
                json={
                    "modelUri": model_uri,
                    "completionOptions": {"stream": False, "temperature": 0, "maxTokens": "500"},
                    "messages": [
                        {"role": "system", "text": SYSTEM_PROMPT},
                        {"role": "user", "text": facts_message(facts)},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result", data)
            return validate_summary(result["alternatives"][0]["message"]["text"])
