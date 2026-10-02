import type { MarketColumn, MarketRow, MarketScreenOut, Verdict } from '../services/screen.api';
import { groupRows, sieve, sieveOrder } from './screenSieve';

const col = (metric: string, axis: string): MarketColumn => ({
  metric, axis, label: metric, axis_label: axis, book: null, book_text: '', source: '', ours: false,
});

// Порядок колонок как отдаёт сервер: отдача на капитал первой.
const COLUMNS = [col('roe', 'profitability'), col('revenue', 'size'), col('current_ratio', 'financial'),
  col('streak', 'dividends'), col('pe_average', 'price')];

const cell = (metric: string, status: Verdict['status']): Verdict => ({
  axis: '', label: '', metric, metric_label: metric, value: 1, unit: '', of: null, status, applied: null,
  book: null, adjusted: false, text: '', book_text: '', source: '', ours: false, note: null, caveat: null,
  distorted: false, marginal: false, shortfall: null,
});

const row = (ticker: string, statuses: Verdict['status'][]): MarketRow => ({
  id: 1, ticker, name: ticker, profile: '', profile_label: '', passed: 0, checked: 0, clears: false,
  complete: true, safety: null, cells: statuses.map((s, i) => cell(COLUMNS[i].metric, s)),
});

const DATA: MarketScreenOut = {
  standard: 'defensive', standard_label: '', columns: COLUMNS,
  summary: { total: 4, cleared: 1, fails: {} },
  rows: [
    row('LKOH', ['pass', 'pass', 'pass', 'pass', 'pass']),
    row('SBER', ['pass', 'pass', 'n/a', 'fail', 'pass']),     // у банка ликвидность не применяется
    row('ROSN', ['fail', 'pass', 'fail', 'pass', 'pass']),
    row('XXXX', ['pass', 'fail', 'unknown', 'fail', 'fail']),
  ],
};

test('сначала требования Грэма в его порядке, наши — в конце', () => {
  expect(sieveOrder(COLUMNS).map((c) => c.metric)).toEqual(['revenue', 'current_ratio', 'streak', 'pe_average', 'roe']);
});

test('сито: сколько осталось после каждого требования', () => {
  const { steps, afterGraham, cleared } = sieve(DATA);
  expect(steps.map((s) => [s.column.metric, s.remaining, s.dropped])).toEqual([
    ['revenue', 3, 1], ['current_ratio', 2, 1], ['streak', 1, 1], ['pe_average', 1, 0], ['roe', 1, 0],
  ]);
  expect(afterGraham).toBe(1);
  expect(cleared).toBe(1);
});

test('группы по числу непройденных; «нет данных» — тоже непройдено', () => {
  const g = groupRows(DATA);
  expect(g.passed.map((x) => x.row.ticker)).toEqual(['LKOH']);
  expect(g.one.map((x) => [x.row.ticker, x.misses[0].metric])).toEqual([['SBER', 'streak']]);
  expect(g.two.map((x) => x.misses.map((m) => m.metric))).toEqual([['current_ratio', 'roe']]);
  expect(g.rest.map((x) => x.row.ticker)).toEqual(['XXXX']);
});
