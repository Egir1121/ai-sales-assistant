"""Anthropic-провайдер (ADR-003): один вызов, structured output по схеме `LLMOutput`.

- Системный промпт + блок БЗ с `cache_control` — стабильный префикс, кэшируется.
- `output_config.format` (JSON Schema) вместо принудительного tool_choice: у Opus 5.5 / Sonnet 5.5
  принудительный tool_choice возвращает 400 (допущение A7).
- temperature — только моделям, которые её принимают, через extra_body: в SDK 1.x параметр убран
  из сигнатур, а Opus 4.7+ отвечает на него 400 (A8). effort — только моделям, которые его знают.
- Серверный fallback при refusal (`fallbacks: "default"`) — где модель его поддерживает (A20).
- Ретраи SDK выключены: общий дедлайн задаёт пайплайн. Сами повторяем 1 раз, если ответ не прошёл
  валидацию Pydantic.
"""

import logging
from typing import Any

import anthropic
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from pydantic import ValidationError

from app.llm.base import LLMError, LLMRequest, LLMResult
from app.llm.schema import LLMOutput

logger = logging.getLogger(__name__)

OUTPUT_SCHEMA: dict[str, Any] = anthropic.transform_schema(LLMOutput)

# Модели, которые ещё принимают temperature. В SDK 1.x параметр убран из сигнатур → extra_body.
_SAMPLING_MODELS = (
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
)
_NO_EFFORT_MODELS = ("claude-haiku-4-5", "claude-sonnet-4-5")
_SERVER_FALLBACK_MODELS = (
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-fable-5-1",
)
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# $ за 1M токенов: (input, output, cache read). Запись в кэш (5 мин) — 1.25 × input.
_PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}


def _matches(model: str, prefixes: tuple[str, ...]) -> bool:
    return model.startswith(prefixes)


class AnthropicLLMClient:
    provider = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        timeout_s: float,
        effort: str = "low",
        max_tokens: int = 8000,
        max_attempts: int = 2,
        http_client: DefaultAsyncHttpxClient | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._effort = effort
        self._max_tokens = max_tokens
        self._max_attempts = max_attempts
        self._client = AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=0, http_client=http_client
        )

    async def generate(self, request: LLMRequest) -> LLMResult:
        try:
            return await self._generate(request)
        except LLMError:
            raise
        except Exception as exc:  # неожиданная форма ответа SDK/API — тоже повод для фолбэка
            raise LLMError(f"неожиданная ошибка при вызове Anthropic: {exc!r}") from exc

    async def _generate(self, request: LLMRequest) -> LLMResult:
        usage = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
        problem = ""
        for attempt in range(1, self._max_attempts + 1):
            response = await self._call(request)
            usage["in"] += response.usage.input_tokens
            usage["out"] += response.usage.output_tokens
            usage["cache_read"] += response.usage.cache_read_input_tokens or 0
            usage["cache_write"] += response.usage.cache_creation_input_tokens or 0

            if response.stop_reason == "refusal":
                category = response.stop_details.category if response.stop_details else None
                raise LLMError(f"модель отказалась отвечать (refusal: {category})")
            if response.stop_reason == "max_tokens":
                raise LLMError("ответ обрезан по max_tokens")

            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                output = LLMOutput.model_validate_json(text)
            except ValidationError as exc:
                problem = f"{exc.error_count()} ошибок схемы"
                logger.warning("LLM вернул невалидный ответ (попытка %d): %s", attempt, problem)
                continue
            return LLMResult(
                output=output,
                provider=self.provider,
                model=response.model,
                tokens_in=usage["in"] + usage["cache_read"] + usage["cache_write"],
                tokens_out=usage["out"],
                cost_usd=self._cost(usage),
            )
        raise LLMError(f"невалидный ответ LLM после {self._max_attempts} попыток: {problem}")

    async def _call(self, request: LLMRequest) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": [{"type": "text", "text": request.system}],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": request.kb_block,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": request.dynamic_block},
                    ],
                }
            ],
            "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        }
        if not _matches(self.model, _NO_EFFORT_MODELS):
            params["output_config"]["effort"] = self._effort
        if _matches(self.model, _SAMPLING_MODELS):
            params["extra_body"] = {"temperature": self._temperature}
        try:
            if _matches(self.model, _SERVER_FALLBACK_MODELS):
                return await self._client.beta.messages.create(
                    **params, betas=[_FALLBACK_BETA], fallbacks="default"
                )
            return await self._client.messages.create(**params)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"ошибка API Anthropic {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:  # включает APITimeoutError
            raise LLMError(f"нет связи с API Anthropic: {exc}") from exc
        except anthropic.AnthropicError as exc:  # прочие ошибки SDK (например, разбор ответа)
            raise LLMError(f"ошибка SDK Anthropic: {exc}") from exc

    def _cost(self, usage: dict[str, int]) -> float | None:
        prices = next((p for m, p in _PRICES.items() if self.model.startswith(m)), None)
        if prices is None:
            return None
        price_in, price_out, price_cache_read = prices
        total = (
            usage["in"] * price_in
            + usage["cache_write"] * price_in * 1.25
            + usage["cache_read"] * price_cache_read
            + usage["out"] * price_out
        )
        return round(total / 1_000_000, 6)
