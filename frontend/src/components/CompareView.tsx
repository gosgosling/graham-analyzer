import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import type { Company } from '../types';
import { fetchCompare, fetchCompareGroups, type CompareCard, type CompareOut } from '../services/compare.api';
import './CompareView.css';

/**
 * Сравнение компаний одной отрасли — по образцу гл. 18 «Разумного
 * инвестора»: компании колонками, показатели строками, лучшее в строке
 * выделено, справа комментарий.
 *
 * Комментарий приходит с сервера и собран по правилам из тех же чисел, что
 * в таблице: новые отчёты или цена — новый комментарий. Выбор компаний
 * живёт в адресе (?ids=… или ?with=…&all=1), чтобы сравнение можно было
 * открыть ссылкой.
 */

const MAX_PICK = 5;

const ru = (x: number, d = 0) => x.toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (mln: number) => (Math.abs(mln) >= 1e6 ? `${ru(mln / 1e6, 2)} трлн` : `${ru(mln / 1e3, 0)} млрд`);
const signed = (x: number, d = 0) => `${x > 0 ? '+' : ''}${ru(x, d)}`;
const perShare = (x: number) => ru(x, Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 10 ? 1 : 2);

type Better = 'min' | 'max' | null;
interface Row {
  label: string;
  value: (c: CompareCard) => number | null;
  fmt: (v: number) => string;
  better: Better;
  /** Цвет знака: запас прочности. */
  tone?: boolean;
  tip?: string;
}
type Line = Row | { group: string };

function rows(data: CompareOut): Line[] {
  const years = Object.keys(data.companies[0]?.eps_years ?? {}).sort().reverse();
  return [
    { group: 'Цена и масштаб' },
    { label: `Цена акции на ${data.as_of.split('-').reverse().join('.')}, ₽`, value: (c) => c.price, fmt: perShare, better: null },
    { label: 'Акций в обращении, млн', value: (c) => (c.shares ? c.shares / 1e6 : null), fmt: (v) => ru(v, 0), better: null },
    { label: 'Капитализация, ₽', value: (c) => c.market_cap, fmt: money, better: null },
    { label: 'Чистый долг, ₽', value: (c) => (c.is_bank ? null : c.net_debt), fmt: money, better: 'min', tip: 'Минус — денег больше, чем долга' },
    { label: 'Балансовая стоимость на акцию, ₽', value: (c) => c.book_per_share, fmt: perShare, better: null },
    { group: 'Отчётность, последние 12 месяцев' },
    { label: 'Выручка, ₽', value: (c) => c.revenue, fmt: money, better: null },
    { label: 'Чистая прибыль, ₽', value: (c) => c.net_income, fmt: money, better: null },
    { label: 'Свободный поток, ₽', value: (c) => (c.is_bank ? null : c.fcf), fmt: money, better: null },
    { label: 'Прибыль на акцию, 12 мес., ₽', value: (c) => c.eps, fmt: perShare, better: null },
    ...years.map((y) => ({ label: `Прибыль на акцию, ${y} г., ₽`, value: (c: CompareCard) => c.eps_years[y] ?? null, fmt: perShare, better: null as Better })),
    { label: 'Дивиденд за 12 мес., ₽', value: (c) => c.dividend, fmt: perShare, better: null },
    { label: 'Дивиденды платятся подряд, лет', value: (c) => c.streak, fmt: (v) => ru(v, 0), better: 'max' },
    { group: 'Коэффициенты' },
    { label: 'Цена / прибыль', value: (c) => (c.pe && c.pe > 0 ? c.pe : null), fmt: (v) => ru(v, 1), better: 'min' },
    { label: 'Цена / балансовая стоимость', value: (c) => c.pb, fmt: (v) => ru(v, 2), better: 'min' },
    { label: 'Цена / свободный поток', value: (c) => (c.p_fcf && c.p_fcf > 0 && !c.is_bank ? c.p_fcf : null), fmt: (v) => ru(v, 1), better: 'min' },
    { label: 'Дивидендная доходность, %', value: (c) => c.dividend_yield, fmt: (v) => ru(v, 1), better: 'max' },
    { label: 'Чистая прибыль / выручка, %', value: (c) => c.net_margin, fmt: (v) => ru(v, 1), better: 'max' },
    { label: 'Прибыль / капитал (ROE), %', value: (c) => c.roe, fmt: (v) => ru(v, 1), better: 'max' },
    { label: 'ROE сверх ключевой ставки, п.п.', value: (c) => c.roe_spread, fmt: (v) => signed(v, 1), better: 'max' },
    { label: 'Оборотные активы / обязательства', value: (c) => (c.is_bank ? null : c.current_ratio), fmt: (v) => ru(v, 2), better: 'max' },
    { label: 'Обязательства / капитал', value: (c) => (c.is_bank ? null : c.debt_to_equity), fmt: (v) => ru(v, 2), better: 'min' },
    { group: 'Рост прибыли на акцию, %' },
    { label: 'за 10 лет, по средним за 3 года', value: (c) => c.growth_10, fmt: (v) => signed(v, 0), better: 'max' },
    { label: 'за 5 лет, по средним за 3 года', value: (c) => c.growth_5, fmt: (v) => signed(v, 0), better: 'max' },
    { label: 'Лет без убытка из 10', value: (c) => c.profitable_years, fmt: (v) => ru(v, 0), better: 'max' },
    { group: 'Оценка' },
    { label: 'Опорная стоимость, ₽', value: (c) => c.reference, fmt: perShare, better: null },
    {
      label: 'Запас прочности', value: (c) => c.margin, better: 'max', tone: true,
      fmt: (v) => (v < -1 ? `×${ru(1 - v, 1)}` : `${signed(Math.round(v * 100))}%`),
    },
    {
      label: 'Консервативные критерии, разделов',
      value: (c) => Object.values(c.sections).filter(Boolean).length,
      fmt: (v) => String(v),
      better: 'max',
    },
  ];
}

