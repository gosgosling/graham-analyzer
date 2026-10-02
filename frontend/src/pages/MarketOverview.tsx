import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchMarketOverview, type MarketOverview as Overview, type MarketYear, type SeriesPoint } from '../services/market.api';
import { useChartColors } from '../contexts/ThemeContext';
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

function IndexChart({ data, range }: { data: Overview; range: string }) {
  const colors = useChartColors();
  const years = RANGES.find((r) => r.key === range)?.years ?? null;
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
    // Обе линии от сотни в начале периода: так видно, сколько стало бы
    // из 100 ₽ — с дивидендами и без. Разница линий и есть дивиденды.
    const points = thin(rows.map((r) => ({
      date: r.date,
      imoex: (r.imoex / base.imoex) * 100,
      mcftr: r.mcftr !== null ? (r.mcftr / (base.mcftr as number)) * 100 : null,
    })));
    const last = points[points.length - 1];
    return { points, from: base.date, last };
  }, [data, years]);

  if (!view) return <div className="mo-state">Истории индексов нет.</div>;
  const long = years === null || years >= 5;
  return (
    <>
      <div className="mo-legend">
        <span><i style={{ background: colors.textPrimary }} />Индекс Мосбиржи — {signed(view.last.imoex - 100)}%</span>
        <span><i style={{ background: colors.line3 }} />с дивидендами (MCFTR) — {signed((view.last.mcftr ?? 100) - 100)}%</span>
        <span className="mo-legend-note">100 ₽ с {dotDate(view.from)}</span>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={view.points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
            ticks={periodTicks(view.points.map((p) => p.date), years)} interval={0}
            tickFormatter={(v: string) => axisDate(v, long)} />
          <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={44}
            domain={['auto', 'auto']} tickFormatter={(v: number) => ru(v)} />
          <ReferenceLine y={100} stroke={colors.axis} strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
            itemStyle={{ color: colors.textPrimary }}
            labelFormatter={(v) => dotDate(String(v))}
            formatter={(v, name) => [`${ru(Number(v), 1)} ₽`, name === 'imoex' ? 'без дивидендов' : 'с дивидендами']}
          />
          <Line dataKey="imoex" stroke={colors.textPrimary} strokeWidth={1.4} dot={false} isAnimationActive={false} />
          <Line dataKey="mcftr" stroke={colors.line3} strokeWidth={1.4} dot={false} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}

// ─── Ставки ────────────────────────────────────────────────────────────────

function RatesChart({ data, range }: { data: Overview; range: string }) {
  const colors = useChartColors();
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
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={view} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
            ticks={periodTicks(view.map((p) => p.date), years)} interval={0}
            tickFormatter={(v: string) => axisDate(v, long)} />
          <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={36}
            domain={[0, 'auto']} tickFormatter={(v: number) => `${ru(v)}%`} />
          <Tooltip
            contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
            itemStyle={{ color: colors.textPrimary }}
            labelFormatter={(v) => dotDate(String(v))}
            formatter={(v, name) => [`${ru(Number(v), 2)}%`, names[String(name)] ?? String(name)]}
          />
          <Line type="stepAfter" dataKey="key" stroke={colors.textPrimary} strokeWidth={1.4} dot={false} isAnimationActive={false} />
          <Line dataKey="ofz" stroke={colors.line1} strokeWidth={1.4} dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="rgbi" stroke={colors.line4} strokeWidth={1.2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}

// ─── Премия акций к облигациям ─────────────────────────────────────────────

function PremiumChart({ years }: { years: MarketYear[] }) {
  const colors = useChartColors();
  const rows = years
    .filter((y) => y.premium !== null)
    .map((y) => ({ label: y.year === 'now' ? 'сейчас' : String(y.year), premium: y.premium as number }));
  if (!rows.length) return <div className="mo-state">Не с чем сравнить.</div>;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={rows} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid}
          tickFormatter={(v: string) => (v === 'сейчас' ? v : `’${v.slice(2)}`)} interval={0} />
        <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} width={36}
          tickFormatter={(v: number) => ru(v)} />
        <ReferenceLine y={0} stroke={colors.axis} />
        <Tooltip
          contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: colors.textPrimary, marginBottom: 2 }}
            itemStyle={{ color: colors.textPrimary }}
          formatter={(v) => [`${signed(Number(v))} п.п.`, 'премия к ОФЗ']}
          cursor={{ fill: colors.grid }}
        />
        <Bar dataKey="premium" isAnimationActive={false} radius={[2, 2, 0, 0]}>
          {rows.map((r) => (
            <Cell key={r.label} fill={r.premium >= 5 ? colors.line3 : r.premium >= 0 ? colors.line4 : colors.refBad} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
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
