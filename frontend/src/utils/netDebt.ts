/** Чистый долг = Долг − Наличность (млн валюты отчёта). */
export function computeNetDebt(
  debt: number | null | undefined,
  cashAndEquivalents: number | null | undefined,
): number | null {
  if (debt == null || cashAndEquivalents == null) return null;
  return Math.round((debt - cashAndEquivalents) * 1000) / 1000;
}
