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
    checks.push(safety.yield_spread >= 0
      ? {
        tone: 'pass',
        title: `Прибыль к цене ${pct(safety.earnings_yield)} — выше ОФЗ на ${ru(safety.yield_spread, 1)} п.п.`,
        detail: 'Акция должна давать больше облигации, гл. 14.',
      }
      : {
        tone: 'fail',
        title: `Прибыль к цене ${pct(safety.earnings_yield)} — ниже ОФЗ ${pct(safety.risk_free_rate)}`,
        detail: 'Облигация даёт больше и без риска.',
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

function CheckIcon({ tone }: { tone: CheckTone }) {
  const path = tone === 'pass' ? 'M5 12l5 5 9-10' : tone === 'fail' ? 'M6 6l12 12M18 6L6 18'
    : tone === 'warn' ? 'M12 6v8M12 18h.01' : 'M6 12h12';
  return (
    <svg className={`vt-check-icon vt-check-icon--${tone}`} width="18" height="18" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

// ─── Вкладка ──────────────────────────────────────────────────────────────

export default function ValuationTab({ companyId }: { companyId: number }) {
  const [window, setWindow] = useState(7);
  const [measureKey, setMeasureKey] = useState<Measure['ladder'] | null>(null);
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

  const windowSwitch = (
    <div className="vt-window">
      <div className="vt-segmented" role="group" aria-label="Окно усреднения прибыли">
        {WINDOWS.map((w) => (
          <button key={w} type="button" className={w === window ? 'is-on' : undefined}
            aria-pressed={w === window} onClick={() => setWindow(w)}
          >
            {years(w)}
          </button>
        ))}
      </div>
      <span className="vt-window-hint">за сколько лет усредняется прибыль</span>
    </div>
  );

  const head = (
    <header className="vt-head">
      <div>
        <h2>Как получилась оценка</h2>
        <p>Нормальная прибыль на акцию, умноженная на множитель. Ниже — откуда каждое из двух чисел.</p>
      </div>
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
  const multiple = reference !== null && normal ? reference / normal : band.multiple_low;
  const fairMultiple = fair !== null && normal ? fair / normal : band.multiple_high;
  const price = detail.price ?? null;
  const margin = headline?.margin ?? detail.safety?.value_margin ?? null;
  const trendOf = (name: string) => detail.trends?.[name] ?? null;
  const ladderTrend = trendOf(ladderName);
  const basisText = band.basis === 'trend' && ladderTrend?.first_year && ladderTrend?.last_year
    ? `по линии тенденции за ${ladderTrend.first_year}–${ladderTrend.last_year}`
    : `средняя за ${years(window)}`;
  const others = (summary?.windows ?? []).filter((w) => w.window !== window && !w.refused && w.reference !== null);

  const measure = MEASURES.find((m) => m.ladder === measureKey)
    ?? (measures.includes(ladderMeasure) ? ladderMeasure : measures[0] ?? MEASURES[0]);
  const measureTrend = trendOf(measure.ladder);
  const measureAverage = detail.averages?.[measure.ladder] ?? null;
  const windowSpan = series?.averages?.[measure.key] ?? null;

  // Формула множителя проверяется прямо здесь: если потолок множителя его
  // подрезал, равенство «выплата ÷ (K − g)» не выполнится — так и надо сказать.
  const payoutShare = detail.payout !== null && detail.payout !== undefined ? detail.payout / 100 : null;
  const growth = band.growth ?? 0;
  const formulaMultiple = band.method === 'epv'
    ? (required ? 100 / required : null)
    : payoutShare !== null && required !== null && required - growth > 0
      ? payoutShare / ((required - growth) / 100)
      : null;
  const capped = formulaMultiple !== null && multiple !== null && Math.abs(formulaMultiple - multiple) > 0.05;

  const checks = buildChecks(detail);
  const rates = summary?.rates ?? [];
  const nowRate = summary?.assumption?.risk_free_rate ?? riskFree;

  return (
    <section className="vt">
      {head}

      {/* ── Формула ─────────────────────────────────────────────────────── */}
      <div className="vt-card vt-equation">
        <div className="vt-eq-row">
          <div className="vt-eq-term">
            <span className="vt-kicker">{NORMAL_TITLE[ladderName] ?? 'Нормальная прибыль на акцию'}</span>
            <span className="vt-eq-value">{rub(normal)}</span>
            <span className="vt-eq-note">{basisText}</span>
          </div>
          <span className="vt-eq-op" aria-hidden>×</span>
          <div className="vt-eq-term">
            <span className="vt-kicker">Множитель</span>
            <span className="vt-eq-value">{multiple !== null ? ru(multiple, 2) : '—'}</span>
            <span className="vt-eq-note">
              {required !== null ? `при требуемой доходности ${pct(required, 0)}` : band.method_label}
            </span>
          </div>
          <span className="vt-eq-op" aria-hidden>=</span>
          <div className="vt-eq-term vt-eq-term--result">
            <span className="vt-kicker">Опорная стоимость</span>
            <span className="vt-eq-value">{rub(reference)}</span>
            <span className="vt-eq-note">
              {price !== null && margin !== null
                ? Math.abs(margin) < 0.005
                  ? `цена ${rub(price)} — почти вровень`
                  : `цена ${rub(price)} — ${margin < 0 ? `на ${ru(Math.abs(margin) * 100)}% выше` : `на ${ru(margin * 100)}% ниже`}`
                : price !== null ? `цена ${rub(price)}` : ''}
            </span>
          </div>
        </div>
        <div className="vt-eq-foot">
          <span>
            {penalty > 0 && fair !== null && fairMultiple !== null ? (
              <>Без надбавки за риск: {rub(normal)} × {ru(fairMultiple, 2)} = <b>{rub(fair)}</b> — справедливая стоимость.</>
            ) : (
              <>Надбавки за риск нет — опорная совпадает со справедливой.</>
            )}
          </span>
          <span className="vt-eq-disclaimer">
            Это расчёт по формуле и допущениям, а не прогноз цены.
          </span>
          {others.length > 0 && (
            <span>
              Другие окна:{' '}
              {others.map((w, i) => (
                <React.Fragment key={w.window}>
                  {i > 0 && ' · '}
                  {years(w.window)} — <b>{rub(w.reference)}</b>
                </React.Fragment>
              ))}
            </span>
          )}
        </div>
      </div>

      <div className="vt-pair">
        {/* ── Откуда прибыль ────────────────────────────────────────────── */}
        <div className="vt-card">
          <div className="vt-card-head">
            <h3>Откуда нормальная прибыль</h3>
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
            <span><i className="vt-key-bar" />годы в окне</span>
            {band.basis === 'trend' && measureTrend && <span><i className="vt-key-trend" />тенденция {rub(measureTrend.value)}</span>}
            {measureAverage !== null && <span><i className="vt-key-average" />средняя {rub(measureAverage)}</span>}
          </div>
          <p className="vt-text">
            {band.basis === 'trend'
              ? 'Берём тенденцию, а не среднюю: у растущей компании средняя занижает нормальный уровень (гл. 30).'
              : 'Берём среднюю за окно: тенденции по этому ряду не набралось.'}
            {measureTrend?.capped && ' Линия подрезана по историческому максимуму — выше уже достигнутого не берём.'}
            {series?.years?.some((y) => y.ltm_label) && ` Последний столбик — ${series.years[series.years.length - 1].ltm_label}.`}
            {measure.ladder === 'прибыль' && ' Прибыль — как в отчёте, с разовыми статьями: на окне в несколько лет они усредняются сами. Мультипликаторы считаются от прибыли без разовых, поэтому их P/E может отличаться.'}
          </p>
        </div>

        {/* ── Откуда множитель ──────────────────────────────────────────── */}
        <div className="vt-card">
          <div className="vt-card-head"><h3>Откуда множитель</h3></div>
          <div className="vt-formula">
            {band.method === 'epv' ? (
              <>
                <span>Множитель = 1 ÷ требуемая доходность — выплат для формулы роста нет</span>
                <b>{multiple !== null ? ru(multiple, 2) : '—'} = 1 ÷ {pct(required)}</b>
              </>
            ) : (
              <>
                <span>Множитель = выплата ÷ (требуемая доходность − рост)</span>
                <b>
                  {multiple !== null ? ru(multiple, 2) : '—'} = {pct(detail.payout)} ÷ ({pct(required)} − {pct(growth)})
                </b>
                {capped && formulaMultiple !== null && (
                  <span>по формуле {ru(formulaMultiple, 2)}, ограничен потолком</span>
                )}
              </>
            )}
          </div>
          <dl className="vt-rows">
            <div>
              <dt>Требуемая доходность<small>сколько инвестор вправе ждать от акции</small></dt>
              <dd>
                {pct(required)}
                <small>
                  ОФЗ {pct(riskFree, 0)} + премия {pct(premium, 0)}{penalty > 0 ? ` + надбавка ${ru(penalty, 0)} п.п.` : ''}
                </small>
              </dd>
            </div>
            {penalty > 0 && (
              <div>
                <dt>
                  Надбавка за риск
                  <small>{band.penalty?.notes?.length ? sentence(band.penalty.notes.join('; ')) : 'за неровность заработка'}</small>
                </dt>
                <dd className="vt-warn">
                  +{ru(penalty, 0)} п.п.
                  {fair !== null && <small>без неё — справедливая {rub(fair)}</small>}
                </dd>
              </div>
            )}
            {band.method !== 'epv' && (
              <div>
                <dt>Выплата владельцу<small>доля прибыли за {years(window)}, вернувшаяся акционерам</small></dt>
                <dd>
                  {pct(detail.payout)}
                  <small>
                    {detail.payout_buyback !== null && detail.payout_buyback !== undefined
                      ? `дивиденды ${pct(detail.payout_dividends)} + выкуп ${pct(detail.payout_buyback)}`
                      : 'дивиденды к прибыли'}
                  </small>
                </dd>
              </div>
            )}
            {band.method !== 'epv' && (
              <div>
                <dt>Рост<small>сколько компания растёт на то, что оставляет себе</small></dt>
                <dd>
                  {pct(growth)}
                  <small>
                    {band.growth_capped
                      ? `подрезан с ${pct(band.growth_uncapped)}`
                      : band.growth_source === 'удержание' && band.growth_roe != null
                        ? `отдача на капитал ${pct(band.growth_roe)} × (1 − ${pct(detail.payout)})`
                        : band.growth_source ?? ''}
                  </small>
                </dd>
                {band.growth_roe_source === 'нормальная прибыль к капиталу' && detail.stability && (
                  <p className="vt-row-note">
                    Отдача — нормальная прибыль к нынешнему капиталу, а не медиана за годы
                    ({pct(detail.stability.median)}): медиана помнит лучшие годы, а растёт
                    компания от того капитала, что есть сейчас.
                  </p>
                )}
              </div>
            )}
          </dl>
        </div>
      </div>

      <div className="vt-pair">
        {/* ── Ставка ────────────────────────────────────────────────────── */}
        <div className="vt-card">
          <div className="vt-card-head vt-card-head--stack">
            <h3>Если изменится доходность ОФЗ</h3>
            <p>Ставка — самое сильное допущение в расчёте. Прибыль та же, меняется множитель.</p>
          </div>
          <div className="vt-table-scroll">
            <table className="vt-table">
              <thead>
                <tr>
                  <th scope="col">ОФЗ</th>
                  <th scope="col">Множитель</th>
                  <th scope="col">Опорная</th>
                  <th scope="col">Запас к цене</th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r) => {
                  const now = nowRate !== null && Math.abs(r.risk_free_rate - nowRate) < 0.01;
                  const rowMultiple = r.reference !== null && r.normal_earnings ? r.reference / r.normal_earnings : null;
                  const tone = r.margin === null ? '' : r.margin >= 1 / 3 ? 'vt-good' : r.margin < 0 ? 'vt-warn' : '';
                  return (
                    <tr key={r.risk_free_rate} className={now ? 'is-now' : undefined}>
                      <th scope="row">
                        {ru(r.risk_free_rate)}%{now && <span className="vt-now">сейчас</span>}
                      </th>
                      <td>{r.refused || rowMultiple === null ? '—' : ru(rowMultiple, 2)}</td>
                      <td className="vt-strong">{r.refused ? '—' : rub(r.reference)}</td>
                      <td className={tone}>{r.margin === null ? '—' : signed(r.margin)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="vt-note">Зелёным — запас от трети, как требует Грэм.</p>
        </div>

        {/* ── Проверки ──────────────────────────────────────────────────── */}
        <div className="vt-card">
          <div className="vt-card-head"><h3>Проверки оценки</h3></div>
          {checks.length > 0 ? (
            <ul className="vt-checks">
              {checks.map((c) => (
                <li key={c.title}>
                  <CheckIcon tone={c.tone} />
                  <div>
                    <span>{c.title}</span>
                    {c.detail && <small>{c.detail}</small>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="vt-state">Проверять нечего: не хватает данных.</div>
          )}
        </div>
      </div>

      {/* ── Три меры ────────────────────────────────────────────────────── */}
      <div className="vt-card">
        <div className="vt-card-head">
          <h3>Три меры прибыли</h3>
          {band.low !== null && band.high !== null && (
            <span className="vt-card-aside">Полоса оценки: <b>{rub(band.low)} – {rub(band.high)}</b></span>
          )}
        </div>
        <div className="vt-table-scroll">
          <table className="vt-table">
            <thead>
              <tr>
                <th scope="col">Мера</th>
                <th scope="col">Средняя за {years(window)}</th>
                <th scope="col">По тенденции</th>
                <th scope="col">Множитель</th>
                <th scope="col">Оценка</th>
              </tr>
            </thead>
            <tbody>
              {band.ladders.map((l) => {
                const m = MEASURES.find((x) => x.ladder === l.name);
                const t = trendOf(l.name);
                return (
                  <tr key={l.name}>
                    <th scope="row">
                      {m?.title ?? l.name}
                      {l.name === ladderName && <span className="vt-basis">основа опорной</span>}
                    </th>
                    <td className="vt-dim">{rub(detail.averages?.[l.name] ?? null)}</td>
                    <td>
                      {t ? rub(t.value) : '—'}
                      {t?.capped && <small className="vt-dim"> подрезана по максимуму</small>}
                    </td>
                    <td>{ru(l.multiple, 2)}</td>
                    <td className="vt-strong" title={l.asset_note ?? undefined}>{rub(l.adjusted ?? l.value)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {band.asset_lift !== null && band.asset_lift !== 1 && (
          <p className="vt-note">
            Поправка на активы подняла оценку в {ru(band.asset_lift, 2)} раза: по прибыли компания стоит{' '}
            {rub(band.low_by_earnings)}–{rub(band.high_by_earnings)}, в счёт пошли две трети
            балансовой стоимости (гл. 34).
          </p>
        )}
      </div>

      <footer className="vt-foot">
        Допущения на {detail.assumption?.year} год: ОФЗ {pct(riskFree, 0)}, премия за риск {pct(premium, 0)}.
        {detail.history_years ? ` История отчётов — ${years(detail.history_years)}.` : ''}
        {' '}Метод — {band.method_label}. <Link to="/valuation">Подробно о методе</Link>
        <p className="vt-disclaimer">
          Опорная и справедливая стоимость — результат расчёта по отчётности и допущениям о
          ставке и премии за риск, а не прогноз будущей цены акции. Материал не является
          индивидуальной инвестиционной рекомендацией и не призывает покупать или продавать
          ценные бумаги. Решение и его последствия — на стороне инвестора.
        </p>
      </footer>
    </section>
  );
}
