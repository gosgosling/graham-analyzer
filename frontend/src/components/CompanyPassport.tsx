import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchPassport,
  type AxisMetric,
  type PassportOut,
  type ScreenAxis,
  type ScreenResult,
  type ScreenStatus,
  type Verdict,
} from '../services/screen.api';
import './CompanyPassport.css';

/**
 * Паспорт компании — разбор по семи осям главы 13 с порогами глав 14 и 15.
 *
 * Строка на ось: слева название, посередине величины, справа порог и почему он
 * такой. Порог всегда в двух видах — применённом и книжном, потому что иначе
 * провал не отличить от чужой мерки: текущая ликвидность 0,92 у нефтяника —
 * это профиль отрасли, а не риск.
 *
 * Свод критериев переключается целиком. Между «10 лет непрерывных дивидендов»
 * и «платит сейчас» середины не существует, и смешивать их в один список
 * значит выдумать строгость, которой в книге нет. Внизу поэтому стоят оба
 * приговора сразу: «не проходит у защитного, проходит у активного» — это и
 * есть ответ, а не полуответ.
 */

/** Подзаголовок оси: чем именно она меряет. */
const AXIS_HINT: Record<string, string> = {
  profitability: 'на капитал',
  stability: 'годы без убытка',
  growth: 'концы сглажены по 3 года',
  financial: 'ликвидность и долг',
  dividends: 'непрерывная серия',
  price: 'P/E · P/B · произведение',
  size: 'выручка',
};

/** Короткое обозначение критерия: в строке порога длинное имя не помещается. */
const SHORT: Record<string, string> = {
  roe: 'ROE',
  revenue: 'выручка',
  current_ratio: 'CR',
  debt_to_equity: 'D/E',
  profitable_years: 'без убытка',
  profitable_years_short: 'без убытка',
  earnings_growth: 'рост',
  earnings_growth_short: 'рост',
  streak: 'подряд',
  cash_positive_years: 'FCF',
  cash_growth: 'рост FCF',
  pe_average: 'P/E',
  pb: 'P/B',
  pb_tangible: 'P/B мат.',
  pe_pb: 'произв.',
};

const short = (v: Verdict) => SHORT[v.metric] ?? v.metric_label;

const CHIP: Record<ScreenStatus, string> = {
  pass: 'прошла',
  fail: 'не прошла',
  'n/a': 'не применяется',
  unknown: 'нет данных',
};

/**
 * Величина есть, но измеряет не то. Отдельная подпись нужна потому, что
 * «не нашли» и «нашли, но это не то» — разные утверждения: у МТС отдача на
 * капитал 228% посчитана верно, просто капитал у неё 17 млрд при долге в сто
 * капиталов, и отношение описывает структуру, а не прибыльность.
 */
const DISTORTED_CHIP = 'искажено';

/** «по 1 критерию», «по 2 критериям» — дательный падеж по числу. */
const criteria = (n: number) => {
  const tens = n % 100;
  const ones = n % 10;
  const one = ones === 1 && tens !== 11;
  return `${n} ${one ? 'критерию' : 'критериям'}`;
};

/**
 * Чего не хватило своду. Искажённое и отсутствующее считаются порознь: у МТС
 * данные есть, они посчитаны верно, и написать «данных не хватает» значило бы
 * послать читателя искать то, что уже лежит перед ним.
 */
