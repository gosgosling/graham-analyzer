import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchPriceHistory, type PriceHistoryOut, type PricePoint } from '../services/prices.api';
import {
  fetchValuationHistory,
  fetchValuationSummary,
  type ValuationHistoryOut,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { useChartColors } from '../contexts/ThemeContext';
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

type Overlay = 'pe' | 'pb';

const OVERLAYS: { key: Overlay; label: string; hint: string }[] = [
  { key: 'pe', label: 'P/E', hint: 'Цена к прибыли на акцию последнего опубликованного отчёта' },
  { key: 'pb', label: 'P/B', hint: 'Цена к балансовой стоимости на акцию' },
];

/**
 * Стоимость поверх цены — рядом по годам, а не горизонталью.
 *
 * Горизонталь по сегодняшнему расчёту сказать может только одно: где акция
 * стоит **сейчас** относительно оценки. Про прошлое она врёт, потому что
 * знает прибыль последнего отчёта и сегодняшнюю ставку. У ЛУКОЙЛа за 2022 год
 * полоса шла 4 691–5 885 при цене 4 072 — акция была дешевле своей тогдашней
 * оценки, и по сегодняшней черте этого не увидеть вовсе.
 *
 * Ряд берётся из обратного теста: за каждый год оценка считается по данным,
 * обрезанным этим годом, и по ключевой ставке того года. Ступенька меняется в
 * день раскрытия отчёта, а не 31 декабря, — до него считать было не по чему.
 */
const VALUES: { key: 'fair' | 'reference'; label: string; hint: string }[] = [
  { key: 'fair', label: 'Справедливая',
    hint: 'Оценка по лестнице прибыли при рыночной премии — верх расчёта того года' },
  { key: 'reference', label: 'Опорная',
    hint: 'Та же лестница с надбавкой за риск — от неё считается запас' },
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
const MAX_POINTS = 1500;

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

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

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

export default function PriceChart({ companyId }: { companyId: number }) {
  const colors = useChartColors();
  const [range, setRange] = useState('5y');
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [shown, setShown] = useState<Set<'fair' | 'reference'>>(new Set());

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

  const { data, isLoading, error } = useQuery<PriceHistoryOut>({
    queryKey: ['price-history', companyId],
    queryFn: () => fetchPriceHistory(companyId),
    staleTime: 30 * 60 * 1000,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const view = useMemo(() => {
    const raw = data?.points ?? [];
    if (!raw.length) return null;

    // Оценка приклеивается к дням цены. Ступень держится до выхода следующего
    // отчёта, поэтому курсор просто едет вперёд вместе с датами — ровно так же,
    // как множители считаются на бэкенде.
    const marks = (history?.years ?? [])
      .filter((y) => !y.refused)
      .sort((a, b) => a.known_from.localeCompare(b.known_from));
    let cursor = -1;
    const all = marks.length === 0 ? raw : raw.map((point) => {
      while (cursor + 1 < marks.length && marks[cursor + 1].known_from <= point.date) {
        cursor += 1;
      }
      const mark = cursor >= 0 ? marks[cursor] : null;
      return {
        ...point,
        fair: mark?.fair ?? null,
        reference: mark?.conservative ?? null,
        basis_valuation: mark?.year ?? null,
      };
    });

    const years = RANGES.find((r) => r.key === range)?.years ?? null;
    let slice = all;
    if (years !== null) {
      const edge = new Date(all[all.length - 1].date);
      edge.setFullYear(edge.getFullYear() - years);
      const iso = edge.toISOString().slice(0, 10);
      const cut = all.filter((p) => p.date >= iso);
      // Окно шире имеющейся истории — показываем то, что есть, а не пустоту.
      if (cut.length > 1) slice = cut;
    }

    const prices = slice.map((p) => p.price);
    const average = prices.reduce((a, b) => a + b, 0) / prices.length;

    // Прореживание — только для отрисовки. Крайние точки сохраняются всегда:
    // без них у линии срезается начало или конец окна.
    const step = Math.ceil(slice.length / MAX_POINTS);
    const thin = step > 1
      ? slice.filter((_, i) => i % step === 0 || i === slice.length - 1)
      : slice;

    const overlayValues = overlay
      ? slice.map((p) => p[overlay]).filter((v): v is number => v !== null && v > 0)
      : [];
    const bounds = multipleBounds(overlayValues);

    // Значения выше потолка вырезаются из отрисовки. Прижимать их к краю
    // нельзя: recharts рисует к границе вертикальный отрезок, и провал
    // прибыли превращается в жёлтый столб во всю высоту поля — ровно то,
    // ради чего потолок и ставился. Обрыв линии честнее: он показывает, что
    // величина ушла за пределы шкалы, а число остаётся в подсказке.
    const points = (overlay && bounds)
      ? thin.map((p) => {
        const value = p[overlay];
        if (value === null || value <= bounds[1]) return p;
        // Ключ удаляется, а не обнуляется. `null` здесь не работает:
        // recharts с `connectNulls={false}` всё равно прочитал его как ноль и
        // увёл линию на дно поля — вместо обрыва получился отвес до нуля при
        // шкале, начинающейся с трёх. Отсутствующий ключ он понимает верно.
        const { [overlay]: _dropped, ...rest } = p;
        return { ...rest, off_scale: value } as unknown as PricePoint;
      })
      : thin;

    return {
      points,
      average,
      min: Math.min(...prices),
      max: Math.max(...prices),
      first: slice[0],
      last: slice[slice.length - 1],
      change: slice[0].price > 0
        ? (slice[slice.length - 1].price - slice[0].price) / slice[0].price
        : null,
      ticks: periodTicks(points, (years ?? 99) >= 3),
      overlayBounds: bounds,
      offScale: overlay && bounds
        ? overlayValues.filter((v) => v > bounds[1]).length
        : 0,
      longRange: (years ?? 99) >= 3,
      thinned: step > 1,
    };
  }, [data, history, range, overlay]);

  if (isLoading) return <div className="pc-state">Загружаем историю цены…</div>;
  if (error) return <div className="pc-state pc-state--error">Не удалось загрузить историю цены</div>;
  if (!view) {
    return (
      <div className="pc-state">
        Истории цены нет. Загрузить: <code>python -m scripts.backfill_price_history {data?.company?.ticker ?? ''}</code>
      </div>
    );
  }

  const overlaySpec = OVERLAYS.find((o) => o.key === overlay);
  // Уровни, которые есть чем нарисовать. Сегодняшняя величина берётся из
  // свода — её видно в подсказке кнопки, — а линия рисуется рядом по годам.
  const levels = (history?.years ?? []).some((y) => !y.refused)
    ? VALUES.map((spec) => ({
      ...spec,
      value: spec.key === 'fair'
        ? valuation?.windows?.find((w) => w.window === valuation.window)?.value ?? null
        : valuation?.safety?.reference ?? null,
    }))
    : [];

  return (
    <section className="pc">
      <header className="pc-head">
        <div className="pc-title">
          <h3>Цена акции</h3>
          <span className="pc-sub">
            {view.first.date} — {view.last.date}
            {view.thinned && ' · прорежено для отрисовки'}
          </span>
        </div>

        <div className="pc-controls">
          {levels.length > 0 && (
            <div className="pc-values" role="group" aria-label="Показать оценку">
              {levels.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  className={`pc-btn pc-btn--value${shown.has(v.key) ? ' is-on' : ''}`}
                  onClick={() => setShown((prev) => {
                    const next = new Set(prev);
                    if (next.has(v.key)) next.delete(v.key); else next.add(v.key);
                    return next;
                  })}
                  title={v.value !== null
                    ? `${v.hint}. Сегодня — ${ru(v.value)} ₽`
                    : v.hint}
                  aria-pressed={shown.has(v.key)}
                >
                  {v.label}
                </button>
              ))}
            </div>
          )}
          <div className="pc-overlays" role="group" aria-label="Наложить множитель">
            {OVERLAYS.map((o) => (
              <button
                key={o.key}
                type="button"
                className={`pc-btn${overlay === o.key ? ' is-on' : ''}`}
                onClick={() => setOverlay(overlay === o.key ? null : o.key)}
                title={o.hint}
                aria-pressed={overlay === o.key}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className="pc-ranges" role="group" aria-label="Период">
            {RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                className={`pc-btn${range === r.key ? ' is-on' : ''}`}
                onClick={() => setRange(r.key)}
                aria-pressed={range === r.key}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="pc-stats">
        <span><b>{ru(view.last.price)} ₽</b> сейчас</span>
        <span className={view.change !== null && view.change >= 0 ? 'pc-up' : 'pc-down'}>
          {view.change === null ? '—'
            : `${view.change >= 0 ? '+' : ''}${ru(view.change * 100, 1)}% за период`}
        </span>
        <span>средняя <b>{ru(view.average)} ₽</b></span>
        <span>коридор {ru(view.min)} — {ru(view.max)} ₽</span>
        {view.last.pe !== null && <span>P/E {ru(view.last.pe, 1)}</span>}
        {view.last.pb !== null && <span>P/B {ru(view.last.pb, 2)}</span>}
      </div>

      <div className="pc-canvas">
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={view.points} margin={{ top: 8, right: overlay ? 52 : 12, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id={`pc-fill-${companyId}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.line1} stopOpacity={0.24} />
                <stop offset="100%" stopColor={colors.line1} stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke={colors.grid} vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: colors.axis, fontSize: 11 }}
              ticks={view.ticks}
              tickFormatter={(v: string) => axisDate(v, view.longRange)}
              interval={0}
              minTickGap={0}
              stroke={colors.grid}
            />
            <YAxis
              yAxisId="price"
              tick={{ fill: colors.axis, fontSize: 11 }}
              tickFormatter={(v: number) => ru(v)}
              domain={['auto', 'auto']}
              width={58}
              stroke={colors.grid}
            />
            {overlay && (
              <YAxis
                yAxisId="mult"
                orientation="right"
                tick={{ fill: colors.line4, fontSize: 11 }}
                tickFormatter={(v: number) => ru(v, v < 10 ? 1 : 0)}
                domain={view.overlayBounds ?? ['auto', 'auto']}
                allowDataOverflow
                width={46}
                stroke={colors.grid}
              />
            )}

            {/* Средняя за период — та величина, относительно которой «дорого»
                и «дёшево» вообще имеют смысл на этом отрезке. */}
            <ReferenceLine
              yAxisId="price"
              y={view.average}
              stroke={colors.axis}
              strokeDasharray="4 4"
              label={{ value: 'средняя', position: 'insideTopLeft', fill: colors.axis, fontSize: 10 }}
            />

            {shown.has('reference') && (
              <Line
                yAxisId="price"
                type="stepAfter"
                dataKey="reference"
                stroke={colors.refBad}
                strokeWidth={1.5}
                strokeDasharray="2 3"
                dot={false}
                connectNulls={false}
                name="Опорная"
                isAnimationActive={false}
              />
            )}
            {shown.has('fair') && (
              <Line
                yAxisId="price"
                type="stepAfter"
                dataKey="fair"
                stroke={colors.line3}
                strokeWidth={1.5}
                strokeDasharray="6 3"
                dot={false}
                connectNulls={false}
                name="Справедливая"
                isAnimationActive={false}
              />
            )}

            <Area
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke={colors.line1}
              strokeWidth={1.6}
              fill={`url(#pc-fill-${companyId})`}
              dot={false}
              activeDot={{ r: 3, stroke: colors.dotStroke, strokeWidth: 1 }}
              name="Цена"
              isAnimationActive={false}
            />

            {overlay && (
              <Line
                yAxisId="mult"
                /* Ломаная, а не сглаженная. Сглаживание здесь не косметика:
                   на пропуске в двести с лишним дней монотонная кривая уходит
                   в перелёт — контрольные точки улетают втрое ниже поля, и
                   получается отвес вместо обрыва. Ломаная между соседями
                   прямая по определению и перелетать ей нечем. */
                type="linear"
                dataKey={overlay}
                stroke={colors.line4}
                strokeWidth={1.4}
                dot={false}
                connectNulls={false}
                name={overlaySpec?.label}
                isAnimationActive={false}
              />
            )}

            <Tooltip
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
                if (label === 'Цена') return [`${ru(num)} ₽`, label];
                if (label === 'Справедливая' || label === 'Опорная') {
                  const basis = (item?.payload as { basis_valuation?: number } | undefined)
                    ?.basis_valuation;
                  return [`${ru(num)} ₽${basis ? ` (расчёт по ${basis} году)` : ''}`, label];
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
                const point = payload?.[0]?.payload as (PricePoint & { off_scale?: number }) | undefined;
                const off = point?.off_scale;
                return off
                  ? `${String(value)} · за шкалой: ${ru(off, 1)}`
                  : String(value);
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {overlay && (
        <p className="pc-note">
          {overlaySpec?.hint}. Шкала ограничена тройной медианой: провал прибыли
          поднимает множитель до сотен, и без ограничения весь остальной ряд сжался бы
          в полоску у нуля.
          {view.offScale > 0 && (
            <> За шкалу ушло {view.offScale} {view.offScale % 10 === 1 && view.offScale % 100 !== 11
              ? 'значение' : 'значений'}: эти дни не нарисованы, и линия проходит
              через них напрямую. Сама величина остаётся в подсказке.</>
          )}
        </p>
      )}
    </section>
  );
}
