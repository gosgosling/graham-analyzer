import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchMarketScreen,
  type MarketColumn,
  type MarketScreenOut,
  type RowSafety,
  type ScreenStatus,
  type Verdict,
} from '../services/screen.api';
import CompanyLogo from '../components/CompanyLogo';
import SelectSheet from '../components/SelectSheet';
import { marginText, SafetyMargin, SIGNAL_SHORT } from '../components/SafetyMargin';
import { groupRows, sieve, type SieveStep } from '../utils/screenSieve';
import { filterRows, industries } from '../utils/screenTableFilter';
import { metricKey, nextSort, parseSort, sortRows, type SortDir, type SortState } from '../utils/screenSort';
import CompareView from '../components/CompareView';
import './MarketScreen.css';

/**
 * Скринер: требования Грэма ко всему рынку.
 *
 * Главный вид — сито: требования по очереди и сколько компаний остаётся
 * после каждого, а справа словами — кто прошёл и чего не хватило ближайшим.
 * Полная таблица — компания на критерий — отдельным видом (?view=table).
 *
 * Смысл этого представления в том, чего не видно в паспорте одной компании.
 * Паспорт говорит «Лукойл не прошёл по ликвидности» — и это читается как
 * приговор Лукойлу. Таблица показывает, что по ликвидности не прошли
 * пятнадцать из двадцати семи, и вопрос сразу меняется: дело в компаниях или
 * в мерке.
 *
 * Итога в виде балла здесь нет. Грэм требует прохождения всех критериев
 * сразу, и «шесть из семи» у него не результат, а непрохождение.
 */

const MARK: Record<ScreenStatus, string> = {
  pass: '✓',
  fail: '✗',
  'n/a': '·',
  unknown: '?',
};

const TITLE: Record<ScreenStatus, string> = {
  pass: 'Пройден',
  fail: 'Не пройден',
  'n/a': 'К отрасли не применяется',
  unknown: 'Не хватает данных',
};

/**
 * Провал «на волосок»: 2,5 пункта при пороге 15 — это шестая часть планки.
 *
 * Сам Грэм порогам буквально не следовал: в гл. 14 он берёт устойчивую
 * компанию и при P/E 16, потому что смотрел на картину целиком, а не на
 * пересечение линии. Отсюда и жёлтый: почти — всё равно не прошла, вердикт
 * не смягчается, но отличить «мимо на шаг» от «мимо на три четверти» нужно.
 */
const NEAR_MISS = 2.5 / 15;

/** Границы глубины провала — в долях самого порога. */
const MILD = 0.5;
const BAD = 1.0;

/**
 * Класс ячейки. У проваленных различаем ещё и глубину.
 *
 * Вердикт остаётся двоичным — свод требует всех критериев сразу. Но Татнефть
 * с отдачей 12% при пороге 15% и Роснефть с 3,2% рисовались одинаковым
 * крестиком, хотя между ними разница вчетверо: для выбора между двумя
 * непрошедшими это ровно та величина, которая и нужна.
 */
/** Короткие имена подставленных показателей: в клетке помещается два слова. */
const SWAP_LABEL: Record<string, string> = {
  capital_core: 'Н1.1',
  cost_of_risk_average: 'ст. риска',
  npl_ratio: 'NPL',
  cost_to_income_average: 'CIR',
};

/**
 * Короткие заголовки столбцов. Колонки равной ширины, и слово длиннее
 * колонки рвалось посреди («ликвидност-ь»): переносов по слогам для
 * русского нет во всех браузерах. Полное имя — в подсказке заголовка.
 */
const SHORT_HEAD: Record<string, string> = {
  roe: 'Отдача на капитал',
  current_ratio: 'Текущая ликвидн.',
  profitable_years: 'Годы без убытка',
  profitable_years_short: 'Без убытка, 5 лет',
  earnings_growth: 'Рост EPS за 10 лет',
  earnings_growth_short: 'Рост EPS за 5 лет',
  streak: 'Дивид. подряд',
  pe_average: 'P/E за 3 года',
  pb_tangible: 'P/B мат. капитала',
  pe_pb: 'P/E × P/B',
  cash_positive_years: 'Годы без оттока FCF',
  cash_growth: 'Рост FCF за 10 лет',
  cash_growth_short: 'Рост FCF за 5 лет',
};

