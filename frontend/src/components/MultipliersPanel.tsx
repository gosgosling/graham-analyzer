import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import {
  getCompanyCurrentMultipliers,
  getCompanyMultipliersHistory,
  refreshCompanyMultipliers,
} from '../services';
import { MultiplierRecord, CurrentMultipliers, Company } from '../types';
import { useChartColors, ChartColors } from '../contexts/ThemeContext';
import './MultipliersPanel.css';

// ─── Критерии Грэма для цветовой кодировки ───────────────────────────────────

type Level = 'good' | 'warn' | 'bad' | 'neutral' | 'loss';

function peLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';
  if (v <= 15) return 'good';
  if (v <= 25) return 'warn';
  return 'bad';
}

function pbLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';
  if (v <= 1.5) return 'good';
  if (v <= 3) return 'warn';
  return 'bad';
}

function roeLevel(v: number | null): Level {
  if (v === null) return 'neutral';
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

/** P/FCF — аналог P/E: те же пороги, в т.ч. отрицательное значение при FCF < 0. */
function pfcfLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v < 0) return 'bad';
  if (v <= 15) return 'good';
  if (v <= 25) return 'warn';
  return 'bad';
}

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

/** ROE в таблице: капитал ≤ 0 → Н/Д; убыток → «убыток»; ROE > 100% → «Искажено». */
function roeBadge(
  roe: number | null | undefined,
  netIncome: number | null | undefined,
  equity: number | null | undefined,
): { value: number | null; level: Level; textLabel?: string; nullHint?: string; centered?: boolean } {
  const eq = equity ?? null;
  const ni = netIncome ?? null;

  if (eq !== null && eq <= 0) {
    return {
      value: null,
      level: 'loss',
      textLabel: 'Н/Д',
      nullHint: 'Собственный капитал ≤ 0 — ROE не применим',
      centered: true,
    };
  }
  if (ni !== null && ni < 0) {
    return {
      value: null,
      level: 'loss',
      textLabel: 'убыток',
      nullHint: 'Убыток за период — ROE не показывается',
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
  value, level, suffix = '', nullHint, textLabel, centered = false,
}: {
  value: number | null;
  level: Level;
  suffix?: string;
  nullHint?: string;
  textLabel?: string;
  centered?: boolean;
}) {
  const tipClass = nullHint ? ' mult-cell-tip' : '';

  const wrap = (node: React.ReactElement) =>
    centered ? <span className="mult-cell-center">{node}</span> : node;

  if (textLabel) {
    const isCompact = textLabel === 'убыток' || textLabel === 'Н/Д' || textLabel === 'Искажено';
    return wrap(
      <span
        className={`mult-cell ${level}${isCompact ? ' mult-cell-text-label' : ''}${tipClass}`}
        title={nullHint}
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
          title={nullHint ?? 'Убыток за период — показатель не применим'}
        >
          убыток
        </span>,
      );
    }
    return (
      <span
        className={`mult-cell neutral${nullHint ? ' mult-cell-tip' : ''}`}
        title={nullHint ?? 'Недостаточно данных'}
      >
        —
      </span>
    );
  }
  return (
    <span className={`mult-cell ${level}`}>
      {value.toFixed(2)}{suffix}
    </span>
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
  return (
    <span className={`mult-cell-center${className ? ` ${className}` : ''}`}>
      <span
        className="mult-div-none mult-div-none--wrap mult-cell-tip"
        title="Дивиденды по обыкновенным акциям за период не выплачивались или не указаны в отчётах"
        aria-label="Дивиденды не выплачивались"
      >
        <span className="mult-div-none-box" aria-hidden>
          ×
        </span>
      </span>
    </span>
  );
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
function ColHeaderWithUnit({ title, unit = 'млрд ₽' }: { title: string; unit?: string }) {
  return (
    <span className="col-header-stacked">
      <span className="col-header-title">{title}</span>
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
}

const CurrentCards: React.FC<CurrentCardsProps> = ({ data, crProfile, isPreferredShare = false }) => {
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
      level: peLevel(data.pe_ratio),
      hint: 'Цена / Прибыль',
      threshold: isLoss ? 'Отрицательный P/E при убытке' : '≤ 15 — хорошо',
    },
    {
      label: 'P/B',
      value: data.pb_ratio,
      level: pbLevel(data.pb_ratio),
      hint: 'Цена / Балансовая стоимость',
      threshold: data.pb_ratio !== null && data.pb_ratio < 0 ? 'Отрицательный P/B' : '≤ 1.5 — хорошо',
    },
    {
      label: 'ROE',
      value: roeUi.textLabel ? null : roeUi.value,
      level: roeUi.level,
      hint: 'Рентабельность капитала',
      threshold:
        roeUi.textLabel === 'Н/Д'
          ? 'Капитал ≤ 0'
          : roeUi.textLabel === 'убыток'
            ? 'Убыток за период'
            : roeUi.textLabel === 'Искажено'
              ? 'ROE > 100%'
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
      threshold: data.debt_to_equity !== null && data.debt_to_equity < 0
        ? 'Отрицательный капитал'
        : '≤ 0.5 — хорошо',
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
              : 'Нет выплат по обыкновенным в отчётах'
            : 'Нет цены / данных для расчёта',
      suffix: '%',
    },
  ];

  // FCF-карточки только для non-bank и только если есть данные ОДДС
  const hasFcfData = ltmFcf !== undefined && ltmFcf !== null;
  const fcfCards = (!isBank && hasFcfData) ? [
    {
      label: 'P/FCF',
      value: pfcf ?? null,
      level: pfcfLevel(pfcf ?? null),
      hint: 'Цена / Свободный денежный поток',
      threshold: pfcf !== null && pfcf !== undefined && pfcf < 0 ? 'Отрицательный P/FCF' : '≤ 15 — хорошо',
    },
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
      {cards.map(({ label, value, level, hint, threshold, suffix = '', nullHint, textLabel }) => (
        <div key={label} className={`current-card level-${level}`}>
          <div className="current-card-label">{label}</div>
          <div className="current-card-value" title={nullHint}>
            {label === 'Div. Yield' && value === null && data.ltm_dividends_per_share === null ? (
              isPreferredShare ? (
                '—'
              ) : (
                <NoDividendYieldMark className="mult-div-none--card" />
              )
            ) : textLabel ? (
              <span className={textLabel === 'убыток' ? 'card-text-label card-text-label--loss' : 'card-text-label'}>
                {textLabel}
              </span>
            ) : value !== null ? (
              `${fmt(value)}${suffix}`
            ) : level === 'loss' ? (
              <span className="card-text-label card-text-label--loss">убыток</span>
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
        <span className="ltm-meta-value">{fmtMln(data.market_cap)}</span>
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

const HistTable: React.FC<HistTableProps> = ({ rows, currentRow, crProfile, isPreferredShare = false }) => {
  const [crTooltipVisible, setCrTooltipVisible] = React.useState(false);
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
            <th className="col-mult" title="Price / Free Cash Flow (только для non-bank)">P/FCF</th>
            <th className="col-mult" title="FCF / Net Income × 100% — качество прибыли">FCF/NI, %</th>
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
            const fcfNiLtm = fcfNiBadge((currentRow as any).fcf_to_net_income, currentRow.ltm_net_income);
            return (
              <tr className="row-ltm">
                <td className="col-year"><span className="badge-ltm">LTM</span></td>
                <td>{currentRow.price_used !== null ? fmt(currentRow.price_used) : '—'}</td>
                <td>{currentRow.market_cap !== null ? (currentRow.market_cap / 1_000).toFixed(2) : '—'}</td>
                <td><MetricBadge value={currentRow.pe_ratio} level={peLevel(currentRow.pe_ratio)} /></td>
                <td><MetricBadge value={currentRow.pb_ratio} level={pbLevel(currentRow.pb_ratio)} /></td>
                <td>
                  <RoeMetricBadge
                    roe={currentRow.roe}
                    netIncome={currentRow.ltm_net_income}
                    equity={currentRow.equity ?? null}
                  />
                </td>
                <td><MetricBadge
                  value={currentRow.debt_to_equity}
                  level={deLevel(currentRow.debt_to_equity)}
                  nullHint={currentRow.debt_to_equity !== null && currentRow.debt_to_equity < 0 ? 'Отрицательный капитал' : undefined}
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
                <td><MetricBadge value={(currentRow as any).price_to_fcf ?? null} level={pfcfLevel((currentRow as any).price_to_fcf ?? null)} /></td>
                <td>
                  <MetricBadge
                    value={fcfNiLtm.value}
                    level={fcfNiLtm.level}
                    suffix="%"
                    nullHint={fcfNiLtm.nullHint}
                  />
                </td>
                <td className={(currentRow as any).ltm_fcf !== null && (currentRow as any).ltm_fcf !== undefined && (currentRow as any).ltm_fcf < 0 ? 'cell-loss' : ''}>{fmtMlnBln((currentRow as any).ltm_fcf ?? null)}</td>
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

            const peHint = noIncome
              ? 'Нет данных о чистой прибыли (net_income)'
              : noPrice ? 'Нет цены / акций'
              : undefined;

            const pbHint = noEquity
              ? 'Нет данных о капитале (equity)'
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
                <td>{r.market_cap !== null ? (r.market_cap / 1_000).toFixed(2) : '—'}</td>
                <td><MetricBadge value={r.pe_ratio} level={peLevel(r.pe_ratio)} nullHint={peHint} /></td>
                <td><MetricBadge value={r.pb_ratio} level={pbLevel(r.pb_ratio)} nullHint={pbHint} /></td>
                <td>
                  <RoeMetricBadge roe={r.roe} netIncome={r.ltm_net_income} equity={r.equity} />
                </td>
                <td><MetricBadge value={r.debt_to_equity} level={deLevel(r.debt_to_equity)} nullHint={deHint} /></td>
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
                <td><MetricBadge value={r.price_to_fcf} level={pfcfLevel(r.price_to_fcf)} /></td>
                <td>
                  <MetricBadge
                    value={fcfNiRow.value}
                    level={fcfNiRow.level}
                    suffix="%"
                    nullHint={fcfNiRow.nullHint}
                  />
                </td>
                <td className={r.ltm_fcf !== null && r.ltm_fcf < 0 ? 'cell-loss' : ''}>{fmtMlnBln(r.ltm_fcf)}</td>
                <td>{fmtMlnBln(r.ltm_revenue)}</td>
                <td className={isLoss ? 'cell-loss' : ''}>{fmtMlnBln(r.ltm_net_income)}</td>
              </tr>
            );
          })}

          {rows.length === 0 && !currentRow && (
            <tr>
              <td colSpan={14} className="table-empty">
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

interface ChartConfig {
  key: keyof MultiplierRecord;
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

// Компонент графиков (пока не подключён к панели)
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- зарезервировано для встраивания графиков
const MultipliersCharts: React.FC<MultipliersChartsProps> = ({ rows, currentRow }) => {
  const chartColors = useChartColors();
  const charts = buildCharts(chartColors);
  const historical = [...rows].reverse();

  const chartData = [
    ...historical.map((r) => ({
      year: fmtDate(r.date),
      pe_ratio: r.pe_ratio,
      pb_ratio: r.pb_ratio,
      roe: r.roe,
      debt_to_equity: r.debt_to_equity,
      current_ratio: r.current_ratio,
      dividend_yield: r.dividend_yield,
      isLtm: false,
    })),
    ...(currentRow
      ? [{
          year: 'LTM',
          pe_ratio: currentRow.pe_ratio,
          pb_ratio: currentRow.pb_ratio,
          roe: currentRow.roe,
          debt_to_equity: currentRow.debt_to_equity,
          current_ratio: currentRow.current_ratio,
          dividend_yield: currentRow.dividend_yield,
          isLtm: true,
        }]
      : []),
  ];

  if (chartData.length === 0) {
    return (
      <div className="charts-empty">
        Недостаточно данных для построения графиков
      </div>
    );
  }

  return (
    <div className="charts-grid">
      {charts.map(({ key, label, color, referenceLines, suffix }) => (
        <div key={String(key)} className="chart-card">
          <div className="chart-card-title">{label}</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 11, fill: chartColors.axis }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: chartColors.axis }}
                tickFormatter={(v) => `${v}${suffix ?? ''}`}
                width={45}
              />
              <Tooltip
                formatter={(value: any) => [`${fmt(typeof value === 'number' ? value : null)}${suffix ?? ''}`, label]}
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
              <Line
                type="monotone"
                dataKey={String(key)}
                stroke={color}
                strokeWidth={2}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;
                  return payload.isLtm
                    ? <circle key="ltm" cx={cx} cy={cy} r={5} fill={color} stroke={chartColors.dotStroke} strokeWidth={2} />
                    : <circle key={payload.year} cx={cx} cy={cy} r={3} fill={color} />;
                }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
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

  const historical = [...rows].reverse();
  const chartData = [
    ...historical.map((r) => ({
      year: fmtDate(r.date),
      pe_ratio: r.pe_ratio,
      pb_ratio: r.pb_ratio,
      roe: r.roe,
      debt_to_equity: r.debt_to_equity,
      current_ratio: r.current_ratio,
      dividend_yield: r.dividend_yield,
      isLtm: false,
    })),
    ...(currentRow ? [{
      year: 'LTM',
      pe_ratio: currentRow.pe_ratio,
      pb_ratio: currentRow.pb_ratio,
      roe: currentRow.roe,
      debt_to_equity: currentRow.debt_to_equity,
      current_ratio: currentRow.current_ratio,
      dividend_yield: currentRow.dividend_yield,
      isLtm: true,
    }] : []),
  ];

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

      {visibleCharts.map(({ key, label, color, referenceLines, suffix }) => (
        <div key={String(key)} className="chart-card">
          <div className="chart-card-title">{label}</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: chartColors.axis }} />
              <YAxis
                tick={{ fontSize: 11, fill: chartColors.axis }}
                tickFormatter={(v) => `${v}${suffix ?? ''}`}
                width={45}
              />
              <Tooltip
                formatter={(value: any) => [
                  `${fmt(typeof value === 'number' ? value : null)}${suffix ?? ''}`, label,
                ]}
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
              <Line
                type="monotone"
                dataKey={String(key)}
                stroke={color}
                strokeWidth={2}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;
                  return payload.isLtm
                    ? <circle key="ltm" cx={cx} cy={cy} r={5} fill={color} stroke={chartColors.dotStroke} strokeWidth={2} />
                    : <circle key={payload.year} cx={cx} cy={cy} r={3} fill={color} />;
                }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
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
  const queryClient = useQueryClient();
  const crProfile = getCrProfile(company.sector);

  const companyId = company.id!;

  const { data: currentData, isLoading: currentLoading, error: currentError } = useQuery({
    queryKey: ['multipliers-current', companyId],
    queryFn: () => getCompanyCurrentMultipliers(companyId),
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
      setTimeout(() => setRefreshMsg(null), 4000);
    },
    onError: () => {
      setRefreshMsg('✗ Ошибка при обновлении цены');
      setTimeout(() => setRefreshMsg(null), 4000);
    },
  });

  // Авто-обновление цены при первом заходе на страницу компании.
  //
  // Делаем это ОТДЕЛЬНО от ручной мутации, чтобы:
  //  1) не блокировать кнопку «Обновить цену» (она остаётся доступной для ручного клика);
  //  2) при «зависании» бэкенда (T-Invest API долго отвечает) — мягко прерывать
  //     запрос по таймауту и снимать индикатор, а не оставлять «Обновляем…» вечно.
  const autoRefreshedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!companyId) return;
    if (autoRefreshedFor.current === companyId) return;
    autoRefreshedFor.current = companyId;

    const controller = new AbortController();
    // Если за 12 секунд цена не пришла — прекращаем ждать; пользователь
    // всё равно увидит ранее закэшированные мультипликаторы.
    const timeoutId = window.setTimeout(() => controller.abort(), 12_000);

    setAutoRefreshing(true);

    refreshCompanyMultipliers(companyId, true, controller.signal)
      .then((res) => {
        queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
        queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
        if (res.success && res.price !== null) {
          setRefreshMsg(`✓ Цена актуальна: ${fmt(res.price)} ₽`);
        } else {
          setRefreshMsg('⚠ Не удалось получить актуальную цену');
        }
        setTimeout(() => setRefreshMsg(null), 3500);
      })
      .catch((err) => {
        // Тихо игнорируем abort и сетевые ошибки — пользователь увидит
        // последние закэшированные значения. Логируем для отладки.
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
        setAutoRefreshing(false);
      });

    return () => {
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
        {(currentLoading || histLoading) && (
          <div className="mult-loading">Загрузка мультипликаторов...</div>
        )}

        {!currentLoading && !histLoading && (
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
                          <span className="ltm-fin-label">Кол-во акций</span>
                          <span className="ltm-fin-value">
                            {currentData.shares_used !== null
                              ? currentData.shares_used.toLocaleString('ru-RU')
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
