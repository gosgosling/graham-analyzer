import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Area, CartesianGrid, ComposedChart, DefaultTooltipContent, Line, ReferenceArea, ReferenceDot, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps,
} from 'recharts';
import {
  fetchPriceHistory, LIVE_PRICE_REFRESH_MS, LIVE_PRICE_STALE_MS,
  type PriceEvent, type PriceHistoryOut, type PricePoint,
} from '../services/prices.api';
import {
  fetchValuationHistory,
  fetchValuationSummary,
  type ValuationHistoryOut,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { useChartColors } from '../contexts/ThemeContext';
import { fetchCommodity, fetchOil, type CommodityOut, type OilOut } from '../services/market.api';
import { COMMODITY_BUTTON, isCommodity, type CommodityKey } from '../utils/commodities';
import { formatPerShare } from '../utils/perShare';
import { PHONE_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import { plotArea, useSpanMark, useTwoFingerSpan } from '../hooks/useTwoFingerSpan';
import { humanDate, SpanBand, SpanSummary } from './PriceSpanLayer';
import { createSpanStore, type SpanStore } from './priceSpanStore';
import './PriceChart.css';

/**
 * График цены по торговым дням с наложением множителей.
 *
 * Годовая точка скрывает ровно то, ради чего на график и смотрят: как цена
 * ходила внутри года относительно того, что компания зарабатывала. У ЛУКОЙЛа
 * между минимумом и максимумом одного 2022 года разница вдвое, а годовая
 * свеча показала бы одно число.
 *
 * **Множители приходят готовыми с бэкенда.** Делить цену на прибыль здесь
 * было бы проще, но неверно: множитель за конкретный день считается по тому
 * отчёту, который на ту дату уже был опубликован, и это знание живёт там же,
 * где отчёты. Посчитать P/E за январь 2025-го по прибыли всего 2025 года —
 * значит нарисовать, что рынок знал её за год вперёд.
 */

type Overlay = 'pe' | 'pb' | 'oil' | CommodityKey;

const OVERLAYS: { key: 'pe' | 'pb'; label: string; hint: string }[] = [
  { key: 'pe', label: 'P/E', hint: 'Цена к прибыли на акцию последнего опубликованного отчёта — без разовых статей, если аналитик их выделил' },
  { key: 'pb', label: 'P/B', hint: 'Цена к балансовой стоимости на акцию' },
];

/**
 * Стоимость поверх цены — такой, какой её посчитали бы тогда.
 *
 * Горизонталь по сегодняшнему расчёту сказать может только одно: где акция
 * стоит **сейчас** относительно оценки. Про прошлое она врёт, потому что
 * знает прибыль последнего отчёта и сегодняшнюю ставку.
 *
 * Ряд берётся из обратного теста: оценка считается по данным, обрезанным
 * годом отчёта, ступень начинается в день его раскрытия, а внутри неё оценка
 * пересчитывается раз в месяц по средней ключевой ставке за двенадцать
 * месяцев до этого дня.
 *
 * **Опорная — главная линия, справедливая — вспомогательная.** Так решили
 * данные, а не вкус: на всей базе покупка в день раскрытия ниже опорной дала
 * за два года +13% против −7% выше неё, а по справедливой разрыв втрое уже.
 * Поэтому опорная включена сразу и нарисована сплошной, справедливая —
 * по кнопке и пунктиром.
 */
type ValueKey = 'fair' | 'reference';

const VALUES: { key: ValueKey; label: string; hint: string }[] = [
  { key: 'reference', label: 'Опорная',
    hint: 'Оценка по прибыли с надбавкой за риск — от неё считается запас прочности' },
  { key: 'fair', label: 'Справедливая',
    hint: 'Та же лестница при рыночной премии, без надбавки — верх расчёта' },
];

/** Окна показа. «Вся» — от первого торгового дня, какой есть. */
const RANGES: { key: string; label: string; years: number | null }[] = [
  { key: '1y', label: '1 год', years: 1 },
  { key: '3y', label: '3 года', years: 3 },
  { key: '5y', label: '5 лет', years: 5 },
  { key: '10y', label: '10 лет', years: 10 },
  { key: 'all', label: 'Вся', years: null },
];

/**
 * Сколько точек рисовать. Больше полутора тысяч линия не различает: соседние
 * дни ложатся в один пиксель, а перерисовка при наведении начинает тормозить.
 * Прореживание идёт равномерным шагом и трогает только отрисовку — сводка,
 * средняя и границы считаются по всем точкам.
 */
const MAX_POINTS = 1000;
/** На телефоне поле в 360 пикселей — больше точек там глазу не различить. */
const MAX_POINTS_PHONE = 450;

/**
 * Во сколько раз шкала множителя может превышать его же медиану.
 *
 * Множитель взлетает не тогда, когда акция дорога, а когда прибыль просела:
 * у ЛУКОЙЛа P/E доходит до 340, потому что прибыль 2020 года схлопнулась до
 * 15 млрд. Это настоящая величина и настоящий эффект Молодовского, но если
 * отдать ей шкалу, все остальные годы сожмутся в полоску у нуля.
 *
 * **Отбрасывать доли процентов бесполезно, и это выяснилось на данных.**
 * Сперва здесь стояла обрезка по краям на 1%; всплеск держался ровно до
 * выхода следующего отчёта, то есть год — около 6% точек, — и шкала всё
 * равно уходила за триста. Величина искажения тут не редкая, а длительная,
 * и мерить её долей точек нельзя.
 *
 * Медиана таких всплесков не замечает по устройству, поэтому потолок считается
 * от неё. Втрое — с запасом: у ровной компании множитель за годы так широко не
 * ходит, а у неровной верх всё равно упирается в этот предел.
 */
const MEDIAN_HEADROOM = 3;

/**
 * P/B, ниже которого период на графике затеняется как признак ловушки.
 *
 * Тот же порог, что `TRAP_PRICE_TO_BOOK` на бэкенде: рынок платит меньше
 * половины балансового капитала. На истории это единственный найденный
 * признак, отделяющий «дёшево, которое сработало» от «дёшево, которое
 * простояло»: ниже опорной при P/B < 0,5 покупка давала за два года +13%, при
 * P/B ≥ 0,5 — +48%. Башнефть пять лет подряд была «дёшево» — и вся под этой
 * тенью.
 */
const TRAP_PRICE_TO_BOOK = 0.5;

/**
 * Запас, с которого период закрашивается как окно входа.
 *
 * Закрашивать любую цену ниже опорной — значит выдавать за сигнал шум. На
 * всей базе (покупка в день раскрытия, цена через два года):
 *
 *     ниже опорной на 0–15%     37 случаев, медиана +10%, в плюсе 57%
 *     ниже на 15–33%            30 случаев, медиана +40%, в плюсе 80%
 *     ниже на 33% и больше      74 случая,  медиана +19%, в плюсе 62%
 *     выше опорной             297 случаев, медиана  +4%, в плюсе 54%
 *
 * Мелкий запас от «выше опорной» почти не отличается. Именно он закрасил
 * Северсталь на весь 2025 год: цена стояла на 12–14% ниже опорной, пока
 * прибыль рушилась, и продолжала падать. Порог подобран на той же истории,
 * на которой проверен, — это направление, а не закон.
 */
const ZONE_MARGIN = 0.15;

/** Отрезки подряд идущих точек, где P/B ниже порога. → [[с, по], ...]. */
function trapRuns(points: PricePoint[]): [string, string][] {
  const runs: [string, string][] = [];
  let start: string | null = null;
  let last: string | null = null;
  for (const point of points) {
    const trapped = point.pb !== null && point.pb !== undefined && point.pb > 0
      && point.pb < TRAP_PRICE_TO_BOOK;
    if (trapped) {
      if (start === null) start = point.date;
      last = point.date;
    } else if (start !== null && last !== null) {
      runs.push([start, last]);
      start = null;
    }
  }
  if (start !== null && last !== null) runs.push([start, last]);
  return runs;
}

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Цена в рублях: число знаков по масштабу, а не фиксированные ноль.
 *
 * `ru` округляет до целых, и у копеечной бумаги от цены ничего не оставалось:
 * ТГК-2 при 0,417 ₽ показывала «0 ₽ сейчас», «коридор 0 — 1 ₽» и подсказку
 * «Цена : 1 ₽», хотя в карточке над графиком стояло правильное 0,417 ₽.
 * Ту же беду однажды лечили в таблицах — тем же `formatPerShare`. */
const rub = (value: number) => formatPerShare(value);

/** Подпись у края поля: у дорогой бумаги копейки — шум. */
const edgeLabel = (value: number) => (Math.abs(value) >= 100 ? ru(value) : rub(value));

/** Изменение в процентах: «+12,3%», «−4%», «0%». */
const pctText = (v: number) => (Math.abs(v) < 0.05
  ? '0%'
  : `${v > 0 ? '+' : '−'}${ru(Math.abs(v), Math.abs(v) < 10 ? 1 : 0)}%`);

/** Дата точки, над которой курсор. `null`, пока recharts её не определил. */
const pointAt = (e: unknown): string | null => {
  const at = (e as { activeLabel?: string | number } | null)?.activeLabel;
  return at === undefined || at === null ? null : String(at);
};

/** Пиксель курсора от левого края поля. Берётся из самого события мыши, а не
 *  из состояния recharts: `chartX` там есть не всегда, и подсветка молча
 *  схлопывалась в нулевую ширину. */
const clientXOf = (e: unknown): number | null => {
  const x = (e as { clientX?: number } | null)?.clientX;
  return typeof x === 'number' ? x : null;
};

/** Подпись даты на оси: год для длинных окон, месяц-год для коротких. */
const axisDate = (iso: string, longRange: boolean) => {
  const [y, m] = iso.split('-');
  return longRange ? y : `${m}.${y.slice(2)}`;
};

/**
 * Засечки оси — по одной на период, а не по усмотрению библиотеки.
 *
 * Автоматические засечки ставятся равномерно по номеру точки, и на длинном
 * окне их выходит больше, чем лет: под графиком печаталось «2021 2022 2022
 * 2022 2023 2023». Отсеивать повторы в форматтере нельзя — он вызывается и на
 * проходе измерения, и на отрисовке, так что к моменту рисования все годы
 * оказывались уже «виденными», и подписи пропадали целиком.
 *
 * Поэтому берётся первая точка каждого периода: сколько подписей, столько и
 * делений, и повторяться нечему.
 */
function periodTicks(points: PricePoint[], longRange: boolean): string[] {
  const seen = new Set<string>();
  const ticks: string[] = [];
  for (const point of points) {
    const key = longRange ? point.date.slice(0, 4) : point.date.slice(0, 7);
    if (seen.has(key)) continue;
    seen.add(key);
    ticks.push(point.date);
  }
  // Неполный первый год — окно «5 лет» начинается в сентябре — давал подпись
  // «2021» вплотную к «2022», и на телефоне они сливались. Год, от которого
  // в окне меньше половины, не подписывается.
  if (longRange && ticks.length > 1 && Number(ticks[0].slice(5, 7)) > 6) {
    ticks.shift();
  }
  // На коротком окне месяцев двенадцать и подписи сливаются — берём каждый
  // второй. Года на длинном окне помещаются все.
  return longRange || ticks.length <= 8
    ? ticks
    : ticks.filter((_, i) => i % 2 === 0);
}

/** Шкала множителя: от минимума до медианы, умноженной на запас. */
function multipleBounds(values: number[]): [number, number] | null {
  if (values.length < 10) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const low = sorted[0];
  const high = Math.min(sorted[sorted.length - 1], median * MEDIAN_HEADROOM);
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return null;
  // Округление вверх до приличного числа: ось с потолком 26,7 читается хуже,
  // чем с потолком 30, а точность здесь не нужна — это рамка, а не величина.
  const step = high > 50 ? 10 : high > 20 ? 5 : 1;
  return [Math.max(0, Math.floor(low)), Math.ceil(high / step) * step];
}

/** События одного дня графика: отчёт и дивиденд могут прийтись на один день. */
interface EventMarkData {
  date: string;
  kinds: PriceEvent['kind'][];
  title: string;
}

/**
 * Привязывает события к точкам ряда. Ось категориальная, и засечка встаёт
 * только на дату, которая в ряду есть: событие в выходной или между
 * прореженными точками переносится на ближайший следующий торговый день.
 * События вне окна не рисуются.
 */
function eventMarks(events: PriceEvent[], points: PricePoint[]): EventMarkData[] {
  if (!points.length || !events.length) return [];
  const dates = points.map((p) => p.date);
  const first = dates[0];
  const last = dates[dates.length - 1];
  const byDate = new Map<string, { kinds: Set<PriceEvent['kind']>; lines: string[] }>();
  let cursor = 0;
  for (const event of [...events].sort((a, b) => a.date.localeCompare(b.date))) {
    if (event.date < first || event.date > last) continue;
    while (cursor < dates.length && dates[cursor] < event.date) cursor += 1;
    if (cursor >= dates.length) break;
    const at = dates[cursor];
    const slot = byDate.get(at) ?? { kinds: new Set(), lines: [] };
    slot.kinds.add(event.kind);
    const day = event.date.split('-').reverse().join('.');
    slot.lines.push(`${day} · ${event.label}${event.detail ? ` — ${event.detail}` : ''}`);
    byDate.set(at, slot);
  }
  return Array.from(byDate, ([date, slot]) => ({
    date,
    kinds: (['report', 'dividend', 'split'] as const).filter((k) => slot.kinds.has(k)),
    title: slot.lines.join('\n'),
  }));
}

/** Метка события у нижнего края поля; подробности — в системной подсказке. */
/** Ширина плашки цены на телефоне: по числу знаков — мерить SVG-текст до отрисовки нечем. */
const pillWidth = (text: string) => Math.round(text.length * 6.6 + 12);

/**
 * Подпись цены на телефоне — справа от линии, как в приложениях брокеров.
 * Текущая цена — плашкой цвета линии, минимум окна — просто текстом.
 */
function PhonePriceTick(props: {
  x?: number; y?: number; payload?: { value: number };
  current: number; colors: ReturnType<typeof useChartColors>;
  format?: (v: number) => string;
}) {
  const { x = 0, y = 0, payload, current, colors, format = edgeLabel } = props;
  if (!payload) return null;
  const text = format(payload.value);
  if (payload.value !== current) {
    return (
      <text x={x + 6} y={y} dy={4} textAnchor="start" fill={colors.axis} fontSize={11}>{text}</text>
    );
  }
  return (
    <g>
      <rect x={x} y={y - 9} width={pillWidth(text)} height={18} rx={4} fill={colors.line1} />
      <text x={x + 6} y={y} dy={4} textAnchor="start" fill="#fff" fontSize={11} fontWeight={600}>{text}</text>
    </g>
  );
}

/**
 * Подсказка на телефоне: дата и числа без пояснений, у верхнего края поля.
 *
 * Полная подсказка с основой оценки и ставкой ОФЗ шириной больше экрана —
 * у края она вылезала за телефон. Пояснения к опорной есть в разделе
 * «Оценка»; здесь важно, сколько стоило в этот день.
 */
function PhoneTip({ active, payload, label, colors, format }: {
  active?: boolean;
  payload?: readonly { name?: unknown; value?: unknown; color?: string }[];
  label?: unknown;
  colors: ReturnType<typeof useChartColors>;
  format: (value: number, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  // Цена — первой: ради неё и водят пальцем; остальное — как в легенде.
  const rows = payload.filter((p) => typeof p.value === 'number')
    .sort((a, b) => Number(b.name === 'Цена') - Number(a.name === 'Цена'));
  return (
    <div className="pc-tip" style={{ background: colors.tooltipBg, borderColor: colors.tooltipBorder, color: colors.textPrimary }}>
      <div className="pc-tip-date">{humanDate(String(label))}</div>
      {rows.map((p) => (
        <div key={String(p.name)} className="pc-tip-row">
          <i style={{ background: p.color }} />
          <span>{String(p.name)}</span>
          <b>{format(p.value as number, String(p.name))}</b>
        </div>
      ))}
    </div>
  );
}

function EventMark(props: { mark: EventMarkData; colors: ReturnType<typeof useChartColors>; viewBox?: { x: number; y: number; height: number } }) {
  const { mark, colors, viewBox } = props;
  if (!viewBox) return null;
  const x = viewBox.x;
  const bottom = viewBox.y + viewBox.height;
  return (
    <g className="pc-event">
      <title>{mark.title}</title>
      {mark.kinds.map((kind, i) => {
        const y = bottom - 7 - i * 11;
        if (kind === 'dividend') {
          return <circle key={kind} cx={x} cy={y} r={3.6} fill={colors.line3} stroke={colors.dotStroke} strokeWidth={1} />;
        }
        if (kind === 'split') {
          return (
            <path key={kind} d={`M${x} ${y - 4.5} L${x + 4.5} ${y} L${x} ${y + 4.5} L${x - 4.5} ${y} Z`}
              fill={colors.line2} stroke={colors.dotStroke} strokeWidth={1} />
          );
        }
        return (
          <rect key={kind} x={x - 3.5} y={y - 3.5} width={7} height={7} rx={1.5}
            fill={colors.axis} stroke={colors.dotStroke} strokeWidth={1} />
        );
      })}
      {/* Невидимая широкая мишень: в четырёхпиксельную метку трудно попасть. */}
      <rect x={x - 6} y={bottom - 12 - (mark.kinds.length - 1) * 11} width={12}
        height={12 + (mark.kinds.length - 1) * 11} fill="transparent" />
    </g>
  );
}

/** Дисконт Urals к Brent, $/барр. — задаёт читатель, хранится в браузере. */
const URALS_KEY = 'ga.chart.uralsDiscount';
const readDiscount = (): number => {
  try {
    const v = Number(window.localStorage.getItem(URALS_KEY));
    return Number.isFinite(v) && v > 0 ? v : 12;
  } catch {
    return 12;
  }
};

/**
 * Точки и сводка графика за выбранное окно. Наложения здесь нет — оно
 * считается отдельно (buildLayer) и рисуется своим слоем, чтобы его
 * включение не пересчитывало и не перерисовывало основной график.
 */
function buildView(
  data: PriceHistoryOut | undefined,
  history: ValuationHistoryOut | undefined,
  range: string,
  isPhone: boolean,
) {
  const raw = data?.points ?? [];
  if (!raw.length) return null;

  // Оценка приклеивается к дням цены. Отрезки идут подряд и не
  // перекрываются, поэтому курсор просто едет вперёд вместе с датами — ровно
  // так же, как множители считаются на бэкенде. День вне отрезков (раньше
  // первого раскрытия или при отказе в оценке) остаётся без линии.
  const marks = (history?.segments ?? [])
    .filter((x) => !x.refused)
    .sort((a, b) => a.from.localeCompare(b.from));
  let cursor = -1;
  const all = marks.length === 0 ? raw : raw.map((point) => {
    while (cursor + 1 < marks.length && marks[cursor + 1].from <= point.date) {
      cursor += 1;
    }
    const mark = cursor >= 0 && point.date < marks[cursor].till ? marks[cursor] : null;
    const reference = mark?.reference ?? null;
    return {
      ...point,
      fair: mark?.fair ?? null,
      reference,
      // Зона «цена ниже опорной» — пара [низ, верх] для заливки между
      // линиями. Только при запасе от ZONE_MARGIN: мелкий запас окном
      // входа не был, см. константу.
      below: reference !== null && point.price <= reference * (1 - ZONE_MARGIN)
        ? [point.price, reference] as [number, number]
        : null,
      basis_label: mark?.basis ?? null,
      basis_rate: mark?.risk_free ?? null,
      basis_rate_source: mark?.risk_free_source ?? null,
    };
  });

  const base = all;

  const years = RANGES.find((r) => r.key === range)?.years ?? null;
  let slice = base;
  if (years !== null) {
    const edge = new Date(base[base.length - 1].date);
    edge.setFullYear(edge.getFullYear() - years);
    const iso = edge.toISOString().slice(0, 10);
    const cut = base.filter((p) => p.date >= iso);
    // Окно шире имеющейся истории — показываем то, что есть, а не пустоту.
    if (cut.length > 1) slice = cut;
  }

  const prices = slice.map((p) => p.price);
  const average = prices.reduce((a, b) => a + b, 0) / prices.length;

  // Прореживание — только для отрисовки. Крайние точки сохраняются всегда:
  // без них у линии срезается начало или конец окна.
  const step = Math.ceil(slice.length / (isPhone ? MAX_POINTS_PHONE : MAX_POINTS));
  const thin = step > 1
    ? slice.filter((_, i) => i % step === 0 || i === slice.length - 1)
    : slice;

  const points = thin;

  return {
    points,
    average,
    min: Math.min(...prices),
    max: Math.max(...prices),
    // Подпись на оси у копеечной бумаги длиннее обычной: «0,004365» против
    // «1 271». В прежнюю ширину она не помещается и обрезается.
    pennyScale: Math.max(...prices.map(Math.abs)) < 1,
    first: slice[0],
    last: slice[slice.length - 1],
    change: slice[0].price > 0
      ? (slice[slice.length - 1].price - slice[0].price) / slice[0].price
      : null,
    ticks: periodTicks(points, (years ?? 99) >= 3),
    // Затенение считается по прореженным точкам: границы отрезков должны
    // совпадать с категориями оси, иначе recharts их не нарисует.
    traps: trapRuns(points),
    longRange: (years ?? 99) >= 3,
    thinned: step > 1,
  };
}

type ChartView = NonNullable<ReturnType<typeof buildView>>;

// ─── Наложение: P/E, P/B, нефть, сырьё ────────────────────────────────────

/** Ключ строки наложения в подсказке основного графика. */
const LAYER_KEY = '__layer';

interface LayerPoint { date: string; v?: number }

interface Layer {
  /** Те же даты, что у основного графика; без `v` — линия обрывается. */
  points: LayerPoint[];
  bounds: [number, number] | null;
  /** Точное значение на дату — для подсказки, включая ушедшие за шкалу. */
  values: Map<string, number>;
  /** Причины пропусков множителя в окне. */
  gaps: string[];
  /** Сколько дней множителя ушло за потолок шкалы. */
  offScale: number;
  axisFormat: (v: number) => string;
}

/** То, что подсказке основного графика надо знать о слое. */
interface LayerInfo {
  label: string;
  values: Map<string, number>;
  /** Значение для подсказки; точка основного графика — для года отчёта. */
  format: (v: number, point?: PricePoint) => string;
  gapOf?: (p: PricePoint) => string | null;
}

/** Подсказка основного графика + строка наложения на ту же дату. */
function withLayerRow<T extends { name?: unknown; value?: unknown; color?: string }>(
  payload: readonly T[] | undefined,
  label: unknown,
  layer: LayerInfo | null,
  colors: ReturnType<typeof useChartColors>,
): T[] {
  const rows = payload ? [...payload] : [];
  if (!layer || !rows.length) return rows;
  const v = layer.values.get(String(label));
  if (v === undefined) return rows;
  return [...rows, { ...rows[0], name: layer.label, value: v, color: colors.line4, dataKey: LAYER_KEY, unit: undefined }];
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Месячный ряд — плавной линией по дням цены.
 *
 * Среднее за месяц ставится на его середину, между соседними месяцами —
 * прямая. Раньше значение месяца держалось до следующего, и золото с газом
 * рисовались прямоугольными ступеньками: глаз читал их как скачки в первый
 * день месяца, которых не было. За последним месяцем линия доходит до его
 * конца и обрывается — дальше данных ещё нет.
 */
function interpolateMonthly(dates: string[], series: [string, number | null][]): (number | undefined)[] {
  const anchors = series
    .filter((x): x is [string, number] => x[1] !== null)
    .map(([d, v]) => ({ start: Date.parse(d), t: Date.parse(d) + 14 * DAY_MS, v }));
  if (!anchors.length) return dates.map(() => undefined);
  const last = anchors[anchors.length - 1];
  const lastEnd = new Date(last.start);
  lastEnd.setUTCMonth(lastEnd.getUTCMonth() + 1);
  let k = -1;
  return dates.map((d) => {
    const t = Date.parse(d);
    while (k + 1 < anchors.length && anchors[k + 1].t <= t) k += 1;
    if (k < 0) return t >= anchors[0].start ? anchors[0].v : undefined;
    if (k === anchors.length - 1) return t < lastEnd.getTime() ? last.v : undefined;
    const a = anchors[k];
    const b = anchors[k + 1];
    return a.v + ((b.v - a.v) * (t - a.t)) / (b.t - a.t);
  });
}

function buildLayer(
  points: PricePoint[],
  overlay: Overlay,
  { oilPoints, commodity, rub: inRub, discount }: {
    oilPoints?: OilOut['points'];
    commodity?: CommodityOut;
    rub: boolean;
    discount: number;
  },
): Layer | null {
  const dates = points.map((p) => p.date);
  let raw: (number | undefined)[];
  let gaps: string[] = [];
  if (overlay === 'pe' || overlay === 'pb') {
    raw = points.map((p) => p[overlay] ?? undefined);
    // Пропуск без причины читается как сбой данных; причин же ровно три, и
    // все — про компанию: убыток, нераскрытый отчёт, первый отчёт не вышел.
    gaps = Array.from(new Set(points
      .filter((p) => p[overlay] === null)
      .map((p) => (overlay === 'pe' ? p.pe_gap : p.pb_gap))
      .filter((reason): reason is string => !!reason)));
  } else if (overlay === 'oil') {
    if (!oilPoints?.length) return null;
    // Нефть дневная — последним известным днём: Brent в праздники
    // Мосбиржи торгуется, а в праздники Лондона — нет.
    let j = -1;
    raw = dates.map((d) => {
      while (j + 1 < oilPoints.length && oilPoints[j + 1][0] <= d) j += 1;
      if (j < 0) return undefined;
      const [, brent, rate] = oilPoints[j];
      const usd = brent - discount;
      return inRub ? (rate ? usd * rate : undefined) : usd;
    });
  } else {
    if (!commodity || commodity.key !== overlay || !(commodity.points.length || commodity.daily?.length)) return null;
    const rub = inRub && !commodity.index;
    const conv = (v: number, rate: number | null) => (rub ? (rate ? v * rate : undefined) : v);
    // Дневной биржевой ряд — как нефть, последним известным днём. Месячный
    // Всемирного банка — только для лет раньше начала дневного (у TTF это
    // до 2017-го, у карбамида — до 2020-го) и для сырья без биржевого ряда.
    const daily = commodity.daily ?? [];
    const dailyStart = daily.length ? daily[0][0] : null;
    const monthly = interpolateMonthly(dates, commodity.points.map(([d, v, rate]) => [d, conv(v, rate) ?? null]));
    let j = -1;
    raw = dates.map((d, i) => {
      if (dailyStart === null || d < dailyStart) return monthly[i];
      while (j + 1 < daily.length && daily[j + 1][0] <= d) j += 1;
      if (j < 0) return undefined;
      const [, v, rate] = daily[j];
      return conv(v, rate);
    });
  }

  const values = new Map<string, number>();
  raw.forEach((v, i) => { if (v !== undefined) values.set(dates[i], v); });
  const positive = raw.filter((v): v is number => v !== undefined && v > 0);
  const isMult = overlay === 'pe' || overlay === 'pb';
  // У цены потолка нет; у множителя — тройная медиана (multipleBounds).
  const bounds: [number, number] | null = isMult
    ? multipleBounds(positive)
    : positive.length ? [Math.floor(Math.min(...positive) * 0.9), Math.ceil(Math.max(...positive) * 1.05)] : null;
  // Значения выше потолка вырезаются из отрисовки. Прижимать их к краю
  // нельзя: recharts рисует к границе отвес, и провал прибыли превращается
  // в столб во всю высоту поля. Обрыв честнее, а число остаётся в подсказке.
  // Ключ не пишется вовсе: `null` recharts читал как ноль и уводил линию
  // на дно поля, отсутствующий ключ он понимает верно.
  let offScale = 0;
  const drawn = dates.map((date, i) => {
    const v = raw[i];
    if (v === undefined) return { date };
    if (isMult && bounds && v > bounds[1]) { offScale += 1; return { date }; }
    return { date, v };
  });
  return {
    points: drawn,
    bounds,
    values,
    gaps,
    offScale,
    axisFormat: (v: number) => ru(v, isMult && v < 10 ? 1 : 0),
  };
}

/**
 * Слой наложения: отдельный лёгкий график под основным.
 *
 * Поле у него ровно то же: те же отступы, а места осей основного графика
 * заняты пустыми осями той же ширины. Своя шкала — подписями внутри поля
 * слева, поэтому основной график при включении наложения не сужается и не
 * сдвигается. Указатель слой не ловит — подсказку и протяжку ведёт основной
 * график, а значение наложения он берёт из layerRef.
 */
const OverlayLayer = React.memo(function OverlayLayer({
  points, bounds, colors, isPhone, leftWidth, rightWidth, format, shared = false,
}: {
  points: LayerPoint[];
  bounds: [number, number] | null;
  /** Режим «в %»: шкала общая с ценой, свои подписи не нужны. */
  shared?: boolean;
  colors: ReturnType<typeof useChartColors>;
  isPhone: boolean;
  leftWidth: number;
  rightWidth: number;
  format: (v: number) => string;
}) {
  return (
    <div className="pc-layer" aria-hidden>
      <ResponsiveContainer width="100%" height={isPhone ? 300 : 320}>
        <ComposedChart
          data={points}
          margin={isPhone ? { top: 12, right: 0, bottom: 0, left: 0 } : { top: 16, right: 44, bottom: 4, left: 4 }}
        >
          <XAxis dataKey="date" height={30} tick={false} axisLine={false} tickLine={false} />
          {isPhone
            ? <YAxis yAxisId="spacer" orientation="right" width={rightWidth} tick={false} axisLine={false} tickLine={false} />
            : <YAxis yAxisId="spacer" width={leftWidth} tick={false} axisLine={false} tickLine={false} />}
          <YAxis
            yAxisId="v"
            orientation="left"
            mirror
            axisLine={false}
            tickLine={false}
            tick={shared ? false : { fill: colors.line4, fontSize: 11 }}
            tickFormatter={format}
            domain={bounds ?? ['auto', 'auto']}
            allowDataOverflow
          />
          <Line
            yAxisId="v"
            /* Ломаная, а не сглаженная: на пропуске в двести с лишним дней
               монотонная кривая уходит в перелёт ниже поля, а прямой между
               соседями перелетать нечем. */
            type="linear"
            dataKey="v"
            stroke={colors.line4}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
});

/** Ширина правой оси цены на телефоне — под плашку текущей цены. */
const phoneAxisWidth = (view: ChartView, format: (v: number) => string = edgeLabel) =>
  Math.max(...phoneTicksOf(view).map((v) => pillWidth(format(v)))) + 6;

/**
 * Режим «в %»: цена (и уровни) — изменение от первого дня окна, как
 * процентная шкала в TradingView. Так цена акции и цена сырья встают на одну
 * шкалу и сравниваются ходом, а не рублями против долларов.
 */
function toPctView(view: ChartView): ChartView {
  const base = view.points[0]?.price;
  if (!base) return view;
  const pc = (v: unknown) => (typeof v === 'number' ? (v / base - 1) * 100 : v);
  const points = view.points.map((p) => {
    const raw = p as unknown as Record<string, unknown>;
    const below = raw.below as [number, number] | null | undefined;
    return {
      ...p,
      price: pc(p.price) as number,
      price_abs: p.price,
      reference: pc(raw.reference),
      fair: pc(raw.fair),
      below: below ? [pc(below[0]), pc(below[1])] : below,
    } as unknown as PricePoint;
  });
  return {
    ...view,
    points,
    average: pc(view.average) as number,
    min: pc(view.min) as number,
    max: pc(view.max) as number,
    first: points[0],
    last: points[points.length - 1],
  };
}

/** Слой в режиме «в %»: от первого дня окна, где у ряда есть значение. */
function toPctLayer(layer: Layer): Layer {
  const base = layer.points.find((p) => p.v !== undefined)?.v;
  if (!base) return layer;
  const pc = (v: number) => (v / base - 1) * 100;
  const values = new Map<string, number>();
  layer.values.forEach((v, d) => values.set(d, pc(v)));
  return {
    ...layer,
    points: layer.points.map((p) => (p.v === undefined ? p : { date: p.date, v: pc(p.v) })),
    values,
    bounds: null,
    axisFormat: pctText,
  };
}

/** Круглые засечки процентной шкалы: шаг 5, 10, 20, 25, 50… и всегда ноль. */
function pctTicks([lo, hi]: [number, number]): number[] {
  const raw = (hi - lo) / 5;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((x) => x >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

/** Общая шкала цены и слоя в режиме «в %» — по всем видимым линиям, с полями. */
function sharedDomain(view: ChartView, layer: Layer, keys: string[]): [number, number] {
  const all: number[] = [];
  view.points.forEach((p) => {
    const raw = p as unknown as Record<string, unknown>;
    keys.forEach((k) => { if (typeof raw[k] === 'number') all.push(raw[k] as number); });
  });
  layer.points.forEach((p) => { if (p.v !== undefined) all.push(p.v); });
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo) * 0.05 || 1;
  return [Math.floor(lo - pad), Math.ceil(hi + pad)];
}

/**
 * На телефоне на оси цены две подписи — минимум окна и текущая, как у
 * брокеров. Сетка из пяти чисел на узком поле читалась хуже, чем линия.
 * Минимум рядом с текущей не подписываем — плашки легли бы друг на друга.
 */
const phoneTicksOf = (view: ChartView) => (Math.abs(view.last.price - view.min) > (view.max - view.min) * 0.08
  ? [view.min, view.last.price]
  : [view.last.price]);

/**
 * Основной график: цена, опорная, справедливая, события.
 *
 * Вынесен в отдельный компонент под React.memo ради одного: переключение
 * наложения (P/E, нефть, золото…) его не перерисовывает. Перерисовка
 * recharts с тысячей точек и пятью линиями стоила около 300 мс на
 * компьютере и втрое больше на телефоне — каждое нажатие кнопки под
 * графиком подвешивало страницу. Наложение живёт в своём слое
 * (OverlayLayer), а в подсказку попадает через layerRef.
 */
const MainChart = React.memo(function MainChart({
  view, colors, isPhone, hasLevels, events,
  spanStore, measureBand, drag, canvasLeft, layerRef, hiddenRef, pct = false, domain,
}: {
  view: ChartView;
  /** Режим «в %»: цена — изменение от начала окна, шкала общая со слоем. */
  pct?: boolean;
  domain?: [number, number];
  colors: ReturnType<typeof useChartColors>;
  isPhone: boolean;
  hasLevels: boolean;
  events: PriceEvent[] | undefined;
  spanStore: SpanStore;
  measureBand: () => void;
  drag: React.MutableRefObject<{ pressed: boolean; fromX: number; fromDate: string } | null>;
  canvasLeft: React.MutableRefObject<number>;
  layerRef: React.MutableRefObject<LayerInfo | null>;
  /** Выключенные линии — их строки убираются из подсказки. */
  hiddenRef: React.MutableRefObject<Set<string>>;
}) {
  // Опорная, справедливая и засечки событий рисуются всегда, а прячутся
  // классом на обёртке (hide-reference и т. п., см. PriceChart.css). Иначе
  // каждая кнопка под графиком перерисовывала его целиком — 250–350 мс.
  // Заодно шкала не прыгает: она считается и по спрятанным линиям.
  const marks = useMemo(() => eventMarks(events ?? [], view.points), [events, view.points]);
  const visibleRows = <T extends { name?: unknown }>(rows: T[]) => rows.filter((r) => !hiddenRef.current.has(String(r.name)));
  const lastReference = (view.last as { reference?: number | null }).reference ?? null;
  // Подписи последних значений расходятся в разные стороны, чтобы не лечь
  // друг на друга: выше та, что выше на графике.
  const priceOnTop = lastReference === null || view.last.price >= lastReference;
  // Даты на телефоне — через одну, если их много, и не у самого левого края:
  // поле там начинается от края экрана, и подпись «2022» обрезалась пополам.
  const edge = view.points.length * 0.06;
  const phoneDateTicks = (view.ticks.length > 5 ? view.ticks.filter((_, i) => i % 2 === 1) : view.ticks)
    .filter((d) => view.points.findIndex((p) => p.date === d) >= edge);
  const phoneTicks = phoneTicksOf(view);
  const fmt = pct ? pctText : edgeLabel;
  return (
        <ResponsiveContainer width="100%" height={isPhone ? 300 : 320}>
          <ComposedChart
            data={view.points}
            margin={isPhone
              ? { top: 12, right: 0, bottom: 0, left: 0 }
              : { top: 16, right: 44, bottom: 4, left: 4 }}
            // Выделение одной левой кнопкой: нажали, провели, отпустили.
            // Нажатие само по себе снимает прежнее — щелчок по пустому месту
            // очищает график, и отдельная кнопка «сбросить» не нужна.
            //
            // Дата начала берётся не только из нажатия: пока по графику не
            // поводили мышью, recharts не знает, над какой точкой курсор, и
            // первое же нажатие давало пустую дату. Поэтому начало
            // подхватывается и с первого движения при зажатой кнопке.
            onMouseDown={(state, event) => {
              spanStore.set(null);
              measureBand();
              // Пиксель известен всегда, дата — не всегда: пока по графику не
              // поводили мышью, recharts не знает, над какой точкой курсор.
              // Поэтому край подсветки берём сразу, а дату дотягиваем с
              // первого же движения — иначе левая граница прыгала туда, где
              // курсор оказался, а не туда, где нажали.
              const x = clientXOf(event);
              drag.current = {
                pressed: true,
                fromX: x === null ? 0 : x - canvasLeft.current,
                fromDate: pointAt(state) ?? '',
              };
            }}
            onMouseMove={(state, event) => {
              const held = drag.current;
              if (!held?.pressed) return;
              const at = pointAt(state);
              const x = clientXOf(event);
              if (at === null || x === null) return;
              if (!held.fromDate) {
                held.fromDate = at;   // край уже записан при нажатии
                return;
              }
              spanStore.set({
                fromX: held.fromX, toX: x - canvasLeft.current,
                fromDate: held.fromDate, toDate: at,
              });
            }}
            onMouseUp={() => { if (drag.current) drag.current.pressed = false; }}
            // Курсор ушёл с поля при зажатой кнопке — отпускания мы не увидим,
            // и без этого протяжка «залипала» бы до следующего нажатия.
            onMouseLeave={() => { if (drag.current) drag.current.pressed = false; }}
            style={{ userSelect: 'none' }}
          >
            {!isPhone && <CartesianGrid stroke={colors.grid} vertical={false} />}
            <XAxis
              dataKey="date"
              tick={{ fill: colors.axis, fontSize: 11 }}
              ticks={isPhone ? phoneDateTicks : view.ticks}
              tickFormatter={(v: string) => axisDate(v, view.longRange)}
              interval={0}
              minTickGap={0}
              stroke={colors.grid}
            />
            {isPhone ? (
              // Ось только справа и узкая — под плашку текущей цены; слева
              // оси нет, линия начинается от края экрана.
              <YAxis
                yAxisId="price"
                orientation="right"
                width={Math.max(...phoneTicks.map((v) => pillWidth(fmt(v)))) + 6}
                axisLine={false}
                tickLine={false}
                tickSize={0}
                tickMargin={4}
                ticks={phoneTicks}
                interval={0}
                tick={<PhonePriceTick current={view.last.price} colors={colors} format={fmt} />}
                domain={domain ?? ['auto', 'auto']}
                allowDataOverflow={!!domain}
              />
            ) : (
              <YAxis
                yAxisId="price"
                tick={{ fill: colors.axis, fontSize: 11 }}
                tickFormatter={(v: number) => (pct ? pctText(v) : rub(v))}
                ticks={pct && domain ? pctTicks(domain) : undefined}
                domain={domain ?? ['auto', 'auto']}
                allowDataOverflow={!!domain}
                width={view.pennyScale ? 74 : 58}
                stroke={colors.grid}
              />
            )}

            {/* Ноль — день, от которого считаются проценты. */}
            {pct && <ReferenceLine yAxisId="price" y={0} stroke={colors.axis} strokeDasharray="3 3" />}
            {view.traps.map(([from, till]) => (
              <ReferenceArea
                key={from}
                yAxisId="price"
                x1={from}
                x2={till}
                fill={colors.axis}
                fillOpacity={0.14}
                stroke="none"
                ifOverflow="hidden"
              />
            ))}

            {/* Заливка между ценой и опорной там, где цена ниже. Под линиями,
                чтобы не мутить их цвет; в подсказку не идёт — это не величина,
                а подсветка того, что уже видно по двум линиям. */}
            {hasLevels && (
              <Area
                className="pc-s-ref"
                yAxisId="price"
                type="linear"
                dataKey="below"
                stroke="none"
                fill={colors.zoneBelow}
                fillOpacity={1}
                connectNulls={false}
                activeDot={false}
                tooltipType="none"
                isAnimationActive={false}
              />
            )}

            {hasLevels && (
              <Line
                className="pc-s-ref"
                // Точка при наведении — с тем же классом, что линия: иначе у
                // выключенной опорной она всё равно появлялась под курсором.
                activeDot={{ r: 3, className: 'pc-s-ref' }}
                yAxisId="price"
                type="stepAfter"
                dataKey="reference"
                stroke={colors.refLine}
                strokeWidth={2.25}
                dot={false}
                connectNulls={false}
                name="Опорная"
                isAnimationActive={false}
              />
            )}
            {hasLevels && (
              <Line
                className="pc-s-fair"
                activeDot={{ r: 3, className: 'pc-s-fair' }}
                yAxisId="price"
                type="stepAfter"
                dataKey="fair"
                stroke={colors.line3}
                strokeWidth={1.2}
                strokeDasharray="5 4"
                strokeOpacity={0.8}
                dot={false}
                connectNulls={false}
                name="Справедливая"
                isAnimationActive={false}
              />
            )}

            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke={colors.line1}
              strokeWidth={1.75}
              dot={false}
              activeDot={{ r: 3, stroke: colors.dotStroke, strokeWidth: 1 }}
              name="Цена"
              isAnimationActive={false}
            />

            {/* Последние значения подписаны у правого края: глаз ищет «где
                сейчас», а искать его по сетке — лишняя работа. */}
            <ReferenceDot
              yAxisId="price"
              x={view.last.date}
              y={view.last.price}
              r={4}
              fill={colors.line1}
              stroke={colors.dotStroke}
              strokeWidth={2}
              label={isPhone ? undefined : { value: fmt(view.last.price), position: priceOnTop ? 'top' : 'bottom', fill: colors.textPrimary, fontSize: 11, fontWeight: 600 }}
            />
            {!isPhone && hasLevels && lastReference !== null && (
              <ReferenceDot
                className="pc-s-ref"
                yAxisId="price"
                x={view.last.date}
                y={lastReference}
                r={0}
                label={{ value: fmt(lastReference), position: priceOnTop ? 'bottom' : 'top', fill: colors.refLine, fontSize: 11, fontWeight: 600, className: 'pc-s-ref' }}
              />
            )}


            {/* Засечки событий — у нижнего края поля, без вертикальных
                линий: на десяти годах их полсотни, и линии превратили бы
                график в частокол. Подробности — в подсказке у метки. */}
            {marks.map((m) => (
              <ReferenceLine
                key={`${m.date}-${m.kinds.join('')}`}
                yAxisId="price"
                x={m.date}
                stroke="none"
                ifOverflow="visible"
                label={<EventMark mark={m} colors={colors} />}
              />
            ))}

            <Tooltip
              // Строка наложения дописывается к подсказке из слоя: сам
              // основной график про наложение ничего не знает.
              {...(isPhone ? {
                content: (props: TooltipContentProps) => (
                  <PhoneTip
                    {...props}
                    payload={visibleRows(withLayerRow(props.payload, props.label, layerRef.current, colors))}
                    colors={colors}
                    format={(v, name) => (name === 'Цена' || name === 'Опорная' || name === 'Справедливая'
                      ? (pct ? pctText(v) : `${edgeLabel(v)} ₽`)
                      : name === layerRef.current?.label
                        ? layerRef.current.format(v)
                        : ru(v, 2))}
                  />
                ),
                position: { y: 0 },
              } : {
                content: (props: TooltipContentProps) => (
                  <DefaultTooltipContent
                    {...props}
                    payload={visibleRows(withLayerRow(props.payload, props.label, layerRef.current, colors))}
                  />
                ),
              })}
              contentStyle={{
                background: colors.tooltipBg,
                border: `1px solid ${colors.tooltipBorder}`,
                borderRadius: 8,
                fontSize: 12,
                color: colors.textPrimary,
              }}
              formatter={(value, name, item) => {
                const label = String(name ?? '');
                const num = typeof value === 'number' ? value : null;
                if (num === null) return ['—', label];
                if (label === 'Цена') {
                  if (!pct) return [`${rub(num)} ₽`, label];
                  const abs = (item?.payload as { price_abs?: number } | undefined)?.price_abs;
                  return [`${pctText(num)}${abs !== undefined ? ` (${rub(abs)} ₽)` : ''}`, label];
                }
                if (pct && (label === 'Справедливая' || label === 'Опорная')) return [pctText(num), label];
                if (label === 'Справедливая' || label === 'Опорная') {
                  const payload = item?.payload as
                    { basis_label?: string; basis_rate?: number; basis_rate_source?: string } | undefined;
                  // Основа и ставка в подсказке обязательны: внутри одной
                  // ступени оценка меняется из месяца в месяц, а ступень LTM
                  // сменяет годовую посреди года, и без подписи движение
                  // линии выглядело бы беспричинным.
                  const rate = payload?.basis_rate
                    ? `безрисковая ${ru(payload.basis_rate, 2)}% (${payload.basis_rate_source})`
                    : null;
                  const why = [payload?.basis_label, rate].filter(Boolean).join(', ');
                  return [`${rub(num)} ₽${why ? ` (${why})` : ''}`, label];
                }
                if ((item as { dataKey?: unknown } | undefined)?.dataKey === LAYER_KEY && layerRef.current) {
                  return [layerRef.current.format(num, item?.payload as PricePoint | undefined), label];
                }
                // Год отчёта едет вместе с множителем: без него ступенька на
                // кривой читается как сбой данных, а не как выход отчётности.
                const year = (item?.payload as PricePoint | undefined)?.basis_year;
                return [`${ru(num, 2)}${year ? ` (по отчёту ${year})` : ''}`, label];
              }}
              // Дни, ушедшие за шкалу, из ряда убраны — иначе линия улетает за
              // поле. Но величина за них известна и в подсказке показывается:
              // спрятать её значило бы сделать вид, что в эти дни множителя не
              // было, тогда как он был, и рекордный.
              labelFormatter={(value, payload) => {
                const point = payload?.[0]?.payload as PricePoint | undefined;
                const gap = point && layerRef.current?.gapOf?.(point);
                return gap ? `${String(value)} · ${layerRef.current?.label}: ${gap}` : String(value);
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
  );
});

export default function PriceChart({ companyId, oil = false, commodities = [] }: {
  companyId: number;
  oil?: boolean;
  /** Сырьё компании для наложения (utils/commodities): газ, золото, удобрения… */
  commodities?: CommodityKey[];
}) {
  const colors = useChartColors();
  const isPhone = useMediaQuery(PHONE_QUERY);
  const [range, setRange] = useState('5y');
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  // Нефть и сырьё: в долларах или рублях; Urals — Brent минус дисконт.
  const [oilRub, setOilRub] = useState(false);
  // Сравнение цены акции и сырья в процентах от начала окна.
  const [pct, setPct] = useState(false);
  const [urals, setUrals] = useState(false);
  const [discount, setDiscount] = useState<number>(readDiscount);
  const [shown, setShown] = useState<Set<ValueKey>>(new Set<ValueKey>(['reference']));
  const [showEvents, setShowEvents] = useState(true);
  // Протяжка держится в хранилище, а не в состоянии компонента: обновление
  // сверху заставляет recharts пересчитать все серии, и на пяти линиях по
  // тысяче точек это около 400 мс на движение мыши. Подписаны на хранилище
  // только подсветка и строка свода — они и перерисовываются.
  const spanStore = useRef(createSpanStore()).current;
  const drag = useRef<{ pressed: boolean; fromX: number; fromDate: string } | null>(null);
  // Вертикальные границы поля — чтобы подсветка не залезала на подписи оси.
  const [band, setBand] = useState({ top: 8, bottom: 24 });

  // Высота поля берётся из отрисованной сетки, а не из констант отступов:
  // recharts считает место под подписи оси сам, и угадывать его значило бы
  // промахиваться каждый раз, когда подпись станет длиннее.
  const canvas = useRef<HTMLDivElement | null>(null);
  const canvasLeft = useRef(0);
  const measureBand = useCallback(() => {
    const box = canvas.current;
    const area = box && plotArea(box);
    if (!box || !area) return;
    canvasLeft.current = box.getBoundingClientRect().left;
    const next = {
      top: Math.max(0, Math.round(area.top)),
      bottom: Math.max(0, Math.round(box.getBoundingClientRect().height - area.top - area.height)),
    };
    // Сравнение обязательно: без него каждое нажатие клало новый объект в
    // состояние и перерисовывало весь график — ровно то, от чего уходим.
    setBand((prev) => (prev.top === next.top && prev.bottom === next.bottom ? prev : next));
  }, []);

  // Оценка тянется отдельным запросом и графику не обязательна: без неё он
  // рисуется как прежде, только без линий уровня.
  const { data: valuation } = useQuery<ValuationSummaryOut>({
    queryKey: ['valuation-summary', companyId],
    queryFn: () => fetchValuationSummary(companyId),
    staleTime: 10 * 60 * 1000,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const { data: history } = useQuery<ValuationHistoryOut>({
    queryKey: ['valuation-history', companyId],
    queryFn: () => fetchValuationHistory(companyId),
    staleTime: 30 * 60 * 1000,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const { data: oilData } = useQuery<OilOut>({
    queryKey: ['market-oil'],
    queryFn: fetchOil,
    staleTime: 60 * 60 * 1000,
    enabled: oil && overlay === 'oil',
  });

  // Сырьё — помесячно. Ряды короткие (≈160 точек), и их подтягиваем
  // заранее, через пару секунд после графика: тогда первое нажатие на
  // «Золото» сразу рисует линию, а не ждёт ответа сервера.
  const queryClient = useQueryClient();
  const commodityList = commodities.join(',');
  useEffect(() => {
    if (!commodityList) return undefined;
    const timer = window.setTimeout(() => {
      commodityList.split(',').forEach((key) => {
        queryClient.prefetchQuery({
          queryKey: ['market-commodity', key],
          queryFn: () => fetchCommodity(key),
          staleTime: 6 * 60 * 60 * 1000,
        });
      });
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [commodityList, queryClient]);
  const commodityKey = isCommodity(overlay) ? overlay : null;
  const { data: commodityData } = useQuery<CommodityOut>({
    queryKey: ['market-commodity', commodityKey],
    queryFn: () => fetchCommodity(commodityKey as CommodityKey),
    staleTime: 6 * 60 * 60 * 1000,
    enabled: commodityKey !== null,
  });

  const { data, isLoading, error } = useQuery<PriceHistoryOut>({
    queryKey: ['price-history', companyId],
    queryFn: () => fetchPriceHistory(companyId),
    staleTime: LIVE_PRICE_STALE_MS,
    refetchInterval: LIVE_PRICE_REFRESH_MS,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const view = useMemo(() => buildView(data, history, range, isPhone), [data, history, range, isPhone]);
  // Наложение — отдельно от основного графика: его включение пересчитывает
  // только слой (см. OverlayLayer и MainChart).
  const layer = useMemo(() => (view && overlay
    ? buildLayer(view.points, overlay, {
      oilPoints: oilData?.points,
      commodity: commodityData,
      rub: oilRub,
      discount: overlay === 'oil' && urals ? discount : 0,
    })
    : null), [view, overlay, oilData, commodityData, oilRub, urals, discount]);
  // «В %» имеет смысл только для цены сырья: множитель в процентах от
  // начала окна ничего не говорит.
  const pctOn = pct && (overlay === 'oil' || isCommodity(overlay)) && layer !== null;
  const shownLayer = useMemo(() => (pctOn && layer ? toPctLayer(layer) : layer), [pctOn, layer]);
  const shownView = useMemo(() => (pctOn && view ? toPctView(view) : view), [pctOn, view]);
  const domainKeys = ['price', ...(shown.has('reference') ? ['reference'] : []), ...(shown.has('fair') ? ['fair'] : [])].join(',');
  const domain = useMemo(
    () => (pctOn && shownView && shownLayer ? sharedDomain(shownView, shownLayer, domainKeys.split(',')) : undefined),
    [pctOn, shownView, shownLayer, domainKeys],
  );
  const layerRef = useRef<LayerInfo | null>(null);
  const hiddenRef = useRef<Set<string>>(new Set());

  // Замер делается заранее, а не при первом нажатии: он меняет состояние, а
  // значит перерисовывает график — 173 мс, и приходились они ровно на начало
  // первой протяжки. Кадр ожидания нужен потому, что ResponsiveContainer
  // измеряет себя сам и сетки в момент монтирования ещё нет.
  useEffect(() => {
    const frame = requestAnimationFrame(measureBand);
    return () => cancelAnimationFrame(frame);
  }, [measureBand, view]);

  // Телефон: отрезок — двумя пальцами (см. хук).
  useTwoFingerSpan(canvas, view?.points, spanStore, isPhone, measureBand);
  useSpanMark(canvas, spanStore, view);


  if (isLoading) return <div className="pc-state">Загружаем историю цены…</div>;
  if (error) return <div className="pc-state pc-state--error">Не удалось загрузить историю цены</div>;
  if (!view) {
    return (
      <div className="pc-state">
        Истории цены нет. Она докачивается из Мосбиржи сама — при старте сервера
        и ежедневно в 19:00 МСК, от даты первого отчёта компании.
      </div>
    );
  }

  const overlaySpec = OVERLAYS.find((o) => o.key === overlay);
  const overlayLabel = overlay === 'oil'
    ? `${urals ? `Urals ≈ Brent − ${ru(discount, 0)} $` : 'Brent'}, ${oilRub ? '₽' : '$'}/барр.`
    : commodityKey
      ? commodityData
        ? `${commodityData.label}, ${oilRub && !commodityData.index ? commodityData.unit.replace('$', '₽') : commodityData.unit}`
        : COMMODITY_BUTTON[commodityKey]
      : overlaySpec?.label;
  // Значение сырья в подсказке: индекс — числом, цена — с валютой.
  const priceText = (v: number) => (commodityData?.index && commodityKey
    ? ru(v, 1)
    : oilRub ? `${ru(v, 0)} ₽` : `${ru(v, v < 100 ? 2 : 0)} $`);
  // Что подсказке основного графика знать о наложении. Ссылка, а не
  // свойство: основной график при смене наложения не перерисовывается, а
  // подсказка читает ref в момент показа.
  const mult = overlay === 'pe' || overlay === 'pb' ? overlay : null;
  layerRef.current = overlay && layer && shownLayer ? {
    label: overlayLabel ?? '',
    values: shownLayer.values,
    format: mult
      ? (v, point) => {
        const off = layer.bounds && v > layer.bounds[1] ? ' — за шкалой' : '';
        // Год отчёта едет вместе с множителем: без него ступенька на кривой
        // читается как сбой данных, а не как выход отчётности.
        return `${ru(v, 2)}${point?.basis_year ? ` (по отчёту ${point.basis_year})` : ''}${off}`;
      }
      : pctOn ? pctText : priceText,
    gapOf: mult ? (p) => (p[mult] === null ? (mult === 'pe' ? p.pe_gap : p.pb_gap) ?? null : null) : undefined,
  } : null;
  // Уровни, которые есть чем нарисовать. Сегодняшняя величина берётся из
  // свода — её видно в подсказке кнопки, — а линия рисуется рядом по годам.
  const levels = (history?.segments ?? []).some((x) => !x.refused)
    ? VALUES.map((spec) => ({
      ...spec,
      value: spec.key === 'fair'
        ? valuation?.windows?.find((w) => w.window === valuation.window)?.value ?? null
        : valuation?.safety?.reference ?? null,
    }))
    : [];


  const hasLevels = levels.length > 0;
  const marks = showEvents ? eventMarks(data?.events ?? [], view.points) : [];
  // Дробление и консолидация — разные события, и в легенде их не путаем.
  const splitKinds = new Set((data?.events ?? []).filter((e) => e.kind === 'split')
    .map((e) => (e.label.startsWith('Консолидация') ? 'консолидация' : 'дробление')));
  const splitWord = Array.from(splitKinds).sort((x, y) => (x === 'дробление' ? -1 : y === 'дробление' ? 1 : 0)).join(' / ') || 'дробление';
  // Опорная — главная линия графика, ради неё он и стоит на первом экране;
  // она включена сразу, но её можно убрать, как и остальные уровни.
  const extras = levels;
  hiddenRef.current = new Set([
    ...(shown.has('reference') ? [] : ['Опорная']),
    ...(shown.has('fair') ? [] : ['Справедливая']),
  ]);
  const toggleValue = (key: ValueKey) => setShown((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  return (
    <section className="pc">
      <header className="pc-head">
        <div className="pc-title">
          <h3>{hasLevels ? 'Цена и опорная стоимость' : 'Цена акции'}</h3>
          <div className="pc-keys">
            <span className="pc-key"><i className="pc-key-line" style={{ background: colors.line1 }} />Цена</span>
            {/* Легенда над графиком не меняется от кнопок под ним: строка,
                выросшая на «P/E — правая шкала», переносилась и сдвигала
                график вниз. Выключенная опорная — бледнее, а не исчезает;
                что включено из остального — видно по цвету кнопок. */}
            {hasLevels && (
              <span className={`pc-key-group${shown.has('reference') ? '' : ' is-off'}`}>
                <span className="pc-key"><i className="pc-key-line" style={{ background: colors.refLine }} />Опорная</span>
                <span className="pc-key" title="Запас прочности от 15%: мелкий запас на истории окном входа не был">
                  <i className="pc-key-zone" style={{ background: colors.zoneBelow }} />Цена ниже опорной на 15%+
                </span>
              </span>
            )}
            {showEvents && marks.length > 0 && (
              <span className="pc-key pc-key--events" title="Наведите на метку у нижнего края графика">
                <i className="pc-key-mark" style={{ background: colors.axis }} />отчёт
                <i className="pc-key-mark pc-key-mark--round" style={{ background: colors.line3 }} />дивиденд
                {marks.some((m) => m.kinds.includes('split')) && (
                  <><i className="pc-key-mark pc-key-mark--diamond" style={{ background: colors.line2 }} />{splitWord}</>
                )}
              </span>
            )}
          </div>
        </div>

        <div className="pc-ranges" role="group" aria-label="Период">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={`pc-btn${range === r.key ? ' is-on' : ''}`}
              // Выделение снимается вместе с окном: отрезок, сделанный на
              // пяти годах, при переходе на год обрезался бы по краю и
              // молча показывал не тот период, который выбирали.
              onClick={() => { setRange(r.key); spanStore.set(null); }}
              aria-pressed={range === r.key}
              title={r.key === range ? `${view.first.date} — ${view.last.date}` : undefined}
            >
              {r.label}
            </button>
          ))}
        </div>
      </header>


      <div
        className={[
          'pc-canvas',
          shown.has('reference') ? '' : 'hide-reference',
          shown.has('fair') ? '' : 'hide-fair',
          showEvents ? '' : 'hide-events',
        ].filter(Boolean).join(' ')}
        ref={canvas}
      >
        <SpanBand store={spanStore} top={band.top} bottom={band.bottom} />
        {/* Наложение — под основным графиком, своим слоем: включение P/E или
            цены сырья не трогает основной график (см. OverlayLayer). */}
        {overlay && shownLayer && shownView && (
          <OverlayLayer
            points={shownLayer.points}
            bounds={domain ?? shownLayer.bounds}
            shared={pctOn}
            colors={colors}
            isPhone={isPhone}
            leftWidth={view.pennyScale ? 74 : 58}
            rightWidth={phoneAxisWidth(shownView, pctOn ? pctText : edgeLabel)}
            format={shownLayer.axisFormat}
          />
        )}
        <MainChart
          view={shownView ?? view}
          pct={pctOn}
          domain={domain}
          colors={colors}
          isPhone={isPhone}
          hasLevels={hasLevels}
          events={data?.events}
          hiddenRef={hiddenRef}
          spanStore={spanStore}
          measureBand={measureBand}
          drag={drag}
          canvasLeft={canvasLeft}
          layerRef={layerRef}
        />
      </div>

      {/* Свод по отрезку. Не заменяет статистику периода: смысл выделения в
          том и есть, чтобы сравнить кусок с целым — «за год +12%, но от
          мартовского пика до июньского дна −31%».

          Стоит под графиком, а не над ним: появляясь сверху, полоса сдвигала
          поле вниз прямо во время протяжки, и график уезжал из-под курсора. */}
      <SpanSummary store={spanStore} points={view.points} />

      {view.traps.length > 0 && (
        <p
          className="pc-legend"
          title="На истории «ниже опорной» в такие периоды давало за два года +13%, в остальные — +48%"
        >
          <span className="pc-legend-swatch" aria-hidden />
          Серым — P/B ниже {TRAP_PRICE_TO_BOOK.toLocaleString('ru-RU')}: в такие периоды
          дешевизна чаще оказывалась ловушкой, чем скидкой.
        </p>
      )}

      <div className="pc-foot">
        {/* Под графиком — только то, без чего его не прочитать: почему цена
            прыгает на дроблении. */}
        {data?.split_note ? <p className="pc-disclaimer">{data.split_note}</p> : <span />}
        <div className="pc-more" role="group" aria-label="Ещё на графике">
          <span className="pc-more-label">Ещё на графике:</span>
          {extras.map((v) => (
            <button
              key={v.key}
              type="button"
              className={`pc-btn pc-btn--small${shown.has(v.key) ? ' is-on' : ''}`}
              onClick={() => toggleValue(v.key)}
              title={v.value !== null ? `${v.hint}. Сегодня — ${rub(v.value)} ₽` : v.hint}
              aria-pressed={shown.has(v.key)}
            >
              {shown.has(v.key) && (
                <i className={`pc-btn-swatch${v.key === 'fair' ? ' pc-btn-swatch--dash' : ''}`}
                  style={v.key === 'fair' ? { borderColor: colors.line3 } : { background: colors.refLine }} />
              )}
              {v.label}
            </button>
          ))}
          <button
            type="button"
            className={`pc-btn pc-btn--small${showEvents ? ' is-on' : ''}`}
            onClick={() => setShowEvents((v) => !v)}
            aria-pressed={showEvents}
            title="Выход отчётов, дивидендные отсечки, дробления акций"
          >
            События
          </button>
          {OVERLAYS.map((o) => (
            <button
              key={o.key}
              type="button"
              className={`pc-btn pc-btn--small${overlay === o.key ? ' is-on' : ''}`}
              onClick={() => setOverlay(overlay === o.key ? null : o.key)}
              title={o.hint}
              aria-pressed={overlay === o.key}
            >
              {overlay === o.key && <i className="pc-btn-swatch" style={{ background: colors.line4 }} />}
              {o.label}
            </button>
          ))}
          {oil && (
            <button
              type="button"
              className={`pc-btn pc-btn--small${overlay === 'oil' ? ' is-on' : ''}`}
              onClick={() => setOverlay(overlay === 'oil' ? null : 'oil')}
              title="Цена нефти Brent на правой шкале — в долларах или рублях"
              aria-pressed={overlay === 'oil'}
            >
              {overlay === 'oil' && <i className="pc-btn-swatch" style={{ background: colors.line4 }} />}
              Нефть
            </button>
          )}
          {commodities.map((key) => (
            <button
              key={key}
              type="button"
              className={`pc-btn pc-btn--small${overlay === key ? ' is-on' : ''}`}
              onClick={() => setOverlay(overlay === key ? null : key)}
              aria-pressed={overlay === key}
            >
              {overlay === key && <i className="pc-btn-swatch" style={{ background: colors.line4 }} />}
              {COMMODITY_BUTTON[key]}
            </button>
          ))}
        </div>
      </div>

      {/* Что за линия наложения и её настройки — под графиком: появляясь
          над ним, строка сдвигала бы поле. */}
      {overlay && (
        <div className="pc-oil" role="group" aria-label="Наложение на графике">
          <span className="pc-key pc-layer-key">
            <i className="pc-key-line" style={{ background: colors.line4 }} />
            {overlayLabel}{pctOn ? ' и цена акции — в % от начала окна' : ' — шкала слева внутри поля'}
          </span>
          {/* Переключатель «в %» — здесь, в строке наложения: он нужен только
              при включённом сырье, и над графиком места ему не отнимаем. */}
          {(overlay === 'oil' || isCommodity(overlay)) && (
            <button
              type="button"
              className={`pc-btn pc-btn--small${pct ? ' is-on' : ''}`}
              aria-pressed={pct}
              onClick={() => setPct((v) => !v)}
              title="Цена акции и сырья — изменение в процентах от первого дня окна, на одной шкале"
            >
              Сравнить в %
            </button>
          )}
          {(overlay === 'oil' || (commodityData && !commodityData.index)) && (
          <span className="pc-oil-seg">
            <button type="button" className={`pc-btn pc-btn--small${!oilRub ? ' is-on' : ''}`} onClick={() => setOilRub(false)}>в долларах</button>
            <button type="button" className={`pc-btn pc-btn--small${oilRub ? ' is-on' : ''}`} onClick={() => setOilRub(true)}>в рублях</button>
          </span>
          )}
          {overlay === 'oil' && (
          <label className="pc-oil-urals">
            <input type="checkbox" checked={urals} onChange={(e) => setUrals(e.target.checked)} />
            Urals: дисконт к Brent
            <input
              type="number"
              min={0}
              max={60}
              step={1}
              value={discount}
              disabled={!urals}
              onChange={(e) => {
                const v = Math.max(0, Math.min(60, Number(e.target.value) || 0));
                setDiscount(v);
                try { window.localStorage.setItem(URALS_KEY, String(v)); } catch { /* браузер без хранилища */ }
              }}
              aria-label="Дисконт Urals к Brent, долларов за баррель"
            />
            $
          </label>
          )}
        </div>
      )}

      {overlay === 'oil' && !isPhone && (
        <p className="pc-note">
          Brent — дневная цена (FRED), в рублях — по курсу ЦБ на тот же день. Urals — Brent минус
          дисконт, который вы задали: официальной дневной цены Urals в открытом доступе нет, а дисконт
          сильно менялся (в 2022–2023 годах доходил до 30 $).
        </p>
      )}
      {commodityKey && commodityData && !isPhone && (
        <p className="pc-note">
          {commodityData.daily?.length
            ? <>Дневные закрытия: {commodityData.daily_source}, с {humanDate(commodityData.daily[0][0])}
              {commodityData.points.length > 0 && commodityData.daily[0][0].slice(0, 7) > commodityData.points[0][0].slice(0, 7)
                ? '; раньше — месячные средние Всемирного банка.' : '.'}</>
            : <>{commodityData.source} — дневного биржевого ряда в открытом доступе нет.</>}
          {' '}В рублях — по курсу ЦБ.
        </p>
      )}
      {mult && layer && !isPhone && (
        <p className="pc-note">
          {overlaySpec?.hint}. Шкала ограничена тройной медианой: провал прибыли
          поднимает множитель до сотен, и без ограничения весь остальной ряд сжался бы
          в полоску у нуля.
          {layer.gaps.length > 0 && <> Пропуски: {layer.gaps.join('; ')}.</>}
          {layer.offScale > 0 && (
            <> За шкалу ушло {layer.offScale} {layer.offScale % 10 === 1 && layer.offScale % 100 !== 11
              ? 'значение' : 'значений'}: эти дни не нарисованы, и линия проходит
              через них напрямую. Сама величина остаётся в подсказке.</>
          )}
        </p>
      )}
    </section>
  );
}
