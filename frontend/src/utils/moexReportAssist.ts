/**
 * MOEX отдаёт цену в ₽; поля отчёта хранятся в валюте отчёта — см. ReportForm.fetchPrice.
 */
export function moexRubPriceToReportFieldValue(
  rubPrice: number,
  currency: string | undefined | null,
  exchangeRate: number | null | undefined,
): number | null {
  const cur = (currency || 'RUB').toUpperCase();
  if (cur === 'RUB') return rubPrice;
  if (!exchangeRate || exchangeRate <= 0) return null;
  return Number((rubPrice / exchangeRate).toFixed(4));
}
