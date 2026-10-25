import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  fetchValuationSummary,
  getCompanySeries,
  getCompanyValuation,
  type CompanySeriesOut,
  type CompanyValuationOut,
  type SeriesYear,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { formatPerShare } from '../utils/perShare';
import { sandboxMultiple, type Sandbox } from '../utils/sandboxValuation';
import InfoTip from './InfoTip';
import './ValuationTab.css';

/**
 * Вкладка «Оценка»: как получилась опорная стоимость.
 *
 * Оценка — это нормальная прибыль, умноженная на множитель. Вкладка идёт
 * ровно в этом порядке: сверху формула с подставленными числами, ниже —
 * откуда взялось каждое из двух чисел, потом чувствительность к ставке и
 * проверки, которые оценку подтверждают или ставят под сомнение.
 *
 * Прежде здесь стояли два блока, повторявшие друг друга, с двумя
 * переключателями окна и таблицей ставок, где множитель справедливой стоял
 * рядом с опорной, — строка не перемножалась. Теперь окно одно на всю
 * вкладку, и каждое число выводится из соседних.
 */

const WINDOWS = [3, 5, 7, 10];

/** Мера прибыли, ключ ряда на графике и имя лестницы в расчёте. */
const MEASURES = [
  { ladder: 'прибыль', key: 'eps', label: 'Прибыль', title: 'Прибыль на акцию' },
  { ladder: 'деньги', key: 'fcf_per_share', label: 'Денежный поток', title: 'Денежный поток на акцию' },
  { ladder: 'прибыль владельца', key: 'owner_earnings_per_share', label: 'Прибыль владельца', title: 'Прибыль владельца' },
] as const;

type Measure = (typeof MEASURES)[number];

const NORMAL_TITLE: Record<string, string> = {
  'прибыль': 'Нормальная прибыль на акцию',
  'деньги': 'Нормальный денежный поток на акцию',
  'прибыль владельца': 'Нормальная прибыль владельца',
};

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    .replace('-', '−');

/** Ставка: круглая — без дробей, живая (16,44) — с сотыми. */
const rate = (value: number) => ru(value, Number.isInteger(value) ? 0 : 2);

/** Рубли на акцию: у дорогой бумаги копейки — шум, у копеечной — вся цена. */
const rub = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : `${Math.abs(value) >= 100 ? ru(value) : formatPerShare(value)} ₽`;

const pct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined ? '—' : `${ru(value, digits)}%`;

const signed = (share: number) => `${share >= 0 ? '+' : '−'}${ru(Math.abs(share) * 100)}%`;

const years = (n: number) => {
  const tens = n % 100;
  const ones = n % 10;
  if (tens >= 11 && tens <= 14) return `${n} лет`;
  if (ones === 1) return `${n} год`;
  if (ones >= 2 && ones <= 4) return `${n} года`;
  return `${n} лет`;
};

/** Причина из API — со строчной и с точкой в числах; здесь она предложение. */
const sentence = (text: string) => {
  const t = text.trim()
    .replace(/(\d)\.(\d)/g, '$1,$2')
    .replace(/(^|[\s(])-(\d)/g, '$1−$2');
  if (!t) return t;
  const capital = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?…]$/.test(capital) ? capital : `${capital}.`;
};

/** Круглый шаг сетки: 1, 2, 2,5, 5 × 10ⁿ. */
function niceStep(raw: number): number {
  if (raw <= 0 || !Number.isFinite(raw)) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10;
  return nice * power;
}

// ─── График нормальной прибыли ────────────────────────────────────────────

interface EarningsChartProps {
  points: SeriesYear[];
  measure: Measure;
  from: number | null;
  till: number | null;
  trend: { value: number; slope?: number; first_year?: number; last_year?: number } | null;
  average: number | null;
}

/**
 * Столбики по годам, а не сглаженная линия: у годовых данных нет ничего
 * между точками, и кривая, перелетающая через провал 2020 года, рисовала бы
 * величины, которых не было. Годы окна подсвечены — из них и сложена оценка.
 */
