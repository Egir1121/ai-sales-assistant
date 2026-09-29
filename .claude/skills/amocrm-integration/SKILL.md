---
name: amocrm-integration
description: Проверенные факты об API amoCRM (формат вебхуков входящих и исходящих сообщений, таймауты, повторы, добавление примечаний в сделку). Использовать при любой работе с app/integrations/amocrm, вебхуком /webhooks/amocrm и их фикстурами.
paths: app/integrations/amocrm/**, tests/fixtures/amocrm/**
---

# amoCRM: что точно известно

Сверено с официальной документацией (сентябрь 2026). Если нужно поле, которого здесь нет, — не придумывай: открой документацию и допиши сюда источник.

- Вебхуки: https://www.amocrm.ru/developers/content/crm_platform/webhooks-format
- Примечания: https://www.amocrm.ru/developers/content/crm_platform/events-and-notes

## Вебхуки

- Настраиваются в разделе «амоМаркет» → WEB HOOKS. Работа с вебхуками через API — с расширенного тарифа и выше.
- Тело — `x-www-form-urlencoded`, структура вида `{entity: {action: {0: {...поля...}}}}`. Парсить через разбор вложенных ключей формы (`message[add][0][text]`), а не как JSON.
- **Входящее сообщение** — ключ `message[add]`. Поля элемента: `id`, `chat_id`, `talk_id`, `contact_id`, `text`, `created_at`, `message_type`, `origin` (канал, например `telegram`), `author{id,type,name,avatar_url}`, `attachment{type,link,file_name}`, `element_id`, `element_type` (сделка — `element_type=2`, `element_id` = id сделки; перепроверь на реальном payload).
- **Исходящее сообщение** (от менеджера или Salesbot) — ключ `outgoing_message[add]`. Поля: те же плюс `type: outgoing`, `author{user_id,type:internal,...}`, `recipient{...}`. Именно так сервис видит «работу менеджера в диалоговом окне» и собирает историю.
- **Таймаут: amoCRM ждёт ответ не более 2 секунд.** Любой код вне 100–299 или таймаут = недоставка.
- Повторы при недоставке: через 5 мин, 15 мин, 15 мин, 1 час (зависит от кода ответа).
- **Хук отключается,** если за 2 часа было более 100 невалидных ответов и последний тоже невалидный.

## Следствия для реализации

1. Эндпоинт вебхука только валидирует и кладёт событие в фоновую обработку (`BackgroundTasks` или очередь), отвечает `200` сразу. Генерация LLM — никогда не в синхронном пути.
2. Идемпотентность по `message.id`: повтор той же доставки не создаёт второе примечание.
3. Сообщения без текста (картинка, стикер) не отправляем в LLM; фиксируем в истории как `[вложение: <type>]`.
4. Ошибки обработки логируем, но на сам вебхук всё равно отвечаем `200`, чтобы amoCRM не отключил хук.

## Запись результата в сделку

- `POST /api/v4/leads/{lead_id}/notes`, `Content-Type: application/json`, тело — массив объектов.
- Текстовое примечание: `{"note_type": "common", "params": {"text": "..."}}`.
- Для интеграций подходит также `service_message` / `extended_service_message` (`params: {service, text}`; `extended_` поддерживает больше текста и сворачивается в интерфейсе) — выбор зафиксируй в ADR.
- Авторизация — OAuth 2.0 (для теста достаточно долгосрочного токена из настроек интеграции): заголовок `Authorization: Bearer <token>`, базовый URL `https://{subdomain}.amocrm.ru`.
- Формат примечания: сначала «💡 Подсказка», затем «✉️ Черновик ответа», в конце версия промпта и request_id.

## Тесты

- Фикстуры в `tests/fixtures/amocrm/` — копии примеров payload из документации (входящее, исходящее, с вложением), сохранённые как form-urlencoded строки.
- Тесты: парсинг каждой фикстуры; ответ вебхука < 2 с даже при «медленном» FakeLLM (sleep 5 с); идемпотентность; в mock-режиме примечание уходит в лог/UI, а не в сеть.

## Сверено с документацией 2026-09-29 (M5)

Источник: https://www.amocrm.ru/developers/content/crm_platform/webhooks-format и
https://www.amocrm.ru/developers/content/crm_platform/events-and-notes.

- «WebHook отправляется в формате x-www-form-urlencoded» — подтверждено. Примеры payload на странице
  показаны как JSON-структура; в `tests/fixtures/amocrm/` они сохранены в form-urlencoded без изменений.
- В примере входящего сообщения `element_type: "1"`, `element_id: "123456789"`. Коды `element_type`
  на странице вебхуков **не расшифрованы**. В проекте принято 1 — контакт, 2 — сделка (коды amoCRM);
  примечание пишется в `contacts/{id}` или `leads/{id}`. Проверить на реальном аккаунте.
- Поля входящего: `id, chat_id, talk_id, contact_id, author{id,type,name,avatar_url}, text, created_at,
  message_type, origin, attachment{type,link,file_name}, element_id, element_type` — совпадает с описанием выше.
- Исходящее дополнительно: `type: outgoing`, `author{..., user_id}`, `recipient{id,type,name,avatar_url}`.
- Повторы: 2-я попытка через 5 мин и 3-я через 15 мин (для кодов 0–99, 300+); 4-я через 15 мин
  и 5-я через 1 ч (для 499, 500–599).
- Примечания: `POST /api/v4/{entity_type}/{entity_id}/notes`, entity_type — leads, contacts, companies,
  customers; успех — 200 и `_embedded.notes[].id`. Лимиты на размер текста в документации не указаны.
