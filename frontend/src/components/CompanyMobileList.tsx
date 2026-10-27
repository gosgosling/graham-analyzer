import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchMarketScreen, type MarketRow, type MarketScreenOut } from '../services/screen.api';
import type { Company } from '../types';
import CompanyLogo from './CompanyLogo';
import { marginText, SIGNAL_SHORT } from './SafetyMargin';
import { SECTOR_RU } from '../utils/sectors';
import { getCompanyTable } from '../services/companies.api';
import { money } from './CompaniesTable';
import './CompanyMobileList.css';

/**
 * Список компаний для телефона: строка вместо восьми колонок.
 *
 * Таблица справочника шириной в тысячу пикселей на экране в 375 читалась
 * только прокруткой вбок — тикер уезжал, и было непонятно, чья это строка.
 * Здесь на строке то, ради чего открывают список: кто это, сколько стоит и
 * дорого ли по Грэму. Остальное — в карточке по нажатию.
 *
 * Оценка берётся из скринера: тот же запрос, тот же кэш, те же цифры, что на
 * странице скринера. У компаний без проверенной отчётности оценки нет — так и
 * пишем, а не прячем их.
 */

type Sort = 'safety' | 'cap' | 'revenue' | 'pe' | 'name';

const SORTS: { key: Sort; label: string }[] = [
  { key: 'safety', label: 'Запас прочности' },
  { key: 'cap', label: 'Капитализация' },
  { key: 'revenue', label: 'Выручка' },
  { key: 'pe', label: 'P/E' },
  { key: 'name', label: 'Название' },
];

/**
 * Стрелка порядка на выбранной кнопке. Запас по умолчанию — от большего
 * (сначала дешёвые), P/E — от меньшего, название — от А.
 */
const arrow = (key: Sort, reversed: boolean): string => {
  if (key === 'name') return reversed ? ' Я→А' : ' А→Я';
  const down = key === 'safety' || key === 'cap' || key === 'revenue' ? !reversed : reversed;
  return down ? ' ↓' : ' ↑';
};

const ru = (n: number, digits = 1) => n.toLocaleString('ru-RU', { maximumFractionDigits: digits });

/** P/E по средней за три года — тот же, что в скринере. */
function peOf(row: MarketRow | undefined, data: MarketScreenOut | undefined): number | null {
  if (!row || !data) return null;
  const i = data.columns.findIndex((c) => c.metric === 'pe_average');
  const v = i >= 0 ? row.cells[i]?.value : null;
  return typeof v === 'number' ? v : null;
}

export default function CompanyMobileList({ companies }: { companies: Company[] }) {
  const [sort, setSort] = useState<Sort>('safety');
  // Повторное нажатие на ту же кнопку переворачивает порядок: «сначала
  // дорогие» или «сначала с большим P/E» тоже бывает нужно.
  const [reversed, setReversed] = useState(false);
  const pick = (key: Sort) => {
    if (key === sort) setReversed((r) => !r);
    else { setSort(key); setReversed(false); }
  };
  // Ключ совпадает со страницей скринера: второй раз не считается.
  const { data } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', 'defensive', false],
    queryFn: () => fetchMarketScreen('defensive', false),
    staleTime: 5 * 60 * 1000,
  });

  // Капитализация и выручка — из таблицы компаний: тот же запрос, что у
  // таблицы на компьютере.
  const { data: table } = useQuery({
    queryKey: ['companies-table'],
    queryFn: getCompanyTable,
    staleTime: 5 * 60 * 1000,
  });
  const facts = useMemo(() => new Map((table?.rows ?? []).map((r) => [r.id, r])), [table]);

  const rows = useMemo(() => {
    const byId = new Map((data?.rows ?? []).map((r) => [r.id, r]));
    const items = companies.map((c) => ({ company: c, row: c.id ? byId.get(c.id) : undefined }));
    const name = (a: (typeof items)[number]) => a.company.name || a.company.ticker || '';
    const dir = reversed ? -1 : 1;
    items.sort((a, b) => {
      if (sort === 'name') return dir * name(a).localeCompare(name(b), 'ru');
      // Без оценки — в конец при любом числовом порядке: «нет данных» не
      // самое дешёвое и не самое дорогое.
      const value = (x: (typeof items)[number]): number | null => {
        const f = x.company.id ? facts.get(x.company.id) : undefined;
        if (sort === 'safety') return x.row?.safety?.value_margin ?? null;
        if (sort === 'cap') return f?.market_cap ?? null;
        if (sort === 'revenue') return f?.revenue ?? null;
        return peOf(x.row, data);
      };
      const va = value(a);
      const vb = value(b);
      if (va === null && vb === null) return name(a).localeCompare(name(b), 'ru');
      if (va === null) return 1;
      if (vb === null) return -1;
      return dir * (sort === 'pe' ? va - vb : vb - va);
    });
    return items;
  }, [companies, data, facts, sort, reversed]);

  return (
    <div className="cml">
      <div className="cml-sorts" role="group" aria-label="Порядок">
        {SORTS.map((s) => (
          <button key={s.key} type="button" className={`cml-chip${sort === s.key ? ' is-on' : ''}`}
            aria-pressed={sort === s.key} onClick={() => pick(s.key)}>
            {s.label}{sort === s.key ? arrow(s.key, reversed) : ''}
          </button>
        ))}
      </div>
      <ul className="cml-list">
        {rows.map(({ company, row }) => {
          const safety = row?.safety ?? null;
          const pe = peOf(row, data);
          const sector = row?.profile_label?.split(' / ')[0]
            ?? (company.sector ? SECTOR_RU[company.sector] ?? company.sector : null);
          const f = company.id ? facts.get(company.id) : undefined;
          const meta = [
            sector,
            safety?.price != null ? `${ru(safety.price, safety.price < 100 ? 2 : 0)} ₽` : null,
            sort === 'cap' && f?.market_cap != null ? `кап. ${money(f.market_cap)}` : null,
            sort === 'revenue' && f?.revenue != null ? `выручка ${money(f.revenue)}` : null,
            pe !== null ? `P/E ${ru(pe)}` : null,
          ].filter(Boolean).join(' · ');
          return (
            <li key={company.figi}>
              <Link to={`/company/${company.id}`} className="cml-row">
                <CompanyLogo url={company.brand_logo_url} ticker={company.ticker} alt="" className="cml-logo" />
                <span className="cml-name">
                  <b><span className="cml-ticker">{company.ticker}</span> · {company.name}</b>
                  {meta && <small>{meta}</small>}
                </span>
                <span className="cml-right">
                  {/* Цвет — сигнал скринера, а не знак числа: «+81%» бывает
                      красным, когда цене мешает долг или доходность ниже ОФЗ. Без
                      подписи такой цвет читался бы как ошибка. */}
                  {safety ? (
                    <>
                      <b className={`ms-safety--${safety.signal}`} title={safety.reason ?? undefined}>
                        {marginText(safety.value_margin)}
                      </b>
                      <small className={`ms-safety--${safety.signal}`}>{SIGNAL_SHORT[safety.signal]}</small>
                    </>
                  ) : (
                    <b className="cml-none" title="Запас не посчитан: мало проверенных отчётов">—</b>
                  )}
                  {row ? (
                    <small className={row.clears ? 'cml-clears' : undefined}>
                      {row.clears ? 'прошла все' : `${row.passed} из ${row.checked}`}
                    </small>
                  ) : (
                    <small className="cml-none">нет оценки</small>
                  )}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
