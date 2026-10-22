import React from 'react';
import type { RowSafety } from '../services/screen.api';

/**
 * Запас прочности так, как его показывают скринер, список компаний и главная.
 *
 * Одна функция на всех: если формат разойдётся, Лукойл в списке будет «−19%»,
 * а в скринере — «−0,19», и человек решит, что это разные числа.
 */

/** Запас к опорной оценке: «+12%», «−9%»; за −100% — во сколько раз дороже. */
export const marginText = (margin: number | null): string => {
  if (margin === null) return '—';
  if (margin < -1) return `×${(1 - margin).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}`;
  const pct = Math.round(margin * 100);
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct)}%`;
};

/** Короткая подпись сигнала: в колонку шириной в два слова длинная не влезет. */
export const SIGNAL_SHORT: Record<RowSafety['signal'], string> = {
  favourable: 'дёшево',
  acceptable: 'умеренно',
  fair: 'вровень',
  expensive: 'дорого',
  bond_better: 'ОФЗ выгоднее',
  dangerous: 'опасная',
};

/** Запас прочности словами и числом — как в колонке таблицы скринера. */
export function SafetyMargin({ safety }: { safety: RowSafety | null }) {
  if (!safety) return <span className="sc-margin sc-margin--none" title="Оценка не посчитана">—</span>;
  return (
    <span className={`sc-margin ms-safety--${safety.signal}`} title={safety.reason ?? undefined}>
      <b>{marginText(safety.value_margin)}</b>
      <i>{SIGNAL_SHORT[safety.signal]}</i>
    </span>
  );
}
