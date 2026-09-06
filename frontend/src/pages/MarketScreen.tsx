import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchMarketScreen,
  type MarketScreenOut,
  type ScreenStatus,
  type Verdict,
} from '../services/screen.api';
import './MarketScreen.css';

/**
 * Экран Грэма по всему рынку: один свод критериев, все компании, столбец на
 * критерий.
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

const cls = (status: ScreenStatus) => `ms-cell ms-cell--${status.replace('/', '')}`;

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
  if (v.note) parts.push(v.note);
  return parts.join('\n');
};

export default function MarketScreen() {
  const [standard, setStandard] = useState('defensive');
  const [allCompanies, setAllCompanies] = useState(false);

  const { data, isLoading, error } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', standard, allCompanies],
    queryFn: () => fetchMarketScreen(standard, allCompanies),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="ms">
      <header className="ms-head">
        <h1>Экран Грэма</h1>
        <p className="ms-lede">
          Критерии глав 14 и 15 «Разумного инвестора», применённые ко всей проверенной
          части базы. Пороги, у которых отрасль имеет свою полосу, сдвинуты
          пропорционально: профиль промышленной компании — это в точности числа Грэма,
          и остальные отрасли читаются как «во сколько раз мягче или строже». Книжное
          значение остаётся в подсказке каждой ячейки.
        </p>
      </header>

      <div className="ms-controls">
        <div className="ms-standards">
          <button
            type="button"
            className={`ms-std${standard === 'defensive' ? ' is-on' : ''}`}
            onClick={() => setStandard('defensive')}
          >
            Защитный инвестор
            <em>строгий свод: качество по справедливой цене</em>
          </button>
          <button
            type="button"
            className={`ms-std${standard === 'enterprising' ? ' is-on' : ''}`}
            onClick={() => setStandard('enterprising')}
          >
            Активный инвестор
            <em>мягче по качеству, строже по цене</em>
          </button>
        </div>

        <label className="ms-all" title="Непроверенные данные выглядят в таблице так же, как настоящие">
          <input
            type="checkbox"
            checked={allCompanies}
            onChange={(e) => setAllCompanies(e.target.checked)}
          />
          вся база, включая непроверенное
        </label>
      </div>

      {isLoading && <div className="ms-state">Считаем…</div>}
      {error && <div className="ms-state ms-state--error">Не удалось посчитать экран</div>}

      {data && (
        <>
          <div className="ms-summary">
            <span className="ms-cleared">
              Прошли целиком: <b>{data.summary.cleared}</b> из {data.summary.total}
            </span>
            {data.summary.cleared === 0 && (
              <span className="ms-note">
                Ни одна компания не проходит свод полностью — это результат, а не сбой.
              </span>
            )}
          </div>

          <div className="ms-scroll">
            <table className="ms-table">
              <thead>
                <tr>
                  <th className="ms-sticky">Компания</th>
                  {data.columns.map((c) => (
                    <th key={c.metric} title={`${c.axis_label} · ${c.source}\nкнижный порог ${c.book_text}`}>
                      <span className="ms-col">{c.label}</span>
                      <span className="ms-col-thr">
                        {c.metric === 'revenue' && c.book !== null
                          ? `≥ ${Math.round(c.book / 1000)} млрд`
                          : c.book_text.replace(/(\d)\.(\d)/g, '$1,$2')}
                        {c.ours && <i title="Порог наш, а не книжный"> ·наш</i>}
                      </span>
                    </th>
                  ))}
                  <th className="ms-total">Итог</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.ticker} className={row.clears ? 'is-clear' : undefined}>
                    <th className="ms-sticky" title={row.profile_label}>
                      <Link to={`/company/${row.id}`}>{row.ticker}</Link>
                      <span className="ms-name">{row.name}</span>
                    </th>
                    {row.cells.map((cell, i) => (
                      <td
                        key={data.columns[i].metric}
                        className={cell ? cls(cell.status) : 'ms-cell'}
                        title={cellTitle(cell)}
                      >
                        <b>{cell ? MARK[cell.status] : '—'}</b>
                        <i>{cellValue(cell)}</i>
                      </td>
                    ))}
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

          <section className="ms-fails">
            <h2>Что валит чаще всего</h2>
            <p>
              Столбец, по которому не проходит большинство, говорит уже не о компаниях.
              Либо мерка чужая для этого рынка, либо у рынка есть общая черта, которую
              критерий и ловит.
            </p>
            <ul>
              {Object.entries(data.summary.fails).map(([metric, count]) => {
                const column = data.columns.find((c) => c.metric === metric);
                const share = count / data.summary.total;
                return (
                  <li key={metric}>
                    <span className="ms-fail-label">{column?.label ?? metric}</span>
                    <span className="ms-fail-bar">
                      <i style={{ width: `${Math.round(share * 100)}%` }} />
                    </span>
                    <span className="ms-fail-count">
                      {count} из {data.summary.total}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
