import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceDot,
} from 'recharts';
import {
  getCompanyCurrentMultipliers,
  getCompanyMultipliersHistory,
  refreshCompanyMultipliers,
} from '../services';
import { MultiplierRecord, CurrentMultipliers, Company } from '../types';
import { useChartColors, ChartColors } from '../contexts/ThemeContext';
import SharesCapHover from './SharesCapHover';
import './MultipliersPanel.css';

// ─── Критерии Грэма для цветовой кодировки ───────────────────────────────────

type Level = 'good' | 'warn' | 'bad' | 'neutral' | 'loss';

function peLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v <= 15) return 'good';
  if (v <= 25) return 'warn';
  return 'bad';
}

/** P/E null + убыток → «убыток» в UI. */
function peLevelContext(pe: number | null, income: number | null): Level {
  if (pe !== null) return peLevel(pe);
  if (income !== null && income < 0) return 'loss';
  return 'neutral';
}

function pbLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v <= 1.5) return 'good';
  if (v <= 3) return 'warn';
  return 'bad';
}

/** P/B null + отрицательный капитал → «убыток» в UI. */
function pbLevelContext(pb: number | null, equity: number | null): Level {
  if (pb !== null) return pbLevel(pb);
  if (equity !== null && equity < 0) return 'loss';
  return 'neutral';
}

function roeLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';
  if (v >= 15) return 'good';
  if (v >= 10) return 'warn';
  return 'bad';
}

/**
 * D/E с учётом отрицательного капитала.
 * Отрицательный D/E = знаменатель (капитал) отрицателен → книжная стоимость дефицит, 'bad'.
 */
function deLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';   // отрицательный капитал: формально «хорошо», фактически плохо
  if (v <= 0.5) return 'good';
  if (v <= 1) return 'warn';
  return 'bad';
}

const DE_BANKRUPTCY_TIP =
  'Отрицательный собственный капитал — компания фактически банкрот. D/E в такой ситуации не имеет смысла.';

