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

/**
 * Какой множитель Дюпона делает ROE таким, какой он есть.
 *
 * Одинаковый ROE у разных компаний собран из разного, и риск в нём разный:
 *
 *   Аренадата  маржа 30,5% × оборот 0,98 × плечо 1,66  = 49,4%
 *   Сбер       маржа 40,5% × оборот 0,06 × плечо 7,8   = 19,8%
 *   Мосбиржа   маржа 45,9% × оборот 0,01 × плечо 50,5  = 23,0%
 *
 * Первая зарабатывает прибыльностью, третья — чужими деньгами на балансе.
 * Порог красит обеих одинаково, поэтому вместе с числом нужно показывать
 * его происхождение.
 *
 * Плечо проверяется первым и по норме своей отрасли: у промышленной компании
 * рычаг 3× — уже сигнал, у банка 8–12× — обычный режим работы. Норма берётся
 * из порога D/E того же профиля (плечо = 1 + D/E), поэтому отдельных
 * констант заводить не нужно.
 */
export type RoeSource = 'leverage' | 'margin' | 'turnover';

export interface RoeSourceVerdict {
  kind: RoeSource;
  /** Одно слово для значка в углу карточки */
  label: string;
  /** Плечо выше отраслевой нормы — отдача сделана заёмными деньгами */
  leveraged: boolean;
  tip: string;
}

/** Нейтральная точка операционной части: 10% маржи при обороте 1,0 даёт ROA 10%. */
const NEUTRAL_MARGIN = 10;
const NEUTRAL_TURNOVER = 1;

export function computeRoeSource(
  dupont: DupontBreakdown,
  /**
   * Порог D/E из профиля отрасли; плечо = 1 + D/E. `null` — у отрасли порога
   * нет (банк, биржа): их обязательства это деньги клиентов, и рычаг 8-50x
   * там не перекос, а устройство бизнеса.
   */
  debtToEquityGood: number | null | undefined,
): RoeSourceVerdict | null {
  const { netMargin, assetTurnover, equityMultiplier } = dupont;
  if (equityMultiplier === null || netMargin === null || assetTurnover === null) return null;

  const hasNorm = debtToEquityGood !== null && debtToEquityGood !== undefined;
  const leverageNorm = hasNorm ? 1 + (debtToEquityGood as number) : 2;

  if (equityMultiplier > leverageNorm) {
    return {
      kind: 'leverage',
      label: 'плечо',
      leveraged: true,
      tip:
        `Отдача сделана рычагом: активы больше капитала в ${equityMultiplier.toFixed(1)} раза` +
        (hasNorm
          ? ` при отраслевой норме ${leverageNorm.toFixed(1)}. `
          : '. Для этой отрасли такой рычаг — устройство бизнеса, а не перекос: ' +
            'обязательства состоят из денег клиентов. ') +
        'Но природа показателя от этого не меняется: он растёт вместе с ' +
        'обязательствами и падает вместе с ними, то есть говорит о структуре ' +
        'баланса, а не о прибыльности.',
    };
  }

  // Плечо в норме — значит отдачу делает операционная часть. Смотрим, что
  // именно: цена (маржа) или объём (оборачиваемость).
  const marginLead = Math.log(netMargin / NEUTRAL_MARGIN);
  const turnoverLead = Math.log(assetTurnover / NEUTRAL_TURNOVER);

  if (marginLead >= turnoverLead) {
    return {
      kind: 'margin',
      label: 'маржа',
      leveraged: false,
      tip:
        `Отдачу делает прибыльность: ${netMargin.toFixed(1)}% выручки доходит до чистой ` +
        `прибыли при плече ${equityMultiplier.toFixed(2)} — заёмных денег в этом ROE нет.`,
    };
  }
  return {
    kind: 'turnover',
    label: 'оборот',
    leveraged: false,
    tip:
      `Отдачу делает оборачиваемость: активы прокручиваются ${assetTurnover.toFixed(2)} раза ` +
      `за год при марже ${netMargin.toFixed(1)}%. Прибыль берётся объёмом, а не ценой.`,
  };
}
