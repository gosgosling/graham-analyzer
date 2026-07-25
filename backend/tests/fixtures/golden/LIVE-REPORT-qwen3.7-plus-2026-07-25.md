# Live extraction: qwen3.7-plus (2026-07-25)

- **Model:** `qwen3.7-plus` (text + vision в одном запросе)
- **Endpoint:** `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- **PDF:** `/tmp/golden_pdfs` (LKOH 2021/2023/2024, NVTK 2023/2024/2025)
- **Результат:** 6/6 ok, **mean score 71.4%**, min 63.2%

## Сравнение с предыдущим прогоном max

| Модель | mean | min | комментарий |
|--------|------|-----|-------------|
| qwen3.7-max (+ vl-plus на сканы) | ~65% | — | гибрид text/vision |
| **qwen3.7-plus** | **71%** | 63% | один multimodal model |

## По кейсам

| Кейс | score | заметки |
|------|-------|---------|
| LKOH 2023 | 79% | DPS mismatch (год отнесения) |
| LKOH 2021 | 79% | hybrid PNG; DPS / shares |
| NVTK 2025 | 74% | DPS missing_ai — ожидаемо для свежего года |
| NVTK 2023 | 71% | DPS missing; dividends_paid / capex |
| LKOH 2024 | 63% | revenue/NI/cash/D&A mismatch; DPS missing |
| NVTK 2024 | 63% | shares missing; NI / paid / capex |

## Дивиденды (ожидаемое поведение)

Правила в промпте/схеме:
- суммировать промежуточные + финальные **за отчётный год**;
- не путать год выплаты и год отнесения;
- в самом свежем отчёте полный DPS часто `null` → `missing_ai` — нормально.

В этом прогоне `dividends_per_share:missing_ai` на LKOH 2024, NVTK 2025/2024/2023 — согласуется с тем, что полный итог за год часто не в том же PDF.

## Вывод

Plus на intl endpoint стабилен (vision OK на балансе НОВАТЭКа), mean выше max. Для массового прогона (~1.3k PDF) plus — разумный выбор до оплаты.
