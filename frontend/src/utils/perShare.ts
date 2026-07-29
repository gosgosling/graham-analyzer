/**
 * Форматирование величин «на акцию»: цены и дивиденда.
 *
 * У копеечных бумаг (ТГК-1 — 0,004365 ₽, ТГК-2 — 0,0042 ₽) округление до двух
 * знаков превращает цену в ноль, а вместе с ней обнуляет капитализацию и P/E
 * на экране. Округление здесь всегда играет против нас: чем дешевле бумага,
 * тем больше знаков нужно, чтобы значение осталось значащим.
 *
 * Число знаков подбирается по масштабу: рубли — два знака, копейки и доли
 * копейки — до шести.
 */

function decimalsFor(value: number): number {
  const abs = Math.abs(value);
  if (abs === 0) return 2;
  if (abs >= 1) return 2;
  if (abs >= 0.01) return 4;
  return 6;
}

/** Число на акцию → строка без единицы измерения. */
export function formatPerShare(value: number | null | undefined, dash = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash;
  return value.toLocaleString('ru-RU', {
    maximumFractionDigits: decimalsFor(value),
  });
}

/** То же с валютой: «0,004365 ₽». */
export function formatPerShareWithCurrency(
  value: number | null | undefined,
  currency: string = 'RUB',
  dash = '—',
): string {
  const formatted = formatPerShare(value, dash);
  if (formatted === dash) return dash;
  const suffix = currency.toUpperCase() === 'RUB' ? '₽' : currency;
  return `${formatted} ${suffix}`;
}
