import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchMarketOverview, type MarketOverview as Overview, type MarketYear, type SeriesPoint } from '../services/market.api';
import { useChartColors } from '../contexts/ThemeContext';
import { SpanBand, humanDate } from '../components/PriceSpanLayer';
import { createSpanStore, type SpanStore } from '../components/priceSpanStore';
import '../components/PriceChart.css';
import PeriodChipList from '../components/PeriodChipList';
import { PHONE_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import { useTwoFingerSpan } from '../hooks/useTwoFingerSpan';
import './MarketOverview.css';

/**
 * Раздел «Рынок»: что сейчас с акциями и облигациями — без прогнозов.
 *
 * Главный вопрос Грэма к рынку в целом — сколько акции зарабатывают на рубль
 * цены по сравнению с тем, что без риска платит государство (гл. 3 и 20).
 * Поэтому, кроме индексов и ставок, здесь сводка по годам: P/E рынка,
 * доходность прибыли и её разница с десятилетними ОФЗ.
 */

const RANGES: { key: string; label: string; years: number | null }[] = [
  { key: '1y', label: '1 год', years: 1 },
  { key: '3y', label: '3 года', years: 3 },
  { key: '5y', label: '5 лет', years: 5 },
  { key: '10y', label: '10 лет', years: 10 },
  { key: 'all', label: 'Всё', years: null },
];

/** Больше точек линия не различает, а наведение начинает тормозить. */
const MAX_POINTS = 900;

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace('-', '−');
const signed = (value: number, digits = 1) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${ru(Math.abs(value), digits)}`;
const dotDate = (iso: string) => iso.split('-').reverse().join('.');

function since(years: number | null, last: string): string | null {
  if (years === null) return null;
  const d = new Date(last);
  d.setFullYear(d.getFullYear() - years);
  return d.toISOString().slice(0, 10);
}

function thin<T>(rows: T[]): T[] {
  if (rows.length <= MAX_POINTS) return rows;
  const step = Math.ceil(rows.length / MAX_POINTS);
  return rows.filter((_, i) => i % step === 0 || i === rows.length - 1);
}

/** Последнее значение ряда не позже даты — для ступенчатых рядов. */
function lookup(series: SeriesPoint[]) {
  let i = 0;
  return (day: string): number | null => {
    while (i + 1 < series.length && series[i + 1][0] <= day) i += 1;
    return series.length && series[i][0] <= day ? series[i][1] : null;
  };
}

const axisDate = (iso: string, long: boolean) => {
  const [y, m] = iso.split('-');
  const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  return long ? y : `${months[Number(m) - 1]} ’${y.slice(2)}`;
};

/** Засечки: начало каждого года на длинном отрезке, квартала — на коротком. */
function periodTicks(dates: string[], years: number | null): string[] {
  const out: string[] = [];
  let prev = '';
  for (const d of dates) {
    const month = Number(d.slice(5, 7));
    const key = years === null || years >= 5
      ? d.slice(0, 4)
      : years >= 3 ? `${d.slice(0, 4)}-${Math.floor((month - 1) / 6)}` : `${d.slice(0, 4)}-${Math.floor((month - 1) / 3)}`;
    if (key !== prev) {
      if (prev) out.push(d);
      prev = key;
    }
  }
  return out;
}

function Ranges({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  return (
    <span className="seg" role="radiogroup" aria-label="Период">
      {RANGES.map((r) => (
        <button key={r.key} type="button" role="radio" aria-checked={value === r.key}
          className={value === r.key ? 'seg-btn is-on' : 'seg-btn'} onClick={() => onChange(r.key)}
        >
          {r.label}
        </button>
      ))}
    </span>
  );
}

// ─── Индекс Мосбиржи и он же с дивидендами ─────────────────────────────────

type IndexScale = 'points' | 'rel';
const INDEX_SCALE_KEY = 'ga.market.indexScale';

type IndexPoint = { date: string; imoex: number; mcftr: number | null; imoexRel: number; mcftrRel: number | null };

const pctChange = (from: number, to: number) => (to / from - 1) * 100;

/** Свод по протянутому отрезку: оба индекса, пункты и проценты. */
function IndexSpanSummary({ store, points }: { store: SpanStore; points: IndexPoint[] }) {
  const live = useSyncExternalStore(store.subscribe, store.get, store.get);
  if (!live || live.fromDate === live.toDate) return null;
  const [a, b] = live.fromDate < live.toDate ? [live.fromDate, live.toDate] : [live.toDate, live.fromDate];
  const from = points.find((p) => p.date >= a);
  const to = [...points].reverse().find((p) => p.date <= b);
  if (!from || !to || from.date >= to.date) return null;
  const line = (name: string, x: number | null, y: number | null) => {
    if (x === null || y === null) return null;
    const ch = pctChange(x, y);
    return (
      <span>
        {name} <b>{ru(x)}</b> → <b>{ru(y)}</b>{' '}
        <b className={ch >= 0 ? 'mo-up' : 'mo-down'}>{signed(y - x, 0)} п. · {signed(ch, 2)}%</b>
      </span>
    );
  };
  return (
    <div className="mo-span">
      <span className="mo-span-dates">{humanDate(from.date)} → {humanDate(to.date)}</span>
      {line('IMOEX', from.imoex, to.imoex)}
      {line('MCFTR', from.mcftr, to.mcftr)}
    </div>
  );
}

/**
 * Ось на телефоне — подписи внутри поля, без линии и засечек: так график
 * идёт от края до края экрана, а не теряет по пять сантиметров на оси с двух
 * сторон. Сетка остаётся — по ней и читаются подписи.
 */
const PHONE_AXIS = { mirror: true, axisLine: false, tickLine: false } as const;
/** Высота графиков на телефоне: на 240 пикселях линии сливались в полосу. */
const PHONE_HEIGHT = 280;
/** Подсказка на телефоне — у верхнего края поля, а не под пальцем. */
const PHONE_TIP = { position: { y: 0 } } as const;

function IndexChart({ data, range }: { data: Overview; range: string }) {
  const colors = useChartColors();
  const isPhone = useMediaQuery(PHONE_QUERY);
  const years = RANGES.find((r) => r.key === range)?.years ?? null;
  const [scale, setScaleState] = useState<IndexScale>(() => {
    try { return (window.localStorage.getItem(INDEX_SCALE_KEY) as IndexScale) || 'points'; } catch { return 'points'; }
  });
  const setScale = (next: IndexScale) => {
    setScaleState(next);
    try { window.localStorage.setItem(INDEX_SCALE_KEY, next); } catch { /* приватный режим */ }
  };

  const view = useMemo(() => {
    const imoex = data.series.IMOEX;
    if (!imoex.length) return null;
    const from = since(years, imoex[imoex.length - 1][0]);
    const mcftr = lookup(data.series.MCFTR);
    const rows = imoex
      .filter(([d]) => !from || d >= from)
      .map(([d, v]) => ({ date: d, imoex: v, mcftr: mcftr(d) }));
    const base = rows[0];
    if (!base || base.mcftr === null) return null;
    // Относительный вид — обе линии от сотни в начале периода: так видно,
    // сколько стало бы из 100 ₽ с дивидендами и без. Абсолютный — пункты
    // индексов, у каждого своя ось: MCFTR втрое «выше» IMOEX по шкале.
    const points: IndexPoint[] = thin(rows.map((r) => ({
      date: r.date,
      imoex: r.imoex,
      mcftr: r.mcftr,
      imoexRel: (r.imoex / base.imoex) * 100,
      mcftrRel: r.mcftr !== null ? (r.mcftr / (base.mcftr as number)) * 100 : null,
    })));
    const last = points[points.length - 1];
    return { points, from: base.date, last, base };
  }, [data, years]);

  // Протяжка — как на графике цены компании: состояние вне React, чтобы
  // движение мыши не перерисовывало сам график.
  const spanStore = useRef(createSpanStore()).current;
  const drag = useRef<{ pressed: boolean; fromX: number; fromDate: string } | null>(null);
  const canvas = useRef<HTMLDivElement | null>(null);
  const [band, setBand] = useState({ top: 8, bottom: 24 });
  const measure = useCallback(() => {
    const box = canvas.current;
    const grid = box?.querySelector('.recharts-cartesian-grid');
    if (!box || !grid) return;
    const outer = box.getBoundingClientRect();
    const inner = (grid as SVGGElement).getBoundingClientRect();
    const next = { top: Math.max(0, Math.round(inner.top - outer.top)), bottom: Math.max(0, Math.round(outer.bottom - inner.bottom)) };
    setBand((prev) => (prev.top === next.top && prev.bottom === next.bottom ? prev : next));
  }, []);
  useEffect(() => {
    spanStore.set(null);
    const frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [measure, view, scale, spanStore]);
  useTwoFingerSpan(canvas, view?.points, spanStore, isPhone, measure);

  if (!view) return <div className="mo-state">Истории индексов нет.</div>;
  const long = years === null || years >= 5;
  const rel = scale === 'rel';
  const xOf = (e: unknown) => {
    const x = (e as { clientX?: number } | null)?.clientX;
    const left = canvas.current?.getBoundingClientRect().left ?? 0;
    return typeof x === 'number' ? x - left : null;
  };
  const dateOf = (state: unknown) => {
    const at = (state as { activeLabel?: string | number } | null)?.activeLabel;
    return at === undefined || at === null ? null : String(at);
  };
  const tooltipLabel: Record<string, string> = {
    imoex: 'IMOEX', mcftr: 'MCFTR', imoexRel: 'без дивидендов', mcftrRel: 'с дивидендами',
  };
  return (
    <>
      <div className="mo-index-head">
        <div className="mo-legend">
          <span><i style={{ background: colors.textPrimary }} />IMOEX <b>{ru(view.last.imoex)}</b> — {signed(view.last.imoexRel - 100)}%</span>
          <span><i style={{ background: colors.line3 }} />MCFTR с дивидендами <b>{view.last.mcftr !== null ? ru(view.last.mcftr) : '—'}</b> — {signed((view.last.mcftrRel ?? 100) - 100)}%</span>
          <span className="mo-legend-note">за период с {dotDate(view.from)}</span>
        </div>
        <span className="seg" role="radiogroup" aria-label="Шкала">
          {([['points', 'В пунктах'], ['rel', 'От 100 ₽']] as const).map(([key, label]) => (
            <button key={key} type="button" role="radio" aria-checked={scale === key}
              className={scale === key ? 'seg-btn is-on' : 'seg-btn'} onClick={() => setScale(key)}>{label}</button>
          ))}
        </span>
      </div>
      <div className="mo-canvas" ref={canvas}>
        <SpanBand store={spanStore} top={band.top} bottom={band.bottom} />
        <ResponsiveContainer width="100%" height={isPhone ? PHONE_HEIGHT : 300}>
          <LineChart
            data={view.points}
            margin={isPhone ? { top: 8, right: 0, bottom: 0, left: 0 } : { top: 8, right: rel ? 8 : 4, bottom: 0, left: 0 }}
            onMouseDown={(state, event) => {
              spanStore.set(null);
              measure();
              const x = xOf(event);
              drag.current = { pressed: true, fromX: x ?? 0, fromDate: dateOf(state) ?? '' };
            }}
            onMouseMove={(state, event) => {
              const held = drag.current;
              if (!held?.pressed) return;
              const at = dateOf(state);
              const x = xOf(event);
              if (at === null || x === null) return;
              if (!held.fromDate) { held.fromDate = at; return; }
              spanStore.set({ fromX: held.fromX, toX: x, fromDate: held.fromDate, toDate: at });
            }}
            onMouseUp={() => { if (drag.current) drag.current.pressed = false; }}
            onMouseLeave={() => { if (drag.current) drag.current.pressed = false; }}
            style={{ userSelect: 'none' }}
          >
            <CartesianGrid stroke={colors.grid} vertical={false} />
            <XAxis dataKey="date" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
              ticks={periodTicks(view.points.map((p) => p.date), years)} interval={0}
              tickFormatter={(v: string) => axisDate(v, long)} />
            {rel ? (
              <YAxis yAxisId="l" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={44}
                domain={['auto', 'auto']} tickFormatter={(v: number) => ru(v)}
                {...(isPhone ? { ...PHONE_AXIS, orientation: 'right' as const } : {})} />
            ) : (
              <>
                <YAxis yAxisId="l" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={52}
                  domain={['auto', 'auto']} tickFormatter={(v: number) => ru(v)} {...(isPhone ? PHONE_AXIS : {})} />
                <YAxis yAxisId="r" orientation="right" tick={{ fill: colors.line3, fontSize: 11 }} stroke={colors.grid} width={56}
                  domain={['auto', 'auto']} tickFormatter={(v: number) => ru(v)} {...(isPhone ? PHONE_AXIS : {})} />
              </>
            )}
            {rel && <ReferenceLine yAxisId="l" y={100} stroke={colors.axis} strokeDasharray="3 3" />}
            <Tooltip
              contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
              itemStyle={{ color: colors.textPrimary }}
              labelFormatter={(v) => dotDate(String(v))}
              formatter={(v, name) => [rel ? `${ru(Number(v), 1)} ₽` : `${ru(Number(v), 2)} п.`, tooltipLabel[String(name)] ?? String(name)]}
              {...(isPhone ? PHONE_TIP : {})}
            />
            <Line yAxisId="l" dataKey={rel ? 'imoexRel' : 'imoex'} stroke={colors.textPrimary} strokeWidth={1.4} dot={false} isAnimationActive={false} />
            <Line yAxisId={rel ? 'l' : 'r'} dataKey={rel ? 'mcftrRel' : 'mcftr'} stroke={colors.line3} strokeWidth={1.4} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <IndexSpanSummary store={spanStore} points={view.points} />
      {isPhone
        ? <p className="mo-hint mo-hint--touch">Коснитесь графика двумя пальцами — покажем изменение за отрезок.</p>
        : <p className="mo-hint">Зажмите кнопку мыши и проведите по графику — покажет изменение за отрезок.</p>}
    </>
  );
}

// ─── Ставки ────────────────────────────────────────────────────────────────

function RatesChart({ data, range }: { data: Overview; range: string }) {
  const colors = useChartColors();
  const isPhone = useMediaQuery(PHONE_QUERY);
  const years = RANGES.find((r) => r.key === range)?.years ?? null;
  const view = useMemo(() => {
    const days = data.series.RGBI_yield;
    if (!days.length) return null;
    const from = since(years, days[days.length - 1][0]);
    const key = lookup(data.series.key_rate);
    const ofz = lookup(data.series.ofz10);
    return thin(days
      .filter(([d]) => !from || d >= from)
      .map(([d, y]) => ({ date: d, rgbi: y, key: key(d), ofz: ofz(d) })));
  }, [data, years]);

  if (!view?.length) return <div className="mo-state">Истории ставок нет.</div>;
  const long = years === null || years >= 5;
  const names: Record<string, string> = { key: 'ключевая', ofz: 'ОФЗ 10 лет', rgbi: 'доходность RGBI' };
  return (
    <>
      <div className="mo-legend">
        <span><i style={{ background: colors.textPrimary }} />ключевая ЦБ</span>
        <span><i style={{ background: colors.line1 }} />ОФЗ 10 лет</span>
        <span><i style={{ background: colors.line4 }} />доходность RGBI</span>
      </div>
      <div className="mo-bleed">
      <ResponsiveContainer width="100%" height={isPhone ? PHONE_HEIGHT : 240}>
        <LineChart data={view} margin={isPhone ? { top: 8, right: 0, bottom: 0, left: 0 } : { top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
            ticks={periodTicks(view.map((p) => p.date), years)} interval={0}
            tickFormatter={(v: string) => axisDate(v, long)} />
          <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={36}
            domain={[0, 'auto']} tickFormatter={(v: number) => `${ru(v)}%`}
            {...(isPhone ? { ...PHONE_AXIS, orientation: 'right' as const } : {})} />
          <Tooltip
            contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
            itemStyle={{ color: colors.textPrimary }}
            labelFormatter={(v) => dotDate(String(v))}
            formatter={(v, name) => [`${ru(Number(v), 2)}%`, names[String(name)] ?? String(name)]}
            {...(isPhone ? PHONE_TIP : {})}
          />
          <Line type="stepAfter" dataKey="key" stroke={colors.textPrimary} strokeWidth={1.4} dot={false} isAnimationActive={false} />
          <Line dataKey="ofz" stroke={colors.line1} strokeWidth={1.4} dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="rgbi" stroke={colors.line4} strokeWidth={1.2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      </div>
    </>
  );
}

// ─── Премия акций к облигациям ─────────────────────────────────────────────

function PremiumChart({ years }: { years: MarketYear[] }) {
  const colors = useChartColors();
  const isPhone = useMediaQuery(PHONE_QUERY);
  const rows = years
    .filter((y) => y.premium !== null)
    .map((y) => ({ label: y.year === 'now' ? 'сейчас' : String(y.year), premium: y.premium as number }));
  if (!rows.length) return <div className="mo-state">Не с чем сравнить.</div>;
  return (
    <div className="mo-bleed">
    <ResponsiveContainer width="100%" height={isPhone ? PHONE_HEIGHT : 240}>
      <BarChart data={rows} margin={isPhone ? { top: 16, right: 0, bottom: 0, left: 0 } : { top: 16, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
          tickFormatter={(v: string) => (v === 'сейчас' ? v : `’${v.slice(2)}`)} interval={0} />
        <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={36}
          tickFormatter={(v: number) => ru(v)}
          {...(isPhone ? { ...PHONE_AXIS, orientation: 'right' as const } : {})} />
        <ReferenceLine y={0} stroke={colors.axis} />
        <Tooltip
          contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
            itemStyle={{ color: colors.textPrimary }}
          formatter={(v) => [`${signed(Number(v))} п.п.`, 'премия к ОФЗ']}
          cursor={{ fill: colors.grid }}
          {...(isPhone ? PHONE_TIP : {})}
        />
        <Bar dataKey="premium" isAnimationActive={false} radius={[2, 2, 0, 0]}>
          {rows.map((r) => (
            <Cell key={r.label} fill={r.premium >= 5 ? colors.line3 : r.premium >= 0 ? colors.line4 : colors.refBad} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
    </div>
  );
}

// ─── Оценка рынка по годам ─────────────────────────────────────────────────

type Row = {
  label: string;
  tip?: string;
  value: (y: MarketYear) => string;
  tone?: (y: MarketYear) => string;
};

const pct = (v: number | null, digits = 1) => (v === null ? '—' : `${ru(v, digits)}`);

const ROWS: { group: string; rows: Row[] }[] = [
  {
    group: 'Оценка',
    rows: [
      { label: 'P/E рынка', tip: 'Капитализация всех компаний ÷ их прибыль вместе с убыточными — так считает индекс', value: (y) => ru(y.pe, 1) },
      { label: 'Медианный P/E', tip: 'Середина по прибыльным компаниям: на неё не влияют гиганты', value: (y) => (y.pe_median === null ? '—' : ru(y.pe_median, 1)) },
      { label: 'P/B', tip: 'Капитализация ÷ собственный капитал', value: (y) => (y.pb === null ? '—' : ru(y.pb, 2)) },
      { label: 'Дивидендная доходность, %', tip: 'Взвешенная по капитализации', value: (y) => pct(y.dividend_yield) },
    ],
  },
  {
    group: 'Акции против облигаций',
    rows: [
      { label: 'Доходность прибыли, %', tip: 'Прибыль ÷ капитализация — обратная к P/E', value: (y) => pct(y.earnings_yield) },
      { label: 'ОФЗ 10 лет, %', tip: 'Средняя за год; «сейчас» — средняя за месяц', value: (y) => pct(y.ofz10, 2) },
      {
        label: 'Премия акций, п.п.',
        tip: 'Доходность прибыли минус ОФЗ. Ниже нуля — облигация платит больше, чем акции зарабатывают на рубль цены',
        value: (y) => (y.premium === null ? '—' : signed(y.premium)),
        tone: (y) => (y.premium === null ? '' : y.premium >= 5 ? 'mo-good' : y.premium >= 0 ? 'mo-warn' : 'mo-bad'),
      },
      { label: 'Ключевая ставка, %', tip: 'Средняя за год; «сейчас» — действующая', value: (y) => pct(y.key_rate, 2) },
    ],
  },
  {
    group: 'Охват',
    rows: [
      { label: 'Капитализация, трлн ₽', value: (y) => ru(y.cap_trln, 1) },
      { label: 'Компаний в расчёте', tip: 'Только с проверенными отчётами и без дефектов аудита', value: (y) => String(y.companies) },
    ],
  },
];

function ValuationTable({ years }: { years: MarketYear[] }) {
  const isPhone = useMediaQuery(PHONE_QUERY);
  if (isPhone) {
    // Четырнадцать лет в колонках на телефоне не помещаются: год кнопкой,
    // показатели списком, «сейчас» — первым.
    const ordered = [...years].reverse();
    const byKey = new Map(ordered.map((y) => [String(y.year), y]));
    return (
      <PeriodChipList
        ariaLabel="Год"
        columns={ordered.map((y) => ({ key: String(y.year), label: y.year === 'now' ? 'сейчас' : String(y.year) }))}
        groups={ROWS.map((g) => ({
          key: g.group,
          title: g.group,
          rows: g.rows.map((r) => ({
            key: r.label,
            label: r.label,
            tip: r.tip,
            cell: (col) => {
              const y = byKey.get(col.key);
              if (!y) return null;
              const text = r.value(y);
              // Ячейки «Рынка» — готовые строки («12,3», «−1,4 п.п.»); число
              // для графика достаём из них.
              const num = typeof text === 'string'
                ? Number(text.replace(/\s/g, '').replace('−', '-').replace(',', '.').replace(/[^\d.-].*$/, ''))
                : NaN;
              return { node: text, className: r.tone?.(y) || undefined, value: Number.isFinite(num) && text !== '—' ? num : null };
            },
          })),
        }))}
      />
    );
  }
  return (
    <div className="mo-table-wrap">
      <table className="mo-table" style={{ '--cols': years.length } as React.CSSProperties}>
        <thead>
          <tr>
            <th />
            {years.map((y) => (
              <th key={String(y.year)} className={y.year === 'now' ? 'is-now' : undefined}>
                {y.year === 'now' ? 'сейчас' : y.year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((g) => (
            <React.Fragment key={g.group}>
              <tr className="mo-group"><th colSpan={years.length + 1}><span>{g.group}</span></th></tr>
              {g.rows.map((r) => (
                <tr key={r.label}>
                  <th scope="row" title={r.tip}><span className={r.tip ? 'mo-tip' : undefined}>{r.label}</span></th>
                  {years.map((y) => (
                    <td key={String(y.year)} className={[y.year === 'now' ? 'is-now' : '', r.tone?.(y) ?? ''].filter(Boolean).join(' ') || undefined}>
                      {r.value(y)}
                    </td>
                  ))}
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Страница ──────────────────────────────────────────────────────────────

export default function MarketOverview() {
  const [range, setRange] = useState('5y');
  const [ratesRange, setRatesRange] = useState('5y');
  const { data, isLoading, error } = useQuery({
    queryKey: ['market-overview'],
    queryFn: fetchMarketOverview,
    staleTime: 30 * 60 * 1000,
  });

  if (isLoading) return <div className="mo"><div className="mo-state">Загружаем данные рынка…</div></div>;
  if (error || !data) return <div className="mo"><div className="mo-state">Не удалось загрузить данные рынка.</div></div>;

  const { today } = data;
  const now = data.valuation.find((y) => y.year === 'now') ?? null;
  const last = data.valuation.filter((y) => y.year !== 'now').slice(-1)[0] ?? null;
  const shownYears = data.valuation.filter((y) => y.year === 'now' || (typeof y.year === 'number' && y.year >= 2014));
  const counts = shownYears.map((y) => y.companies);
  const minCount = counts.length ? Math.min(...counts) : 0;
  const maxCount = counts.length ? Math.max(...counts) : 0;
  const imoex = today.IMOEX;
  const mcftr = today.MCFTR;
  const rgbi = today.RGBI;

  // Одна фраза о том, что видно в цифрах ниже, — без советов.
  const lede = now && now.premium !== null && now.ofz10 !== null
    ? `Акции рынка зарабатывают ${ru(now.earnings_yield, 1)}% на рубль цены, десятилетние ОФЗ платят ${ru(now.ofz10, 1)}%: `
      + (now.premium >= 5
        ? `премия за риск акций ${signed(now.premium)} п.п. — широкая.`
        : now.premium >= 0
          ? `премия за риск акций ${signed(now.premium)} п.п. — узкая.`
          : `облигации платят больше на ${ru(Math.abs(now.premium), 1)} п.п.`)
    : null;

  const stat = (label: string, value: string, sub?: React.ReactNode, tone?: string) => (
    <div className="mo-stat">
      <span className="mo-stat-label">{label}</span>
      <span className={`mo-stat-value${tone ? ` ${tone}` : ''}`}>{value}</span>
      {sub && <span className="mo-stat-sub">{sub}</span>}
    </div>
  );
  const change = (v: number | null | undefined, what: string) =>
    v === null || v === undefined ? null : (
      <span className={v >= 0 ? 'mo-up' : 'mo-down'}>{signed(v)}% {what}</span>
    );

  return (
    <div className="mo">
      <section className="mo-card mo-head">
        <div className="mo-head-top">
          <div>
            {/* Мистер Рынок — притча Грэма из гл. 8 «Разумного инвестора»:
                партнёр, который каждый день называет цену, то восторженную,
                то паническую. В меню раздел зовётся просто «Рынок». */}
            <h1>Мистер Рынок</h1>
            {lede && <p className="mo-lede">{lede}</p>}
          </div>
          <span className="mo-asof">данные на {dotDate(imoex?.date ?? data.as_of)}</span>
        </div>
        <div className="mo-stats">
          {stat('Индекс Мосбиржи', imoex ? ru(imoex.value, 0) : '—', change(imoex?.year, 'за год'))}
          {stat('С дивидендами, MCFTR', mcftr ? ru(mcftr.value, 0) : '—', change(mcftr?.year, 'за год'))}
          {stat('Гособлигации, RGBI', rgbi?.yield != null ? `${ru(rgbi.yield, 2)}%` : '—',
            rgbi ? <>доходность; индекс {ru(rgbi.value, 2)}, {change(rgbi.year, 'за год')}</> : undefined)}
          {stat('ОФЗ 10 лет', data.ofz10.month_average !== null ? `${ru(data.ofz10.month_average, 2)}%` : '—', 'средняя за месяц')}
          {stat('Ключевая ставка', data.key_rate.value !== null ? `${ru(data.key_rate.value, 2)}%` : '—',
            data.key_rate.date ? `ЦБ, на ${dotDate(data.key_rate.date)}` : undefined)}
          {stat('P/E рынка', now ? ru(now.pe, 1) : '—',
            now ? <>медианный {now.pe_median !== null ? ru(now.pe_median, 1) : '—'}{last ? `; в ${last.year} — ${ru(last.pe, 1)}` : ''}</> : undefined)}
        </div>
      </section>

      <section className="mo-card">
        <div className="mo-card-head">
          <h2>Индекс Мосбиржи: с дивидендами и без</h2>
          <Ranges value={range} onChange={setRange} />
        </div>
        <IndexChart data={data} range={range} />
        <p className="mo-note">
          MCFTR — с реинвестированными дивидендами, без налога. Разрыв между линиями — дивиденды за период.
        </p>
      </section>

      <div className="mo-pair">
        <section className="mo-card">
          <div className="mo-card-head">
            <h2>Ставки</h2>
            <Ranges value={ratesRange} onChange={setRatesRange} />
          </div>
          <RatesChart data={data} range={ratesRange} />
          <p className="mo-note">
            RGBI — средняя доходность корзины ОФЗ (дюрация {rgbi?.duration_days ? `${ru(rgbi.duration_days / 365, 1)} года` : '—'}).
            ОФЗ 10 лет — точка кривой бескупонной доходности.
          </p>
        </section>
        <section className="mo-card">
          <div className="mo-card-head">
            <h2>Премия акций к ОФЗ</h2>
            <span className="mo-card-sub">доходность прибыли рынка минус ОФЗ 10 лет, п.п.</span>
          </div>
          <PremiumChart years={data.valuation} />
          <p className="mo-note">
            Зелёный — от 5 п.п., жёлтый — до 5, красный — облигации выгоднее.
          </p>
        </section>
      </div>

      <section className="mo-card">
        <div className="mo-card-head">
          <h2>Оценка рынка по годам</h2>
          <span className="mo-card-sub">по компаниям в базе, на конец года</span>
        </div>
        <ValuationTable years={shownYears} />
        <p className="mo-note">
          По {minCount}–{maxCount} компаниям с проверенными отчётами, а не по всему индексу. Ушедшие с биржи
          компании не учтены, поэтому прошлое выглядит чуть лучше, чем было.
        </p>
      </section>
    </div>
  );
}