function deBadge(
  de: number | null,
  equity: number | null,
  fallbackHint?: string,
): { value: number | null; level: Level; tip?: string } {
  const level = deLevel(de);
  const bankrupt = de !== null && de < 0 && equity !== null && equity < 0;
  return {
    value: de,
    level,
    tip: bankrupt ? DE_BANKRUPTCY_TIP : fallbackHint,
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

function netDebtValueUi(netDebtMln: number | null): {
  display: string;
  level: Level;
  tip?: string;
} {
  if (netDebtMln === null) {
    return { display: '—', level: 'neutral', tip: 'Нет данных о долге и наличности' };
  }
  const display = (netDebtMln / 1_000).toFixed(2);
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
 *  ≥ 100%: FCF превышает прибыль → high-quality earnings ('good')
 *  70–99%: норма ('warn')
 *  0–69%: сомнительное качество ('bad')
 *  < 0:    отрицательный FCF при положительной прибыли → красный флаг ('loss')
 */
function fcfNiLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 100) return 'good';
  if (v >= 70) return 'warn';
  if (v >= 0) return 'bad';
  return 'loss';  // FCF отрицательный — красный флаг
}

/** ROE: капитал ≤ 0 → «Н/Д»; ROE > 100% → «Искажено»; иначе число (в т.ч. отрицательное при убытке). */
function roeBadge(
  roe: number | null | undefined,
  _netIncome: number | null | undefined,
  equity: number | null | undefined,
): { value: number | null; level: Level; textLabel?: string; nullHint?: string; centered?: boolean } {
  const eq = equity ?? null;

  if (eq !== null && eq <= 0) {
    return {
      value: null,
      level: 'loss',
      textLabel: 'Н/Д',
      nullHint: 'Собственный капитал ≤ 0 — ROE не применим',
      centered: true,
    };
  }
  const v = roe ?? null;
  if (v !== null && v > 100) {
    return {
      value: null,
      level: 'warn',
      textLabel: 'Искажено',
      nullHint: 'ROE > 100% — показатель может быть искажён (малый капитал или разовые эффекты)',
    };
  }
  return { value: v, level: roeLevel(v) };
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

// ─── Отраслевые профили Current Ratio ────────────────────────────────────────
//
// CR — «градусник»: норма сильно зависит от бизнес-модели.
// Для сырьевых/коммунальных компаний мощный денежный поток перекрывает
// краткосрочные обязательства, даже когда CR < 1.
// Для ритейла и дистрибуции — нет стабильного потока, запасы критичны,
// и норма Грэма ≥ 2 абсолютно уместна.

export interface CrProfile {
  /** Название группы для тултипа */
  industryLabel: string;
  /** CR выше этого уровня → 'good' */
  good: number;
  /** CR выше этого уровня → 'warn' (ниже — 'bad') */
  warn: number;
  /** Одна строка-объяснение для карточки */
  thresholdHint: string;
  /** Многострочное пояснение для тултипа в заголовке таблицы */
  tooltipLines: string[];
  /**
   * Нужно ли вместо числовой оценки показать нейтральную пометку
   * (напр. для банков — у них нестандартная структура баланса).
   */
  notApplicable?: boolean;
}

/**
 * Определяет отраслевой профиль CR по строке sector компании.
 * Ключевые слова — без регистра, частичное совпадение.
 */
export function getCrProfile(sector?: string | null): CrProfile {
  const s = (sector ?? '').toLowerCase();

  const hasAny = (...words: string[]) => words.some((w) => s.includes(w));

  // ── Банки и финансовые организации ──
  // Структура баланса принципиально иная: краткосрочные обязательства ≈ вклады,
  // классический CR не применим. Не даём оценку — только информируем.
  if (hasAny('bank', 'банк', 'financial', 'финанс', 'insurance', 'страхов',
             'leasing', 'лизинг', 'finance')) {
    return {
      industryLabel: 'Банки / финансы',
      good: Infinity,
      warn: Infinity,
      thresholdHint: 'CR для банков не применим',
      tooltipLines: [
        'Для банков и финансовых организаций CR не используется:',
        'их «краткосрочные обязательства» — это депозиты клиентов,',
        'а не коммерческие долги. Ликвидность оценивается по',
        'нормативам ЦБ (Н1, Н2, Н3), а не по балансовому соотношению.',
      ],
      notApplicable: true,
    };
  }

  // ── Нефть и газ, горнодобыча, металлургия ──
  // Огромный операционный поток покрывает краткосрочные обязательства;
  // значительная часть «краткосрочного» долга — это кредитные линии,
  // которые постоянно рефинансируются. Норма 0.7–1.2.
  if (hasAny('oil', 'gas', 'нефт', 'газ', 'энерго', 'energy',
             'mining', 'металл', 'coal', 'уголь', 'petro', 'горнодобыв',
             'золото', 'silver', 'copper', 'alumin')) {
    return {
      industryLabel: 'Нефтегаз / горнодобыча / металлургия',
      good: 1.0,
      warn: 0.7,
      thresholdHint: '≥ 1.0 — норма для нефтегаза',
      tooltipLines: [
        'Нефтегаз, металлургия: мощный операционный поток',
        'покрывает краткосрочный долг даже при CR < 1.',
        '≥ 1.0  —  хорошо',
        '0.7–1.0  —  допустимо, смотри D/E и cash flow',
        '< 0.7  —  агрессивная долговая политика, копай глубже',
        '',
        'Пример: Лукойл ~0.9 — норма; Роснефть ~0.5 — красный флаг',
        'даже для нефтянки (огромный краткосрочный долг).',
      ],
    };
  }

  // ── Коммунальные услуги, электроэнергетика, тепло, вода ──
  // Регулируемый тариф = стабильный поток; высокий capex финансируется
  // долгосрочным долгом. CR < 1 — обычная ситуация.
  if (hasAny('util', 'electric', 'энергетик', 'электро', 'тепло',
             'water', 'вода', 'коммунал', 'generation', 'генерац')) {
    return {
      industryLabel: 'Коммунальные / электроэнергетика',
      good: 1.0,
      warn: 0.7,
      thresholdHint: '≥ 1.0 — норма для коммунальных',
      tooltipLines: [
        'Коммунальные, электроэнергетика: регулируемый тариф',
        'обеспечивает предсказуемый поток. CR < 1 — ок.',
        '≥ 1.0  —  хорошо',
        '0.7–1.0  —  норма, смотри долг и инвестиции',
        '< 0.7  —  требует пояснения (разовые капвложения?)',
      ],
    };
  }

  // ── IT / телеком / цифровые сервисы ──
  //
  // Важно: GICS «communication_services» (Яндекс, VK, Meta и др.) НЕ содержит
  // слова telecom/internet — без явного учёта уходит в «промышленность».
  // Сектор T-Invest ровно «it» тоже должен ловиться (не путать с подстрокой «it»
  // внутри случайных слов — только границы слова / точное совпадение).
  const wordIt = /\b(it|ict)\b/.test(s);
  const gicsIt = hasAny(
    'communication_services',
    'communication services',
    'information_technology',
    'information technology',
    'it_services',
    'it services',
    'internet_software',
    'internet software',
  );
  const itTelecomMedia = hasAny(
    'software', 'hardware', 'internet', 'computer', 'semiconductor', 'cyber',
    'cloud', 'saas', 'digital', 'platform', 'technology', 'technologies',
    'informatics', 'telecom', 'телеком', 'связь', 'cellular', 'mobile',
    'мобильн', 'медиа', 'media', 'gaming', 'програм', 'информац', 'цифров', 'облак',
  );
  if (s === 'it' || gicsIt || wordIt || itTelecomMedia) {
    return {
      industryLabel: 'IT / телеком / цифровые сервисы',
      good: 1.5,
      warn: 1.0,
      thresholdHint: '≥ 1.5 — хорошо для IT / цифровых сервисов',
      tooltipLines: [
        'IT, телеком, платформы: обычно asset-light, мало запасов,',
        'высокая маржа или подписная выручка. Классический CR ≥ 2 для',
        '«магазина с полки» здесь часто завышен; ориентиры мягче.',
        '≥ 1.5  —  хорошо',
        '1.0–1.5  —  приемлемо',
        '< 1.0  —  нетипично, смотри структуру обязательств и cash flow',
        '',
        'Секторы вроде communication_services (GICS) относятся сюда же.',
      ],
    };
  }

  // ── Ритейл и дистрибуция ──
  // Нет мощного сырьевого потока. Бизнес живёт от оборачиваемости запасов
  // и дебиторки. CR < 1 — почти всегда симптом беды. Норма Грэма ≥ 2.
  // «consumer» одно слово слишком широкое — используем типичные хвосты GICS.
  const retailCore = hasAny(
    'retail', 'ритейл', 'торговл', 'supermarket', 'маркет', 'hypermarket',
    'distribution', 'дистрибуц', 'food', 'grocery', 'продукт', 'фарм', 'pharma',
    'drugstore', 'shopping', 'потребител',
  );
  const gicsRetailConsumer =
    hasAny(
      'consumer_staples',
      'consumer_discretionary',
      'consumer_defensive',
      'consumer cyclical',
      'consumer_cyclical',
      'consumer staples',
      'consumer discretionary',
      'consumer defensive',
    ) || /\bconsumer\s+(staples|discretionary|defensive|cyclical)\b/.test(s);
  if (retailCore || gicsRetailConsumer) {
    return {
      industryLabel: 'Ритейл / дистрибуция / FMCG',
      good: 2.0,
      warn: 1.2,
      thresholdHint: '≥ 2.0 — норма по Грэму для ритейла',
      tooltipLines: [
        'Ритейл, дистрибуция: нет стабильного сырьевого потока.',
        'Бизнес живёт за счёт оборачиваемости товарных запасов.',
        'CR < 1 здесь — почти всегда симптом предбанкротного',
        'состояния. Применяется классическая норма Грэма.',
        '≥ 2.0  —  хорошо (норма Грэма)',
        '1.2–2.0  —  приемлемо, следить за оборачиваемостью',
        '< 1.2  —  красный флаг для ритейла',
      ],
    };
  }

  // ── Строительство и девелопмент ──
  // Большие авансы от покупателей входят в «краткосрочные обязательства»,
  // что искусственно занижает CR. Смотри в динамике, сравнивай с аналогами.
  if (hasAny('construct', 'строит', 'develo', 'девелоп', 'real estate',
             'недвижим', 'realty')) {
    return {
      industryLabel: 'Строительство / девелопмент',
      good: 1.2,
      warn: 0.8,
      thresholdHint: '≥ 1.2 — норма для строителей',
      tooltipLines: [
        'Строительство: авансы покупателей квартир — краткосрочные',
        'обязательства, что занижает CR. Важнее смотреть динамику',
        'и эскроу-счета (в РФ — обязательно с 2019 г.).',
        '≥ 1.2  —  хорошо',
        '0.8–1.2  —  обычная ситуация для девелопера',
        '< 0.8  —  изучить структуру обязательств',
      ],
    };
  }

  // ── Промышленность и производство (General / default) ──
  // Умеренная ликвидность, запасы важны, но есть производственный поток.
  // Ориентир — ≥ 1.5; классическая норма Грэма ≥ 2 здесь уже уместна.
  return {
    industryLabel: 'Промышленность / прочее',
    good: 2.0,
    warn: 1.5,
    thresholdHint: '≥ 2.0 — норма по Грэму',
    tooltipLines: [
      'Производство, промышленность: запасы и дебиторка критичны.',
      'Применяется классическая норма Грэма.',
      '≥ 2.0  —  хорошо (норма Грэма)',
      '1.5–2.0  —  приемлемо, следить за запасами',
      '< 1.5  —  внимание; < 1.0  —  красный флаг',
    ],
  };
}

/**
 * Уровень CR с учётом отраслевого профиля.
 * Для секторов, где CR не применим (банки), всегда возвращает 'neutral'.
 */
function crLevel(v: number | null, profile: CrProfile): Level {
  if (v === null) return 'neutral';
  if (profile.notApplicable) return 'neutral';
  if (v >= profile.good) return 'good';
  if (v >= profile.warn) return 'warn';
  return 'bad';
}

function dyLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 3) return 'good';
  if (v >= 1) return 'warn';
  return 'bad';
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
    <span className={`mult-cell ${level}${tipClass}`} title={hoverTip}>
      {value.toFixed(2)}{suffix}
    </span>
  );
}

