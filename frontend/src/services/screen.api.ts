import { api } from './companies.api';

/**
 * Экран Грэма: паспорт компании и сводная таблица по рынку.
 *
 * Величины и пороги приходят порознь намеренно. Ось знает, сколько получилось;
 * порог знает, с чем сравнивать, и приходит сразу в двух видах — применённом и
 * книжном. Скрыть отраслевую поправку значит превратить экран в гадание:
 * провал уже нельзя отличить от чужой мерки.
 */

/** Статус оси. Три последних — не провал, и складывать их с ним нельзя. */
export type ScreenStatus = 'pass' | 'fail' | 'n/a' | 'unknown';

/** Одна подметрика оси вместе с рядом по годам. */
export interface AxisMetric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  /** Знаменатель там, где величина — «столько-то из стольких-то». */
  of: number | null;
  average: number | null;
  series: [number, number][];
  /** Годы, испортившие подметрику: убыточные, с отрицательным капиталом. */
  flagged: number[];
  note: string | null;
  /** На когда величина: «LTM» или год. */
  asof: string | null;
  /**
   * Сторона нуля, на которой величина. Не порог: убыток есть убыток при любой
   * мерке, а отрицательный чистый долг — это чистая денежная позиция. Где знак
   * ничего не значит (ликвидность, P/E), пометки нет.
   */
  tone: 'good' | 'bad' | null;
}

export interface ScreenAxis {
  key: string;
  label: string;
  lead: string | null;
  measurable: boolean;
  note: string | null;
  metrics: AxisMetric[];
}

/** Одна ось против одного требования — с обоими порогами напоказ. */
export interface Verdict {
  axis: string;
  label: string;
  metric: string;
  metric_label: string;
  value: number | null;
  unit: string;
  of: number | null;
  status: ScreenStatus;
  /** Порог, который применили — с отраслевой поправкой. */
  applied: number | null;
  /** Что стоит в книге до поправки. */
  book: number | null;
  adjusted: boolean;
  text: string;
  book_text: string;
  source: string;
  /** Порог наш, а не книжный. */
  ours: boolean;
  note: string | null;
  /**
   * Оговорка к засчитанному критерию: он посчитан, но опираться на него в
   * одиночку нельзя. Так помечен пятилетний тест роста — его окно на
   * российских данных неизбежно накрывает 2020 и 2022 годы.
   */
  caveat: string | null;
  /**
   * Величина есть, но верить ей нельзя — знаменатель не отражает бизнес.
   * Отличается от «нет данных» тем, что мы знаем, чего не хватает: не строки
   * в базе, а осмысленного знаменателя. Читателю разница существенна.
   */
  distorted: boolean;
}

export interface ScreenResult {
  ticker: string;
  standard: string;
  standard_label: string;
  profile: { key: string; label: string };
  passed: number;
  checked: number;
  total: number;
  complete: boolean;
  clears: boolean;
  failed: string[];
  unknown: string[];
  verdicts: Verdict[];
}

export interface SectorBand {
  good: number | null;
  warn: number | null;
  higher_is_better: boolean;
  hint: string;
  applicable: boolean;
  note: string | null;
  tooltip_lines: string[];
}

export interface SectorProfileOut {
  key: string;
  label: string;
  summary: string;
  book_value_reliable: boolean;
  lease_heavy: boolean;
  bands: Record<string, SectorBand>;
}

export interface PassportOut {
  company: { id: number; ticker: string; name: string; sector: string | null };
  profile: SectorProfileOut;
  order: string[];
  axes: Record<string, ScreenAxis>;
  screens: Record<string, ScreenResult>;
}

export interface MarketColumn {
  metric: string;
  label: string;
  axis: string;
  axis_label: string;
  book: number | null;
  book_text: string;
  source: string;
  ours: boolean;
}

export interface MarketRow {
  id: number;
  ticker: string;
  name: string;
  profile: string;
  profile_label: string;
  passed: number;
  checked: number;
  clears: boolean;
  complete: boolean;
  cells: (Verdict | null)[];
}

export interface MarketScreenOut {
  standard: string;
  standard_label: string;
  columns: MarketColumn[];
  rows: MarketRow[];
  summary: {
    total: number;
    cleared: number;
    fails: Record<string, number>;
  };
}

export interface StandardsOut {
  standards: { key: string; label: string }[];
  default: string;
}

export const fetchStandards = async (): Promise<StandardsOut> =>
  (await api.get<StandardsOut>('/screen/standards')).data;

export const fetchPassport = async (companyId: number): Promise<PassportOut> =>
  (await api.get<PassportOut>(`/screen/company/${companyId}`)).data;

export const fetchMarketScreen = async (
  standard: string,
  allCompanies = false,
): Promise<MarketScreenOut> =>
  (
    await api.get<MarketScreenOut>('/screen/market', {
      params: { standard, all: allCompanies },
    })
  ).data;
