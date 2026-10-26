import type { ValuationBasis } from '../services/valuation.api';

export interface Freshness {
  text: string;
  /** Отчёт старый или цена ушла далеко — рынок, похоже, знает больше отчёта. */
  stale: boolean;
}

/** «отчёту за 2025 год» / «12 месяцам по отчёту за 1П 2026». */
function basisName(label: string, year: number): string {
  if (label.startsWith('LTM')) {
    const period = label.slice(4).replace(/^(\d)П/, '$1П ').replace(/^(\d)М/, '$1 мес. ');
    return `12 месяцам по отчёту за ${period}`;
  }
  return `отчёту за ${year} год`;
}

/**
 * Опорная меняется только в день отчёта, а цена — каждый день. Между ними
 * рынок успевает отыграть то, чего в отчёте ещё нет: у Лукойла весь 2023 год,
 * у Юнипро — падение до отчёта, который его объяснил. Строка говорит, сколько
 * оценке лет и куда за это время ушла цена.
 */
export function freshnessOf(basis: ValuationBasis | null | undefined, price: number | null, today = new Date()): Freshness | null {
  if (!basis?.since) return null;
  const since = new Date(`${basis.since}T00:00:00`);
  const months = Math.max(0, Math.round((today.getTime() - since.getTime()) / (30.44 * 24 * 3600 * 1000)));
  const age = months < 1 ? 'меньше месяца назад' : `${months} мес. назад`;
  const change = basis.price_then && price ? price / basis.price_then - 1 : null;
  const moved = change === null ? ''
    : ` Цена с тех пор ${change >= 0 ? '+' : '−'}${Math.round(Math.abs(change) * 100)}%.`;
  const date = basis.since.split('-').reverse().join('.');
  return {
    text: `Оценка — по ${basisName(basis.label, basis.year)}, известному с ${date} (${age}).${moved}`,
    stale: months >= 9 || (change !== null && Math.abs(change) >= 0.25),
  };
}
