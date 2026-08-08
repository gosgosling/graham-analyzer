import { isFullYear, periodLabel, periodMonths, pickBankPeriods } from './bankPeriod';
import type { FinancialReport } from '../types';

function report(over: Partial<FinancialReport> = {}): FinancialReport {
  return {
    id: 1,
    company_id: 60,
    period_type: 'annual',
    fiscal_year: 2025,
    fiscal_quarter: null,
    report_date: '2025-12-31',
    bank_metrics: { roa: 2.5 },
    ...over,
  } as unknown as FinancialReport;
}

describe('periodMonths', () => {
  it('годовой отчёт — двенадцать месяцев', () => {
    expect(periodMonths(report())).toBe(12);
  });

  it('полугодовой — шесть', () => {
    expect(periodMonths(report({ period_type: 'semi_annual' }))).toBe(6);
  });

  it('квартальные накопительные: Q3 — девять месяцев, а не три', () => {
    expect(periodMonths(report({ period_type: 'quarterly', fiscal_quarter: 3 }))).toBe(9);
    expect(periodMonths(report({ period_type: 'quarterly', fiscal_quarter: 1 }))).toBe(3);
  });

  it('четыре квартала — это уже полный год', () => {
    const q4 = report({ period_type: 'quarterly', fiscal_quarter: 4 });
    expect(periodMonths(q4)).toBe(12);
    expect(isFullYear(q4)).toBe(true);
  });

  it('неизвестный период считаем годом, а не множим на случайный коэффициент', () => {
    expect(periodMonths(report({ period_type: undefined as never }))).toBe(12);
  });
});

describe('periodLabel', () => {
  it('год называется годом', () => {
    expect(periodLabel(report())).toBe('2025 год');
  });

  it('промежуточный период — числом месяцев', () => {
    expect(periodLabel(report({ period_type: 'semi_annual', fiscal_year: 2026 }))).toBe(
      '6 месяцев 2026',
    );
  });
});

describe('pickBankPeriods', () => {
  const annual2025 = report({ id: 1, report_date: '2025-12-31', fiscal_year: 2025 });
  const half2026 = report({
    id: 2,
    period_type: 'semi_annual',
    fiscal_year: 2026,
    report_date: '2026-06-30',
  });

  it('свежий промежуточный и последний полный год — разные отчёты', () => {
    const { latest, lastFullYear } = pickBankPeriods([annual2025, half2026]);
    expect(latest?.id).toBe(2);
    expect(lastFullYear?.id).toBe(1);
  });

  it('порядок на входе не важен', () => {
    const { latest } = pickBankPeriods([half2026, annual2025]);
    expect(latest?.id).toBe(2);
  });

  it('без промежуточных обе ссылки — на один и тот же годовой отчёт', () => {
    const { latest, lastFullYear } = pickBankPeriods([annual2025]);
    expect(latest).toBe(lastFullYear);
  });

  it('отчёты без банковских показателей не участвуют', () => {
    const general = report({ id: 3, report_date: '2026-12-31', bank_metrics: null });
    const { latest } = pickBankPeriods([annual2025, general]);
    expect(latest?.id).toBe(1);
  });

  it('пустой список не ломает выбор', () => {
    expect(pickBankPeriods([])).toEqual({ latest: null, lastFullYear: null });
  });
});
