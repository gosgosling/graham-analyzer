import type { MarketColumn, MarketRow, MarketScreenOut, Verdict } from '../services/screen.api';

/**
 * Скринер как сито: требования по очереди, после каждого видно, сколько
 * компаний осталось. Сначала требования Грэма (гл. 14 и 15 «Разумного
 * инвестора») в его порядке — размер, финансовое положение, стабильность,
 * дивиденды, рост, цена, — затем наши дополнения про отдачу и деньги.
 */

/** Наши дополнения: у Грэма этих требований нет. */
export const OURS = new Set(['roe', 'cash_positive_years', 'cash_growth', 'cash_growth_short']);

const AXIS_ORDER = ['size', 'financial', 'stability', 'dividends', 'growth', 'price', 'profitability'];

const axisRank = (c: MarketColumn) => {
  const i = AXIS_ORDER.indexOf(c.axis);
  return i < 0 ? AXIS_ORDER.length : i;
};

/** Колонки в порядке сита: Грэм, затем наши; внутри — по оси. */
export function sieveOrder(columns: MarketColumn[]): MarketColumn[] {
  return [...columns].sort((a, b) =>
    Number(OURS.has(a.metric)) - Number(OURS.has(b.metric)) || axisRank(a) - axisRank(b));
}

/** Требование пройдено, если пройдено или к отрасли не применяется. Нет
 *  данных — не пройдено: Грэм требует подтверждённого, а не непроверенного. */
export const passes = (cell: Verdict | null) => cell != null && (cell.status === 'pass' || cell.status === 'n/a');

export interface SieveStep {
  column: MarketColumn;
  remaining: number;
  dropped: number;
  ours: boolean;
}

export function sieve(data: MarketScreenOut): { steps: SieveStep[]; afterGraham: number; cleared: number } {
  const index = new Map(data.columns.map((c, i) => [c.metric, i]));
  let alive: MarketRow[] = data.rows;
  let afterGraham = alive.length;
  const steps = sieveOrder(data.columns).map((column) => {
    const i = index.get(column.metric)!;
    const before = alive.length;
    alive = alive.filter((row) => passes(row.cells[i]));
    if (!OURS.has(column.metric)) afterGraham = alive.length;
    return { column, remaining: alive.length, dropped: before - alive.length, ours: OURS.has(column.metric) };
  });
  return { steps, afterGraham, cleared: alive.length };
}

/** Непройденные требования строки — в порядке сита. */
export function misses(data: MarketScreenOut, row: MarketRow): Verdict[] {
  const index = new Map(data.columns.map((c, i) => [c.metric, i]));
  return sieveOrder(data.columns)
    .map((c) => row.cells[index.get(c.metric)!])
    .filter((cell): cell is Verdict => cell != null && !passes(cell));
}

export function groupRows(data: MarketScreenOut) {
  const withMisses = data.rows.map((row) => ({ row, misses: misses(data, row) }));
  return {
    passed: withMisses.filter((x) => x.misses.length === 0),
    one: withMisses.filter((x) => x.misses.length === 1),
    two: withMisses.filter((x) => x.misses.length === 2),
    rest: withMisses.filter((x) => x.misses.length > 2),
  };
}
