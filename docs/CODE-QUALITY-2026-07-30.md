# Метрики качества кода

| Метрика | Значение | Порог |  |
| --- | --- | --- | --- |
| Строк Python / TypeScript | 21677 / 13388 | — | — |
| Файлов длиннее порога | 15 | ≤ 500 строк | ⚠️ |
| Функций длиннее порога | 69 | ≤ 60 строк | ⚠️ |
| Функций сложнее порога | 73 | ≤ 12 ветвлений | ⚠️ |
| Дублирующихся блоков | 48 | ≥ 6 строк подряд | ⚠️ |
| Нарушений расслоения | 0 | 0 | ✅ |
| Тестов / assert'ов | 176 / 391 | — | — |
| Assert на тест | 2.2 | ≥ 1.5 | ✅ |
| Покрытие расчётного слоя | 86% | ≥ 90% | ⚠️ |
| Покрытие backend целиком | 35% | ≥ 60% | ⚠️ |
| Доля строк-комментариев | 16% | 10–25% | — |
| `# type: ignore` / `any` | 161 / 29 | — | — |

## Файлы, которые не помещаются в голову

| Файл | Строк |
| --- | --- |
| `frontend/src/components/MultipliersPanel.tsx` | 2112 |
| `frontend/src/components/ReportForm.tsx` | 1952 |
| `backend/app/services/report_parser/extractor_service.py` | 1551 |
| `frontend/src/pages/CompanyDetail.tsx` | 1412 |
| `frontend/src/components/AiParsePdfModal.tsx` | 1199 |
| `frontend/src/pages/CompanyReportsMatrix.tsx` | 1081 |
| `backend/app/services/analysis/multiplier_service.py` | 822 |
| `frontend/src/pages/CompaniesList.tsx` | 794 |
| `backend/app/utils/moex_client.py` | 695 |
| `backend/app/services/analysis/sector_profiles.py` | 605 |
| `backend/app/services/report_parser/pdf_extractor.py` | 600 |
| `backend/app/services/report_parser/schemas.py` | 590 |
| `scripts/code_quality.py` | 579 |
| `backend/app/services/report_parser/prompts.py` | 523 |
| `backend/app/routers/reports_router.py` | 509 |

## Длинные функции

| Место | Функция | Строк | Ветвлений |
| --- | --- | --- | --- |
| `frontend/src/pages/CompanyDetail.tsx:32` | CompanyDetail | 843 | 114 |
| `frontend/src/pages/CompanyReportsMatrix.tsx:291` | CompanyReportsMatrix | 624 | 94 |
| `frontend/src/pages/CompaniesList.tsx:23` | CompaniesList | 409 | 76 |
| `frontend/src/pages/MassParse.tsx:41` | MassParse | 403 | 56 |
| `backend/app/services/report_parser/extractor_service.py:920` | parse_pdf_to_report | 325 | 26 |
| `frontend/src/pages/DisclosureCoverage.tsx:31` | DisclosureCoverage | 300 | 40 |
| `frontend/src/components/MultipliersPanel.tsx:1817` | MultipliersPanel | 294 | 52 |
| `backend/app/services/analysis/calc_multipliers.py:23` | calculate_multipliers | 240 | 62 |
| `backend/app/services/mass_parse/worker.py:168` | _process_one_item | 194 | 25 |
| `backend/app/services/report_parser/pdf_extractor.py:297` | extract_financial_pages | 186 | 24 |
| `backend/app/utils/tinkoff_client.py:196` | get_tinkoff_companies | 171 | 61 |
| `backend/app/services/report_parser/extractor_service.py:593` | _collect_sanity_warnings | 167 | 41 |
| `backend/scripts/run_live_extraction_quality.py:45` | main | 156 | 31 |
| `frontend/src/pages/BondsList.tsx:96` | BondsList | 154 | 21 |
| `tools/edisclosure-scraper/main.py:130` | main | 145 | 33 |

## Ветвистые функции

