import type { FinancialReport, FinancialReportCreate } from '../types';

function sliceDate(d: unknown): string {
  if (d == null || d === '') return '';
  const s = typeof d === 'string' ? d : String(d);
  return s.slice(0, 10);
}

/** Полное тело для PUT /reports/{id} из текущего ответа API. */
export function financialReportToCreatePayload(
  r: FinancialReport,
  companyId: number,
): FinancialReportCreate {
  const pt = String(r.period_type).toLowerCase() as FinancialReportCreate['period_type'];
  const std = String(r.accounting_standard || 'IFRS').toUpperCase() as FinancialReportCreate['accounting_standard'];
  const src = String(r.source || 'manual').toLowerCase() as FinancialReportCreate['source'];

  return {
    company_id: companyId,
    period_type: pt,
    fiscal_year: r.fiscal_year,
    fiscal_quarter: pt === 'annual' ? null : r.fiscal_quarter ?? null,
    accounting_standard: std,
    consolidated: r.consolidated ?? true,
    source: src,
    report_date: sliceDate(r.report_date),
    filing_date: r.filing_date ? sliceDate(r.filing_date) : null,
    price_per_share: r.price_per_share ?? null,
    price_at_filing: r.price_at_filing ?? null,
    shares_outstanding: r.shares_outstanding ?? null,
    revenue: r.revenue ?? null,
    net_income: r.net_income ?? null,
    net_income_reported: r.net_income_reported ?? null,
    total_assets: r.total_assets ?? null,
    current_assets: r.current_assets ?? null,
    total_liabilities: r.total_liabilities ?? null,
    current_liabilities: r.current_liabilities ?? null,
    equity: r.equity ?? null,
    dividends_per_share: r.dividends_per_share ?? null,
    dividends_paid: r.dividends_paid ?? false,
    net_interest_income: r.net_interest_income ?? null,
    fee_commission_income: r.fee_commission_income ?? null,
    operating_expenses: r.operating_expenses ?? null,
    provisions: r.provisions ?? null,
    operating_cash_flow: r.operating_cash_flow ?? null,
    capex: r.capex ?? null,
    depreciation_amortization: r.depreciation_amortization ?? null,
    currency: r.currency || 'RUB',
    exchange_rate: r.exchange_rate ?? null,
    auto_extracted: r.auto_extracted ?? false,
    verified_by_analyst: r.verified_by_analyst ?? true,
    extraction_notes: r.extraction_notes ?? null,
    extraction_model: r.extraction_model ?? null,
    source_pdf_path: r.source_pdf_path ?? null,
  };
}