function unmeasured(result: ScreenResult): string {
  const gaps = result.unknown.map(
    (m) => result.verdicts.find((v) => v.metric === m),
  );
  const distorted = gaps.filter((v) => v?.distorted).length;
  const missing = gaps.length - distorted;

  const parts: string[] = [];
  if (missing) parts.push(`данных не хватает по ${criteria(missing)}`);
  if (distorted) parts.push(`искажены величины по ${criteria(distorted)}`);
  const text = parts.join(', ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Приговор оси целиком: провал одной подметрики валит ось. */
function axisStatus(verdicts: Verdict[]): ScreenStatus {
  if (!verdicts.length) return 'unknown';
  if (verdicts.some((v) => v.status === 'fail')) return 'fail';
  if (verdicts.some((v) => v.status === 'unknown')) return 'unknown';
  if (verdicts.every((v) => v.status === 'n/a')) return 'n/a';
  return 'pass';
}

const num = (v: number, digits: number) =>
  v.toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

/** Крупные суммы — словами: 3 767 768 млн читается хуже, чем 3,8 трлн. */
function compact(value: number): string {
  const abs = Math.abs(value);
  const round = (v: number) => num(v, 1).replace(/,0$/, '');
  if (abs >= 1_000_000) return `${round(value / 1_000_000)} трлн ₽`;
  if (abs >= 1_000) return `${round(value / 1_000)} млрд ₽`;
  return `${num(value, 0)} млн ₽`;
}

/** Десятичная запятая и в порогах тоже: «≥ 33.3» — не по-русски. */
const comma = (text: string) => text.replace(/(\d)\.(\d)/g, '$1,$2');

const isGrowth = (key: string) => key.startsWith('earnings_growth') || key.startsWith('cash_growth');

function metricValue(m: AxisMetric): string {
  if (m.value === null) return '—';
  if (m.of !== null && m.of !== undefined) return `${num(m.value, 0)} / ${num(m.of, 0)}`;
  if (m.unit === 'млн ₽') return compact(m.value);
  if (m.unit === 'лет') return `${num(m.value, 0)} лет`;
  // У процента сотые доли не значат ничего, у отношения — значат: ликвидность
  // 0,92 и 0,9 читаются одинаково, но первое число настоящее. У роста важен знак.
  const digits = m.unit === '%' ? (Math.abs(m.value) >= 100 ? 0 : 1) : 2;
  const sign = isGrowth(m.key) && m.value > 0 ? '+' : '';
  return `${sign}${num(m.value, digits)}${m.unit === '%' ? '%' : ''}`;
}

/** Пояснение под величиной: средняя, испорченные годы. */
function metricAside(m: AxisMetric): string | null {
  const parts: string[] = [];
  if (m.average !== null) parts.push(`средняя ${num(m.average, 1)}${m.unit === '%' ? '%' : ''}`);
  if (m.flagged.length) parts.push(m.flagged.join(', '));
  return parts.length ? parts.join(' · ') : null;
}

/** Спарклайн: форма ряда важнее его точных значений. */
function Spark({ series }: { series: [number, number][] }) {
  if (series.length < 3) return <span className="pp-spark-empty" />;
  const values = series.map(([, v]) => v);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const w = 62;
  const h = 16;
  const step = w / (series.length - 1);
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`)
    .join(' ');

  return (
    <svg className="pp-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      {min < 0 && max > 0 && (
        <line
          x1={0}
          y1={h - ((0 - min) / span) * h}
          x2={w}
          y2={h - ((0 - min) / span) * h}
          className="pp-spark-zero"
        />
      )}
      <polyline points={points} className="pp-spark-line" />
    </svg>
  );
}

function AxisRow({ axis, verdicts }: { axis: ScreenAxis; verdicts: Verdict[] }) {
  const status = axisStatus(verdicts);
  // Искажение подменяет только подпись, не приговор: критерий всё равно не
  // засчитан, но причина у него своя и называть её «нет данных» неверно.
  const distorted = status === 'unknown' && verdicts.some((v) => v.distorted);
  const chip = distorted ? DISTORTED_CHIP : CHIP[status];
  // «без убытка без единого убытка» — короткое имя и текст порога здесь об
  // одном и том же, и приставка только мешает.
  const rule = (v: Verdict, text: string, value: number | null) => {
    // Порог по выручке хранится в миллионах, как и сама величина; рядом с
    // «3,8 трлн» число «50 000» не читается вовсе.
    if (v.metric === 'revenue' && value !== null) return `выручка ≥ ${compact(value)}`;
    if (text.startsWith('без ') || text === 'по профилю') return text;
    return `${short(v)} ${text}`;
  };

  const thresholds = verdicts
    .map((v) => (v.status === 'n/a' ? null : comma(rule(v, v.text, v.applied))))
    .filter(Boolean)
    .join(' · ');

  // Пояснение относится к порогу, а не к величине. Примечания отдельных
  // подметрик живут в подсказке своей строки: иначе рядом с защитным сводом
  // всплывает объяснение про горизонт активного, к которому оно не относится.
  // Какие подметрики вообще судятся порогом — и с каким исходом.
  const ruled = new Map<string, string>(
    verdicts.map((v) => [v.metric, v.marginal ? 'marginal' : v.status]),
  );
  const adjusted = verdicts.filter((v) => v.adjusted);
  // Величина, которой нельзя верить, важнее любого порога: её и показываем.
  const doubt = verdicts.map((v) => (v.status === 'unknown' ? v.note : null)).find(Boolean);
  // Оговорка к засчитанному критерию — не то же, что недоверие к величине.
  // Число верное, вопрос поставлен шатко: пятилетнее окно на российских
  // данных неизбежно накрывает 2020 и 2022 годы.
  const caveat = verdicts.map((v) => v.caveat).find(Boolean);

  // Общее пояснение — только то, что ещё не сказано выше. Недоверие и
  // оговорка берут свой текст из тех же примечаний, и без этой проверки одна
  // и та же фраза печаталась дважды подряд: красным и серым.
  const said = new Set([doubt, caveat].filter(Boolean));
  const prose = [...verdicts.map((v) => v.note), axis.note]
    .filter((v, i, all) => v && !said.has(v) && all.indexOf(v) === i)
    .slice(0, 2)
    .join('. ');

  return (
    <div className={`pp-row pp-row--${status.replace('/', '')}`}>
      <div className="pp-mark" title={chip}>
        {status === 'pass' ? '✓' : status === 'fail' ? '✗'
          : status === 'n/a' ? '·' : distorted ? '≠' : '?'}
      </div>

      <div className="pp-name">
        <h4>{axis.label}</h4>
        <span>{AXIS_HINT[axis.key] ?? ''}</span>
      </div>

      <div className="pp-values">
        {axis.metrics.map((m) => {
          const aside = metricAside(m);
          // Цвет величины: сторона нуля — от оси, прохождение порога — от
          // вердикта. Без второго стоимость риска решала судьбу оси, оставаясь
          // при этом серой: читатель видел крестик у «Стабильности» и не
          // понимал, какая из трёх строк его вызвала.
          const judged = ruled.get(m.key);
          const paint = judged === 'marginal' ? 'is-warn'
            : judged === 'pass' ? 'is-good'
              : judged === 'fail' ? 'is-bad'
                : m.tone ? `is-${m.tone}` : undefined;
          return (
            <div className="pp-metric" key={m.key}>
              <b className={paint} title={m.note ?? undefined}>
                {metricValue(m)}
              </b>
              <span title={m.note ?? undefined}>
                {m.label}
                {m.asof === 'LTM' && (
                  <em title="За последние двенадцать месяцев, а не за календарный год">
                    LTM
                  </em>
                )}
                {aside && <i> · {aside}</i>}
              </span>
              <Spark series={m.series} />
            </div>
          );
        })}
      </div>

      <div className="pp-verdict">
        <div className="pp-verdict-head">
          <span className="pp-chip">{chip}</span>
          <span className="pp-threshold">{thresholds || '—'}</span>
        </div>
        {adjusted.length > 0 && (
          <div className="pp-adjusted">
            в книге {comma(adjusted.map((v) => rule(v, v.book_text, v.book)).join(' · '))} — порог
            сдвинут отраслью
          </div>
        )}
        {doubt && <p className="pp-doubt">{doubt}</p>}
        {caveat && <p className="pp-caveat">{caveat}</p>}
        {prose && <p className="pp-prose">{prose}</p>}
      </div>
    </div>
  );
}

interface Props {
  companyId: number;
}

export default function CompanyPassport({ companyId }: Props) {
  const [standard, setStandard] = useState('defensive');

  const { data, isLoading, error } = useQuery<PassportOut>({
    queryKey: ['screen-passport', companyId],
    queryFn: () => fetchPassport(companyId),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <div className="pp-state">Считаем оси…</div>;
  if (error || !data) {
    const detail =
      (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return <div className="pp-state pp-state--error">{detail ?? 'Не удалось посчитать паспорт'}</div>;
  }

  const result = data.screens[standard];
  const byAxis = new Map<string, Verdict[]>();
  result.verdicts.forEach((v) => {
    byAxis.set(v.axis, [...(byAxis.get(v.axis) ?? []), v]);
  });

  return (
    <div className="pp">
      <div className="pp-head">
        <div className="pp-title">
          <b>{data.company.ticker}</b>
          <span>{data.company.name}</span>
          <em title={data.profile.summary}>профиль: {data.profile.label.toLowerCase()}</em>
        </div>
      </div>

      <div className="pp-section">
        <span>семь осей · пороги</span>
        <div className="pp-switch">
          {Object.entries(data.screens).map(([key, s]) => (
            <button
              key={key}
              type="button"
              className={key === standard ? 'is-on' : undefined}
              onClick={() => setStandard(key)}
            >
              {key === 'defensive' ? 'защитного' : 'активного'} инвестора
            </button>
          ))}
        </div>
        <i />
      </div>

      <div className="pp-rows">
        {data.order.map((key) => {
          const axis = data.axes[key];
          if (!axis) return null;
          return <AxisRow key={key} axis={axis} verdicts={byAxis.get(key) ?? []} />;
        })}
      </div>

      <div className="pp-section">
        <span>уровень</span>
        <i />
      </div>

      <div className="pp-levels">
        {Object.entries(data.screens).map(([key, s]) => (
          <div
            key={key}
            className={`pp-level${s.clears ? ' is-clear' : ''}${key === standard ? ' is-current' : ''}`}
          >
            <div className="pp-level-tag">
              {key === 'defensive' ? 'защитный инвестор' : 'активный инвестор'}
            </div>
            <div className="pp-level-verdict">
              {s.clears ? 'проходит' : 'не проходит'}
            </div>
            <p>
              {s.clears
                ? `Все ${s.checked} критериев пройдены.`
                : s.failed.length
                  ? `${s.passed} из ${s.checked}. Не прошла: ${s.failed
                      .map((m) => s.verdicts.find((v) => v.metric === m)?.metric_label ?? m)
                      .join(', ')}.`
                  : `${s.passed} из ${s.checked}.`}
              {!s.complete && ` ${unmeasured(s)} — прохождением это не считается.`}
            </p>
          </div>
        ))}
      </div>

      <p className="pp-foot">
        Балла здесь нет намеренно. Грэм требует прохождения всех критериев сразу, а не
        суммы очков: компания с шестью пятёрками и одним нулём у него не проходит, и
        усреднение это скрыло бы.
      </p>
    </div>
  );
}
