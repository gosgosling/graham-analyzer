/**
 * Разбор мультипликаторов отчёта.
 *
 * Формулы — зеркало `calc_multipliers.py`, поэтому числа в примерах взяты
 * круглыми: 100 ₽ × 1 млрд акций = 100 млрд ₽ капитализации при прибыли
 * 10 млрд и капитале 50 млрд.
 */
import type { FinancialReport } from '../types';
import { explainReportMultipliers, marketCapMln } from './reportMultipliers';

function report(overrides: Partial<FinancialReport> = {}): FinancialReport {
  return {
    id: 1,
    company_id: 1,
    period_type: 'annual',
    fiscal_year: 2024,
    accounting_standard: 'IFRS',
    consolidated: true,
    source: 'manual',
    report_date: '2024-12-31',
    report_type: 'general',
    currency: 'RUB',
    price_per_share: 100,
    shares_outstanding: 1_000_000_000,
    net_income: 10_000,
    equity: 50_000,
    total_liabilities: 25_000,
    current_assets: 30_000,
    current_liabilities: 15_000,
    revenue: 80_000,
    dividends_paid: true,
    dividends_per_share: 6,
    ...overrides,
  } as FinancialReport;
}

function metric(r: FinancialReport, key: string) {
  return explainReportMultipliers(r).find((m) => m.key === key)!;
}

describe('marketCapMln', () => {
  it('цена × акции в млн ₽', () => {
    expect(marketCapMln(report())).toBe(100_000); // 100 ₽ × 1 млрд = 100 млрд
  });

  it('без цены или акций капитализации нет', () => {
    expect(marketCapMln(report({ price_per_share: null }))).toBeNull();
    expect(marketCapMln(report({ shares_outstanding: null }))).toBeNull();
  });
});

describe('explainReportMultipliers', () => {
  it('считает как бэкенд и показывает обе части дроби', () => {
    const pe = metric(report(), 'pe');

    expect(pe.value).toBe(10); // 100 млрд / 10 млрд
    expect(pe.formula).toBe('Капитализация ÷ Чистая прибыль');
    expect(pe.substitution).toBe('100.00 млрд ₽ ÷ 10.00 млрд ₽');

    expect(metric(report(), 'pb').value).toBe(2);      // 100 / 50
    expect(metric(report(), 'roe').value).toBe(20);    // 10 / 50
    expect(metric(report(), 'de').value).toBe(0.5);    // 25 / 50
    expect(metric(report(), 'cr').value).toBe(2);      // 30 / 15
    expect(metric(report(), 'dy').value).toBe(6);      // 6 ₽ / 100 ₽
  });

  it('называет, какого поля не хватает, вместо пустого прочерка', () => {
    const pb = metric(report({ equity: null }), 'pb');

    expect(pb.value).toBeNull();
    expect(pb.missing).toContain('капитал');
  });

  it('отрицательный капитал — не «ноль», а отсутствие смысла', () => {
    const pb = metric(report({ equity: -1_000 }), 'pb');

    expect(pb.value).toBeNull();
    expect(pb.missing).toContain('отрицателен');
  });

  it('убыток отключает P/E', () => {
    expect(metric(report({ net_income: -5_000 }), 'pe').value).toBeNull();
  });

  it('без выплат дивидендная доходность не считается', () => {
    const dy = metric(report({ dividends_paid: false }), 'dy');

    expect(dy.value).toBeNull();
    expect(dy.missing).toContain('не выплачивались');
  });

  it('у банка вместо D/E и CR — Cost/Income', () => {
    const bank = report({ report_type: 'bank', operating_expenses: 24_000, revenue: 80_000 });
    const keys = explainReportMultipliers(bank).map((m) => m.key);

    expect(keys).not.toContain('de');
    expect(keys).not.toContain('cr');
    expect(metric(bank, 'cir').value).toBe(30); // 24 / 80
  });

  it('валютный отчёт считается по рублёвым величинам', () => {
    // Отчёт в долларах: бэкенд отдаёт *_rub, и числитель со знаменателем
    // должны браться из одного представления, иначе P/E разъедется в 90 раз.
    const usd = report({
      currency: 'USD',
      price_per_share: 1.1,
      price_per_share_rub: 100,
      net_income: 110,
      net_income_rub: 10_000,
      equity: 550,
      equity_rub: 50_000,
    });

    expect(metric(usd, 'pe').value).toBe(10);
    expect(metric(usd, 'pb').value).toBe(2);
  });
});
