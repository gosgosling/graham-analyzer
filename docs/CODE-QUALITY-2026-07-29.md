# Метрики качества кода

| Метрика | Значение | Порог |  |
| --- | --- | --- | --- |
| Строк Python / TypeScript | 21724 / 13117 | — | — |
| Файлов длиннее порога | 16 | ≤ 500 строк | ⚠️ |
| Функций длиннее порога | 69 | ≤ 60 строк | ⚠️ |
| Функций сложнее порога | 74 | ≤ 12 ветвлений | ⚠️ |
| Дублирующихся блоков | 57 | ≥ 6 строк подряд | ⚠️ |
| Тестов / assert'ов | 161 / 366 | — | — |
| Assert на тест | 2.3 | ≥ 1.5 | ✅ |
| Покрытие расчётного слоя | 86% | ≥ 90% | ⚠️ |
| Покрытие backend целиком | 34% | ≥ 60% | ⚠️ |
| Доля строк-комментариев | 15% | 10–25% | — |
| `# type: ignore` / `any` | 161 / 29 | — | — |

## Файлы, которые не помещаются в голову

| Файл | Строк |
| --- | --- |
| `frontend/src/components/MultipliersPanel.tsx` | 2112 |
| `frontend/src/components/ReportForm.tsx` | 1991 |
| `backend/app/services/report_parser/extractor_service.py` | 1551 |
| `frontend/src/pages/CompanyDetail.tsx` | 1424 |
| `frontend/src/components/AiParsePdfModal.tsx` | 1207 |
| `frontend/src/pages/CompanyReportsMatrix.tsx` | 1125 |
| `backend/app/services/analysis/multiplier_service.py` | 822 |
| `frontend/src/pages/CompaniesList.tsx` | 799 |
| `backend/app/schemas.py` | 745 |
| `backend/app/utils/moex_client.py` | 671 |
| `backend/app/services/analysis/sector_profiles.py` | 605 |
| `backend/app/services/report_parser/pdf_extractor.py` | 600 |
| `backend/app/services/report_parser/schemas.py` | 590 |
| `backend/app/routers/reports_router.py` | 585 |
| `backend/app/services/report_parser/prompts.py` | 523 |

## Длинные функции

| Место | Функция | Строк | Ветвлений |
| --- | --- | --- | --- |
| `frontend/src/pages/CompanyDetail.tsx:31` | CompanyDetail | 849 | 118 |
| `frontend/src/pages/CompanyReportsMatrix.tsx:335` | CompanyReportsMatrix | 624 | 94 |
| `frontend/src/pages/CompaniesList.tsx:22` | CompaniesList | 409 | 76 |
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
| `backend/app/routers/reports_router.py:236` | parse_pdf_endpoint | 150 | 24 |

## Ветвистые функции

| Место | Функция | Ветвлений | Строк |
| --- | --- | --- | --- |
| `frontend/src/pages/CompanyDetail.tsx:31` | CompanyDetail | 118 | 849 |
| `frontend/src/pages/CompanyReportsMatrix.tsx:335` | CompanyReportsMatrix | 94 | 624 |
| `frontend/src/pages/CompaniesList.tsx:22` | CompaniesList | 76 | 409 |
| `backend/app/services/analysis/calc_multipliers.py:23` | calculate_multipliers | 62 | 240 |
| `backend/app/utils/tinkoff_client.py:196` | get_tinkoff_companies | 61 | 171 |
| `frontend/src/pages/MassParse.tsx:41` | MassParse | 56 | 403 |
| `scripts/compare_apis.py:90` | get_tinkoff_companies | 53 | 142 |
| `frontend/src/components/MultipliersPanel.tsx:1817` | MultipliersPanel | 52 | 294 |
| `backend/app/services/report_parser/extractor_service.py:593` | _collect_sanity_warnings | 41 | 167 |
| `frontend/src/pages/DisclosureCoverage.tsx:31` | DisclosureCoverage | 40 | 300 |
| `backend/app/services/report_parser/extractor_service.py:1295` | _compute_generic_status | 33 | 55 |
| `tools/edisclosure-scraper/main.py:130` | main | 33 | 145 |
| `backend/scripts/run_live_extraction_quality.py:45` | main | 31 | 156 |
| `scripts/code_quality.py:344` | build_report | 31 | 125 |
| `backend/app/services/bonds/bond_service.py:60` | _instrument_to_bond | 30 | 52 |

## Дублирование

Одинаковые куски кода в разных местах:

- 51 строк × 2: `tools/copy_bane_reports_to_banep.py:39`, `tools/copy_reports_to_preferred.py:37`
- 32 строк × 2: `tools/copy_bane_reports_to_banep.py:139`, `tools/copy_reports_to_preferred.py:207`
- 31 строк × 2: `backend/app/routers/reports_router.py:304`, `backend/app/routers/reports_router.py:493`
- 22 строк × 2: `backend/app/schemas.py:162`, `backend/app/schemas.py:273`
- 22 строк × 2: `frontend/src/utils/histTableYoY.ts:218`, `frontend/src/utils/histTableYoY.ts:244`
- 19 строк × 2: `tools/copy_bane_reports_to_banep.py:105`, `tools/copy_reports_to_preferred.py:99`
- 18 строк × 2: `backend/app/schemas.py:192`, `backend/app/schemas.py:302`
- 16 строк × 2: `backend/app/routers/reports_router.py:267`, `backend/app/routers/reports_router.py:458`
- 15 строк × 2: `backend/app/schemas.py:616`, `backend/app/schemas.py:675`
- 15 строк × 2: `frontend/src/components/ReportForm.tsx:555`, `frontend/src/pages/CompanyReportsMatrix.tsx:173`

## Сервисы, где тесты не выполнили ни строки

Не «мало покрытия», а ноль: поведение этих модулей ничем не зафиксировано.

- `app/services/admin/backup_service.py`
- `app/services/bonds/bond_service.py`
- `app/services/companies/sync_service.py`
- `app/services/disclosure/calendar.py`
- `app/services/disclosure/edisclosure_client.py`
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

