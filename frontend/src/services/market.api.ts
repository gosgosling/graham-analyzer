import { api } from './companies.api';

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
 * Получает количество выпущенных акций (ISSUESIZE) из реестра Мосбиржи.
 * Это текущее значение — историческое недоступно.
 */
export const getMoexShares = async (ticker: string): Promise<MoexSharesResult> => {
    const response = await api.get<MoexSharesResult>('/market/shares/moex', {
        params: { ticker },
    });
    return response.data;
};

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
