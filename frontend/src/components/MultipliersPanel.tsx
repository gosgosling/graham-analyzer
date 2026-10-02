import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getCompanyCurrentMultipliers,
  getCompanyMultipliersHistory,
  getLtmBankMetrics,
  getSectorProfiles,
  refreshCompanyMultipliers,
  updateCompanySectorProfile,
  updateCompanyType,
} from '../services';
import { MultiplierRecord, CurrentMultipliers, Company, SectorProfile, BankMetrics, FinancialReport, CompanyType } from '../types';
import SharesCapHover from './SharesCapHover';
import DownloadLinks from './DownloadLinks';
import { downloadSheet, parseCellText, type ExportFormat, type Sheet } from '../utils/tableExport';
import { formatPerShare } from '../utils/perShare';
import { formatApiErrorMessage } from '../utils/apiErrors';
import {
  computeBankYoY,
  computeHistRowYoY,
  fcfPerShare,
  fcfToEquityPct,
  metricPct,
  metricPp,
  snapshotFromCurrent,
  snapshotFromRecord,
  YOY_NA,
  type HistRowSnapshot,
  type HistRowYoY,
  type PerShareColMode,
  type RoeColMode,
  type YoYDisplay,
} from '../utils/histTableYoY';
import {
  GRAHAM_FALLBACK,
  getBand,
  hintFor,
  levelFor,
  tooltipLinesFor,
  type MetricLevel,
} from '../utils/sectorProfile';
import {
  computeDupont,
  computeRoeSource,
  computeRoeDriver,
  roeTooltipLines,
  type RoeDriver,
  type RoeSourceVerdict,
} from '../utils/roeBreakdown';
import {
  fetchValuationHistory,
  fetchValuationSummary,
  getCompanySeries,
  type CompanySeriesOut,
  type ValuationHistoryOut,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { useAdmin } from '../hooks/useAdmin';
import './MultipliersPanel.css';






/**
 * Сколько лет истории показывать в свёрнутом виде.
 *
 * Полная таблица у ЛУКОЙЛа — восемнадцать строк, и она отодвигает пороги
 * Грэма на экран вниз. Семь — не round number: это окно нормализации, по
 * которому считается оценка, то есть ровно те годы, из которых она и сложена.
 * Остальное остаётся в разворачивании, а не пропадает.
 */
const HIST_COLLAPSED_YEARS = 7;

/** Откуда прибыль в P/E мультипликаторов — и почему P/E оценки может отличаться. */
const PE_BASIS_TIP =
  'P/E здесь — от прибыли без разовых статей, если аналитик их выделил; иначе она совпадает с отчётной. Оценка стоимости считает от прибыли как в отчёте, поэтому P/E там может отличаться.';

/** «ещё 1 год», «ещё 3 года», «ещё 11 лет» — по правилам русского счёта. */
const plural = (n: number, one: string, few: string, many: string) => {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  const mod10 = n % 10;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
};

// Пороги P/E, P/B, D/E, CR, ROE и дивдоходности задаёт отраслевой профиль,
// который приходит с бэкенда вместе с мультипликаторами: у продуктового
// ритейлера Current Ratio 0.7 — норма, у банка D/E вообще не считается.
// Пороги, не зависящие от отрасли (P/FCF, FCF/NI, ND/FCF), остаются здесь.

type Level = MetricLevel;

/** P/E null + убыток → «убыток» в UI. */
function peLevelContext(
  profile: SectorProfile | null | undefined,
  pe: number | null,
  income: number | null,
): Level {
  if (pe !== null) return levelFor(profile, 'pe', pe);
  if (income !== null && income < 0) return 'loss';
  return 'neutral';
}

/** P/B null + отрицательный капитал → «убыток» в UI. */
function pbLevelContext(
  profile: SectorProfile | null | undefined,
  pb: number | null,
  equity: number | null,
): Level {
  if (pb !== null) return levelFor(profile, 'pb', pb);
  if (equity !== null && equity < 0) return 'loss';
  return 'neutral';
}

/**
 * D/E с учётом отрицательного капитала: отрицательное значение формально
 * попадает в «хорошо», хотя означает дефицит балансовой стоимости.
 */
function deLevel(profile: SectorProfile | null | undefined, v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';
  return levelFor(profile, 'de', v);
}

const DE_BANKRUPTCY_TIP =
  'Отрицательный собственный капитал — компания фактически банкрот. D/E в такой ситуации не имеет смысла.';

function deBadge(
  profile: SectorProfile | null | undefined,
  de: number | null,
  equity: number | null,
  fallbackHint?: string,
): { value: number | null; level: Level; tip?: string } {
  const level = deLevel(profile, de);
  const bankrupt = de !== null && de < 0 && equity !== null && equity < 0;
  const leaseNote = getBand(profile, 'de').note ?? undefined;
  return {
    value: de,
    level,
    tip: bankrupt ? DE_BANKRUPTCY_TIP : (fallbackHint ?? leaseNote),
  };
}

/** P/FCF null + отрицательный FCF → «убыток» в UI. */
function pfcfLevel(v: number | null, fcf: number | null): Level {
  if (v !== null) {
    if (v <= 15) return 'good';
    if (v <= 25) return 'warn';
    return 'bad';
  }
  if (fcf !== null && fcf < 0) return 'loss';
  return 'neutral';
}

/** FCF yield = 100 / P/FCF (%). Пороги — обратные к P/FCF. */
function fcfYieldLevel(yieldPct: number | null, fcf: number | null): Level {
  if (yieldPct !== null) {
    if (yieldPct >= 6.67) return 'good';
    if (yieldPct >= 4) return 'warn';
    return 'bad';
  }
  if (fcf !== null && fcf < 0) return 'loss';
  return 'neutral';
}

function pfcfToFcfYield(pfcf: number | null): number | null {
  if (pfcf === null || pfcf <= 0) return null;
  return Math.round((100 / pfcf) * 100) / 100;
}

/** Net Debt/FCF — лет погашения; цвет зависит от знака FCF и Net Debt. */
function computeNetDebtToFcf(
  ratio: number | null | undefined,
  netDebt: number | null | undefined,
  fcf: number | null | undefined,
): number | null {
  if (ratio != null) return ratio;
  if (netDebt == null || fcf == null || fcf === 0) return null;
  return Math.round((netDebt / fcf) * 100) / 100;
}

function netDebtFcfBadge(
  ratio: number | null | undefined,
  netDebt: number | null | undefined,
  fcf: number | null | undefined,
): { value: number | null; level: Level; tip?: string } {
  const f = fcf ?? null;
  const nd = netDebt ?? null;
  const v = computeNetDebtToFcf(ratio, nd, f);

  if (v === null) {
    if (f === 0) {
      return { value: null, level: 'neutral', tip: 'FCF = 0 — ND/FCF не определён' };
    }
    return { value: null, level: 'neutral', tip: 'Недостаточно данных для ND/FCF' };
  }

  if (f !== null && f < 0) {
    return {
      value: v,
      level: 'loss',
      tip: nd !== null && nd > 0
        ? 'FCF отрицателен при положительном чистом долге — компания сжигает деньги; отрицательное ND/FCF сигнализирует о росте долговой нагрузки'
        : 'FCF отрицателен — свободный денежный поток отрицателен; показатель отражает сжигание cash flow',
    };
  }

  if (nd !== null && nd < 0) {
    return {
      value: v,
      level: 'good',
      tip: 'Net Debt отрицателен (чистый денежный запас): наличность превышает долг — отрицательное ND/FCF отражает запас ликвидности',
    };
  }

  if (v <= 3) {
    return { value: v, level: 'good', tip: 'Низкая нагрузка: чистый долг покрывается за ≤ 3 года FCF' };
  }
  if (v <= 5) {
    return { value: v, level: 'warn', tip: 'Умеренная нагрузка: на погашение чистого долга потребуется 3–5 лет FCF' };
  }
  return { value: v, level: 'bad', tip: 'Высокая нагрузка: погашение чистого долга займёт более 5 лет FCF' };
}

function netDebtValueUi(netDebtMln: number | null, scale: MoneyScale): {
  display: string;
  level: Level;
  tip?: string;
} {
  if (netDebtMln === null) {
    return { display: '—', level: 'neutral', tip: 'Нет данных о долге и наличности' };
  }
  const display = fmtMoney(netDebtMln, scale);
  if (netDebtMln < 0) {
    return {
      display,
      level: 'good',
      tip: 'Net Debt отрицателен: денежные средства и эквиваленты превышают долг (чистый денежный запас)',
    };
  }
  return {
    display,
    level: 'neutral',
    tip: 'Положительный чистый долг: заёмные средства превышают наличность и эквиваленты',
  };
}

type PfcfColMode = 'pfcf' | 'yield';

/**
 * FCF/Net Income (конверсия) — детектор качества прибыли при положительном NI.
 * Использовать только когда LTM net income > 0 (см. `fcfNiBadge`).
 *  ≥ 1.0: FCF превышает или равен прибыли → high-quality earnings ('good')
 *  0.7–0.99: норма ('warn')
 *  0–0.69: сомнительное качество ('bad')
 *  < 0:    отрицательный FCF при положительной прибыли → красный флаг ('loss')
 */
function fcfNiLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 1) return 'good';
  if (v >= 0.7) return 'warn';
  if (v >= 0) return 'bad';
  return 'loss';  // FCF отрицательный — красный флаг
}

/**
 * Особые состояния ROE, не зависящие от отрасли: при неположительном капитале
 * показатель бессмыслен, а значение выше 100% почти всегда означает не
 * выдающийся бизнес, а крошечный знаменатель.
 */
function roeDisplayState(
  roe: number | null | undefined,
  equity: number | null | undefined,
): { value: number | null; textLabel?: string; nullHint?: string; centered?: boolean } {
  const eq = equity ?? null;
  if (eq !== null && eq <= 0) {
    return {
      value: null,
      textLabel: 'Н/Д',
      nullHint: 'Собственный капитал ≤ 0 — ROE не применим',
      centered: true,
    };
  }
  const v = roe ?? null;
  if (v !== null && v > 100) {
    return {
      value: null,
      textLabel: 'Искажено',
      nullHint: 'ROE > 100% — показатель может быть искажён (малый капитал или разовые эффекты)',
    };
  }
  return { value: v };
}

/** ROE: капитал ≤ 0 → «Н/Д»; ROE > 100% → «Искажено»; иначе число (в т.ч. отрицательное при убытке). */
function roeBadge(
  profile: SectorProfile | null | undefined,
  roe: number | null | undefined,
  equity: number | null | undefined,
): { value: number | null; level: Level; textLabel?: string; nullHint?: string; centered?: boolean } {
  const state = roeDisplayState(roe, equity);
  if (state.textLabel === 'Н/Д') return { ...state, level: 'loss' };
  if (state.textLabel === 'Искажено') return { ...state, level: 'warn' };
  const v = state.value;
  if (v !== null && v < 0) return { value: v, level: 'bad' };
  return { value: v, level: levelFor(profile, 'roe', v) };
}

/**
 * Пояснение к ROE — одно на карточку и на таблицу.
 *
 * Само число ничего не говорит: одинаковый ROE у разных компаний собран из
 * разных множителей и означает разное. Поэтому в пояснении четыре слоя:
 *
 *   1. Разложение по Дюпону — из чего складывается уровень;
 *   2. Что делает отдачу — прибыльность, оборот или заёмные деньги;
 *   3. Сколько это даёт сверх ключевой ставки;
 *   4. Чем вызвано движение к прошлому году — прибылью или капиталом.
 *
 * Четвёртый слой нужен, чтобы скачок ROE вверх при падающей прибыли читался
 * как сжатие капитала, а не как рост эффективности.
 */
function roeExplanation(
  snapshot: HistRowSnapshot,
  previous: HistRowSnapshot | null | undefined,
  profile: SectorProfile,
): { driver: RoeDriver; source: RoeSourceVerdict | null; tip?: string } {
  const dupont = computeDupont({
    netIncome: snapshot.ltm_net_income,
    revenue: snapshot.ltm_revenue,
    totalAssets: snapshot.total_assets,
    equity: snapshot.equity,
  });
  const driver = computeRoeDriver(
    { roe: snapshot.roe, netIncome: snapshot.ltm_net_income, equity: snapshot.equity },
    previous
      ? { roe: previous.roe, netIncome: previous.ltm_net_income, equity: previous.equity }
      : null,
  );
  const source = computeRoeSource(dupont, getBand(profile, 'de').good);

  const blocks = [roeTooltipLines(dupont, driver).join('\n'), source?.tip, roeSpreadLine(snapshot)];
  const tip = blocks.filter(Boolean).join('\n\n');
  return { driver, source, tip: tip.length > 0 ? tip : undefined };
}

/** Строка про отдачу сверх безрисковой ставки — пусто, если ставки нет. */
function roeSpreadLine(snapshot: HistRowSnapshot): string | undefined {
  const { roe_spread: spread, key_rate: rate, roe } = snapshot;
  if (spread === null || spread === undefined) return undefined;
  const head =
    roe !== null && rate !== null
      ? `Сверх ключевой ставки: ${roe.toFixed(1)}% − ${rate.toFixed(2)}% = ${spread.toFixed(1)} п.п.`
      : `Сверх ключевой ставки: ${spread.toFixed(1)} п.п.`;
  if (spread <= 0) {
    return head + ' Отдача не превышает безрисковую: держать ОФЗ выгоднее, чем владеть капиталом компании.';
  }
  if (spread < 5) {
    return head + ' Запас над безрисковой невелик — при снижении ставки он вырастет, при росте исчезнет.';
  }
  return head;
}

/**
 * Значок спреда ROE к ключевой ставке.
 *
 * Пороги отраслей («≥ 15% — хорошо») написаны безотносительно режима ставок и
 * не переписываются при каждом решении ЦБ. Спред делает это сам: пять
 * пунктов сверх безрисковой — уже вклад, ноль и ниже — повод держать ОФЗ.
 */
function roeSpreadBadge(
  spread: number | null,
  roe: number | null,
  keyRate: number | null,
  source: RoeSourceVerdict | null,
): { text: string; level: Level; tip: string } | undefined {
  if (spread === null || spread === undefined) return undefined;
  const level: Level = spread <= 0 ? 'bad' : spread < 5 ? 'warn' : 'good';
  const arithmetic =
    roe !== null && keyRate !== null
      ? `ROE ${roe.toFixed(1)}% − ключевая ${keyRate.toFixed(2)}% = ${spread.toFixed(1)} п.п.`
      : `Сверх ключевой ставки: ${spread.toFixed(1)} п.п.`;
  const verdict =
    spread <= 0
      ? ' Отдача не превышает безрисковую: держать ОФЗ выгоднее, чем владеть капиталом компании.'
      : '';
  const rounded = Math.round(spread * 10) / 10;
  return {
    text: rounded === 0 ? '0,0' : `${rounded > 0 ? '+' : '−'}${dec(Math.abs(rounded), 1)}`,
    level,
    tip: arithmetic + verdict + (source ? `\n\n${source.tip}` : ''),
  };
}

/** UI для FCF/NI: при NI ≤ 0 — «убыток»; при NI > 0 — число и шкала fcfNiLevel. */
function fcfNiBadge(
  fcfNi: number | null | undefined,
  ltmNetIncome: number | null | undefined,
): { value: number | null; level: Level; nullHint?: string } {
  const ni = ltmNetIncome ?? null;
  if (ni !== null && ni <= 0) {
    return {
      value: null,
      level: 'loss',
      nullHint: 'Чистая прибыль ≤ 0 — соотношение FCF/NI не применимо',
    };
  }
  const v = fcfNi ?? null;
  return { value: v, level: fcfNiLevel(v) };
}


// ─── Вспомогательные компоненты ──────────────────────────────────────────────

