/**
 * Размытие и прибыль на акцию в таблице истории.
 *
 * Допэмиссия не двигает ни одну из старых колонок: выручка, прибыль, капитал
 * и мультипликаторы остаются прежними. Единственное, что о ней сообщает, —
 * пара «EPS + число акций», поэтому её поведение проверяется отдельно.
 */
import { computeHistRowYoY, type HistRowSnapshot } from './histTableYoY';

const EMPTY: HistRowSnapshot = {
  price_used: null, market_cap: null, pe_ratio: null, pb_ratio: null,
  pb_tangible: null, goodwill_to_assets: null, roe: null,
  debt_to_equity: null, current_ratio: null, ltm_dividends_per_share: null,
  price_to_fcf: null, ltm_fcf: null, ltm_capex: null, fcf_to_net_income: null,
  net_debt_to_fcf: null, net_debt: null, ltm_revenue: null,
  ltm_net_income: null, eps: null, shares_used: null, equity: null,
  total_assets: null, dividend_yield: null, dividend_yield_regular: null,
  ltm_special_dividends_per_share: null,
};

const snap = (o: Partial<HistRowSnapshot>): HistRowSnapshot => ({ ...EMPTY, ...o });

describe('размытие доли акционера', () => {
  it('рост числа акций считается ухудшением', () => {
    // Аренадата 2025: 200,0 → 232,6 млн под оплату покупки дочерней компании
    const yoy = computeHistRowYoY(
      snap({ shares_used: 232_558_140 }),
      snap({ shares_used: 200_000_000 }),
      'pfcf',
    );

    expect(yoy.shares.level).toBe('bad');
    expect(yoy.shares.text).toContain('16');
  });

  it('выкуп акций считается улучшением', () => {
    const yoy = computeHistRowYoY(
      snap({ shares_used: 900_000_000 }),
      snap({ shares_used: 1_000_000_000 }),
      'pfcf',
    );

    expect(yoy.shares.level).toBe('good');
  });

  it('EPS отстаёт от прибыли ровно на размытие', () => {
    // прибыль +37,7%, акций +16,3% → EPS растёт заметно медленнее
    const yoy = computeHistRowYoY(
      snap({ ltm_net_income: 2_670.035, eps: 11.48, shares_used: 232_558_140 }),
      snap({ ltm_net_income: 1_938.422, eps: 9.69, shares_used: 200_000_000 }),
      'pfcf',
    );

    const profit = parseFloat(yoy.profit.text.replace(',', '.'));
    const eps = parseFloat(yoy.eps.text.replace(',', '.'));

    expect(profit).toBeGreaterThan(eps);
    expect(yoy.profit.level).toBe('good');
    expect(yoy.eps.level).toBe('good');
  });

  it('падение EPS при растущей прибыли красится плохим', () => {
    // Размытие съело весь рост: прибыль вверх, доля акционера вниз
    const yoy = computeHistRowYoY(
      snap({ ltm_net_income: 1_100, eps: 5.5, shares_used: 200_000_000 }),
      snap({ ltm_net_income: 1_000, eps: 10.0, shares_used: 100_000_000 }),
      'pfcf',
    );

    expect(yoy.profit.level).toBe('good');
    expect(yoy.eps.level).toBe('bad');
    expect(yoy.shares.level).toBe('bad');
  });

  it('без данных об акциях изменение не выдумывается', () => {
    const yoy = computeHistRowYoY(snap({ eps: 10 }), snap({}), 'pfcf');

    expect(yoy.shares.level).toBe('neutral');
    expect(yoy.eps.level).toBe('neutral');
  });
});