const cls = (v: Verdict) => {
  const base = `ms-cell ms-cell--${v.status.replace('/', '')}`;
  if (v.status !== 'fail') return base;
  // Минус — не «дальше по той же шкале», а другое состояние: отдача −3,5%
  // означает, что капитал акционера уменьшается, а не медленно растёт.
  // Отдельная полоса нужна ещё и потому, что у правил с порогом ноль (рост
  // потока) расстояние в долях порога не выражается вовсе, и без этой ветки
  // сжимающийся поток красился бы бледнее любого недобора.
  if (v.value != null && v.value < 0) return `${base} ms-cell--loss`;
  if (v.shortfall == null) return base;
  const depth = v.shortfall <= NEAR_MISS ? 'near'
    : v.shortfall <= MILD ? 'mild'
      : v.shortfall <= BAD ? 'bad'
        : 'severe';
  return `${base} ms-cell--${depth}`;
};

/** Величина в ячейке — рядом со знаком, чтобы было видно, насколько мимо.
 *
 * Сжимать до «млрд» можно только деньги. Прирост прибыли Novabev — 42 868%,
 * и без проверки единицы он превращался в «43 млрд». */
const cellValue = (v: Verdict | null): string => {
  if (!v || v.value === null) return '';
  if (v.of !== null && v.of !== undefined) return `${v.value}/${v.of}`;

  const abs = Math.abs(v.value);
  const ru = (n: number, digits: number) =>
    n.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

  if (v.unit === 'млн ₽') {
    if (abs >= 1_000_000) return `${ru(v.value / 1_000_000, 1)} трлн`;
    if (abs >= 1_000) return `${ru(v.value / 1_000, 0)} млрд`;
    return `${ru(v.value, 0)} млн`;
  }
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return `${ru(v.value, digits)}${v.unit === '%' ? '%' : ''}`;
};

const cellTitle = (v: Verdict | null): string => {
  if (!v) return '—';
  const parts = [`${v.metric_label}: ${TITLE[v.status]}`];
  if (v.value !== null) {
    parts.push(`значение ${v.value.toLocaleString('ru-RU')}${v.unit ? ` ${v.unit}` : ''}`);
  }
  parts.push(`порог ${v.text}`);
  if (v.adjusted) parts.push(`в книге ${v.book_text}`);
  parts.push(v.source);
  if (v.status === 'fail' && v.value != null && v.value < 0) {
    parts.push('величина отрицательна — не «мало», а минус');
  } else if (v.shortfall != null) {
    const pct = (v.shortfall * 100).toLocaleString('ru-RU', { maximumFractionDigits: 0 });
    parts.push(v.shortfall <= NEAR_MISS
      ? `мимо на ${pct}% порога — почти дотянула`
      : `мимо на ${pct}% порога`);
  }
  if (v.note) parts.push(v.note);
  return parts.join('\n');
};

const decimal = (t: string) => t.replace(/(\d)\.(\d)/g, '$1,$2');

/**
 * Действующий порог столбца — по нему и ставятся отметки (выручка — в
 * миллиардах). Раньше здесь стоял книжный: заголовок обещал ликвидность
 * ≥ 2, а ЛУКОЙЛ с 1,18 проходил по отраслевому ≥ 1, и это читалось как ошибка.
 */
const thresholdText = (c: MarketColumn): string => (c.metric === 'revenue' && c.book !== null
  ? `≥ ${Math.round(c.book / 1000)} млрд`
  : decimal(c.applied_text ?? c.book_text));

/** Книжный порог, если он отличается от действующего, — «у Грэма ≥ 2». */
const bookText = (c: MarketColumn): string | null => {
  if (c.metric === 'revenue' || !c.applied_text || c.applied_text === c.book_text) return null;
  if (c.book_text === '—' || c.book_text === 'по профилю') return null;
  return `у Грэма ${decimal(c.book_text)}`;
};

