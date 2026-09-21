/**
 * Размытие и прибыль на акцию в таблице истории.
 *
 * Допэмиссия не двигает ни одну из старых колонок: выручка, прибыль, капитал
 * и мультипликаторы остаются прежними. Единственное, что о ней сообщает, —
 * пара «EPS + число акций», поэтому её поведение проверяется отдельно.
 */
import {
  computeHistRowYoY,
  fcfPerShare,
  fcfToEquityPct,
  type HistRowSnapshot,
} from './histTableYoY';

const EMPTY: HistRowSnapshot = {
  price_used: null, market_cap: null, pe_ratio: null, pb_ratio: null,
  pb_tangible: null, goodwill_to_assets: null, intangibles_to_equity: null, roe: null,
  debt_to_equity: null, current_ratio: null, ltm_dividends_per_share: null,
  price_to_fcf: null, ltm_fcf: null, ltm_capex: null, fcf_to_net_income: null,
  net_debt_to_fcf: null, net_debt: null, ltm_revenue: null,
  ltm_net_income: null, eps: null, shares_used: null, shares_split_factor: null, equity: null,
  key_rate: null, roe_spread: null,
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

  it('дробление не считается размытием', () => {
    // Т-Технологии, сплит 10:1 от 17.04.2026. В отчёте за 2025 год стоит
    // 257,4 млн акций и коэффициент 10 (столько дроблений прошло ПОСЛЕ него),
    // в полугодии 2026 — уже 2 549,9 млн и коэффициент 1. Доля владельца при
    // дроблении не меняется, и прирост должен быть около нуля.
    const yoy = computeHistRowYoY(
      snap({ shares_used: 2_549_948_000, shares_split_factor: 1 }),
      snap({ shares_used: 257_393_950, shares_split_factor: 10 }),
      'pfcf',
    );

    expect(yoy.shares.level).not.toBe('bad');
    expect(yoy.shares.text).not.toContain('890');
  });

  it('допэмиссия после дробления видна как размытие', () => {
    // Тот же масштаб, но акций стало вдвое больше — это уже не сплит.
    const yoy = computeHistRowYoY(
      snap({ shares_used: 5_147_879_000, shares_split_factor: 1 }),
      snap({ shares_used: 257_393_950, shares_split_factor: 10 }),
      'pfcf',
    );

    expect(yoy.shares.level).toBe('bad');
    expect(yoy.shares.text).toContain('100');
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


describe('прибыль против денег', () => {
  it('поток к капиталу считается от той же базы, что и ROE', () => {
    // ФосАгро LTM: поток −15 086 млн при капитале 264 000 млн.
    const row = snap({ ltm_fcf: -15_086, equity: 264_000 });

    expect(fcfToEquityPct(row)).toBeCloseTo(-5.71, 1);
  });

  it('поток на акцию — в той же шкале, что EPS', () => {
    // Прибыль 192 414 млн на 257,4 млн акций даёт EPS 747,55 ₽.
    // Поток 24 610 млн на тех же акциях — 95,6 ₽ на акцию.
    const row = snap({ ltm_fcf: 24_610, shares_used: 257_393_950 });

    expect(fcfPerShare(row)).toBeCloseTo(95.61, 1);
  });

  it('без потока или капитала величины нет, а не нуля', () => {
    expect(fcfToEquityPct(snap({ ltm_fcf: 100, equity: null }))).toBeNull();
    expect(fcfToEquityPct(snap({ ltm_fcf: 100, equity: 0 }))).toBeNull();
    expect(fcfPerShare(snap({ ltm_fcf: 100, shares_used: null }))).toBeNull();
  });

  it('прирост считается по той величине, что на виду', () => {
    const cur = snap({ roe: 20, ltm_fcf: 1_000, equity: 10_000 });
    const prev = snap({ roe: 10, ltm_fcf: 500, equity: 10_000 });

    // режим прибыли: ROE вырос на 10 п.п.
    expect(computeHistRowYoY(cur, prev, 'pfcf').roe.text).toContain('10.0');
    // режим потока: 10% против 5% — рост на 5 п.п., а не на 10
    expect(computeHistRowYoY(cur, prev, 'pfcf', 'fcf').roe.text).toContain('5.0');
  });
});
