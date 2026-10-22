import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchMarketScreen, type MarketRow, type MarketScreenOut } from '../services/screen.api';
import type { Company } from '../types';
import CompanyLogo from './CompanyLogo';
import { marginText, SIGNAL_SHORT } from './SafetyMargin';
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

/** Отрасли T-Invest по-русски — для компаний, у которых нет профиля скринера. */
const SECTOR_RU: Record<string, string> = {
  materials: 'сырьё',
  utilities: 'энергетика',
  consumer: 'потребительский',
  financial: 'финансы',
  energy: 'нефть и газ',
  it: 'IT',
  industrials: 'промышленность',
  telecom: 'телеком',
  health_care: 'здравоохранение',
  real_estate: 'недвижимость',
  other: 'прочее',
};

type Sort = 'safety' | 'pe' | 'name';

const SORTS: { key: Sort; label: string }[] = [
  { key: 'safety', label: 'Запас прочности' },
  { key: 'pe', label: 'P/E' },
  { key: 'name', label: 'Название' },
];

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
  // Ключ совпадает со страницей скринера: второй раз не считается.
  const { data } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', 'defensive', false],
    queryFn: () => fetchMarketScreen('defensive', false),
    staleTime: 5 * 60 * 1000,
  });

  const rows = useMemo(() => {
    const byId = new Map((data?.rows ?? []).map((r) => [r.id, r]));
    const items = companies.map((c) => ({ company: c, row: c.id ? byId.get(c.id) : undefined }));
    const name = (a: (typeof items)[number]) => a.company.name || a.company.ticker || '';
    items.sort((a, b) => {
      if (sort === 'name') return name(a).localeCompare(name(b), 'ru');
      // Без оценки — в конец при любом числовом порядке: «нет данных» не
      // самое дешёвое и не самое дорогое.
      const va = sort === 'safety' ? a.row?.safety?.value_margin ?? null : peOf(a.row, data);
      const vb = sort === 'safety' ? b.row?.safety?.value_margin ?? null : peOf(b.row, data);
      if (va === null && vb === null) return name(a).localeCompare(name(b), 'ru');
      if (va === null) return 1;
      if (vb === null) return -1;
      return sort === 'safety' ? vb - va : va - vb;
    });
    return items;
  }, [companies, data, sort]);

  return (
    <div className="cml">
      <div className="cml-sorts" role="group" aria-label="Порядок">
        {SORTS.map((s) => (
          <button key={s.key} type="button" className={`cml-chip${sort === s.key ? ' is-on' : ''}`}
            aria-pressed={sort === s.key} onClick={() => setSort(s.key)}>
            {s.label}{sort === s.key && s.key !== 'name' ? (s.key === 'safety' ? ' ↓' : ' ↑') : ''}
          </button>
        ))}
      </div>
      <ul className="cml-list">
        {rows.map(({ company, row }) => {
          const safety = row?.safety ?? null;
          const pe = peOf(row, data);
          const sector = row?.profile_label?.split(' / ')[0]
            ?? (company.sector ? SECTOR_RU[company.sector] ?? company.sector : null);
          const meta = [
            sector,
            safety?.price != null ? `${ru(safety.price, safety.price < 100 ? 2 : 0)} ₽` : null,
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
                      красным, когда цене мешает долг или ОФЗ выгоднее. Без
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
