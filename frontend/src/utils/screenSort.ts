import type { MarketColumn, MarketRow } from '../services/screen.api';

/**
 * Сортировка полной таблицы скринера по колонке.
 *
 * Ключ — `company`, `safety` (запас прочности), `total` (итог) или
 * `m:<метрика>` для колонки требования. Нажатие на заголовок идёт по кругу:
 * своё направление → обратное → без сортировки. «Своё» направление — то, при
 * котором сверху лучшие: у P/E и P/B это меньшие значения (порог «≤»), у
 * остальных — большие, у компании — по алфавиту.
 *
 * Пустые значения — нет данных, отрасль не та, оценка не посчитана — всегда
 * внизу, в какую сторону ни сортируй: иначе при обратном порядке таблица
 * начиналась бы с прочерков.
 */

export type SortKey = string;
export type SortDir = 'asc' | 'desc';
export interface SortState { key: SortKey; dir: SortDir }

export const metricKey = (metric: string): SortKey => `m:${metric}`;

/** Порог «≤» — чем меньше, тем лучше. */
const lowerIsBetter = (column: MarketColumn | undefined): boolean =>
  Boolean(column && (column.applied_text ?? column.book_text ?? '').trim().startsWith('≤'));

/** Банковские показатели без своей колонки (см. `swappedHead`), где лучше меньшее. */
const LOWER_IS_BETTER = new Set(['cost_of_risk_average', 'npl_ratio', 'cost_to_income_average']);

export function defaultDir(key: SortKey, columns: readonly MarketColumn[]): SortDir {
  if (key === 'company') return 'asc';
  if (key.startsWith('m:')) {
    const metric = key.slice(2);
    const column = columns.find((c) => c.metric === metric);
    if (!column) return LOWER_IS_BETTER.has(metric) ? 'asc' : 'desc';
    return lowerIsBetter(column) ? 'asc' : 'desc';
  }
  return 'desc';
}

/** Следующее состояние по нажатию на колонку `key`. */
export function nextSort(current: SortState | null, key: SortKey, columns: readonly MarketColumn[]): SortState | null {
  const first = defaultDir(key, columns);
  if (!current || current.key !== key) return { key, dir: first };
  if (current.dir === first) return { key, dir: first === 'asc' ? 'desc' : 'asc' };
  return null;
}

/** Значение строки для ключа; `null` — сортировать нечего, строка уходит вниз. */
function valueOf(row: MarketRow, key: SortKey, columns: readonly MarketColumn[]): number | string | null {
  if (key === 'company') return row.ticker;
  if (key === 'safety') return row.safety?.value_margin ?? null;
  // Итог: прошедшие все — первыми, дальше по доле пройденных.
  if (key === 'total') return row.checked ? (row.clears ? 1 : 0) + row.passed / row.checked : null;
  if (key.startsWith('m:')) {
    const metric = key.slice(2);
    const i = columns.findIndex((c) => c.metric === metric);
    // Банковский показатель своей колонки не имеет: когда таблица отфильтрована
    // до банков, сортировка по нему ищет его клетку в строке.
    const cell = i >= 0 ? row.cells[i] : row.cells.find((c) => c?.metric === metric) ?? null;
    // Банковский показатель в чужой колонке (достаточность капитала вместо
    // ликвидности) с остальными числами несравним — в конец.
    if (!cell || cell.metric !== metric || cell.value === null) return null;
    if (cell.status === 'n/a' || cell.status === 'unknown') return null;
    return cell.value;
  }
  return null;
}

export function sortRows(rows: readonly MarketRow[], state: SortState | null, columns: readonly MarketColumn[]): MarketRow[] {
  if (!state) return [...rows];
  const sign = state.dir === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: valueOf(row, state.key, columns) }))
    .sort((a, b) => {
      if (a.value === null || b.value === null) {
        if (a.value === b.value) return a.index - b.index;
        return a.value === null ? 1 : -1;
      }
      const cmp = typeof a.value === 'string'
        ? a.value.localeCompare(String(b.value), 'ru')
        : a.value - (b.value as number);
      return cmp * sign || a.index - b.index;
    })
    .map((item) => item.row);
}

/** Из адреса: `?sort=m:pe_average&dir=asc`. Битое значение — без сортировки. */
export function parseSort(key: string | null, dir: string | null): SortState | null {
  if (!key) return null;
  return { key, dir: dir === 'asc' ? 'asc' : 'desc' };
}