function EarningsChart({ points, measure, from, till, trend, average }: EarningsChartProps) {
  const n = points.length;
  const values = points.map((p) => (p[measure.key] as number | null) ?? null);
  const trendStart = trend && trend.slope !== undefined && trend.first_year !== undefined && trend.last_year !== undefined
    ? trend.value - trend.slope * (trend.last_year - trend.first_year)
    : null;
  const known = values.filter((v): v is number => v !== null);
  const extremes = [...known, 0, ...(trendStart !== null ? [trendStart] : []),
    ...(trend ? [trend.value] : []), ...(average !== null ? [average] : [])];
  const rawMax = Math.max(...extremes);
  const rawMin = Math.min(...extremes);
  const step = niceStep((rawMax - rawMin) / 3 || 1);
  const top = Math.ceil(rawMax / step) * step || step;
  const bottom = Math.floor(rawMin / step) * step;
  const H = 220;
  const W = n * 10;
  const y = (v: number) => (H * (top - v)) / (top - bottom);
  const ticks: number[] = [];
  for (let v = bottom; v <= top + step / 2; v += step) ticks.push(v);

  const index = (year: number | undefined | null) =>
    year === undefined || year === null ? -1 : points.findIndex((p) => p.year === year);
  const firstIdx = index(from);
  const lastIdx = index(till);
  const inWindow = (i: number) => firstIdx >= 0 && lastIdx >= 0 && i >= firstIdx && i <= lastIdx;
  const trendFrom = index(trend?.first_year);
  const trendTill = index(trend?.last_year);
  const label = (p: SeriesYear) => (p.ltm_label ? 'LTM' : String(p.year));

  return (
    <div className="vt-chart">
      <div className="vt-chart-axis" aria-hidden>
        {ticks.map((t) => (
          <span key={t} style={{ top: `${(y(t) / H) * 100}%` }}>{ru(t)}</span>
        ))}
      </div>
      <div className="vt-chart-field">
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
          role="img" aria-label={`${measure.title} по годам`}
        >
          {firstIdx >= 0 && lastIdx >= 0 && (
            <rect className="vt-chart-window" x={firstIdx * 10} y={0}
              width={(lastIdx - firstIdx + 1) * 10} height={H} />
          )}
          {ticks.map((t) => (
            <line key={t} className={t === 0 ? 'vt-chart-zero' : 'vt-chart-grid'}
              x1={0} x2={W} y1={y(t)} y2={y(t)} vectorEffect="non-scaling-stroke" />
          ))}
          {values.map((v, i) => (v === null ? null : (
            <rect
              key={points[i].year}
              className={inWindow(i) ? 'vt-bar vt-bar--window' : 'vt-bar'}
              x={i * 10 + 1.8}
              width={6.4}
              y={y(Math.max(v, 0))}
              height={Math.max(Math.abs(y(v) - y(0)), 0.6)}
            >
              <title>{`${label(points[i])}: ${rub(v)}`}</title>
            </rect>
          )))}
          {average !== null && firstIdx >= 0 && lastIdx >= 0 && (
            <line className="vt-chart-average" x1={firstIdx * 10} x2={(lastIdx + 1) * 10}
              y1={y(average)} y2={y(average)} vectorEffect="non-scaling-stroke" />
          )}
          {trend && trendStart !== null && trendFrom >= 0 && trendTill >= 0 && (
            <line className="vt-chart-trend" x1={trendFrom * 10 + 5} x2={trendTill * 10 + 5}
              y1={y(trendStart)} y2={y(trend.value)} vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {trend && trendTill >= 0 && (
          <span className="vt-chart-mark" style={{ top: `${(y(trend.value) / H) * 100}%` }}>
            {ru(trend.value)}
          </span>
        )}
        <div className="vt-chart-years" aria-hidden>
          {points.map((p, i) => ((n - 1 - i) % 3 === 0 ? (
            <span key={p.year} style={{ left: `${((i + 0.5) / n) * 100}%` }}>{label(p)}</span>
          ) : null))}
        </div>
      </div>
    </div>
  );
}

// ─── Проверки ─────────────────────────────────────────────────────────────

type CheckTone = 'pass' | 'warn' | 'fail' | 'none';

interface Check {
  tone: CheckTone;
  title: string;
  detail?: string;
}

const TRAP_TITLE: Record<string, string> = {
  deep_discount: 'Рынок платит меньше половины капитала',
  retention_leak: 'Удержанная прибыль не доходит до капитала',
};

function buildChecks(data: CompanyValuationOut): Check[] {
  const checks: Check[] = [];
  const safety = data.safety;

  if (safety?.earnings_yield != null && safety.risk_free_rate != null && safety.yield_spread != null) {
    // С отделённой кассой отдача — бизнеса к цене бизнеса: процент с депозитов
    // и сама касса из сравнения с облигацией вынесены вместе.
    const subject = data.business_price ? 'Прибыль бизнеса к его цене' : 'Прибыль к цене';
    const basis = data.business_price
      ? ` Цена бизнеса — ${rub(data.business_price)}: цена минус касса ${rub(data.net_cash_per_share)}.`
      : '';
    checks.push(safety.yield_spread >= 0
      ? {
        tone: 'pass',
        title: `${subject} ${pct(safety.earnings_yield)} — выше ОФЗ на ${ru(safety.yield_spread, 1)} п.п.`,
        detail: 'Акция должна давать больше облигации, гл. 14.' + basis,
      }
      : {
        tone: 'fail',
        title: `${subject} ${pct(safety.earnings_yield)} — ниже ОФЗ ${pct(safety.risk_free_rate)}`,
        detail: 'Облигация даёт больше и без риска.' + basis,
      });
  }

  const priced = data.priced_in;
  if (priced && priced.growth_affordable !== null) {
    checks.push(priced.demanding
      ? {
        tone: 'warn',
        title: `Рынок ждёт роста ${pct(priced.growth_priced_in)} в год, компания способна на ${pct(priced.growth_affordable)}`,
        detail: 'Цена держится на вере в рост, которого в отчётах пока нет.',
      }
      : {
        tone: 'pass',
        title: `Рынок ждёт роста ${pct(priced.growth_priced_in)} в год, компания способна на ${pct(priced.growth_affordable)}`,
        detail: 'В цену не заложено ничего сверх того, что бизнес вытягивает сам.',
      });
  }

  for (const trap of safety?.traps ?? []) {
    checks.push({ tone: 'warn', title: TRAP_TITLE[trap.kind] ?? 'Признак ловушки стоимости', detail: sentence(trap.reason) });
  }

  const replacement = safety?.replacement;
  if (replacement && replacement.ratio > 1.2) {
    checks.push({
      tone: 'warn',
      title: `Оценка по заработку в ${ru(replacement.ratio, 1)} раза выше баланса`,
      detail: `${rub(replacement.value_per_share)} против ${rub(replacement.book_value_per_share)} балансовой стоимости на акцию.`,
    });
  }

  // Два признака ловушки, которых нет среди проверок выше: остальные три
  // (дисконт, утечка удержанного, капитал против заработка) уже показаны.
  for (const sign of data.trap_signs ?? []) {
    if (sign.kind === 'persistent_discount' || sign.kind === 'low_payout') {
      checks.push({ tone: 'warn', title: sign.title, detail: sign.detail ? sentence(sign.detail) : undefined });
    }
  }

  if (data.denominator) {
    checks.push({ tone: 'warn', title: 'Отдача держится на малом капитале', detail: sentence(data.denominator.reason) });
  }
  if (data.molodovsky?.artifact && data.molodovsky.reason) {
    checks.push({ tone: 'warn', title: 'Прибыль последнего года — провал, а не норма', detail: sentence(data.molodovsky.reason) });
  }
  if (data.structure?.reason && data.structure.verdict !== 'ok') {
    checks.push({ tone: 'warn', title: 'Структура капитала', detail: sentence(data.structure.reason) });
  }
  for (const warning of data.band?.warnings ?? []) {
    checks.push({ tone: 'warn', title: sentence(warning) });
  }

  const ncav = safety?.ncav;
  if (ncav) {
    checks.push(ncav.passes
      ? { tone: 'pass', title: 'Цена ниже чистых оборотных активов', detail: 'Компания проходит тест net-net, гл. 15.' }
      : {
        tone: 'none',
        title: ncav.per_share < 0 ? 'Чистые оборотные активы отрицательны' : 'Цена выше чистых оборотных активов',
        detail: 'Как net-net по гл. 15 компания не подходит.',
      });
  }
  return checks;
}

// ─── Песочница ────────────────────────────────────────────────────────────

/** Ползунок на месте значения: само значение и, мелко, исходное. */
function SandboxSlider({ label, value, base, min, max, step, fmt, onChange }: {
  label: string;
  value: number;
  base: number;
  min: number;
  max: number;
  step: number;
  fmt: (v: number) => string;
  onChange: (v: number) => void;
}) {
  const changed = Math.abs(value - base) > step / 2;
  return (
    <span className="vt-slider">
      <span className="vt-slider-top">
        <input
          type="range"
          min={Math.min(min, base)}
          max={Math.max(max, base)}
          step={step}
          value={value}
          aria-label={label}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        <b>{fmt(value)}</b>
      </span>
      <small className={changed ? 'is-changed' : undefined}>
        {changed
          ? <button type="button" onClick={() => onChange(base)} title="Вернуть исходное значение">было {fmt(base)} ↺</button>
          : 'исходное'}
      </small>
    </span>
  );
}

// ─── Вкладка ──────────────────────────────────────────────────────────────

/**
 * Шкала под таблицей ставок: где цена среди оценок.
 *
 * Одна ось, на ней: зелёная полоса — три мерила заработка (от низшего к
 * высшему), серые засечки — опорная при других ставках из таблицы над шкалой,
 * оранжевая черта — опорная сейчас, точка — цена. Справедливой здесь нет: она
 * часто выходит за полосу и растягивает шкалу ради числа, которое не про запас
 * прочности. Шкала отвечает на один вопрос — при какой ставке цена окажется
 * ниже опорной.
 *
 * Все подписи под осью — опорная, цена и края полосы — раскладываются одним
 * проходом по строкам, чтобы ни одна не легла на другую; засечки ставок
 * подписаны над осью серым, отдельно от оранжевой опорной.
 */
function RateScale({ low, high, price, reference, rates }: {
  low: number | null;
  high: number | null;
  price: number | null;
  reference: number | null;
  rates: { rate: number; reference: number; now: boolean }[];
}) {
  // Ширина шкалы — чтобы разводить подписи по строкам по их настоящей ширине.
  const box = React.useRef<HTMLDivElement | null>(null);
  // Пока вкладка скрыта (телефон), ширина нулевая — тогда берём оценку по
  // экрану: шкала идёт почти во всю его ширину.
  const guess = () => (typeof window !== 'undefined' && window.innerWidth < 761 ? window.innerWidth - 60 : 600);
  const [width, setWidth] = React.useState(guess);
  React.useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const measure = () => setWidth(el.clientWidth || guess());
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const values = [low, high, price, reference, ...rates.map((r) => r.reference)]
    .filter((v): v is number => v !== null && Number.isFinite(v) && v > 0);
  if (values.length < 2 || price === null) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Поля по краям — под половину подписи, чтобы крайняя метка не прилипала к
  // краю, а её подпись не вылезала за него.
  const pad = 4;
  const at = (v: number) => pad + ((v - min) / (max - min || 1)) * (100 - 2 * pad);
  const half = (text: string, px = 7.2) => ((text.length * px + 10) / 2 / width) * 100;

  // Засечки ставок. Ниже какой-то ставки множитель упирается в потолок, и
  // оценки при 13, 10 и 8% совпадают — такие сливаются в одну «≤ 13%».
  // Засечка, почти совпавшая с опорной сейчас (16% при нынешних 16,7%), не
  // рисуется: две черты рядом читались как одна жирная с подписью «16%».
  const refX = reference === null ? null : at(reference);
  const scenarios: { x: number; label: string; first: number; ref: number }[] = [];
  [...rates].filter((r) => !r.now).sort((a, b) => b.rate - a.rate).forEach((r) => {
    const prev = scenarios[scenarios.length - 1];
    if (prev && Math.abs(r.reference - prev.ref) <= prev.ref * 0.005) {
      prev.label = `≤ ${rate(prev.first)}%`;
      return;
    }
    scenarios.push({ x: at(r.reference), label: `${rate(r.rate)}%`, first: r.rate, ref: r.reference });
  });
  let lastRateEdge = -100;
  const ticks = scenarios
    .filter((t) => refX === null || Math.abs(t.x - refX) * width / 100 >= 18)
    .sort((a, b) => a.x - b.x)
    .map((t) => {
      const h = half(t.label, 6.6);
      const show = t.x - h >= lastRateEdge;
      if (show) lastRateEdge = t.x + h;
      return { ...t, show };
    });

  // Подписи под осью. Порядок — по важности: опорная, потом цена, края
  // полосы — что останется. Каждая — в первую строку, где она
  // не пересекается ни с одной уже положенной.
  // Края полосы — второстепенные: их числа есть в таблице «Три мерила», так
  // что край, которому нет места в первой строке, просто не подписывается.
  type Label = { key: string; x: number; text: string; cls: string; minor?: boolean };
  const wanted: Label[] = [];
  if (reference !== null) {
    wanted.push({ key: 'ref', x: at(reference), text: `опорная ${rub(reference)}`, cls: 'vt-scale-lab--ref' });
  }
  wanted.push({ key: 'price', x: at(price), text: `цена ${rub(price)}`, cls: 'vt-scale-lab--price' });
  if (low !== null && high !== null) {
    wanted.push({ key: 'low', x: at(low), text: rub(low), cls: 'vt-scale-lab--band', minor: true });
    wanted.push({ key: 'high', x: at(high), text: rub(high), cls: 'vt-scale-lab--band', minor: true });
  }
  const rows: [number, number][][] = [[], [], []];
  const placed = wanted.flatMap((l) => {
    const h = half(l.text);
    const x = Math.min(100 - h, Math.max(h, l.x));
    const span: [number, number] = [x - h, x + h];
    const row = rows.findIndex((taken) => taken.every(([a, b]) => span[1] <= a || span[0] >= b));
    if (row < 0 || (l.minor && row > 0)) return [];
    rows[row].push(span);
    return [{ ...l, x, row }];
  });
  const rowsUsed = Math.max(1, ...placed.map((l) => l.row + 1));

  return (
    <div className="vt-scale" aria-label="Цена на шкале оценок" ref={box}>
      <div className="vt-scale-rates">
        {ticks.filter((t) => t.show).map((t) => (
          <span key={t.label} className="vt-scale-rate" style={{ left: `${t.x}%` }}>{t.label}</span>
        ))}
      </div>
      <div className="vt-scale-field">
        <span className="vt-scale-track" />
        {low !== null && high !== null && (
          <span className="vt-scale-band" style={{ left: `${at(low)}%`, width: `${at(high) - at(low)}%` }} />
        )}
        {ticks.map((t) => (
          <span key={t.label} className="vt-scale-tick" style={{ left: `${t.x}%` }}
            title={`При ОФЗ ${t.label} опорная ${rub(t.ref)}`} />
        ))}
        {refX !== null && <span className="vt-scale-mark--ref" style={{ left: `${refX}%` }} />}
        <span className="vt-scale-price" style={{ left: `${at(price)}%` }} />
      </div>
      <div className="vt-scale-labels" style={{ height: rowsUsed * 17 }}>
        {placed.map((l) => (
          <span key={l.key} className={`vt-scale-lab ${l.cls}`} style={{ left: `${l.x}%`, top: l.row * 17 }}>
            {l.text}
          </span>
        ))}
      </div>
      <div className="vt-scale-legend">
        {low !== null && high !== null && <span><i className="vt-scale-key vt-scale-key--band" />три мерила заработка</span>}
        {ticks.length > 0 && <span><i className="vt-scale-key vt-scale-key--tick" />опорная при другой ставке ОФЗ</span>}
      </div>
    </div>
  );
}

export default function ValuationTab({ companyId }: { companyId: number }) {
  const [window, setWindow] = useState(7);
  const [measureKey, setMeasureKey] = useState<Measure['ladder'] | null>(null);
  const [sandbox, setSandbox] = useState<Sandbox | null>(null);
  const enabled = Number.isFinite(companyId) && companyId > 0;

  const { data: detail, isLoading: detailLoading, error } = useQuery<CompanyValuationOut>({
    queryKey: ['company-valuation', companyId, window],
    queryFn: () => getCompanyValuation(companyId, window),
    enabled,
  });
  const { data: summary } = useQuery<ValuationSummaryOut>({
    queryKey: ['valuation-summary', companyId, window],
    queryFn: () => fetchValuationSummary(companyId, window),
    staleTime: 10 * 60 * 1000,
    enabled,
  });
  const { data: series } = useQuery<CompanySeriesOut>({
    queryKey: ['company-series', companyId, window],
    queryFn: () => getCompanySeries(companyId, window),
    enabled,
  });

  const measures = useMemo(
    () => MEASURES.filter((m) => detail?.averages?.[m.ladder] !== undefined || detail?.trends?.[m.ladder]),
    [detail],
  );

  // Окно не может быть длиннее истории: у компании с пятью годами отчётов
  // «средняя за десять лет» — та же пятилетняя, только с чужой подписью.
  const historyYears = detail?.history_years ?? null;
  const allowed = (w: number) => historyYears === null || w <= historyYears;
  const longest = WINDOWS.filter(allowed).pop() ?? WINDOWS[0];
  if (historyYears !== null && !allowed(window) && window !== longest) {
    setWindow(longest);
  }

  const windowSwitch = (
    <div className="vt-window" role="group" aria-label="Окно усреднения прибыли">
      <span className="vt-window-label">окно усреднения:</span>
      {WINDOWS.map((w, i) => (
        <React.Fragment key={w}>
          {i > 0 && <span className="vt-window-sep" aria-hidden>·</span>}
          <button
            type="button"
            className={w === window ? 'vt-window-btn is-on' : 'vt-window-btn'}
            aria-pressed={w === window}
            disabled={!allowed(w)}
            title={allowed(w) ? undefined : `История отчётов — ${years(historyYears ?? 0)}: окно длиннее не набирается`}
            onClick={() => setWindow(w)}
          >
            {years(w)}
          </button>
        </React.Fragment>
      ))}
    </div>
  );

  const head = (
    <header className="vt-head">
      <h2 className="cd-section-title">Как получилась оценка</h2>
      {windowSwitch}
    </header>
  );

  if (detailLoading) return <section className="vt">{head}<div className="vt-state">Считаем оценку…</div></section>;
  if (error || !detail) {
    const reason = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return <section className="vt">{head}<div className="vt-state">{reason ?? 'Не удалось посчитать оценку.'}</div></section>;
  }
  if (!detail.available || !detail.band || detail.band.refused) {
    return (
      <section className="vt">
        {head}
        <div className="vt-state">
          {sentence(detail.band?.reason ?? detail.reason ?? 'Оценка не считается: не хватает данных.')}
        </div>
      </section>
    );
  }

  const band = detail.band;
  const penalty = band.penalty?.total ?? 0;
  const riskFree = detail.assumption?.risk_free_rate ?? null;
  const premium = detail.assumption?.risk_premium ?? null;
  const required = riskFree !== null && premium !== null ? riskFree + premium + penalty : null;
  const headline = summary?.headline;
  const ladderName = headline?.ladder ?? 'прибыль';
  const ladderMeasure = MEASURES.find((m) => m.ladder === ladderName) ?? MEASURES[0];
  const normal = headline?.normal_earnings ?? band.ladders.find((l) => l.name === ladderName)?.normal_per_share ?? null;
  const reference = headline?.reference ?? detail.safety?.reference ?? null;
  const fair = headline?.value ?? null;
  // Касса, отделённая от бизнеса, сидит в опорной и справедливой рубль за
  // рубль. Множитель — только бизнеса: без вычета кассы деление дало бы у
  // ЛУКОЙЛа 4,57 вместо 3,99 и «потолок», которого не было.
  const cash = band.net_cash ?? 0;
  const multiple = reference !== null && normal ? (reference - cash) / normal : band.multiple_low;
  const fairMultiple = fair !== null && normal ? (fair - cash) / normal : band.multiple_high;
  const price = detail.price ?? null;
  const margin = headline?.margin ?? detail.safety?.value_margin ?? null;
  const trendOf = (name: string) => detail.trends?.[name] ?? null;
  const ladderTrend = trendOf(ladderName);
  const basisText = band.basis === 'trend' && ladderTrend?.first_year && ladderTrend?.last_year
    ? `тенденция за ${ladderTrend.first_year}–${ladderTrend.last_year}${ladderTrend.capped ? ', срезана по лучшему году' : ''}`
    : `средняя за ${years(window)}`;
  const others = (summary?.windows ?? [])
    .filter((w) => w.window !== window && allowed(w.window) && !w.refused && w.reference !== null);

  const measure = MEASURES.find((m) => m.ladder === measureKey)
    ?? (measures.includes(ladderMeasure) ? ladderMeasure : measures[0] ?? MEASURES[0]);
  const measureTrend = trendOf(measure.ladder);
  const measureAverage = detail.averages?.[measure.ladder] ?? null;
  const windowSpan = series?.averages?.[measure.key] ?? null;

  // Формула множителя проверяется прямо здесь: если потолок множителя его
  // подрезал, равенство «выплата ÷ (K − g)» не выполнится — так и надо сказать.
  const payoutShare = detail.payout !== null && detail.payout !== undefined ? detail.payout / 100 : null;
  const growth = band.growth ?? 0;
  const isEpv = band.method === 'epv';
  const formulaMultiple = isEpv
    ? (required ? 100 / required : null)
    : payoutShare !== null && required !== null && required - growth > 0
      ? payoutShare / ((required - growth) / 100)
      : null;
  const capped = formulaMultiple !== null && multiple !== null && Math.abs(formulaMultiple - multiple) > 0.05;

  const checks = buildChecks(detail);
  const rates = summary?.rates ?? [];
  const nowRate = summary?.assumption?.risk_free_rate ?? riskFree;
  const rateMultiples = rates.map((r) => (r.reference !== null && r.normal_earnings ? (r.reference - cash) / r.normal_earnings : null));
  const rateCapped = rateMultiples.length > 1
    && rateMultiples[rateMultiples.length - 1] !== null
    && rateMultiples[rateMultiples.length - 1] === rateMultiples[rateMultiples.length - 2];

  // ── Расчётный лист: строки с номерами, операции на полях ──
  //
  // В песочнице те же строки становятся ползунками. Считается тем же путём,
  // что и на сервере: множитель гл. 32 с потолком 8, надбавка за риск
  // сохраняется в доходностях. Ничего не сохраняется — выход возвращает
  // нашу оценку как есть.
  const base: Sandbox = {
    normal: normal ?? 0,
    riskFree: riskFree ?? 0,
    premium: premium ?? 0,
    penalty,
    growth,
    payout: detail.payout ?? 0,
  };
  const vals = sandbox ?? base;
  const sandboxed = sandbox !== null ? sandboxMultiple(vals, isEpv) : null;
  const shownRequired = sandbox ? vals.riskFree + vals.premium + vals.penalty : required;
  const shownMultiple = sandboxed ? sandboxed.reference : multiple;
  const shownReference = sandboxed && sandboxed.reference !== null ? vals.normal * sandboxed.reference + cash : reference;
  const shownFair = sandboxed && sandboxed.fair !== null ? vals.normal * sandboxed.fair + cash : fair;
  const shownMargin = sandbox
    ? (shownReference !== null && shownReference > 0 && price !== null ? (shownReference - price) / shownReference : null)
    : margin;
  const set = (key: keyof Sandbox) => (value: number) =>
    setSandbox((s) => (s ? { ...s, [key]: value } : s));
  const normalMax = Math.max(base.normal * 2, 1);

  type Line = {
    name: string;
    note?: string;
    noteTitle?: string;
    value: string;
    op?: string;
    kind?: 'sub' | 'total' | 'margin';
    edit?: { key: keyof Sandbox; min: number; max: number; step: number; fmt: (v: number) => string };
  };
  const groups: { title: string; lines: Line[] }[] = [];
  const retention = detail.payout !== null && detail.payout !== undefined ? 100 - detail.payout : null;
  const growthNote = band.growth_source === 'удержание' && band.growth_roe != null && retention !== null
    ? `отдача ${pct(band.growth_roe)} × удержание ${pct(retention)}`
      + (band.growth_capped ? ` = ${pct(band.growth_uncapped)}, срезан до ${pct(growth)}` : '')
    : band.growth_capped ? `${band.growth_source ?? ''}, срезан с ${pct(band.growth_uncapped)}` : band.growth_source ?? '';
  const growthTitle = band.growth_roe_source === 'нормальная прибыль к капиталу' && detail.stability
    ? `Отдача — нормальная прибыль к нынешнему капиталу, а не медиана за годы (${pct(detail.stability.median)}): `
      + 'медиана помнит лучшие годы, а растёт компания от того капитала, что есть сейчас.'
    : undefined;
  const pctFmt = (v: number) => pct(v);
  const ppFmt = (v: number) => ru(v, 2).replace(/,?0+$/, '') || '0';

  groups.push({
    title: 'Прибыль',
    lines: [{
      name: NORMAL_TITLE[ladderName] ?? 'Нормальная прибыль на акцию',
      note: cash ? `${basisText}, без процентов на кассу` : basisText,
      value: rub(vals.normal),
      edit: { key: 'normal', min: 0, max: normalMax, step: niceStep(normalMax / 200), fmt: (v) => rub(v) },
    }],
  });
  const showPenalty = penalty > 0 || sandbox !== null;
  const mult: Line[] = [
    {
      name: 'Доходность ОФЗ',
      note: detail.assumption?.risk_free_source === 'допущения'
        ? 'по допущениям года: кривой ОФЗ за месяц нет'
        : '10 лет, средняя за месяц по кривой Мосбиржи',
      noteTitle: detail.assumption?.risk_free_note ?? undefined,
      value: pct(vals.riskFree),
      edit: { key: 'riskFree', min: 4, max: 25, step: 0.25, fmt: pctFmt },
    },
    {
      name: 'Премия за риск акций',
      value: ru(vals.premium, 1),
      op: '+',
      edit: { key: 'premium', min: 0, max: 12, step: 0.25, fmt: ppFmt },
    },
  ];
  if (showPenalty) {
    mult.push({
      name: 'Надбавка за риск',
      note: band.penalty?.notes?.length ? sentence(band.penalty.notes.join('; ')).replace(/\.$/, '') : 'за неровность заработка',
      value: ru(vals.penalty, 1),
      op: '+',
      edit: { key: 'penalty', min: 0, max: 6, step: 0.25, fmt: ppFmt },
    });
  }
  const requiredLine = 2 + (showPenalty ? 3 : 2);
  mult.push({
    name: 'Требуемая доходность',
    note: `стр. ${Array.from({ length: requiredLine - 2 }, (_, i) => i + 2).join(' + ')}`,
    value: pct(shownRequired),
    op: '=',
    kind: 'sub',
  });
  if (isEpv) {
    mult.push({
      name: 'Множитель',
      note: `1 ÷ стр. ${requiredLine} — выплат для формулы роста нет`,
      value: shownMultiple !== null ? ru(shownMultiple, 2) : '—',
      op: '=',
      kind: 'sub',
    });
  } else {
    const growthLine = requiredLine + 1;
    const payoutLine = requiredLine + 2;
    mult.push({
      name: 'Рост',
      note: sandbox ? 'сколько компания растёт на то, что оставляет себе' : growthNote,
      noteTitle: sandbox ? undefined : growthTitle,
      value: pct(vals.growth),
      op: '−',
      edit: { key: 'growth', min: -5, max: 15, step: 0.25, fmt: pctFmt },
    });
    mult.push({
      name: 'Доля прибыли акционерам',
      note: sandbox
        ? 'дивиденды и выкуп к прибыли'
        : detail.payout_buyback !== null && detail.payout_buyback !== undefined
          ? `за ${years(window)}: дивиденды ${pct(detail.payout_dividends)}, выкуп ${pct(detail.payout_buyback)}`
          : `за ${years(window)}, дивиденды к прибыли`,
      value: pct(vals.payout),
      edit: { key: 'payout', min: 0, max: 100, step: 1, fmt: (v) => pct(v, 0) },
    });
    const multNote = sandbox
      ? sandboxed?.problem ?? (sandboxed?.capped ? 'упёрся в потолок 8' : `стр. ${payoutLine} ÷ (стр. ${requiredLine} − стр. ${growthLine})`)
      : `стр. ${payoutLine} ÷ (стр. ${requiredLine} − стр. ${growthLine})`
        + (capped && formulaMultiple !== null ? ` = ${ru(formulaMultiple, 2)}, ограничен потолком` : '');
    mult.push({
      name: 'Множитель',
      note: multNote,
      value: shownMultiple !== null ? ru(shownMultiple, 2) : '—',
      op: '=',
      kind: 'sub',
    });
  }
  groups.push({ title: 'Множитель', lines: mult });
  const multipleLine = 1 + mult.length;
  const cashLines: Line[] = cash ? [{
    name: 'Чистая касса на акцию',
    note: 'деньги минус долг — по номиналу, без множителя',
    value: rub(cash),
    op: '+',
  }] : [];
  const referenceLine = multipleLine + cashLines.length + 1;
  groups.push({
    title: sandbox ? 'Итог в песочнице' : 'Итог',
    lines: [
      ...cashLines,
      {
        name: 'Опорная стоимость',
        note: sandbox && reference !== null
          ? `исходная — ${rub(reference)}`
          : `стр. 1 × стр. ${multipleLine}` + (cash ? ` + стр. ${multipleLine + 1}` : ''),
        value: rub(shownReference),
        op: '=',
        kind: 'total',
      },
      { name: 'Цена сегодня', value: rub(price) },
      {
        name: 'Запас прочности',
        note: `(стр. ${referenceLine} − стр. ${referenceLine + 1}) ÷ стр. ${referenceLine}`,
        value: shownMargin === null ? '—' : shownMargin < -1 ? `×${ru(1 - shownMargin, 1)}` : signed(shownMargin),
        kind: 'margin',
      },
    ],
  });
  let lineNo = 0;
  const marginTone = shownMargin === null ? '' : shownMargin >= 0.15 ? 'vt-good' : shownMargin < 0 ? 'vt-bad' : 'vt-warn';

  return (
    <section className="vt">
      {head}

      <div className="vt-grid">
        {/* ── Расчётный лист ──────────────────────────────────────────── */}
        <div className={`vt-sheet${sandbox ? ' is-sandbox' : ''}`}>
          <div className="vt-sandbox-bar">
            {sandbox ? (
              <>
                <span className="vt-sandbox-title">Песочница: двигайте допущения и сравнивайте. Ничего не сохраняется.</span>
                <span className="vt-sandbox-actions">
                  <button type="button" className="vt-sandbox-btn" onClick={() => setSandbox({ ...base })}>Вернуть исходные</button>
                  <button type="button" className="vt-sandbox-btn vt-sandbox-btn--main" onClick={() => setSandbox(null)}>Выйти</button>
                </span>
              </>
            ) : (
              <button
                type="button"
                className="vt-sandbox-btn"
                onClick={() => setSandbox({ ...base })}
                title="Подставить свои допущения и посмотреть, как изменится оценка. Ничего не сохраняется."
              >
                Попробовать свои допущения
              </button>
            )}
          </div>
          <table className="vt-ws">
            <tbody>
              {groups.map((g) => (
                <React.Fragment key={g.title}>
                  <tr className="vt-ws-group"><td colSpan={4}>{g.title}</td></tr>
                  {g.lines.map((l) => {
                    lineNo += 1;
                    return (
                      <tr key={l.name} className={l.kind ? `vt-ws-${l.kind}` : undefined}>
                        <td className="vt-ws-no">{lineNo}</td>
                        <td className="vt-ws-name">
                          {l.name}
                          {l.note && <small title={l.noteTitle}>{l.note}</small>}
                        </td>
                        <td className="vt-ws-op">{l.op ?? ''}</td>
                        <td className={`vt-ws-value${l.kind === 'margin' ? ` ${marginTone}` : ''}${sandbox && l.edit ? ' vt-ws-value--edit' : ''}`}>
                          {sandbox && l.edit ? (
                            <SandboxSlider
                              label={l.name}
                              value={sandbox[l.edit.key]}
                              base={base[l.edit.key]}
                              min={l.edit.min}
                              max={l.edit.max}
                              step={l.edit.step}
                              fmt={l.edit.fmt}
                              onChange={set(l.edit.key)}
                            />
                          ) : l.value}
                        </td>
                      </tr>
                    );
                  })}
                </React.Fragment>
              ))}
            </tbody>
          </table>
          <p className="vt-note">
            {sandbox
              ? <>Без надбавки за риск — <b>{rub(shownFair)}</b>. Расчёт не сохраняется; оценка на сайте — {rub(reference)}.</>
              : penalty > 0 && fair !== null && fairMultiple !== null
                ? <>Без надбавки за риск множитель {ru(fairMultiple, 2)} и стоимость <b>{rub(fair)}</b> — это справедливая; опорная осторожнее.</>
                : <>Надбавки за риск нет — опорная совпадает со справедливой.</>}
            {!sandbox && others.length > 0 && (
              <>
                {' '}Другие окна:{' '}
                {others.map((w, i) => (
                  <React.Fragment key={w.window}>
                    {i > 0 && ' · '}
                    {years(w.window)} — <b>{rub(w.reference)}</b>
                  </React.Fragment>
                ))}.
              </>
            )}
          </p>
        </div>

        <div className="vt-side">
          {/* ── Откуда прибыль ─────────────────────────────────────────── */}
          <div className="vt-block vt-block--earnings">
            <div className="vt-block-head">
              <h3>
                Откуда {rub(normal)}
                <InfoTip label="Как получена прибыль на акцию">
                  {band.basis === 'trend'
                    ? `${measure.title} по отчётам. Берём тренд, а не среднюю${measureAverage !== null ? ` (${rub(measureAverage)})` : ''}: у растущей компании средняя занижена.`
                    : `${measure.title} по отчётам, средняя за окно — тренда не набралось.`}
                  {measureTrend?.capped && ' Тренд не выше лучшего года.'}
                  {series?.years?.some((y) => y.ltm_label) && ` Последний столбик — ${series.years[series.years.length - 1].ltm_label}.`}
                  {measure.ladder === 'прибыль' && ' Прибыль с разовыми статьями.'}
                  {cash ? ' В годах с чистой кассой из ряда вычтены проценты на депозиты: их доход заменён самой кассой в итоге.' : null}
                </InfoTip>
              </h3>
              {measures.length > 1 && (
                <div className="vt-pills" role="group" aria-label="Мера прибыли">
                  {measures.map((m) => (
                    <button key={m.ladder} type="button" className={m === measure ? 'is-on' : undefined}
                      aria-pressed={m === measure} onClick={() => setMeasureKey(m.ladder)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {series?.years?.length ? (
              <EarningsChart
                points={series.years}
                measure={measure}
                from={windowSpan?.first_year ?? measureTrend?.first_year ?? null}
                till={windowSpan?.last_year ?? measureTrend?.last_year ?? null}
                trend={band.basis === 'trend' ? measureTrend : null}
                average={measureAverage}
              />
            ) : (
              <div className="vt-state">Ряда по годам нет.</div>
            )}
            <div className="vt-keys">
              <span><i className="vt-key-bar" />годы окна</span>
              {band.basis === 'trend' && measureTrend && <span><i className="vt-key-trend" />тенденция → {rub(measureTrend.value)}</span>}
              {measureAverage !== null && <span><i className="vt-key-average" />средняя {rub(measureAverage)}</span>}
            </div>
          </div>

          {/* ── Ставка — под графиком, на месте пустого поля ─────────────── */}
          <div className="vt-block vt-block--rates">
            <h3>
              Если ставка ОФЗ будет другой
              <InfoTip label="Что показывает таблица">
                Прибыль та же, меняется множитель{cash ? ', касса прибавлена к опорной' : ''}. Зелёным — запас от трети, как требует Грэм.
                {rateCapped && ' Ниже множитель упирается в потолок — дальше стоимость не растёт.'}
              </InfoTip>
            </h3>
            <table className="vt-mini">
              <thead>
                <tr><th>ОФЗ</th><th>множ.</th><th>опорная</th><th>запас</th></tr>
              </thead>
              <tbody>
                {rates.map((r, i) => {
                  const now = nowRate !== null && Math.abs(r.risk_free_rate - nowRate) < 0.01;
                  const rowMultiple = rateMultiples[i];
                  const tone = r.margin === null ? '' : r.margin >= 1 / 3 ? 'vt-good' : r.margin < 0 ? 'vt-bad' : '';
                  return (
                    <tr key={r.risk_free_rate} className={now ? 'is-now' : undefined}>
                      <td>{rate(r.risk_free_rate)}%{now && ' · сейчас'}</td>
                      <td>{r.refused || rowMultiple === null ? '—' : ru(rowMultiple, 2)}</td>
                      <td>{r.refused ? '—' : rub(r.reference)}</td>
                      <td className={tone}>{r.margin === null ? '—' : signed(r.margin)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <RateScale
              low={band.low}
              high={band.high}
              price={price}
              reference={reference}
              rates={rates.filter((r) => !r.refused && r.reference !== null).map((r) => ({
                rate: r.risk_free_rate,
                reference: r.reference as number,
                now: nowRate !== null && Math.abs(r.risk_free_rate - nowRate) < 0.01,
              }))}
            />
          </div>
        </div>
      </div>

      <div className="vt-bottom">
        {/* ── Три мерила ────────────────────────────────────────────────── */}
        <div className="vt-block">
          <h3>
            Три мерила заработка
            <InfoTip label="Что такое три мерила">
              {band.low !== null && band.high !== null && <>Полоса оценки {rub(band.low)} – {rub(band.high)}. </>}
              В опорную идёт {ladderMeasure.label.toLowerCase()}.
              {band.net_cash ? (
                <> Касса отдельно от бизнеса: заработок в лестницах — без процентов на депозиты,
                  а чистая касса {rub(band.net_cash)} на акцию прибавлена рубль за рубль.</>
              ) : null}
              {band.asset_lift !== null && band.asset_lift !== 1 && ' К оценке по потоку добавлена треть избыточных активов (гл. 34).'}
            </InfoTip>
          </h3>
          <table className="vt-mini vt-mini--measures">
            <tbody>
              {band.ladders.map((l) => {
                const m = MEASURES.find((x) => x.ladder === l.name);
                return (
                  <tr key={l.name} className={l.name === ladderName ? 'is-now' : undefined}>
                    <td>{m?.label ?? l.name}</td>
                    <td className="vt-measure-calc" title={`средняя за ${years(window)} — ${rub(detail.averages?.[l.name] ?? null)}`}>
                      {rub(l.normal_per_share)} × {ru(l.multiple, 2)}
                      {band.net_cash ? <> + {rub(band.net_cash)}</> : null}
                    </td>
                    <td title={l.asset_note ?? undefined}>{rub(l.adjusted ?? l.value)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* ── Проверки ──────────────────────────────────────────────────── */}
        <div className="vt-block">
          <h3>Проверки</h3>
          {checks.length > 0 ? (
            <ul className="vt-checks">
              {checks.map((c) => (
                <li key={c.title} className={`vt-check vt-check--${c.tone}`}>
                  <span className="vt-check-mark" aria-hidden>
                    {c.tone === 'pass' ? '✓' : c.tone === 'fail' ? '✗' : c.tone === 'warn' ? '!' : '–'}
                  </span>
                  <span>
                    {c.title}
                    {c.detail && <small>{c.detail}</small>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="vt-state">Проверять нечего: не хватает данных.</div>
          )}
        </div>
      </div>

      <footer className="vt-foot">
        Ставка: {detail.assumption?.risk_free_note ?? `ОФЗ ${pct(riskFree)}`}. Премия за риск {pct(premium, 0)} — допущение {detail.assumption?.year} года.
        {detail.history_years ? ` История отчётов — ${years(detail.history_years)}.` : ''}
        {' '}Метод — {band.method_label}. <Link to="/valuation">Подробно о методе</Link>
        <p className="vt-disclaimer">
          Расчёт по отчётности, а не прогноз цены. Не является индивидуальной
          инвестиционной рекомендацией.
        </p>
      </footer>
    </section>
  );
}
