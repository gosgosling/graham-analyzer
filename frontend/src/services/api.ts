import axios from 'axios';
import { Security, Company, FinancialReport, FinancialReportCreate, MultiplierRecord, CurrentMultipliers } from '../types';

const api = axios.create({
    baseURL: 'http://localhost:8000',
});

export const getSecurities = async (): Promise<Security[]> => {
    try {
        const response = await api.get<Security[]>('/securities/');
        return response.data;
    } catch (error) {
        console.error('Error fetching securities:', error);
        throw error;
    }
};

export const getCompanies = async (): Promise<Company[]> => {
    try {
        const response = await api.get<Company[]>('/companies/');
        return response.data;
    } catch (error) {
        console.error('Error fetching companies:', error);
        throw error;
    }
};

export const getCompanyById = async (companyId: number): Promise<Company> => {
    try {
        const response = await api.get<Company>(`/companies/${companyId}`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching company ${companyId}:`, error);
        throw error;
    }
};

// ============ API для финансовых отчетов ============

export const createFinancialReport = async (
    reportData: FinancialReportCreate
): Promise<FinancialReport> => {
    try {
        const response = await api.post<FinancialReport>('/reports/', reportData);
        return response.data;
    } catch (error) {
        console.error('Error creating financial report:', error);
        throw error;
    }
};

export const getFinancialReports = async (): Promise<FinancialReport[]> => {
    try {
        const response = await api.get<FinancialReport[]>('/reports/');
        return response.data;
    } catch (error) {
        console.error('Error fetching financial reports:', error);
        throw error;
    }
};

export const getCompanyReports = async (companyId: number): Promise<FinancialReport[]> => {
    try {
        const response = await api.get<FinancialReport[]>(`/reports/company/${companyId}`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching reports for company ${companyId}:`, error);
        throw error;
    }
};

export const getLatestCompanyReport = async (companyId: number): Promise<FinancialReport> => {
    try {
        const response = await api.get<FinancialReport>(`/reports/company/${companyId}/latest`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching latest report for company ${companyId}:`, error);
        throw error;
    }
};

export const updateFinancialReport = async (
    reportId: number,
    reportData: FinancialReportCreate
): Promise<FinancialReport> => {
    try {
        const response = await api.put<FinancialReport>(`/reports/${reportId}`, reportData);
        return response.data;
    } catch (error) {
        console.error(`Error updating report ${reportId}:`, error);
        throw error;
    }
};

export const deleteFinancialReport = async (reportId: number): Promise<void> => {
    try {
        await api.delete(`/reports/${reportId}`);
    } catch (error) {
        console.error(`Error deleting report ${reportId}:`, error);
        throw error;
    }
};

// ============ API для мультипликаторов ============

/** Актуальные мультипликаторы (LTM + текущая цена), вычисляются на лету */
export const getCompanyCurrentMultipliers = async (
    companyId: number,
    price?: number,
): Promise<CurrentMultipliers> => {
    const params = price !== undefined ? { price } : {};
    const response = await api.get<CurrentMultipliers>(
        `/companies/${companyId}/multipliers/current`,
        { params },
    );
    return response.data;
};

/** История мультипликаторов из кэша (для таблицы и графиков) */
export const getCompanyMultipliersHistory = async (
    companyId: number,
    type?: 'report_based' | 'current' | 'daily',
    limit = 365,
): Promise<MultiplierRecord[]> => {
    const params: Record<string, string | number> = { limit };
    if (type) params['type'] = type;
    const response = await api.get<MultiplierRecord[]>(
        `/companies/${companyId}/multipliers/history`,
        { params },
    );
    return response.data;
};

/** Обновить цену из T-Invest API и пересчитать мультипликаторы */
export const refreshCompanyMultipliers = async (
    companyId: number,
    saveToCache = true,
): Promise<{ company_id: number; ticker: string; price: number | null; success: boolean }> => {
    const response = await api.post(
        `/companies/${companyId}/multipliers/refresh`,
        null,
        { params: { save_to_cache: saveToCache } },
    );
    return response.data;
};

/** Мультипликаторы по конкретному отчёту */
export const getReportMultipliers = async (reportId: number): Promise<MultiplierRecord> => {
    const response = await api.get<MultiplierRecord>(`/reports/${reportId}/multipliers`);
    return response.data;
};

// ============ API рыночных данных (MOEX) ============

export interface MoexPriceResult {
    ticker: string;
    requested_date: string;
    actual_date: string;
    price: number;
    board: string;
    /** true — если биржа была закрыта и вернулась цена за предыдущий торговый день */
    is_adjusted: boolean;
}

export interface MoexSharesResult {
    ticker: string;
    issuesize: number;
    secname: string;
    lotsize: number;
    board: string;
    note: string;
}

/**
 * Получает количество выпущенных акций (ISSUESIZE) из реестра Мосбиржи.
 * Это текущее значение — историческое недоступно.
 */
export const getMoexShares = async (ticker: string): Promise<MoexSharesResult> => {
    const response = await api.get<MoexSharesResult>('/market/shares/moex', {
        params: { ticker },
    });
    return response.data;
};

export interface DividendPayment {
    registryclosedate: string;
    value: number;
    currency: string;
}

export interface MoexDividendsResult {
    ticker: string;
    fiscal_year: number;
    period_type: string;
    fiscal_quarter: number | null;
    period_from: string;
    period_till: string;
    total: number;
    currency: string;
    payments: DividendPayment[];
    payments_count: number;
    note: string;
}

/**
 * Получает дивиденды компании с Мосбиржи за отчётный период.
 * Суммирует все выплаты, чья дата закрытия реестра попадает в период.
 */
export const getMoexDividends = async (
    ticker: string,
    fiscal_year: number,
    period_type: string,
    fiscal_quarter?: number | null,
): Promise<MoexDividendsResult> => {
    const params: Record<string, unknown> = { ticker, fiscal_year, period_type };
    if (fiscal_quarter != null) params.fiscal_quarter = fiscal_quarter;
    const response = await api.get<MoexDividendsResult>('/market/dividends/moex', { params });
    return response.data;
};

/**
 * Получает цену закрытия акции на Мосбирже на указанную дату.
 * Если биржа была закрыта (выходной, праздник), возвращает цену
 * последнего доступного торгового дня.
 *
 * @param ticker  Тикер (SECID), например: "SBER", "GAZP"
 * @param date    Дата в формате YYYY-MM-DD
 */
export const getMoexPrice = async (
    ticker: string,
    date: string,
): Promise<MoexPriceResult> => {
    const response = await api.get<MoexPriceResult>('/market/price/moex', {
        params: { ticker, date },
    });
    return response.data;
};