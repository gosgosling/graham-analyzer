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

export interface PayoutRung {
  payout: number;
  /** Свой на каждой ступени: расти можно только на то, что не раздал. */
  growth: number | null;
  spread: number | null;
  multiple: number | null;
  problem: string | null;
  normalized_multiple: number | null;
  dividend_yield: number | null;
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
  payout_ladder: PayoutRung[];
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


// ── Оценка отдельной компании ─────────────────────────────────────────────

export interface ValuationLadder {
  name: string;
  normal_per_share: number;
  multiple: number;
  value: number;
  adjusted: number | null;
  asset_note: string | null;
}

export interface RiskPenaltyOut {
  spread: number;
  coverage: number;
  history: number;
  total: number;
  notes: string[];
}

export interface ValueBandOut {
  low: number | null;
  high: number | null;
  /** Та же полоса до поправки на активы: по ней и меряется ширина. */
  low_by_earnings: number | null;
  high_by_earnings: number | null;
  width: number | null;
  asset_lift: number | null;
  ladders: ValuationLadder[];
  penalty: RiskPenaltyOut | null;
  multiple_high: number | null;
  multiple_low: number | null;
  /** Рост, подставленный в формулу — уже с учётом потолка. */
  growth: number | null;
  /** Он же до потолка: расхождение и есть сообщение о малом знаменателе. */
  growth_uncapped: number | null;
  growth_capped: boolean;
  refused: boolean;
  reason: string | null;
  warnings: string[];
  /** Чем меряется уровень: 'trend' или 'average'. */
  basis: string;
}

export interface CompanyValuationOut {
  available: boolean;
  reason?: string;
  window?: number;
  price?: number | null;
  payout?: number | null;
  /** Из чего сложился возврат владельцу: выплата и выкуп по отдельности. */
  payout_dividends?: number | null;
  payout_buyback?: number | null;
  /** Пометка о том, что высокая отдача держится на малом капитале. */
  denominator?: {
    roe: number;
    price_to_book: number | null;
    reason: string;
  } | null;
  history_years?: number;
  book_value_per_share?: number | null;
  stability?: {
    minimum: number;
    maximum: number;
    median: number;
    years: number;
    relative_spread: number | null;
    halves_gap: number | null;
    label: string;
  } | null;
  structure?: {
    coverage: number | null;
    verdict: string;
    reason: string | null;
    valuation_allowed: boolean;
  };
  cash_backing?: number | null;
  band?: ValueBandOut;
  molodovsky?: {
    reported_multiple: number | null;
    normal_multiple: number | null;
    depression: number | null;
    artifact: boolean;
    reason: string | null;
  };
  /** Обратный ход: какой рост сидит в цене и по силам ли он компании. */
  priced_in?: {
    multiple_paid: number;
    growth_priced_in: number;
    growth_affordable: number | null;
    gap: number | null;
    demanding: boolean;
  } | null;
  direction?: { label: string; change: number | null } | null;
  assumption?: { year: number; risk_free_rate: number; risk_premium: number };
  /** Простая средняя по каждой лестнице — для сравнения с тенденцией. */
  averages?: Record<string, number>;
  /** Линия тенденции: уровень, наклон и не упёрлась ли она в пик. */
  trends?: Record<string, {
    value: number;
    annual_growth: number | null;
    peak: number;
    capped: boolean;
    years_used: number;
  }>;
  price_to_low?: number | null;
  price_to_high?: number | null;
}

export async function getCompanyValuation(
  companyId: number,
  window = 7,
): Promise<CompanyValuationOut> {
  const { data } = await api.get<CompanyValuationOut>(
    `/valuation/company/${companyId}`,
    { params: { window } },
  );
  return data;
}


// ── Ряды по годам ─────────────────────────────────────────────────────────

export interface SeriesYear {
  year: number;
  eps: number | null;
  fcf_per_share: number | null;
  owner_earnings_per_share: number | null;
  book_value_per_share: number | null;
  dividends_per_share: number | null;
  roe: number | null;
  /** Цена на дату отчёта — как торговалась тогда, без приведения к сплитам. */
  price: number | null;
}

export interface SeriesAverage {
  value: number;
  first_year: number;
  last_year: number;
  complete: boolean;
}

export interface CompanySeriesOut {
  available: boolean;
  window?: number;
  years: SeriesYear[];
  averages: Record<string, SeriesAverage>;
  current_price?: number | null;
}

export async function getCompanySeries(
  companyId: number,
  window = 7,
): Promise<CompanySeriesOut> {
  const { data } = await api.get<CompanySeriesOut>(
    `/valuation/company/${companyId}/series`,
    { params: { window } },
  );
  return data;
}
