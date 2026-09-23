import { api } from './companies.api';

/**
 * История цены для графика на карточке компании.
 *
 * Множители приходят готовыми, посчитанными на бэкенде. Делить цену на прибыль
 * здесь было бы соблазнительно и неверно: множитель за конкретный день должен
 * считаться по тому отчёту, который на ту дату уже был опубликован, а знание
 * «отчёт за 2024 год становится известен весной 2025-го» живёт в бэкенде.
 */

/** Один торговый день: цена и множители к ней. */
export interface PricePoint {
  date: string;
  price: number;
  /** null там, где отчёта ещё не было или прибыль неположительна. */
  pe: number | null;
  pb: number | null;
  /** Год отчёта, по которому посчитаны множители этого дня. */
  basis_year: number | null;
}

/** Публикация годового отчёта — засечка на оси времени. */
export interface PriceReportMark {
  year: number;
  published: string;
  eps: number;
  bvps: number | null;
}

export interface PriceHistoryOut {
  company: { id: number; ticker: string; name: string };
  points: PricePoint[];
  reports: PriceReportMark[];
  summary: {
    from: string;
    till: string;
    count: number;
    min: number;
    max: number;
    last: number;
    average: number;
  } | null;
}

export async function fetchPriceHistory(
  companyId: number,
  since?: string,
): Promise<PriceHistoryOut> {
  const { data } = await api.get<PriceHistoryOut>(
    `/companies/${companyId}/prices`,
    since ? { params: { since } } : undefined,
  );
  return data;
}
