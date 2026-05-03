export interface Bond {
    figi: string;
    ticker: string;
    name: string;
    isin: string;
    currency: string;
    sector: string;
    country_of_risk: string;
    country_of_risk_name: string;
    exchange: string;
    maturity_date: string | null;
    placement_date: string | null;
    nominal: number | null;
    coupon_quantity_per_year: number | null;
    floating_coupon_flag: boolean;
    perpetual_flag: boolean;
    amortization_flag: boolean;
    issue_size: number | null;
    lot: number;
}

export interface Security {
    secid: string;
    boardid: string;
    shortname: string;
    prevprice: number | null;
    lotsize: number;
    facevalue: number;
    status: string;
    boardname: string;
    decimals: number;
    secname: string;
    remarks: string | null;
    marketcode: string;
    instrid: string;    
    sectorid: string | null;
    minstep: number;
    prevwaprice: number | null;
    faceunit: string;
    prevdate: string | null; 
    issuesize: number;
    isin: string;
    latname: string;
    regnumber: string | null;
    prevlegalcloseprice: number | null;
    currencyid: string;
    sectype: string;
    listlevel: number;
    settledate: string | null;  
}

export interface Multipliers {
    company_id: number;
    pe_ratio: number;
    pb_ratio: number;
    debt_to_equity: number;
    roe: number;
    dividend_yield: number;
    date: string;
}

/** Кэшированная запись мультипликаторов из таблицы multipliers */
export interface MultiplierRecord {
    id: number;
    company_id: number;
    report_id: number | null;
    date: string;           // YYYY-MM-DD
    type: 'report_based' | 'current' | 'daily';

    // Рыночные данные
    price_used: number | null;
    shares_used: number | null;
    market_cap: number | null;

    // LTM P&L
    ltm_net_income: number | null;
    ltm_revenue: number | null;
    ltm_dividends_per_share: number | null;

    // Балансовые (в рублях)
    equity: number | null;
    total_liabilities: number | null;
    current_assets: number | null;
    current_liabilities: number | null;

    // Мультипликаторы
    pe_ratio: number | null;
    pb_ratio: number | null;
    roe: number | null;
    debt_to_equity: number | null;
    current_ratio: number | null;
    dividend_yield: number | null;
    /** Cost-to-Income ratio (%), только для банков */
    cost_to_income: number | null;

    // Денежные потоки LTM (NULL для банков)
    ltm_fcf: number | null;
    ltm_operating_cash_flow: number | null;
    /** P/FCF = Market Cap / LTM FCF, NULL для банков и FCF ≤ 0 */
    price_to_fcf: number | null;
    /** FCF/NI = LTM FCF / LTM Net Income × 100%, детектор качества прибыли */
    fcf_to_net_income: number | null;

    created_at?: string;
    updated_at?: string | null;

    /** Дата публикации отчёта (из financial_reports.filing_date) */
    filing_date?: string | null;
    /** Цена на дату публикации, в рублях (из price_at_filing) */
    price_at_filing_rub?: number | null;
}

/** Актуальные мультипликаторы, вычисленные на лету */
export interface CurrentMultipliers {
    company_id: number;
    date: string;
    current_price: number | null;
    balance_report_id: number | null;
    balance_report_date: string | null;
    ltm_source: string | null;

    ltm_net_income: number | null;
    ltm_revenue: number | null;
    ltm_dividends_per_share: number | null;

    price_used: number | null;
    shares_used: number | null;
    market_cap: number | null;

    pe_ratio: number | null;
    pb_ratio: number | null;
    roe: number | null;
    debt_to_equity: number | null;
    current_ratio: number | null;
    dividend_yield: number | null;
    cost_to_income: number | null;

    // Денежные потоки LTM (NULL для банков)
    ltm_fcf: number | null;
    ltm_operating_cash_flow: number | null;
    price_to_fcf: number | null;
    fcf_to_net_income: number | null;
}

/** GET /companies/sync/status */
export interface CompaniesSyncStatus {
    token_configured: boolean;
    companies_total: number;
    companies_with_brand_logo: number;
    companies_with_brand_color: number;
}

export interface CompaniesSyncStatistics {
    total: number;
    created: number;
    updated: number;
    errors: number;
}

/** POST /companies/sync */
export interface CompaniesSyncResponse {
    status: string;
    message: string;
    statistics: CompaniesSyncStatistics;
}

export interface Company {
    id?: number;
    figi: string;
    ticker: string;
    name: string;
    isin?: string;
    sector?: string;
    currency: string;
    lot: number;
    api_trade_available_flag: boolean;
    current_price?: number | null;
    price_updated_at?: string | null;
    /** URL логотипа с CDN Т-Банка (после синхронизации из T-Invest API) */
    brand_logo_url?: string | null;
    /** Основной цвет бренда (#RRGGBB) */
    brand_color?: string | null;
}

export interface FinancialReportCreate {
    company_id: number;
    
    // Атрибуты отчёта
    period_type: 'quarterly' | 'annual' | 'semi_annual';
    fiscal_year: number;
    fiscal_quarter?: number | null;  // 1-4 для квартальных, null для годовых
    accounting_standard: 'IFRS' | 'RAS' | 'US_GAAP' | 'UK_GAAP' | 'OTHER';
    consolidated: boolean;
    source: 'manual' | 'company_website' | 'api' | 'regulator' | 'other';
    
    // Даты
    report_date: string; // YYYY-MM-DD (дата окончания периода)
    filing_date?: string | null; // YYYY-MM-DD (дата публикации)
    
    // Рыночные данные
    price_per_share?: number | null;  // Цена на дату окончания периода (report_date) - для расчёта мультипликаторов
    price_at_filing?: number | null;  // Цена на дату публикации (filing_date) - для анализа реакции рынка
    shares_outstanding?: number | null;
    
