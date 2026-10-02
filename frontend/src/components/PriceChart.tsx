import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  fetchPriceHistory, type PriceEvent, type PriceHistoryOut, type PricePoint,
} from '../services/prices.api';
import {
  fetchValuationHistory,
  fetchValuationSummary,
  type ValuationHistoryOut,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { useChartColors } from '../contexts/ThemeContext';
import { fetchOil, type OilOut } from '../services/market.api';
import { formatPerShare } from '../utils/perShare';
import { SpanBand, SpanSummary } from './PriceSpanLayer';
import { createSpanStore } from './priceSpanStore';
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

type Overlay = 'pe' | 'pb' | 'oil';

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

export default function PriceChart({ companyId, oil = false }: { companyId: number; oil?: boolean }) {
  const colors = useChartColors();
  const [range, setRange] = useState('5y');
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  // Нефть: в долларах или рублях; Urals — Brent минус дисконт.
  const [oilRub, setOilRub] = useState(false);
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
    const grid = box?.querySelector('.recharts-cartesian-grid');
    if (!box || !grid) return;
    const outer = box.getBoundingClientRect();
    const inner = (grid as SVGGElement).getBoundingClientRect();
    canvasLeft.current = outer.left;
    const next = {
      top: Math.max(0, Math.round(inner.top - outer.top)),
      bottom: Math.max(0, Math.round(outer.bottom - inner.bottom)),
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

  const { data, isLoading, error } = useQuery<PriceHistoryOut>({
    queryKey: ['price-history', companyId],
    queryFn: () => fetchPriceHistory(companyId),
    staleTime: 30 * 60 * 1000,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const view = useMemo(() => {
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

    // Нефть приклеивается к дням цены так же — последним известным днём:
    // Brent в праздники Мосбиржи торгуется, а в праздники Лондона — нет.
    let base = all;
    if (overlay === 'oil' && oilData?.points.length) {
      const series = oilData.points;
      let j = -1;
      base = all.map((point) => {
        while (j + 1 < series.length && series[j + 1][0] <= point.date) j += 1;
        if (j < 0) return { ...point, oil: null };
        const [, brent, rate] = series[j];
        const usd = brent - (urals ? discount : 0);
        return { ...point, oil: oilRub ? (rate ? usd * rate : null) : usd };
      });
    }

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
    const step = Math.ceil(slice.length / MAX_POINTS);
    const thin = step > 1
      ? slice.filter((_, i) => i % step === 0 || i === slice.length - 1)
      : slice;

    const overlayValues = overlay
      ? slice.map((p) => (p as unknown as Record<string, number | null>)[overlay]).filter((v): v is number => v != null && v > 0)
      : [];
    // У нефти потолка нет: это цена, а не множитель с провалами прибыли.
    const bounds: [number, number] | null = overlay === 'oil'
      ? (overlayValues.length ? [Math.floor(Math.min(...overlayValues) * 0.9), Math.ceil(Math.max(...overlayValues) * 1.05)] : null)
      : multipleBounds(overlayValues);

    // Значения выше потолка вырезаются из отрисовки. Прижимать их к краю
    // нельзя: recharts рисует к границе вертикальный отрезок, и провал
    // прибыли превращается в жёлтый столб во всю высоту поля — ровно то,
    // ради чего потолок и ставился. Обрыв линии честнее: он показывает, что
    // величина ушла за пределы шкалы, а число остаётся в подсказке.
    const points = (overlay && overlay !== 'oil' && bounds)
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

    // Причины пропусков множителя в видимом окне. Пропуск без причины читается
    // как сбой данных; причин же ровно три, и все — про компанию: убыток,
    // нераскрытый отчёт, первый отчёт ещё не вышел.
    const gaps = overlay && overlay !== 'oil'
      ? Array.from(new Set(
        slice
          .filter((p) => p[overlay] === null)
          .map((p) => (overlay === 'pe' ? p.pe_gap : p.pb_gap))
          .filter((reason): reason is string => !!reason),
      ))
      : [];

    return {
      points,
      gaps,
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
      overlayBounds: bounds,
      offScale: overlay && overlay !== 'oil' && bounds
        ? overlayValues.filter((v) => v > bounds[1]).length
        : 0,
      longRange: (years ?? 99) >= 3,
      thinned: step > 1,
    };
  }, [data, history, range, overlay, oilData, oilRub, urals, discount]);

  // Замер делается заранее, а не при первом нажатии: он меняет состояние, а
  // значит перерисовывает график — 173 мс, и приходились они ровно на начало
  // первой протяжки. Кадр ожидания нужен потому, что ResponsiveContainer
  // измеряет себя сам и сетки в момент монтирования ещё нет.
  useEffect(() => {
    const frame = requestAnimationFrame(measureBand);
    return () => cancelAnimationFrame(frame);
  }, [measureBand, view]);


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
    : overlaySpec?.label;
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
  // Опорная рисуется всегда, когда есть чем: это главная линия графика, ради
  // неё он и стоит на первом экране. Остальные уровни — по кнопкам под полем.
  const extras = levels.filter((v) => v.key !== 'reference');
  const lastReference = (view.last as { reference?: number | null }).reference ?? null;
  // Подписи последних значений расходятся в разные стороны, чтобы не лечь
  // друг на друга: выше та, что выше на графике.
  const priceOnTop = lastReference === null || view.last.price >= lastReference;
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
            {hasLevels && (
              <>
                <span className="pc-key"><i className="pc-key-line" style={{ background: colors.refLine }} />Опорная</span>
                <span className="pc-key" title="Запас прочности от 15%: мелкий запас на истории окном входа не был">
                  <i className="pc-key-zone" style={{ background: colors.zoneBelow }} />Цена ниже опорной на 15%+
                </span>
              </>
            )}
            {shown.has('fair') && hasLevels && (
              <span className="pc-key"><i className="pc-key-line pc-key-line--dash" style={{ borderColor: colors.line3 }} />Справедливая</span>
            )}
            {overlay && (
              <span className="pc-key"><i className="pc-key-line" style={{ background: colors.line4 }} />{overlayLabel} — правая шкала</span>
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


      <div className="pc-canvas" ref={canvas}>
        <SpanBand store={spanStore} top={band.top} bottom={band.bottom} />
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart
            data={view.points}
            margin={{ top: 16, right: overlay ? 56 : 44, bottom: 4, left: 4 }}
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
              tickFormatter={(v: number) => rub(v)}
              domain={['auto', 'auto']}
              width={view.pennyScale ? 74 : 58}
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
            {shown.has('fair') && (
              <Line
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
              label={{ value: edgeLabel(view.last.price), position: priceOnTop ? 'top' : 'bottom', fill: colors.textPrimary, fontSize: 11, fontWeight: 600 }}
            />
            {hasLevels && lastReference !== null && (
              <ReferenceDot
                yAxisId="price"
                x={view.last.date}
                y={lastReference}
                r={0}
                label={{ value: edgeLabel(lastReference), position: priceOnTop ? 'bottom' : 'top', fill: colors.refLine, fontSize: 11, fontWeight: 600 }}
              />
            )}

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
                name={overlayLabel}
                isAnimationActive={false}
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
                if (label === 'Цена') return [`${rub(num)} ₽`, label];
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
                if (overlay === 'oil' && label === overlayLabel) {
                  return [`${ru(num, oilRub ? 0 : 2)} ${oilRub ? '₽' : '$'}`, label];
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
                if (off) return `${String(value)} · за шкалой: ${ru(off, 1)}`;
                const gap = overlay && overlay !== 'oil' && point
                  ? (overlay === 'pe' ? point.pe_gap : point.pb_gap)
                  : null;
                return gap ? `${String(value)} · ${overlaySpec?.label}: ${gap}` : String(value);
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
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
        {hasLevels ? (
          <p
            className="pc-disclaimer"
            title="Параметры модели подобраны на этой же истории, а в выборке лишь компании, которые торгуются сегодня, — поэтому прошлое на графике выглядит надёжнее, чем выглядело бы в моменте."
          >
            Опорная на каждую дату посчитана только по отчётам, опубликованным к этой дате.
            {data?.split_note && <> {data.split_note}</>}
          </p>
        ) : <span />}
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
              Нефть
            </button>
          )}
        </div>
      </div>

      {overlay === 'oil' && (
        <div className="pc-oil" role="group" aria-label="Нефть на графике">
          <span className="pc-oil-seg">
            <button type="button" className={`pc-btn pc-btn--small${!oilRub ? ' is-on' : ''}`} onClick={() => setOilRub(false)}>в долларах</button>
            <button type="button" className={`pc-btn pc-btn--small${oilRub ? ' is-on' : ''}`} onClick={() => setOilRub(true)}>в рублях</button>
          </span>
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
        </div>
      )}

      {overlay === 'oil' && (
        <p className="pc-note">
          Brent — дневная цена (FRED), в рублях — по курсу ЦБ на тот же день. Urals — Brent минус
          дисконт, который вы задали: официальной дневной цены Urals в открытом доступе нет, а дисконт
          сильно менялся (в 2022–2023 годах доходил до 30 $).
        </p>
      )}
      {overlay && overlay !== 'oil' && (
        <p className="pc-note">
          {overlaySpec?.hint}. Шкала ограничена тройной медианой: провал прибыли
          поднимает множитель до сотен, и без ограничения весь остальной ряд сжался бы
          в полоску у нуля.
          {view.gaps.length > 0 && (
            <> Пропуски: {view.gaps.join('; ')}.</>
          )}
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
