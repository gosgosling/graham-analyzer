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
    report_date: string; // YYYY-MM-DD формат
    price_per_share?: number | null;
    shares_outstanding?: number | null;
    revenue?: number | null;
    net_income?: number | null;
    total_assets?: number | null;
    current_assets?: number | null;
    total_liabilities?: number | null;
    current_liabilities?: number | null;
    equity?: number | null;
    dividends_per_share?: number | null;
    dividends_paid: boolean;
    currency: string; // "RUB" или "USD"
    exchange_rate?: number | null; // Обязателен для USD
}

export interface FinancialReport extends FinancialReportCreate {
    id: number;
    created_at?: string;
    updated_at?: string | null;
}