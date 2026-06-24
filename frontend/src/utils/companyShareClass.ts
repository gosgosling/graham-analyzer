import type { Company } from '../types';

/** Обыкновенные тикеры MOEX, оканчивающиеся на «P» (не префы). */
const ORDINARY_TICKERS_ENDING_IN_P = new Set(['GAZP']);

/** MOEX: префы — отдельный тикер *P, обычно ≥5 символов (BANEP, TRNFP). */
export function tickerLooksPreferred(ticker: string): boolean {
  const t = ticker.trim().toUpperCase();
  if (ORDINARY_TICKERS_ENDING_IN_P.has(t)) return false;
  return t.length >= 5 && t.endsWith('P');
}

export function nameLooksPreferred(name: string): boolean {
  return /привилегирован/i.test(name);
}

/** По тикеру/названию инструмент может быть префовым (отдельный тикер на бирже). */
export function canBePreferredInstrument(company: Pick<Company, 'ticker' | 'name'>): boolean {
  if (nameLooksPreferred(company.name ?? '')) return true;
  return tickerLooksPreferred(company.ticker ?? '');
}

/** Флаг «префы» включён у тикера, который префами быть не может (ошибка в БД). */
export function isMisclassifiedAsPreferred(
  company: Pick<Company, 'ticker' | 'name' | 'is_preferred_share'>,
): boolean {
  return !!company.is_preferred_share && !canBePreferredInstrument(company);
}
