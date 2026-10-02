/**
 * Песочница оценки: множитель гл. 32 по допущениям читателя.
 * Чистая арифметика, без React, — чтобы её можно было проверить тестом.
 */

/** Допущения, которые читатель может подвинуть. Доли — в процентах. */
export interface Sandbox {
  normal: number;
  riskFree: number;
  premium: number;
  penalty: number;
  growth: number;
  payout: number;
}

/** Тот же потолок, что на сервере (`company_valuation.MULTIPLE_CAP`). */
const MULTIPLE_CAP = 8;

/**
 * Множитель гл. 32 по допущениям песочницы — тем же путём, что на сервере:
 * выплата ÷ (K − g), справедливый без надбавки, опорный с ней; за потолком
 * верхний замирает на восьми, а надбавка сохраняется в доходностях. Иначе
 * при входе в песочницу опорная не совпала бы с нашей.
 */
export function sandboxMultiple(
  v: Sandbox,
  epv: boolean,
): { fair: number | null; reference: number | null; capped: boolean; problem: string | null } {
  const payout = epv ? 1 : v.payout / 100;
  const growth = epv ? 0 : v.growth / 100;
  const k = (v.riskFree + v.premium) / 100;
  const kPenalty = k + v.penalty / 100;
  if (payout <= 0) return { fair: null, reference: null, capped: false, problem: 'без выплат формула не работает' };
  if (k - growth <= 0) {
    return { fair: null, reference: null, capped: false, problem: 'рост не меньше требуемой доходности — формула теряет смысл' };
  }
  const top = payout / (k - growth);
  const bottom = payout / (kPenalty - growth);
  if (top <= MULTIPLE_CAP) return { fair: top, reference: bottom, capped: false, problem: null };
  const gap = Math.max(0, (kPenalty - k) / payout);
  return { fair: MULTIPLE_CAP, reference: 1 / (1 / MULTIPLE_CAP + gap), capped: true, problem: null };
}