    // Финансовые показатели
    revenue?: number | null;
    net_income?: number | null;
    /** Фактическая отчётная прибыль по раскрытию, млн (если отличается от net_income) */
    net_income_reported?: number | null;
    total_assets?: number | null;
    current_assets?: number | null;
    total_liabilities?: number | null;
    current_liabilities?: number | null;
    equity?: number | null;
    dividends_per_share?: number | null;
    dividends_paid: boolean;

    // Банковские показатели (заполняются только для банков, определяется автоматически по сектору)
    // revenue при этом = Total Operating Income (NII + комиссии + трейдинг + прочее)
    net_interest_income?: number | null;   // Чистые процентные доходы, млн
    fee_commission_income?: number | null; // Чистые комиссионные доходы, млн
    operating_expenses?: number | null;    // Операционные расходы (до резервов), млн
    provisions?: number | null;            // Резервы под обесценение кредитов, млн

    // Денежные потоки (ОДДС) — для всех типов, кроме банков (для банков оставляют null)
    /** Операционный денежный поток (CF from operations), млн валюты */
    operating_cash_flow?: number | null;
    /** CAPEX — капитальные затраты, положительное число, млн валюты */
    capex?: number | null;
    /** Амортизация и износ (D&A), млн — для сравнения с CAPEX (будущий модуль анализа) */
    depreciation_amortization?: number | null;

    // Валюта
    currency: string; // "RUB" или "USD"
    exchange_rate?: number | null; // Обязателен для USD

    // ─── AI-извлечение (передаются при PUT после парсинга или правки аналитиком) ───
    auto_extracted?: boolean;
    verified_by_analyst?: boolean;
    extraction_notes?: string | null;
    extraction_model?: string | null;
    source_pdf_path?: string | null;
}

export interface FinancialReport extends FinancialReportCreate {
    id: number;
    created_at?: string;
    updated_at?: string | null;
    // Автоматически рассчитанные поля в рублях (приходят с backend)
    price_per_share_rub?: number | null;
    price_at_filing_rub?: number | null;
    revenue_rub?: number | null;
    net_income_rub?: number | null;
    net_income_reported_rub?: number | null;
    total_assets_rub?: number | null;
    current_assets_rub?: number | null;
    total_liabilities_rub?: number | null;
    current_liabilities_rub?: number | null;
    equity_rub?: number | null;
    dividends_per_share_rub?: number | null;
    /** FCF = operating_cash_flow - capex, млн валюты (computed) */
    fcf?: number | null;
    operating_cash_flow_rub?: number | null;
    capex_rub?: number | null;
    depreciation_amortization_rub?: number | null;
    fcf_rub?: number | null;

    // ─── AI-парсер / проверка аналитиком ────────────────────────────────
    /** Был ли отчёт создан автоматически через AI-парсинг PDF */
    auto_extracted?: boolean;
    /** Проверен ли отчёт финансовым аналитиком вручную */
    verified_by_analyst?: boolean;
    /** Заметки о нюансах извлечения (флаги для аналитика, допущения модели) */
    extraction_notes?: string | null;
    /** Идентификатор модели, создавшей черновик (например, 'openai:gpt-4o-mini') */
    extraction_model?: string | null;
    /** Путь к исходному PDF (если парсили из CLI) */
    source_pdf_path?: string | null;
    /** Когда аналитик отметил отчёт как проверенный */
    verified_at?: string | null;

    /** bank | general — с бэкенда, только для отображения */
    report_type?: string;
}

/** Ответ эндпоинта POST /reports/parse-pdf */
export interface ParsePdfResponse {
    report: FinancialReport;
    auto_extracted: boolean;
    extraction_model: string;
    selected_pages: number;
    total_pages: number;
    warnings: string[];
}

/** Статус настройки LLM (GET /reports/ai/status) */
export interface LlmStatus {
    configured: boolean;
    provider: string;
    model: string;
    base_url: string;
}

/** Статус одного поля в diff-режиме сравнения */
export type ReportDiffStatus =
    | 'match'              // совпало
    | 'close'              // отличается < 1% (обычно округление)
    | 'mismatch'           // значимое расхождение
    | 'missing_ai'         // аналитик заполнил, модель не нашла
    | 'missing_existing'   // модель нашла, аналитик не заполнил
    | 'both_missing';      // оба пустые

/** Вид поля для форматирования в UI */
export type ReportFieldKind =
    | 'money_mln'
    | 'int'
    | 'float'
    | 'bool'
    | 'str'
    | 'date';

/** Одно поле в diff-таблице режима сравнения */
export interface ReportFieldDiff {
    field: string;
    label: string;
    kind: ReportFieldKind;
    existing_value: number | string | boolean | null;
    extracted_value: number | string | boolean | null;
    abs_diff: number | null;
    pct_diff: number | null;
    status: ReportDiffStatus;
    note: string | null;
}

/** Сводка режима сравнения */
export interface ComparisonSummary {
    total_fields: number;
    matched: number;
    close: number;
    mismatched: number;
    missing_in_ai: number;
    missing_in_existing: number;
    both_missing: number;
    max_pct_diff: number | null;
}

/** Ответ POST /reports/compare-pdf */
export interface ComparePdfResponse {
    ticker: string;
    fiscal_year: number;
    report_type: 'general' | 'bank';
    existing_report_id: number;
    existing_report_verified: boolean;
    extraction_model: string;
    selected_pages: number;
    total_pages: number;
    diffs: ReportFieldDiff[];
    summary: ComparisonSummary;
    /** Сырой ExtractedReport — «как увидела модель» */
    extracted: Record<string, unknown>;
}