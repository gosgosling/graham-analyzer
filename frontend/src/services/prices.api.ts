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
  /** Почему множителя за этот день нет: убыток, нет данных в отчёте, отчёт не вышел. */
  pe_gap: string | null;
  pb_gap: string | null;
}

/** Публикация годового отчёта — засечка на оси времени. */
export interface PriceReportMark {
  year: number;
  published: string;
  eps: number;
  bvps: number | null;
}

/** Засечка на графике: выход отчёта, дивидендная отсечка, сплит. */
export interface PriceEvent {
  date: string;
  kind: 'report' | 'dividend' | 'split';
  label: string;
  detail: string | null;
  value?: number | null;
}

/**
 * Как часто открытая страница перечитывает цену. Сервер обновляет цены
 * каждые пять минут сам; страница забирает готовое из базы — это быстро и
 * ничего не пишет. В фоновой вкладке опрос стоит, при возврате на неё цена
 * перечитывается сразу.
 */
export const LIVE_PRICE_REFRESH_MS = 5 * 60 * 1000;
/** Чуть меньше шага опроса: при возврате на вкладку цена не старше минуты. */
export const LIVE_PRICE_STALE_MS = 60 * 1000;

/** Откуда текущая цена и насколько она свежая. */
export interface PriceQuote {
  /** «tinvest» — брокер; «moex» — резерв, котировка Мосбиржи с задержкой 15 минут. */
  source: 'tinvest' | 'moex' | string;
  quoted_at: string;
  /** Цена старше трёх дней — оценка считается по устаревшей цене. */
  stale: boolean;
}

export interface PriceHistoryOut {
  company: { id: number; ticker: string; name: string };
  quote?: PriceQuote | null;
  points: PricePoint[];
  reports: PriceReportMark[];
  events?: PriceEvent[];
  /** Подпись про сплиты: цены до них приведены к нынешнему числу акций. */
  split_note?: string | null;
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
