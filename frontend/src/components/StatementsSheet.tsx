import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { FinancialReport } from '../types';
import { buildColumns, derived, type Column } from '../utils/statements';
import { downloadSheet, type ExportFormat, type Sheet } from '../utils/tableExport';
import DownloadLinks from './DownloadLinks';
import './StatementsSheet.css';

/**
 * «Отчётность» — показатели, как они стоят в отчётах компании, по периодам.
 * Без нормализации и подсветки по порогам: это не оценка, а первоисточник.
 * Матрица для правки у администратора — отдельная (reports-matrix).
 */

type V = Record<string, number | null>;
interface Row {
  label: string;
  get: (v: V) => number | null;
  fmt: 'money' | 'shares' | 'perShare' | 'pct' | 'ratio';
  sub?: boolean;
  tip?: string;
}
type Line = Row | { group: string; unit?: string };

const f = (key: string) => (v: V) => v[key] ?? null;
const abs = (key: string) => (v: V) => (v[key] == null ? null : Math.abs(v[key] as number));

const SHARES_AND_MARKET: Line[] = [
  { group: 'Акции и дивиденды' },
  { label: 'Акций, млн', get: derived.shares, fmt: 'shares', tip: 'Средневзвешенное за период, если указано; иначе — в обращении на дату' },
  { label: 'Прибыль на акцию, ₽', get: derived.eps, fmt: 'perShare', tip: 'Чистая прибыль по отчёту на средневзвешенное число акций' },
  { label: 'Дивиденд на акцию, ₽', get: f('dividends_per_share'), fmt: 'perShare', tip: 'Объявленный за этот год' },
  { label: 'Дивиденды, всего', get: derived.dividendsTotal, fmt: 'money' },
  { label: 'Доля прибыли на дивиденды, %', get: derived.payout, fmt: 'pct' },
  { group: 'Рынок' },
  { label: 'Цена акции на конец периода, ₽', get: f('price_per_share'), fmt: 'perShare' },
  { label: 'Капитализация', get: derived.marketCap, fmt: 'money' },
];

const GENERAL: Line[] = [
  { group: 'Прибыль и убытки', unit: 'млрд' },
  { label: 'Выручка', get: f('revenue'), fmt: 'money' },
  { label: 'Операционная прибыль', get: f('operating_profit'), fmt: 'money' },
  { label: 'Амортизация', get: abs('depreciation_amortization'), fmt: 'money' },
  { label: 'Финансовые расходы', get: abs('finance_costs'), fmt: 'money' },
  { label: 'Чистая прибыль', get: (v) => v.net_income_reported ?? v.net_income ?? null, fmt: 'money' },
  { group: 'Баланс', unit: 'млрд' },
  { label: 'Активы', get: f('total_assets'), fmt: 'money' },
  { label: 'Оборотные активы', get: f('current_assets'), fmt: 'money', sub: true },
  { label: 'Денежные средства', get: f('cash_and_equivalents'), fmt: 'money', sub: true },
  { label: 'Гудвил', get: f('goodwill'), fmt: 'money', sub: true },
  { label: 'Обязательства', get: f('total_liabilities'), fmt: 'money' },
  { label: 'Краткосрочные обязательства', get: f('current_liabilities'), fmt: 'money', sub: true },
  { label: 'Долг', get: f('debt'), fmt: 'money', sub: true },
  { label: 'Чистый долг', get: derived.netDebt, fmt: 'money', sub: true, tip: 'Долг минус денежные средства' },
  { label: 'Капитал', get: f('equity'), fmt: 'money' },
  { group: 'Денежный поток', unit: 'млрд' },
  { label: 'Операционный поток', get: f('operating_cash_flow'), fmt: 'money' },
  { label: 'Капзатраты', get: abs('capex'), fmt: 'money' },
  { label: 'Свободный поток', get: derived.fcf, fmt: 'money', tip: 'Операционный поток минус капзатраты' },
  { label: 'Проценты уплаченные', get: abs('interest_paid'), fmt: 'money' },
  { label: 'Аренда (основная часть)', get: abs('lease_principal'), fmt: 'money' },
  ...SHARES_AND_MARKET,
];

