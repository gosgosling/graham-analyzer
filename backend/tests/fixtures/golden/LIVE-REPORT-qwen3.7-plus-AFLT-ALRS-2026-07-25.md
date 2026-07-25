# Live extraction: qwen3.7-plus — AFLT / ALRS (2026-07-25)

- **Model:** `qwen3.7-plus` @ dashscope-intl
- **Кейсы:** AFLT 2023–2025, ALRS 2023–2025
- **Итог (6/6 после fallback):** mean **~62%**, min 55%

| Кейс | score | заметки |
|------|-------|---------|
| AFLT 2023 | 75% | лучший; NI missing; cash/debt mismatch |
| AFLT 2025 | 62% | hybrid vision; debt/cash/lease; DPS missing |
| AFLT 2024 | 62% | revenue/NI/cash/debt |
| ALRS 2025 | 61% | битый ToUnicode → vision (первые 10 стр.) |
| ALRS 2024 | 58% | то же |
| ALRS 2023 | 55% | текст+vision; NI/cash/debt/DPS |

## Сравнение с LKOH/NVTK

| Набор | mean |
|-------|------|
| LKOH+NVTK | ~71% |
| AFLT+ALRS | ~62% |

AFLT: частые ошибки по debt/cash (лизинг авиапарка). ALRS 2024/2025: PDF с битой кодировкой — без vision-fallback прогон падал.

## Фикс по ходу

В `pdf_extractor`: если текст длинный, но почти без кириллицы → режим vision (как скан).
