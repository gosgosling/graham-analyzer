import type { MarketColumn, MarketRow, Verdict } from '../services/screen.api';
import { defaultDir, nextSort, sortRows } from './screenSort';

const col = (metric: string, applied: string): MarketColumn => ({
  metric, axis: '', label: metric, axis_label: '', book: null, book_text: applied, applied_text: applied, source: '', ours: false,
});
const COLUMNS = [col('roe', '≥ 10–20'), col('pe_average', '≤ 8–20')];

const cell = (metric: string, value: number | null, status: Verdict['status'] = 'pass'): Verdict => ({
  axis: '', label: '', metric, metric_label: metric, value, unit: '', of: null, status, applied: null,
  book: null, adjusted: false, text: '', book_text: '', source: '', ours: false, note: null, caveat: null,
  distorted: false, marginal: false, shortfall: null,
});

const row = (ticker: string, roe: Verdict, pe: Verdict, margin: number | null): MarketRow => ({
  id: ticker.length, ticker, name: ticker, profile: '', profile_label: '', passed: 1, checked: 2, clears: false,
  complete: true,
  safety: margin === null ? null : { signal: 'fair', label: '', reason: null, value_margin: margin } as MarketRow['safety'],
  cells: [roe, pe],
});

const ROWS = [
  row('AAA', cell('roe', 12), cell('pe_average', 9), 0.1),
  row('BBB', cell('roe', 25), cell('pe_average', 4), -0.3),
  row('CCC', cell('roe', null, 'unknown'), cell('pe_average', 6), null),
  row('DDD', cell('capital_core', 30), cell('pe_average', 12), 0.5),
];

const tickers = (rows: MarketRow[]) => rows.map((r) => r.ticker).join(' ');

test('направление по умолчанию: P/E — по возрастанию, остальное — по убыванию', () => {
  expect(defaultDir('m:pe_average', COLUMNS)).toBe('asc');
  expect(defaultDir('m:roe', COLUMNS)).toBe('desc');
  expect(defaultDir('safety', COLUMNS)).toBe('desc');
  expect(defaultDir('company', COLUMNS)).toBe('asc');
});

test('нажатия идут по кругу: своё направление, обратное, без сортировки', () => {
  const first = nextSort(null, 'safety', COLUMNS);
  expect(first).toEqual({ key: 'safety', dir: 'desc' });
  const second = nextSort(first, 'safety', COLUMNS);
  expect(second).toEqual({ key: 'safety', dir: 'asc' });
  expect(nextSort(second, 'safety', COLUMNS)).toBeNull();
  expect(nextSort(second, 'm:pe_average', COLUMNS)).toEqual({ key: 'm:pe_average', dir: 'asc' });
});

test('пустые значения внизу в обе стороны', () => {
  expect(tickers(sortRows(ROWS, { key: 'safety', dir: 'desc' }, COLUMNS))).toBe('DDD AAA BBB CCC');
  expect(tickers(sortRows(ROWS, { key: 'safety', dir: 'asc' }, COLUMNS))).toBe('BBB AAA DDD CCC');
});

test('чужой банковский показатель в колонке и «нет данных» не сравниваются с числами', () => {
  expect(tickers(sortRows(ROWS, { key: 'm:roe', dir: 'desc' }, COLUMNS))).toBe('BBB AAA CCC DDD');
});

test('P/E по возрастанию: дешёвые сверху', () => {
  expect(tickers(sortRows(ROWS, { key: 'm:pe_average', dir: 'asc' }, COLUMNS))).toBe('BBB CCC AAA DDD');
});

test('без сортировки — исходный порядок', () => {
  expect(tickers(sortRows(ROWS, null, COLUMNS))).toBe('AAA BBB CCC DDD');
});

test('банковский показатель без своей колонки сортируется по своей клетке, меньшее — лучше', () => {
  const bank = (ticker: string, cor: number) => row(ticker, cell('roe', 10), cell('cost_of_risk_average', cor), 0);
  const banks = [bank('AAA', 1.8), bank('BBB', 0.9), bank('CCC', 1.2)];
  expect(defaultDir('m:cost_of_risk_average', COLUMNS)).toBe('asc');
  expect(tickers(sortRows(banks, { key: 'm:cost_of_risk_average', dir: 'asc' }, COLUMNS))).toBe('BBB CCC AAA');
});
