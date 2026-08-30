/**
 * Разложение ROE по Дюпону и объяснение его изменения.
 *
 * Единственная финансовая логика, которая живёт только на фронтенде: на бэкенде
 * есть сам ROE, но не его декомпозиция. Значит здесь тесты — единственная
 * проверка формул, и именно этот случай («дорогая компания с хорошим ROE за
 * счёт сжатия капитала») отобран как один из кейсов для доклада.
 */
import { computeDupont, computeRoeDriver, computeRoeSource } from './roeBreakdown';

describe('computeDupont', () => {
  it('раскладывает ROE на маржу, оборачиваемость и рычаг', () => {
    const d = computeDupont({
      netIncome: 10_000,
      revenue: 50_000,
      totalAssets: 100_000,
      equity: 50_000,
    });

    expect(d.netMargin).toBeCloseTo(20);        // 10 000 / 50 000
    expect(d.assetTurnover).toBeCloseTo(0.5);   // 50 000 / 100 000
    expect(d.equityMultiplier).toBeCloseTo(2);  // 100 000 / 50 000
    // 0.2 × 0.5 × 2 = 0.2 → 20% — сходится с прямым NI / E
    expect(d.impliedRoe).toBeCloseTo(20);
  });

  it('нулевой или отрицательный капитал не даёт рычага', () => {
    expect(computeDupont({ netIncome: 10, revenue: 100, totalAssets: 200, equity: 0 }).equityMultiplier).toBeNull();
    expect(computeDupont({ netIncome: 10, revenue: 100, totalAssets: 200, equity: -50 }).equityMultiplier).toBeNull();
  });

  it('без части данных возвращает null, а не ноль', () => {
    const d = computeDupont({ netIncome: null, revenue: 100, totalAssets: 200, equity: 50 });

    expect(d.netMargin).toBeNull();
    expect(d.impliedRoe).toBeNull();
    expect(d.assetTurnover).toBeCloseTo(0.5);
  });
});

describe('computeRoeDriver', () => {
  const prev = { roe: 10, netIncome: 1_000, equity: 10_000 };

  it('рост ROE при сжатии капитала помечается как вводящий в заблуждение', () => {
    // Прибыль почти не изменилась, капитал упал вдвое — ROE вырос «на бумаге».
    const driver = computeRoeDriver({ roe: 20, netIncome: 1_020, equity: 5_100 }, prev);

    expect(driver.kind).toBe('equity_shrink');
    expect(driver.misleading).toBe(true);
    expect(driver.label).toBe('капитал ↓');
  });

  it('рост ROE за счёт прибыли — нормальный случай', () => {
    const driver = computeRoeDriver({ roe: 20, netIncome: 2_000, equity: 10_000 }, prev);

    expect(driver.kind).toBe('profit');
    expect(driver.misleading).toBe(false);
  });

  it('падение ROE из-за роста капитала объясняется знаменателем', () => {
    const driver = computeRoeDriver({ roe: 5, netIncome: 1_010, equity: 20_200 }, prev);

    expect(driver.kind).toBe('equity_growth');
    expect(driver.misleading).toBe(false);
  });

  it('изменение меньше двух пунктов — шум', () => {
    expect(computeRoeDriver({ roe: 11, netIncome: 1_100, equity: 10_000 }, prev).kind).toBe('none');
  });

  it('убыток или отрицательный капитал делают разложение неприменимым', () => {
    expect(computeRoeDriver({ roe: 20, netIncome: 1_000, equity: 5_000 }, { roe: -5, netIncome: -500, equity: 10_000 }).kind)
      .toBe('unknown');
    expect(computeRoeDriver({ roe: 20, netIncome: 1_000, equity: -100 }, prev).kind).toBe('unknown');
  });

  it('без предыдущего периода сравнивать не с чем', () => {
    expect(computeRoeDriver({ roe: 20, netIncome: 1_000, equity: 5_000 }, null).kind).toBe('unknown');
  });
});

describe('computeRoeSource — откуда взялся ROE', () => {
  // Три реальные компании с сопоставимой маржой и совершенно разным
  // происхождением отдачи. Порог красит их одинаково, значок — нет.
  const arenadata = { netIncome: 2670, revenue: 8750, totalAssets: 8960, equity: 5405 };
  const sber = { netIncome: 1580, revenue: 3900, totalAssets: 62000, equity: 8000 };
  const moex = { netIncome: 59.2, revenue: 129.0, totalAssets: 13027.8, equity: 258.0 };

  it('прибыльность при низком плече — «маржа»', () => {
    const v = computeRoeSource(computeDupont(arenadata), 1.0);

    expect(v?.kind).toBe('margin');
    expect(v?.leveraged).toBe(false);
  });

  it('банковское плечо 7,8× при норме D/E 1,0 — «плечо»', () => {
    const v = computeRoeSource(computeDupont(sber), 1.0);

    expect(v?.kind).toBe('leverage');
    expect(v?.leveraged).toBe(true);
  });

  it('то же плечо в пределах банковской нормы перестаёт быть перекосом', () => {
    // У профиля банка порог D/E выше, значит рычаг 7,8× — обычный режим
    const v = computeRoeSource(computeDupont(sber), 10.0);

    expect(v?.kind).not.toBe('leverage');
  });

  it('чужие деньги на балансе биржи — «плечо» при любом пороге', () => {
    const v = computeRoeSource(computeDupont(moex), 10.0);

    expect(v?.kind).toBe('leverage');
    expect(v?.tip).toContain('50');
  });

  it('низкая маржа при быстром обороте — «оборот»', () => {
    // Ретейл: 2% маржи, активы прокручиваются трижды за год
    const v = computeRoeSource(
      computeDupont({ netIncome: 2, revenue: 100, totalAssets: 33, equity: 20 }),
      1.0,
    );

    expect(v?.kind).toBe('turnover');
  });

  it('без порога отрасли плечо сверяется с двойкой', () => {
    const v = computeRoeSource(computeDupont(arenadata), null);

    expect(v?.kind).toBe('margin'); // 1,66 < 2 — рычага нет
  });

  it('нет капитала — вердикта нет', () => {
    const v = computeRoeSource(
      computeDupont({ netIncome: 10, revenue: 100, totalAssets: 200, equity: 0 }),
      1.0,
    );

    expect(v).toBeNull();
  });
});
