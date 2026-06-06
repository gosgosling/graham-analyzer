/** Опциональный отток в формуле FCF: null/undefined → 0. */
function outflow(val: number | null | undefined): number {
  if (val == null) return 0;
  return val;
}

/**
 * FCF = OCF − CAPEX − тело аренды − % по аренде − тело долга (долг. ЦБ).
 * OCF и CAPEX обязательны; остальные поля опциональны (млн валюты, оттоки — положит.).
 */
export function computeFcf(
  operatingCashFlow: number | null | undefined,
  capex: number | null | undefined,
  leasePrincipal?: number | null,
  leaseInterest?: number | null,
  debtPrincipal?: number | null,
): number | null {
  if (operatingCashFlow == null || capex == null) return null;
  const totalOut =
    capex +
    outflow(leasePrincipal) +
    outflow(leaseInterest) +
    outflow(debtPrincipal);
  return Math.round((operatingCashFlow - totalOut) * 1000) / 1000;
}
