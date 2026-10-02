import type { FinancialReport } from '../types';

/**
 * Открытая «Отчётность»: показатели, как они стоят в отчётах. Без
 * нормализации разовых статей и прочих поправок проекта — только простая
 * арифметика, которую видно по названию строки (свободный поток = поток −
 * капзатраты, чистый долг = долг − деньги).
 *
 * Колонка LTM — последние двенадцать месяцев по последнему промежуточному
 * отчёту: нарастающий итог + прошлый год − тот же период прошлого года.
 * Балансовые строки в ней — на дату последнего отчёта.
 */

export type Field = keyof FinancialReport & string;

/** Потоковые поля: их LTM складывается из трёх отчётов. */
export const FLOW_FIELDS: Field[] = [
  'revenue', 'net_income', 'net_income_reported', 'operating_profit', 'finance_costs',
  'operating_cash_flow', 'capex', 'lease_principal', 'interest_paid', 'depreciation_amortization',
  'net_interest_income', 'fee_commission_income', 'operating_expenses', 'provisions',
  'interest_income', 'interest_expense',
] as Field[];

export interface Column {
  key: string;
  label: string;
  /** Отчёт за период — или null у колонки LTM. */
  report: FinancialReport | null;
  values: Record<string, number | null>;
  currency: string;
  isLtm: boolean;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : v == null ? null : Number(v));

export function periodLabel(r: FinancialReport): string {
  const y = r.fiscal_year;
  if (r.period_type === 'annual') return String(y);
  if (r.period_type === 'semi_annual') return `6 мес. ${y}`;
  const q = r.fiscal_quarter ?? 0;
  return q === 1 ? `3 мес. ${y}` : q === 2 ? `6 мес. ${y}` : q === 3 ? `9 мес. ${y}` : `12 мес. ${y}`;
}

function rawValues(r: FinancialReport): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const [k, v] of Object.entries(r)) {
    if (typeof v === 'number' || v === null) out[k] = num(v);
  }
  return out;
}

/** Тот же период прошлого года: полугодие к полугодию, 9 мес. к 9 мес. */
function samePeriod(reports: FinancialReport[], r: FinancialReport): FinancialReport | undefined {
  return reports.find((x) => x.fiscal_year === r.fiscal_year - 1 && x.period_type === r.period_type
    && (x.fiscal_quarter ?? null) === (r.fiscal_quarter ?? null));
}

export function ltmColumn(reports: FinancialReport[]): Column | null {
  const latest = [...reports].sort((a, b) => b.report_date.localeCompare(a.report_date))[0];
  if (!latest || latest.period_type === 'annual') return null;
  const fy = reports.find((x) => x.period_type === 'annual' && x.fiscal_year === latest.fiscal_year - 1);
  const prev = samePeriod(reports, latest);
  if (!fy || !prev) return null;
  const values = rawValues(latest);
  const a = rawValues(fy);
  const b = rawValues(prev);
  // Прошлый период — из сравнительной колонки свежего отчёта, если она есть:
  // компании пересчитывают прошлый год, и старый отчёт с ним расходится.
  // Так же считает сервер (multiplier_service.comparative_prior).
  const comp = latest.comparative ?? {};
  for (const f of FLOW_FIELDS) {
    const cur = values[f];
    const before = typeof comp[f] === 'number' ? (comp[f] as number) : b[f];
    values[f] = cur != null && a[f] != null && before != null ? cur + (a[f] as number) - before : null;
  }
  // Дивиденд на акцию — за год, а не нарастающим итогом: берём годовой.
  values.dividends_per_share = a.dividends_per_share ?? null;
  return {
    key: 'ltm', label: '12 мес.', report: null, values, currency: latest.currency || 'RUB', isLtm: true,
  };
}

/** Колонки слева направо — от старых к свежим, LTM последней. */
export function buildColumns(reports: FinancialReport[], withInterim: boolean): Column[] {
  const chosen = reports
    .filter((r) => withInterim || r.period_type === 'annual')
    .sort((a, b) => a.report_date.localeCompare(b.report_date));
  const cols: Column[] = chosen.map((r) => ({
    key: String(r.id), label: periodLabel(r), report: r, values: rawValues(r), currency: r.currency || 'RUB', isLtm: false,
  }));
  if (!withInterim) {
    const ltm = ltmColumn(reports);
    if (ltm) cols.push(ltm);
  }
  return cols;
}

/** Строки с простой арифметикой — считаются из полей колонки. */
export const derived = {
  fcf: (v: Record<string, number | null>) =>
    (v.operating_cash_flow != null && v.capex != null ? v.operating_cash_flow - Math.abs(v.capex) : null),
  netDebt: (v: Record<string, number | null>) => (v.debt != null && v.cash_and_equivalents != null ? v.debt - v.cash_and_equivalents : null),
  shares: (v: Record<string, number | null>) => v.shares_weighted_avg ?? v.shares_outstanding ?? v.shares_issued ?? null,
  eps: (v: Record<string, number | null>) => {
    const s = derived.shares(v);
    const ni = v.net_income_reported ?? v.net_income;
    return s && ni != null ? (ni * 1e6) / s : null;
  },
  dividendsTotal: (v: Record<string, number | null>) => {
    const s = v.shares_outstanding ?? v.shares_issued;
    return s && v.dividends_per_share != null ? (v.dividends_per_share * s) / 1e6 : null;
  },
  payout: (v: Record<string, number | null>) => {
    const total = derived.dividendsTotal(v);
    const ni = v.net_income_reported ?? v.net_income;
    return total != null && ni && ni > 0 ? (total / ni) * 100 : null;
  },
  marketCap: (v: Record<string, number | null>) => {
    const s = v.shares_outstanding ?? v.shares_issued;
    return s && v.price_per_share != null ? (v.price_per_share * s) / 1e6 : null;
  },
  cor: (v: Record<string, number | null>) => (v.provisions != null && v.gross_loans ? (v.provisions / v.gross_loans) * 100 : null),
  cir: (v: Record<string, number | null>) => (v.operating_expenses != null && v.revenue ? (Math.abs(v.operating_expenses) / v.revenue) * 100 : null),
  nplShare: (v: Record<string, number | null>) => (v.npl_loans != null && v.gross_loans ? (v.npl_loans / v.gross_loans) * 100 : null),
};
