/**
 * Формулы, продублированные на фронтенде: FCF, чистый долг, выбор акций.
 *
 * Эти функции — зеркало бэкенда (`fcf.py`, `net_debt.py`, `share_counts.py`).
 * Дубль сделан осознанно: матрица отчётов пересчитывает значения на клиенте до
 * сохранения, чтобы аналитик видел результат сразу. Но у дубля есть цена — две
 * копии формулы расходятся молча, и на экране появляется одно число, а в базе
 * другое. Тесты держат обе копии на одних и тех же примерах: числа здесь взяты
 * из backend/tests/test_fcf_and_shares.py.
 */
import { computeFcf } from './fcf';
import { computeNetDebt } from './netDebt';
import { computeCirculationShares, resolveSharesForMultipliers } from './shareCounts';

describe('computeFcf', () => {
  test('OCF минус CAPEX, аренда и уплаченные проценты', () => {
    expect(computeFcf(15000, 5000, 2000, 500, 1000, 9999)).toBe(6500);
    expect(computeFcf(15000, 5000, 2000, 500, null, 9999)).toBe(7500);
  });

  test('проценты в financing вычитаются (Мечел-паттерн)', () => {
    expect(computeFcf(46352, 10760, 5711, null, 43348)).toBe(-13467);
  });

  test('необязательные оттоки трактуются как нули', () => {
    expect(computeFcf(15000, 5000)).toBe(10000);
  });

  test('тело долга в формулу не входит', () => {
    expect(computeFcf(15000, 5000, null, null, null, 9999)).toBe(10000);
  });

  test('без OCF или CAPEX результата нет — это не ноль', () => {
    expect(computeFcf(null, 5000)).toBeNull();
    expect(computeFcf(15000, null)).toBeNull();
  });

  test('FCF может быть отрицательным', () => {
    expect(computeFcf(3000, 8000)).toBe(-5000);
  });
});

describe('computeNetDebt', () => {
  test('долг минус денежные средства', () => {
    expect(computeNetDebt(20000, 5000)).toBe(15000);
  });

  test('денег больше долга — чистый долг отрицательный', () => {
    expect(computeNetDebt(1000, 9000)).toBe(-8000);
  });

  test('пустое поле не превращается в ноль', () => {
    expect(computeNetDebt(20000, null)).toBeNull();
    expect(computeNetDebt(null, 5000)).toBeNull();
  });
});

describe('акции для капитализации', () => {
  test('явное количество в обращении важнее вычисленного', () => {
    const shares = computeCirculationShares({
      shares_outstanding: 900,
      shares_issued: 1000,
      treasury_shares: 50,
    });

    expect(shares).toBe(900);
  });

  test('без явного — размещённые минус казначейские', () => {
    expect(computeCirculationShares({ shares_issued: 1000, treasury_shares: 150 })).toBe(850);
  });

  test('казначейских больше размещённых — не уходим в минус', () => {
    expect(computeCirculationShares({ shares_issued: 100, treasury_shares: 150 })).toBe(0);
  });

  test('размещённые без казначейских не считаются обращением', () => {
    expect(computeCirculationShares({ shares_issued: 1000 })).toBeNull();
  });

  test('приоритет для мультипликаторов: обращение → средневзвешенное → размещённые', () => {
    expect(
      resolveSharesForMultipliers({ shares_outstanding: 900, shares_weighted_avg: 950 }),
    ).toBe(900);
    expect(
      resolveSharesForMultipliers({ shares_issued: 1000, shares_weighted_avg: 950 }),
    ).toBe(950);
    expect(resolveSharesForMultipliers({ shares_issued: 1000 })).toBe(1000);
    expect(resolveSharesForMultipliers({})).toBeNull();
  });
});
