import { api } from './companies.api';

/** Одна компания в сравнении: все числа таблицы. */
export interface CompareCard {
  id: number;
  ticker: string;
  name: string;
  logo_url: string | null;
  is_bank: boolean;
  price: number | null;
  shares: number | null;
  market_cap: number | null;      // млн ₽
  net_debt: number | null;        // млн ₽
  book_per_share: number | null;
  revenue: number | null;         // млн ₽, 12 мес.
  net_income: number | null;
  fcf: number | null;
  eps: number | null;
  eps_years: Record<string, number | null>;
  dividend: number | null;
  streak: number | null;
  pe: number | null;
  pb: number | null;
  p_fcf: number | null;
  dividend_yield: number | null;
  net_margin: number | null;
  roe: number | null;
  roe_spread: number | null;
  key_rate: number | null;
  current_ratio: number | null;
  debt_to_equity: number | null;
  growth_10: number | null;
  growth_5: number | null;
  profitable_years: number | null;
  reference: number | null;
  margin: number | null;
  /** Разделы свода защитного инвестора: пройден ли каждый. */
  sections: Record<string, boolean | null>;
}

export interface CompareOut {
  as_of: string;
  group: string;
  group_size: number;
  companies: CompareCard[];
  /** Абзацы комментария; имена компаний — между **. */
  comment: string[];
}

export interface CompareGroup {
  label: string;
  companies: { id: number; ticker: string; name: string }[];
}

export const fetchCompare = async (params: { ids?: number[]; with?: number; all?: boolean }): Promise<CompareOut> =>
  (await api.get<CompareOut>('/compare', {
    params: {
      ids: params.ids?.length ? params.ids.join(',') : undefined,
      with: params.with,
      all: params.all ? 1 : undefined,
    },
  })).data;

export const fetchCompareGroups = async (): Promise<CompareGroup[]> =>
  (await api.get<CompareGroup[]>('/compare/groups')).data;
