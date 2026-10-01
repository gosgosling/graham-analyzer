/**
 * Отрезок, выделенный протяжкой по графику цены.
 *
 * Считается по тем точкам, что нарисованы, а не по всему ряду: окно графика
 * («1 год», «5 лет») уже отрезало часть истории, и брать соседние дни из
 * полного ряда значило бы начать отрезок раньше, чем его видно.
 *
 * Границы включаются обе. Пользователь тянет от даты до даты, и день, на
 * котором он отпустил кнопку, — часть выбранного, а не первый день после.
 */

export interface SpanPoint {
  date: string;
  price: number;
}

export interface PriceSpan<P extends SpanPoint> {
  from: P;
  to: P;
  /** Сколько торговых дней попало в отрезок, вместе с краями. */
  days: number;
  min: number;
  max: number;
  /** Изменение цены в рублях: конец минус начало. */
  delta: number;
  /** Оно же долей. `null`, когда начальная цена не положительна: делить не на
   *  что, а рисовать «+∞%» хуже, чем не рисовать ничего. */
  change: number | null;
}

/**
 * Свод по отрезку между двумя датами. Порядок дат не важен — тянуть можно в
 * любую сторону.
 *
 * `null`, когда в отрезок попала одна точка или ни одной: изменение одного дня
 * относительно самого себя — это ноль, и показывать его как результат выбора
 * значит притворяться, что выбор состоялся.
 */
export function priceSpan<P extends SpanPoint>(
  points: readonly P[],
  a: string,
  b: string,
): PriceSpan<P> | null {
  const [from, till] = a <= b ? [a, b] : [b, a];
  const inside = points.filter((p) => p.date >= from && p.date <= till);
  if (inside.length < 2) return null;

  const first = inside[0];
  const last = inside[inside.length - 1];
  const prices = inside.map((p) => p.price);

  return {
    from: first,
    to: last,
    days: inside.length,
    min: Math.min(...prices),
    max: Math.max(...prices),
    delta: last.price - first.price,
    change: first.price > 0 ? (last.price - first.price) / first.price : null,
  };
}