function MetricBadge({
  value, level, suffix = '', nullHint, textLabel, centered = false, tip,
}: {
  value: number | null;
  level: Level;
  suffix?: string;
  nullHint?: string;
  textLabel?: string;
  centered?: boolean;
  tip?: string;
}) {
  const hoverTip = tip ?? nullHint;
  const tipClass = hoverTip ? ' mult-cell-tip' : '';
  // `nullHint` объясняет ПУСТУЮ ячейку и на заполненную попадать не должен:
  // иначе над числом всплывает «поле не заполнено в отчёте».
  const filledTip = tip;
  const filledTipClass = filledTip ? ' mult-cell-tip' : '';

  const wrap = (node: React.ReactElement) =>
    centered ? <span className="mult-cell-center">{node}</span> : node;

  if (textLabel) {
    const isCompact = textLabel === 'убыток' || textLabel === 'Н/Д' || textLabel === 'Искажено';
    return wrap(
      <span
        className={`mult-cell ${level}${isCompact ? ' mult-cell-text-label' : ''}${tipClass}`}
        title={hoverTip}
      >
        {textLabel}
      </span>,
    );
  }
  if (value === null) {
    if (level === 'loss') {
      return wrap(
        <span
          className={`mult-cell loss mult-cell-text-label${tipClass}`}
          title={hoverTip ?? 'Убыток за период — показатель не применим'}
        >
          убыток
        </span>,
      );
    }
    return (
      <span
        className={`mult-cell neutral${hoverTip ? ' mult-cell-tip' : ''}`}
        title={hoverTip ?? 'Недостаточно данных'}
      >
        —
      </span>
    );
  }
  return (
    <span className={`mult-cell ${level}${filledTipClass}`} title={filledTip}>
      {dec(value, 2)}{suffix}
    </span>
  );
}

/** Порог, за которым гудвил перестаёт быть мелочью в балансе. */
const GOODWILL_FLAG_PCT = 20;

/**
 * Порог доли всего нематериального в КАПИТАЛЕ.
 *
 * Считается от капитала, а не от активов: у застройщика с тяжёлым балансом
 * 11 млрд НМА — это 3% активов и 37% капитала, и обеспечением служит второе.
 * Треть — та граница, за которой балансовая стоимость перестаёт быть твёрдой.
 */
const INTANGIBLES_FLAG_PCT = 33;

