/**
 * Выбор отчётного периода для банковского блока.
 *
 * Свежий промежуточный отчёт и последний полный год отвечают на разные
 * вопросы. Промежуточный — «как банк идёт сейчас», но его потоковые
 * показатели приведены к году множителем, а значит содержат допущение, что
 * оставшиеся месяцы будут такими же. Полный год — «чем всё кончилось», без
 * допущений, но он может отставать на полгода. Поэтому в панели переключатель,
 * а не выбор за пользователя.
 *
 * Длина периода повторяет backend/app/services/analysis/periods.py: там она
 * решает, на что умножать поток, здесь — что писать в заголовке. Разойдутся —
 * пользователь увидит «6 месяцев» рядом с годовыми числами.
 */
import type { FinancialReport } from '../types';

const MONTHS_BY_PERIOD: Record<string, number> = {
  annual: 12,
  semi_annual: 6,
};

/** Сколько месяцев покрывает отчёт. Квартальные — накопительные с начала года. */
export function periodMonths(report: FinancialReport): number {
  const key = String(report.period_type ?? '').toLowerCase();
  const known = MONTHS_BY_PERIOD[key];
  if (known) return known;

  if (key === 'quarterly') {
    const quarter = report.fiscal_quarter;
    if (typeof quarter === 'number' && quarter >= 1 && quarter <= 4) {
      return quarter * 3;
    }
  }
  return 12;
}

/** Полные двенадцать месяцев — включая отчёт «за 4 квартала». */
export function isFullYear(report: FinancialReport): boolean {
  return periodMonths(report) === 12;
}

/** Подпись периода в заголовке: «2025 год» или «6 месяцев 2026». */
export function periodLabel(report: FinancialReport): string {
  const months = periodMonths(report);
  return months === 12
    ? `${report.fiscal_year} год`
    : `${months} месяцев ${report.fiscal_year}`;
}

export interface BankPeriods {
  /** Самый свежий отчёт с банковскими показателями — любой длины. */
  latest: FinancialReport | null;
  /** Последний отчёт за полные двенадцать месяцев. */
  lastFullYear: FinancialReport | null;
}

/**
 * Два периода для панели. Отбираются только отчёты с посчитанными
 * банковскими показателями: у компании может быть годовой отчёт до того, как
 * её пометили банком, и он даст пустую панель вместо данных.
 */
export function pickBankPeriods(reports: FinancialReport[]): BankPeriods {
  const withMetrics = reports
    .filter((r) => r.bank_metrics)
    .sort((a, b) => String(b.report_date).localeCompare(String(a.report_date)));

  return {
    latest: withMetrics[0] ?? null,
    lastFullYear: withMetrics.find(isFullYear) ?? null,
  };
}
