/** Опциональный отток в формуле FCF: null/undefined → 0. */
function outflow(val: number | null | undefined): number {
  if (val == null) return 0;
  return val;
}

/**
 * FCF = OCF − CAPEX − аренда − проценты уплаченные (financing).
 * Тело долга (кредиты/облигации) в формулу не входит.
 * OCF и CAPEX обязательны; остальные опциональны (млн валюты, оттоки — положит.).
 */
export function computeFcf(
  operatingCashFlow: number | null | undefined,
  capex: number | null | undefined,
  leasePrincipal?: number | null,
  leaseInterest?: number | null,
  interestPaid?: number | null,
  _debtPrincipal?: number | null,
): number | null {
  if (operatingCashFlow == null || capex == null) return null;
  const totalOut =
    capex +
    outflow(leasePrincipal) +
    outflow(leaseInterest) +
    outflow(interestPaid);
  return Math.round((operatingCashFlow - totalOut) * 1000) / 1000;
}
