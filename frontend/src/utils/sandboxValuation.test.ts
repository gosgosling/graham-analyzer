import { sandboxMultiple } from './sandboxValuation';

const tatneft = { normal: 145.57, riskFree: 16, premium: 5, penalty: 1, growth: 9, payout: 52.68 };

test('песочница с нашими допущениями повторяет нашу оценку', () => {
  const m = sandboxMultiple(tatneft, false);
  expect(m.reference).toBeCloseTo(4.05, 2);
  expect(m.fair).toBeCloseTo(4.39, 2);
  expect(tatneft.normal * (m.reference ?? 0)).toBeCloseTo(589.6, 0);
});

test('за потолком верхний множитель замирает на восьми, надбавка остаётся', () => {
  const m = sandboxMultiple({ ...tatneft, riskFree: 6 }, false);
  expect(m.capped).toBe(true);
  expect(m.fair).toBe(8);
  expect(m.reference).toBeLessThan(8);
  // Ниже ставка — опорная не дешевеет.
  const lower = sandboxMultiple({ ...tatneft, riskFree: 5 }, false);
  expect(lower.reference).toBeCloseTo(m.reference ?? 0, 6);
});

test('рост не меньше требуемой доходности — формулы нет', () => {
  const m = sandboxMultiple({ ...tatneft, growth: 21 }, false);
  expect(m.reference).toBeNull();
  expect(m.problem).toMatch(/рост/);
});

test('EPV: множитель — единица на требуемую доходность', () => {
  const m = sandboxMultiple({ ...tatneft, penalty: 0 }, true);
  expect(m.fair).toBeCloseTo(1 / 0.21, 4);
});