/**
 * Ячейка сигнала о цене.
 *
 * Свод отвечает на вопрос «хороша ли компания», сигнал — «хороша ли цена».
 * Вопросы разные, и в одну оценку их сводить нельзя: Лукойл проходит свод
 * целиком и при этом стоит дороже своей оценки, а МТС не проходит и вдобавок
 * уступает облигации. Обе пары «прошла/дорого» и «не прошла/дёшево»
 * содержательны ровно потому, что столбцы независимы.
 */
function SafetyCell({ safety }: { safety: RowSafety | null }) {
  if (!safety) {
    return <td className="ms-safety" title="Оценка не посчитана">—</td>;
  }
  const margin = safety.value_margin;
  return (
    <td
      className={`ms-safety ms-safety--${safety.signal}`}
      title={[
        safety.reason,
        safety.reference !== null ? `опорная оценка ${safety.reference.toLocaleString('ru-RU')} ₽` : null,
        safety.yield_spread !== null ? `запас по ставке ${safety.yield_spread > 0 ? '+' : ''}${safety.yield_spread} п.п.` : null,
        ...safety.notes,
      ].filter(Boolean).join('\n')}
    >
      <b>{SIGNAL_SHORT[safety.signal]}</b>
      {/* За минус сто процентов запас перестаёт читаться: «−368%» — это
          цена в 4,7 раза выше опорной, так и пишем. */}
      {margin !== null && <i>{marginText(margin)}</i>}
    </td>
  );
}

/** Компания в строке: логотип, тикер-ссылка, имя. */
function Ident({ row }: { row: MarketScreenOut['rows'][number] }) {
  return (
    <span className="ms-ident">
      <CompanyLogo url={row.logo_url} ticker={row.ticker} alt="" className="ms-logo" />
      <span className="ms-ident-text">
        <Link to={`/company/${row.id}`}>{row.ticker}</Link>
        <span className="ms-name" title={row.name}>{row.name}</span>
      </span>
    </span>
  );
}

/** Сито: требования по очереди, сколько компаний остаётся после каждого. */
function Sieve({ data, steps, afterGraham, cleared }: {
  data: MarketScreenOut; steps: SieveStep[]; afterGraham: number; cleared: number;
}) {
  const graham = steps.filter((s) => !s.ours);
  const ours = steps.filter((s) => s.ours);
  const step = (s: SieveStep, n: number) => (
    <li key={s.column.metric} className="sc-step" title={`${s.column.label}\n${s.column.source}`}>
      <span className="sc-n">{String(n).padStart(2, '0')}</span>
      <span className="sc-req">
        <b>{s.column.label}</b>
        <small>
          {thresholdText(s.column)}
          {bookText(s.column) && <span className="sc-book"> · {bookText(s.column)}</span>}
        </small>
      </span>
      <span className="sc-left">
        {s.remaining}
        {s.dropped > 0 && <s>−{s.dropped}</s>}
      </span>
    </li>
  );
  return (
    <ol className="sc-sieve">
      <li className="sc-step sc-step--total">
        <span className="sc-n" />
        <span className="sc-req"><b>Компаний с проверенной отчётностью</b></span>
        <span className="sc-left">{data.rows.length}</span>
      </li>
      {graham.map((s, i) => step(s, i + 1))}
      {ours.length > 0 && (
        <>
          <li className="sc-mid">После требований Грэма — <b>{afterGraham}</b>. Дальше — проверки сверх книги:</li>
          {ours.map((s, i) => step(s, graham.length + i + 1))}
        </>
      )}
      <li className="sc-step sc-step--end">
        <span className="sc-n" />
        <span className="sc-req"><b>Прошли и требования Грэма, и наши проверки</b></span>
        <span className="sc-left">{cleared}</span>
      </li>
    </ol>
  );
}

/** Первая буква — строчная, но аббревиатуры не трогаем: «P/B», «FCF». */
const lowerFirst = (label: string) =>
  (/^[А-ЯЁA-Z][а-яёa-z]/.test(label) ? label[0].toLowerCase() + label.slice(1) : label);

