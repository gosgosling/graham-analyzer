/** Только для UI-бейджа «тип отрасли» — не путать с report_type в БД (bank/general). */
export type SectorDisplayKind = 'bank' | 'it' | 'general';

/**
 * Группа для подписи по строке sector из T-Invest и др.
 * Банки — первыми (чтобы не пересечься с «fintech» как IT и т.п.).
 */
export function detectSectorDisplayKind(sector?: string | null): SectorDisplayKind {
  if (!sector) return 'general';
  const raw = sector.trim();
  const s = raw.toLowerCase();

  const bankKeywords = [
    'banks', 'bank', 'banking', 'financials', 'financial_services',
    'финансы', 'банки', 'банк', 'insurance', 'страхов',
  ];
  if (
    bankKeywords.some((kw) => s === kw || s.includes(kw))
    || (s.includes('financial') && !s.includes('non-financial') && !s.includes('nonfinancial'))
  ) {
    return 'bank';
  }

  if (s === 'it') return 'it';

  const itKeywords = [
    'technology', 'technologies', 'software', 'internet', 'digital',
    'telecom', 'telecommunication', 'electronics', 'hardware',
    'semiconductor', 'cyber', 'cloud', 'saas', 'informatics',
    'информационн', 'программ', 'цифров', 'телеком', 'it_services',
  ];
  if (itKeywords.some((kw) => s.includes(kw))) return 'it';

  return 'general';
}
