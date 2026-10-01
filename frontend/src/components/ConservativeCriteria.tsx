import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchPassport, type PassportOut, type ScreenStatus, type Verdict } from '../services/screen.api';
import CompanyPassport from './CompanyPassport';
import './ConservativeCriteria.css';

/**
 * Консервативные критерии — свод глав 14 и 15 «Разумного инвестора» одной
 * таблицей: раздел, его показатели друг под другом, значение, наш порог,
 * порог в книге.
 *
 * Называются они консервативными, а не «критериями Грэма», потому что пороги
 * местами наши: двадцати лет дивидендов у российского рынка нет, текущая
 * ликвидность нефтяника по книжной мерке проваливается, а книжные 100 млн $
 * 1971 года пересчитаны. Книжный порог стоит рядом — расхождение видно, а не
 * спрятано. Проверки, которых в книге нет вовсе, помечены «наше».
 *
 * Раздел проходит, только когда пройдены все его строки: баллов у Грэма нет.
 */

const STANDARDS: { key: string; label: string; hint: string }[] = [
  { key: 'defensive', label: 'Защитный инвестор', hint: 'Глава 14: строгие пороги для того, кто не следит за рынком' },
  { key: 'enterprising', label: 'Активный инвестор', hint: 'Глава 15: мягче по истории, строже по цене' },
];

/** Подписи разделов короче серверных: «Динамика цен» здесь про уровень цены. */
const AXIS_LABEL: Record<string, string> = { price: 'Цена' };

const num = (v: number, digits: number) =>
  v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace('-', '−');

/** Десятичная запятая и в порогах: «≥ 33.3» — не по-русски. */
const comma = (text: string) => text.replace(/(\d)\.(\d)/g, '$1,$2');

/** Крупные суммы словами: 3 919 444 млн читается хуже, чем 3,92 трлн. */
function money(mln: number): string {
  const abs = Math.abs(mln);
  if (abs >= 1_000_000) return `${num(mln / 1_000_000, 2)} трлн ₽`;
  if (abs >= 1_000) return `${num(mln / 1_000, 0)} млрд ₽`;
  return `${num(mln, 0)} млн ₽`;
}

const isGrowth = (key: string) => key.startsWith('earnings_growth') || key.startsWith('cash_growth');

function value(v: Verdict): string {
  if (v.value === null) return '—';
  if (v.unit === 'млн ₽') return money(v.value);
  if (v.unit === 'лет') {
    return v.of !== null && v.of !== undefined && v.of !== v.value
      ? `${num(v.value, 0)} из ${num(v.of, 0)}`
      : num(v.value, 0);
  }
  if (v.unit === '%') {
    const sign = isGrowth(v.metric) && v.value > 0 ? '+' : '';
    return `${sign}${num(v.value, Math.abs(v.value) >= 100 ? 0 : 1)}%`;
  }
  return num(v.value, Math.abs(v.value) >= 10 ? 1 : 2);
}

/** Порог с единицей: «≥ 50 000» у выручки — это миллионы рублей. */
function threshold(text: string, v: Verdict): string {
  const t = comma(text);
  if (!/\d/.test(t)) return t;
  if (v.unit === 'млн ₽') {
    return t.replace(/\d[\d\s]*\d|\d/, (m) => money(Number(m.replace(/\s/g, ''))));
  }
  if (v.unit === '%') return `${t}%`;
  return t;
}

/** Проверки, которых в книге нет: поток, короткие окна, рентабельность. */
const isOurs = (v: Verdict) => /наше|у Грэма нет|у Грэма банков нет/i.test(v.source);

function sectionStatus(verdicts: Verdict[]): ScreenStatus {
  if (verdicts.some((v) => v.status === 'fail')) return 'fail';
  if (verdicts.some((v) => v.status === 'unknown')) return 'unknown';
  return 'pass';
}

const SECTION_WORD: Record<ScreenStatus, string> = {
  pass: 'пройден',
  fail: 'не пройден',
  unknown: 'нет данных',
  'n/a': 'не применяется',
};

function Mark({ v }: { v: Verdict }) {
  if (v.status === 'pass') {
    return (
      <span className={`cc-mark ${v.marginal ? 'cc-mark--marginal' : 'cc-mark--pass'}`}
        title={v.marginal ? 'Пройден по мягкому краю: значение в полосе «терпимо», а не «хорошо»' : 'Пройден'}>
        ✓
      </span>
    );
  }
  if (v.status === 'fail') {
    const tip = v.shortfall !== null && v.shortfall !== undefined
      ? `Не пройден: не хватило ${num(v.shortfall * 100, 0)}% порога`
      : 'Не пройден';
    return <span className="cc-mark cc-mark--fail" title={tip}>✗</span>;
  }
  return (
    <span className="cc-mark cc-mark--unknown" title={v.distorted ? 'Величина искажена — знаменатель не отражает бизнес' : 'Нет данных'}>
      {v.distorted ? 'иск.' : '?'}
    </span>
  );
}

