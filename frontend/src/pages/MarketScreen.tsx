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

/** Порог столбца так, как он написан в книге (выручка — в миллиардах). */
const thresholdText = (c: MarketColumn): string => (c.metric === 'revenue' && c.book !== null
  ? `≥ ${Math.round(c.book / 1000)} млрд`
  : c.book_text.replace(/(\d)\.(\d)/g, '$1,$2'));

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
        <small>{thresholdText(s.column)}{s.column.ours && <i title="Порог отличается от книжного">*</i>}</small>
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
        <span className="sc-req"><b>Прошли все требования</b></span>
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
          <h2>{standard === 'defensive' ? 'Прошли все семь требований' : 'Прошли все требования'}
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
            <h2>Не хватило одного <span>— {groups.one.length}</span></h2>
            <ul className="sc-list">{groups.one.map(missRow)}</ul>
          </section>
        )}

        {groups.two.length > 0 && (
          <section className="sc-sec">
            <h2>Не хватило двух <span>— {groups.two.length}</span></h2>
            <ul className="sc-list">{groups.two.map(missRow)}</ul>
          </section>
        )}

        <section className="sc-sec">
          <h2>Не хватило трёх и больше <span>— {groups.rest.length}</span></h2>
          <p className="sc-empty">
            Все компании по всем требованиям — в <Link to="?view=table">полной таблице</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}

/** Тон отрезка полоски: пройдено, чуть не дотянула, не пройдено, нет числа. */
const dotTone = (cell: Verdict | null): string => {
  if (!cell || cell.status === 'n/a') return 'na';
  if (cell.status === 'unknown') return 'unknown';
  if (cell.status === 'pass') return 'pass';
  const negative = cell.value != null && cell.value < 0;
  return !negative && cell.shortfall != null && cell.shortfall <= NEAR_MISS ? 'near' : 'fail';
};

/**
 * Полная таблица на телефоне: компания — строка, требования — полоска.
 *
 * Пятнадцать колонок на экране в 375 пикселей читались только прокруткой
 * вбок, и через две колонки терялось, чья это строка. Здесь каждое требование
 * — отрезок полоски в его цвет, а по нажатию раскрывается то, ради чего
 * таблицу и открывают: что именно не прошло, на сколько и при каком пороге.
 */
function ScreenMobileList({ data, rows }: { data: MarketScreenOut; rows: MarketScreenOut['rows'] }) {
  const [open, setOpen] = useState<number | null>(null);
  const sorted = useMemo(() => [...rows].sort((a, b) => (b.passed - a.passed)
    || ((b.safety?.value_margin ?? -Infinity) - (a.safety?.value_margin ?? -Infinity))), [rows]);
  return (
    <div className="smb">
      <p className="smb-legend" aria-hidden>
        <i className="smb-dot smb-dot--pass" /> пройдено
        <i className="smb-dot smb-dot--near" /> чуть не дотянула
        <i className="smb-dot smb-dot--fail" /> не пройдено
        <i className="smb-dot smb-dot--unknown" /> нет данных
      </p>
      <ul className="smb-list">
        {sorted.map((row) => {
          const isOpen = open === row.id;
          const misses = row.cells.filter((c): c is Verdict => c != null && (c.status === 'fail' || c.status === 'unknown'));
          return (
            <li key={row.ticker} className={`smb-item${isOpen ? ' is-open' : ''}`}>
              <button type="button" className="smb-row" aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : row.id)}>
                <span className="smb-head">
                  <CompanyLogo url={row.logo_url} ticker={row.ticker} alt="" className="smb-logo" />
                  <span className="smb-name"><b>{row.ticker}</b> · {row.name}</span>
                  <span className={`smb-count${row.clears ? ' is-clear' : ''}`}>
                    {row.clears ? 'прошла все' : `${row.passed} из ${row.checked}`}
                  </span>
                </span>
                <span className="smb-bar" aria-label={`Пройдено ${row.passed} требований из ${row.checked}`}>
                  {row.cells.map((cell, i) => (
                    <i key={data.columns[i].metric} className={`smb-dot smb-dot--${dotTone(cell)}`}
                      title={`${data.columns[i].label}: ${TITLE[cell?.status ?? 'n/a']}`} />
                  ))}
                </span>
              </button>
              {isOpen && (
                <div className="smb-detail">
                  {misses.length === 0 ? (
                    <p className="smb-ok">Все требования пройдены.</p>
                  ) : (
                    <>
                      <h5 className="smb-kicker">Не прошла</h5>
                      <ul className="smb-misses">
                        {misses.map((m) => {
                          const tone = m.status === 'unknown' ? 'unknown' : dotTone(m);
                          return (
                            <li key={m.metric} className="smb-miss" title={cellTitle(m)}>
                              <span className="smb-miss-name">{m.metric_label}</span>
                              <span className="smb-miss-val">
                                <b className={`smb-tone--${tone}`}>
                                  {m.status === 'unknown' ? 'нет данных' : cellValue(m)}
                                </b>
                                {m.status !== 'unknown' && (
                                  <small>порог {m.text.replace(/(\d)\.(\d)/g, '$1,$2')}</small>
                                )}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </>
                  )}
                  <div className="smb-miss smb-safety-row">
                    <span className="smb-miss-name">Запас прочности</span>
                    {row.safety ? (
                      <span className={`smb-miss-val smb-signal ms-safety--${row.safety.signal}`}>
                        <b>{marginText(row.safety.value_margin)}</b>
                        <small>{SIGNAL_SHORT[row.safety.signal]}</small>
                      </span>
                    ) : (
                      <span className="smb-miss-val"><b className="smb-tone--unknown">не посчитан</b></span>
                    )}
                  </div>
                  <Link className="smb-open" to={`/company/${row.id}`}>Открыть карточку</Link>
                </div>
              )}
            </li>
          );
        })}
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
  const options = useMemo(() => industries(data.rows), [data.rows]);
  const rows = useMemo(() => filterRows(data.rows, query, industry), [data.rows, query, industry]);
  const narrowed = rows.length !== data.rows.length;

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
      <ScreenMobileList data={data} rows={rows} />
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
              <th className="ms-sticky">Компания</th>
              {data.columns.map((c) => (
                <th key={c.metric} title={`${c.label}\n${c.axis_label} · ${c.source}\nкнижный порог ${c.book_text}`}>
                  <span className="ms-col">{SHORT_HEAD[c.metric] ?? c.label}</span>
                  <span className="ms-col-thr">
                    {thresholdText(c)}
                    {c.ours && <i title="Порог отличается от книжного">*</i>}
                  </span>
                </th>
              ))}
              <th
                className="ms-safety"
                title={'Запас прочности: опорная оценка против цены.\n'
                  + 'Отдельный вопрос от свода — свод про компанию, сигнал про цену.'}
              >
                <span className="ms-col">Запас прочности</span>
                <span className="ms-col-thr">≥ ⅓</span>
              </th>
              <th className="ms-total">Итог</th>
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
  defensive: 'семь требований защитного инвестора — гл. 14 «Разумного инвестора»',
  enterprising: 'требования активного инвестора — гл. 15 «Разумного инвестора»',
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
        * Порога в книге нет или он пересчитан для российского рынка. Не является
        индивидуальной инвестиционной рекомендацией.
      </p>
    </div>
  );
}