const SECTIONS: [string, string][] = [
  ['size', 'Размер'], ['financial', 'Финансовое положение'], ['stability', 'Стабильность'],
  ['dividends', 'Дивиденды'], ['growth', 'Рост'], ['price', 'Цена'], ['profitability', 'Рентабельность'],
];

/** «**Лукойл** стоит…» → жирное имя. */
function Bolded({ text }: { text: string }) {
  return <>{text.split('**').map((part, i) => (i % 2 ? <b key={i}>{part}</b> : <React.Fragment key={i}>{part}</React.Fragment>))}</>;
}

function bestOf(values: (number | null)[], better: Better): number | null {
  if (!better) return null;
  const known = values.map((v, i) => [v, i] as const).filter((x): x is readonly [number, number] => x[0] !== null);
  if (known.length < 2) return null;
  const pick = known.reduce((a, b) => ((better === 'min' ? b[0] < a[0] : b[0] > a[0]) ? b : a));
  return known.filter((x) => x[0] === pick[0]).length > 1 ? null : pick[1];
}

function AddCompany({ taken, onAdd }: { taken: number[]; onAdd: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: getCompanies, staleTime: 10 * 60 * 1000, enabled: open });
  const found = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s || !companies) return [];
    return companies
      .filter((c: Company) => c.id && !taken.includes(c.id)
        && ((c.ticker ?? '').toLowerCase().startsWith(s) || (c.name ?? '').toLowerCase().includes(s)))
      .slice(0, 8);
  }, [companies, q, taken]);
  if (!open) {
    return <button type="button" className="cv-add" onClick={() => setOpen(true)}>+ добавить компанию</button>;
  }
  return (
    <span className="cv-add-box">
      <input
        autoFocus
        className="cv-add-input"
        placeholder="тикер или название"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); setQ(''); } }}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {found.length > 0 && (
        <ul className="cv-add-list">
          {found.map((c: Company) => (
            <li key={c.id}>
              <button type="button" onMouseDown={() => { onAdd(c.id!); setQ(''); setOpen(false); }}>
                <b>{c.ticker}</b> {c.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

function Groups({ onPick }: { onPick: (ids: number[]) => void }) {
  const { data } = useQuery({ queryKey: ['compare-groups'], queryFn: fetchCompareGroups, staleTime: 30 * 60 * 1000 });
  const groups = (data ?? []).filter((g) => g.companies.length >= 2);
  return (
    <div className="cv-groups">
      <p className="cv-hint">Выберите отрасль — в сравнение попадут её крупнейшие компании. Состав можно поменять.</p>
      <ul>
        {groups.map((g) => (
          <li key={g.label}>
            <button type="button" onClick={() => onPick(g.companies.slice(0, 4).map((c) => c.id))}>
              <span className="cv-group-name">{g.label}</span>
              <span className="cv-group-members">{g.companies.slice(0, 4).map((c) => c.name).join(', ')}{g.companies.length > 4 ? '…' : ''}</span>
              <span className="cv-group-count">{g.companies.length}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CompareView({ showTitle = true }: { showTitle?: boolean }) {
  const [params, setParams] = useSearchParams();
  const ids = (params.get('ids') ?? '').split(',').map(Number).filter((x) => Number.isFinite(x) && x > 0);
  const withId = Number(params.get('with')) || undefined;
  const all = params.get('all') === '1';
  const view = params.get('view');
  const active = ids.length > 0 || withId !== undefined;

  const { data, isLoading, error } = useQuery({
    queryKey: ['compare', ids.join(','), withId, all],
    queryFn: () => fetchCompare(ids.length ? { ids } : { with: withId, all }),
    enabled: active,
    staleTime: 5 * 60 * 1000,
  });

  // Выбор живёт в адресе; вкладка скринера (view) сохраняется.
  const setIds = (next: number[]) => {
    const p: Record<string, string> = {};
    if (view) p.view = view;
    if (next.length) p.ids = next.join(',');
    setParams(p);
  };
  const shown = data?.companies.map((c) => c.id) ?? ids;
  const wide = (data?.companies.length ?? 0) > 4;

  return (
    <div className="cv">
      {showTitle && (
        <header className="cv-head">
          <h1>Сравнение компаний</h1>
          <p className="cv-lede">
            {data ? `отрасль: ${data.group} · ` : ''}по образцу гл. 18 «Разумного инвестора»
          </p>
        </header>
      )}

      <div className="cv-pick">
        {data?.companies.map((c) => (
          <span key={c.id} className="cv-chip">
            <Link to={`/company/${c.id}`}>{c.name}</Link>
            <button type="button" aria-label={`Убрать ${c.name}`} onClick={() => setIds(shown.filter((x) => x !== c.id))}>×</button>
          </span>
        ))}
        {shown.length < MAX_PICK && <AddCompany taken={shown} onAdd={(id) => setIds([...shown, id])} />}
        {data && data.group_size > data.companies.length && (
          <span className="cv-muted">
            · вся отрасль:{' '}
            <button type="button" className="cv-link" onClick={() => {
              const p: Record<string, string> = { with: String(data.companies[0].id), all: '1' };
              if (view) p.view = view;
              setParams(p);
            }}
            >
              {data.group} ({data.group_size})
            </button>
          </span>
        )}
        {active && <button type="button" className="cv-link cv-reset" onClick={() => setIds([])}>сбросить</button>}
      </div>

      {!active && <Groups onPick={setIds} />}
      {active && isLoading && <p className="cv-state">Собираем таблицу…</p>}
      {error && <p className="cv-state">Не удалось собрать сравнение.</p>}

      {data && data.companies.length < 2 && (
        <p className="cv-state">Добавьте ещё хотя бы одну компанию — сравнивать не с чем.</p>
      )}

      {data && data.companies.length >= 2 && (
        <div className={`cv-grid${wide ? ' cv-grid--wide' : ''}`}>
          <section className="cv-main">
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead>
                  <tr>
                    <th className="cv-asof">данные на {data.as_of.split('-').reverse().join('.')}</th>
                    {data.companies.map((c) => (
                      <th key={c.id}><span className="cv-tk">{c.ticker}</span>{c.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows(data).map((r) => {
                    if ('group' in r) {
                      return <tr key={r.group} className="cv-g"><td colSpan={data.companies.length + 1}>{r.group}</td></tr>;
                    }
                    const values = data.companies.map(r.value);
                    const best = bestOf(values, r.better);
                    return (
                      <tr key={r.label}>
                        <th title={r.tip}>{r.label}</th>
                        {values.map((v, i) => (
                          <td
                            key={data.companies[i].id}
                            className={[i === best ? 'cv-best' : '', r.tone && v !== null ? (v < 0 ? 'cv-down' : 'cv-up') : ''].join(' ').trim() || undefined}
                          >
                            {v === null ? '—' : r.fmt(v)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="cv-note">
              Выделено лучшее значение в строке. Прибыль на акцию — без разовых статей; рост — по средним за три
              года, чтобы один год не решал за десять.
            </p>
          </section>

          <aside className="cv-side">
            <h2>Комментарий</h2>
            <div className="cv-comment">
              {data.comment.map((p, i) => <p key={i}><Bolded text={p} /></p>)}
            </div>
            <h2 className="cv-h2-gap">Свод защитного инвестора</h2>
            <table className="cv-crit">
              <thead>
                <tr><th />{data.companies.map((c) => <th key={c.id}>{c.ticker}</th>)}</tr>
              </thead>
              <tbody>
                {SECTIONS.map(([key, label]) => (
                  <tr key={key}>
                    <th>{label}</th>
                    {data.companies.map((c) => {
                      const ok = c.sections[key];
                      return (
                        <td key={c.id} className={ok == null ? 'cv-na' : ok ? 'cv-ok' : 'cv-no'}>
                          {ok == null ? '·' : ok ? '✓' : '✗'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </aside>
        </div>
      )}
    </div>
  );
}