function DeMetricBadge({
  de,
  equity,
  fallbackHint,
}: {
  de: number | null;
  equity: number | null | undefined;
  fallbackHint?: string;
}) {
  const ui = deBadge(de, equity ?? null, fallbackHint);
  return (
    <MetricBadge
      value={ui.value}
      level={ui.level}
      nullHint={ui.value === null ? ui.tip : undefined}
      tip={ui.value !== null ? ui.tip : undefined}
    />
  );
}

function RoeMetricBadge({
  roe,
  netIncome,
  equity,
}: {
  roe: number | null | undefined;
  netIncome: number | null | undefined;
  equity: number | null | undefined;
}) {
  const ui = roeBadge(roe, netIncome, equity);
  return (
    <MetricBadge
      value={ui.value}
      level={ui.level}
      suffix="%"
      nullHint={ui.nullHint}
      textLabel={ui.textLabel}
      centered={ui.centered}
    />
  );
}

/** Нет дивидендной доходности: выплаты по обыкновенным не указаны или не было выплат */
function NoDividendYieldMark({ className = '' }: { className?: string }) {
  const isCard = className.includes('mult-div-none--card');
  const mark = (
    <span
      className={`mult-div-none mult-div-none--wrap mult-cell-tip${isCard ? ` ${className}` : ''}`}
      title="Дивиденды по обыкновенным акциям за период не выплачивались или не указаны в отчётах"
      aria-label="Дивиденды не выплачивались"
    >
      <span className="mult-div-none-box" aria-hidden>
        ×
      </span>
    </span>
  );
  if (isCard) return mark;
  return <span className={`mult-cell-center${className ? ` ${className}` : ''}`}>{mark}</span>;
}

