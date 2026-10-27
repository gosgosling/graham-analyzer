/** Таблица компаний: формат денег и сортировка — без зависимостей, под тесты. */

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Миллионы рублей → «3,70 трлн», «559 млрд», «840 млн». */
export function money(mln: number | null): string {
  if (mln === null) return '—';
  const abs = Math.abs(mln);
  const sign = mln < 0 ? '−' : '';
  if (abs >= 1_000_000) return `${sign}${ru(abs / 1_000_000, 2)} трлн`;
  if (abs >= 10_000) return `${sign}${ru(abs / 1_000, 0)} млрд`;
  if (abs >= 1_000) return `${sign}${ru(abs / 1_000, 1)} млрд`;
  return `${sign}${ru(abs, 0)} млн`;
}


/** Сортировка по значению; пустые — всегда внизу, в какую сторону ни сортируй. */
export function sortBy<T>(rows: readonly T[], valueOf: (row: T) => number | string | null, dir: 'asc' | 'desc'): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, v: valueOf(row) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === b.v ? a.index - b.index : a.v === null ? 1 : -1;
      const cmp = typeof a.v === 'string' ? a.v.localeCompare(String(b.v), 'ru') : a.v - (b.v as number);
      return cmp * sign || a.index - b.index;
    })
    .map((x) => x.row);
}
