import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Bar, CartesianGrid, Cell, ComposedChart, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  fetchMacro, fetchMacroCompanies, fetchMarketOverview,
  type MacroCompany, type MacroOut, type MarketOverview, type SeriesPoint,
} from '../services/market.api';
import { useChartColors } from '../contexts/ThemeContext';
import { PHONE_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import { formatPerShare } from '../utils/perShare';
import { SpanBand, humanDate } from '../components/PriceSpanLayer';
import { createSpanStore, type SpanStore } from '../components/priceSpanStore';
import { plotArea, useSpanMark } from '../hooks/useTwoFingerSpan';
import '../components/PriceChart.css';
import './MarketOverview.css';
import './EconomyPage.css';

/**
 * Раздел «Экономика»: в каком состоянии государство — бюджет, долг, резервы,
 * цены и настроения людей. Без прогнозов: только опубликованные ряды Минфина,
 * ЦБ и Всемирного банка, у каждого графика — источник.
 *
 * Сверху — снимок на дату. Выбранный день отмечен чертой на всех графиках, а
 * ниже сводки видно, что тогда было с рынком и какие компании стоили дешевле
 * всего относительно своей тогдашней опорной стоимости. Это и есть цепочка
 * «экономика → рынок → компания»: в сентябре 2022-го всё выглядело плохо — и
 * именно тогда цены были ниже всего.
 */

// ─── Форматы ───────────────────────────────────────────────────────────────

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace('-', '−');
const signed = (value: number, digits = 1) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${ru(Math.abs(value), digits)}`;
const dotDate = (iso: string) => iso.split('-').reverse().join('.');
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTHS_FULL = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
const monthName = (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;
const quarterName = (iso: string) => `${['I', 'II', 'III', 'IV'][Math.floor((Number(iso.slice(5, 7)) - 1) / 3)]} кв. ${iso.slice(0, 4)}`;
/** Миллиарды рублей → «7,3 трлн». */
const trln = (bln: number, digits = 1) => `${ru(bln / 1000, digits)} трлн`;

const toT = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)) || 1);
const fromT = (t: number) => new Date(t).toISOString().slice(0, 10);
const todayIso = () => new Date().toISOString().slice(0, 10);

/** Последняя точка ряда не позже даты. */
function at(series: SeriesPoint[] | undefined, iso: string): SeriesPoint | null {
  if (!series?.length) return null;
  let lo = 0;
  let hi = series.length - 1;
  if (series[0][0] > iso) return null;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (series[mid][0] <= iso) lo = mid; else hi = mid - 1;
  }
  return series[lo];
}

/** Последний период, закончившийся к дате: месяц, квартал или год, датированный
 * своим первым числом, закрыт, когда наступил следующий за ним день. */
function closed(series: SeriesPoint[] | undefined, iso: string, months: number): SeriesPoint | null {
  const d = new Date(toT(iso));
  d.setUTCDate(d.getUTCDate() + 1);
  d.setUTCMonth(d.getUTCMonth() - months);
  return at(series, d.toISOString().slice(0, 10));
}

const RANGES = [
  { key: '5y', label: '5 лет', years: 5 },
  { key: '10y', label: '10 лет', years: 10 },
  { key: 'all', label: 'Всё', years: null },
] as const;
type RangeKey = typeof RANGES[number]['key'];

/** Даты снимка: дни, когда рынок был у дна, и сегодня. */
const PRESETS: { on: string; label: string; what: string }[] = [
  { on: '2014-12-16', label: 'дек 2014', what: 'обвал рубля, ставка 17%' },
  { on: '2020-03-18', label: 'мар 2020', what: 'пандемия, дно рынка' },
  { on: '2022-02-24', label: '24 фев 2022', what: 'начало СВО' },
  { on: '2022-10-10', label: 'окт 2022', what: 'мобилизация, дно рынка' },
  { on: '2024-12-17', label: 'дек 2024', what: 'ставка 21%' },
];

// ─── Графики ───────────────────────────────────────────────────────────────

const PHONE_AXIS = { mirror: true, axisLine: false, tickLine: false } as const;
const PHONE_TIP = { position: { y: 0 } } as const;

type LineSpec = {
  key: string;
  label: string;
  color: string;
  data: SeriesPoint[];
  /** Ступенька (ключевая ставка) или ряд другой частоты: значение берётся
   * последнее известное на дату сетки, а сетку не задаёт. */
  sample?: boolean;
  step?: boolean;
  dash?: string;
  axis?: 'l' | 'r';
  width?: number;
};

type Fmt = (v: number) => string;

function yearTicks(fromT_: number, toT_: number, every: number): number[] {
  const out: number[] = [];
  const first = new Date(fromT_).getUTCFullYear() + 1;
  const last = new Date(toT_).getUTCFullYear();
  for (let y = first; y <= last; y += 1) {
    if ((last - y) % every === 0) out.push(Date.UTC(y, 0, 1));
  }
  return out;
}

/** Круглые деления шкалы: шаг 1, 2, 2,5 или 5 на степень десяти. */
function niceAxis(values: number[], withZero: boolean): { domain: [number, number]; ticks: number[] } | null {
  const xs = values.filter((v) => Number.isFinite(v));
  if (!xs.length) return null;
  let min = Math.min(...xs);
  let max = Math.max(...xs);
  if (withZero) { min = Math.min(0, min); max = Math.max(0, max); }
  if (min === max) max = min + 1;
  const raw = (max - min) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.round(t / step) * step);
  return { domain: [lo, hi], ticks };
}

function tooltipStyle(colors: ReturnType<typeof useChartColors>) {
  return {
    contentStyle: { background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 },
    labelStyle: { color: colors.textPrimary, marginBottom: 2 },
    itemStyle: { color: colors.textPrimary, padding: 0 },
  };
}

function Legend({ items }: { items: { label: React.ReactNode; color: string; dash?: boolean }[] }) {
  return (
    <div className="mo-legend">
      {items.map((it, i) => (
        <span key={i}>
          <i style={it.dash
            ? { background: `repeating-linear-gradient(90deg, ${it.color} 0 4px, transparent 4px 7px)` }
            : { background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

type Row = Record<string, number | string> & { date: string; t: number };

/** Как показывать изменение за отрезок: в процентах, в пунктах (ставки,
 * доли) или разностью (ряды, проходящие через ноль, — дефицит). */
type DeltaKind = 'pct' | 'pp' | 'abs';

/**
 * Свод по выделенному отрезку: у каждой линии — значение на краях и разница.
 * Подписан на хранилище отрезка, как на графиках «Рынка» и компании: движение
 * мыши перерисовывает только эту строку, не график.
 */
function TimeSpanSummary({ store, rows, lines, fmt, fmtR, delta, monthly }: {
  store: SpanStore;
  rows: Row[];
  lines: LineSpec[];
  fmt: Fmt;
  fmtR?: Fmt;
  delta: DeltaKind;
  monthly: boolean;
}) {
  const live = useSyncExternalStore(store.subscribe, store.get, store.get);
  if (!live || live.fromDate === live.toDate) return null;
  const [a, b] = live.fromDate < live.toDate ? [live.fromDate, live.toDate] : [live.toDate, live.fromDate];
  const when = (iso: string) => (monthly ? monthName(iso) : humanDate(iso));
  const parts = lines.flatMap((l) => {
    const first = rows.find((r) => r.date >= a && typeof r[l.key] === 'number');
    const last = [...rows].reverse().find((r) => r.date <= b && typeof r[l.key] === 'number');
    if (!first || !last || first.date >= last.date) return [];
    const x = first[l.key] as number;
    const y = last[l.key] as number;
    const f = l.axis === 'r' && fmtR ? fmtR : fmt;
    const change = delta === 'pct' && x > 0
      ? `${signed((y / x - 1) * 100, 1)}%`
      : delta === 'pp' ? `${signed(y - x, 1)} п.п.` : `${y - x >= 0 ? '+' : '−'}${f(Math.abs(y - x))}`;
    return [(
      <span key={l.key}>
        {l.label} <b>{f(x)}</b> → <b>{f(y)}</b>{' '}
        <b className={y >= x ? 'mo-up' : 'mo-down'}>{change}</b>
      </span>
    )];
  });
  if (!parts.length) return null;
  return (
    <div className="mo-span">
      <span className="mo-span-dates">{when(a)} → {when(b)}</span>
      {parts}
    </div>
  );
}

/**
 * Линии по времени. Сетку задают ряды без `sample`; остальные (ступенчатая
 * ставка, недельный курс) берутся последним известным значением на дату
 * сетки — так подсказка показывает все линии сразу, а не одну.
 *
 * Отрезок выделяется протяжкой мыши, на телефоне — двумя пальцами, как на
 * графиках «Рынка» и компании. Ось — время, поэтому дата под курсором
 * считается по положению, а не по номеру точки: точки рядов разной частоты
 * стоят неравномерно.
 */
function TimeChart({ lines: rawLines, from, till, snap, fmt: rawFmt, fmtR: rawFmtR, height = 240, zero, monthly = true, legend = true, delta: rawDelta = 'pct', rebase = false }: {
  lines: LineSpec[];
  from: string | null;
  /** Правый край: дата снимка, если смотрим «как было тогда». */
  till: string | null;
  snap: string | null;
  fmt: Fmt;
  fmtR?: Fmt;
  height?: number;
  zero?: boolean;
  /** Подпись даты в подсказке — месяцем, а не днём. */
  monthly?: boolean;
  legend?: boolean;
  delta?: DeltaKind;
  /** Каждый ряд — в процентах от своего значения в начале периода: так
   * доллар, евро и юань, нефть в долларах и в рублях сравниваются на одной
   * шкале, хотя в абсолюте различаются в разы. */
  rebase?: boolean;
}) {
  const colors = useChartColors();
  // При пересчёте в проценты все ряды ложатся на одну шкалу — правая не нужна.
  const lines = useMemo(() => (rebase ? rawLines.map((l) => ({ ...l, axis: 'l' as const })) : rawLines), [rawLines, rebase]);
  const fmt = rebase ? ((v: number) => `${signed(v, 0)}%`) : rawFmt;
  const fmtR = rebase ? undefined : rawFmtR;
  const delta: DeltaKind = rebase ? 'pp' : rawDelta;
  const isPhone = useMediaQuery(PHONE_QUERY);
  const rows = useMemo(() => {
    const grid = new Map<string, Row>();
    lines.filter((l) => !l.sample).forEach((l) => {
      l.data.forEach(([d, v]) => {
        if ((from && d < from) || (till && d > till)) return;
        const row = grid.get(d) ?? { date: d, t: toT(d) } as Row;
        row[l.key] = v;
        grid.set(d, row);
      });
    });
    const out = Array.from(grid.values()).sort((a, b) => a.t - b.t);
    lines.filter((l) => l.sample).forEach((l) => {
      out.forEach((row) => {
        const p = at(l.data, row.date);
        if (p) row[l.key] = p[1];
      });
    });
    if (rebase) {
      lines.forEach((l) => {
        const first = out.find((row) => typeof row[l.key] === 'number');
        const base = first ? (first[l.key] as number) : null;
        if (!base) return;
        out.forEach((row) => {
          if (typeof row[l.key] === 'number') row[l.key] = ((row[l.key] as number) / base - 1) * 100;
        });
      });
    }
    return out;
  }, [lines, from, till, rebase]);

  const store = useRef(createSpanStore()).current;
  const canvas = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ fromX: number; fromDate: string } | null>(null);
  const [band, setBand] = useState({ top: 8, bottom: 24 });
  const t0 = rows.length ? rows[0].t : 0;
  const t1 = rows.length ? rows[rows.length - 1].t : 1;

  /** Ближайшая к пикселю точка сетки и её пиксель — от левого края обёртки. */
  const locate = useCallback((clientX: number) => {
    const box = canvas.current;
    const area = box && plotArea(box);
    if (!box || !area || area.width <= 0 || !rows.length) return null;
    const x = clientX - box.getBoundingClientRect().left;
    const t = t0 + ((x - area.left) / area.width) * (t1 - t0);
    let lo = 0;
    let hi = rows.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid].t < t) lo = mid + 1; else hi = mid;
    }
    const i = lo > 0 && Math.abs(rows[lo - 1].t - t) < Math.abs(rows[lo].t - t) ? lo - 1 : lo;
    const row = rows[i];
    return { date: row.date, x: area.left + ((row.t - t0) / (t1 - t0 || 1)) * area.width };
  }, [rows, t0, t1]);

  const measure = useCallback(() => {
    const box = canvas.current;
    const area = box && plotArea(box);
    if (!box || !area) return;
    const next = { top: Math.round(area.top), bottom: Math.round(box.clientHeight - area.top - area.height) };
    setBand((prev) => (prev.top === next.top && prev.bottom === next.bottom ? prev : next));
  }, []);

  useEffect(() => { store.set(null); }, [rows, store]);
  useSpanMark(canvas, store, rows);

  // Два пальца — свои слушатели: у React обработчики касаний пассивные, и
  // без preventDefault жест увеличивал бы страницу.
  useEffect(() => {
    const box = canvas.current;
    if (!isPhone || !box) return undefined;
    const onTwo = (e: TouchEvent) => {
      if (e.touches.length !== 2) return;
      e.preventDefault();
      const [a, b] = [e.touches[0].clientX, e.touches[1].clientX].sort((x, y) => x - y).map(locate);
      if (!a || !b || a.date === b.date) return;
      store.set({ fromX: a.x, toX: b.x, fromDate: a.date, toDate: b.date });
    };
    const onStart = (e: TouchEvent) => {
      if (e.touches.length === 1) { store.set(null); return; }
      measure();
      onTwo(e);
    };
    box.addEventListener('touchstart', onStart, { passive: false });
    box.addEventListener('touchmove', onTwo, { passive: false });
    return () => {
      box.removeEventListener('touchstart', onStart);
      box.removeEventListener('touchmove', onTwo);
    };
  }, [isPhone, locate, measure, store]);

  if (!rows.length) return <div className="mo-state">Нет данных за этот период.</div>;
  const spanYears = (t1 - t0) / (365.25 * 864e5);
  const ticks = yearTicks(t0, t1, spanYears > 14 ? (isPhone ? 4 : 2) : spanYears > 7 && isPhone ? 2 : 1);
  const hasRight = lines.some((l) => l.axis === 'r');
  const axisOf = (side: 'l' | 'r') => niceAxis(
    rows.flatMap((row) => lines.filter((l) => (l.axis ?? 'l') === side).map((l) => row[l.key] as number)),
    side === 'l' && zero !== undefined,
  );
  const left = axisOf('l');
  const right = hasRight ? axisOf('r') : null;
  const snapT = snap ? toT(snap) : null;
  const names = Object.fromEntries(lines.map((l) => [l.key, l]));
  return (
    <>
      {legend && <Legend items={lines.map((l) => ({ label: l.label, color: l.color, dash: Boolean(l.dash) }))} />}
      <div
        className="mo-canvas"
        ref={canvas}
        onMouseDown={(e) => {
          if (e.button !== 0) return;
          store.set(null);
          measure();
          const p = locate(e.clientX);
          drag.current = p ? { fromX: p.x, fromDate: p.date } : null;
        }}
        onMouseMove={(e) => {
          const held = drag.current;
          if (!held) return;
          const p = locate(e.clientX);
          if (p) store.set({ fromX: held.fromX, toX: p.x, fromDate: held.fromDate, toDate: p.date });
        }}
        onMouseUp={() => { drag.current = null; }}
        onMouseLeave={() => { drag.current = null; }}
      >
        <SpanBand store={store} top={band.top} bottom={band.bottom} />
        <ResponsiveContainer width="100%" height={isPhone ? Math.max(height, 240) : height}>
          <LineChart data={rows} margin={isPhone ? { top: 8, right: 0, bottom: 0, left: 0 } : { top: 8, right: hasRight ? 0 : 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={colors.grid} vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={[t0, t1]} ticks={ticks}
              tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
              tickFormatter={(v: number) => String(new Date(v).getUTCFullYear())} />
            <YAxis yAxisId="l" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={48}
              domain={left?.domain ?? ['auto', 'auto']} ticks={left?.ticks} interval={0} tickFormatter={fmt}
              {...(isPhone ? PHONE_AXIS : {})} />
            {hasRight && (
              <YAxis yAxisId="r" orientation="right" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={48}
                domain={right?.domain ?? ['auto', 'auto']} ticks={right?.ticks} interval={0}
                tickFormatter={fmtR ?? fmt} {...(isPhone ? PHONE_AXIS : {})} />
            )}
            {zero === false && <ReferenceLine yAxisId="l" y={0} stroke={colors.axis} />}
            {snapT !== null && snapT >= t0 && snapT <= t1 && (
              <ReferenceLine yAxisId="l" x={snapT} stroke="var(--mo-accent)" strokeWidth={1.5} strokeDasharray="4 3" />
            )}
            <Tooltip
              {...tooltipStyle(colors)}
              labelFormatter={(v) => {
                const iso = fromT(Number(v));
                return monthly ? `${MONTHS_FULL[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : dotDate(iso);
              }}
              formatter={(v, key) => {
                const spec = names[String(key)];
                return [(spec?.axis === 'r' && fmtR ? fmtR : fmt)(Number(v)), spec?.label ?? String(key)];
              }}
              {...(isPhone ? PHONE_TIP : {})}
            />
            {lines.map((l) => (
              <Line key={l.key} yAxisId={l.axis ?? 'l'} dataKey={l.key} stroke={l.color}
                strokeWidth={l.width ?? 1.5} strokeDasharray={l.dash} dot={false}
                type={l.step ? 'stepAfter' : 'linear'} connectNulls isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TimeSpanSummary store={store} rows={rows} lines={lines} fmt={fmt} fmtR={fmtR} delta={delta} monthly={monthly} />
    </>
  );
}

type BarSpec = { key: string; label: string; color: string; stack?: boolean };
type BarRow = Record<string, number | string | null> & { label: string };

/** Столбцы по годам или кварталам; линии поверх — по той же оси. */
function PeriodBars({ rows, bars, lines = [], snapLabel, fmt, height = 240, signColors }: {
  rows: BarRow[];
  bars: BarSpec[];
  lines?: { key: string; label: string; color: string; axis?: 'l' | 'r' }[];
  snapLabel: string | null;
  fmt: Fmt;
  height?: number;
  /** Один ряд столбцов, окрашенный по знаку. */
  signColors?: { pos: string; neg: string };
}) {
  const colors = useChartColors();
  const isPhone = useMediaQuery(PHONE_QUERY);
  if (!rows.length) return <div className="mo-state">Нет данных.</div>;
  const quarterly = rows.some((r) => r.label.includes('кв.'));
  const every = Math.ceil(rows.length / (quarterly ? 4 : 1) / (isPhone ? 6 : 14));
  const yearTick = (label: string) => {
    if (!quarterly) return label;
    const year = Number(label.slice(-4));
    const lastYear = Number(rows[rows.length - 1].label.slice(-4));
    return label.startsWith('I кв.') && (lastYear - year) % every === 0 ? String(year) : '';
  };
  const names = Object.fromEntries([...bars, ...lines].map((b) => [b.key, b.label]));
  return (
    <div className="mo-bleed">
      <ResponsiveContainer width="100%" height={isPhone ? Math.max(height, 240) : height}>
        <ComposedChart data={rows} margin={isPhone ? { top: 8, right: 0, bottom: 0, left: 0 } : { top: 8, right: 8, bottom: 0, left: 0 }}
          stackOffset="sign">
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="label" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
            interval={quarterly ? 0 : every - 1} tickFormatter={yearTick} tickLine={!quarterly} />
          <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={48} tickFormatter={fmt}
            {...(isPhone ? PHONE_AXIS : {})} />
          <ReferenceLine y={0} stroke={colors.axis} />
          {snapLabel && rows.some((r) => r.label === snapLabel) && (
            <ReferenceLine x={snapLabel} stroke="var(--mo-accent)" strokeWidth={1.5} strokeDasharray="4 3" />
          )}
          <Tooltip
            {...tooltipStyle(colors)}
            cursor={{ fill: colors.grid }}
            formatter={(v, key) => [v === null || v === undefined ? '—' : fmt(Number(v)), names[String(key)] ?? String(key)]}
            {...(isPhone ? PHONE_TIP : {})}
          />
          {bars.map((b) => (
            <Bar key={b.key} dataKey={b.key} fill={b.color} stackId={b.stack ? 's' : undefined}
              isAnimationActive={false} maxBarSize={28}>
              {signColors && rows.map((r) => (
                <Cell key={r.label} fill={Number(r[b.key]) >= 0 ? signColors.pos : signColors.neg} />
              ))}
            </Bar>
          ))}
          {lines.map((l) => (
            <Line key={l.key} dataKey={l.key} stroke={l.color} strokeWidth={1.6} dot={{ r: 2, fill: l.color }}
              isAnimationActive={false} connectNulls />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Расчёты ───────────────────────────────────────────────────────────────

function ratio(a: SeriesPoint[], b: SeriesPoint[], scale = 100): SeriesPoint[] {
  const byDate = new Map(b);
  return a.flatMap(([d, v]) => {
    const den = byDate.get(d);
    return den ? [[d, (v / den) * scale] as SeriesPoint] : [];
  });
}

function diff(a: SeriesPoint[], b: SeriesPoint[]): SeriesPoint[] {
  const byDate = new Map(b);
  return a.flatMap(([d, v]) => (byDate.has(d) ? [[d, v - (byDate.get(d) as number)] as SeriesPoint] : []));
}

/** Значение ряда на конец каждого года (декабрь) и последний месяц текущего. */
function yearEnds(series: SeriesPoint[]): Map<number, { value: number; month: number }> {
  const out = new Map<number, { value: number; month: number }>();
  series.forEach(([d, v]) => out.set(Number(d.slice(0, 4)), { value: v, month: Number(d.slice(5, 7)) }));
  return out;
}

/**
 * ВВП за двенадцать месяцев, кончающихся месяцем даты, млрд ₽.
 *
 * ВВП у нас годовой (Всемирный банк), а бюджет и долг — помесячные. Окно
 * «октябрь 2021 — сентябрь 2022» собирается из долей двух лет: 3/12 ВВП 2021
 * и 9/12 ВВП 2022. Год, которого ещё нет, — оценка: прошлый год, выросший
 * так же, как вырос он сам. Делить номинал на номинал нужно потому, что при
 * инфляции 6–12% в год «трлн ₽» растут сами по себе: долг 8 трлн в 2016-м
 * и 33 трлн сейчас — не вчетверо большая нагрузка, а вдвое.
 */
function gdpWindow(gdp: SeriesPoint[] | undefined): (iso: string) => number | null {
  const byYear = new Map((gdp ?? []).map(([d, v]) => [Number(d.slice(0, 4)), v]));
  const years = Array.from(byYear.keys()).sort((a, b) => a - b);
  const last = years[years.length - 1];
  const growth = last && byYear.get(last - 1) ? (byYear.get(last) as number) / (byYear.get(last - 1) as number) : 1;
  const yearGdp = (y: number) => byYear.get(y) ?? (last && y > last ? (byYear.get(last) as number) * growth ** (y - last) : null);
  return (iso: string) => {
    const y = Number(iso.slice(0, 4));
    const m = Number(iso.slice(5, 7));
    const a = yearGdp(y - 1);
    const b = yearGdp(y);
    return a === null || b === null ? null : (a * (12 - m) + b * m) / 12;
  };
}

/** Ряд в процентах ВВП за двенадцать месяцев. */
function toGdp(series: SeriesPoint[], gdp: (iso: string) => number | null): SeriesPoint[] {
  return series.flatMap(([d, v]) => {
    const g = gdp(d);
    return g ? [[d, (v / g) * 100] as SeriesPoint] : [];
  });
}

/** Сдвиг даты на месяцы, первое число месяца. */
function shiftMonth(iso: string, months: number): string {
  const d = new Date(toT(iso.slice(0, 7) + '-01'));
  d.setUTCMonth(d.getUTCMonth() + months);
  return d.toISOString().slice(0, 10);
}

/**
 * Рост медианного дохода из опроса ЦБ год к году, %. Опрос шумный — месяц
 * к месяцу медиана прыгает на 5–10%, — поэтому сравниваются средние за три
 * месяца: последние три против тех же трёх год назад.
 */
function incomeGrowth(series: SeriesPoint[] | undefined): SeriesPoint[] {
  const byMonth = new Map((series ?? []).map(([d, v]) => [d.slice(0, 7), v]));
  const mean = (end: string) => {
    const xs = [0, -1, -2].map((k) => byMonth.get(shiftMonth(end, k).slice(0, 7))).filter((x): x is number => x !== undefined);
    return xs.length >= 2 ? xs.reduce((a, x) => a + x, 0) / xs.length : null;
  };
  return (series ?? []).flatMap(([d]) => {
    const now = mean(d);
    const before = mean(shiftMonth(d, -12));
    return now !== null && before ? [[d, (now / before - 1) * 100] as SeriesPoint] : [];
  });
}

/** Первое число последнего месяца, закончившегося к дате. */
function closedMonth(iso: string): string {
  const d = new Date(toT(iso));
  d.setUTCDate(d.getUTCDate() + 1);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return d.toISOString().slice(0, 10);
}

// ─── Сводка на дату ────────────────────────────────────────────────────────

function Stat({ label, value, sub, now }: { label: string; value: string; sub?: React.ReactNode; now?: string | null }) {
  return (
    <div className="mo-stat">
      <span className="mo-stat-label">{label}</span>
      <span className="mo-stat-value">{value}</span>
      {sub && <span className="mo-stat-sub">{sub}</span>}
      {now && <span className="mo-stat-sub ec-now">сейчас {now}</span>}
    </div>
  );
}

function Summary({ macro, market, on, isToday }: { macro: MacroOut; market: MarketOverview; on: string; isToday: boolean }) {
  const s = macro.series;
  const b = macro.budget;
  const latest = todayIso();
  // Дневные ряды (ставка, курс, нефть) — на сам день; помесячные, квартальные
  // и годовые — за последний закончившийся к нему период.
  const FREQ_MONTHS: Record<string, number> = { month: 1, quarter: 3, year: 12 };
  const monthsOf = (series: SeriesPoint[] | undefined) => {
    const code = Object.keys(s).find((c) => s[c] === series);
    return FREQ_MONTHS[macro.meta[code ?? '']?.freq ?? ''] ?? (series && Object.values(b).some((x) => x.rolling === series) ? 1 : 0);
  };
  const pick = (series: SeriesPoint[] | undefined, iso: string) => {
    const months = monthsOf(series);
    return months ? closed(series, iso, months) : at(series, iso);
  };
  const nowOf = (series: SeriesPoint[] | undefined, f: (v: number) => string) => {
    if (isToday) return null;
    const p = pick(series, latest);
    return p ? f(p[1]) : null;
  };
  const pct1 = (v: number) => `${ru(v, 1)}%`;
  const pct2 = (v: number) => `${ru(v, 2)}%`;

  const infl = pick(s.M_INFL, on);
  const exp = pick(s.M_INFL_EXP, on);
  const key = pick(market.series.key_rate, on);
  // В ряду ставки последний день повторяет ступень — «с какого дня» берём по
  // первой точке ступени.
  const keySince = (() => {
    const steps = market.series.key_rate;
    if (!key) return null;
    let i = steps.findIndex(([d]) => d === key[0]);
    while (i > 0 && steps[i - 1][1] === key[1]) i -= 1;
    return steps[i]?.[0] ?? key[0];
  })();
  const ofz = pick(market.series.ofz10, on);
  const bal = pick(b.M_BUD_BAL?.rolling, on);
  const og = closed(ratio(b.M_BUD_REV_OG?.rolling ?? [], b.M_BUD_REV?.rolling ?? []), on, 1);
  const fnb = pick(s.M_FNB, on);
  const fnbOther = pick(s.M_FNB_OTHER, on);
  const fnbGdp = pick(s.M_FNB_GDP, on);
  const debt = pick(s.M_DEBT_DOM, on);
  const usd = pick(s.USDRUB, on);
  const eur = pick(s.EURRUB, on);
  const cny = pick(s.CNYRUB, on);
  const brent = pick(s.BRENT, on);
  const gdpGrowth = pick(s.M_GDP_GROWTH, on);
  const credit = pick(s.M_CREDIT, on);
  const creditCorp = pick(s.M_CREDIT_CORP, on);
  const creditHh = pick(s.M_CREDIT_HH, on);
  const unemp = pick(s.M_UNEMP, on);
  const gdpW = gdpWindow(s.M_GDP);
  const liquid = (f: SeriesPoint | null, o: SeriesPoint | null) => (f && o && f[0] === o[0] ? f[1] - o[1] : null);
  const fnbLiquid = liquid(fnb, fnbOther);
  const fnbLiquidNow = isToday ? null : liquid(pick(s.M_FNB, latest), pick(s.M_FNB_OTHER, latest));
  const balNow = isToday ? null : pick(b.M_BUD_BAL?.rolling, latest);

  return (
    <div className="mo-stats ec-stats">
      <Stat label="Инфляция, год к году" value={infl ? pct2(infl[1]) : '—'}
        sub={infl ? <>за {monthName(infl[0])}{exp ? `; люди ждут ${pct1(exp[1])}` : ''}</> : undefined}
        now={nowOf(s.M_INFL, pct2)} />
      <Stat label="Ключевая ставка" value={key ? pct2(key[1]) : '—'}
        sub={key ? <>с {dotDate(keySince ?? key[0])}{infl ? `; за вычетом инфляции ${signed(key[1] - infl[1], 1)}%` : ''}</> : undefined}
        now={nowOf(market.series.key_rate, pct2)} />
      <Stat label="ОФЗ 10 лет" value={ofz ? pct2(ofz[1]) : '—'}
        sub={ofz && key ? `к ключевой ${signed(ofz[1] - key[1], 1)} п.п.${exp ? `; к ожиданиям людей ${signed(ofz[1] - exp[1], 1)} п.п.` : ''}` : 'доходность'}
        now={nowOf(market.series.ofz10, pct2)} />
      <Stat label="Бюджет за 12 месяцев" value={bal ? `${bal[1] < 0 ? '−' : '+'}${trln(Math.abs(bal[1]))}` : '—'}
        sub={bal ? <>{bal[1] < 0 ? 'дефицит' : 'профицит'}{gdpW(bal[0]) ? ` ≈ ${ru(Math.abs(bal[1]) / (gdpW(bal[0]) as number) * 100, 1)}% ВВП` : ''}{og ? `; нефтегаз — ${ru(og[1], 0)}% доходов` : ''}</> : undefined}
        now={balNow ? `${balNow[1] < 0 ? '−' : '+'}${trln(Math.abs(balNow[1]))}` : null} />
      <Stat label="ФНБ, ликвидная часть" value={fnbLiquid !== null ? `${trln(fnbLiquid)} ₽` : '—'}
        sub={fnb ? <>всего {trln(fnb[1])}{fnbGdp ? `, ${ru(fnbGdp[1], 1)}% ВВП` : ''}
          {fnbLiquid !== null && bal && bal[1] < 0 ? `; ≈ ${ru(fnbLiquid / (-bal[1] / 12), 0)} мес. дефицита` : ''}</> : undefined}
        now={fnbLiquidNow !== null ? `${trln(fnbLiquidNow)} ₽` : null} />
      <Stat label="Госдолг в ОФЗ" value={debt ? `${trln(debt[1])} ₽` : '—'}
        sub={debt ? (() => {
          const g = gdpW(debt[0]);
          return `на конец ${monthName(debt[0])}${g ? `; ≈ ${ru(debt[1] / g * 100, 1)}% ВВП` : ''}`;
        })() : undefined}
        now={nowOf(s.M_DEBT_DOM, (v) => `${trln(v)} ₽`)} />
      <Stat label="Доллар" value={usd ? `${ru(usd[1], 2)} ₽` : '—'}
        sub={eur && cny ? `евро ${ru(eur[1], 2)} ₽, юань ${ru(cny[1], 2)} ₽` : undefined}
        now={nowOf(s.USDRUB, (v) => `${ru(v, 2)} ₽`)} />
      <Stat label="Нефть Brent" value={brent ? `$${ru(brent[1], 0)}` : '—'}
        sub={brent && usd ? `${ru(brent[1] * usd[1], 0)} ₽ за баррель` : undefined}
        now={nowOf(s.BRENT, (v) => `$${ru(v, 0)}`)} />
      {(() => {
        // Истории у оценки нет: Мосбиржа отдаёт только сегодняшние выпуски,
        // ряд копится с первого запуска. На прошлую дату — прочерк.
        const interest = pick(s.M_OFZ_INT, on);
        const rev = pick(b.M_BUD_REV?.rolling, on);
        const fresh = interest && (isToday || interest[0] >= on.slice(0, 8) + '01');
        return (
          <Stat label="Проценты по ОФЗ за год" value={fresh && interest ? `${trln(interest[1])} ₽` : '—'}
            sub={fresh && interest
              ? <>оценка по текущим купонам{rev ? `; ≈ ${ru(interest[1] / rev[1] * 100, 0)}% доходов бюджета` : ''}</>
              : `оценка ведётся с ${s.M_OFZ_INT?.[0] ? dotDate(s.M_OFZ_INT[0][0]) : 'октября 2026'}`}
            now={!isToday && s.M_OFZ_INT?.length ? `${trln(s.M_OFZ_INT[s.M_OFZ_INT.length - 1][1])} ₽` : null} />
        );
      })()}
      <Stat label="Кредит экономике" value={credit ? `${signed(credit[1], 1)}%` : '—'}
        sub={credit ? <>за год к {monthName(credit[0])}{creditCorp && creditHh ? `; компаниям ${signed(creditCorp[1], 1)}%, людям ${signed(creditHh[1], 1)}%` : ''}</> : undefined}
        now={nowOf(s.M_CREDIT, (v) => `${signed(v, 1)}%`)} />
      <Stat label="Рост ВВП" value={gdpGrowth ? `${signed(gdpGrowth[1], 1)}%` : '—'}
        sub={gdpGrowth ? `за ${gdpGrowth[0].slice(0, 4)} год` : undefined}
        now={nowOf(s.M_GDP_GROWTH, (v) => `${signed(v, 1)}%`)} />
      <Stat label="Безработица" value={unemp ? pct1(unemp[1]) : '—'}
        sub={unemp ? `за ${unemp[0].slice(0, 4)} год` : undefined} now={nowOf(s.M_UNEMP, pct1)} />
    </div>
  );
}

// ─── Рынок и компании на дату ──────────────────────────────────────────────

const money = (n: number) => (Math.abs(n) >= 100 ? ru(n, 0) : formatPerShare(n));

function MarketThen({ market, on, isToday }: { market: MarketOverview; on: string; isToday: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['macro-companies', on],
    queryFn: () => fetchMacroCompanies(on),
    staleTime: 30 * 60 * 1000,
  });
  const [all, setAll] = useState(false);
  const isPhone = useMediaQuery(PHONE_QUERY);
  const imoexThen = at(market.series.IMOEX, on);
  const mcftrThen = at(market.series.MCFTR, on);
  const imoexNow = market.series.IMOEX[market.series.IMOEX.length - 1];
  const mcftrNow = market.series.MCFTR[market.series.MCFTR.length - 1];
  // P/E рынка — на конец последнего закрытого к дате года.
  const year = Number(on.slice(0, 4)) - (on.slice(5) === '12-31' ? 0 : 1);
  const val = isToday
    ? market.valuation.find((y) => y.year === 'now')
    : market.valuation.find((y) => y.year === year);

  const rows = data?.rows ?? [];
  const cheaper = rows.filter((r) => r.price < r.reference);
  const dearer = rows.filter((r) => r.price >= r.reference);
  const avg = (list: MacroCompany[]) => {
    const xs = list.map((r) => r.change).filter((x): x is number => x !== null);
    return xs.length ? xs.reduce((a, x) => a + x, 0) / xs.length : null;
  };
  const shown = all ? rows : rows.slice(0, 10);
  const median = (list: MacroCompany[]) => {
    const xs = list.map((r) => r.change).filter((x): x is number => x !== null).sort((a, b) => a - b);
    if (!xs.length) return null;
    const mid = xs.length >> 1;
    return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
  };
  const avgCheap = avg(cheaper);
  const avgDear = avg(dearer);
  const medCheap = median(cheaper);
  const medDear = median(dearer);

  return (
    <section className="mo-card">
      <div className="mo-card-head">
        <h2>{isToday ? 'Рынок и компании сейчас' : `Рынок и компании на ${dotDate(on)}`}</h2>
        <span className="mo-card-sub">опорная — как она считалась в тот день, по раскрытым к нему отчётам</span>
      </div>
      <div className="ec-then">
        <div className="ec-then-fig">
          <span className="mo-stat-label">Индекс Мосбиржи</span>
          <span className="mo-stat-value">{imoexThen ? ru(imoexThen[1], 0) : '—'}</span>
          {!isToday && imoexThen && imoexNow && (
            <span className="mo-stat-sub">
              сейчас {ru(imoexNow[1], 0)}{' '}
              <b className={imoexNow[1] >= imoexThen[1] ? 'mo-up' : 'mo-down'}>{signed((imoexNow[1] / imoexThen[1] - 1) * 100, 0)}%</b>
              {mcftrThen && mcftrNow && <>; с дивидендами {signed((mcftrNow[1] / mcftrThen[1] - 1) * 100, 0)}%</>}
            </span>
          )}
        </div>
        <div className="ec-then-fig">
          <span className="mo-stat-label">{isToday ? 'P/E рынка' : `P/E рынка на конец ${year}`}</span>
          <span className="mo-stat-value">{val ? ru(val.pe, 1) : '—'}</span>
          {val && (
            <span className="mo-stat-sub">
              доходность прибыли {ru(val.earnings_yield, 1)}%{val.ofz10 !== null ? ` против ${ru(val.ofz10, 1)}% ОФЗ` : ''}
              {val.premium !== null && <> — разрыв <b className={val.premium >= 0 ? 'mo-up' : 'mo-down'}>{signed(val.premium, 1)} п.п.</b></>}
            </span>
          )}
        </div>
        <div className="ec-then-fig">
          <span className="mo-stat-label">Дешевле опорной</span>
          <span className="mo-stat-value">{data ? <>{cheaper.length}<small> из {rows.length}</small></> : '…'}</span>
          {!isToday && medCheap !== null && (
            <span className="mo-stat-sub">
              их цена с тех пор: медиана <b className={medCheap >= 0 ? 'mo-up' : 'mo-down'}>{signed(medCheap, 0)}%</b>
              {avgCheap !== null && <>, в среднем {signed(avgCheap, 0)}%</>}
              {medDear !== null && <>; у {dearer.length} остальных медиана {signed(medDear, 0)}%{avgDear !== null ? `, в среднем ${signed(avgDear, 0)}%` : ''}</>}
            </span>
          )}
        </div>
      </div>

      {isLoading && <div className="mo-state">Считаем оценки на эту дату…</div>}
      {rows.length > 0 && isPhone && (
        <>
          <ul className="ec-list">
            {shown.map((r) => {
              const gap = (r.price / r.reference - 1) * 100;
              return (
                <li key={r.id}>
                  <Link to={`/company/${r.id}`} className="ec-list-name">{r.name}<span className="ec-ticker">{r.ticker}</span></Link>
                  <span className="ec-list-line">
                    {money(r.price)} ₽ при опорной {money(r.reference)}{' · '}
                    <b className={gap < 0 ? 'ec-cheap' : 'ec-dear'}>
                      {gap < 0 ? `дешевле на ${ru(-gap, 0)}%` : `дороже на ${ru(gap, 0)}%`}
                    </b>
                    {!isToday && r.change !== null && (
                      <>{' · '}с тех пор <b className={r.change >= 0 ? 'mo-up' : 'mo-down'}>{signed(r.change, 0)}%</b></>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
          {rows.length > 10 && (
            <button type="button" className="ec-more" onClick={() => setAll((v) => !v)}>
              {all ? 'Только первые десять' : `Все ${rows.length} компаний`}
            </button>
          )}
        </>
      )}
      {rows.length > 0 && !isPhone && (
        <div className="ec-table-wrap">
          <table className="ec-table">
            <thead>
              <tr>
                <th scope="col">Компания</th>
                <th scope="col">Цена{isToday ? '' : ' тогда'}, ₽</th>
                <th scope="col">Опорная{isToday ? '' : ' тогда'}, ₽</th>
                <th scope="col">Цена к опорной</th>
                {!isToday && <th scope="col">Цена сейчас, ₽</th>}
                {!isToday && <th scope="col">Изменение</th>}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const gap = (r.price / r.reference - 1) * 100;
                return (
                  <tr key={r.id}>
                    <th scope="row">
                      <Link to={`/company/${r.id}`}>{r.name}</Link>
                      <span className="ec-ticker">{r.ticker}</span>
                    </th>
                    <td>{money(r.price)}</td>
                    <td title={r.basis ? `по ${r.basis.replace('отчёт', 'отчёту')}` : undefined}>{money(r.reference)}</td>
                    <td className={gap < 0 ? 'ec-cheap' : 'ec-dear'}>
                      {gap < 0 ? `дешевле на ${ru(-gap, 0)}%` : r.price >= r.reference * 2 ? `дороже в ${ru(r.price / r.reference, 1)} раза` : `дороже на ${ru(gap, 0)}%`}
                    </td>
                    {!isToday && <td>{r.price_now !== null ? money(r.price_now) : '—'}</td>}
                    {!isToday && (
                      <td className={r.change === null ? '' : r.change >= 0 ? 'mo-up' : 'mo-down'}>
                        {r.change === null ? '—' : `${signed(r.change, 0)}%`}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length > 10 && (
            <button type="button" className="ec-more" onClick={() => setAll((v) => !v)}>
              {all ? 'Только первые десять' : `Все ${rows.length} компаний`}
            </button>
          )}
        </div>
      )}
      {data && rows.length === 0 && <div className="mo-state">На эту дату оценок нет: отчётов за прошлые годы в базе не хватает.</div>}
      <p className="mo-note">
        Компании с проверенными отчётами, у которых на эту дату была цена и хватало истории для оценки, —
        только те, что торгуются до сих пор: ушедшие с биржи в выборку не попали, и прошлое из-за этого
        выглядит лучше, чем было. Цена приведена к нынешнему числу акций; изменение — без дивидендов. Выборка
        небольшая: одна-две компании заметно сдвигают среднее, поэтому рядом — медиана. Это история, а не
        совет: дешевизна относительно опорной — запас прочности, а не обещание роста.
      </p>
    </section>
  );
}

// ─── Страница ──────────────────────────────────────────────────────────────

type Window = { from: string | null; fromYear: number; rel: boolean };

/**
 * Карточка графика со своими переключателями: период и единицы стоят прямо
 * у графика. Раньше они были одни на всю страницу, наверху, — чтобы сменить
 * период у курса валют, приходилось листать мимо пяти графиков вверх и
 * обратно. Каждая карточка помнит свой выбор сама.
 *
 * `units` — подписи «как есть / относительно» (трлн ₽ / % ВВП, ₽ / % от
 * начала); нет — у ряда, который и так в процентах, переключать нечего.
 */
function EcCard({ title, sub, end, units, defaultRange = '10y', className, children }: {
  title: string;
  sub: (rel: boolean) => string;
  /** Правый край графиков: дата снимка или сегодня. */
  end: string;
  units?: [string, string];
  defaultRange?: RangeKey;
  className?: string;
  children: (w: Window) => React.ReactNode;
}) {
  const [range, setRange] = useState<RangeKey>(defaultRange);
  const [rel, setRel] = useState(false);
  const years = RANGES.find((r) => r.key === range)?.years ?? null;
  const from = years === null ? null : `${Number(end.slice(0, 4)) - years}${end.slice(4, 7)}-01`;
  return (
    <section className={`mo-card ec-card${className ? ` ${className}` : ''}`}>
      <div className="mo-card-head ec-card-head">
        <div>
          <h2>{title}</h2>
          <span className="mo-card-sub">{sub(rel)}</span>
        </div>
        <div className="ec-ctrl">
          <span className="seg" role="radiogroup" aria-label={`Период: ${title}`}>
            {RANGES.map((r) => (
              <button key={r.key} type="button" role="radio" aria-checked={range === r.key}
                className={range === r.key ? 'seg-btn is-on' : 'seg-btn'} onClick={() => setRange(r.key)}>{r.label}</button>
            ))}
          </span>
          {units && (
            <span className="seg" role="radiogroup" aria-label={`Единицы: ${title}`}>
              {([false, true] as const).map((value, i) => (
                <button key={String(value)} type="button" role="radio" aria-checked={rel === value}
                  className={rel === value ? 'seg-btn is-on' : 'seg-btn'} onClick={() => setRel(value)}>{units[i]}</button>
              ))}
            </span>
          )}
        </div>
      </div>
      {children({ from, fromYear: from ? Number(from.slice(0, 4)) : 0, rel })}
    </section>
  );
}

function Source({ children }: { children: React.ReactNode }) {
  return <p className="ec-source">{children}</p>;
}

export default function EconomyPage() {
  const colors = useChartColors();
  const [params, setParams] = useSearchParams();
  // «Как было тогда» — графики обрываются на дате снимка; «и что было потом» —
  // идут до сегодня, а дата отмечена чертой.
  const [after, setAfter] = useState(false);
  const today = todayIso();
  const onParam = params.get('on');
  const on = onParam && /^\d{4}-\d{2}-\d{2}$/.test(onParam) && onParam < today ? onParam : today;
  const isToday = on === today;
  const setOn = (iso: string | null) => {
    const next = new URLSearchParams(params);
    if (!iso || iso >= today) next.delete('on'); else next.set('on', iso);
    setParams(next, { replace: true });
  };

  const { data: macro, isLoading, error } = useQuery({ queryKey: ['macro'], queryFn: fetchMacro, staleTime: 30 * 60 * 1000 });
  const { data: market } = useQuery({ queryKey: ['market-overview'], queryFn: fetchMarketOverview, staleTime: 30 * 60 * 1000 });

  const till = isToday || after ? null : on;
  const end = till ?? today;
  const snap = isToday ? null : on;
  // Последний месяц, закончившийся к дате снимка: по нему таблица бюджета и
  // столбцы финансирования. Квартал и год — так же, по их концу.
  const cutoff = isToday ? null : closedMonth(on);
  const cutQuarter = cutoff
    ? `${cutoff.slice(0, 5)}${String(Math.floor((Number(cutoff.slice(5, 7)) - 1) / 3) * 3 + 1).padStart(2, '0')}-01`
    : null;
  const quarterDone = cutoff && cutQuarter && Number(cutoff.slice(5, 7)) % 3 === 0;
  const lastQuarter = !cutoff ? null : quarterDone ? cutQuarter : (() => {
    const d = new Date(toT(cutQuarter as string));
    d.setUTCMonth(d.getUTCMonth() - 3);
    return d.toISOString().slice(0, 10);
  })();
  const lastYear = cutoff ? Number(cutoff.slice(0, 4)) - (cutoff.slice(5, 7) === '12' ? 0 : 1) : null;

  const views = useMemo(() => {
    if (!macro) return null;
    const s = macro.series;
    const b = macro.budget;
    const roll = (code: string) => b[code]?.rolling ?? [];

    // Финансирование дефицита по годам: декабрь каждого года (накопленный
    // итог = весь год), у текущего — последний опубликованный месяц.
    const fin = [
      { key: 'M_BUD_FIN_DOM', label: 'ОФЗ (займы минус погашения)', color: colors.line1 },
      { key: 'M_BUD_FIN_ACC', label: 'Остатки на счетах, в т. ч. ФНБ', color: colors.line4 },
      { key: 'M_BUD_FIN_FX', label: 'Курсовая разница', color: colors.line5 },
      { key: 'M_BUD_FIN_OTH', label: 'Прочее внутри страны', color: colors.axis },
      { key: 'M_BUD_FIN_EXT', label: 'Внешние займы', color: colors.line6 },
    ];
    // Столбцы — тот же график: с «что было потом» идут до сегодня.
    const finCut = after ? null : cutoff;
    const upTo = (series: SeriesPoint[] | undefined) => (series ?? []).filter(([d]) => !finCut || d <= finCut);
    const ends = Object.fromEntries(fin.map((f) => [f.key, yearEnds(upTo(s[f.key]))]));
    const balEnds = yearEnds(upTo(s.M_BUD_BAL));
    const finYears = Array.from(ends.M_BUD_FIN_DOM.keys()).sort();
    const finRows: BarRow[] = finYears.map((y) => {
      const month = ends.M_BUD_FIN_DOM.get(y)?.month ?? 12;
      const row: BarRow = { label: month === 12 ? String(y) : `${y}*`, year: y };
      fin.forEach((f) => { row[f.key] = ends[f.key].get(y)?.value ?? null; });
      const bal = (s.M_BUD_BAL ?? []).find(([d]) => d === `${y}-${String(month).padStart(2, '0')}-01`);
      row.deficit = bal ? -bal[1] : (balEnds.get(y)?.value ?? null);
      return row;
    });
    const finPartial = finYears.length ? ends.M_BUD_FIN_DOM.get(finYears[finYears.length - 1]) : null;
    const finMonths = new Map(finYears.map((y) => [y, ends.M_BUD_FIN_DOM.get(y)?.month ?? 12]));

    // Счёт текущих операций и торговля — по кварталам.
    const bopRows: BarRow[] = (s.M_BOP_CA ?? []).map(([d, v]) => ({
      label: quarterName(d), date: d,
      ca: v,
      exp: at(s.M_BOP_EXP, d)?.[1] ?? null,
      imp: at(s.M_BOP_IMP, d)?.[1] ?? null,
    }));

    const gdpRows: BarRow[] = (s.M_GDP_GROWTH ?? []).map(([d, v]) => ({
      label: d.slice(0, 4), year: Number(d.slice(0, 4)), growth: v,
      unemp: s.M_UNEMP?.find(([u]) => u === d)?.[1] ?? null,
    }));

    const brentRub: SeriesPoint[] = (s.BRENT ?? []).flatMap(([d, v]) => {
      const fx = at(s.USDRUB, d);
      return fx ? [[d, v * fx[1]] as SeriesPoint] : [];
    });

    return {
      rev: roll('M_BUD_REV'),
      exp: roll('M_BUD_EXP'),
      revOg: roll('M_BUD_REV_OG'),
      revNog: roll('M_BUD_REV_NOG'),
      bal: roll('M_BUD_BAL'),
      balNog: roll('M_BUD_BAL_NOG'),
      ogShare: ratio(roll('M_BUD_REV_OG'), roll('M_BUD_REV')),
      fin, finRows, finPartial, finMonths,
      fnbLiquid: diff(s.M_FNB ?? [], s.M_FNB_OTHER ?? []),
      bopRows, gdpRows, brentRub,
      incomeGrowth: incomeGrowth(s.M_INCOME),
    };
  }, [macro, colors, cutoff, after]);

  if (isLoading) return <div className="mo"><div className="mo-state">Загружаем данные экономики…</div></div>;
  if (error || !macro || !views) return <div className="mo"><div className="mo-state">Не удалось загрузить данные экономики.</div></div>;

  const s = macro.series;
  const gdpW = gdpWindow(s.M_GDP);
  // Бюджет и долг — в трлн ₽ или в % ВВП, у каждой карточки свой выбор.
  const u = (series: SeriesPoint[], inGdp: boolean) => (inGdp ? toGdp(series, gdpW) : series);
  const k = (bln: number) => ru(bln / 1000, Number.isInteger(Math.round(bln) / 1000) ? 0 : 1);
  const share = (v: number) => `${ru(v, Number.isInteger(v) ? 0 : 1)}%`;
  const money = (inGdp: boolean) => (inGdp ? share : k);
  const unitName = (inGdp: boolean) => (inGdp ? '% ВВП' : 'трлн ₽');
  const MONEY_UNITS: [string, string] = ['трлн ₽', '% ВВП'];
  const REBASE_UNITS = (abs: string): [string, string] => [abs, '% от начала'];
  const showAll = isToday || after;
  const pctFmt = (v: number) => `${ru(v, 0)}%`;
  const snapYear = isToday ? null : on.slice(0, 4);
  const snapQuarter = isToday ? null : quarterName(`${on.slice(0, 5)}${String(Math.floor((Number(on.slice(5, 7)) - 1) / 3) * 3 + 1).padStart(2, '0')}-01`);

  // Сводка бюджета с начала года против того же периода прошлого.
  const lastRev = cutoff ? at(s.M_BUD_REV, cutoff) : s.M_BUD_REV?.[s.M_BUD_REV.length - 1];
  const ytdMonth = lastRev ? lastRev[0] : null;
  const prevSame = ytdMonth ? `${Number(ytdMonth.slice(0, 4)) - 1}${ytdMonth.slice(4)}` : null;
  const prevYearEnd = ytdMonth ? `${Number(ytdMonth.slice(0, 4)) - 1}-12-01` : null;
  const valueAt = (code: string, iso: string | null) => (iso ? s[code]?.find(([d]) => d === iso)?.[1] ?? null : null);
  const ytdRows: [string, string, boolean?][] = [
    ['Доходы', 'M_BUD_REV'],
    ['нефтегазовые', 'M_BUD_REV_OG', true],
    ['ненефтегазовые', 'M_BUD_REV_NOG', true],
    ['в т. ч. НДС внутренний', 'M_BUD_VAT', true],
    ['в т. ч. налог на прибыль', 'M_BUD_PROFIT', true],
    ['Расходы', 'M_BUD_EXP'],
    ['Дефицит (−) / профицит (+)', 'M_BUD_BAL'],
    ['Ненефтегазовый дефицит', 'M_BUD_BAL_NOG'],
  ];
  const lawEnd = cutoff ?? today;
  const lawRows = Object.entries(macro.budget_law)
    .map(([y, law]) => ({ year: Number(y), law }))
    .filter((r) => r.year <= Number(lawEnd.slice(0, 4)))
    .flatMap(({ year, law }) => {
      const last = at(s.M_BUD_REV, `${year}-12-01` < lawEnd ? `${year}-12-01` : lawEnd);
      if (!last || Number(last[0].slice(0, 4)) !== year) return [];
      const month = Number(last[0].slice(5, 7));
      return [{
        year, law, month, partial: month !== 12,
        rev: valueAt('M_BUD_REV', last[0]),
        exp: valueAt('M_BUD_EXP', last[0]),
        bal: valueAt('M_BUD_BAL', last[0]),
      }];
    });
  const ytdLabel = ytdMonth ? `янв–${MONTHS[Number(ytdMonth.slice(5, 7)) - 1]} ${ytdMonth.slice(0, 4)}` : '';
  const prevLabel = prevSame ? `янв–${MONTHS[Number(prevSame.slice(5, 7)) - 1]} ${prevSame.slice(0, 4)}` : '';

  return (
    <div className="mo ec">
      <section className="mo-card mo-head">
        <div className="mo-head-top">
          <div>
            <h1>Экономика</h1>
            <p className="mo-lede">
              Состояние государства в опубликованных числах: бюджет и чем закрывается дефицит, резервы и
              долг, цены, курс и настроения людей. Выберите дату — графики и таблицы покажут, как всё выглядело
              тогда, а ниже будет видно, что было с рынком и какие компании стоили дешевле своей оценки.
            </p>
          </div>
          <span className="mo-asof">данные на {dotDate(macro.as_of)}</span>
        </div>

        <div className="ec-snap" role="group" aria-label="Снимок на дату">
          <span className="ec-snap-label">Снимок:</span>
          <button type="button" className={isToday ? 'ec-chip is-on' : 'ec-chip'} onClick={() => setOn(null)}>сейчас</button>
          {PRESETS.map((p) => (
            <button key={p.on} type="button" title={p.what}
              className={on === p.on ? 'ec-chip is-on' : 'ec-chip'} onClick={() => setOn(p.on)}>{p.label}</button>
          ))}
          <input type="date" className="ec-date" aria-label="Своя дата" min="2014-01-01" max={today}
            value={on} onChange={(e) => e.target.value && setOn(e.target.value)} />
        </div>

        {market ? <Summary macro={macro} market={market} on={on} isToday={isToday} /> : <div className="mo-state">…</div>}
        {!isToday && (
          <p className="mo-note">
            Значения — за последний период, закончившийся к {dotDate(on)}: инфляция и бюджет — за месяц, рост ВВП
            и безработица — за год. Публикуются они с задержкой, так что в сам этот день часть ещё не была известна.
          </p>
        )}
      </section>

      {market && <MarketThen market={market} on={on} isToday={isToday} />}

      {!isToday && (
        <div className="ec-range">
          <label className="ec-after">
            <input type="checkbox" checked={after} onChange={(e) => setAfter(e.target.checked)} />
            показать на графиках, что было после {dotDate(on)}
          </label>
        </div>
      )}
      <p className="mo-hint ec-hint">
        Период и единицы меняются у каждого графика справа от заголовка. Зажмите кнопку мыши и проведите по
        графику — покажет, как изменился каждый ряд за отрезок.
      </p>

      <EcCard title="Федеральный бюджет" end={end} units={MONEY_UNITS}
        sub={(rel) => `за последние 12 месяцев на каждую дату, ${unitName(rel)}`}>
        {({ from, rel }) => (
          <>
            <TimeChart from={from} till={till} snap={snap} fmt={money(rel)} height={260} delta={rel ? 'pp' : 'pct'} lines={[
              { key: 'rev', label: 'Доходы', color: colors.line3, data: u(views.rev, rel), width: 2 },
              { key: 'exp', label: 'Расходы', color: colors.refBad, data: u(views.exp, rel), width: 2 },
              { key: 'og', label: 'в т. ч. нефтегазовые доходы', color: colors.line4, data: u(views.revOg, rel) },
            ]} />
            <div className="mo-pair ec-subpair">
              <div className="mo-card">
                <h3 className="ec-h3">Дефицит за 12 месяцев, {unitName(rel)}</h3>
                <TimeChart from={from} till={till} snap={snap} fmt={money(rel)} zero={false} height={200} delta={rel ? 'pp' : 'abs'} lines={[
                  { key: 'bal', label: 'Дефицит (−) / профицит (+)', color: colors.textPrimary, data: u(views.bal, rel), width: 2 },
                  { key: 'nog', label: 'без нефти и газа', color: colors.axis, data: u(views.balNog, rel), dash: '4 3' },
                ]} />
              </div>
              <div className="mo-card">
                <h3 className="ec-h3">Доля нефти и газа в доходах, %</h3>
                <TimeChart from={from} till={till} snap={snap} fmt={pctFmt} zero height={200} legend={false} delta="pp" lines={[
                  { key: 'share', label: 'нефтегазовые доходы', color: colors.line4, data: views.ogShare, width: 2 },
                ]} />
              </div>
            </div>
            {ytdMonth && prevSame && (
              <div className="ec-table-wrap">
                <table className="ec-table ec-ytd">
                  <thead>
                    <tr>
                      <th scope="col">С начала года, млрд ₽</th>
                      <th scope="col">{ytdLabel}</th>
                      <th scope="col">{prevLabel}</th>
                      <th scope="col">Изменение</th>
                      <th scope="col">{Number(ytdMonth.slice(0, 4)) - 1} целиком</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ytdRows.map(([label, code, sub]) => {
                      const now = valueAt(code, ytdMonth);
                      const prev = valueAt(code, prevSame);
                      const full = valueAt(code, prevYearEnd);
                      const ch = now !== null && prev ? (now / prev - 1) * 100 : null;
                      const isBal = code.startsWith('M_BUD_BAL');
                      return (
                        <tr key={code} className={sub ? 'ec-sub' : undefined}>
                          <th scope="row">{label}</th>
                          <td>{now !== null ? ru(now, 0) : '—'}</td>
                          <td>{prev !== null ? ru(prev, 0) : '—'}</td>
                          <td>{isBal && now !== null && prev !== null ? `${signed(now - prev, 0)} млрд` : ch !== null ? `${signed(ch, 1)}%` : '—'}</td>
                          <td>{full !== null ? ru(full, 0) : '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {lawRows.length > 0 && (
              <div className="ec-table-wrap">
                <table className="ec-table ec-law">
                  <thead>
                    <tr>
                      <th scope="col">План и факт, млрд ₽</th>
                      <th scope="col">Доходы по закону</th>
                      <th scope="col">факт</th>
                      <th scope="col">Расходы по закону</th>
                      <th scope="col">факт</th>
                      <th scope="col">Дефицит по закону</th>
                      <th scope="col">факт</th>
                      <th scope="col">Расходы к закону</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lawRows.map((r) => (
                      <tr key={r.year} className={r.partial ? 'ec-partial' : undefined}>
                        <th scope="row">{r.partial ? `${r.year}, янв–${MONTHS[r.month - 1]}` : r.year}</th>
                        <td>{ru(r.law.revenue, 0)}</td>
                        <td>{r.rev !== null ? ru(r.rev, 0) : '—'}</td>
                        <td>{ru(r.law.expense, 0)}</td>
                        <td>{r.exp !== null ? ru(r.exp, 0) : '—'}</td>
                        <td>{ru(r.law.balance, 0)}</td>
                        <td className={r.bal !== null && r.bal < r.law.balance ? 'ec-over' : undefined}>{r.bal !== null ? ru(r.bal, 0) : '—'}</td>
                        <td className={!r.partial && r.exp !== null && r.exp > r.law.expense ? 'ec-over' : undefined}>
                          {r.exp === null ? '—' : r.partial
                            ? `${ru(r.exp / r.law.expense * 100, 0)}% годового`
                            : `${signed((r.exp / r.law.expense - 1) * 100, 1)}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Source>
              План — закон о бюджете в первоначальной редакции, без поправок в течение года: так видно, насколько
              исполнение ушло от того, что заложили в начале. Красным — дефицит больше заложенного и расходы сверх
              закона. Для неполного года — исполнено с начала года к годовому плану.
            </Source>
            <Source>
              Минфин, краткая информация об исполнении федерального бюджета; последний месяц — предварительная
              оценка. Сумма за 12 месяцев — накопленное с начала года плюс прошлый год минус прошлый год по тот же
              месяц. С 2022 года Минфин не публикует расходы по разделам (оборона, безопасность и другие) — в
              файле они обрываются на 2021 годе, поэтому здесь только общий итог.
            </Source>
          </>
        )}
      </EcCard>

      <EcCard title="Чем закрывается дефицит" end={end} units={MONEY_UNITS}
        sub={(rel) => `источники финансирования за год, ${unitName(rel)}`}>
        {({ fromYear, rel }) => (
          <>
            <Legend items={[...views.fin.map((f) => ({ label: f.label, color: f.color })), { label: 'дефицит', color: colors.textPrimary }]} />
            <PeriodBars
              rows={views.finRows.filter((r) => (r.year as number) >= fromYear).map((r) => {
                if (!rel) return r;
                // Год целиком — к ВВП года; неполный — к ВВП за 12 месяцев по последний месяц.
                const g = gdpW(`${r.year}-${r.label.endsWith('*') ? String(views.finMonths.get(r.year as number) ?? 12).padStart(2, '0') : '12'}-01`);
                const out: BarRow = { ...r };
                [...views.fin.map((f) => f.key), 'deficit'].forEach((key) => {
                  out[key] = g && typeof r[key] === 'number' ? ((r[key] as number) / g) * 100 : null;
                });
                return out;
              })}
              bars={views.fin.map((f) => ({ ...f, stack: true }))}
              lines={[{ key: 'deficit', label: 'Дефицит', color: colors.textPrimary }]}
              snapLabel={showAll ? snapYear : null} fmt={rel ? share : k} height={280} />
            <Source>
              Выше нуля — откуда взяли деньги, ниже — куда отложили (в профицитные годы бюджет пополнял счета и
              гасил долг). «Остатки на счетах» — это прежде всего траты ФНБ и других накоплений; курсовая разница —
              переоценка валюты на этих счетах.
              {views.finPartial && views.finPartial.month !== 12 && (cutoff && !after
                ? ` * — январь–${MONTHS_FULL[views.finPartial.month - 1]}: последний месяц, закончившийся к дате снимка.`
                : ` * — январь–${MONTHS_FULL[views.finPartial.month - 1]}: источники Минфин публикует на месяц позже доходов и расходов.`)}
            </Source>
          </>
        )}
      </EcCard>

      <EcCard title="Нефть и бюджетное правило" end={end} sub={() => 'за месяц, млрд ₽'}>
        {({ from }) => (
          <>
            <Legend items={[
              { label: 'Нефтегазовые доходы сверх базовых (ниже нуля — недобор)', color: colors.line3 },
              { label: 'Покупка (+) / продажа (−) валюты Минфином', color: colors.textPrimary },
            ]} />
            <PeriodBars
              rows={(s.M_OG_EXTRA ?? [])
                .filter(([d]) => (!from || d >= from) && (showAll || !cutoff || d <= cutoff))
                .map(([d, v]) => ({ label: monthName(d), extra: v, fx: at(s.M_FX_OPS, d)?.[0] === d ? (at(s.M_FX_OPS, d) as SeriesPoint)[1] : null }))}
              bars={[{ key: 'extra', label: 'Сверх базовых', color: colors.line3 }]}
              lines={[{ key: 'fx', label: 'Покупка / продажа валюты', color: colors.textPrimary }]}
              signColors={{ pos: colors.line3, neg: colors.refBad }}
              snapLabel={showAll && !isToday ? monthName(closedMonth(on)) : null} fmt={(v) => ru(v, 0)} height={240} />
            <Source>
              Минфин. Бюджет считает «базовыми» нефтегазовые доходы при цене отсечения Urals (в 2026 году — $59 за
              баррель); всё сверх неё — дополнительные доходы, их Минфин откладывает в ФНБ, покупая валюту и золото.
              Недобор покрывается продажей из ФНБ — так бюджетное правило гасит колебания нефти для рубля и бюджета.
              Цены Urals машиночитаемым рядом Минфин не публикует, поэтому вместо неё — то, что из неё следует для
              бюджета. Покупка валюты идёт в следующем месяце по итогам предыдущего.
            </Source>
          </>
        )}
      </EcCard>

      <EcCard title="Подушка и долг" end={end} units={MONEY_UNITS} sub={(rel) => `ФНБ и госдолг в ОФЗ, ${unitName(rel)}`}>
        {({ from, rel }) => (
          <>
            <TimeChart from={from} till={till} snap={snap} fmt={money(rel)} zero height={260} delta={rel ? 'pp' : 'pct'} lines={[
              { key: 'debt', label: 'Госдолг в ОФЗ', color: colors.refBad, data: u(s.M_DEBT_DOM ?? [], rel), width: 2 },
              { key: 'fnb', label: 'ФНБ всего', color: colors.line1, data: u(s.M_FNB ?? [], rel) },
              { key: 'liq', label: 'ФНБ ликвидный (на счетах в ЦБ)', color: colors.line3, data: u(views.fnbLiquid, rel), width: 2 },
            ]} />
            <Source>
              Минфин. Ликвидная часть ФНБ — средства на счетах в Банке России (юани и золото); остальное вложено в
              акции, облигации и депозиты и быстро потратить его нельзя. Госдолг — внутренний, в ценных бумагах; до
              текущего года — на 1 января, дальше — помесячно. Внешний госдолг меньше и здесь не показан.
            </Source>
          </>
        )}
      </EcCard>

      <EcCard title="Инфляция и ставка" end={end} sub={() => '%, годовых'}>
        {({ from }) => (
          <>
            {market && (
              <TimeChart from={from} till={till} snap={snap} delta="pp" fmt={pctFmt} zero height={260} lines={[
                { key: 'infl', label: 'Инфляция год к году', color: colors.refBad, data: s.M_INFL ?? [], width: 2 },
                { key: 'key', label: 'Ключевая ставка', color: colors.textPrimary, data: market.series.key_rate, sample: true, step: true },
                { key: 'ofz', label: 'ОФЗ 10 лет', color: colors.line1, data: market.series.ofz10, sample: true },
                { key: 'target', label: 'Цель ЦБ', color: colors.line3, data: s.M_INFL_TARGET ?? [], dash: '5 4' },
              ]} />
            )}
            <Source>ЦБ: инфляция — по данным Росстата, на конец месяца; ключевая ставка и кривая ОФЗ — Банк России.</Source>
          </>
        )}
      </EcCard>

      <div className="mo-pair">
        <EcCard title="Что чувствуют люди" end={end} sub={() => 'инфляция, %'}>
          {({ from }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} delta="pp" fmt={pctFmt} zero height={240} lines={[
                { key: 'obs', label: 'Ощущаемая', color: colors.line6, data: s.M_INFL_OBS ?? [], width: 2 },
                { key: 'exp', label: 'Ожидаемая через год', color: colors.line4, data: s.M_INFL_EXP ?? [] },
                { key: 'infl', label: 'Официальная', color: colors.refBad, data: s.M_INFL ?? [], dash: '4 3' },
              ]} />
              <Source>ЦБ, опрос населения «инФОМ»: медианные оценки. Ожидания людей — то, на что смотрит ЦБ, решая о ставке.</Source>
            </>
          )}
        </EcCard>
        <EcCard title="Настроения" end={end} units={REBASE_UNITS('пункты')}
          sub={(rel) => (rel ? 'индекс потребительских настроений, % от начала периода' : 'индекс потребительских настроений, пункты')}>
          {({ from, rel }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} delta="abs" fmt={(v) => ru(v, 0)} height={240} legend={false} rebase={rel} lines={[
                { key: 'csi', label: 'Индекс настроений', color: colors.line1, data: s.M_CSI ?? [], width: 2 },
              ]} />
              <Source>ЦБ, «инФОМ»: оценка людьми своего положения, экономики и момента для крупных покупок. Выше — увереннее.</Source>
            </>
          )}
        </EcCard>
      </div>

      <div className="mo-pair">
        <EcCard title="Кредит и деньги" end={end} sub={() => 'рост за год, %'}>
          {({ from }) => (
            <>
              {market && (
                <TimeChart from={from} till={till} snap={snap} fmt={pctFmt} height={240} delta="pp" lines={[
                  { key: 'corp', label: 'Кредиты компаниям', color: colors.line1, data: s.M_CREDIT_CORP ?? [], width: 2 },
                  { key: 'hh', label: 'Кредиты людям', color: colors.line6, data: s.M_CREDIT_HH ?? [], width: 2 },
                  { key: 'm2', label: 'Денежная масса М2', color: colors.line3, data: s.M_M2 ?? [] },
                  { key: 'key', label: 'Ключевая ставка', color: colors.textPrimary, data: market.series.key_rate, sample: true, step: true, dash: '4 3' },
                ]} />
              )}
              <Source>
                ЦБ. Кредит, растущий быстрее инфляции при высокой ставке, значит, что спрос на деньги не гаснет —
                ЦБ это читает как довод держать ставку. Резкое торможение кредита компаниям — первый признак, что
                ставка начала душить инвестиции.
              </Source>
            </>
          )}
        </EcCard>
        <EcCard title="Доходы людей" end={end} sub={() => 'рост за год, %'}>
          {({ from }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} fmt={pctFmt} height={240} delta="pp" lines={[
                { key: 'inc', label: 'Медианный доход (опрос ЦБ)', color: colors.line3, data: views.incomeGrowth, width: 2 },
                { key: 'infl', label: 'Инфляция', color: colors.refBad, data: s.M_INFL ?? [], dash: '4 3' },
              ]} />
              <Source>
                ЦБ, «инФОМ»: медиана располагаемого дохода на человека, по ответам людей; сравниваются средние за
                три месяца, иначе ряд прыгает. Зелёная выше красной — доходы обгоняют цены. Это не Росстат, а
                самооценка — но она есть каждый месяц, а реальных зарплат Росстата с сервера не достать.
              </Source>
            </>
          )}
        </EcCard>
      </div>

      <div className="mo-pair">
        <EcCard title="Курсы валют" end={end} units={REBASE_UNITS('₽')}
          sub={(rel) => (rel ? 'изменение от начала периода, %' : '₽, официальный курс ЦБ')}>
          {({ from, rel }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} monthly={false} rebase={rel} fmt={(v) => ru(v, 0)} fmtR={(v) => ru(v, 1)} height={240} lines={[
                { key: 'usd', label: 'Доллар', color: colors.line3, data: s.USDRUB ?? [], width: 2 },
                { key: 'eur', label: 'Евро', color: colors.line1, data: s.EURRUB ?? [] },
                { key: 'cny', label: rel ? 'Юань' : 'Юань (правая шкала)', color: colors.refBad, data: s.CNYRUB ?? [], axis: 'r' },
              ]} />
              <Source>ЦБ, курсы на конец недели.</Source>
            </>
          )}
        </EcCard>
        <EcCard title="Нефть Brent" end={end} units={REBASE_UNITS('$ и ₽')}
          sub={(rel) => (rel ? 'изменение от начала периода, %' : 'за баррель')}>
          {({ from, rel }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} monthly={false} rebase={rel} fmt={(v) => `$${ru(v, 0)}`} fmtR={(v) => ru(v, 0)} height={240} lines={[
                { key: 'brent', label: 'в долларах', color: colors.textPrimary, data: s.BRENT ?? [], width: 2 },
                { key: 'rub', label: rel ? 'в рублях' : 'в рублях (правая шкала)', color: colors.line4, data: views.brentRub, axis: 'r' },
              ]} />
              <Source>FRED (Brent spot), курс ЦБ. Российская Urals дешевле на дисконт — бюджет считает налоги от неё.</Source>
            </>
          )}
        </EcCard>
      </div>

      <div className="mo-pair">
        <EcCard title="Платёжный баланс" end={end} sub={() => 'за квартал, млрд $'}>
          {({ from }) => (
            <>
              <Legend items={[
                { label: 'Счёт текущих операций', color: colors.line3 },
                { label: 'Экспорт товаров', color: colors.line1 },
                { label: 'Импорт товаров', color: colors.refBad },
              ]} />
              <PeriodBars
                rows={views.bopRows.filter((r) => (r.date as string) >= (from ?? '') && (showAll || !lastQuarter || (r.date as string) <= lastQuarter))}
                bars={[{ key: 'ca', label: 'Счёт текущих операций', color: colors.line3 }]}
                lines={[{ key: 'exp', label: 'Экспорт товаров', color: colors.line1 }, { key: 'imp', label: 'Импорт товаров', color: colors.refBad }]}
                signColors={{ pos: colors.line3, neg: colors.refBad }}
                snapLabel={showAll ? snapQuarter : null} fmt={(v) => ru(v, 0)} height={240} />
              <Source>ЦБ. Счёт текущих операций — сколько валюты страна заработала за вычетом потраченной: экспорт минус импорт, доходы и переводы.</Source>
            </>
          )}
        </EcCard>
        <EcCard title="Международные резервы" end={end} units={REBASE_UNITS('млрд $')}
          sub={(rel) => (rel ? 'изменение от начала периода, %' : 'на конец месяца, млрд $')}>
          {({ from, rel }) => (
            <>
              <TimeChart from={from} till={till} snap={snap} rebase={rel} fmt={(v) => ru(v, 0)} zero={rel ? undefined : true} height={240} lines={[
                { key: 'res', label: 'Всего', color: colors.line1, data: s.M_RES ?? [], width: 2 },
                { key: 'gold', label: 'в т. ч. золото', color: colors.line4, data: s.M_RES_GOLD ?? [] },
              ]} />
              <Source>ЦБ. Около 300 млрд $ из них с 2022 года заморожены за рубежом — в цифре они остаются.</Source>
            </>
          )}
        </EcCard>
      </div>

      <EcCard title="Рост и занятость" end={end} defaultRange="all" sub={() => 'по годам, %'}>
        {({ fromYear }) => (
          <>
            <Legend items={[{ label: 'Рост ВВП', color: colors.line3 }, { label: 'Безработица', color: colors.line1 }]} />
            <PeriodBars
              rows={views.gdpRows.filter((r) => (r.year as number) >= fromYear && (showAll || lastYear === null || (r.year as number) <= lastYear))}
              bars={[{ key: 'growth', label: 'Рост ВВП', color: colors.line3 }]}
              lines={[{ key: 'unemp', label: 'Безработица', color: colors.line1 }]}
              signColors={{ pos: colors.line3, neg: colors.refBad }}
              snapLabel={showAll ? snapYear : null} fmt={(v) => ru(v, 0)} height={240} />
            <Source>
              Всемирный банк (по данным Росстата), годовые. Квартальных рядов Росстата с нашего сервера не достать —
              сайт его не отвечает; годовых для общей картины хватает.
            </Source>
          </>
        )}
      </EcCard>
    </div>
  );
}
