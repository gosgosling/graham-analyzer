import { api } from './companies.api';

/** Одна из четырёх величин формулы вместе с её происхождением. */
export interface BaseMultipleOut {
  value: number | null;
  problem: string | null;
  payout: number;
  risk_free_rate: number;
  risk_premium: number;
  dividend_growth: number;
  required_return: number;
  spread: number;
  fragile: boolean;
  earnings_yield: number | null;
  historic_average: number;
  historic_range: number[];
}

export interface ExcludedCompany {
  ticker: string;
  market_cap: number;
  reference_cap: number;
  ratio: number;
  reason: string;
}

export interface MarketSnapshotOut {
  year: number;
  tickers: string[];
  companies: number;
  payout: number | null;
  roe: number | null;
  sustainable_growth: number | null;
  total_dividends: number;
  total_profit: number;
  total_equity: number;
  market_cap: number;
  profit_ltm: number;
  /** Фактический P/E проверенного подмножества — с чем сверяемся. */
  observed_multiple: number | null;
  /** Выброшенные из суммы и почему: молча пропускать компанию нельзя. */
  excluded: ExcludedCompany[];
}

export interface SensitivityRow {
  risk_premium_shift: number;
  risk_premium: number;
  value: number | null;
  problem: string | null;
}

export interface MarketMultipleOut {
  assumption: {
    year: number;
    risk_free_rate: number;
    normalized_risk_free_rate: number | null;
    risk_premium: number;
    dividend_growth: number;
    payout: number | null;
    payout_used: number;
    payout_from_data: boolean;
    note: string | null;
    source: string;
  };
  snapshot: MarketSnapshotOut;
  current: BaseMultipleOut | null;
  normalized: BaseMultipleOut | null;
  /** Во сколько раз множитель вырастет при нормализации ставок. */
  rate_effect: number | null;
  sensitivity: SensitivityRow[];
  implied: {
    growth_at_stated_premium: number | null;
    premium_at_stated_growth: number | null;
    risk_free_at_stated_premium_and_growth: number | null;
  };
  reference: {
    book: Record<string, number>;
    book_multiple: number | null;
    historic_average: number;
    historic_range: number[];
  };
}

export async function getMarketMultiple(): Promise<MarketMultipleOut> {
  const { data } = await api.get<MarketMultipleOut>('/valuation/market-multiple');
  return data;
}
