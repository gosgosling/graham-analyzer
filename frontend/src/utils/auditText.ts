/** Компания, не прошедшая аудит данных: дефекты по годам и число мягких пометок. */
export interface AuditFailure {
  ticker: string;
  defects: { year: number; message: string }[];
  warnings: number;
}

/** «1 мягкая пометка», «3 мягкие пометки», «10 мягких пометок». */
export function softMarks(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'мягкая пометка';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'мягкие пометки';
  return 'мягких пометок';
}

/** Текст подсказки: почему компания не прошла аудит. */
export function auditTitle(failure: AuditFailure): string {
  const lines = failure.defects.map((d) => `${d.year}: ${d.message}`);
  const n = failure.warnings;
  const tail = n > 0 ? [`Ещё ${n} ${softMarks(n)} — на допуск не влияют.`] : [];
  return ['Не прошла аудит данных — в скринер не попадает.', ...lines, ...tail].join('\n');
}
