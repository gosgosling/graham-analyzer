/**
 * Разложение ROE и определение того, чем вызвано его изменение.
 *
 * ROE сам по себе — плохой сигнал: он растёт и когда бизнес зарабатывает
 * больше, и когда просто уменьшается знаменатель. Выкуп акций у нерезидентов
 * или крупная разовая выплата схлопывают собственный капитал, и график ROE
 * рисует бодрый рост в тот самый год, когда прибыль упала.
 *
 * Здесь два инструмента:
 *   1. Формула Дюпона — из чего складывается уровень ROE.
 *   2. Атрибуция изменения — прибылью или капиталом вызван сдвиг.
 */

export interface DupontBreakdown {
  /** Чистая маржа, % = NI / Выручка */
  netMargin: number | null;
  /** Оборачиваемость активов = Выручка / Активы */
  assetTurnover: number | null;
  /** Финансовый рычаг = Активы / Капитал */
  equityMultiplier: number | null;
  /** ROE, восстановленный из трёх множителей, % — для сверки с прямым расчётом */
  impliedRoe: number | null;
}

export interface DupontInput {
  netIncome: number | null | undefined;
  revenue: number | null | undefined;
  totalAssets: number | null | undefined;
  equity: number | null | undefined;
}

function ratio(numerator: number | null | undefined, denominator: number | null | undefined): number | null {
  if (numerator === null || numerator === undefined) return null;
  if (denominator === null || denominator === undefined || denominator === 0) return null;
  return numerator / denominator;
}

export function computeDupont({ netIncome, revenue, totalAssets, equity }: DupontInput): DupontBreakdown {
  const marginRatio = ratio(netIncome, revenue);
  const assetTurnover = ratio(revenue, totalAssets);
  const equityMultiplier = equity !== null && equity !== undefined && equity > 0
    ? ratio(totalAssets, equity)
    : null;

  const impliedRoe =
    marginRatio !== null && assetTurnover !== null && equityMultiplier !== null
      ? marginRatio * assetTurnover * equityMultiplier * 100
      : null;

  return {
    netMargin: marginRatio !== null ? marginRatio * 100 : null,
    assetTurnover,
    equityMultiplier,
    impliedRoe,
  };
}

export type RoeDriverKind =
  | 'none'            // изменение незначительное
  | 'profit'          // движение объясняется прибылью
  | 'equity_shrink'   // ROE вырос из-за сокращения капитала
  | 'equity_growth'   // ROE упал из-за роста капитала
  | 'unknown';        // недостаточно данных

export interface RoeDriver {
  kind: RoeDriverKind;
  /** Изменение ROE, п.п. */
  roeDeltaPp: number | null;
  /** Изменение прибыли, % */
  profitChangePct: number | null;
  /** Изменение капитала, % */
  equityChangePct: number | null;
  /** Короткая метка для бейджа рядом с ROE */
  label: string | null;
  /** Развёрнутое пояснение для тултипа */
  tip: string | null;
  /** Нужно ли предупредить пользователя (жёлтый бейдж) */
  misleading: boolean;
}

export interface RoePeriod {
  roe: number | null | undefined;
  netIncome: number | null | undefined;
  equity: number | null | undefined;
}

const ROE_NOISE_PP = 2;

const UNKNOWN_DRIVER: RoeDriver = {
  kind: 'unknown',
  roeDeltaPp: null,
  profitChangePct: null,
  equityChangePct: null,
  label: null,
  tip: null,
  misleading: false,
};