const BANK: Line[] = [
  { group: 'Доходы и расходы', unit: 'млрд' },
  { label: 'Процентные доходы', get: f('interest_income'), fmt: 'money' },
  { label: 'Процентные расходы', get: abs('interest_expense'), fmt: 'money' },
  { label: 'Чистый процентный доход', get: f('net_interest_income'), fmt: 'money' },
  { label: 'Чистый комиссионный доход', get: f('fee_commission_income'), fmt: 'money' },
  { label: 'Операционные расходы', get: abs('operating_expenses'), fmt: 'money' },
  { label: 'Расходы на резервы', get: f('provisions'), fmt: 'money' },
  { label: 'Чистая прибыль', get: (v) => v.net_income_reported ?? v.net_income ?? null, fmt: 'money' },
  { group: 'Кредиты и средства клиентов', unit: 'млрд' },
  { label: 'Активы', get: f('total_assets'), fmt: 'money' },
  { label: 'Кредиты до резервов', get: f('gross_loans'), fmt: 'money' },
  { label: 'физлицам', get: f('loans_retail'), fmt: 'money', sub: true },
  { label: 'юрлицам', get: f('loans_corporate'), fmt: 'money', sub: true },
  { label: 'Резерв под обесценение', get: f('loan_loss_allowance'), fmt: 'money', sub: true },
  { label: 'Неработающие кредиты', get: f('npl_loans'), fmt: 'money', sub: true, tip: 'Стадия 3 и POCI' },
  { label: 'Средства клиентов', get: f('customer_deposits'), fmt: 'money' },
  { label: 'физлиц', get: f('deposits_retail'), fmt: 'money', sub: true },
  { label: 'юрлиц', get: f('deposits_corporate'), fmt: 'money', sub: true },
  { label: 'Капитал', get: f('equity'), fmt: 'money' },
  { group: 'Качество и нормативы', unit: '%' },
  { label: 'Стоимость риска', get: derived.cor, fmt: 'pct', tip: 'Расходы на резервы к кредитам до резервов' },
  { label: 'Расходы к доходам', get: derived.cir, fmt: 'pct' },
  { label: 'Доля неработающих кредитов', get: derived.nplShare, fmt: 'pct' },
  { label: 'Достаточность капитала Н1.0', get: f('capital_adequacy_ratio'), fmt: 'pct' },
  { label: 'Достаточность основного капитала Н1.1', get: f('capital_adequacy_core'), fmt: 'pct' },
  ...SHARES_AND_MARKET,
];

const ru = (x: number, d: number) => x.toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });

/** Число для выгрузки — в тех же единицах, что на экране, но без округления до десятых. */
function exportValue(v: number, kind: Row['fmt']): number {
  const round = (x: number, d: number) => Math.round(x * 10 ** d) / 10 ** d;
  switch (kind) {
    case 'money': return round(v / 1000, 3);
    case 'shares': return round(v / 1e6, 3);
    case 'perShare': return round(v, 4);
    default: return round(v, 2);
  }
}

/** В свёрнутом виде — первые строки, как у листа по годам. */
const COLLAPSED_LINES = 7;

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

function format(v: number, kind: Row['fmt']): string {
  switch (kind) {
    case 'money': {
      const bn = v / 1000;
      return ru(bn, Math.abs(bn) >= 1000 ? 0 : 1);
    }
    case 'shares': {
      const mln = v / 1e6;
      return ru(mln, mln >= 100 ? 0 : 1);
    }
    case 'perShare':
      return ru(v, Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 1 ? 2 : 4);
    case 'pct':
      return `${ru(v, 1)}%`;
    default:
      return ru(v, 2);
  }
}

interface Props {
  reports: FinancialReport[];
  company?: { ticker: string; name: string };
}

