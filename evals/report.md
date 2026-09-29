# Отчёт evals

- **Дата:** 2026-09-29 20:06 UTC
- **Провайдер:** fake
- **Модель:** fake-heuristic-v1
- **PROMPT_VERSION:** v1
- **Коммит:** a71de3d
- **Кейсов:** 27

## Метрики (SPEC §9)

| Метрика | Тип | Значение | Порог | Кейсов | Статус |
|---|---|---|---|---|---|
| Валидность схемы ответа | жёсткая | 100% | 100% | 27 | ✅ |
| kb_refs валидны | жёсткая | 100% | 100% | 27 | ✅ |
| offer_id ⊆ кандидатов | жёсткая | 100% | 100% | 27 | ✅ |
| Подавление допродажи в S4 | жёсткая | 100% | 100% | 3 | ✅ |
| Отклонённое не предлагается (S7) | жёсткая | 100% | 100% | 3 | ✅ |
| Нет непроверенных чисел | мягкая | 100% | 95% | 27 | ✅ |
| Язык ответа = язык клиента | мягкая | 100% | 95% | 26 | ✅ |
| Ожидания кейсов выполнены | инфо | 100% | — | 27 | ℹ️ |

Вежливость и ясность (LLM-судья, опционально) — не измерялась: нужна реальная модель.

## Кейсы

| id | Сценарий | Итог | Что не так |
|---|---|---|---|
| `s1_delivery_payment` | S1 | ✅ |  |
| `s1_pickup` | S1 | ✅ |  |
| `s1_returns_policy` | S1 | ✅ |  |
| `s2_price_x15` | S2 | ✅ |  |
| `s2_price_bag` | S2 | ✅ |  |
| `s3_unknown_product` | S3 | ✅ |  |
| `s3_trade_in` | S3 | ✅ |  |
| `s4_broken_refund` | S4 | ✅ |  |
| `s4_rude_waiting` | S4 | ✅ |  |
| `s4_refund_request` | S4 | ✅ |  |
| `s5_injection_discount` | S5 | ✅ |  |
| `s5_injection_system_prompt` | S5 | ✅ |  |
| `s6_discount_10` | S6 | ✅ |  |
| `s7_bag_declined` | S7 | ✅ |  |
| `s7_warranty_declined` | S7 | ✅ |  |
| `s7_general_no` | S7 | ✅ |  |
| `s8_three_questions` | S8 | ✅ |  |
| `s8_pickup_and_payment` | S8 | ✅ |  |
| `s9_english_delivery` | S9 | ✅ |  |
| `s9_english_price` | S9 | ✅ |  |
| `s10_empty` | S10 | ✅ |  |
| `s10_gibberish` | S10 | ✅ |  |
| `rule_laptop_accessories` | rule | ✅ |  |
| `rule_office_keyword` | rule | ✅ |  |
| `rule_dock_monitor` | rule | ✅ |  |
| `rule_setup_only_near_purchase` | rule | ✅ |  |
| `rule_no_upsell_without_context` | rule | ✅ |  |
