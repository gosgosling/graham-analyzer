import type { FinancialReport } from '../types';
import { buildColumns, derived, ltmColumn, periodLabel } from './statements';

const rep = (id: number, fy: number, period: FinancialReport['period_type'], date: string, extra: Partial<FinancialReport> = {}) =>
  ({ id, fiscal_year: fy, period_type: period, report_date: date, currency: 'RUB', fiscal_quarter: null, ...extra }) as FinancialReport;

const reports = [
  rep(1, 2024, 'annual', '2024-12-31', { revenue: 100, net_income_reported: 20, equity: 300 }),
  rep(2, 2025, 'semi_annual', '2025-06-30', { revenue: 60, net_income_reported: 9, equity: 310 }),
  rep(3, 2025, 'annual', '2025-12-31', { revenue: 130, net_income_reported: 25, equity: 330, dividends_per_share: 5 }),
  rep(4, 2026, 'semi_annual', '2026-06-30', { revenue: 70, net_income_reported: 14, equity: 345 }),
];

test('LTM: полугодие + прошлый год − прошлое полугодие; баланс — на последнюю дату', () => {
  const ltm = ltmColumn(reports)!;
  expect(ltm.values.revenue).toBe(70 + 130 - 60);
  expect(ltm.values.net_income_reported).toBe(14 + 25 - 9);
  expect(ltm.values.equity).toBe(345);
  expect(ltm.values.dividends_per_share).toBe(5);
});

test('годы — годовые отчёты и LTM последним; все отчёты — без LTM, от старых к свежим', () => {
  expect(buildColumns(reports, false).map((c) => c.label)).toEqual(['2024', '2025', '12 мес.']);
  expect(buildColumns(reports, true).map((c) => c.label)).toEqual(['2024', '6 мес. 2025', '2025', '6 мес. 2026']);
});

test('после годового отчёта LTM не нужна', () => {
  expect(ltmColumn(reports.slice(0, 3))).toBeNull();
});

test('подписи промежуточных периодов', () => {
  expect(periodLabel(rep(9, 2025, 'quarterly', '2025-09-30', { fiscal_quarter: 3 }))).toBe('9 мес. 2025');
});

test('простая арифметика строк', () => {
  expect(derived.fcf({ operating_cash_flow: 100, capex: 40 })).toBe(60);
  expect(derived.netDebt({ debt: 50, cash_and_equivalents: 80 })).toBe(-30);
  expect(derived.eps({ net_income_reported: 20, shares_outstanding: 1e6 })).toBe(20);
});

test('прошлый период для LTM — из сравнительной колонки свежего отчёта', () => {
  const withComp = [...reports.slice(0, 3), { ...reports[3], comparative: { revenue: 55 } } as FinancialReport];
  expect(ltmColumn(withComp)!.values.revenue).toBe(70 + 130 - 55);
});
