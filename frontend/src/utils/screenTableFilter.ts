import type { MarketRow } from '../services/screen.api';

/**
 * Поиск и отбор по отрасли в полной таблице скринера.
 *
 * Отрасль — это отраслевой профиль строки (`profile`), а не сектор из
 * T-Invest: по профилю экран подбирает пороги, и фильтр по нему показывает
 * ровно тех, кого мерили одной меркой.
 */

/** Нормализация для поиска: регистр и «ё» не должны мешать найти «Сбер». */
export function normalize(text: string): string {
  return text.toLowerCase().replace(/ё/g, 'е').trim();
}

/** Отрасли таблицы с числом компаний — по убыванию, затем по названию. */
export function industries(rows: readonly MarketRow[]): { key: string; label: string; count: number }[] {
  const seen = new Map<string, { key: string; label: string; count: number }>();
  for (const row of rows) {
    const hit = seen.get(row.profile);
    if (hit) hit.count += 1;
    else seen.set(row.profile, { key: row.profile, label: row.profile_label, count: 1 });
  }
  return Array.from(seen.values()).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'ru'));
}

/** Строки, подходящие под запрос и отрасль. Пустой запрос и `''` — без отбора. */
export function filterRows(rows: readonly MarketRow[], query: string, industry: string): MarketRow[] {
  const q = normalize(query);
  return rows.filter((row) =>
    (!industry || row.profile === industry)
    && (!q || normalize(row.ticker).includes(q) || normalize(row.name).includes(q)));
}
