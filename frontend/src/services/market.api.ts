import { api } from './companies.api';

export interface MoexPriceResult {
    ticker: string;
    requested_date: string;
    actual_date: string;
    price: number;
    board: string;
    /** true — если биржа была закрыта и вернулась цена за предыдущий торговый день */
    is_adjusted: boolean;
    /**
     * Символ, под которым бумага торговалась в запрошенную дату, если он
     * отличается от нынешнего (YNDX для Яндекса до июля 2024). null — тикер
     * не менялся.
     */
    resolved_from?: string | null;
}

export interface MoexSharesResult {
    ticker: string;
    /** Выпуск на сегодня — реестр Мосбиржи исторических значений не хранит. */
    issuesize: number;
    secname: string;
    lotsize: number;
    board: string;
    note: string;
    /**
     * Выпуск на отчётную дату: сегодняшний, делённый на дробления после неё.
     * Именно его нужно класть в отчёт — иначе после сплита количество акций
     * и капитализация вырастут в разы. null — сплитов не было.
     */
    issuesize_at_date?: number | null;
    /** Пояснение про смену масштаба, если между отчётом и сегодня был сплит. */
    split_note?: string | null;
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
/**
 * Количество выпущенных акций из реестра Мосбиржи.
 *
 * @param ticker    Тикер (SECID)
 * @param companyId ID компании — нужен, чтобы учесть дробления
 * @param date      Отчётная дата YYYY-MM-DD. С ней ответ содержит
 *                  `issuesize_at_date` — выпуск, действовавший тогда.
 */
export const getMoexShares = async (
    ticker: string,
    companyId?: number,
    date?: string,
): Promise<MoexSharesResult> => {
    const params: Record<string, unknown> = { ticker };
    if (companyId != null) params.company_id = companyId;
    if (date) params.date = date;
    const response = await api.get<MoexSharesResult>('/market/shares/moex', { params });
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
 * @param ticker    Тикер (SECID), например: "SBER", "GAZP"
 * @param date      Дата в формате YYYY-MM-DD
 * @param companyId ID компании. Передавайте всегда, когда он известен: без
 *                  него цена за период до переименования не найдётся —
 *                  история Яндекса за 2022 год лежит под тикером YNDX.
 */
export const getMoexPrice = async (
    ticker: string,
    date: string,
    companyId?: number,
): Promise<MoexPriceResult> => {
    const params: Record<string, unknown> = { ticker, date };
    if (companyId != null) params.company_id = companyId;
    const response = await api.get<MoexPriceResult>('/market/price/moex', { params });
    return response.data;
};

export interface FxRateResult {
    currency: string;
    requested_date: string;
    actual_date: string;
    rate: number;
    /** Источник курса: "MOEX" (биржевой) или "CBR" (официальный курс ЦБ РФ) */
    source: 'MOEX' | 'CBR';
    /** true — если на requested_date биржа/ЦБ не работали, вернулся курс предыдущего рабочего дня */
    is_adjusted: boolean;
}

/**
 * Получает курс иностранной валюты к рублю на указанную дату.
 *
 * Источник MOEX (биржевой, WAPRICE) → CBR (официальный ЦБ) в качестве fallback.
 * Работает для USD, EUR, CNY, GBP, JPY, CHF. После июня 2024 для USD/EUR
 * автоматически переключается на ЦБ (MOEX прекратил торги).
 *
 * @param currency  Код валюты (USD, EUR, CNY …)
 * @param date      Дата в формате YYYY-MM-DD (обычно дата окончания отчётного периода)
 */
export const getFxRate = async (
    currency: string,
    date: string,
): Promise<FxRateResult> => {
    const response = await api.get<FxRateResult>('/market/fx/rate', {
        params: { currency, date },
    });
    return response.data;
};

// ── Раздел «Рынок» ───────────────────────────────────────────────────────

/** [дата, значение] */
export type SeriesPoint = [string, number];

export interface IndexToday {
  date: string;
  value: number;
  /** Изменение за день и за год, %. */
  day: number | null;
  year: number | null;
  /** У RGBI: доходность, % годовых, и дюрация, дни. */
  yield: number | null;
  duration_days: number | null;
}

export interface MarketYear {
  year: number | 'now';
  companies: number;
  /** Капитализация всех ÷ прибыль всех, включая убыточных. */
  pe: number;
  pe_median: number | null;
  earnings_yield: number;
  pb: number | null;
  dividend_yield: number | null;
  cap_trln: number;
  ofz10: number | null;
  key_rate: number | null;
  /** Доходность прибыли рынка минус ОФЗ 10 лет, п.п. */
  premium: number | null;
}

export interface MarketOverview {
  today: Partial<Record<'IMOEX' | 'MCFTR' | 'RGBI', IndexToday>>;
  ofz10: { month_average: number | null; note: string | null; last: number | null; last_date: string | null };
  key_rate: { value: number | null; date: string | null };
  series: {
    IMOEX: SeriesPoint[];
    MCFTR: SeriesPoint[];
    RGBI: SeriesPoint[];
    RGBI_yield: SeriesPoint[];
    ofz10: SeriesPoint[];
    key_rate: SeriesPoint[];
  };
  valuation: MarketYear[];
  as_of: string;
}

export const fetchMarketOverview = async (): Promise<MarketOverview> => {
  const { data } = await api.get<MarketOverview>('/market/overview');
  return data;
};

/** Brent ($/барр.) и курс ₽/$ по дням: [дата, Brent, курс]. */
export interface OilOut {
  source: string;
  points: [string, number, number | null][];
}

export const fetchOil = async (): Promise<OilOut> =>
  (await api.get<OilOut>('/market/oil')).data;

/** Сырьё для графика цены: ключи — в utils/commodities. */
export interface CommodityOut {
  key: string;
  label: string;
  /** «$/т», «$/унц.», «индекс». */
  unit: string;
  /** Индекс, а не цена: в рубли не переводится. */
  index: boolean;
  source: string;
  /** Месячный ряд: [первое число месяца, значение в $, курс ₽/$]. */
  points: [string, number, number | null][];
  /** Дневной биржевой ряд [день, значение в $, курс ₽/$]; пустой, если его нет. */
  daily: [string, number, number | null][];
  daily_source: string | null;
}

export const fetchCommodity = async (key: string): Promise<CommodityOut> =>
  (await api.get<CommodityOut>(`/market/commodity/${key}`)).data;

// ── Раздел «Экономика» ───────────────────────────────────────────────────

export interface MacroMeta {
  label: string;
  unit: string;
  freq: 'day' | 'month' | 'quarter' | 'year';
  source: string;
}

export interface MacroOut {
  meta: Record<string, MacroMeta>;
  /** Ряды по кодам: M_* — экономика, USDRUB/EURRUB/CNYRUB/BRENT — по неделям. */
  series: Record<string, SeriesPoint[]>;
  /** Бюджет: за месяц и за последние 12 месяцев (из накопленного итога). */
  budget: Record<string, { month: SeriesPoint[]; rolling: SeriesPoint[] }>;
  /** Закон о бюджете в первоначальной редакции по годам, млрд ₽. */
  budget_law: Record<string, { revenue: number; expense: number; balance: number }>;
  as_of: string;
}

export const fetchMacro = async (): Promise<MacroOut> =>
  (await api.get<MacroOut>('/market/macro')).data;

export interface MacroCompany {
  id: number;
  ticker: string;
  name: string;
  /** Цена на дату, приведённая к сегодняшнему числу акций. */
  price: number;
  price_date: string;
  /** Опорная стоимость, какой она считалась в тот день. */
  reference: number;
  low: number | null;
  high: number | null;
  basis: string | null;
  risk_free: number | null;
  price_now: number | null;
  /** Изменение цены с той даты до сегодня, % (без дивидендов). */
  change: number | null;
}

export const fetchMacroCompanies = async (on: string): Promise<{ on: string; rows: MacroCompany[] }> =>
  (await api.get<{ on: string; rows: MacroCompany[] }>('/market/macro/companies', { params: { on } })).data;
