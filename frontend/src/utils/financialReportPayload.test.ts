/**
 * Общий конструктор тела отчёта.
 *
 * Список полей раньше жил в двух местах — в форме отчёта и в матрице — и уже
 * разошёлся: в форме не было флагов верификации, в матрице — разовых
 * дивидендов. Тест держит полноту списка: пропущенное поле означает, что
 * значение уедет на бэкенд как `undefined` и молча заменится дефолтом.
 */
import { emptyFinancialReportPayload } from './financialReportPayload';

// Поля, которых не хватало в разошедшихся копиях, — за ними следим отдельно.
const PREVIOUSLY_MISSED = [
  'special_dividends_per_share',
  'special_dividends_note',
  'auto_extracted',
  'verified_by_analyst',
  'extraction_notes',
  'extraction_model',
  'source_pdf_path',
] as const;

describe('emptyFinancialReportPayload', () => {
  it('заполняет все показатели null, а не пропускает их', () => {
    const payload = emptyFinancialReportPayload(42);

    for (const key of ['revenue', 'net_income', 'equity', 'total_liabilities', 'capex']) {
      expect(payload).toHaveProperty(key, null);
    }
    expect(payload.company_id).toBe(42);
  });

  it('содержит поля, которых не хватало в прежних копиях', () => {
    const payload = emptyFinancialReportPayload(1) as unknown as Record<string, unknown>;

    for (const key of PREVIOUSLY_MISSED) {
      expect(Object.prototype.hasOwnProperty.call(payload, key)).toBe(true);
    }
  });

  it('служебные значения — как при ручном вводе', () => {
    const payload = emptyFinancialReportPayload(1);

    expect(payload.auto_extracted).toBe(false);
    expect(payload.verified_by_analyst).toBe(true);
    expect(payload.source).toBe('manual');
    expect(payload.currency).toBe('RUB');
    expect(payload.dividends_paid).toBe(false);
  });

  it('overrides перекрывают дефолты — форма задаёт квартал, матрица дату', () => {
    const quarterly = emptyFinancialReportPayload(1, {
      period_type: 'quarterly',
      fiscal_year: 2024,
      fiscal_quarter: 4,
    });
    expect(quarterly.period_type).toBe('quarterly');
    expect(quarterly.fiscal_quarter).toBe(4);
    expect(quarterly.fiscal_year).toBe(2024);

    const annual = emptyFinancialReportPayload(1, { fiscal_year: 2025, report_date: '2025-12-31' });
    expect(annual.period_type).toBe('annual');
    expect(annual.fiscal_quarter).toBeNull();
    expect(annual.report_date).toBe('2025-12-31');
  });
});