function fmt2(value: number): string {
  return value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * P/B по материальной балансовой стоимости — как у Грэма.
 *
 * Гудвил вычтен из капитала: это не имущество, а разница между уплаченной за
 * компанию ценой и её чистыми активами. Продать его отдельно нельзя, денег он
 * не приносит, а при неудачной сделке списывается разом — и балансовая
 * стоимость падает сразу на всю сумму. Поэтому в таблице стоит очищенное
 * число, а отчётное уходит в подсказку.
 *
 * Когда гудвила нет, оба значения совпадают и показывать нечего.
 *
 * Прочие НМА из показанного числа НЕ вычитаются: купленные лицензии, софт и
 * патенты — настоящие средства производства, и «вон всё нематериальное» у
 * IT-компании было бы не консерватизмом, а другой ошибкой. Но когда на них
 * держится треть капитала, рядом встаёт значок: среди НМА попадаются
 * отложенные права и льготы, живущие до тех пор, пока выполняются условия.
 */
function PbMetricBadge({
  profile, pb, equity, pbTangible, goodwillShare, intangiblesShare, nullHint,
}: {
  profile: SectorProfile | null | undefined;
  pb: number | null;
  equity: number | null | undefined;
  pbTangible?: number | null;
  goodwillShare?: number | null;
  intangiblesShare?: number | null;
  nullHint?: string;
}) {
  const hasGoodwill = goodwillShare != null;
  // Пустой материальный P/B при наличии гудвила означает одно: гудвил съел
  // капитал целиком. Это не «нет данных», и молчать об этом нельзя.
  const wipedOut = hasGoodwill && pbTangible == null;
  const shown = hasGoodwill ? pbTangible ?? null : pb;

  const share = hasGoodwill ? goodwillShare!.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '';
  const tip = wipedOut
    ? `Гудвил (${share}% активов) больше собственного капитала: по материальным активам `
      + `компания в минусе, поэтому P/B не считается. С гудвилом было бы `
      + `${pb != null ? fmt2(pb) : '—'}.`
    : hasGoodwill
      ? `Балансовая стоимость без гудвила, как у Грэма. С гудвилом — `
        + `${pb != null ? fmt2(pb) : '—'}, сам гудвил — ${share}% активов.`
      : undefined;

  const badge = (
    <MetricBadge
      value={shown}
      level={pbLevelContext(profile, shown, equity ?? null)}
      nullHint={shown === null ? tip ?? nullHint : undefined}
      tip={shown !== null ? tip : undefined}
    />
  );

  // Значок ставят две независимые тревоги. Гудвил меряется от активов и уже
  // вычтен из показанного числа; прочие НМА — от капитала и не вычтены. Значок
  // один: две восклицательных рядом читались бы как удвоенная беда, а это не
  // так — они про разное.
  const goodwillFlagged = hasGoodwill && goodwillShare! >= GOODWILL_FLAG_PCT;
  const intangiblesFlagged =
    intangiblesShare != null && intangiblesShare >= INTANGIBLES_FLAG_PCT;
  if (!goodwillFlagged && !intangiblesFlagged) return badge;

  const reasons: string[] = [];
  if (goodwillFlagged) {
    // Когда гудвил съел капитал целиком, вычитать уже нечего и показывать
    // нечего: P/B пуст. Прежний текст утверждал, что гудвил «вычтен из
    // показанного P/B», хотя показанного не было, — и человек оставался с
    // пустой клеткой и объяснением про другое.
    reasons.push(
      wipedOut
        ? `P/B не показан: гудвил (${share}% активов) больше собственного капитала, `
          + `и по материальным активам компания в минусе — делить не на что. `
          + `С гудвилом P/B был бы ${pb != null ? fmt2(pb) : '—'}, но эта величина `
          + `держится на оценке, которую проверяют раз в год и списывают целиком.`
        : `Гудвил — ${share}% активов, и он уже вычтен из показанного P/B. `
          + `С гудвилом было бы ${pb != null ? fmt2(pb) : '—'}. `
          + `Чем крупнее эта доля, тем сильнее балансовая стоимость зависит от одной оценки: `
          + `гудвил проверяют на обесценение раз в год, и списывают его целиком, а не постепенно.`,
    );
  }
  if (intangiblesFlagged) {
    const softShare = intangiblesShare!.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
    reasons.push(
      `Нематериальные активы вместе с гудвилом — ${softShare}% капитала, и из показанного `
      + `P/B они НЕ вычтены. Купленные лицензии, софт и патенты — настоящие средства `
      + `производства, вычитать их было бы неверно. Но в той же строке баланса рядом с ними `
      + `живут отложенные права и льготы, которые действуют, только пока выполняются условия `
      + `сделки. Стоит открыть примечание об НМА и посмотреть состав.`,
    );
  }

  return (
    <span className="metric-with-flag">
      {badge}
      <span className="metric-flag" title={reasons.join('\n\n')}>
        !
      </span>
    </span>
  );
}

function DeMetricBadge({
  profile,
  de,
  equity,
  fallbackHint,
}: {
  profile: SectorProfile | null | undefined;
  de: number | null;
  equity: number | null | undefined;
  fallbackHint?: string;
}) {
  const ui = deBadge(profile, de, equity ?? null, fallbackHint);
  return (
    <MetricBadge
      value={ui.value}
      level={ui.level}
      nullHint={ui.value === null ? ui.tip : undefined}
      tip={ui.value !== null ? ui.tip : undefined}
    />
  );
}

/**
 * Свободный поток к капиталу, %.
 *
 * Пара к ROE, отвечающая на тот же вопрос деньгами, а не начислениями.
 * Отраслевой порог сюда не переносится: он откалиброван под прибыль, и у
 * компании в фазе стройки поток к капиталу законно уходит в минус, хотя
 * бизнес здоров. Поэтому окраска простая — плюс или минус, без «хорошо».
 */
function FcfToEquityCell({ value }: { value: number | null }) {
  return (
    <MetricBadge
      value={value}
      level={value !== null && value < 0 ? 'loss' : 'neutral'}
      suffix="%"
      nullHint="Свободный поток или капитал неизвестны"
      tip={value === null ? undefined
        : 'Свободный поток к собственному капиталу: та же база, что у ROE, '
          + 'но вместо прибыли — деньги, оставшиеся после капзатрат'}
    />
  );
}

function RoeMetricBadge({
  profile,
  roe,
  equity,
  explanationTip,
  misleading = false,
}: {
  profile: SectorProfile | null | undefined;
  roe: number | null | undefined;
  equity: number | null | undefined;
  /** Разложение по Дюпону и причина изменения — показывается по наведению */
  explanationTip?: string;
  /** Изменение ROE вызвано движением капитала: подсвечиваем как «внимание» */
  misleading?: boolean;
}) {
  const ui = roeBadge(profile, roe, equity);
  const level: Level = misleading && ui.level === 'good' ? 'warn' : ui.level;
  return (
    <MetricBadge
      value={ui.value}
      level={level}
      suffix="%"
      nullHint={ui.nullHint}
      textLabel={ui.textLabel}
      centered={ui.centered}
      tip={ui.value !== null ? explanationTip : undefined}
    />
  );
}

/** Нет дивидендной доходности: выплаты по обыкновенным не указаны или не было выплат */
/**
 * Что показывать вместо доходности, когда дивиденда за скользящий год нет.
 *
 * Пустая доходность у Лукойла и у М.Видео означает совершенно разное: первый
 * платит семь лет из семи и просто ещё не объявил за текущий период, второй не
 * платил ни разу. Один и тот же прочерк на обоих — потеря главного, что здесь
 * есть. Поэтому состояний три, и различает их привычка компании, а не текущее
 * окно LTM.
 */
type DividendAbsence = {
  mark: string;
  label: string;
  level: 'warn' | 'bad';
  /** Короткая строка под значением — на месте порога */
  threshold: string;
  /** Развёрнутое пояснение, только по наведению */
  tip: string;
};

/**
 * Дивиденда за период нет.
 *
 * Ноль и пустота значат здесь одно и то же: выплаты не было. Раньше сумма LTM
 * возвращала `null`, когда хоть одно слагаемое пустое, и проверка на `null`
 * работала. Теперь пустое полугодие при флаге «не платили» читается как ноль —
 * и ветка «дивиденда нет» перестала срабатывать, а строка проваливалась в
 * «нет цены акции», хотя цена была на месте.
 */
function hasNoDividend(dps: number | null | undefined): boolean {
  return dps === null || dps === undefined || dps === 0;
}


/** Сколько лет молчания означают, что компания перестала платить. */


function NoDividendYieldMark({
  className = '',
  absence,
}: {
  className?: string;
  absence?: DividendAbsence;
}) {
  const isCard = className.includes('mult-div-none--card');
  const a = absence;
  const mark = (
    <span
      className={
        `mult-div-none mult-div-none--wrap mult-cell-tip` +
        `${a ? ` mult-div-none--${a.level}` : ''}${isCard ? ` ${className}` : ''}`
      }
      title={
        a?.tip ??
        'Дивиденды по обыкновенным акциям за период не выплачивались или не указаны в отчётах'
      }
      aria-label={a?.label ?? 'Дивиденды не выплачивались'}
    >
      {(a?.mark ?? '×') !== '' && (
        <span className="mult-div-none-box" aria-hidden>
          {a?.mark ?? '×'}
        </span>
      )}
      {isCard && a && <span className="mult-div-none-label">{a.label}</span>}
    </span>
  );
  if (isCard) return mark;
  return <span className={`mult-cell-center${className ? ` ${className}` : ''}`}>{mark}</span>;
}

/**
 * Подсказка к доходности, в которой есть разовая часть.
 * Спецвыплата — компенсация пропущенных лет, распределение от продажи актива —
 * не повторится в следующем году, поэтому оценивается регулярная часть.
 */
function specialDividendTip(
  totalYield: number | null,
  regularYield: number | null,
  specialPerShare: number,
): string {
  const parts = [
    `Всего за 12 мес.: ${totalYield !== null ? `${totalYield.toFixed(2)}%` : '—'}`,
    `из них разовая часть: ${fmt(specialPerShare)} ₽ на акцию`,
    `регулярная доходность: ${regularYield !== null ? `${regularYield.toFixed(2)}%` : '—'}`,
    '',
    'Оценка выставлена по регулярной части: спецвыплата в следующем году не повторится.',
  ];
  return parts.join('\n');
}

function DividendYieldBadge({
  profile,
  dividendYield,
  dividendYieldRegular,
  specialDividendsPerShare,
  ltmDividendsPerShare,
  priceUsed,
  isPreferredShare = false,
}: {
  profile: SectorProfile | null | undefined;
  dividendYield: number | null;
  /** Доходность без разовых выплат — именно она получает цветовую оценку */
  dividendYieldRegular?: number | null;
  /** Разовая часть выплаты, ₽ на акцию */
  specialDividendsPerShare?: number | null;
  ltmDividendsPerShare: number | null;
  priceUsed: number | null;
  /** Тикер представляет привилегированные акции — у него нет понятия
   *  «не выплачивались по обыкновенным», поэтому красный маркер не нужен. */
  isPreferredShare?: boolean;
}) {
  if (dividendYield !== null) {
    const special = specialDividendsPerShare ?? 0;
    const hasSpecial = special > 0;
    const regular = dividendYieldRegular ?? dividendYield;
    const shown = hasSpecial ? regular : dividendYield;
    const lvl = levelFor(profile, 'dy', shown);
    const tip = hasSpecial
      ? specialDividendTip(dividendYield, regular, special)
      : (isPreferredShare ? 'Доходность по привилегированным акциям' : undefined);
    return (
      <span className={`mult-cell ${lvl}${tip ? ' mult-cell-tip' : ''}`} title={tip}>
        {dec(shown, 2)}%{hasSpecial ? <span className="div-special-mark">*</span> : null}
      </span>
    );
  }
  if (hasNoDividend(ltmDividendsPerShare)) {
    if (isPreferredShare) {
      return (
        <span
          className="mult-cell neutral null-hint"
          title="Доходность по привилегированным акциям — дивиденды в отчётах не указаны"
        >
          —
        </span>
      );
    }
    return <NoDividendYieldMark />;
  }
  const hint =
    priceUsed === null || priceUsed === undefined
      ? 'Недостаточно данных для расчёта доходности'
      : 'Нет цены акции для расчёта доходности';
  return (
    <span className="mult-cell neutral null-hint" title={hint}>
      —
    </span>
  );
}

/**
 * Число с десятичной запятой и пробелом в тысячах. `toFixed` давал «3143.27»
 * рядом с «5 365» из соседней колонки — две разные записи в одной таблице.
 */
function dec(n: number, digits: number): string {
  return n.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmt(n: number | null, decimals = 2): string {
  if (n === null) return '—';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
}

/** Заголовок колонки: название + единица измерения меньшим шрифтом снизу. */
/**
 * Заголовок из названия и единицы измерения.
 *
 * Длинные названия набираются мельче. Ширину колонки задаёт самое длинное из
 * двух — название или значение, — и у «Покрытия» с «Портфелем» слово вдвое
 * шире числа под ним. Коротким заголовкам (P/E, ROA, CIR) мельчить нечего:
 * их колонки давно определяются значениями.
 */
const LONG_TITLE_CHARS = 6;

function ColHeaderWithUnit({
  title,
  unit = 'млрд ₽',
  uppercase = true,
  align = 'center',
}: {
  title: string;
  unit?: string;
  uppercase?: boolean;
  align?: 'center' | 'right';
}) {
  const base = uppercase ? 'col-header-title' : 'col-header-title-plain';
  const long = title.length > LONG_TITLE_CHARS ? ' col-header-title--long' : '';
  return (
    <span className={`col-header-stacked${align === 'right' ? ' col-header-stacked-right' : ''}`}>
      <span className={`${base}${long}`}>{title}</span>
      <span className="col-header-unit">{unit}</span>
    </span>
  );
}


/**
 * Портфель крупного банка в млрд — пятизначное число, которое глазом не
 * читается: 48 473 против 46 710 отличить труднее, чем 48,47 и 46,71. Поэтому
 * колонка целиком переключается на триллионы, как только хотя бы одно значение
 * в ней доходит до пяти знаков. Именно колонка целиком, а не отдельная ячейка:
 * иначе в одном столбце оказались бы соседние годы в разных единицах.
 */
const PORTFOLIO_TRILLION_THRESHOLD_MLN = 10_000_000; // 10 000 млрд = 5 знаков

function fmtPortfolio(n: number | null, inTrillions: boolean): string {
  if (n === null || n === undefined) return '—';
  return dec(n / (inTrillions ? 1_000_000 : 1_000), 2);
}

/**
 * Масштаб денежной колонки: млн → млрд → трлн.
 *
 * Жёсткие миллиарды годились, пока в базе были одни голубые фишки. У компании,
 * которая отчитывается в тысячах рублей, в них схлопывается вся строка: выручка
 * 1 756 млн превращается в «1.76», прибыль 0,53 млн — в «0.00», CAPEX и чистый
 * долг — в «0.17» и «0.25». Колонка перестаёт что-либо говорить, а разница
 * между годами пропадает в округлении.
 *
 * Единица выбирается по самому крупному значению колонки и выносится в её
 * заголовок — как у портфеля банка выше. Масштаб именно на колонку целиком,
 * а не на ячейку: иначе соседние годы оказались бы в разных единицах.
 */
type MoneyScale = { divisor: number; unit: string };

const MONEY_SCALES: MoneyScale[] = [
  { divisor: 1, unit: 'млн ₽' },
  { divisor: 1_000, unit: 'млрд ₽' },
  { divisor: 1_000_000, unit: 'трлн ₽' },
];

// Переходим к следующей единице, когда числу стало бы тесно в пяти знаках, —
// тот же порог читаемости, что у PORTFOLIO_TRILLION_THRESHOLD_MLN.
const MONEY_SCALE_LIMIT = 10_000;

function moneyColumnScale(values: (number | null | undefined)[]): MoneyScale {
  let max = 0;
  for (const v of values) {
    if (typeof v === 'number' && Number.isFinite(v)) max = Math.max(max, Math.abs(v));
  }
  for (const scale of MONEY_SCALES) {
    if (max / scale.divisor < MONEY_SCALE_LIMIT) return scale;
  }
  return MONEY_SCALES[MONEY_SCALES.length - 1];
}

/** Значение в млн ₽ → число в единице колонки (сама единица — в заголовке). */
function fmtMoney(n: number | null | undefined, scale: MoneyScale): string {
  if (n === null || n === undefined) return '—';
  return dec(n / scale.divisor, 2);
}

/** Масштабы всех денежных колонок таблицы — по одному на колонку. */
interface MoneyScales {
  cap: MoneyScale;
  netDebt: MoneyScale;
  fcf: MoneyScale;
  capex: MoneyScale;
  revenue: MoneyScale;
  profit: MoneyScale;
}

const DEFAULT_MONEY_SCALE: MoneyScale = MONEY_SCALES[1];

const DEFAULT_MONEY_SCALES: MoneyScales = {
  cap: DEFAULT_MONEY_SCALE,
  netDebt: DEFAULT_MONEY_SCALE,
  fcf: DEFAULT_MONEY_SCALE,
  capex: DEFAULT_MONEY_SCALE,
  revenue: DEFAULT_MONEY_SCALE,
  profit: DEFAULT_MONEY_SCALE,
};

const SHARE_SCALE: [number, string][] = [
  [1e12, 'трлн'],
  [1e9, 'млрд'],
  [1e6, 'млн'],
  [1e3, 'тыс'],
];

/** Порядок величины числа акций: множитель и подпись. */
function shareScaleOf(n: number): [number, string] {
  const abs = Math.abs(n);
  for (const [factor, unit] of SHARE_SCALE) {
    if (abs >= factor) return [factor, unit];
  }
  return [1, 'шт'];
}

/**
 * Как подписывать колонку с числом акций.
 *
 * Обычно единица одна на всю колонку и стоит в заголовке — так короче и
 * ровнее. Но дробление может развести значения на порядки: у ВТБ в 2023 году
 * было 26 трлн акций, а после консолидации 2024 года — 5,3 млрд, разница в
 * пять тысяч раз. Одна единица тогда либо превращает свежие годы в 0,01,
 * либо старые в пятизначное число, поэтому для таких компаний единица
 * переезжает в ячейку, к своему значению.
 *
 * Порог — три порядка. Список исключений не нужен: признак виден из данных,
 * и следующий такой сплит определится сам.
 */
const SHARE_SPREAD_LIMIT = 1000;

function shareColumnScale(values: number[]): { factor: number; unit: string } | null {
  const positive = values.filter((v) => v > 0);
  if (positive.length === 0) return null;
  const max = Math.max(...positive);
  if (max / Math.min(...positive) >= SHARE_SPREAD_LIMIT) return null;
  const [factor, unit] = shareScaleOf(max);
  return { factor, unit };
}

/** Число с фиксированной точностью; пусто — прочерк. */

/** Год из даты YYYY-MM-DD — подпись периода в таблице и на графике.
 *  Имя `fmtDate` вводило в заблуждение: в BondDetail так называется настоящее
 *  форматирование даты, а здесь возвращается только год. */
function fmtYear(d: string): string {
  return d.split('-')[0];
}

/**
 * Подпись строки истории — финансовый год, а не год даты отчёта.
 *
 * У компаний со сдвинутым финансовым годом это разные вещи. Диасофт закрывает
 * год 31 марта: период 31.03.2025-31.03.2026 — отчёт за 2025-й, но дата
 * мультипликатора 2026-03-31, и по ней вся история съезжала на год вперёд.
 * Год даты остаётся запасным вариантом для строк без связанного отчёта.
 */
function periodLabel(r: { date: string; fiscal_year?: number | null }): string {
  return r.fiscal_year != null ? String(r.fiscal_year) : fmtYear(r.date);
}

/** Дата YYYY-MM-DD → дд.мм.гггг (без сдвига часового пояса) */
function fmtDateFull(iso: string): string {
  const p = iso.split('-');
  if (p.length !== 3) return iso;
  const [y, m, d] = p;
  if (!y || !m || !d) return iso;
  return `${d.padStart(2, '0')}.${m.padStart(2, '0')}.${y}`;
}

// ─── Карточки текущих мультипликаторов ────────────────────────────────────────







// ─── Информационная строка с LTM-метаданными ─────────────────────────────────


// ─── Историческая таблица ─────────────────────────────────────────────────────

// ─── Тултип заголовка колонки с отраслевыми порогами ─────────────────────────

interface MetricTooltipProps {
  profile: SectorProfile;
  metric: 'cr';
  anchorRef: React.RefObject<HTMLElement | null>;
}

/**
 * Rich-тултип: объясняет, какой отраслевой профиль применён к метрике
 * и каковы конкретные пороги «хорошо / внимание / тревога».
 * Рендерится в portal, чтобы не зажиматься overflow:hidden таблицы.
 */
const MetricTooltip: React.FC<MetricTooltipProps> = ({ profile, metric, anchorRef }) => {
  const [pos, setPos] = React.useState<{ top: number; left: number } | null>(null);
  const band = getBand(profile, metric);
  const lines = tooltipLinesFor(profile, metric);

  React.useLayoutEffect(() => {
    const el = anchorRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({
      top: r.bottom + window.scrollY + 6,
      left: r.left + window.scrollX + r.width / 2,
    });
  }, [anchorRef]);

  if (!pos) return null;

  const comparator = band.higher_is_better ? '≥' : '≤';
  const inverse = band.higher_is_better ? '<' : '>';

  return createPortal(
    <div
      className="cr-tooltip"
      style={{ top: pos.top, left: pos.left }}
      role="tooltip"
    >
      <div className="cr-tooltip-industry">{profile.label}</div>
      {!band.applicable || band.good === null || band.warn === null ? (
        <p className="cr-tooltip-na">{lines[0] ?? band.hint}</p>
      ) : (
        <>
          <div className="cr-tooltip-thresholds">
            <span className="cr-tt-good">● хорошо: {comparator} {band.good.toFixed(1)}</span>
            <span className="cr-tt-warn">● внимание: {comparator} {band.warn.toFixed(1)}</span>
            <span className="cr-tt-bad">● тревога: {inverse} {band.warn.toFixed(1)}</span>
          </div>
          <div className="cr-tooltip-body">
            {lines.map((line, i) =>
              line === '' ? <br key={i} /> : <div key={i} className="cr-tooltip-line">{line}</div>,
            )}
          </div>
        </>
      )}
    </div>,
    document.body,
  );
};

/** Всплывающая подсказка: цена в ячейке — на конец периода; рядом — на дату публикации отчёта. */
const HistPriceCell: React.FC<{ row: MultiplierRecord }> = ({ row }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  const filing = row.filing_date?.trim() ?? '';
  const hasTip = Boolean(filing) || row.price_at_filing_rub != null;

  const onEnterMove = (e: React.MouseEvent) => {
    setPos({ x: e.clientX + 14, y: e.clientY + 14 });
  };

  const tipBody = (() => {
    if (filing && row.price_at_filing_rub != null) {
      return (
        <>
          <div className="mult-price-tip-line">
            На дату публикации ({fmtDateFull(filing)})
          </div>
          <div className="mult-price-tip-value">{formatPerShare(row.price_at_filing_rub)} ₽</div>
        </>
      );
    }
    if (filing) {
      return (
        <>
          <div className="mult-price-tip-line">Дата публикации: {fmtDateFull(filing)}</div>
          <div className="mult-price-tip-muted">Цена на эту дату в отчёте не указана</div>
        </>
      );
    }
    if (row.price_at_filing_rub != null) {
      return (
        <div className="mult-price-tip-value">Цена на дату публикации: {formatPerShare(row.price_at_filing_rub)} ₽</div>
      );
    }
    return null;
  })();

  return (
    <>
      <span
        className={hasTip ? 'mult-price-with-tip' : undefined}
        onMouseEnter={(e) => {
          if (!hasTip) return;
          onEnterMove(e);
          setOpen(true);
        }}
        onMouseMove={(e) => {
          if (!open) return;
          onEnterMove(e);
        }}
        onMouseLeave={() => setOpen(false)}
      >
        {row.price_used !== null ? formatPerShare(row.price_used) : '—'}
      </span>
      {open && hasTip && tipBody
        ? createPortal(
            <div
              className="mult-price-filing-tooltip"
              style={{ left: pos.x, top: pos.y }}
              role="tooltip"
            >
              <div className="mult-price-tip-title">Цена при выходе отчёта</div>
              {tipBody}
            </div>,
            document.body,
          )
        : null}
    </>
  );
};

const HistCapCell: React.FC<{
  marketCapMln: number | null;
  explanation: string | null | undefined;
  scale: MoneyScale;
}> = ({ marketCapMln, explanation, scale }) => {
  const display = fmtMoney(marketCapMln, scale);
  return (
    <SharesCapHover explanation={explanation}>
      {display}
    </SharesCapHover>
  );
};

const HistPfcfHeader: React.FC<{
  mode: PfcfColMode;
  onToggle: () => void;
}> = ({ mode, onToggle }) => (
  <th className="col-mult col-compact col-pfcf-header col-header-unit-col">
    <span className="col-header-stacked">
      <span className="col-header-title">{mode === 'pfcf' ? 'P/FCF' : 'FCF yld'}</span>
      <button
        type="button"
        className="col-toggle-btn"
        onClick={onToggle}
        aria-label={mode === 'pfcf' ? 'Показать FCF yield' : 'Показать P/FCF'}
        title="Переключить P/FCF ↔ FCF yield"
      >
        ⇄
      </button>
    </span>
  </th>
);

/**
 * Заголовки-переключатели ROE и «на акцию».
 *
 * Прибыль и свободный поток отвечают на разные вопросы: первая — сколько
 * заработано по правилам учёта, второй — сколько осталось в кассе. У компании
 * с большим капексом они расходятся годами, и держать их в соседних колонках
 * значило бы раздуть и без того широкую таблицу. Переключатель показывает обе
 * величины на одном месте и в одной шкале, так что разрыв виден сразу.
 */
const HistRoeHeader: React.FC<{
  mode: RoeColMode;
  onToggle: () => void;
  /** У банка свободного потока нет — и переключаться не на что. */
  swappable?: boolean;
}> = ({ mode, onToggle, swappable = true }) => (
  <th className="col-mult col-header-unit-col">
    <span className="col-header-stacked">
      <span className="col-header-title">{mode === 'fcf' ? 'FCF/E' : 'ROE'}</span>
      <span className="col-header-unit-row">
        {swappable && (
          <button
            type="button"
            className="col-toggle-btn"
            onClick={onToggle}
            aria-label={mode === 'fcf' ? 'Показать ROE по прибыли' : 'Показать поток к капиталу'}
            title="Переключить ROE ↔ свободный поток к капиталу"
          >
            ⇄
          </button>
        )}
        <span className="col-header-unit">%</span>
      </span>
    </span>
  </th>
);

const HistPerShareHeader: React.FC<{
  mode: PerShareColMode;
  onToggle: () => void;
  swappable?: boolean;
}> = ({ mode, onToggle, swappable = true }) => (
  <th
    className="col-mult col-compact col-header-unit-col"
    title={mode === 'fcf'
      ? 'Свободный поток на акцию — та же шкала, что у EPS'
      : 'Прибыль на акцию. Считается от тех же акций, что и капитализация, поэтому Цена / EPS в точности равна P/E этой строки'}
  >
    <span className="col-header-stacked">
      <span className="col-header-title">{mode === 'fcf' ? 'FCF/акц' : 'EPS'}</span>
      <span className="col-header-unit-row">
        {swappable && (
          <button
            type="button"
            className="col-toggle-btn"
            onClick={onToggle}
            aria-label={mode === 'fcf' ? 'Показать прибыль на акцию' : 'Показать поток на акцию'}
            title="Переключить прибыль на акцию ↔ свободный поток на акцию"
          >
            ⇄
          </button>
        )}
        <span className="col-header-unit">₽</span>
      </span>
    </span>
  </th>
);

const HistNetDebtFcfCell: React.FC<{
  ratio: number | null;
  netDebt: number | null;
  fcf: number | null;
}> = ({ ratio, netDebt, fcf }) => {
  const ui = netDebtFcfBadge(ratio, netDebt, fcf);
  return (
    <MetricBadge
      value={ui.value}
      level={ui.level}
      tip={ui.value !== null ? ui.tip : undefined}
      nullHint={ui.value === null ? ui.tip : undefined}
    />
  );
};

const HistNetDebtCell: React.FC<{ netDebtMln: number | null; scale: MoneyScale }> = ({
  netDebtMln,
  scale,
}) => {
  const ui = netDebtValueUi(netDebtMln, scale);
  return (
    <span className="hist-plain-value" title={ui.tip}>
      {ui.display}
    </span>
  );
};

const HistPfcfCell: React.FC<{
  mode: PfcfColMode;
  pfcf: number | null;
  fcf: number | null;
}> = ({ mode, pfcf, fcf }) => {
  const fcfLossHint = fcf !== null && fcf < 0
    ? (mode === 'pfcf' ? 'FCF отрицателен — P/FCF не рассчитывается' : 'FCF отрицателен — yield не рассчитывается')
    : undefined;

  if (mode === 'yield') {
    const yld = pfcfToFcfYield(pfcf);
    return (
      <MetricBadge
        value={yld}
        level={fcfYieldLevel(yld, fcf)}
        suffix="%"
        nullHint={fcfLossHint}
      />
    );
  }

  return (
    <MetricBadge
      value={pfcf}
      level={pfcfLevel(pfcf, fcf)}
      nullHint={fcfLossHint}
    />
  );
};

const HistChangeCell: React.FC<{ change: YoYDisplay }> = ({ change }) => (
  <span
    className={`hist-change hist-change-${change.level}${change.tip ? ' hist-change-tip' : ''}`}
    title={change.tip}
  >
    {change.text}
  </span>
);

// ─── Столбцы и ячейки истории ────────────────────────────────────────────────
//
// Таблица умеет стоять двумя способами: годы строками (как раньше) и годы
// колонками (как лист Value Line). Чтобы подсветка, подсказки и переключатели
// не разъехались между ориентациями, обе собираются из одного набора: список
// столбцов (что показываем и как подписано) и ячейки одного периода (что
// показываем в каждом). Ориентация решает только, куда их положить.

type HistColKey =
  | 'price' | 'ref' | 'margin' | 'cap'
  | 'pe' | 'peRep' | 'pb' | 'pfcf' | 'div' | 'cir'
  | 'roe' | 'spread' | 'fcfNi'
  | 'de' | 'cr' | 'ndFcf' | 'netDebt'
  | 'roa' | 'cor' | 'npl' | 'coverage' | 'ldr' | 'n11' | 'portfolio'
  | 'revenue' | 'profit' | 'fcf' | 'capex'
  | 'eps' | 'shares';

type SheetOrientation = 'rows' | 'cols';

const HIST_GROUPS = [
  'Цена и оценка',
  'Мультипликаторы',
  'Отдача',
  'Долг и ликвидность',
  'Банк',
  'Деньги',
  'На акцию',
] as const;
type HistGroup = (typeof HIST_GROUPS)[number];

interface HistFlags {
  isBank: boolean;
  noLeverage: boolean;
  showCir: boolean;
  showFcf: boolean;
  showRatios: boolean;
  hasValuation: boolean;
  /** Есть отчётная прибыль — можно показать P/E по отчёту рядом с очищенным. */
  hasReported: boolean;
}

function histFlags(
  profile: SectorProfile,
  isHolding: boolean,
  hasValuation: boolean,
  hasReported: boolean,
): HistFlags {
  // У банка плечо — это бизнес-модель, а не риск, ликвидность считается
  // нормативами ЦБ, а FCF неприменим концептуально. Биржа: обязательства —
  // чужие деньги и зеркальные позиции клиринга, поэтому плечо, ликвидность и
  // чистый долг не выводятся, но свободный поток есть. У холдинга P/E, P/B и
  // ROE по консолидации описывают сумму чужих бизнесов.
  const isBank = profile?.key === 'bank';
  const isExchange = profile?.key === 'exchange';
  return {
    isBank,
    noLeverage: isBank || isExchange || isHolding,
    showCir: isBank || isExchange,
    showFcf: !isBank && !isHolding,
    showRatios: !isHolding,
    hasValuation,
    hasReported: hasReported && !isHolding,
  };
}

/** Запас прочности словами ячейки: ниже −100% — «цена в N раз выше». */
function marginText(margin: number): string {
  if (margin < -1) return `×${dec(1 - margin, 1)}`;
  const pct = Math.round(margin * 100);
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct)}%`;
}

const MARGIN_GOOD = 0.15;

function marginLevel(margin: number | null): Level {
  if (margin === null) return 'neutral';
  if (margin >= MARGIN_GOOD) return 'good';
  return margin >= 0 ? 'warn' : 'bad';
}

const MarginCell: React.FC<{ margin: number | null }> = ({ margin }) => {
  if (margin === null) {
    return <span className="mult-cell neutral mult-cell-tip" title="Оценки за этот период нет">—</span>;
  }
  const tip = margin < -1
    ? `Цена выше опорной стоимости в ${dec(1 - margin, 1)} раза`
    : margin >= MARGIN_GOOD
      ? 'Цена ниже опорной на 15% и больше — запас прочности есть'
      : margin >= 0
        ? 'Цена ниже опорной, но запас тоньше 15%'
        : 'Цена выше опорной стоимости';
  return (
    <span className={`mult-cell ${marginLevel(margin)} mult-cell-tip`} title={tip}>
      {marginText(margin)}
    </span>
  );
};

/** Изменение запаса прочности — в пунктах, как у всех долей. */
function marginChange(current: number | null, previous: number | null): YoYDisplay {
  if (current === null || previous === null) return YOY_NA;
  return metricPp(current * 100, previous * 100, 'higher_better', 'Запас прочности');
}

interface HistRowCellsInput {
  record?: MultiplierRecord;
  snapshot: HistRowSnapshot;
  dividendYield?: number | null;
  yoy: HistRowYoY | null;
  pctMode: boolean;
  pfcfColMode: PfcfColMode;
  roeColMode: RoeColMode;
  perShareColMode: PerShareColMode;
  profile: SectorProfile;
  /** Период годом раньше — для атрибуции ROE и режима «изменение». */
  previous?: HistRowSnapshot | null;
  isPreferredShare: boolean;
  portfolioInTrillions?: boolean;
  moneyScales?: MoneyScales;
  sharesScale?: { factor: number; unit: string } | null;
  bankMetrics?: BankMetrics | null;
  costToIncome?: number | null;
  previousBankMetrics?: BankMetrics | null;
  previousCostToIncome?: number | null;
  /** Опорная стоимость по отчёту этого периода и прошлого. */
  reference?: number | null;
  previousReference?: number | null;
  /** P/E от прибыли как в отчёте — этого периода и прошлого. */
  peReported?: number | null;
  previousPeReported?: number | null;
  flags: HistFlags;
}

interface HistCell {
  node: React.ReactNode;
  className?: string;
}

type HistCells = Partial<Record<HistColKey, HistCell>>;

function histRowCells({
  record,
  snapshot,
  dividendYield,
  yoy,
  pctMode,
  pfcfColMode,
  roeColMode,
  perShareColMode,
  profile,
  previous,
  isPreferredShare,
  portfolioInTrillions,
  moneyScales = DEFAULT_MONEY_SCALES,
  sharesScale,
  bankMetrics,
  costToIncome,
  previousBankMetrics,
  previousCostToIncome,
  reference = null,
  previousReference = null,
  peReported = null,
  previousPeReported = null,
  flags,
}: HistRowCellsInput): HistCells {
  const out: HistCells = {};
  // В режиме «изменение» любая ячейка показывает прирост к прошлому году —
  // иначе строка читалась бы как смесь двух разных величин.
  const put = (
    key: HistColKey,
    change: YoYDisplay | null | undefined,
    content: React.ReactNode,
    className?: string,
  ) => {
    out[key] = { node: pctMode ? <HistChangeCell change={change ?? YOY_NA} /> : content, className };
  };

  const bankYoY = pctMode
    ? computeBankYoY(
        bankMetrics as unknown as Record<string, number | null> | null,
        previousBankMetrics as unknown as Record<string, number | null> | null,
        costToIncome,
        previousCostToIncome,
      )
    : null;

  const bank = (key: HistColKey, metric: keyof BankMetrics, change?: YoYDisplay | null) => {
    if (pctMode) {
      out[key] = { node: <HistChangeCell change={change ?? YOY_NA} />, className: 'col-mult col-compact col-bank' };
      return;
    }
    const value = (bankMetrics?.[metric] ?? null) as number | null;
    const status = bankMetrics?.statuses?.[metric as string] ?? 'n/a';
    const level = status === 'good' ? 'good' : status === 'normal' ? 'warn' : status === 'bad' ? 'bad' : 'neutral';
    // Доля проблемных и покрытие могут быть посчитаны по просрочке 90+, когда
    // эмитент не раскрыл стадии. Просрочка уже Стадии 3 — в неё не попадают
    // реструктуризации, — поэтому такие значения занижены и помечаются.
    const byOverdue =
      bankMetrics?.npl_basis === 'overdue_90' && (metric === 'npl_ratio' || metric === 'npl_coverage');
    out[key] = {
      className: 'col-mult col-compact col-bank',
      node: (
        <span className={byOverdue ? 'metric-with-flag' : undefined}>
          <MetricBadge
            value={value}
            level={level as Level}
            tip={bankMetrics?.hints?.[metric as string]}
            nullHint={bankMetrics ? 'Поле не заполнено в отчёте' : 'Нет банковских данных за период'}
          />
          {byOverdue && (
            <span
              className="metric-flag"
              title="Посчитано по ссудам с задержкой платежа свыше 90 дней: разбивку по стадиям эмитент за этот год не раскрыл. Просрочка уже Стадии 3 — реструктурированные кредиты, по которым платежи идут, в неё не попадают, поэтому доля проблемных занижена, а покрытие завышено."
            >
              !
            </span>
          )}
        </span>
      ),
    };
  };

  const income = snapshot.ltm_net_income;
  const isLoss = income !== null && income < 0;
  const negEquity = snapshot.equity !== null && snapshot.equity < 0;
  const fcfNiRow = fcfNiBadge(snapshot.fcf_to_net_income, income);
  const roeInfo = roeExplanation(snapshot, previous, profile);
  const crBand = getBand(profile, 'cr');

  const noPrice = snapshot.price_used === null || (record != null && record.shares_used === null);
  const noIncome = income === null;
  const noEquity = snapshot.equity === null;
  const noLiab = record != null && record.total_liabilities === null;
  const noCurr = record != null && (
    record.current_assets === null || record.current_liabilities === null
  );

  const peHint = isLoss
    ? 'Убыток за период — P/E не рассчитывается'
    : noIncome ? 'Нет данных о чистой прибыли (net_income)'
    : noPrice ? 'Нет цены / акций'
    : undefined;
  const pbHint = negEquity
    ? 'Отрицательный капитал — P/B не рассчитывается'
    : noEquity ? 'Нет данных о капитале (equity)'
    : noPrice ? 'Нет цены / акций'
    : undefined;
  const deHint = negEquity
    ? 'Отрицательный капитал: формула даёт отрицательный результат'
    : noLiab ? 'Нет данных об обязательствах (total_liabilities)'
    : noEquity ? 'Нет данных о капитале (equity)'
    : undefined;

  // ── Цена и оценка ──
  put(
    'price',
    yoy?.price,
    record ? <HistPriceCell row={record} /> : (snapshot.price_used !== null ? formatPerShare(snapshot.price_used) : '—'),
    !pctMode && record ? 'col-price-cell' : undefined,
  );
  if (flags.hasValuation) {
    const margin = reference !== null && snapshot.price_used !== null && reference > 0
      ? (reference - snapshot.price_used) / reference
      : null;
    const prevMargin = previousReference !== null && previous?.price_used != null && previousReference > 0
      ? (previousReference - previous.price_used) / previousReference
      : null;
    put(
      'ref',
      metricPct(reference, previousReference, 'higher_better', 'Опорная стоимость'),
      reference === null
        ? <span className="mult-cell neutral mult-cell-tip" title="Оценка за этот период не посчитана">—</span>
        : (
          <span className="hist-ref" title="Опорная стоимость по отчёту этого периода — расчёт, а не прогноз">
            {Math.abs(reference) >= 100 ? dec(Math.round(reference), 0) : formatPerShare(reference)}
          </span>
        ),
    );
    put('margin', marginChange(margin, prevMargin), <MarginCell margin={margin} />);
  }
  put(
    'cap',
    yoy?.cap,
    <HistCapCell
      marketCapMln={snapshot.market_cap}
      explanation={record?.shares_cap_explanation}
      scale={moneyScales.cap}
    />,
  );

  // ── Мультипликаторы ──
  if (flags.showRatios) {
    put('pe', yoy?.pe, (
      <MetricBadge
        value={snapshot.pe_ratio}
        level={peLevelContext(profile, snapshot.pe_ratio, income)}
        nullHint={peHint}
      />
    ));
    put('pb', yoy?.pb, (
      <PbMetricBadge
        profile={profile}
        pb={snapshot.pb_ratio}
        equity={snapshot.equity}
        pbTangible={snapshot.pb_tangible}
        goodwillShare={snapshot.goodwill_to_assets}
        intangiblesShare={snapshot.intangibles_to_equity}
        nullHint={pbHint}
      />
    ));
  }
  if (flags.hasReported) {
    // Без цвета: прибыль с разовыми статьями — не мерка для порогов отрасли,
    // строка нужна, чтобы видеть, от чего считается оценка.
    put(
      'peRep',
      metricPct(peReported, previousPeReported, 'lower_better', 'P/E по отчёту'),
      peReported === null
        ? <span className="mult-cell neutral mult-cell-tip" title="Отчётной прибыли нет или убыток">—</span>
        : (
          <span className="hist-pe-rep" title="Цена / прибыль как в отчёте, с разовыми статьями">
            {peReported > 50 ? '> 50' : dec(peReported, 1)}
          </span>
        ),
    );
  }
  if (flags.showFcf) {
    put('pfcf', yoy?.pfcf, <HistPfcfCell mode={pfcfColMode} pfcf={snapshot.price_to_fcf} fcf={snapshot.ltm_fcf} />);
  }
  put('div', yoy?.div, (
    <DividendYieldBadge
      profile={profile}
      dividendYield={dividendYield ?? record?.dividend_yield ?? null}
      dividendYieldRegular={snapshot.dividend_yield_regular}
      specialDividendsPerShare={snapshot.ltm_special_dividends_per_share}
      ltmDividendsPerShare={snapshot.ltm_dividends_per_share}
      priceUsed={snapshot.price_used}
      isPreferredShare={isPreferredShare}
    />
  ));
  if (flags.showCir) {
    out.cir = {
      className: 'col-mult col-compact col-bank',
      node: pctMode ? (
        <HistChangeCell change={bankYoY?.cir ?? YOY_NA} />
      ) : (
        <MetricBadge
          value={costToIncome ?? null}
          level={levelFor(profile, 'cir', costToIncome ?? null)}
          suffix="%"
          tip={hintFor(profile, 'cir')}
          nullHint="Нет операционных расходов или доходов в отчёте"
        />
      ),
    };
  }

  // ── Отдача ──
  if (flags.showRatios) {
    // В режиме потока порог отрасли не применяем: он откалиброван под
    // прибыль, а поток к капиталу у здоровой компании с большим капексом
    // законно ниже. Красить его красным по чужой мерке значило бы врать.
    put('roe', yoy?.roe, roeColMode === 'fcf'
      ? <FcfToEquityCell value={fcfToEquityPct(snapshot)} />
      : (
        <RoeMetricBadge
          profile={profile}
          roe={snapshot.roe}
          equity={snapshot.equity}
          explanationTip={roeInfo.tip}
          misleading={roeInfo.driver.misleading}
        />
      ));
    const spread = roeSpreadBadge(snapshot.roe_spread, snapshot.roe, snapshot.key_rate, roeInfo.source);
    put(
      'spread',
      metricPp(snapshot.roe_spread, previous?.roe_spread ?? null, 'higher_better', 'ROE сверх ключевой'),
      spread
        ? <span className={`mult-cell ${spread.level} mult-cell-tip`} title={spread.tip}>{spread.text}</span>
        : <span className="mult-cell neutral mult-cell-tip" title="Нет ключевой ставки за этот период">—</span>,
    );
  }
  if (flags.showFcf) {
    put('fcfNi', yoy?.fcfNi, <MetricBadge value={fcfNiRow.value} level={fcfNiRow.level} nullHint={fcfNiRow.nullHint} />);
  }

  // ── Долг и ликвидность ──
  if (!flags.noLeverage) {
    put('de', yoy?.de, (
      <DeMetricBadge profile={profile} de={snapshot.debt_to_equity} equity={snapshot.equity} fallbackHint={deHint} />
    ));
    put('cr', yoy?.cr, (
      <MetricBadge
        value={snapshot.current_ratio}
        level={levelFor(profile, 'cr', snapshot.current_ratio)}
        nullHint={
          noCurr
            ? 'Нет оборотных активов или краткосрочных обязательств'
            : !crBand.applicable
              ? 'CR не применим для данного типа компании'
              : undefined
        }
      />
    ));
    put('ndFcf', yoy?.ndFcf, (
      <HistNetDebtFcfCell ratio={snapshot.net_debt_to_fcf} netDebt={snapshot.net_debt} fcf={snapshot.ltm_fcf} />
    ));
    put('netDebt', yoy?.netDebt, <HistNetDebtCell netDebtMln={snapshot.net_debt} scale={moneyScales.netDebt} />, 'col-compact');
  }

  // ── Банк ──
  if (flags.isBank) {
    bank('roa', 'roa', bankYoY?.roa);
    bank('cor', 'cost_of_risk', bankYoY?.cost_of_risk);
    bank('npl', 'npl_ratio', bankYoY?.npl_ratio);
    bank('coverage', 'npl_coverage', bankYoY?.npl_coverage);
    bank('ldr', 'loans_to_deposits', bankYoY?.loans_to_deposits);
    bank('n11', 'capital_adequacy_core', bankYoY?.capital_adequacy_core);
    // Портфель — знаменатель трёх соседних показателей. Без него не отличить
    // «риск снизился» от «портфель раздули».
    put(
      'portfolio',
      bankYoY?.gross_loans,
      fmtPortfolio((bankMetrics?.gross_loans ?? null) as number | null, !!portfolioInTrillions),
      'col-portfolio',
    );
  }

  // ── Деньги ──
  put('revenue', yoy?.revenue, fmtMoney(snapshot.ltm_revenue, moneyScales.revenue));
  put('profit', yoy?.profit, fmtMoney(snapshot.ltm_net_income, moneyScales.profit), isLoss ? 'cell-loss' : undefined);
  if (flags.showFcf) {
    put(
      'fcf',
      yoy?.fcf,
      fmtMoney(snapshot.ltm_fcf, moneyScales.fcf),
      snapshot.ltm_fcf !== null && snapshot.ltm_fcf < 0 ? 'cell-loss' : undefined,
    );
    put('capex', yoy?.capex, fmtMoney(snapshot.ltm_capex, moneyScales.capex), 'col-compact');
  }

  // ── На акцию ──
  // EPS и число акций — пара, которая объясняет разрыв между «прибыль
  // выросла» и «моя прибыль выросла». Без них допэмиссия невидима.
  put(
    'eps',
    yoy?.eps,
    perShareColMode === 'fcf' ? formatPerShare(fcfPerShare(snapshot)) : formatPerShare(snapshot.eps),
    isLoss ? 'cell-loss' : undefined,
  );
  put('shares', yoy?.shares, (() => {
    const n = snapshot.shares_used;
    if (n === null || n === undefined) return '—';
    if (sharesScale) return dec(n / sharesScale.factor, 2);
    const [factor, unit] = shareScaleOf(n);
    return (
      <>
        {dec(n / factor, 2)}
        <span className="hist-shares-unit">{unit}</span>
      </>
    );
  })());

  return out;
}

/** Кнопка ⇄ у показателя с парой. */
const SwapButton: React.FC<{ label: string; title: string; onClick: () => void }> = ({ label, title, onClick }) => (
  <button type="button" className="col-toggle-btn hist-swap" onClick={onClick} title={title} aria-label={title}>
    ⇄{label && <span className="hist-swap-label"> {label}</span>}
  </button>
);

/** CR с отраслевой подсказкой — заголовок столбца или подпись строки. */
const CrHead: React.FC<{ profile: SectorProfile; as: 'th' | 'label' }> = ({ profile, as }) => {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLElement | null>(null);
  const body = (
    <>
      {as === 'th' ? 'CR' : 'Текущая ликвидность'}
      <span className="cr-header-hint-icon" aria-hidden>ⓘ</span>
      {open && <MetricTooltip profile={profile} metric="cr" anchorRef={ref} />}
    </>
  );
  const handlers = { onMouseEnter: () => setOpen(true), onMouseLeave: () => setOpen(false) };
  return as === 'th'
    ? <th ref={ref as React.Ref<HTMLTableCellElement>} className="col-mult col-cr-header" {...handlers}>{body}</th>
    : <span ref={ref as React.Ref<HTMLSpanElement>} className="hist-label-cr" {...handlers}>{body}</span>;
};

interface HistColumn {
  key: HistColKey;
  group: HistGroup;
  /** Название для выбора строк — без единиц и переключателей. */
  name: string;
  /** Заголовок столбца, когда годы идут строками. */
  th: React.ReactElement<{ className?: string }>;
  /** Подпись строки, когда годы идут колонками. */
  label: React.ReactNode;
  /** Пороги и смысл — подсказка у подписи. */
  tip?: string;
}

interface HistColumnsInput {
  profile: SectorProfile;
  flags: HistFlags;
  moneyScales: MoneyScales;
  sharesScale: { factor: number; unit: string } | null;
  portfolioInTrillions: boolean;
  hasCoreFcf: boolean;
  pfcfColMode: PfcfColMode;
  roeColMode: RoeColMode;
  perShareColMode: PerShareColMode;
  togglePfcf: () => void;
  toggleRoe: () => void;
  togglePerShare: () => void;
}

function bandTip(profile: SectorProfile, metric: Parameters<typeof hintFor>[1], what: string): string {
  const band = getBand(profile, metric);
  return [what, hintFor(profile, metric), band.note].filter(Boolean).join('\n');
}

function histColumns({
  profile,
  flags,
  moneyScales,
  sharesScale,
  portfolioInTrillions,
  hasCoreFcf,
  pfcfColMode,
  roeColMode,
  perShareColMode,
  togglePfcf,
  toggleRoe,
  togglePerShare,
}: HistColumnsInput): HistColumn[] {
  const cols: HistColumn[] = [];
  const add = (c: HistColumn) => cols.push(c);
  const money = (key: HistColKey, group: HistGroup, name: string, unit: string, tip?: string, extra = '') => add({
    key,
    group,
    name,
    tip,
    th: (
      <th key={key} className={`col-rev col-header-unit-col${extra}`} title={tip}>
        <ColHeaderWithUnit title={name} unit={unit} />
      </th>
    ),
    label: `${name}, ${unit}`,
  });

  // ── Цена и оценка ──
  add({
    key: 'price',
    group: 'Цена и оценка',
    name: 'Цена',
    tip: 'Цена на конец периода. Наведите на значение — цена на дату выхода отчёта.',
    th: (
      <th key="price" className="col-price col-header-unit-col"
        title="В ячейке — цена на дату окончания отчётного периода. Наведите для цены на дату публикации (если заполнено в отчёте).">
        <ColHeaderWithUnit title="Цена" unit="₽" align="right" />
      </th>
    ),
    label: 'Цена, ₽',
  });
  if (flags.hasValuation) {
    add({
      key: 'ref',
      group: 'Цена и оценка',
      name: 'Опорная стоимость',
      tip: 'Опорная стоимость по отчёту этого периода: нормальная прибыль × множитель. Расчёт, а не прогноз.',
      th: (
        <th key="ref" className="col-price col-header-unit-col" title="Опорная стоимость по отчёту этого периода">
          <ColHeaderWithUnit title="Опорная" unit="₽" align="right" />
        </th>
      ),
      label: <span className="hist-label-ref">Опорная стоимость, ₽</span>,
    });
    add({
      key: 'margin',
      group: 'Цена и оценка',
      name: 'Запас прочности',
      tip: 'Насколько цена ниже опорной. Зелёным — запас 15% и больше; «×2,3» — цена выше опорной в 2,3 раза.',
      th: <th key="margin" className="col-mult" title="Насколько цена ниже опорной стоимости">Запас</th>,
      label: 'Запас прочности',
    });
  }
  money('cap', 'Цена и оценка', 'Кап.', moneyScales.cap.unit, 'Капитализация по акциям в обращении');
  cols[cols.length - 1].label = `Капитализация, ${moneyScales.cap.unit}`;
  cols[cols.length - 1].name = 'Капитализация';

  // ── Мультипликаторы ──
  if (flags.showRatios) {
    add({
      key: 'pe',
      group: 'Мультипликаторы',
      name: 'P/E',
      tip: [bandTip(profile, 'pe', 'Цена / прибыль без разовых статей.'), PE_BASIS_TIP].join('\n\n'),
      th: <th key="pe" className="col-mult" title={PE_BASIS_TIP}>P/E</th>,
      label: 'P/E',
    });
    if (flags.hasReported) {
      add({
        key: 'peRep',
        group: 'Мультипликаторы',
        name: 'P/E по отчёту',
        tip: 'Цена / прибыль как в отчёте, с разовыми статьями. От неё считается оценка стоимости; '
          + 'P/E строкой выше — от прибыли без разовых, если аналитик их выделил.',
        th: <th key="peRep" className="col-mult" title="Цена / прибыль как в отчёте, с разовыми статьями">P/E отч.</th>,
        label: 'P/E по отчёту',
      });
    }
    add({
      key: 'pb',
      group: 'Мультипликаторы',
      name: 'P/B',
      tip: bandTip(profile, 'pb', 'Цена / балансовая стоимость.'),
      th: <th key="pb" className="col-mult">P/B</th>,
      label: 'P/B',
    });
  }
  if (flags.showFcf) {
    const pfcfName = pfcfColMode === 'pfcf' ? 'P/FCF' : 'FCF-доходность';
    add({
      key: 'pfcf',
      group: 'Мультипликаторы',
      name: 'P/FCF',
      tip: pfcfColMode === 'pfcf'
        ? 'Капитализация / свободный поток. ≤ 15 хорошо, ≤ 25 терпимо.'
        : 'Свободный поток / капитализация, %. ≥ 6,7% хорошо, ≥ 4% терпимо.',
      th: <HistPfcfHeader key="pfcf" mode={pfcfColMode} onToggle={togglePfcf} />,
      label: (
        <>
          {pfcfColMode === 'pfcf' ? 'P/FCF' : 'FCF-доходность, %'}
          <SwapButton label={pfcfColMode === 'pfcf' ? 'доходность' : 'P/FCF'} title={`Показать ${pfcfColMode === 'pfcf' ? 'FCF-доходность' : 'P/FCF'} вместо ${pfcfName}`} onClick={togglePfcf} />
        </>
      ),
    });
  }
  add({
    key: 'div',
    group: 'Мультипликаторы',
    name: 'Дивидендная доходность',
    tip: bandTip(profile, 'dy', 'Дивиденды за 12 месяцев / цена.'),
    th: <th key="div" className="col-mult col-header-unit-col"><ColHeaderWithUnit title="Div" unit="%" align="right" /></th>,
    label: 'Дивидендная доходность, %',
  });
  if (flags.showCir) {
    add({
      key: 'cir',
      group: 'Мультипликаторы',
      name: 'Расходы / доходы',
      tip: 'Cost/Income: операционные расходы к операционным доходам',
      th: (
        <th key="cir" className="col-mult col-compact col-bank col-header-unit-col" title="Cost/Income: операционные расходы к операционным доходам">
          <ColHeaderWithUnit title="CIR" unit="%" align="right" />
        </th>
      ),
      label: 'Расходы / доходы, %',
    });
  }

  // ── Отдача ──
  if (flags.showRatios) {
    add({
      key: 'roe',
      group: 'Отдача',
      name: 'ROE',
      tip: roeColMode === 'fcf'
        ? 'Свободный поток к капиталу, %. Порог отрасли не применяется: он откалиброван под прибыль.'
        : bandTip(profile, 'roe', 'Прибыль к капиталу, %. Наведите на значение — из чего она сложилась.'),
      th: <HistRoeHeader key="roe" mode={roeColMode} onToggle={toggleRoe} swappable={flags.showFcf} />,
      label: (
        <>
          {roeColMode === 'fcf' ? 'FCF / капитал, %' : 'ROE, %'}
          {flags.showFcf && <SwapButton label={roeColMode === 'fcf' ? 'ROE' : 'FCF/E'} title="Переключить ROE ↔ свободный поток к капиталу" onClick={toggleRoe} />}
        </>
      ),
    });
    add({
      key: 'spread',
      group: 'Отдача',
      name: 'ROE сверх ключевой ставки',
      tip: 'ROE минус средняя ключевая ставка года, п.п. Ноль и ниже — держать ОФЗ выгоднее, чем капитал компании.',
      th: (
        <th key="spread" className="col-mult col-header-unit-col" title="ROE минус ключевая ставка">
          <ColHeaderWithUnit title="ROE−ставка" unit="п.п." align="right" />
        </th>
      ),
      label: 'ROE сверх ключевой ставки, п.п.',
    });
  }
  // У банка свободного потока нет, а отдачу активов нельзя поднять плечом —
  // она и встаёт в «Отдачу» рядом с ROE вместо FCF / прибыли.
  if (flags.isBank) {
    const roaTip = 'Отдача активов: прибыль / активы. В отличие от ROE её нельзя поднять плечом';
    add({
      key: 'roa',
      group: 'Отдача',
      name: 'Отдача активов',
      tip: roaTip,
      th: (
        <th key="roa" className="col-mult col-compact col-bank col-header-unit-col" title={roaTip}>
          <ColHeaderWithUnit title="ROA" unit="%" align="right" />
        </th>
      ),
      label: 'Отдача активов (ROA), %',
    });
  }
  if (flags.showFcf) {
    add({
      key: 'fcfNi',
      group: 'Отдача',
      name: 'FCF / прибыль',
      tip: 'Качество прибыли: ≥ 1 — прибыль подтверждена деньгами, 0,7–1 — норма, ниже — сомнительно.',
      th: <th key="fcfNi" className="col-mult col-compact" title="FCF / Net Income — качество прибыли">FCF/NI</th>,
      label: 'FCF / прибыль',
    });
  }

  // ── Долг и ликвидность ──
  if (!flags.noLeverage) {
    add({
      key: 'de',
      group: 'Долг и ликвидность',
      name: 'Обязательства / капитал',
      tip: bandTip(profile, 'de', 'Все обязательства к собственному капиталу.'),
      th: <th key="de" className="col-mult">D/E</th>,
      label: 'Обязательства / капитал',
    });
    add({
      key: 'cr',
      group: 'Долг и ликвидность',
      name: 'Текущая ликвидность',
      th: <CrHead key="cr" profile={profile} as="th" />,
      label: <CrHead profile={profile} as="label" />,
    });
    add({
      key: 'ndFcf',
      group: 'Долг и ликвидность',
      name: 'Чистый долг / FCF',
      tip: 'Сколько лет свободного потока нужно, чтобы погасить чистый долг. ≤ 3 хорошо, ≤ 5 терпимо; отрицательный — денег больше, чем долга.',
      th: <th key="ndFcf" className="col-mult col-compact" title="Net Debt / LTM FCF — лет погашения">ND/FCF</th>,
      label: 'Чистый долг / FCF, лет',
    });
    add({
      key: 'netDebt',
      group: 'Долг и ликвидность',
      name: 'Чистый долг',
      tip: 'Долг минус денежные средства. Отрицательный — денег больше, чем займов.',
      th: (
        <th key="netDebt" className="col-rev col-compact col-net-debt-header col-header-unit-col" title="Чистый долг = Долг − Наличность">
          <ColHeaderWithUnit title="Net Debt" unit={moneyScales.netDebt.unit} uppercase={false} align="right" />
        </th>
      ),
      label: `Чистый долг, ${moneyScales.netDebt.unit}`,
    });
  }

  // ── Банк ──
  if (flags.isBank) {
    const bankCol = (key: HistColKey, short: string, name: string, tip: string, unit = '%') => add({
      key,
      group: 'Банк',
      name,
      tip,
      th: (
        <th key={key} className="col-mult col-compact col-bank col-header-unit-col" title={tip}>
          <ColHeaderWithUnit title={short} unit={unit} align="right" />
        </th>
      ),
      label: `${name}, ${unit}`,
    });
    bankCol('cor', 'CoR', 'Стоимость риска', 'Стоимость риска: резерв за период / кредитный портфель');
    bankCol('npl', 'NPL', 'Доля проблемных', 'Доля обесцененных кредитов (Stage 3 / 90+) в портфеле');
    bankCol('coverage', 'Покрытие', 'Покрытие резервами', 'Накопленный резерв к обесцененным кредитам (Стадия 3 + POCI)');
    bankCol('ldr', 'LDR', 'Кредиты / депозиты', 'Чистые кредиты к средствам клиентов');
    bankCol('n11', 'Н1.1', 'Достаточность капитала', 'Достаточность основного капитала (Н1.1 / CET1)');
    const unit = portfolioInTrillions ? 'трлн ₽' : 'млрд ₽';
    add({
      key: 'portfolio',
      group: 'Банк',
      name: 'Кредитный портфель',
      tip: 'Кредитный портфель до вычета резерва — знаменатель ROA, стоимости риска и доли проблемных',
      th: (
        <th key="portfolio" className="col-rev col-portfolio col-header-unit-col"
          title="Кредитный портфель до вычета резерва — знаменатель ROA, стоимости риска и доли проблемных">
          <ColHeaderWithUnit title="Портфель" unit={unit} />
        </th>
      ),
      label: `Кредитный портфель, ${unit}`,
    });
  }

  // ── Деньги ──
  money('revenue', 'Деньги', 'Выручка', moneyScales.revenue.unit);
  money('profit', 'Деньги', 'Прибыль', moneyScales.profit.unit, 'Чистая прибыль без разовых статей, если аналитик их выделил');
  if (flags.showFcf) {
    const fcfTip = hasCoreFcf
      ? 'FCF ядра = Операционный поток − CAPEX − приток от роста банковского баланса'
      : 'FCF = Операционный поток − CAPEX';
    money('fcf', 'Деньги', hasCoreFcf ? 'FCF ядра' : 'FCF', moneyScales.fcf.unit, fcfTip);
    cols[cols.length - 1].label = `${hasCoreFcf ? 'Свободный поток ядра' : 'Свободный поток'}, ${moneyScales.fcf.unit}`;
    cols[cols.length - 1].name = 'Свободный поток';
    money('capex', 'Деньги', 'CAPEX', moneyScales.capex.unit, 'Капитальные затраты', ' col-compact');
    cols[cols.length - 1].label = `Капзатраты, ${moneyScales.capex.unit}`;
    cols[cols.length - 1].name = 'Капзатраты';
  }

  // ── На акцию ──
  add({
    key: 'eps',
    group: 'На акцию',
    name: 'Прибыль на акцию',
    tip: perShareColMode === 'fcf'
      ? 'Свободный поток на акцию — та же шкала, что у EPS'
      : 'Прибыль на акцию от тех же акций, что и капитализация: цена / EPS в точности равна P/E этого периода',
    th: <HistPerShareHeader key="eps" mode={perShareColMode} onToggle={togglePerShare} swappable={flags.showFcf} />,
    label: (
      <>
        {perShareColMode === 'fcf' ? 'Поток на акцию, ₽' : 'Прибыль на акцию, ₽'}
        {flags.showFcf && <SwapButton label={perShareColMode === 'fcf' ? 'EPS' : 'FCF/акц'} title="Переключить прибыль на акцию ↔ поток на акцию" onClick={togglePerShare} />}
      </>
    ),
  });
  const sharesTip =
    'Число акций, использованных в капитализации. '
    + (sharesScale ? '' : 'После дробления счёт меняется на порядки, поэтому единица стоит у каждого значения. ')
    + 'В режиме «изменение» показывает размытие: рост — доля акционера уменьшилась, выкуп — увеличилась';
  add({
    key: 'shares',
    group: 'На акцию',
    name: 'Акций в обращении',
    tip: sharesTip,
    th: (
      <th key="shares" className={`col-mult col-compact col-shares-header${sharesScale ? ' col-header-unit-col' : ''}`} title={sharesTip}>
        {sharesScale ? <ColHeaderWithUnit title="Акций" unit={sharesScale.unit} align="right" /> : 'Акций'}
      </th>
    ),
    label: sharesScale ? `Акций в обращении, ${sharesScale.unit}` : 'Акций в обращении',
  });

  return cols;
}

interface HistTableProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
  profile: SectorProfile;
  /** Тикер представляет привилегированные акции — влияет на отображение Div. Yield */
  isPreferredShare?: boolean;
  /** report_id → банковские показатели этого отчёта (пусто у небанков) */
  bankMetricsByReport?: Map<number, BankMetrics>;
  /**
   * Банковские показатели строки LTM. Отдельно от `bankMetricsByReport`,
   * потому что считаются не по одному отчёту: потоки берутся за скользящий
   * год, а баланс — с последнего отчёта.
   */
  ltmBankMetrics?: BankMetrics | null;
  /** Холдинг: P/E, P/B, ROE и плечо по консолидации не выводятся. */
  isHolding?: boolean;
  pctMode: boolean;
  orientation?: SheetOrientation;
  /** Скрытые читателем показатели. */
  hidden?: ReadonlySet<HistColKey>;
  /** Опорная стоимость по годам отчёта и на сегодня. Без них столбцов оценки нет. */
  referenceByYear?: Map<number, number | null>;
  ltmReference?: number | null;
  /** Прибыль как в отчёте по годам (млн) и прибыль на акцию за 12 месяцев. */
  reportedProfitByYear?: Map<number, number | null>;
  ltmReportedEps?: number | null;
  /** Годы колонками: сколько ранних лет скрыто и как их раскрыть. */
  earlierHidden?: number;
  onToggleEarlier?: () => void;
  earlierShown?: boolean;
  /** Отдаёт наружу список столбцов — для выбора строк. */
  onColumns?: (columns: HistColumn[]) => void;
}

/**
 * Годы строками — таблица широкая, и производные показатели в ней лишние:
 * запас прочности читается по соседним «Цена» и «Опорная», спред ROE — в
 * подсказке у ROE. Освободившееся место нужно EPS и числу акций.
 */
const ROWS_ONLY_HIDDEN: ReadonlySet<HistColKey> = new Set<HistColKey>(['margin', 'spread', 'peRep']);

/**
 * Лист «годы в колонках» → таблица для выгрузки. Берётся то, что нарисовано:
 * подписи с единицами и числа как на экране — так файл не разойдётся с
 * карточкой. Кнопки-переключатели из подписей вырезаются.
 */
function sheetFromColsTable(table: HTMLTableElement, title: string): Sheet {
  const textOf = (el: Element) => {
    const copy = el.cloneNode(true) as HTMLElement;
    copy.querySelectorAll('button').forEach((b) => b.remove());
    return copy.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  };
  const headRow = table.tHead?.rows[table.tHead.rows.length - 1];
  const header = ['Показатель', ...Array.from(headRow?.cells ?? []).slice(1).map((c) => {
    const t = textOf(c);
    return t === '12 мес.' ? '12 мес. (LTM)' : t;
  })];
  const rows: Sheet['rows'] = [];
  Array.from(table.tBodies[0]?.rows ?? []).forEach((tr) => {
    if (tr.classList.contains('hist-group-row')) {
      rows.push({ cells: [textOf(tr.cells[0])], group: true });
      return;
    }
    const [label, ...cells] = Array.from(tr.cells);
    rows.push({ cells: [textOf(label), ...cells.map((c) => parseCellText(textOf(c)))] });
  });
  return { title, header, rows };
}

const yearOf = (r: MultiplierRecord) => r.fiscal_year ?? Number(String(r.date).slice(0, 4));

const HistTable: React.FC<HistTableProps> = ({
  rows,
  currentRow,
  profile,
  isPreferredShare = false,
  pctMode,
  bankMetricsByReport,
  ltmBankMetrics,
  isHolding = false,
  orientation = 'rows',
  hidden,
  referenceByYear,
  ltmReference = null,
  reportedProfitByYear,
  ltmReportedEps = null,
  earlierHidden = 0,
  onToggleEarlier,
  earlierShown = false,
  onColumns,
}) => {
  const [pfcfColMode, setPfcfColMode] = React.useState<PfcfColMode>('pfcf');
  // Прибыль или деньги: ROE и «на акцию» переключаются на свободный поток.
  const [roeColMode, setRoeColMode] = React.useState<RoeColMode>('profit');
  const [perShareColMode, setPerShareColMode] = React.useState<PerShareColMode>('eps');

  const hasValuation = Boolean(referenceByYear && referenceByYear.size > 0);
  const hasReported = Boolean(reportedProfitByYear && reportedProfitByYear.size > 0);
  const flags = histFlags(profile, isHolding, hasValuation, hasReported);
  const peReportedOf = (r: MultiplierRecord | undefined): number | null => {
    if (!r) return null;
    const profit = reportedProfitByYear?.get(yearOf(r)) ?? null;
    return profit !== null && profit > 0 && r.market_cap != null ? r.market_cap / profit : null;
  };
  const ltmPeReported = currentRow?.price_used != null && ltmReportedEps !== null && ltmReportedEps > 0
    ? currentRow.price_used / ltmReportedEps
    : null;

  // Поток ядра приходит только у гибридов. Если он есть хоть в одной строке,
  // столбец показывает именно его — и заголовок обязан об этом сказать.
  const hasCoreFcf =
    rows.some((r) => r.ltm_core_fcf != null) || currentRow?.ltm_core_fcf != null;

  // Единица числа акций — одна на столбец, если значения одного порядка.
  const sharesScale = React.useMemo(() => {
    const values: number[] = [];
    if (currentRow?.shares_used != null) values.push(currentRow.shares_used);
    rows.forEach((r) => r.shares_used != null && values.push(r.shares_used));
    return shareColumnScale(values);
  }, [rows, currentRow]);

  // Единицы денежных столбцов — по самому крупному значению каждого,
  // включая LTM: иначе единица «поедет» на первой же публикации.
  const moneyScales = React.useMemo<MoneyScales>(() => {
    const snapshots = rows.map(snapshotFromRecord);
    if (currentRow) snapshots.push(snapshotFromCurrent(currentRow));
    const scaleOf = (pick: (s: HistRowSnapshot) => number | null | undefined) =>
      moneyColumnScale(snapshots.map(pick));
    return {
      cap: scaleOf((s) => s.market_cap),
      netDebt: scaleOf((s) => s.net_debt),
      fcf: scaleOf((s) => s.ltm_fcf),
      capex: scaleOf((s) => s.ltm_capex),
      revenue: scaleOf((s) => s.ltm_revenue),
      profit: scaleOf((s) => s.ltm_net_income),
    };
  }, [rows, currentRow]);

  const portfolioInTrillions = React.useMemo(() => {
    const values: number[] = [];
    const push = (m: BankMetrics | null | undefined) => {
      const v = m?.gross_loans;
      if (typeof v === 'number') values.push(Math.abs(v));
    };
    push(ltmBankMetrics);
    rows.forEach((r) => r.report_id != null && push(bankMetricsByReport?.get(r.report_id)));
    return values.some((v) => v >= PORTFOLIO_TRILLION_THRESHOLD_MLN);
  }, [rows, bankMetricsByReport, ltmBankMetrics]);

  const allColumns = histColumns({
    profile,
    flags,
    moneyScales,
    sharesScale,
    portfolioInTrillions,
    hasCoreFcf,
    pfcfColMode,
    roeColMode,
    perShareColMode,
    togglePfcf: () => setPfcfColMode((m) => (m === 'pfcf' ? 'yield' : 'pfcf')),
    toggleRoe: () => setRoeColMode((m) => (m === 'profit' ? 'fcf' : 'profit')),
    togglePerShare: () => setPerShareColMode((m) => (m === 'eps' ? 'fcf' : 'eps')),
  });
  const columnKeys = allColumns.map((c) => c.key).join(',');
  React.useEffect(() => {
    onColumns?.(allColumns);
    // Список меняется только с набором ключей; подписи с переключателями
    // пересобираются на каждом рендере и наружу не нужны.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnKeys]);
  const columns = allColumns.filter(
    (c) => !hidden?.has(c.key) && !(orientation === 'rows' && ROWS_ONLY_HIDDEN.has(c.key)),
  );

  // ── Периоды: LTM и годовые, свежие первыми ──
  interface Period {
    id: string;
    label: React.ReactNode;
    isLtm: boolean;
    cells: HistCells;
  }
  const common = {
    pctMode,
    pfcfColMode,
    roeColMode,
    perShareColMode,
    profile,
    isPreferredShare,
    portfolioInTrillions,
    moneyScales,
    sharesScale,
    flags,
  };
  // Опорная посчитана на нынешние акции, а строка хранит цену и прибыль как
  // торговались тогда. Через сплит их надо привести к одному масштабу —
  // к масштабу строки, иначе у Белуги до дробления 8:1 запас выходил «×17».
  const refOf = (r: MultiplierRecord | undefined) => {
    const ref = r ? referenceByYear?.get(yearOf(r)) ?? null : null;
    return ref === null || !r ? ref : ref * (r.shares_split_factor ?? 1);
  };
  const yoyOf = (cur: HistRowSnapshot, prev: HistRowSnapshot | null) =>
    pctMode && prev ? computeHistRowYoY(cur, prev, pfcfColMode, roeColMode, perShareColMode) : null;

  const periods: Period[] = [];
  if (currentRow) {
    const snapshot = snapshotFromCurrent(currentRow);
    const previous = rows.length > 0 ? snapshotFromRecord(rows[0]) : null;
    periods.push({
      id: 'ltm',
      isLtm: true,
      label: <span className="badge-ltm" title="Последние 12 месяцев">LTM</span>,
      cells: histRowCells({
        ...common,
        snapshot,
        previous,
        dividendYield: currentRow.dividend_yield,
        yoy: yoyOf(snapshot, previous),
        // Потоковые показатели (ROA, маржа, стоимость риска) — за скользящий
        // год, балансовые — с отчёта `balance_report_id`.
        bankMetrics:
          ltmBankMetrics ??
          (currentRow.balance_report_id != null ? bankMetricsByReport?.get(currentRow.balance_report_id) : null),
        costToIncome: currentRow.cost_to_income,
        previousBankMetrics:
          rows.length > 0 && rows[0].report_id != null ? bankMetricsByReport?.get(rows[0].report_id) : null,
        previousCostToIncome: rows.length > 0 ? rows[0].cost_to_income : null,
        reference: ltmReference,
        previousReference: refOf(rows[0]),
        peReported: ltmPeReported,
        previousPeReported: peReportedOf(rows[0]),
      }),
    });
  }
  rows.forEach((r, index) => {
    const snapshot = snapshotFromRecord(r);
    const prevRecord = index + 1 < rows.length ? rows[index + 1] : undefined;
    const previous = prevRecord ? snapshotFromRecord(prevRecord) : null;
    periods.push({
      id: String(r.id),
      isLtm: false,
      label: periodLabel(r),
      cells: histRowCells({
        ...common,
        record: r,
        snapshot,
        previous,
        yoy: yoyOf(snapshot, previous),
        bankMetrics: r.report_id != null ? bankMetricsByReport?.get(r.report_id) : null,
        costToIncome: r.cost_to_income,
        previousBankMetrics:
          prevRecord?.report_id != null ? bankMetricsByReport?.get(prevRecord.report_id) : null,
        previousCostToIncome: prevRecord ? prevRecord.cost_to_income : null,
        reference: refOf(r),
        previousReference: refOf(prevRecord),
        peReported: peReportedOf(r),
        previousPeReported: peReportedOf(prevRecord),
      }),
    });
  });

  // Годы колонками открываются на свежих: справа LTM и последние годы,
  // ранние — прокруткой влево. На узком экране иначе видно только 2016-й.
  const colsWrapRef = React.useRef<HTMLDivElement | null>(null);
  React.useLayoutEffect(() => {
    const el = colsWrapRef.current;
    if (orientation !== 'cols' || !el) return undefined;
    el.scrollLeft = el.scrollWidth;
    // На телефоне лист лежит на скрытой вкладке: ширины у него нет, пока
    // вкладку не открыли. Прокручиваем, когда она появляется.
    if (typeof ResizeObserver === 'undefined') return undefined;
    let wasHidden = el.clientWidth === 0;
    const observer = new ResizeObserver(() => {
      if (wasHidden && el.clientWidth > 0) el.scrollLeft = el.scrollWidth;
      wasHidden = el.clientWidth === 0;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [orientation, periods.length]);

  if (periods.length === 0) {
    return (
      <div className="hist-table-wrapper">
        <table className="hist-table"><tbody><tr>
          <td className="table-empty">Нет данных. Добавьте годовые отчёты и нажмите «Обновить цену».</td>
        </tr></tbody></table>
      </div>
    );
  }

  // Группы подряд: подпись группы над её столбцами (годы строками) или
  // отдельной строкой над её показателями (годы колонками).
  const groupRuns: { group: HistGroup; columns: HistColumn[] }[] = [];
  columns.forEach((c) => {
    const last = groupRuns[groupRuns.length - 1];
    if (last && last.group === c.group) last.columns.push(c);
    else groupRuns.push({ group: c.group, columns: [c] });
  });

  if (orientation === 'cols') {
    // Старые годы слева, свежие справа, LTM — последней колонкой.
    const ordered = [...periods].reverse();
    return (
      <div
        ref={colsWrapRef}
        className={`hist-table-wrapper hist-table-wrapper--cols${pctMode ? ' hist-table-wrapper--pct' : ''}`}
      >
        <table className="hist-table hist-table--cols" style={{ '--periods': ordered.length } as React.CSSProperties}>
          <thead>
            <tr>
              <th className="col-label">
                {earlierHidden > 0 || earlierShown ? (
                  <button type="button" className="hist-earlier" onClick={onToggleEarlier}>
                    {earlierShown ? 'Скрыть ранние' : `← ещё ${earlierHidden} ${plural(earlierHidden, 'год', 'года', 'лет')}`}
                  </button>
                ) : null}
              </th>
              {ordered.map((p) => (
                <th key={p.id} className={p.isLtm ? 'col-period col-period--ltm' : 'col-period'}>
                  {p.isLtm ? <span title="Последние 12 месяцев">12 мес.</span> : p.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groupRuns.map((run) => (
              <React.Fragment key={run.group}>
                <tr className="hist-group-row">
                  <th colSpan={ordered.length + 1} scope="rowgroup"><span>{run.group}</span></th>
                </tr>
                {run.columns.map((c) => (
                  <tr key={c.key}>
                    <th scope="row" className="col-label" title={c.tip}>
                      <span className={c.tip ? 'hist-label hist-label--tip' : 'hist-label'}>{c.label}</span>
                    </th>
                    {ordered.map((p) => {
                      const cell = p.cells[c.key];
                      return (
                        <td key={p.id} className={[cell?.className, p.isLtm ? 'cell-ltm' : ''].filter(Boolean).join(' ') || undefined}>
                          {cell?.node ?? '—'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className={`hist-table-wrapper${pctMode ? ' hist-table-wrapper--pct' : ''}`}>
      <table className="hist-table">
        <thead>
          <tr className="hist-group-head">
            <th className="col-year" />
            {groupRuns.map((run) => (
              <th key={run.group} colSpan={run.columns.length} className="hist-group-th">
                <span>{run.group}</span>
              </th>
            ))}
          </tr>
          <tr>
            <th className="col-year">Период</th>
            {columns.map((c) => React.cloneElement(c.th, {
              key: c.key,
              className: [c.th.props.className, groupRuns.some((g) => g.columns[0].key === c.key) ? 'col-group-start' : '']
                .filter(Boolean).join(' '),
            }))}
          </tr>
        </thead>
        <tbody>
          {periods.map((p) => (
            <tr key={p.id} className={p.isLtm ? 'row-ltm' : 'row-hist'}>
              <td className="col-year">{p.label}</td>
              {columns.map((c) => {
                const cell = p.cells[c.key];
                const start = groupRuns.some((g) => g.columns[0].key === c.key);
                return (
                  <td key={c.key} className={[cell?.className, start ? 'col-group-start' : ''].filter(Boolean).join(' ') || undefined}>
                    {cell?.node ?? '—'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

/**
 * Глубина истории: сколько полных лет стоит за показателями.
 *
 * Все пороги в карточках — проверки одного среза: P/E ≤ 20, ROE ≥ 20%.
 * Компания с двумя годами данных проходит их автоматически, потому что
 * проверять нечего. Грэм требовал десять лет прибыли и двадцать дивидендов
 * именно поэтому: его критерии про устойчивость, а не про уровень.
 *
 * Зелёный экран без этой строки читается как «проверка пройдена», хотя
 * означает лишь «сейчас в норме». Здесь мы честно говорим, на скольких годах
 * основан вывод.
 */
const GRAHAM_YEARS = 10;
const ENOUGH_YEARS = 7;

const HistoryDepth: React.FC<{ years: number }> = ({ years }) => {
  if (years <= 0) return null;
  const level = years >= GRAHAM_YEARS ? 'good' : years >= ENOUGH_YEARS ? 'warn' : 'thin';
  const word = years === 1 ? 'год' : years >= 2 && years <= 4 ? 'года' : 'лет';
  return (
    <div
      className={`mult-depth mult-depth--${level}`}
      title={
        years >= GRAHAM_YEARS
          ? `${years} ${word} годовых отчётов — Грэм считал достаточным десять.`
          : `${years} ${word} годовых отчётов. Грэм требовал десять лет прибыли: ` +
            'пороги ниже проверяют только текущий срез и на короткой истории ' +
            'проходятся почти автоматически. Устойчивость по ним не видна.'
      }
    >
      <span className="mult-depth-value">{years}</span>
      <span className="mult-depth-label">
        {word} данных
        {years < GRAHAM_YEARS && <span className="mult-depth-of"> из 10 по Грэму</span>}
      </span>
    </div>
  );
};

/**
 * Метод анализа компании. Порядок — от самого частого к редкому; подсказки
 * объясняют, чем тип отличается, потому что цена ошибки высокая: не тот тип
 * даёт компании чужие метрики.
 */
const COMPANY_TYPE_OPTIONS: { value: CompanyType; label: string; hint: string }[] = [
  { value: 'industrial', label: 'Обычный бизнес', hint: 'Полный набор тестов Грэма' },
  { value: 'lender', label: 'Кредитор (банк, МФО, лизинг)', hint: 'Активы — займы: CoR, NPL, Н1; без FCF, D/E и Current Ratio' },
  { value: 'insurance', label: 'Страховщик', hint: 'Резервы и комбинированный коэффициент; банковские метрики неприменимы' },
  { value: 'holding', label: 'Холдинг', hint: 'Владеет долями и сам не оперирует: оценка по NAV, а не по мультипликаторам консолидации' },
  { value: 'hybrid', label: 'Гибрид (операционка + финбизнес)', hint: 'Яндекс: финсегмент раздувает баланс и поток — оценивать отдельно' },
  { value: 'exchange', label: 'Биржа / клиринг / депозитарий', hint: 'МОЕХ: баланс раздут чужими деньгами и зеркальными позициями клиринга — без D/E и Current Ratio, но с FCF без клиентских денег' },
];

interface MultipliersPanelProps {
  company: Company;
  /**
   * Отчёты компании — источник банковских показателей для таблицы истории.
   * Они считаются из полей отчёта, а не из цены, поэтому лежат в отчёте, а не
   * в кэше мультипликаторов. Панель работает и без них: у небанков колонок нет.
   */
  reports?: FinancialReport[];
}

/** Сколько лет видно в листе, когда годы идут колонками, — пока ширина
 *  экрана не измерена. Дальше лет показывается столько, сколько влезает:
 *  растягивать десять колонок на широкий экран значит раздувать клетки
 *  пустотой, а место лучше отдать истории. */
const SHEET_COLS_YEARS = 10;
const SHEET_COLS_MIN = 5;
const SHEET_ORIENTATION_KEY = 'ga.sheet.orientation';
const SHEET_HIDDEN_KEY = 'ga.sheet.hidden';

function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // приватное окно или запрет хранилища — выбор просто не запомнится
  }
}

/** Переключатель из двух-трёх положений. */
function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: { key: T; label: string; title?: string }[];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <span className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={value === o.key}
          className={value === o.key ? 'seg-btn is-on' : 'seg-btn'}
          title={o.title}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </span>
  );
}

/** Какие показатели показывать: список с галочками, сгруппированный как таблица. */
const RowsChooser: React.FC<{
  columns: HistColumn[];
  hidden: ReadonlySet<HistColKey>;
  onChange: (next: Set<HistColKey>) => void;
  noun: string;
}> = ({ columns, hidden, onChange, noun }) => {
  const [open, setOpen] = useState(false);
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  const shown = columns.filter((c) => !hidden.has(c.key)).length;
  const groups = HIST_GROUPS.filter((g) => columns.some((c) => c.group === g));
  const toggle = (key: HistColKey) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  };
  return (
    <div className="rows-chooser" ref={rootRef}>
      <button type="button" className="rows-chooser-btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {noun}: {shown} из {columns.length} ▾
      </button>
      {open && (
        <div className="rows-chooser-pop" role="dialog" aria-label="Какие показатели показывать">
          {groups.map((g) => (
            <div key={g} className="rows-chooser-group">
              <div className="rows-chooser-group-title">{g}</div>
              {columns.filter((c) => c.group === g).map((c) => (
                <label key={c.key} className="rows-chooser-item">
                  <input type="checkbox" checked={!hidden.has(c.key)} onChange={() => toggle(c.key)} />
                  {c.name}
                </label>
              ))}
            </div>
          ))}
          {hidden.size > 0 && (
            <button type="button" className="rows-chooser-reset" onClick={() => onChange(new Set())}>
              Показать все
            </button>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Пояснение по нажатию — для экранов без наведения. Подсказки в таблице живут
 * в атрибуте title, а на телефоне его не увидеть: здесь нажатие на ячейку с
 * подсказкой поднимает её текст в панель снизу.
 */
const TouchTip: React.FC<{ tip: { head: string; body: string } | null; onClose: () => void }> = ({ tip, onClose }) => {
  if (!tip) return null;
  return createPortal(
    <div className="touch-tip" role="dialog" aria-label={tip.head} onClick={onClose}>
      <div className="touch-tip-sheet" onClick={(e) => e.stopPropagation()}>
        <span className="touch-tip-grip" aria-hidden />
        <div className="touch-tip-head">{tip.head}</div>
        <div className="touch-tip-body">{tip.body}</div>
        <button type="button" className="touch-tip-close" onClick={onClose}>Понятно</button>
      </div>
    </div>,
    document.body,
  );
};

const MultipliersPanel: React.FC<MultipliersPanelProps> = ({ company, reports }) => {
  const { isAdmin, checking: adminChecking } = useAdmin();
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  const [histPctMode, setHistPctMode] = useState(false);
  /** После первого sync цены с T-Invest можно грузить current-мультипликаторы. */
  const [initialPriceSynced, setInitialPriceSynced] = useState(false);
  const queryClient = useQueryClient();

  const companyId = company.id!;

  // Строка таблицы знает свой report_id — по нему и находим показатели.
  const bankMetricsByReport = React.useMemo(() => {
    const map = new Map<number, BankMetrics>();
    for (const report of reports ?? []) {
      if (report.bank_metrics) map.set(report.id, report.bank_metrics);
    }
    return map;
  }, [reports]);

  // Банковские показатели за скользящий год: собираются из трёх отчётов, а
  // значит только на бэкенде. Ключ тот же, что у карточки банка, — React Query
  // отдаст обоим один ответ.
  const { data: ltmBankMetrics } = useQuery({
    queryKey: ['bank-metrics-ltm', companyId],
    queryFn: () => getLtmBankMetrics(companyId),
    enabled: bankMetricsByReport.size > 0,
    retry: false,
  });

  const { data: currentData, isLoading: currentLoading, error: currentError } = useQuery({
    queryKey: ['multipliers-current', companyId],
    queryFn: () => getCompanyCurrentMultipliers(companyId),
    enabled: initialPriceSynced,
    retry: false,
  });

  // Профиль приходит вместе с мультипликаторами; пока их нет — классический Грэм.
  const profile = currentData?.sector_profile ?? GRAHAM_FALLBACK;

  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['multipliers-history', companyId, 'report_based'],
    queryFn: () => getCompanyMultipliersHistory(companyId, 'report_based', 20),
    retry: false,
  });

  const { data: profileOptions } = useQuery({
    queryKey: ['sector-profiles'],
    queryFn: getSectorProfiles,
    staleTime: Infinity,
  });

  // Закрепление профиля за компанией: сектор из T-Invest слишком крупный,
  // поэтому аналитик может выбрать пороги вручную и сразу увидеть перекраску.
  const typeMutation = useMutation({
    mutationFn: (value: CompanyType) => updateCompanyType(companyId, value),
    onSuccess: () => {
      // Тип меняет набор полей отчётов, значит и мультипликаторы, и историю.
      queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['company'] });
    },
    onError: (e: unknown) => window.alert(formatApiErrorMessage(e, 'Не удалось сменить тип компании')),
  });

  const profileMutation = useMutation({
    mutationFn: (key: string | null) => updateCompanySectorProfile(companyId, key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
      // Ключ карточки компании хранит id строкой из useParams — инвалидируем
      // по префиксу, иначе точное совпадение по числу не сработает.
      queryClient.invalidateQueries({ queryKey: ['company'] });
    },
  });

  // Ручное обновление по кнопке — с тостом успеха/ошибки.
  const refreshMutation = useMutation({
    mutationFn: () => refreshCompanyMultipliers(companyId),
    onSuccess: (res) => {
      setRefreshMsg(
        res.success
          ? `✓ Цена обновлена: ${formatPerShare(res.price)} ₽`
          : '⚠ Не удалось получить цену из T-Invest API',
      );
      queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
      queryClient.invalidateQueries({ queryKey: ['company', companyId] });
      setTimeout(() => setRefreshMsg(null), 4000);
    },
    onError: () => {
      setRefreshMsg('✗ Ошибка при обновлении цены');
      setTimeout(() => setRefreshMsg(null), 4000);
    },
  });

  // Авто-обновление цены при заходе на карточку компании.
  // Сначала тянем цену из T-Invest, затем (через enabled) грузим current-мультипликаторы —
  // иначе useQuery успевает отрисовать устаревшие P/E, P/B и т.д.
  //
  // Не используем ref «уже обновляли» — в React StrictMode первый запрос
  // прерывается cleanup, а ref блокировал повтор на втором mount.
  useEffect(() => {
    setInitialPriceSynced(false);
  }, [companyId]);

  useEffect(() => {
    if (!companyId || adminChecking) return;
    // Гость цену не обновляет: это запись в базу, она закрыта. Цены и так
    // обновляет ежедневная задача на сервере.
    if (!isAdmin) {
      setInitialPriceSynced(true);
      return;
    }

    let disposed = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 20_000);

    setAutoRefreshing(true);

    refreshCompanyMultipliers(companyId, true, controller.signal)
      .then((res) => {
        if (disposed) return;
        queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
        queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
        queryClient.invalidateQueries({ queryKey: ['company', companyId] });
        if (res.success && res.price !== null) {
          setRefreshMsg('Цена обновлена');
        } else {
          setRefreshMsg('⚠ Не удалось получить актуальную цену');
        }
        setTimeout(() => setRefreshMsg(null), 3500);
      })
      .catch((err) => {
        if (disposed) return;
        const isAbort =
          err?.name === 'CanceledError' ||
          err?.code === 'ERR_CANCELED' ||
          err?.message === 'canceled';
        if (!isAbort) {
          // eslint-disable-next-line no-console
          console.warn('Авто-обновление цены не удалось:', err);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
        if (!disposed) {
          setInitialPriceSynced(true);
          setAutoRefreshing(false);
        }
      });

    return () => {
      disposed = true;
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [companyId, queryClient, isAdmin, adminChecking]);

  const rows = histData ?? [];
  const [histExpanded, setHistExpanded] = React.useState(false);

  // Свежие годы сверху — их и показываем в свёрнутом виде. Отрезается хвост
  // по годам, а не по позиции в списке: порядок строк задаёт сама таблица, и
  // при другой сортировке по позиции скрылось бы не то.
  //
  // Год берётся из даты записи: отдельного поля года у записи нет, а дата —
  // это конец отчётного периода.
  const histYears = React.useMemo(() => {
    const seen = new Set<number>();
    rows.forEach((r) => {
      const year = Number(String(r.date).slice(0, 4));
      if (Number.isFinite(year)) seen.add(year);
    });
    return Array.from(seen).sort((a, b) => b - a);
  }, [rows]);
  const histCut = histYears[HIST_COLLAPSED_YEARS - 1];
  const histHidden = Math.max(0, histYears.length - HIST_COLLAPSED_YEARS);
  const histRows = histExpanded || histHidden === 0
    ? rows
    : rows.filter((r) => Number(String(r.date).slice(0, 4)) >= histCut);

  // Холдинг: P/E, P/B и ROE по консолидации в листе не выводятся.
  const isHolding = company.company_type === 'holding';

  // ── Лист по годам ──
  const [orientation, setOrientationState] = React.useState<SheetOrientation>(
    () => readStored<SheetOrientation>(SHEET_ORIENTATION_KEY, 'cols'),
  );
  const setOrientation = (next: SheetOrientation) => {
    setOrientationState(next);
    writeStored(SHEET_ORIENTATION_KEY, next);
  };
  const [hiddenCols, setHiddenColsState] = React.useState<Set<HistColKey>>(
    () => new Set(readStored<HistColKey[]>(SHEET_HIDDEN_KEY, [])),
  );
  const setHiddenCols = (next: Set<HistColKey>) => {
    setHiddenColsState(next);
    writeStored(SHEET_HIDDEN_KEY, Array.from(next));
  };
  const [sheetColumns, setSheetColumns] = React.useState<HistColumn[]>([]);
  const [earlierShown, setEarlierShown] = React.useState(false);
  const sheetRef = React.useRef<HTMLDivElement | null>(null);
  const [colsFit, setColsFit] = React.useState(SHEET_COLS_YEARS);
  const [touchTip, setTouchTip] = React.useState<{ head: string; body: string } | null>(null);
  // Выгрузка: на время скачивания рисуется полный лист вне экрана — все годы
  // и все показатели, независимо от того, что свёрнуто или скрыто у читателя.
  const [exportFormat, setExportFormat] = React.useState<ExportFormat | null>(null);
  const exportRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    if (!exportFormat) return;
    const table = exportRef.current?.querySelector('table');
    if (table) {
      const sheet = sheetFromColsTable(table, `${company.name} (${company.ticker}) — мультипликаторы и показатели по годам`);
      downloadSheet(sheet, exportFormat, `${company.ticker}_мультипликаторы`, 'Мультипликаторы');
    }
    setExportFormat(null);
  }, [exportFormat, company.name, company.ticker]);

  // Опорная по годам — тот же ряд, что ступенька на графике цены: ключ
  // общий, запрос уходит один раз.
  const { data: valuationHistory } = useQuery<ValuationHistoryOut>({
    queryKey: ['valuation-history', companyId],
    queryFn: () => fetchValuationHistory(companyId),
    staleTime: 10 * 60 * 1000,
  });
  const { data: valuationSummary } = useQuery<ValuationSummaryOut>({
    queryKey: ['valuation-summary', companyId],
    queryFn: () => fetchValuationSummary(companyId),
    staleTime: 10 * 60 * 1000,
  });
  const referenceByYear = React.useMemo(() => {
    const map = new Map<number, number | null>();
    (valuationHistory?.years ?? []).forEach((y) => map.set(y.year, y.refused ? null : y.conservative));
    return map;
  }, [valuationHistory]);
  // P/E по отчёту: прибыль годовых отчётов как в раскрытии, за 12 месяцев —
  // из ряда оценки (там LTM собран из отчётной прибыли).
  const reportedProfitByYear = React.useMemo(() => {
    const map = new Map<number, number | null>();
    (reports ?? [])
      .filter((r) => r.period_type.toLowerCase() === 'annual')
      .forEach((r) => map.set(r.fiscal_year, r.net_income_reported ?? r.net_income ?? null));
    return map;
  }, [reports]);
  const { data: valuationSeries } = useQuery<CompanySeriesOut>({
    queryKey: ['company-series', companyId, 7],
    queryFn: () => getCompanySeries(companyId, 7),
    staleTime: 10 * 60 * 1000,
  });
  const ltmReportedEps = valuationSeries?.years?.find((y) => y.ltm_label)?.eps ?? null;
  const ltmReference = valuationSummary?.available && !valuationSummary.band?.refused
    ? valuationSummary.safety?.reference ?? valuationSummary.headline?.reference ?? null
    : null;

  // Годы колонками: видно столько последних лет, сколько влезает по ширине,
  // остальные — по кнопке слева. Ширины колонок берутся из CSS таблицы.
  React.useEffect(() => {
    const el = sheetRef.current;
    if (!el || orientation !== 'cols' || typeof ResizeObserver === 'undefined') return undefined;
    const measure = () => {
      const table = el.querySelector('.hist-table--cols');
      if (!table) return;
      const css = getComputedStyle(table);
      const label = parseFloat(css.getPropertyValue('--label-w')) || 226;
      const period = parseFloat(css.getPropertyValue('--period-w')) || 78;
      // Одна колонка уходит под «12 мес.».
      const fit = Math.floor((el.clientWidth - label) / period) - 1;
      setColsFit(Math.max(SHEET_COLS_MIN, fit));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [orientation, histLoading]);
  const colsCut = histYears[Math.min(colsFit, histYears.length) - 1];
  const colsHidden = Math.max(0, histYears.length - colsFit);
  const sheetRows = orientation === 'cols'
    ? (earlierShown || colsHidden === 0 ? rows : rows.filter((r) => Number(String(r.date).slice(0, 4)) >= colsCut))
    : histRows;

  const onSheetClick = (e: React.MouseEvent) => {
    if (typeof window === 'undefined' || !window.matchMedia?.('(hover: none)').matches) return;
    const target = (e.target as HTMLElement).closest('[title]') as HTMLElement | null;
    if (!target || !e.currentTarget.contains(target)) return;
    const body = target.getAttribute('title');
    if (!body) return;
    const textOf = (el: Element | null | undefined) => {
      if (!el) return '';
      const copy = el.cloneNode(true) as HTMLElement;
      copy.querySelectorAll('button').forEach((btn) => btn.remove());
      return copy.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    };
    const cell = target.closest('td, th') as HTMLTableCellElement | null;
    const row = cell?.parentElement;
    // Годы колонками: подпись строки — показатель. Годы строками: показатель
    // в заголовке столбца, а в строке — период.
    const rowLabel = textOf(row?.querySelector('th.col-label'));
    const period = textOf(row?.querySelector('td.col-year'));
    const table = cell?.closest('table');
    const headRow = table?.tHead?.rows[table.tHead.rows.length - 1];
    const column = !rowLabel && cell && headRow ? textOf(headRow.cells[cell.cellIndex]) : '';
    const value = target === cell ? '' : textOf(target);
    const head = [rowLabel || column, period, value].filter(Boolean).join(' · ');
    setTouchTip({ head: head || 'Пояснение', body });
  };

  const typeLabel = company.company_type === 'holding'
    ? 'Холдинг'
    : company.company_type === 'exchange'
      ? 'Биржа'
      : company.company_type === 'hybrid' ? 'Гибрид' : null;
  return (
    <div className="ys">
      <div className="ys-controls">
        <div className="ys-controls-main">
          <Segmented<SheetOrientation>
            label="Как расположить годы"
            value={orientation}
            onChange={setOrientation}
            options={[
              { key: 'cols', label: 'Годы в колонках' },
              { key: 'rows', label: 'Годы в строках' },
            ]}
          />
          <Segmented<'values' | 'pct'>
            label="Значения или изменение"
            value={histPctMode ? 'pct' : 'values'}
            onChange={(v) => setHistPctMode(v === 'pct')}
            options={[
              { key: 'values', label: 'Значения' },
              { key: 'pct', label: 'Изменение, %', title: 'Изменение к прошлому году' },
            ]}
          />
          {sheetColumns.length > 0 && (
            <RowsChooser
              columns={orientation === 'rows' ? sheetColumns.filter((c) => !ROWS_ONLY_HIDDEN.has(c.key)) : sheetColumns}
              hidden={hiddenCols}
              onChange={setHiddenCols}
              noun={orientation === 'cols' ? 'Строки' : 'Столбцы'}
            />
          )}
          {rows.length > 0 && <DownloadLinks what="мультипликаторы" onPick={setExportFormat} />}
        </div>
        <div className="ys-legend" title={profile.summary}>
          <span>Пороги: {profile.label.toLowerCase()}</span>
          <span className="ys-dot good">хорошо</span>
          <span className="ys-dot warn">терпимо</span>
          <span className="ys-dot bad">плохо</span>
          <span className="ys-dot loss">убыток</span>
        </div>
      </div>

      {typeLabel && (
        <div className="mult-type-warning">
          <b>{typeLabel}.</b>{' '}
          {company.company_type === 'holding'
            ? 'Мультипликаторы по консолидированной отчётности складывают выручку и долг дочерних компаний. Для холдинга корректна оценка по сумме частей, а не P/E консолидации.'
            : company.company_type === 'exchange'
              ? 'Обязательства — средства участников торгов и позиции клиринга, поэтому плечо, ликвидность и чистый долг не считаются. Свободный поток очищен от прироста клиентских остатков.'
              : 'Внутри компании есть финансовый бизнес: клиентские средства раздувают баланс, а их приток попадает в операционный поток. Ликвидность, чистый долг и FCF здесь искажены.'}
        </div>
      )}

      {currentData && rows.length < GRAHAM_YEARS && <HistoryDepth years={rows.length} />}

      {(autoRefreshing || !initialPriceSynced || currentLoading || histLoading) ? (
        <div className="mult-loading">
          {autoRefreshing || !initialPriceSynced ? 'Обновляем цену и загружаем показатели…' : 'Загрузка показателей…'}
        </div>
      ) : (
        <div
          ref={sheetRef}
          className={`mult-history-body${orientation === 'rows' && histHidden > 0 && !histExpanded ? ' is-collapsed' : ''}`}
          onClick={onSheetClick}
        >
          <HistTable
            isHolding={isHolding}
            rows={sheetRows}
            currentRow={currentData ?? undefined}
            profile={profile}
            isPreferredShare={!!company.is_preferred_share}
            pctMode={histPctMode}
            bankMetricsByReport={bankMetricsByReport}
            ltmBankMetrics={ltmBankMetrics}
            orientation={orientation}
            hidden={hiddenCols}
            referenceByYear={referenceByYear}
            ltmReference={ltmReference}
            reportedProfitByYear={reportedProfitByYear}
            ltmReportedEps={ltmReportedEps}
            earlierHidden={colsHidden}
            earlierShown={earlierShown}
            onToggleEarlier={() => setEarlierShown((v) => !v)}
            onColumns={setSheetColumns}
          />
          {orientation === 'rows' && histHidden > 0 && (
            <button
              type="button"
              className="hist-expand"
              onClick={() => setHistExpanded((v) => !v)}
              aria-expanded={histExpanded}
            >
              <span className="hist-expand-label">
                {histExpanded ? 'Свернуть' : `Ещё ${histHidden} ${plural(histHidden, 'год', 'года', 'лет')}`}
              </span>
              <span className="hist-expand-chevron" aria-hidden>
                <svg viewBox="0 0 16 16" width="16" height="16">
                  <path d={histExpanded ? 'M3 10l5-5 5 5' : 'M3 6l5 5 5-5'} fill="none" stroke="currentColor"
                    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </button>
          )}
        </div>
      )}
      {exportFormat && (
        <div ref={exportRef} className="ys-export" aria-hidden>
          <HistTable
            isHolding={isHolding}
            rows={rows}
            currentRow={currentData ?? undefined}
            profile={profile}
            isPreferredShare={!!company.is_preferred_share}
            pctMode={false}
            bankMetricsByReport={bankMetricsByReport}
            ltmBankMetrics={ltmBankMetrics}
            orientation="cols"
            referenceByYear={referenceByYear}
            ltmReference={ltmReference}
            reportedProfitByYear={reportedProfitByYear}
            ltmReportedEps={ltmReportedEps}
          />
        </div>
      )}
      {currentError && (
        <div className="mult-error">Нет данных: убедитесь, что добавлены финансовые отчёты и задана текущая цена.</div>
      )}

      <div className="ys-foot">
        {currentData?.balance_report_date && (
          <p className="ys-note">
            12 мес. — баланс на {currentData.balance_report_date.split('-').reverse().join('.')}
          </p>
        )}
        {isAdmin && <div className="ys-admin">
          {autoRefreshing && !refreshMutation.isPending && (
            <span className="refresh-auto-indicator"><span className="refresh-auto-spinner" aria-hidden />обновляем цену…</span>
          )}
          {refreshMsg && <span className="refresh-msg">{refreshMsg}</span>}
          <label className="legend-profile" title="Метод анализа: какие показатели применимы">
            <span className="legend-profile-label">Тип:</span>
            <select
              className="legend-profile-select"
              value={company.company_type ?? 'industrial'}
              onChange={(e) => typeMutation.mutate(e.target.value as CompanyType)}
              disabled={typeMutation.isPending}
            >
              {COMPANY_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value} title={opt.hint}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label className="legend-profile" title={profile.summary}>
            <span className="legend-profile-label">Пороги:</span>
            <select
              className="legend-profile-select"
              value={company.sector_profile_key ?? ''}
              onChange={(e) => profileMutation.mutate(e.target.value || null)}
              disabled={profileMutation.isPending || !profileOptions}
            >
              <option value="">По отрасли автоматически</option>
              {(profileOptions ?? []).map((opt) => (
                <option key={opt.key} value={opt.key} title={opt.summary}>{opt.label}</option>
              ))}
            </select>
          </label>
          <button className="btn-refresh" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
            {refreshMutation.isPending ? 'Обновляем…' : '↺ Обновить цену'}
          </button>
        </div>}
      </div>
      <TouchTip tip={touchTip} onClose={() => setTouchTip(null)} />
    </div>
  );
};

export default MultipliersPanel;
