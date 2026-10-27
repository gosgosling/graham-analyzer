import React, { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { CompanyTableRow } from '../services/companies.api';
import CompanyLogo from './CompanyLogo';
import { money, sortBy } from '../utils/companyTable';
import './CompaniesTable.css';

export { money };

/**
 * Таблица компаний — как таблица акций на Investing: кто большой, кто
 * зарабатывает, у кого долг, и всё сортируется нажатием на заголовок.
 * Отчётные числа — за последние 12 месяцев, рыночные — по текущей цене.
 *
 * Сортировка в адресе (`?sort=market_cap&dir=desc`), как в скринере: таблицу,
 * отсортированную по выручке, можно отправить ссылкой.
 */

type Dir = 'asc' | 'desc';
type Key = 'company' | 'price' | 'change' | 'market_cap' | 'revenue' | 'net_income'
  | 'assets' | 'equity' | 'net_debt' | 'pe' | 'pb' | 'dividend_yield' | 'roe';

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

const priceText = (v: number | null) => (v === null ? '—' : `${ru(v, v < 10 ? 3 : v < 100 ? 2 : v < 1000 ? 1 : 0)} ₽`);
const ratio = (v: number | null) => {
  if (v === null) return '—';
  if (v < 0) return 'убыток';
  return v > 100 ? '> 100' : ru(v, 1);
};
const pct = (v: number | null, digits = 1) => (v === null ? '—' : `${ru(v, digits)}%`);

interface Column {
  key: Key;
  label: string;
  title: string;
  value: (r: CompanyTableRow) => number | string | null;
  /** Своё направление при первом нажатии: у P/E и P/B лучше меньшее. */
  dir: Dir;
  cell: (r: CompanyTableRow) => React.ReactNode;
  className?: string;
}

const COLUMNS: Column[] = [
  { key: 'price', label: 'Цена', title: 'Последняя цена, ₽', dir: 'desc',
    value: (r) => r.price, cell: (r) => priceText(r.price) },
  { key: 'change', label: 'За день', title: 'Изменение к вчерашнему закрытию', dir: 'desc',
    value: (r) => r.change,
    cell: (r) => (r.change === null ? '—' : (
      <span className={r.change > 0 ? 'ct-up' : r.change < 0 ? 'ct-down' : undefined}>
        {r.change > 0 ? '+' : r.change < 0 ? '−' : ''}{ru(Math.abs(r.change) * 100, 2)}%
      </span>
    )) },
  { key: 'market_cap', label: 'Капитализация', title: 'Цена × акции в обращении', dir: 'desc',
    value: (r) => r.market_cap, cell: (r) => money(r.market_cap) },
  { key: 'revenue', label: 'Выручка', title: 'За последние 12 месяцев; у банков — операционные доходы', dir: 'desc',
    value: (r) => r.revenue, cell: (r) => money(r.revenue) },
  { key: 'net_income', label: 'Прибыль', title: 'Чистая прибыль акционеров за последние 12 месяцев', dir: 'desc',
    value: (r) => r.net_income,
    cell: (r) => <span className={r.net_income !== null && r.net_income < 0 ? 'ct-down' : undefined}>{money(r.net_income)}</span> },
  { key: 'assets', label: 'Активы', title: 'Активы на дату последнего отчёта', dir: 'desc',
    value: (r) => r.assets, cell: (r) => money(r.assets) },
  { key: 'equity', label: 'Капитал', title: 'Капитал акционеров на дату последнего отчёта', dir: 'desc',
    value: (r) => r.equity, cell: (r) => money(r.equity) },
  { key: 'net_debt', label: 'Чистый долг', title: 'Долг минус деньги. Минус — денег больше, чем долга. У банков не считается', dir: 'asc',
    value: (r) => r.net_debt,
    cell: (r) => <span className={r.net_debt !== null && r.net_debt < 0 ? 'ct-up' : undefined}>{money(r.net_debt)}</span> },
  { key: 'pe', label: 'P/E', title: 'Капитализация к прибыли за 12 месяцев', dir: 'asc',
    value: (r) => (r.pe !== null && r.pe > 0 ? r.pe : null), cell: (r) => ratio(r.pe) },
  { key: 'pb', label: 'P/B', title: 'Капитализация к капиталу', dir: 'asc',
    value: (r) => (r.pb !== null && r.pb > 0 ? r.pb : null), cell: (r) => ratio(r.pb) },
  { key: 'dividend_yield', label: 'Див. доходн.', title: 'Дивиденды за 12 месяцев к текущей цене', dir: 'desc',
    value: (r) => r.dividend_yield, cell: (r) => pct(r.dividend_yield) },
  { key: 'roe', label: 'ROE', title: 'Прибыль к капиталу', dir: 'desc',
    value: (r) => r.roe, cell: (r) => pct(r.roe) },
];

const DIR_OF: Record<string, Dir> = Object.fromEntries([['company', 'asc'], ...COLUMNS.map((c) => [c.key, c.dir])]);

function SortArrow({ dir }: { dir: Dir | null }) {
  return (
    <svg className={`ct-sort${dir ? ' is-on' : ''}`} width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
      {dir === 'desc' && <path d="M2 3.5 5 7l3-3.5" />}
      {dir === 'asc' && <path d="M2 6.5 5 3l3 3.5" />}
      {!dir && <path d="M2 3.5 5 1l3 2.5M2 6.5 5 9l3-2.5" />}
    </svg>
  );
}

function sortRows(rows: readonly CompanyTableRow[], key: string, dir: Dir): CompanyTableRow[] {
  const column = COLUMNS.find((c) => c.key === key);
  return sortBy(rows, (r) => (key === 'company' ? r.ticker : column ? column.value(r) : null), dir);
}

export default function CompaniesTable({ rows, asof }: { rows: CompanyTableRow[]; asof?: string }) {
  const [params, setParams] = useSearchParams();
  const key = params.get('sort') ?? 'market_cap';
  const dir: Dir = params.get('dir') === 'asc' ? 'asc' : params.get('dir') === 'desc' ? 'desc' : (DIR_OF[key] ?? 'desc');
  const sorted = useMemo(() => sortRows(rows, key, dir), [rows, key, dir]);

  const onSort = (next: string) => {
    const p = new URLSearchParams(params);
    const first = DIR_OF[next] ?? 'desc';
    const nextDir: Dir = next === key ? (dir === 'asc' ? 'desc' : 'asc') : first;
    p.set('sort', next);
    p.set('dir', nextDir);
    setParams(p, { replace: true });
  };
  const dirOf = (k: string): Dir | null => (k === key ? dir : null);
  const aria = (k: string) => (k === key ? (dir === 'asc' ? 'ascending' : 'descending') : 'none');

  return (
    <div className="ct-wrap">
      <div className="ct-scroll">
      <table className="ct-table">
        <thead>
          <tr>
            <th className="ct-sticky" aria-sort={aria('company')}>
              <button type="button" className="ct-sort-btn" onClick={() => onSort('company')}>
                Компания<SortArrow dir={dirOf('company')} />
              </button>
            </th>
            {COLUMNS.map((c) => (
              <th key={c.key} className={c.className} aria-sort={aria(c.key)} title={c.title}>
                <button type="button" className="ct-sort-btn" onClick={() => onSort(c.key)}>
                  {c.label}<SortArrow dir={dirOf(c.key)} />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id}>
              <th className="ct-sticky" scope="row">
                <Link to={`/company/${r.id}`} className="ct-company">
                  <CompanyLogo url={r.logo_url} ticker={r.ticker} alt="" className="ct-logo" />
                  <span className="ct-company-text">
                    <b>{r.ticker}</b>
                    <span className="ct-name" title={r.name}>
                      {r.name}
                      {r.has_reports && !r.verified && (
                        <span className="ct-unverified" title="Отчётность аналитиком не сверена — числа предварительные">не сверено</span>
                      )}
                    </span>
                  </span>
                </Link>
              </th>
              {COLUMNS.map((c) => <td key={c.key} className={c.className}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <p className="ct-note">
        Отчётные показатели — за последние 12 месяцев по МСФО, баланс — на дату последнего отчёта; рыночные — по
        текущей цене{asof ? ` на ${asof.split('-').reverse().join('.')}` : ''}. Деньги в рублях. «Не сверено» —
        отчётность компании ещё не проверена аналитиком. Нажмите на заголовок, чтобы отсортировать.
      </p>
    </div>
  );
}