function DividendYieldBadge({
  dividendYield,
  ltmDividendsPerShare,
  priceUsed,
  isPreferredShare = false,
}: {
  dividendYield: number | null;
  ltmDividendsPerShare: number | null;
  priceUsed: number | null;
  /** Тикер представляет привилегированные акции — у него нет понятия
   *  «не выплачивались по обыкновенным», поэтому красный маркер не нужен. */
  isPreferredShare?: boolean;
}) {
  if (dividendYield !== null) {
    const lvl = dyLevel(dividendYield);
    return (
      <span
        className={`mult-cell ${lvl}`}
        title={isPreferredShare ? 'Доходность по привилегированным акциям' : undefined}
      >
        {dividendYield.toFixed(2)}%
      </span>
    );
  }
  if (ltmDividendsPerShare === null) {
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

function fmt(n: number | null, decimals = 2): string {
  if (n === null) return '—';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
}

/** Заголовок колонки: название + единица измерения меньшим шрифтом снизу. */
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
  return (
    <span className={`col-header-stacked${align === 'right' ? ' col-header-stacked-right' : ''}`}>
      <span className={uppercase ? 'col-header-title' : 'col-header-title-plain'}>{title}</span>
      <span className="col-header-unit">{unit}</span>
    </span>
  );
}

/**
 * Форматирует значение в миллионах ₽.
 * Если >= 1000 млн — показывает в млрд, иначе в млн.
 */
function fmtMln(n: number | null): string {
  if (n === null) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ' трлн ₽';
  if (abs >= 1_000)     return (n / 1_000).toFixed(2) + ' млрд ₽';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн ₽';
}

/** Значение в млн ₽ → число в млрд (без единицы; единица в заголовке колонки). */
function fmtMlnBln(n: number | null): string {
  if (n === null) return '—';
  return (n / 1_000).toFixed(2);
}

function fmtDate(d: string): string {
  return d.split('-')[0];
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

interface CurrentCardsProps {
  data: CurrentMultipliers;
  crProfile: CrProfile;
  /** Тикер компании — привилегированные акции (TRNFP, BANEP, SBERP …) */
  isPreferredShare?: boolean;
}

interface DashboardCard {
  label: string;
  value: number | null;
  level: Level;
  hint: string;
  threshold: string;
  suffix?: string;
  nullHint?: string;
  textLabel?: string;
  tip?: string;
  toggleable?: boolean;
}

const PfcfCardToggleIcon: React.FC = () => (
  <svg className="current-card-toggle-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
    <path
      d="M2 4.5h8M9 2.5l1.5 2-1.5 2"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M12 9.5H4M5 11.5L3.5 9.5 5 7.5"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const CurrentCards: React.FC<CurrentCardsProps> = ({ data, crProfile, isPreferredShare = false }) => {
  const [pfcfCardMode, setPfcfCardMode] = React.useState<PfcfColMode>('pfcf');
  const income = data.ltm_net_income;
  const isLoss = income !== null && income < 0;
  const roeUi = roeBadge(data.roe, income, data.equity ?? null);
  const isBank = data.cost_to_income !== null || (
    data.debt_to_equity === null && data.current_ratio === null
  );
  const ltmFcf = (data as any).ltm_fcf as number | null | undefined;
  const pfcf = (data as any).price_to_fcf as number | null | undefined;
  const fcfNi = (data as any).fcf_to_net_income as number | null | undefined;
  const fcfNiUi = fcfNiBadge(fcfNi ?? null, income ?? null);

  const baseCards = [
    {
      label: 'P/E',
      value: data.pe_ratio,
      level: peLevelContext(data.pe_ratio, income),
      hint: 'Цена / Прибыль',
      threshold: isLoss ? 'Убыток — P/E не применим' : '≤ 15 — хорошо',
    },
    {
      label: 'P/B',
      value: data.pb_ratio,
      level: pbLevelContext(data.pb_ratio, data.equity ?? null),
      hint: 'Цена / Балансовая стоимость',
      threshold: '≤ 1.5 — хорошо',
    },
    {
      label: 'ROE',
      value: roeUi.textLabel ? null : roeUi.value,
      level: roeUi.level,
      hint: 'Рентабельность капитала',
      threshold:
        roeUi.textLabel === 'Н/Д'
          ? 'Капитал ≤ 0'
          : roeUi.textLabel === 'Искажено'
            ? 'ROE > 100%'
            : roeUi.value !== null && roeUi.value < 0
              ? 'Отрицательный ROE'
              : '≥ 15% — хорошо',
      suffix: '%',
      nullHint: roeUi.nullHint,
      textLabel: roeUi.textLabel,
    },
    {
      label: 'Долг/Капитал',
      value: data.debt_to_equity,
      level: deLevel(data.debt_to_equity),
      hint: 'Total Liabilities / Equity',
      threshold:
        data.equity !== null &&
        data.equity !== undefined &&
        data.equity < 0 &&
        data.debt_to_equity !== null &&
        data.debt_to_equity < 0
          ? 'Отрицательный капитал — банкрот'
          : data.debt_to_equity !== null && data.debt_to_equity < 0
            ? 'Отрицательный капитал'
            : '≤ 0.5 — хорошо',
      tip:
        data.debt_to_equity !== null &&
        data.debt_to_equity < 0 &&
        data.equity != null &&
        data.equity < 0
          ? DE_BANKRUPTCY_TIP
          : undefined,
    },
    {
      label: 'Current Ratio',
      value: data.current_ratio,
      level: crLevel(data.current_ratio, crProfile),
      hint: crProfile.notApplicable ? 'CR не применим для данного типа компании' : 'Текущая ликвидность',
      threshold: crProfile.thresholdHint,
    },
    {
      label: 'Div. Yield',
      value: data.dividend_yield,
      level:
        data.dividend_yield !== null
          ? dyLevel(data.dividend_yield)
          : data.ltm_dividends_per_share === null
            ? isPreferredShare
              ? 'neutral'
              : 'bad'
            : 'neutral',
      hint: isPreferredShare
        ? 'Дивидендная доходность (привилегированные)'
        : 'Дивидендная доходность',
      threshold:
        data.dividend_yield !== null
          ? '≥ 3% — хорошо'
          : data.ltm_dividends_per_share === null
            ? isPreferredShare
              ? 'Дивиденды по префам в отчётах не указаны'
              : 'Дивиденды не выплачивались'
            : 'Нет цены / данных для расчёта',
      suffix: '%',
    },
  ];

  // FCF-карточки только для non-bank и только если есть данные ОДДС
  const hasFcfData = ltmFcf !== undefined && ltmFcf !== null;
  const pfcfYield = pfcfToFcfYield(pfcf ?? null);
  const pfcfCard: DashboardCard = pfcfCardMode === 'yield'
    ? {
        label: 'FCF yld',
        value: pfcfYield,
        level: fcfYieldLevel(pfcfYield, ltmFcf ?? null),
        hint: 'Доходность FCF = 100 / P/FCF',
        threshold: (ltmFcf ?? 0) < 0 ? 'FCF отрицателен' : '≥ 6.7% — хорошо',
        suffix: '%',
        toggleable: true,
      }
    : {
        label: 'P/FCF',
        value: pfcf ?? null,
        level: pfcfLevel(pfcf ?? null, ltmFcf ?? null),
        hint: 'Цена / Свободный денежный поток',
        threshold: (ltmFcf ?? 0) < 0 ? 'FCF отрицателен' : '≤ 15 — хорошо',
        toggleable: true,
      };

  const fcfCards = (!isBank && hasFcfData) ? [
    pfcfCard,
    {
      label: 'FCF/NI',
      value: fcfNiUi.value,
      level: fcfNiUi.level,
      hint: 'Качество прибыли (FCF / Net Income)',
      threshold:
        income !== null && income <= 0
          ? 'Прибыль ≤ 0 — показатель не применим'
          : fcfNiUi.value === null
            ? 'Недостаточно данных'
            : fcfNiUi.value < 0
              ? '⚠ Красный флаг: FCF < 0'
              : fcfNiUi.value >= 100
                ? 'FCF > прибыли — отлично'
                : fcfNiUi.value >= 70
                  ? '70–100% — норма'
                  : '< 70% — сомнительно',
      suffix: '%',
      nullHint: fcfNiUi.nullHint,
    },
  ] : [];

  const cards: DashboardCard[] = [...baseCards, ...fcfCards];

  return (
    <div className="current-cards-grid">
      {cards.map(({ label, value, level, hint, threshold, suffix = '', nullHint, textLabel, tip, toggleable }) => (
        <div
          key={toggleable ? 'pfcf-toggle' : label}
          className={`current-card level-${level}${toggleable ? ' current-card--toggleable' : ''}`}
        >
          {toggleable && (
            <button
              type="button"
              className="current-card-toggle"
              onClick={() => setPfcfCardMode((m) => (m === 'pfcf' ? 'yield' : 'pfcf'))}
              aria-label={pfcfCardMode === 'pfcf' ? 'Показать FCF yield' : 'Показать P/FCF'}
              title="Переключить P/FCF ↔ FCF yield"
            >
              <PfcfCardToggleIcon />
            </button>
          )}
          <div className="current-card-label">{label}</div>
          <div className="current-card-value" title={tip ?? nullHint}>
            {label === 'Div. Yield' && value === null && data.ltm_dividends_per_share === null ? (
              isPreferredShare ? (
                '—'
              ) : (
                <NoDividendYieldMark className="mult-div-none--card" />
              )
            ) : textLabel === 'убыток' || level === 'loss' ? (
              <span className="card-loss-badge">убыток</span>
            ) : textLabel ? (
              <span className="card-text-label">{textLabel}</span>
            ) : value !== null ? (
              `${fmt(value)}${suffix}`
            ) : (
              '—'
            )}
          </div>
          <div className="current-card-hint">{hint}</div>
          <div className={`current-card-threshold level-${level}`}>{threshold}</div>
        </div>
      ))}
    </div>
  );
};

// ─── Информационная строка с LTM-метаданными ─────────────────────────────────

const LtmMeta: React.FC<{ data: CurrentMultipliers }> = ({ data }) => {
  const sourceLabel: Record<string, string> = {
    quarterly_4: '4 квартала',
    annual: 'Годовой отчёт',
  };
  const src = data.ltm_source ? sourceLabel[data.ltm_source] ?? data.ltm_source : '—';

  return (
    <div className="ltm-meta-bar">
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">💰</span>
        <span className="ltm-meta-label">Текущая цена:</span>
        <span className="ltm-meta-value">
          {data.current_price !== null ? `${fmt(data.current_price)} ₽` : 'не задана'}
        </span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📊</span>
        <span className="ltm-meta-label">Капитализация:</span>
        <span className="ltm-meta-value">
          <SharesCapHover explanation={data.shares_cap_explanation}>
            {fmtMln(data.market_cap)}
          </SharesCapHover>
        </span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📈</span>
        <span className="ltm-meta-label">LTM источник:</span>
        <span className="ltm-meta-value">{src}</span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📅</span>
        <span className="ltm-meta-label">Баланс от:</span>
        <span className="ltm-meta-value">{data.balance_report_date ?? '—'}</span>
      </span>
    </div>
  );
};

// ─── Историческая таблица ─────────────────────────────────────────────────────

// ─── Тултип для заголовка CR с отраслевыми порогами ──────────────────────────

interface CrTooltipProps {
  profile: CrProfile;
  anchorRef: React.RefObject<HTMLTableCellElement | null>;
}

/**
 * Rich-тултип: объясняет, какой отраслевой профиль применяется для CR
 * и каковы конкретные пороги «хорошо / внимание / плохо».
 * Рендерится в portal (#root), чтобы не зажиматься overflow:hidden таблицы.
 */
const CrTooltip: React.FC<CrTooltipProps> = ({ profile, anchorRef }) => {
  const [pos, setPos] = React.useState<{ top: number; left: number } | null>(null);

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

  return createPortal(
    <div
      className="cr-tooltip"
      style={{ top: pos.top, left: pos.left }}
      role="tooltip"
    >
      <div className="cr-tooltip-industry">{profile.industryLabel}</div>
      {profile.notApplicable ? (
        <p className="cr-tooltip-na">{profile.tooltipLines[0]}</p>
      ) : (
        <>
          <div className="cr-tooltip-thresholds">
            <span className="cr-tt-good">● хорошо: ≥ {profile.good.toFixed(1)}</span>
            <span className="cr-tt-warn">● внимание: ≥ {profile.warn.toFixed(1)}</span>
            <span className="cr-tt-bad">● тревога: &lt; {profile.warn.toFixed(1)}</span>
          </div>
          <div className="cr-tooltip-body">
            {profile.tooltipLines.map((line, i) =>
              line === '' ? <br key={i} /> : <div key={i} className="cr-tooltip-line">{line}</div>,
            )}
          </div>
        </>
      )}
    </div>,
    document.body,
  );
};

interface HistTableProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
  crProfile: CrProfile;
  /** Тикер представляет привилегированные акции — влияет на отображение Div. Yield */
  isPreferredShare?: boolean;
}

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
          <div className="mult-price-tip-value">{fmt(row.price_at_filing_rub)} ₽</div>
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
        <div className="mult-price-tip-value">Цена на дату публикации: {fmt(row.price_at_filing_rub)} ₽</div>
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
        {row.price_used !== null ? fmt(row.price_used) : '—'}
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
}> = ({ marketCapMln, explanation }) => {
  const display = marketCapMln !== null ? (marketCapMln / 1_000).toFixed(2) : '—';
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

const HistNetDebtCell: React.FC<{ netDebtMln: number | null }> = ({ netDebtMln }) => {
  const ui = netDebtValueUi(netDebtMln);
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

const HistTable: React.FC<HistTableProps> = ({ rows, currentRow, crProfile, isPreferredShare = false }) => {
  const [crTooltipVisible, setCrTooltipVisible] = React.useState(false);
  const [pfcfColMode, setPfcfColMode] = React.useState<PfcfColMode>('pfcf');
  const crThRef = React.useRef<HTMLTableCellElement | null>(null);

  return (
    <div className="hist-table-wrapper">
      <table className="hist-table">
        <thead>
          <tr>
            <th className="col-year">Период</th>
            <th
              className="col-price"
              title="В ячейке — цена на дату окончания отчётного периода. Наведите для цены на дату публикации (если заполнено в отчёте)."
            >
              Цена, ₽
            </th>
            <th className="col-mkt col-header-unit-col">
              <ColHeaderWithUnit title="Кап." />
            </th>
            <th className="col-mult">P/E</th>
            <th className="col-mult">P/B</th>
            <th className="col-mult">ROE, %</th>
            <th className="col-mult">D/E</th>
            <th
              ref={crThRef}
              className="col-mult col-cr-header"
              onMouseEnter={() => setCrTooltipVisible(true)}
              onMouseLeave={() => setCrTooltipVisible(false)}
            >
              CR
              <span className="cr-header-hint-icon" aria-hidden>ⓘ</span>
              {crTooltipVisible && (
                <CrTooltip profile={crProfile} anchorRef={crThRef} />
              )}
            </th>
            <th className="col-mult">Div, %</th>
            <HistPfcfHeader
              mode={pfcfColMode}
              onToggle={() => setPfcfColMode((m) => (m === 'pfcf' ? 'yield' : 'pfcf'))}
            />
            <th className="col-mult col-compact" title="FCF / Net Income × 100% — качество прибыли">FCF/NI, %</th>
            <th className="col-mult col-compact" title="Net Debt / LTM FCF — лет погашения">ND/FCF</th>
            <th className="col-rev col-compact col-net-debt-header col-header-unit-col" title="Чистый долг = Долг − Наличность">
              <ColHeaderWithUnit title="Net Debt" uppercase={false} align="right" />
            </th>
            <th className="col-rev col-header-unit-col" title="FCF = Операционный поток − CAPEX">
              <ColHeaderWithUnit title="FCF" />
            </th>
            <th className="col-rev col-header-unit-col">
              <ColHeaderWithUnit title="Выручка" />
            </th>
            <th className="col-ni col-header-unit-col">
              <ColHeaderWithUnit title="Прибыль" />
            </th>
          </tr>
        </thead>
        <tbody>
          {/* LTM-строка (актуальные данные) */}
          {currentRow && (() => {
            const ltmIsLoss = currentRow.ltm_net_income !== null && currentRow.ltm_net_income < 0;
            const fcfNiLtm = fcfNiBadge(currentRow.fcf_to_net_income, currentRow.ltm_net_income);
            return (
              <tr className="row-ltm">
                <td className="col-year"><span className="badge-ltm">LTM</span></td>
                <td>{currentRow.price_used !== null ? fmt(currentRow.price_used) : '—'}</td>
                <td>
                  <HistCapCell
                    marketCapMln={currentRow.market_cap}
                    explanation={currentRow.shares_cap_explanation}
                  />
                </td>
                <td><MetricBadge
                  value={currentRow.pe_ratio}
                  level={peLevelContext(currentRow.pe_ratio, currentRow.ltm_net_income)}
                  nullHint={ltmIsLoss ? 'Убыток за период — P/E не рассчитывается' : undefined}
                /></td>
                <td><MetricBadge
                  value={currentRow.pb_ratio}
                  level={pbLevelContext(currentRow.pb_ratio, currentRow.equity ?? null)}
                  nullHint={
                    currentRow.equity !== null && currentRow.equity !== undefined && currentRow.equity < 0
                      ? 'Отрицательный капитал — P/B не рассчитывается'
                      : undefined
                  }
                /></td>
                <td>
                  <RoeMetricBadge
                    roe={currentRow.roe}
                    netIncome={currentRow.ltm_net_income}
                    equity={currentRow.equity ?? null}
                  />
                </td>
                <td><DeMetricBadge
                  de={currentRow.debt_to_equity}
                  equity={currentRow.equity ?? null}
                  fallbackHint={
                    currentRow.debt_to_equity !== null && currentRow.debt_to_equity < 0
                      ? 'Отрицательный капитал'
                      : undefined
                  }
                /></td>
                <td><MetricBadge value={currentRow.current_ratio} level={crLevel(currentRow.current_ratio, crProfile)}
                  nullHint={crProfile.notApplicable ? 'CR не применим для данного типа компании' : undefined} /></td>
                <td>
                  <DividendYieldBadge
                    dividendYield={currentRow.dividend_yield}
                    ltmDividendsPerShare={currentRow.ltm_dividends_per_share}
                    priceUsed={currentRow.price_used}
                    isPreferredShare={isPreferredShare}
                  />
                </td>
                <td><HistPfcfCell
                  mode={pfcfColMode}
                  pfcf={currentRow.price_to_fcf}
                  fcf={currentRow.ltm_fcf}
                /></td>
                <td>
                  <MetricBadge
                    value={fcfNiLtm.value}
                    level={fcfNiLtm.level}
                    suffix="%"
                    nullHint={fcfNiLtm.nullHint}
                  />
                </td>
                <td><HistNetDebtFcfCell
                  ratio={currentRow.net_debt_to_fcf}
                  netDebt={currentRow.net_debt}
                  fcf={currentRow.ltm_fcf}
                /></td>
                <td className="col-compact"><HistNetDebtCell netDebtMln={currentRow.net_debt} /></td>
                <td className={(currentRow.ltm_fcf !== null && currentRow.ltm_fcf < 0) ? 'cell-loss' : ''}>{fmtMlnBln(currentRow.ltm_fcf)}</td>
                <td>{fmtMlnBln(currentRow.ltm_revenue)}</td>
                <td className={ltmIsLoss ? 'cell-loss' : ''}>{fmtMlnBln(currentRow.ltm_net_income)}</td>
              </tr>
            );
          })()}

          {/* Исторические строки */}
          {rows.map((r) => {
            const noPrice   = r.price_used === null || r.shares_used === null;
            const noIncome  = r.ltm_net_income === null;
            const isLoss    = r.ltm_net_income !== null && r.ltm_net_income < 0;
            const noEquity  = r.equity === null;
            const negEquity = r.equity !== null && r.equity < 0;
            const noLiab    = r.total_liabilities === null;
            const noCurr    = r.current_assets === null || r.current_liabilities === null;
            const fcfNiRow = fcfNiBadge(r.fcf_to_net_income, r.ltm_net_income);

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
              : noLiab  ? 'Нет данных об обязательствах (total_liabilities)'
              : noEquity ? 'Нет данных о капитале (equity)'
              : undefined;

            return (
              <tr key={r.id} className="row-hist">
                <td className="col-year">{fmtDate(r.date)}</td>
                <td className="col-price-cell">
                  <HistPriceCell row={r} />
                </td>
                <td>
                  <HistCapCell
                    marketCapMln={r.market_cap}
                    explanation={r.shares_cap_explanation}
                  />
                </td>
                <td><MetricBadge
                  value={r.pe_ratio}
                  level={peLevelContext(r.pe_ratio, r.ltm_net_income)}
                  nullHint={peHint}
                /></td>
                <td><MetricBadge
                  value={r.pb_ratio}
                  level={pbLevelContext(r.pb_ratio, r.equity)}
                  nullHint={pbHint}
                /></td>
                <td>
                  <RoeMetricBadge roe={r.roe} netIncome={r.ltm_net_income} equity={r.equity} />
                </td>
                <td><DeMetricBadge de={r.debt_to_equity} equity={r.equity} fallbackHint={deHint} /></td>
                <td><MetricBadge value={r.current_ratio} level={crLevel(r.current_ratio, crProfile)}
                  nullHint={noCurr ? 'Нет оборотных активов или краткосрочных обязательств' : crProfile.notApplicable ? 'CR не применим для данного типа компании' : undefined} /></td>
                <td>
                  <DividendYieldBadge
                    dividendYield={r.dividend_yield}
                    ltmDividendsPerShare={r.ltm_dividends_per_share}
                    priceUsed={r.price_used}
                    isPreferredShare={isPreferredShare}
                  />
                </td>
                <td><HistPfcfCell mode={pfcfColMode} pfcf={r.price_to_fcf} fcf={r.ltm_fcf} /></td>
                <td>
                  <MetricBadge
                    value={fcfNiRow.value}
                    level={fcfNiRow.level}
                    suffix="%"
                    nullHint={fcfNiRow.nullHint}
                  />
                </td>
                <td><HistNetDebtFcfCell ratio={r.net_debt_to_fcf} netDebt={r.net_debt} fcf={r.ltm_fcf} /></td>
                <td className="col-compact"><HistNetDebtCell netDebtMln={r.net_debt} /></td>
                <td className={r.ltm_fcf !== null && r.ltm_fcf < 0 ? 'cell-loss' : ''}>{fmtMlnBln(r.ltm_fcf)}</td>
                <td>{fmtMlnBln(r.ltm_revenue)}</td>
                <td className={isLoss ? 'cell-loss' : ''}>{fmtMlnBln(r.ltm_net_income)}</td>
              </tr>
            );
          })}

          {rows.length === 0 && !currentRow && (
            <tr>
              <td colSpan={16} className="table-empty">
                Нет данных. Добавьте годовые отчёты и нажмите «Обновить цену».
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

// ─── Графики мультипликаторов ─────────────────────────────────────────────────

interface ChartPoint {
  year: string;
  isLtm: boolean;
  pe_ratio: number | null;
  pe_loss: boolean;
  pb_ratio: number | null;
  roe: number | null;
  roe_na: boolean;
  debt_to_equity: number | null;
  current_ratio: number | null;
  dividend_yield: number | null;
  no_dividend: boolean;
}

type ChartRowInput = Pick<
  MultiplierRecord,
  | 'pe_ratio'
  | 'pb_ratio'
  | 'roe'
  | 'debt_to_equity'
  | 'current_ratio'
  | 'dividend_yield'
  | 'ltm_net_income'
  | 'equity'
  | 'ltm_dividends_per_share'
>;

function toChartPoint(r: ChartRowInput, year: string, isLtm: boolean): ChartPoint {
  const ni = r.ltm_net_income ?? null;
  const isLoss = ni !== null && ni < 0;
  const roeUi = roeBadge(r.roe, ni, r.equity ?? null);

  const peOk = r.pe_ratio != null && r.pe_ratio > 0 && !isLoss;
  const roeOk = !roeUi.textLabel && roeUi.value != null;
  const hasDividend = r.ltm_dividends_per_share != null && r.ltm_dividends_per_share > 0;

  return {
    year,
    isLtm,
    pe_ratio: peOk ? r.pe_ratio : null,
    pe_loss: !peOk && isLoss,
    pb_ratio: r.pb_ratio,
    roe: roeOk ? roeUi.value : null,
    roe_na: roeUi.textLabel === 'Н/Д',
    debt_to_equity: r.debt_to_equity,
    current_ratio: r.current_ratio,
    dividend_yield: hasDividend && r.dividend_yield != null ? r.dividend_yield : null,
    no_dividend: !hasDividend,
  };
}

function buildMultiplierChartData(
  rows: MultiplierRecord[],
  currentRow?: CurrentMultipliers,
): ChartPoint[] {
  const historical = [...rows].reverse();
  return [
    ...historical.map((r) => toChartPoint(r, fmtDate(r.date), false)),
    ...(currentRow ? [toChartPoint(currentRow, 'LTM', true)] : []),
  ];
}

function chartMarkerLabel(chartKey: keyof ChartPoint): string | null {
  if (chartKey === 'pe_ratio') return 'убыток';
  if (chartKey === 'roe') return 'Н/Д';
  if (chartKey === 'dividend_yield') return '×';
  return null;
}

function chartMarkerFlag(chartKey: keyof ChartPoint, point: ChartPoint): boolean {
  if (chartKey === 'pe_ratio') return point.pe_loss;
  if (chartKey === 'roe') return point.roe_na;
  if (chartKey === 'dividend_yield') return point.no_dividend;
  return false;
}

function chartTooltipValue(
  chartKey: keyof ChartPoint,
  point: ChartPoint,
  value: unknown,
  suffix: string | undefined,
  label: string,
): [string, string] {
  if (chartKey === 'pe_ratio' && point.pe_loss) return ['убыток', label];
  if (chartKey === 'roe' && point.roe_na) return ['Н/Д', label];
  if (chartKey === 'dividend_yield' && point.no_dividend) return ['нет выплат', label];
  if (value == null || typeof value !== 'number') return ['—', label];
  return [`${fmt(value)}${suffix ?? ''}`, label];
}

interface ChartConfig {
  key: 'pe_ratio' | 'pb_ratio' | 'roe' | 'debt_to_equity' | 'current_ratio' | 'dividend_yield';
  label: string;
  color: string;
  referenceLines?: { value: number; label: string; color: string }[];
  suffix?: string;
  domain?: [number | 'auto', number | 'auto'];
}

/**
 * Конфиги графиков строим из текущей темы — цвета берутся из CSS-токенов
 * (см. tokens.css → --color-chart-*), что обеспечивает консистентный
 * вид светлой и тёмной палитры.
 */
function buildCharts(c: ChartColors, crProfile?: CrProfile): ChartConfig[] {
  const crRefs: ChartConfig['referenceLines'] = crProfile && !crProfile.notApplicable
    ? [
        { value: crProfile.good, label: `${crProfile.good.toFixed(1)} хорошо`, color: c.refGood },
        ...(crProfile.warn !== crProfile.good
          ? [{ value: crProfile.warn, label: `${crProfile.warn.toFixed(1)} внимание`, color: c.refBad }]
          : []),
      ]
    : [{ value: 2, label: '2.0', color: c.refGood }];

  return [
    {
      key: 'pe_ratio',
      label: 'P/E',
      color: c.line1,
      referenceLines: [
        { value: 15, label: 'Грэм 15', color: c.refGood },
        { value: 25, label: 'Грэм 25', color: c.refBad },
      ],
    },
    {
      key: 'pb_ratio',
      label: 'P/B',
      color: c.line2,
      referenceLines: [
        { value: 1.5, label: '1.5×', color: c.refGood },
        { value: 3, label: '3×', color: c.refBad },
      ],
    },
    {
      key: 'roe',
      label: 'ROE, %',
      color: c.line3,
      suffix: '%',
      referenceLines: [
        { value: 15, label: '15%', color: c.refGood },
      ],
    },
    {
      key: 'debt_to_equity',
      label: 'Долг/Капитал',
      color: c.line4,
      referenceLines: [
        { value: 0.5, label: '0.5', color: c.refGood },
        { value: 1, label: '1.0', color: c.refBad },
      ],
    },
    {
      key: 'current_ratio',
      label: 'Current Ratio',
      color: c.line5,
      referenceLines: crRefs,
    },
    {
      key: 'dividend_yield',
      label: 'Дивиденд. доходность, %',
      color: c.line6,
      suffix: '%',
      referenceLines: [
        { value: 3, label: '3%', color: c.refGood },
      ],
    },
  ];
}

interface MultipliersChartsProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
}

interface MetricLineChartProps {
  data: ChartPoint[];
  config: ChartConfig;
  chartColors: ChartColors;
}

const MetricLineChart: React.FC<MetricLineChartProps> = ({ data, config, chartColors }) => {
  const { key, label, color, referenceLines, suffix } = config;
  const dataKey = String(key);
  const markerLabel = chartMarkerLabel(key);
  const markerPoints = markerLabel ? data.filter((p) => chartMarkerFlag(key, p)) : [];
  const showBottomMarkers = markerPoints.length > 0;

  return (
    <div className="chart-card">
      <div className="chart-card-title">{label}</div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
          <XAxis dataKey="year" tick={{ fontSize: 11, fill: chartColors.axis }} />
          <YAxis
            tick={{ fontSize: 11, fill: chartColors.axis }}
            tickFormatter={(v) => `${v}${suffix ?? ''}`}
            width={45}
            domain={
              showBottomMarkers
                ? ([dataMin, dataMax]: readonly [number, number]) => [
                    Math.min(dataMin, 0),
                    dataMax === dataMin ? dataMax + 1 : dataMax,
                  ]
                : undefined
            }
          />
          <Tooltip
            formatter={(value: unknown, _name, item) => {
              const point = (item as { payload?: ChartPoint }).payload;
              if (!point) return ['—', label];
              return chartTooltipValue(key, point, value, suffix, label);
            }}
            labelStyle={{ color: chartColors.textPrimary, fontWeight: 600 }}
            contentStyle={{
              backgroundColor: chartColors.tooltipBg,
              border: `1px solid ${chartColors.tooltipBorder}`,
              borderRadius: 8,
              color: chartColors.textPrimary,
            }}
          />
          {referenceLines?.map((rl) => (
            <ReferenceLine
              key={rl.value}
              y={rl.value}
              stroke={rl.color}
              strokeDasharray="6 3"
              label={{ value: rl.label, position: 'insideTopRight', fontSize: 10, fill: rl.color }}
            />
          ))}
          {markerLabel
            ? markerPoints.map((p) => (
                  <ReferenceDot
                    key={`${dataKey}-mark-${p.year}`}
                    x={p.year}
                    y={0}
                    r={0}
                    ifOverflow="discard"
                    label={{
                      value: markerLabel,
                      position: 'insideBottomLeft',
                      fontSize: key === 'dividend_yield' ? 12 : 9,
                      fill: key === 'dividend_yield' ? chartColors.refBad : 'var(--color-loss-text)',
                      offset: 8,
                    }}
                  />
                ))
            : null}
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            connectNulls
            dot={(props: { cx?: number; cy?: number; payload?: ChartPoint; value?: number | null }) => {
              const { cx, cy, payload, value } = props;
              if (cx == null || cy == null || payload == null || value == null) return null;
              if (payload.isLtm) {
                return (
                  <circle
                    key={`${dataKey}-ltm`}
                    cx={cx}
                    cy={cy}
                    r={5}
                    fill={color}
                    stroke={chartColors.dotStroke}
                    strokeWidth={2}
                  />
                );
              }
              return <circle key={`${dataKey}-${payload.year}`} cx={cx} cy={cy} r={3} fill={color} />;
            }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

// Компонент графиков (пока не подключён к панели)
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- зарезервировано для встраивания графиков
const MultipliersCharts: React.FC<MultipliersChartsProps> = ({ rows, currentRow }) => {
  const chartColors = useChartColors();
  const charts = buildCharts(chartColors);
  const chartData = buildMultiplierChartData(rows, currentRow);

  if (chartData.length === 0) {
    return (
      <div className="charts-empty">
        Недостаточно данных для построения графиков
      </div>
    );
  }

  return (
    <div className="charts-grid">
      {charts.map((cfg) => (
        <MetricLineChart key={String(cfg.key)} data={chartData} config={cfg} chartColors={chartColors} />
      ))}
    </div>
  );
};

// ─── Пара графиков с пагинацией ───────────────────────────────────────────────

interface ChartsPairProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
  crProfile: CrProfile;
}

const CHART_PAGE_SIZE = 2;

const ChartsPager: React.FC<ChartsPairProps> = ({ rows, currentRow, crProfile }) => {
  const [page, setPage] = useState(0);
  const chartColors = useChartColors();
  const charts = buildCharts(chartColors, crProfile);
  const totalPages = Math.ceil(charts.length / CHART_PAGE_SIZE);
  const visibleCharts = charts.slice(page * CHART_PAGE_SIZE, (page + 1) * CHART_PAGE_SIZE);
  const chartData = buildMultiplierChartData(rows, currentRow);

  if (chartData.length === 0) {
    return <div className="charts-empty">Недостаточно данных для построения графиков</div>;
  }

  return (
    <div className="charts-pager">
      <div className="charts-pager-nav">
        <span className="charts-pager-label">
          {page * CHART_PAGE_SIZE + 1}–{Math.min((page + 1) * CHART_PAGE_SIZE, charts.length)} из {charts.length}
        </span>
        <button
          className="charts-nav-btn"
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          disabled={page === 0}
        >‹</button>
        <button
          className="charts-nav-btn"
          onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
          disabled={page === totalPages - 1}
        >›</button>
      </div>

      {visibleCharts.map((cfg) => (
        <MetricLineChart key={String(cfg.key)} data={chartData} config={cfg} chartColors={chartColors} />
      ))}
    </div>
  );
};

// ─── Главный компонент панели ─────────────────────────────────────────────────

interface MultipliersPanelProps {
  company: Company;
}

const MultipliersPanel: React.FC<MultipliersPanelProps> = ({ company }) => {
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  /** После первого sync цены с T-Invest можно грузить current-мультипликаторы. */
  const [initialPriceSynced, setInitialPriceSynced] = useState(false);
  const queryClient = useQueryClient();
  const crProfile = getCrProfile(company.sector);

  const companyId = company.id!;

  const { data: currentData, isLoading: currentLoading, error: currentError } = useQuery({
    queryKey: ['multipliers-current', companyId],
    queryFn: () => getCompanyCurrentMultipliers(companyId),
    enabled: initialPriceSynced,
    retry: false,
  });

  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['multipliers-history', companyId, 'report_based'],
    queryFn: () => getCompanyMultipliersHistory(companyId, 'report_based', 20),
    retry: false,
  });

  // Ручное обновление по кнопке — с тостом успеха/ошибки.
  const refreshMutation = useMutation({
    mutationFn: () => refreshCompanyMultipliers(companyId),
    onSuccess: (res) => {
      setRefreshMsg(
        res.success
          ? `✓ Цена обновлена: ${fmt(res.price)} ₽`
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
    if (!companyId) return;

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
          setRefreshMsg(`✓ Цена актуальна: ${fmt(res.price)} ₽`);
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
  }, [companyId, queryClient]);

  const rows = histData ?? [];

  return (
    <div className="mult-panel">
      {/* Заголовок */}
      <div className="mult-panel-header">
        <h2 className="mult-panel-title">Мультипликаторы</h2>
        <div className="mult-panel-controls">
          {autoRefreshing && !refreshMutation.isPending && (
            <span className="refresh-auto-indicator" title="Подтягиваем актуальную цену из T-Invest API">
              <span className="refresh-auto-spinner" aria-hidden />
              обновляем цену…
            </span>
          )}
          {refreshMsg && <span className="refresh-msg">{refreshMsg}</span>}
          <button
            className="btn-refresh"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? 'Обновляем...' : '↺ Обновить цену'}
          </button>
        </div>
      </div>

      {/* Легенда */}
      <div className="legend-bar">
        <span className="legend-item good">● Норма по Грэму</span>
        <span className="legend-item warn">● Внимание</span>
        <span className="legend-item bad">● Превышение</span>
        <span className="legend-item loss">● Убыток</span>
        <span className="legend-item neutral">● Нет данных</span>
      </div>

      {/* Контент */}
      <div className="mult-tab-content">
        {(autoRefreshing || !initialPriceSynced || currentLoading || histLoading) && (
          <div className="mult-loading">
            {autoRefreshing || !initialPriceSynced
              ? 'Обновляем цену и загружаем мультипликаторы…'
              : 'Загрузка мультипликаторов...'}
          </div>
        )}

        {initialPriceSynced && !currentLoading && !histLoading && (
          <>
            {/* ── Верхняя строка: текущие (лево) + графики (право) ── */}
            <div className="mult-top-row">
              {/* Левая часть — текущие показатели */}
              <div className="mult-current-col">
                {currentError && (
                  <div className="mult-error">
                    Нет данных: убедитесь, что добавлены финансовые отчёты и задана текущая цена.
                  </div>
                )}
                {currentData && (
                  <>
                    <LtmMeta data={currentData} />
                    <CurrentCards
                      data={currentData}
                      crProfile={crProfile}
                      isPreferredShare={!!company.is_preferred_share}
                    />
                    <div className="ltm-financials">
                      <h3 className="ltm-fin-title">Финансовые показатели LTM</h3>
                      <div className="ltm-fin-grid">
                        <div className="ltm-fin-item">
                          <span className="ltm-fin-label">Выручка</span>
                          <span className="ltm-fin-value">{fmtMln(currentData.ltm_revenue)}</span>
                        </div>
                        <div className={`ltm-fin-item${currentData.ltm_net_income !== null && currentData.ltm_net_income < 0 ? ' ltm-fin-item--loss' : ''}`}>
                          <span className="ltm-fin-label">
                            {currentData.ltm_net_income !== null && currentData.ltm_net_income < 0
                              ? 'Чистый убыток'
                              : 'Чистая прибыль'}
                          </span>
                          <span className={`ltm-fin-value${currentData.ltm_net_income !== null && currentData.ltm_net_income < 0 ? ' value-loss' : ''}`}>
                            {fmtMln(currentData.ltm_net_income)}
                          </span>
                        </div>
                        <div className="ltm-fin-item">
                          <span className="ltm-fin-label">Дивиденды на акцию</span>
                          <span className="ltm-fin-value">
                            {currentData.ltm_dividends_per_share !== null
                              ? `${fmt(currentData.ltm_dividends_per_share)} ₽`
                              : '—'}
                          </span>
                        </div>
                        <div className="ltm-fin-item">
                          <span className="ltm-fin-label">Размещено (общее)</span>
                          <span className="ltm-fin-value">
                            {currentData.shares_issued !== null
                              ? currentData.shares_issued.toLocaleString('ru-RU')
                              : '—'}
                          </span>
                        </div>
                        <div className="ltm-fin-item">
                          <span className="ltm-fin-label">Акции в обращении</span>
                          <span className="ltm-fin-value">
                            {currentData.shares_outstanding_circulation !== null
                              ? currentData.shares_outstanding_circulation.toLocaleString('ru-RU')
                              : '—'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Правая часть — 2 графика с пагинацией */}
              <div className="mult-charts-col">
                <ChartsPager rows={rows} currentRow={currentData ?? undefined} crProfile={crProfile} />
              </div>
            </div>

            {/* ── Нижняя строка: история на всю ширину ── */}
            {(rows.length > 0 || currentData) && (
              <div className="mult-history-row">
                <div className="mult-history-label">История мультипликаторов</div>
                <HistTable
                  rows={rows}
                  currentRow={currentData ?? undefined}
                  crProfile={crProfile}
                  isPreferredShare={!!company.is_preferred_share}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default MultipliersPanel;