/** Чего не хватило: «лет подряд с выплатой: 4/10 при пороге ≥ 10». */
function Miss({ cell }: { cell: Verdict }) {
  const near = cell.status === 'fail' && cell.shortfall != null && cell.shortfall <= NEAR_MISS
    && !(cell.value != null && cell.value < 0);
  return (
    <span className="sc-miss" title={cellTitle(cell)}>
      {lowerFirst(cell.metric_label)}:{' '}
      {cell.status === 'unknown'
        ? <em className="sc-miss-unknown">нет данных</em>
        : <b className={near ? 'sc-near' : undefined}>{cellValue(cell)}</b>}
      {cell.status !== 'unknown' && <span className="sc-thr"> при пороге {cell.text.replace(/(\d)\.(\d)/g, '$1,$2')}</span>}
    </span>
  );
}

function SieveView({ data, standard }: { data: MarketScreenOut; standard: string }) {
  const { steps, afterGraham, cleared } = sieve(data);
  const groups = groupRows(data);
  const value = (row: MarketScreenOut['rows'][number], metric: string) => {
    const i = data.columns.findIndex((c) => c.metric === metric);
    return i >= 0 ? cellValue(row.cells[i]) || '—' : '—';
  };
  const pbMetric = data.columns.some((c) => c.metric === 'pb') ? 'pb' : 'pb_tangible';
  const missRow = ({ row, misses }: (typeof groups.one)[number]) => (
    <li key={row.ticker} className="sc-row sc-row--miss">
      <Ident row={row} />
      <span className="sc-why">
        {misses.map((m, i) => <React.Fragment key={m.metric}>{i > 0 && '; '}<Miss cell={m} /></React.Fragment>)}
      </span>
      <SafetyMargin safety={row.safety} />
    </li>
  );
  return (
    <div className="sc">
      <aside className="sc-side">
        {/* На узком экране воронка идёт после результата и без заголовка
            читалась бы как продолжение списка компаний. */}
        <h2 className="sc-side-title">Как отбирали: {data.rows.length} → {cleared}</h2>
        <Sieve data={data} steps={steps} afterGraham={afterGraham} cleared={cleared} />
      </aside>
      <div className="sc-main">
        <section className="sc-sec">
          {/* «Прошли все семь требований» смешивало этапы: в итоге учтены и
              наши проверки отдачи и денежного потока, которых у Грэма нет. */}
          <h2>Прошли требования Грэма и наши проверки
            {' '}<span>— {groups.passed.length}</span></h2>
          {groups.passed.length === 0 ? (
            <p className="sc-empty">Ни одна компания не проходит всё — это результат, а не сбой.</p>
          ) : (
            <ul className="sc-list">
              <li className="sc-row sc-row--head" aria-hidden>
                <span />
                <span>P/E за 3 года</span>
                <span>P/B</span>
                <span>Дивиденды подряд</span>
                <span>Запас прочности</span>
              </li>
              {groups.passed.map(({ row }) => (
                <li key={row.ticker} className="sc-row sc-row--pass">
                  <Ident row={row} />
                  {/* Подписи — для телефона: там числа уходят второй строкой
                      под название, и шапки колонок над ними нет. */}
                  <span className="sc-num" data-label="P/E 3 г.">{value(row, 'pe_average')}</span>
                  <span className="sc-num" data-label="P/B">{value(row, pbMetric)}</span>
                  <span className="sc-num" data-label="Дивиденды подряд">{value(row, 'streak')}</span>
                  <SafetyMargin safety={row.safety} />
                </li>
              ))}
            </ul>
          )}
        </section>

        {groups.one.length > 0 && (
          <section className="sc-sec">
            <h2>Не прошли одно требование <span>— {groups.one.length}</span></h2>
            <ul className="sc-list">{groups.one.map(missRow)}</ul>
          </section>
        )}

        {groups.two.length > 0 && (
          <section className="sc-sec">
            <h2>Не прошли два требования <span>— {groups.two.length}</span></h2>
            <ul className="sc-list">{groups.two.map(missRow)}</ul>
          </section>
        )}

        <section className="sc-sec">
          <h2>Не прошли три требования и больше <span>— {groups.rest.length}</span></h2>
          <p className="sc-empty">
            Все компании по всем требованиям — в <Link to="?view=table">полной таблице</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}

/** Тон плитки: пройдено, чуть не дотянула, не пройдено, нет числа. */
const dotTone = (cell: Verdict | null): string => {
  if (!cell || cell.status === 'n/a') return 'na';
  if (cell.status === 'unknown') return 'unknown';
  if (cell.status === 'pass') return 'pass';
  const negative = cell.value != null && cell.value < 0;
  return !negative && cell.shortfall != null && cell.shortfall <= NEAR_MISS ? 'near' : 'fail';
};

/** Подписи плиток на телефоне — в плитку шириной в палец влезает слово. */
const TILE_LABEL: Record<string, string> = {
  roe: 'ROE',
  revenue: 'Выручка',
  current_ratio: 'Ликвидн.',
  profitable_years: 'Без убытка',
  profitable_years_short: 'Без уб. 5 л.',
  earnings_growth: 'Рост EPS',
  earnings_growth_short: 'EPS 5 л.',
  streak: 'Дивиденды',
  pe_average: 'P/E 3 г.',
  pb: 'P/B',
  pb_tangible: 'P/B мат.',
  pe_pb: 'P/E×P/B',
  cash_positive_years: 'FCF > 0',
  cash_growth: 'FCF 10 л.',
  cash_growth_short: 'FCF 5 л.',
};

/** Кнопки сортировки на телефоне — шапки колонок там нет. */
const MOBILE_SORTS: { key: string; label: string }[] = [
  { key: 'safety', label: 'Запас прочности' },
  { key: 'total', label: 'Пройдено' },
  { key: metricKey('pe_average'), label: 'P/E' },
  { key: metricKey('pb'), label: 'P/B' },
  { key: metricKey('streak'), label: 'Дивиденды' },
  { key: metricKey('roe'), label: 'ROE' },
];

/** Стрелка сортировки: бледная двойная — можно, одинарная цветная — отсортировано. */
function SortArrow({ dir }: { dir: SortDir | null }) {
  return (
    <svg className={`ms-sort${dir ? ' is-on' : ''}`} width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
      {dir === 'desc' && <path d="M2 3.5 5 7l3-3.5" />}
      {dir === 'asc' && <path d="M2 6.5 5 3l3 3.5" />}
      {!dir && <path d="M2 3.5 5 1l3 2.5M2 6.5 5 9l3-2.5" />}
    </svg>
  );
}

/**
 * Полная таблица на телефоне: компания — строка, требования — плитки.
 *
 * Пятнадцать колонок на экране в 375 пикселей читались только прокруткой
 * всей таблицы вбок, и через две колонки терялось, чья это строка. Здесь
 * строка компании стоит на месте, а вбок листается только её лента плиток:
 * у каждой подпись, число и цвет — пройдено, чуть не дотянула, не пройдено.
 * Первая плитка — запас прочности. Нажатие на компанию ведёт в её карточку:
 * раньше под строкой раскрывалось окно с непройденными требованиями, но
 * теперь всё это видно в плитках, и окно только повторяло их.
 */
function ScreenMobileList({ data, rows, sort, onSort }: {
  data: MarketScreenOut;
  rows: MarketScreenOut['rows'];
  sort: SortState | null;
  onSort: (key: string) => void;
}) {
  // Без выбранной сортировки — сначала прошедшие больше требований.
  const ordered = useMemo(() => (sort ? rows : [...rows].sort((a, b) => (b.passed - a.passed)
    || ((b.safety?.value_margin ?? -Infinity) - (a.safety?.value_margin ?? -Infinity)))), [rows, sort]);
  const sorts = MOBILE_SORTS.filter((o) => !o.key.startsWith('m:') || data.columns.some((c) => metricKey(c.metric) === o.key));
  return (
    <div className="smb">
      <div className="smb-sorts" role="group" aria-label="Сортировка">
        <span>Сортировка:</span>
        {sorts.map((o) => {
          const on = sort?.key === o.key;
          return (
            <button key={o.key} type="button" className={`smb-sort${on ? ' is-on' : ''}`} aria-pressed={on}
              onClick={() => onSort(o.key)}>
              {o.label}{on && (sort!.dir === 'desc' ? ' ↓' : ' ↑')}
            </button>
          );
        })}
      </div>
      <p className="smb-legend" aria-hidden>
        <i className="smb-key smb-tile--pass" /> пройдено
        <i className="smb-key smb-tile--near" /> чуть не дотянула
        <i className="smb-key smb-tile--fail" /> не пройдено
        <i className="smb-key smb-tile--unknown" /> нет данных
      </p>
      <ul className="smb-list">
        {ordered.map((row) => (
          <li key={row.ticker} className="smb-item">
            <Link className="smb-row" to={`/company/${row.id}`}>
              <span className="smb-head">
                <CompanyLogo url={row.logo_url} ticker={row.ticker} alt="" className="smb-logo" />
                <span className="smb-name"><b>{row.ticker}</b> · {row.name}</span>
                <span className={`smb-count${row.clears ? ' is-clear' : ''}`}>
                  {row.clears ? 'прошла все' : `${row.passed} из ${row.checked}`}
                </span>
              </span>
            </Link>
            <div className="smb-tiles" aria-label={`Пройдено ${row.passed} требований из ${row.checked}`}>
              <span className={`smb-tile smb-tile--safety ms-safety--${row.safety?.signal ?? 'none'}`}>
                <small>Запас</small>
                <b>{row.safety ? marginText(row.safety.value_margin) : '—'}</b>
              </span>
              {row.cells.map((cell, i) => {
                const column = data.columns[i];
                const swapped = cell != null && cell.metric !== column.metric;
                const label = swapped ? (SWAP_LABEL[cell!.metric] ?? cell!.metric_label) : (TILE_LABEL[column.metric] ?? column.label);
                return (
                  <span key={column.metric} className={`smb-tile smb-tile--${dotTone(cell)}`} title={cellTitle(cell)}>
                    <small>{label}</small>
                    <b>{cell && cell.status !== 'n/a' && cell.status !== 'unknown' ? cellValue(cell) || '—' : '—'}</b>
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FullTable({ data }: { data: MarketScreenOut }) {
  // Поиск и отрасль живут в адресе: отфильтрованную таблицу можно отправить
  // ссылкой, и она переживает переключение «защитный / активный».
  const [params, setParams] = useSearchParams();
  const query = params.get('q') ?? '';
  const industry = params.get('industry') ?? '';
  const update = (key: 'q' | 'industry', value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  // Сортировка тоже в адресе: отсортированную таблицу можно отправить ссылкой.
  const sort = parseSort(params.get('sort'), params.get('dir'));
  const onSort = (key: string) => {
    const next = nextSort(sort, key, data.columns);
    const p = new URLSearchParams(params);
    if (next) { p.set('sort', next.key); p.set('dir', next.dir); } else { p.delete('sort'); p.delete('dir'); }
    setParams(p, { replace: true });
  };
  const dirOf = (key: string): SortDir | null => (sort?.key === key ? sort.dir : null);
  const ariaSort = (key: string) => (sort?.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none');
  const options = useMemo(() => industries(data.rows), [data.rows]);
  const filtered = useMemo(() => filterRows(data.rows, query, industry), [data.rows, query, industry]);
  const rows = useMemo(() => sortRows(filtered, sort, data.columns), [filtered, sort, data.columns]);
  const narrowed = filtered.length !== data.rows.length;

  return (
    <>
      <div className="ms-filter" role="search">
        <input
          type="search"
          className="ms-filter-search"
          placeholder="Тикер или название"
          aria-label="Найти компанию в таблице"
          value={query}
          onChange={(e) => update('q', e.target.value)}
        />
        <SelectSheet
          className="ms-filter-industry"
          label="Отрасль"
          value={industry}
          onChange={(v) => update('industry', v)}
          options={[
            { value: '', label: 'Все отрасли', count: data.rows.length },
            ...options.map((o) => ({ value: o.key, label: o.label, count: o.count })),
          ]}
        />
        {narrowed && (
          <>
            <span className="ms-filter-count">{rows.length} из {data.rows.length}</span>
            <button type="button" className="ms-filter-reset" onClick={() => setParams(
              (() => { const n = new URLSearchParams(params); n.delete('q'); n.delete('industry'); return n; })(),
              { replace: true },
            )}>
              Сбросить
            </button>
          </>
        )}
      </div>
      <ScreenMobileList data={data} rows={rows} sort={sort} onSort={onSort} />
      <div className="ms-scroll ms-scroll--wide">
        <table className="ms-table">
          {/* Ширины задаёт colgroup, а не содержимое: иначе колонку
              раздувал самый длинный заголовок, и одинаковые по смыслу
              столбцы выходили от 45 до 130 пикселей. Критерии делят
              остаток поровну. */}
          <colgroup>
            <col className="ms-col-company" />
            {data.columns.map((c) => <col key={c.metric} />)}
            <col className="ms-col-safety" />
            <col className="ms-col-total" />
          </colgroup>
          <thead>
            <tr>
              <th className={`ms-sticky ms-sortable${dirOf('company') ? ' is-sorted' : ''}`} aria-sort={ariaSort('company')}>
                <button type="button" className="ms-sort-btn" onClick={() => onSort('company')}>
                  Компания<SortArrow dir={dirOf('company')} />
                </button>
              </th>
              {data.columns.map((c) => {
                const key = metricKey(c.metric);
                return (
                  <th key={c.metric} className={`ms-sortable${dirOf(key) ? ' is-sorted' : ''}`} aria-sort={ariaSort(key)}
                    title={`${c.label}\n${c.axis_label} · ${c.source}\nкнижный порог ${c.book_text}`}>
                    <button type="button" className="ms-sort-btn" onClick={() => onSort(key)}>
                      <span className="ms-col">{SHORT_HEAD[c.metric] ?? c.label}</span>
                      <span className="ms-col-thr">{thresholdText(c)}</span>
                      {bookText(c) && <span className="ms-col-book">{bookText(c)}</span>}
                      <SortArrow dir={dirOf(key)} />
                    </button>
                  </th>
                );
              })}
              <th
                className={`ms-safety ms-sortable${dirOf('safety') ? ' is-sorted' : ''}`}
                aria-sort={ariaSort('safety')}
                title={'Запас прочности: опорная оценка против цены.\n'
                  + 'Отдельный вопрос от свода — свод про компанию, сигнал про цену.'}
              >
                <button type="button" className="ms-sort-btn" onClick={() => onSort('safety')}>
                  <span className="ms-col">Запас прочности</span>
                  <span className="ms-col-thr">≥ ⅓</span>
                  <SortArrow dir={dirOf('safety')} />
                </button>
              </th>
              <th className={`ms-total ms-sortable${dirOf('total') ? ' is-sorted' : ''}`} aria-sort={ariaSort('total')}>
                <button type="button" className="ms-sort-btn" onClick={() => onSort('total')}>
                  Итог<SortArrow dir={dirOf('total')} />
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="ms-empty" colSpan={data.columns.length + 3}>
                  Под запрос не подошла ни одна компания
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.ticker} className={row.clears ? 'is-clear' : undefined}>
                <th className="ms-sticky" title={row.profile_label}>
                  {/* Логотип перед тикером: в таблице на три десятка
                      строк знакомый кружок находится быстрее, чем
                      читается код бумаги. Компании без логотипа просто
                      остаются без него — заглушка была бы шумом. */}
                  <span className="ms-ident">
                    <CompanyLogo
                      url={row.logo_url}
                      ticker={row.ticker}
                      alt=""
                      className="ms-logo"
                    />
                    <span className="ms-ident-text">
                      <Link to={`/company/${row.id}`}>{row.ticker}</Link>
                      <span className="ms-name" title={row.name}>{row.name}</span>
                    </span>
                  </span>
                </th>
                {row.cells.map((cell, i) => {
                  // Клетка, которую компания оставляет пустой, может быть
                  // занята её собственным показателем: у банка нет текущей
                  // ликвидности, зато есть достаточность капитала. Имя
                  // едет вместе с числом — без него цифра прочиталась бы
                  // как величина из заголовка столбца.
                  const swapped = cell != null && cell.metric !== data.columns[i].metric;
                  return (
                    <td
                      key={data.columns[i].metric}
                      className={`${cell ? cls(cell) : 'ms-cell'}${swapped ? ' ms-cell--swapped' : ''}`}
                      title={cellTitle(cell)}
                    >
                      {swapped && <u>{SWAP_LABEL[cell!.metric] ?? cell!.metric_label}</u>}
                      {/* Пройден или нет — видно по цвету клетки; галочка
                          рядом с числом только мешала его читать. Знак
                          остаётся там, где числа нет: «·» и «?» объясняют
                          пустую клетку. */}
                      {(!cell || cell.status === 'n/a' || cell.status === 'unknown')
                        && <b>{cell ? MARK[cell.status] : '—'}</b>}
                      <i>{cellValue(cell)}</i>
                    </td>
                  );
                })}
                <SafetyCell safety={row.safety} />
                <td className="ms-total">
                  {row.clears ? (
                    <b className="ms-clear-mark">прошла</b>
                  ) : (
                    <span>
                      {row.passed}/{row.checked}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const LEDE: Record<string, string> = {
  defensive: 'семь требований защитного инвестора из гл. 14 «Разумного инвестора» с отраслевыми порогами и наши проверки отдачи и денежного потока',
  enterprising: 'требования активного инвестора из гл. 15 «Разумного инвестора» с отраслевыми порогами и наши проверки отдачи и денежного потока',
};

export default function MarketScreen() {
  const [params, setParams] = useSearchParams();
  const view = params.get('view') === 'table' ? 'table' : params.get('view') === 'compare' ? 'compare' : 'sieve';
  const [standard, setStandard] = useState('defensive');
  const [allCompanies, setAllCompanies] = useState(false);

  const { data, isLoading, error } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', standard, allCompanies],
    queryFn: () => fetchMarketScreen(standard, allCompanies),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="ms">
      <header className="sc-head">
        <div>
          <h1>Скринер</h1>
          <p className="sc-lede">{LEDE[standard] ?? ''}</p>
        </div>
        <nav className="sc-switch" aria-label="Чьи требования">
          {(['defensive', 'enterprising'] as const).map((key) => (
            <button key={key} type="button" className={standard === key ? 'is-on' : ''}
              aria-pressed={standard === key} onClick={() => setStandard(key)}>
              {key === 'defensive' ? 'Защитный инвестор' : 'Активный инвестор'}
            </button>
          ))}
          <span className="sc-switch-gap" />
          <button type="button" className={`sc-view ${view === 'sieve' ? 'is-on' : ''}`} onClick={() => setParams({})}>Отбор</button>
          <button type="button" className={`sc-view ${view === 'table' ? 'is-on' : ''}`} onClick={() => setParams({ view: 'table' })}>Полная таблица</button>
          <button type="button" className={`sc-view ${view === 'compare' ? 'is-on' : ''}`} onClick={() => setParams({ view: 'compare' })}>Сравнение</button>
        </nav>
        <label className="ms-all" title="Непроверенные данные выглядят так же, как настоящие">
          <input type="checkbox" checked={allCompanies} onChange={(e) => setAllCompanies(e.target.checked)} />
          показать и непроверенные отчёты
        </label>
      </header>

      {isLoading && <div className="ms-state">Считаем…</div>}
      {error && <div className="ms-state ms-state--error">Не удалось посчитать скринер</div>}

      {view === 'compare'
        ? <CompareView showTitle={false} />
        : data && (view === 'table' ? <FullTable data={data} /> : <SieveView data={data} standard={standard} />)}

      <p className="ms-footnote">
        * Порога в книге нет или он пересчитан для российского рынка —{' '}
        <Link to="/thresholds">почему и как</Link>. Не является индивидуальной инвестиционной рекомендацией.
      </p>
    </div>
  );
}
