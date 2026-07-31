/**
 * Форматирование денежных величин, которые хранятся в миллионах.
 *
 * Инвариант проекта: все денежные поля отчёта лежат в миллионах валюты отчёта.
 * На экране их показывают в млн / млрд / трлн, и эта функция была скопирована
 * в четыре файла (в CompanyDetail — дважды). Копии успели разойтись: где-то
 * валюта подставлялась из отчёта, где-то был захардкожен рубль, а параметр
 * `showCur` в одной из копий не использовался нигде.
 *
 * @param value    значение в миллионах
 * @param currency единица после масштаба: '₽', 'USD', код валюты отчёта.
 *                 `null` — только масштаб, без валюты (единица указана
 *                 в заголовке колонки).
 */
export function formatMln(
  value: number | null | undefined,
  currency: string | null = '₽',
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';

  const unit = currency ? ` ${currency}` : '';
  const abs = Math.abs(value);

  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} трлн${unit}`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)} млрд${unit}`;
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн${unit}`;
}