| Место | Функция | Ветвлений | Строк |
| --- | --- | --- | --- |
| `frontend/src/pages/CompanyDetail.tsx:32` | CompanyDetail | 114 | 843 |
| `frontend/src/pages/CompanyReportsMatrix.tsx:291` | CompanyReportsMatrix | 94 | 624 |
| `frontend/src/pages/CompaniesList.tsx:23` | CompaniesList | 76 | 409 |
| `backend/app/services/analysis/calc_multipliers.py:23` | calculate_multipliers | 62 | 240 |
| `backend/app/utils/tinkoff_client.py:196` | get_tinkoff_companies | 61 | 171 |
| `frontend/src/pages/MassParse.tsx:41` | MassParse | 56 | 403 |
| `scripts/compare_apis.py:90` | get_tinkoff_companies | 53 | 142 |
| `frontend/src/components/MultipliersPanel.tsx:1817` | MultipliersPanel | 52 | 294 |
| `backend/app/services/report_parser/extractor_service.py:593` | _collect_sanity_warnings | 41 | 167 |
| `frontend/src/pages/DisclosureCoverage.tsx:31` | DisclosureCoverage | 40 | 300 |
| `backend/app/services/report_parser/extractor_service.py:1295` | _compute_generic_status | 33 | 55 |
| `scripts/code_quality.py:399` | build_report | 33 | 142 |
| `tools/edisclosure-scraper/main.py:130` | main | 33 | 145 |
| `backend/scripts/run_live_extraction_quality.py:45` | main | 31 | 156 |
| `backend/app/services/bonds/bond_service.py:60` | _instrument_to_bond | 30 | 52 |

## Дублирование

Одинаковые куски кода в разных местах:

- 22 строк × 2: `frontend/src/utils/histTableYoY.ts:218`, `frontend/src/utils/histTableYoY.ts:244`
- 16 строк × 2: `backend/app/routers/reports_router.py:262`, `backend/app/routers/reports_router.py:416`
- 15 строк × 2: `backend/app/schemas/multiplier.py:74`, `backend/app/schemas/multiplier.py:133`
- 14 строк × 2: `backend/app/services/report_parser/extractor_service.py:1009`, `backend/app/services/report_parser/extractor_service.py:1468`
- 13 строк × 2: `backend/app/utils/tinkoff_client.py:260`, `scripts/compare_apis.py:123`
- 12 строк × 2: `backend/app/utils/tinkoff_client.py:227`, `scripts/compare_apis.py:102`
- 12 строк × 2: `tools/edisclosure-scraper/db_client.py:34`, `tools/edisclosure-scraper/db_client.py:78`
- 11 строк × 2: `backend/app/services/disclosure/parse_queue.py:118`, `backend/app/services/disclosure/parse_queue.py:137`
- 11 строк × 2: `backend/app/utils/moex_client.py:289`, `backend/app/utils/moex_client.py:445`
- 10 строк × 2: `backend/app/services/disclosure/paths.py:14`, `tools/edisclosure-scraper/period_parse.py:20`

## Сервисы, где тесты не выполнили ни строки

Не «мало покрытия», а ноль: поведение этих модулей ничем не зафиксировано.

- `app/services/admin/backup_service.py`
- `app/services/bonds/bond_service.py`
- `app/services/companies/sync_service.py`
- `app/services/disclosure/calendar.py`
- `app/services/disclosure/parse_queue.py`
- `app/services/disclosure/paths.py`
- `app/services/disclosure/sync_service.py`
- `app/services/market/tinvest_price_service.py`
- `app/services/mass_parse/scanner.py`
- `app/services/mass_parse/service.py`
- `app/services/mass_parse/worker.py`

## Как читать

Длина и ветвистость показывают, где код правят вслепую. Дубли — где вместо
существующей функции написали новую рядом. Покрытие расчётного слоя —
единственная метрика про поведение: остальные проверяют форму, а форма у
сгенерированного кода хороша всегда, в том числе когда он считает неверно.

