/**
 * Применение отраслевого профиля к значениям метрик.
 *
 * Профиль приходит с бэкенда (`/multipliers/current` → `sector_profile`) —
 * он единственный источник истины по порогам. Локальный GRAHAM_FALLBACK нужен
 * только для случая, когда актуальные мультипликаторы ещё не загружены
 * (историческая таблица рисуется раньше) или запрос завершился ошибкой.
 */
import { SectorMetricKey, SectorProfile, SectorProfileBand } from '../types';

export type MetricLevel = 'good' | 'warn' | 'bad' | 'neutral' | 'loss';

function band(
  good: number | null,
  warn: number | null,
  higherIsBetter: boolean,
  hint: string,
  applicable = true,
): SectorProfileBand {
  return {
    good,
    warn,
    higher_is_better: higherIsBetter,
    hint,
    applicable,
    note: null,
    tooltip_lines: [],
  };
}

/** Классические пороги Грэма — используются, пока профиль не пришёл с бэкенда. */
export const GRAHAM_FALLBACK: SectorProfile = {
  key: 'industrial',
  label: 'Промышленность / прочее',
  summary: 'Классические пороги Грэма без отраслевых поправок.',
  book_value_reliable: true,
  lease_heavy: false,
  bands: {
    pe: band(15, 25, false, '≤ 15 — хорошо'),
    pb: band(1.5, 3.0, false, '≤ 1.5 — хорошо'),
    de: band(0.5, 1.0, false, '≤ 0.5 — хорошо'),
    cr: band(2.0, 1.5, true, '≥ 2.0 — норма по Грэму'),
    roe: band(15, 10, true, '≥ 15% — хорошо'),
    dy: band(6, 3, true, '≥ 6% — хорошо'),
  },
};

export function getBand(
  profile: SectorProfile | null | undefined,
  metric: SectorMetricKey,
): SectorProfileBand {
  return (profile ?? GRAHAM_FALLBACK).bands[metric] ?? GRAHAM_FALLBACK.bands[metric];
}

/**
 * Уровень значения в рамках профиля.
 * Метрика, неприменимая к отрасли (например Current Ratio у банка),
 * возвращает 'neutral' — её показывают, но не окрашивают.
 */
export function levelFor(
  profile: SectorProfile | null | undefined,
  metric: SectorMetricKey,
  value: number | null | undefined,
): MetricLevel {
  const b = getBand(profile, metric);
  if (value === null || value === undefined) return 'neutral';
  if (!b.applicable || b.good === null || b.warn === null) return 'neutral';
  if (b.higher_is_better) {
    if (value >= b.good) return 'good';
    return value >= b.warn ? 'warn' : 'bad';
  }
  if (value <= b.good) return 'good';
  return value <= b.warn ? 'warn' : 'bad';
}

/** Текст порога для подписи под значением в карточке. */
export function hintFor(
  profile: SectorProfile | null | undefined,
  metric: SectorMetricKey,
): string {
  return getBand(profile, metric).hint;
}

/**
 * Строки для rich-тултипа: собственные строки метрики, а если их нет —
 * пороги профиля и пояснение, почему они отличаются от грэмовских.
 */
export function tooltipLinesFor(
  profile: SectorProfile | null | undefined,
  metric: SectorMetricKey,
): string[] {
  const b = getBand(profile, metric);
  if (b.tooltip_lines.length > 0) return b.tooltip_lines;
  return b.note ? [b.note] : [];
}
