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
  if (v <= 15) return 'good';
  if (v <= 25) return 'warn';
  return 'bad';
}

/**
 * Уровень для P/E с учётом убытка.
 * Если P/E есть — стандартная градация.
 * Если P/E null + доход < 0 — компания убыточна ('loss').
 * Иначе — нет данных ('neutral').
 */
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

/**
 * Уровень P/B с учётом отрицательного капитала:
 * если капитал < 0, P/B не считается и показываем 'bad' (book deficit).
 */
function pbLevelContext(pb: number | null, equity: number | null): Level {
  if (pb !== null) return pbLevel(pb);
  if (equity !== null && equity < 0) return 'loss';
  return 'neutral';
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

  // ── Телекоммуникации ──
  // Абонентская база = устойчивая ежемесячная выручка; капитальные затраты
  // финансируются долгосрочным долгом. CR ~ 0.8–1.0 — норма.
  if (hasAny('telecom', 'телеком', 'связь', 'cellular', 'mobile',
             'мобильн', 'интернет', 'internet', 'media', 'медиа')) {
    return {
      industryLabel: 'Телекоммуникации / медиа',
      good: 1.0,
      warn: 0.7,
      thresholdHint: '≥ 1.0 — норма для телекома',
      tooltipLines: [
        'Телеком: стабильная подписная выручка снижает потребность',
        'в буфере ликвидности. CR ~ 0.8–1.0 — стандарт отрасли.',
        '≥ 1.0  —  хорошо',
        '0.7–1.0  —  норма для телекома',
        '< 0.7  —  агрессивное краткосрочное финансирование',
      ],
    };
  }

  // ── Ритейл и дистрибуция ──
  // Нет мощного сырьевого потока. Бизнес живёт от оборачиваемости запасов
  // и дебиторки. CR < 1 — почти всегда симптом беды. Норма Грэма ≥ 2.
  if (hasAny('retail', 'ритейл', 'торговл', 'supermarket', 'маркет',
             'consumer', 'потребител', 'distribution', 'дистрибуц',
             'food', 'продукт', 'фарм', 'pharma', 'drugstore')) {
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

  // ── IT и технологии ──
  // Как правило, asset-light, высокая маржа. Запасы минимальны.
  // Норма — ≥ 1.5, но в целом компании часто держат большой кеш.
  if (hasAny('tech', 'it ', 'software', 'програм', 'informati', 'информац',
             'digital', 'цифров', 'cloud', 'облак')) {
    return {
      industryLabel: 'IT / технологии',
      good: 1.5,
      warn: 1.0,
      thresholdHint: '≥ 1.5 — хорошо для IT',
      tooltipLines: [
        'IT, технологии: asset-light бизнес, часто большой кеш.',
        'Запасы минимальны, долг меньше, чем у промышленников.',
        '≥ 1.5  —  хорошо',
        '1.0–1.5  —  приемлемо',
        '< 1.0  —  нетипично для IT, требует объяснения',
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
  value, level, suffix = '', nullHint,
}: {
  value: number | null;
  level: Level;
  suffix?: string;
  nullHint?: string;
}) {
  if (value === null) {
    if (level === 'loss') {
      return (
        <span className="mult-cell loss null-hint" title={nullHint ?? 'Убыток за период — показатель не применим'}>
          Убыток
        </span>
      );
    }
    return (
      <span className="mult-cell neutral null-hint" title={nullHint ?? 'Недостаточно данных'}>
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

function fmt(n: number | null, decimals = 2): string {
  if (n === null) return '—';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
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
}

const CurrentCards: React.FC<CurrentCardsProps> = ({ data, crProfile }) => {
  const income = data.ltm_net_income;
  const isLoss = income !== null && income < 0;

  const cards = [
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
      level: pbLevelContext(data.pb_ratio, data.market_cap),
      hint: 'Цена / Балансовая стоимость',
      threshold: '≤ 1.5 — хорошо',
    },
    {
      label: 'ROE',
      value: data.roe,
      level: roeLevel(data.roe),
      hint: 'Рентабельность капитала',
      threshold: isLoss && data.roe !== null && data.roe < 0 ? 'Отрицательный ROE' : '≥ 15% — хорошо',
      suffix: '%',
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
      level: dyLevel(data.dividend_yield),
      hint: 'Дивидендная доходность',
      threshold: '≥ 3% — хорошо',
      suffix: '%',
    },
  ];

  return (
    <div className="current-cards-grid">
      {cards.map(({ label, value, level, hint, threshold, suffix = '' }) => (
        <div key={label} className={`current-card level-${level}`}>
          <div className="current-card-label">{label}</div>
          <div className="current-card-value">
            {value !== null
              ? `${fmt(value)}${suffix}`
              : level === 'loss' ? 'Убыток' : '—'}
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

const HistTable: React.FC<HistTableProps> = ({ rows, currentRow, crProfile }) => {
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
            <th className="col-mkt">Кап., млрд ₽</th>
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
            <th className="col-rev">Выручка LTM</th>
            <th className="col-ni">Прибыль LTM</th>
          </tr>
        </thead>
        <tbody>
          {/* LTM-строка (актуальные данные) */}
          {currentRow && (() => {
            const ltmIsLoss = currentRow.ltm_net_income !== null && currentRow.ltm_net_income < 0;
            return (
              <tr className="row-ltm">
                <td className="col-year"><span className="badge-ltm">LTM</span></td>
                <td>{currentRow.price_used !== null ? fmt(currentRow.price_used) : '—'}</td>
                <td>{currentRow.market_cap !== null ? (currentRow.market_cap / 1_000).toFixed(2) : '—'}</td>
                <td><MetricBadge
                  value={currentRow.pe_ratio}
                  level={peLevelContext(currentRow.pe_ratio, currentRow.ltm_net_income)}
                  nullHint={ltmIsLoss ? 'Убыток за период — P/E не рассчитывается' : undefined}
                /></td>
                <td><MetricBadge value={currentRow.pb_ratio} level={pbLevel(currentRow.pb_ratio)} /></td>
                <td><MetricBadge value={currentRow.roe} level={roeLevel(currentRow.roe)} suffix="%" /></td>
                <td><MetricBadge
                  value={currentRow.debt_to_equity}
                  level={deLevel(currentRow.debt_to_equity)}
                  nullHint={currentRow.debt_to_equity !== null && currentRow.debt_to_equity < 0 ? 'Отрицательный капитал' : undefined}
                /></td>
                <td><MetricBadge value={currentRow.current_ratio} level={crLevel(currentRow.current_ratio, crProfile)}
                  nullHint={crProfile.notApplicable ? 'CR не применим для данного типа компании' : undefined} /></td>
                <td><MetricBadge value={currentRow.dividend_yield} level={dyLevel(currentRow.dividend_yield)} suffix="%" /></td>
                <td>{fmtMln(currentRow.ltm_revenue)}</td>
                <td className={ltmIsLoss ? 'cell-loss' : ''}>{fmtMln(currentRow.ltm_net_income)}</td>
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
            const noDivs    = r.ltm_dividends_per_share === null;

            const peHint = isLoss
              ? 'Убыток за период — P/E не рассчитывается'
              : noIncome ? 'Нет данных о чистой прибыли (net_income)'
              : noPrice  ? 'Нет цены / акций'
              : undefined;

            const pbHint = negEquity
              ? 'Отрицательный капитал — P/B не рассчитывается'
              : noEquity ? 'Нет данных о капитале (equity)'
              : noPrice  ? 'Нет цены / акций'
              : undefined;

            const roeHint = noIncome
              ? 'Нет данных о чистой прибыли (net_income)'
              : noEquity ? 'Нет данных о капитале (equity)'
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
                <td><MetricBadge value={r.roe} level={roeLevel(r.roe)} suffix="%" nullHint={roeHint} /></td>
                <td><MetricBadge value={r.debt_to_equity} level={deLevel(r.debt_to_equity)} nullHint={deHint} /></td>
                <td><MetricBadge value={r.current_ratio} level={crLevel(r.current_ratio, crProfile)}
                  nullHint={noCurr ? 'Нет оборотных активов или краткосрочных обязательств' : crProfile.notApplicable ? 'CR не применим для данного типа компании' : undefined} /></td>
                <td><MetricBadge value={r.dividend_yield} level={dyLevel(r.dividend_yield)} suffix="%"
                  nullHint={noDivs ? 'Дивиденды не указаны' : noPrice ? 'Нет цены акции' : undefined} /></td>
                <td>{fmtMln(r.ltm_revenue)}</td>
                <td className={isLoss ? 'cell-loss' : ''}>{fmtMln(r.ltm_net_income)}</td>
              </tr>
            );
          })}

          {rows.length === 0 && !currentRow && (
            <tr>
              <td colSpan={11} className="table-empty">
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
                    <CurrentCards data={currentData} crProfile={crProfile} />
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
                <HistTable rows={rows} currentRow={currentData ?? undefined} crProfile={crProfile} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default MultipliersPanel;
