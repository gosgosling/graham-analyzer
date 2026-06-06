import type { Company } from '../types';

/** MOEX: тикер привилегированных акций обычно оканчивается на «P» (BANEP, TRNFP). */
export function tickerLooksPreferred(ticker: string): boolean {
  const t = ticker.trim().toUpperCase();
  return t.length >= 2 && t.endsWith('P');
}

export function nameLooksPreferred(name: string): boolean {
  return /привилегирован/i.test(name);
}

/** По тикеру/названию инструмент может быть префовым (отдельный тикер на бирже). */
export function canBePreferredInstrument(company: Pick<Company, 'ticker' | 'name'>): boolean {
  return tickerLooksPreferred(company.ticker ?? '') || nameLooksPreferred(company.name ?? '');
}

/** Флаг «префы» включён у тикера, который префами быть не может (ошибка в БД). */
export function isMisclassifiedAsPreferred(
  company: Pick<Company, 'ticker' | 'name' | 'is_preferred_share'>,
): boolean {
  return !!company.is_preferred_share && !canBePreferredInstrument(company);
}
