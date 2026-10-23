/**
 * Сырьё, которое можно наложить на график цены компании.
 *
 * Список по тикерам, а не по отрасли: «металлургия» — это и золото Полюса, и
 * алмазы АЛРОСА, и никель Норникеля, и по сектору их не развести. Ряды
 * приходят с бэкенда (/market/commodity/<ключ>), помесячно.
 */
export type CommodityKey = 'gas_eu' | 'lng_asia' | 'urea' | 'dap' | 'potash' | 'gold' | 'palladium' | 'nickel' | 'copper' | 'diamonds';

/** Подпись кнопки под графиком — короткая, рядом с «P/E» и «Нефть». */
export const COMMODITY_BUTTON: Record<CommodityKey, string> = {
  gas_eu: 'Газ',
  lng_asia: 'СПГ',
  urea: 'Карбамид',
  dap: 'DAP',
  potash: 'Калий',
  gold: 'Золото',
  palladium: 'Палладий',
  nickel: 'Никель',
  copper: 'Медь',
  diamonds: 'Алмазы',
};

export const COMMODITIES_BY_TICKER: Record<string, CommodityKey[]> = {
  // Удобрения: ФосАгро — фосфорные (DAP) и азотные (карбамид), Акрон — азотные.
  PHOR: ['dap', 'urea'],
  AKRN: ['urea', 'dap'],
  ALRS: ['diamonds'],
  GAZP: ['gas_eu'],
  NVTK: ['lng_asia', 'gas_eu'],
  PLZL: ['gold'],
  UGLD: ['gold'],
  SELG: ['gold'],
  // Норникель: палладий — первый по выручке, никель и медь — следом.
  GMKN: ['palladium', 'nickel', 'copper'],
};

export const isCommodity = (key: string | null | undefined): key is CommodityKey =>
  !!key && key in COMMODITY_BUTTON;