export default function ConservativeCriteria({ companyId }: { companyId: number }) {
  const [standard, setStandard] = useState('defensive');
  const [details, setDetails] = useState(false);
  const { data, isLoading, error } = useQuery<PassportOut>({
    queryKey: ['screen-passport', companyId],
    queryFn: () => fetchPassport(companyId),
    staleTime: 5 * 60 * 1000,
  });

  const head = (
    <div className="cc-head">
      <h2 className="cd-section-title">Консервативные критерии</h2>
      <span className="seg" role="radiogroup" aria-label="Чьи пороги">
        {STANDARDS.map((s) => (
          <button
            key={s.key}
            type="button"
            role="radio"
            aria-checked={standard === s.key}
            className={standard === s.key ? 'seg-btn is-on' : 'seg-btn'}
            title={s.hint}
            onClick={() => setStandard(s.key)}
          >
            {s.label}
          </button>
        ))}
      </span>
    </div>
  );

  if (isLoading) return <>{head}<div className="cc-state">Считаем критерии…</div></>;
  const result = data?.screens?.[standard];
  if (error || !data || !result) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return <>{head}<div className="cc-state">{detail ?? 'Критерии не посчитаны: не хватает отчётов.'}</div></>;
  }

  const sections = data.order
    .map((axis) => ({
      axis,
      label: AXIS_LABEL[axis] ?? data.axes[axis]?.label ?? axis,
      verdicts: result.verdicts.filter((v) => v.axis === axis && v.status !== 'n/a'),
    }))
    .filter((s) => s.verdicts.length > 0);
  const passed = sections.filter((s) => sectionStatus(s.verdicts) === 'pass').length;

  return (
    <>
      {head}
      <p className="cc-lede">
        По главам 14 и 15 «Разумного инвестора» Грэма. Где наш порог отличается от книжного, рядом сказано
        почему; «наше» — проверки, которых в книге нет. Пороги: {data.profile.label.toLowerCase()}.
      </p>
      <div className="cc-table-wrap">
        <table className="cc-table">
          <colgroup>
            <col className="cc-col-section" />
            <col />
            <col className="cc-col-num" />
            <col className="cc-col-num" />
            <col className="cc-col-book" />
            <col className="cc-col-mark" />
          </colgroup>
          <thead>
            <tr>
              <th>Раздел</th>
              <th>Показатель</th>
              <th className="is-num">Значение</th>
              <th className="is-num">Наш порог</th>
              <th className="is-num">В книге</th>
              <th className="is-mark">Итог</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((s) => {
              const status = sectionStatus(s.verdicts);
              return s.verdicts.map((v, i) => (
                <tr key={`${s.axis}-${v.metric}`} className={i === s.verdicts.length - 1 ? 'cc-last' : undefined}>
                  {i === 0 && (
                    <td rowSpan={s.verdicts.length} className="cc-section">
                      <span className="cc-section-name">{s.label}</span>
                      <span className={`cc-section-status cc-section-status--${status === 'n/a' ? 'unknown' : status}`}>
                        {SECTION_WORD[status]}
                      </span>
                    </td>
                  )}
                  <td className="cc-metric">
                    <span>{v.metric_label}</span>
                    {isOurs(v) && <span className="cc-ours" title={v.source}>наше</span>}
                    {(v.note || v.caveat) && <small>{comma(v.caveat ?? v.note ?? '')}</small>}
                  </td>
                  <td className="is-num cc-value">{value(v)}</td>
                  <td className="is-num" title={v.adjusted ? 'Порог сдвинут под отрасль' : undefined}>
                    {threshold(v.text, v)}
                  </td>
                  <td className="is-num cc-book" title={v.source}>
                    {isOurs(v) ? '—' : threshold(v.book_text, v)}
                  </td>
                  <td className="is-mark"><Mark v={v} /></td>
                </tr>
              ));
            })}
          </tbody>
        </table>
      </div>
      <div className="cc-foot">
        <span>
          Пройдено разделов: {passed} из {sections.length}. Раздел пройден, когда пройдены все его строки.
        </span>
        <button type="button" className="cc-more" aria-expanded={details} onClick={() => setDetails((v) => !v)}>
          {details ? 'Скрыть подробности' : 'Подробно: ряды по годам для каждого раздела ▸'}
        </button>
      </div>
      {details && (
        <div className="cc-details">
          <CompanyPassport companyId={companyId} />
        </div>
      )}
    </>
  );
}
