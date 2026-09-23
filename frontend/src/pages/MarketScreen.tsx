import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchMarketScreen,
  type MarketScreenOut,
  type RowSafety,
  type ScreenStatus,
  type Verdict,
} from '../services/screen.api';
import CompanyLogo from '../components/CompanyLogo';
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

/** Короткая подпись сигнала: в колонку шириной в два слова длинная не влезет. */
const SIGNAL_SHORT: Record<RowSafety['signal'], string> = {
  favourable: 'дёшево',
  acceptable: 'умеренно',
  fair: 'вровень',
  expensive: 'дорого',
  bond_better: 'ОФЗ лучше',
  dangerous: 'опасная',
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
      {margin !== null && (
        <i>{margin > 0 ? '+' : ''}{Math.round(margin * 100)}%</i>
      )}
    </td>
  );
}

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
                  <th
                    className="ms-safety"
                    title={'Запас прочности: опорная оценка против цены.\n'
                      + 'Отдельный вопрос от свода — свод про компанию, сигнал про цену.'}
                  >
                    <span className="ms-col">Цена</span>
                    <span className="ms-col-thr">запас ≥ ⅓</span>
                  </th>
                  <th className="ms-total">Итог</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.ticker} className={row.clears ? 'is-clear' : undefined}>
                    <th className="ms-sticky" title={row.profile_label}>
                      {/* Логотип перед тикером: в таблице на три десятка
                          строк знакомый кружок находится быстрее, чем
                          читается код бумаги. Компании без логотипа просто
                          остаются без него — заглушка была бы шумом. */}
                      <span className="ms-ident">
                        <CompanyLogo
                          url={row.logo_url}
                          alt=""
                          className="ms-logo"
                        />
                        <span className="ms-ident-text">
                          <Link to={`/company/${row.id}`}>{row.ticker}</Link>
                          <span className="ms-name">{row.name}</span>
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
                          <b>{cell ? MARK[cell.status] : '—'}</b>
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
