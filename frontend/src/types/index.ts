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

export interface Company {
    id?: number; // ID из базы данных
    figi: string;
    ticker: string;
    name: string;
    isin?: string;
    sector?: string;
    currency: string;
    lot: number;
    api_trade_available_flag: boolean;
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
    total_assets?: number | null;
    current_assets?: number | null;
    total_liabilities?: number | null;
    current_liabilities?: number | null;
    equity?: number | null;
    dividends_per_share?: number | null;
    dividends_paid: boolean;
    
    // Валюта
    currency: string; // "RUB" или "USD"
    exchange_rate?: number | null; // Обязателен для USD
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
    total_assets_rub?: number | null;
    current_assets_rub?: number | null;
    total_liabilities_rub?: number | null;
    current_liabilities_rub?: number | null;
    equity_rub?: number | null;
    dividends_per_share_rub?: number | null;
}