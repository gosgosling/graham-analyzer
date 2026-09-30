/**
 * Подсветка выделенного отрезка и свод по нему.
 *
 * Две крошечные части, подписанные на `priceSpanStore`. Живут отдельно от
 * графика намеренно: перерисовать два `div` стоит доли миллисекунды, а
 * перерисовать сам график — около четырёхсот. Пока протяжка идёт, recharts
 * не трогается вовсе.
 *
 * Подсветка рисуется наложением, а не `ReferenceArea`, по той же причине:
 * элемент внутри графика заставил бы его перерисоваться.
 */
import React, { useSyncExternalStore } from 'react';

import { formatPerShare } from '../utils/perShare';
import { priceSpan, type SpanPoint } from '../utils/priceSpan';
import type { SpanStore } from './priceSpanStore';

const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];

/** Дата выделенного края: «27 марта 2026». Год обязателен — иначе две весны
 *  разных лет в подписи неразличимы. */
export const humanDate = (iso: string) => {
  const [y, m, d] = iso.split('-');
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`;
};

const rub = (value: number) => formatPerShare(value);

function useSpan(store: SpanStore) {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

/** Полупрозрачная полоса поверх поля графика. */
export const SpanBand: React.FC<{ store: SpanStore; top: number; bottom: number }> = (
  { store, top, bottom },
) => {
  const live = useSpan(store);
  if (!live || live.fromX === live.toX) return null;
  const left = Math.min(live.fromX, live.toX);
  const width = Math.abs(live.toX - live.fromX);
  return (
    <div
      className="pc-band"
      style={{ left, width, top, bottom }}
      aria-hidden
    />
  );
};

/** Строка свода под графиком. */
export const SpanSummary: React.FC<{ store: SpanStore; points: readonly SpanPoint[] }> = (
  { store, points },
) => {
  const live = useSpan(store);
  const span = live ? priceSpan(points, live.fromDate, live.toDate) : null;
  if (!span) return null;

  const up = span.delta >= 0;
  return (
    <div className="pc-span">
      <span>{humanDate(span.from.date)} <b>{rub(span.from.price)} ₽</b></span>
      <span className="pc-span-arrow">→</span>
      <span>{humanDate(span.to.date)} <b>{rub(span.to.price)} ₽</b></span>
      <span className={up ? 'pc-up' : 'pc-down'}>
        <b>
          {up ? '+' : '−'}{rub(Math.abs(span.delta))} ₽
          {span.change !== null && ` · ${up ? '+' : '−'}${
            (Math.abs(span.change) * 100).toLocaleString('ru-RU', {
              minimumFractionDigits: 2, maximumFractionDigits: 2,
            })}%`}
        </b>
      </span>
      <span className="pc-span-aside">
        {span.days} торг. дн. · в отрезке {rub(span.min)} — {rub(span.max)} ₽
      </span>
    </div>
  );
};
