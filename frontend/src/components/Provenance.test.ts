import { ltmComposition } from './Provenance';
import type { CurrentMultipliers, FinancialReport } from '../types';

const reports = [
  { id: 1, period_type: 'quarterly', fiscal_year: 2026, fiscal_quarter: 3, report_date: '2026-09-30' },
  // Позднее загруженный годовой отчёт не меняет состав исторического LTM.
  { id: 2, period_type: 'annual', fiscal_year: 2026, report_date: '2026-12-31' },
] as FinancialReport[];

test.each([['quarterly_1_derived', 3], ['quarterly_2_derived', 6], ['quarterly_3_derived', 9],
  ['semi_annual_derived', 6]])('LTM composition for %s', (source, months) => {
  const current = { balance_report_id: 1, ltm_source: source } as CurrentMultipliers;
  expect(ltmComposition(current, reports)).toBe(`2025 год + ${months} мес. 2026 − ${months} мес. 2025`);
});
