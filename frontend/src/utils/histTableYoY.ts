import type { CurrentMultipliers, MultiplierRecord } from '../types';

export type YoYLevel = 'good' | 'bad' | 'neutral';
export type YoYDirection = 'higher_better' | 'lower_better';
export type PfcfColMode = 'pfcf' | 'yield';

export interface YoYDisplay {
  text: string;
  level: YoYLevel;
  tip?: string;
}

export interface HistRowSnapshot {
  price_used: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  ltm_dividends_per_share: number | null;
  price_to_fcf: number | null;
  ltm_fcf: number | null;
  fcf_to_net_income: number | null;
  net_debt_to_fcf: number | null;
  net_debt: number | null;
  ltm_revenue: number | null;
  ltm_net_income: number | null;
  equity: number | null;
}

export interface HistRowYoY {
  price: YoYDisplay;
  cap: YoYDisplay;
  pe: YoYDisplay;
  pb: YoYDisplay;
  roe: YoYDisplay;
  de: YoYDisplay;
  cr: YoYDisplay;
  div: YoYDisplay;
  pfcf: YoYDisplay;
  fcfNi: YoYDisplay;
  ndFcf: YoYDisplay;
  netDebt: YoYDisplay;
  fcf: YoYDisplay;
  revenue: YoYDisplay;
  profit: YoYDisplay;
}

export const YOY_NA: YoYDisplay = {
  text: '—',
  level: 'neutral',
  tip: 'Нет данных за прошлый год для сравнения',
};

function pfcfToFcfYield(pfcf: number | null): number | null {
  if (pfcf === null || pfcf <= 0) return null;
  return Math.round((100 / pfcf) * 100) / 100;
}

function computeNetDebtToFcf(
  ratio: number | null | undefined,
  netDebt: number | null | undefined,
  fcf: number | null | undefined,
): number | null {
  if (ratio != null) return ratio;
  if (netDebt == null || fcf == null || fcf === 0) return null;
  return Math.round((netDebt / fcf) * 100) / 100;
}

function changeLevel(delta: number, direction: YoYDirection): YoYLevel {
  if (Math.abs(delta) < 0.05) return 'neutral';
  const improved = direction === 'higher_better' ? delta > 0 : delta < 0;
  return improved ? 'good' : 'bad';
}

function formatPctDelta(delta: number, direction: YoYDirection, label: string): YoYDisplay {
  const sign = delta > 0 ? '+' : '';
  const text = `${sign}${delta.toFixed(1)}%`;
  return {
    text,
    level: changeLevel(delta, direction),
    tip: `${label}: ${text} к прошлому году`,
  };
}

function formatPpDelta(delta: number, direction: YoYDirection, label: string): YoYDisplay {
  const sign = delta > 0 ? '+' : '';
  const text = `${sign}${delta.toFixed(1)} п.п.`;
  return {
    text,
    level: changeLevel(delta, direction),
    tip: `${label}: ${text} к прошлому году`,
  };
}