function pctChange(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function fmtPct(v: number | null): string {
  if (v === null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(1)}%`;
}

/**
 * Определяет, чем вызвано изменение ROE между двумя периодами.
 *
 * Опирается на то, что для ROE = NI / E относительное изменение
 * раскладывается как %ΔROE ≈ %ΔNI − %ΔE. Если вклад знаменателя перевешивает
 * вклад прибыли, движение ROE говорит о структуре капитала, а не о бизнесе.
 */
export function computeRoeDriver(
  current: RoePeriod,
  previous: RoePeriod | null | undefined,
): RoeDriver {
  if (!previous) return UNKNOWN_DRIVER;

  const curRoe = current.roe ?? null;
  const prevRoe = previous.roe ?? null;
  const curNi = current.netIncome ?? null;
  const prevNi = previous.netIncome ?? null;
  const curEq = current.equity ?? null;
  const prevEq = previous.equity ?? null;

  if (curRoe === null || prevRoe === null) return UNKNOWN_DRIVER;
  if (curNi === null || prevNi === null || curEq === null || prevEq === null) return UNKNOWN_DRIVER;
  // Отрицательные капитал или прибыль ломают интерпретацию относительных изменений
  if (prevEq <= 0 || curEq <= 0 || prevNi <= 0) return UNKNOWN_DRIVER;

  const roeDeltaPp = curRoe - prevRoe;
  const profitChangePct = pctChange(curNi, prevNi);
  const equityChangePct = pctChange(curEq, prevEq);

  if (profitChangePct === null || equityChangePct === null) return UNKNOWN_DRIVER;

  const base = {
    roeDeltaPp,
    profitChangePct,
    equityChangePct,
  };

  if (Math.abs(roeDeltaPp) < ROE_NOISE_PP) {
    return { ...base, kind: 'none', label: null, tip: null, misleading: false };
  }

  // Вклад знаменателя в изменение ROE: сокращение капитала даёт положительный вклад
  const equityEffect = -equityChangePct;
  const profitDominates = Math.abs(profitChangePct) >= Math.abs(equityEffect);

  if (roeDeltaPp > 0) {
    if (!profitDominates && equityEffect > 0) {
      return {
        ...base,
        kind: 'equity_shrink',
        label: 'капитал ↓',
        tip:
          `ROE вырос на ${roeDeltaPp.toFixed(1)} п.п., но прибыль изменилась на ` +
          `${fmtPct(profitChangePct)}, а собственный капитал — на ${fmtPct(equityChangePct)}. ` +
          'Рост объясняется сокращением капитала (выкуп акций, крупная выплата, убыток ' +
          'прошлых лет), а не улучшением бизнеса.',
        misleading: true,
      };
    }
    return {
      ...base,
      kind: 'profit',
      label: null,
      tip:
        `ROE вырос на ${roeDeltaPp.toFixed(1)} п.п.: прибыль ${fmtPct(profitChangePct)}, ` +
        `капитал ${fmtPct(equityChangePct)}.`,
      misleading: false,
    };
  }

  if (!profitDominates && equityEffect < 0) {
    return {
      ...base,
      kind: 'equity_growth',
      label: 'капитал ↑',
      tip:
        `ROE снизился на ${Math.abs(roeDeltaPp).toFixed(1)} п.п. при изменении прибыли ` +
        `${fmtPct(profitChangePct)}. Причина — рост собственного капитала на ` +
        `${fmtPct(equityChangePct)} (допэмиссия или нераспределённая прибыль), а не спад бизнеса.`,
      misleading: false,
    };
  }

  return {
    ...base,
    kind: 'profit',
    label: null,
    tip:
      `ROE снизился на ${Math.abs(roeDeltaPp).toFixed(1)} п.п.: прибыль ` +
      `${fmtPct(profitChangePct)}, капитал ${fmtPct(equityChangePct)}.`,
    misleading: false,
  };
}

/** Строки для тултипа карточки ROE: уровень (Дюпон) + причина изменения. */
export function roeTooltipLines(dupont: DupontBreakdown, driver: RoeDriver): string[] {
  const lines: string[] = [];
  if (dupont.netMargin !== null) {
    lines.push(`Маржа: ${dupont.netMargin.toFixed(1)}% (прибыль / выручка)`);
  }
  if (dupont.assetTurnover !== null) {
    lines.push(`Оборачиваемость: ${dupont.assetTurnover.toFixed(2)}× (выручка / активы)`);
  }
  if (dupont.equityMultiplier !== null) {
    lines.push(`Рычаг: ${dupont.equityMultiplier.toFixed(1)}× (активы / капитал)`);
  }
  if (driver.tip) {
    if (lines.length > 0) lines.push('');
    lines.push(driver.tip);
  }
  return lines;
}