export default function StatementsSheet({ reports, company }: Props) {
  const [interim, setInterim] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const cols: Column[] = useMemo(() => buildColumns(reports, interim), [reports, interim]);
  const latest = useMemo(() => [...reports].sort((a, b) => b.report_date.localeCompare(a.report_date))[0], [reports]);
  const isBank = latest?.report_type === 'bank';
  const lines = isBank ? BANK : GENERAL;
  const hasInterim = reports.some((r) => r.period_type !== 'annual');

  // Свежие периоды справа — таблица открывается прокрученной до них.
  const wrap = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    el.scrollLeft = el.scrollWidth;
    if (typeof ResizeObserver === 'undefined') return undefined;
    // На телефоне раздел открывается вкладкой: пока он скрыт, ширины нет,
    // и прокрутить некуда. Докручиваем, когда таблица получила размер.
    let width = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        if (width === 0) el.scrollLeft = el.scrollWidth;
        width = el.clientWidth;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [cols.length]);

  // Строки, где нет ни одного значения, не показываем: у компании без
  // аренды или гудвила это пустые полосы.
  const visible = lines.filter((l, i) => {
    if ('group' in l) {
      const next = lines.slice(i + 1);
      const end = next.findIndex((x) => 'group' in x);
      const body = (end < 0 ? next : next.slice(0, end)) as Row[];
      return body.some((r) => cols.some((c) => r.get(c.values) != null));
    }
    return cols.some((c) => l.get(c.values) != null);
  });

  const shown = expanded ? visible : visible.slice(0, COLLAPSED_LINES);
  // Свёрнутая таблица не должна кончаться заголовком следующей группы.
  while (!expanded && shown.length && 'group' in shown[shown.length - 1]) shown.pop();
  const hiddenRows = visible.slice(COLLAPSED_LINES).filter((l) => !('group' in l)).length;
  const collapsible = hiddenRows > 0;

  const onDownload = (format: ExportFormat) => {
    const currency = latest?.currency && latest.currency !== 'RUB' ? latest.currency : '₽';
    const sheet: Sheet = {
      title: `${company ? `${company.name} (${company.ticker}) — ` : ''}отчётность, ${interim ? 'все отчёты' : 'годы'}; `
        + `суммы в млрд ${currency}${cols.some((c) => c.currency !== (latest?.currency || 'RUB')) ? ' (у отмеченных лет — в валюте отчёта)' : ''}, `
        + 'акции в млн, как в отчётах компании',
      header: ['Показатель', ...cols.map((c) => `${c.isLtm ? '12 мес. (LTM)' : c.label}${c.currency !== 'RUB' ? ` (${c.currency})` : ''}`)],
      rows: visible.map((l) => ('group' in l
        ? { cells: [l.unit === 'млрд' ? `${l.group}, млрд` : l.group], group: true }
        : { cells: [l.sub ? `  ${l.label}` : l.label, ...cols.map((c) => {
          const v = l.get(c.values);
          return v == null ? null : exportValue(v, l.fmt);
        })] })),
    };
    const base = `${company?.ticker ?? 'company'}_отчётность_${interim ? 'все-отчёты' : 'годы'}`;
    downloadSheet(sheet, format, base, 'Отчётность');
  };

  if (!reports.length) return <p className="st-empty">Отчётов пока нет.</p>;

  return (
    <div className="st">
      <div className="st-controls">
        <span className="st-seg" role="group" aria-label="Периоды">
          <button type="button" className={!interim ? 'is-on' : ''} onClick={() => setInterim(false)}>Годы</button>
          {hasInterim && (
            <button type="button" className={interim ? 'is-on' : ''} onClick={() => setInterim(true)}>Все отчёты</button>
          )}
        </span>
        <span className="st-note">
          {interim
            ? 'Промежуточные отчёты — нарастающим итогом, как опубликованы: «9 мес.» — с января по сентябрь.'
            : cols.some((c) => c.isLtm) ? '«12 мес.» — последние двенадцать месяцев по последнему отчёту.' : ''}
          {latest && latest.currency !== 'RUB' ? ` Суммы — в валюте отчёта (${latest.currency}).` : ''}
        </span>
        <span className="st-dl"><DownloadLinks what="отчётность" onPick={onDownload} /></span>
      </div>
      <div className={`st-body${collapsible && !expanded ? ' is-collapsed' : ''}`}>
      <div className="st-wrap" ref={wrap}>
        <table className="st-table" style={{ '--st-cols': cols.length } as React.CSSProperties}>
          <thead>
            <tr>
              <th className="st-label" />
              {cols.map((c) => (
                <th key={c.key} className={c.isLtm ? 'st-ltm' : undefined} title={c.report?.report_date ? `на ${c.report.report_date.split('-').reverse().join('.')}` : undefined}>
                  {c.label}{c.currency !== 'RUB' && <span className="st-cur"> {c.currency === 'USD' ? '$' : c.currency}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => ('group' in l ? (
              <tr key={l.group} className="st-group">
                <th className="st-label">{l.group}{l.unit && <span>{l.unit === 'млрд' ? ', млрд' : ''}</span>}</th>
                <td colSpan={cols.length} />
              </tr>
            ) : (
              <tr key={l.label} className={l.sub ? 'st-sub' : undefined}>
                <th className="st-label" title={l.tip}>
                  <span className={l.tip ? 'st-tip' : undefined}>{l.label}</span>
                </th>
                {cols.map((c) => {
                  const v = l.get(c.values);
                  return (
                    <td key={c.key} className={[c.isLtm ? 'st-ltm' : '', v != null && v < 0 ? 'st-neg' : ''].join(' ').trim() || undefined}>
                      {v == null ? '' : format(v, l.fmt)}
                    </td>
                  );
                })}
              </tr>
            )))}
          </tbody>
        </table>
      </div>
      {collapsible && (
        <button type="button" className="st-expand" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
          <span>{expanded ? 'Свернуть' : `Вся отчётность · ещё ${hiddenRows} ${plural(hiddenRows, 'строка', 'строки', 'строк')}`}</span>
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
            <path d={expanded ? 'M3 10l5-5 5 5' : 'M3 6l5 5 5-5'} fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      </div>
    </div>
  );
}