function pctChange(current: number | null, previous: number | null): number | null {
  if (current === null || previous === null) return null;
  if (previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function ppChange(current: number | null, previous: number | null): number | null {
  if (current === null || previous === null) return null;
  return current - previous;
}

function metricPct(
  current: number | null,
  previous: number | null,
  direction: YoYDirection,
  label: string,
): YoYDisplay {
  const delta = pctChange(current, previous);
  if (delta === null) return YOY_NA;
  return formatPctDelta(delta, direction, label);
}

function metricPp(
  current: number | null,
  previous: number | null,
  direction: YoYDirection,
  label: string,
): YoYDisplay {
  const delta = ppChange(current, previous);
  if (delta === null) return YOY_NA;
  return formatPpDelta(delta, direction, label);
}

function profitChange(current: number | null, previous: number | null): YoYDisplay {
  if (current === null || previous === null) return YOY_NA;

  if (previous < 0 && current > 0) {
    return {
      text: 'в прибыль',
      level: 'good',
      tip: 'Компания вышла из убытка в прибыль',
    };
  }
  if (previous > 0 && current < 0) {
    return {
      text: 'в убыток',
      level: 'bad',
      tip: 'Компания ушла из прибыли в убыток',
    };
  }
  if (previous === 0) {
    if (current === 0) return { text: '0%', level: 'neutral', tip: 'Прибыль без изменений' };
    return formatPctDelta(current > 0 ? 100 : -100, 'higher_better', 'Прибыль');
  }

  return metricPct(current, previous, 'higher_better', 'Прибыль');
}

function divDpsChange(current: number | null, previous: number | null): YoYDisplay {
  if (current === null || previous === null) return YOY_NA;
  if (previous === 0) {
    if (current === 0) {
      return { text: '0%', level: 'neutral', tip: 'Дивиденды не выплачивались' };
    }
    return {
      text: 'нов.',
      level: 'good',
      tip: 'Дивиденды на акцию появились относительно прошлого года',
    };
  }
  return metricPct(current, previous, 'higher_better', 'Дивиденды на акцию');
}

function pfcfColumnChange(
  current: HistRowSnapshot,
  previous: HistRowSnapshot,
  pfcfMode: PfcfColMode,
): YoYDisplay {
  if (pfcfMode === 'yield') {
    const cur = pfcfToFcfYield(current.price_to_fcf);
    const prev = pfcfToFcfYield(previous.price_to_fcf);
    return metricPp(cur, prev, 'higher_better', 'FCF yield');
  }
  return metricPct(current.price_to_fcf, previous.price_to_fcf, 'lower_better', 'P/FCF');
}

export function computeHistRowYoY(
  current: HistRowSnapshot,
  previous: HistRowSnapshot,
  pfcfMode: PfcfColMode,
): HistRowYoY {
  const curNdFcf = computeNetDebtToFcf(current.net_debt_to_fcf, current.net_debt, current.ltm_fcf);
  const prevNdFcf = computeNetDebtToFcf(previous.net_debt_to_fcf, previous.net_debt, previous.ltm_fcf);

  return {
    price: metricPct(current.price_used, previous.price_used, 'higher_better', 'Цена'),
    cap: metricPct(current.market_cap, previous.market_cap, 'higher_better', 'Капитализация'),
    pe: metricPct(current.pe_ratio, previous.pe_ratio, 'lower_better', 'P/E'),
    pb: metricPct(current.pb_ratio, previous.pb_ratio, 'lower_better', 'P/B'),
    roe: metricPp(current.roe, previous.roe, 'higher_better', 'ROE'),
    de: metricPct(current.debt_to_equity, previous.debt_to_equity, 'lower_better', 'D/E'),
    cr: metricPp(current.current_ratio, previous.current_ratio, 'higher_better', 'Current Ratio'),
    div: divDpsChange(current.ltm_dividends_per_share, previous.ltm_dividends_per_share),
    pfcf: pfcfColumnChange(current, previous, pfcfMode),
    fcfNi: metricPp(current.fcf_to_net_income, previous.fcf_to_net_income, 'higher_better', 'FCF/NI'),
    ndFcf: metricPct(curNdFcf, prevNdFcf, 'lower_better', 'Net Debt/FCF'),
    netDebt: metricPct(current.net_debt, previous.net_debt, 'lower_better', 'Net Debt'),
    fcf: metricPct(current.ltm_fcf, previous.ltm_fcf, 'higher_better', 'FCF'),
    revenue: metricPct(current.ltm_revenue, previous.ltm_revenue, 'higher_better', 'Выручка'),
    profit: profitChange(current.ltm_net_income, previous.ltm_net_income),
  };
}

export function snapshotFromRecord(r: MultiplierRecord): HistRowSnapshot {
  return {
    price_used: r.price_used,
    market_cap: r.market_cap,
    pe_ratio: r.pe_ratio,
    pb_ratio: r.pb_ratio,
    roe: r.roe,
    debt_to_equity: r.debt_to_equity,
    current_ratio: r.current_ratio,
    ltm_dividends_per_share: r.ltm_dividends_per_share,
    price_to_fcf: r.price_to_fcf,
    ltm_fcf: r.ltm_fcf,
    fcf_to_net_income: r.fcf_to_net_income,
    net_debt_to_fcf: r.net_debt_to_fcf,
    net_debt: r.net_debt,
    ltm_revenue: r.ltm_revenue,
    ltm_net_income: r.ltm_net_income,
    equity: r.equity,
  };
}

export function snapshotFromCurrent(r: CurrentMultipliers): HistRowSnapshot {
  return {
    price_used: r.price_used,
    market_cap: r.market_cap,
    pe_ratio: r.pe_ratio,
    pb_ratio: r.pb_ratio,
    roe: r.roe,
    debt_to_equity: r.debt_to_equity,
    current_ratio: r.current_ratio,
    ltm_dividends_per_share: r.ltm_dividends_per_share,
    price_to_fcf: r.price_to_fcf,
    ltm_fcf: r.ltm_fcf,
    fcf_to_net_income: r.fcf_to_net_income,
    net_debt_to_fcf: r.net_debt_to_fcf,
    net_debt: r.net_debt,
    ltm_revenue: r.ltm_revenue,
    ltm_net_income: r.ltm_net_income,
    equity: r.equity,
  };
}
