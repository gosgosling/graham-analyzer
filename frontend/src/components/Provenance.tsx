import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { CurrentMultipliers, FinancialReport } from '../types';
import './InfoTip.css';
import './Provenance.css';

/**
 * Происхождение числа: из какого отчёта оно, когда отчёт вышел, в какой
 * валюте записан, как попал в базу и сверен ли.
 *
 * Рецензент сайта заметил справедливо: «проверено» без расшифровки ничего не
 * говорит — была ли это ручная сверка с PDF, автоматическое извлечение или
 * правка одного поля. Здесь это сказано у самого числа.
 */

export type ProvenanceRow = [string, string];

const fmtDate = (iso?: string | null) => {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split('-');
  return d && m && y ? `${d}.${m}.${y}` : null;
};

const STANDARD: Record<string, string> = { IFRS: 'МСФО', RAS: 'РСБУ', US_GAAP: 'US GAAP', UK_GAAP: 'UK GAAP' };

/** «за 2025 год», «за 6 мес. 2026», «за 9 мес. 2025». */
export function periodName(r: Pick<FinancialReport, 'period_type' | 'fiscal_year' | 'fiscal_quarter'>): string {
  if (r.period_type === 'annual') return `за ${r.fiscal_year} год`;
  if (r.period_type === 'semi_annual') return `за 6 мес. ${r.fiscal_year}`;
  const months = (r.fiscal_quarter ?? 1) * 3;
  return `за ${months} мес. ${r.fiscal_year}`;
}

/** Отчёт одной строкой: «МСФО за 2025 год». */
export function reportTitle(r: FinancialReport): string {
  const standard = STANDARD[r.accounting_standard] ?? r.accounting_standard;
  return `${standard} ${periodName(r)}${r.consolidated ? '' : ', неконсолидированная'}`;
}

function howEntered(r: FinancialReport): string {
  const auto = r.auto_extracted || (r.extraction_notes ?? '').startsWith('[AUTO-EXTRACTED');
  if (auto) return 'разобрано из PDF автоматически';
  switch (r.source) {
    case 'company_website': return 'вручную по отчёту с сайта компании';
    case 'regulator': return 'вручную по отчёту с сайта раскрытия';
    case 'api': return 'по API';
    default: return 'вручную по отчёту';
  }
}

/** Строки «Откуда» для одного отчёта. */
export function reportProvenance(r: FinancialReport): ProvenanceRow[] {
  const rows: ProvenanceRow[] = [['Отчёт', reportTitle(r)]];
  const published = fmtDate(r.filing_date);
  if (published) rows.push(['Опубликован', published]);
  const currency = (r.currency || 'RUB').toUpperCase();
  rows.push(['Единицы', currency === 'RUB'
    ? 'млн ₽, как в отчёте'
    : `млн ${currency}; в рубли — по курсу ${r.exchange_rate?.toLocaleString('ru-RU', { maximumFractionDigits: 4 }) ?? '—'} на ${fmtDate(r.report_date) ?? r.report_date}`]);
  rows.push(['Внесено', howEntered(r)]);
  const verified = fmtDate(r.verified_at);
  rows.push(['Сверка', r.verified_by_analyst ? `сверено аналитиком${verified ? ` ${verified}` : ''}` : 'аналитиком не сверено']);
  const updated = fmtDate(r.updated_at);
  if (updated && r.created_at && r.updated_at && r.updated_at.slice(0, 10) !== r.created_at.slice(0, 10)) {
    rows.push(['Правка', `последняя — ${updated}`]);
  }
  return rows;
}

/** Из чего собраны «12 месяцев». */
export function ltmComposition(current: CurrentMultipliers, reports: FinancialReport[]): string | null {
  const balance = reports.find((r) => r.id === current.balance_report_id);
  const annual = [...reports].filter((r) => r.period_type === 'annual')
    .sort((a, b) => b.report_date.localeCompare(a.report_date))[0];
  switch (current.ltm_source) {
    case 'annual':
      return annual ? `годовой отчёт ${annual.fiscal_year}` : 'годовой отчёт';
    case 'semi_annual_derived':
      return balance && annual
        ? `${annual.fiscal_year} год + 6 мес. ${balance.fiscal_year} − 6 мес. ${balance.fiscal_year - 1}`
        : 'год + полугодие − прошлое полугодие';
    case 'quarterly_3_derived':
      return balance && annual
        ? `${annual.fiscal_year} год + 9 мес. ${balance.fiscal_year} − 9 мес. ${balance.fiscal_year - 1}`
        : 'год + 9 мес. − прошлые 9 мес.';
    case 'ytd_full_year':
      return 'отчёт за полный год';
    default:
      return null;
  }
}

/** Строки «Откуда» для столбца «12 мес.». */
export function ltmProvenance(current: CurrentMultipliers, reports: FinancialReport[]): ProvenanceRow[] {
  const rows: ProvenanceRow[] = [];
  const composition = ltmComposition(current, reports);
  if (composition) rows.push(['12 месяцев', composition]);
  const price = fmtDate(current.date);
  if (price) rows.push(['Цена', `Мосбиржа, ${price}`]);
  const balance = reports.find((r) => r.id === current.balance_report_id);
  if (balance) {
    rows.push(['Баланс', `на ${fmtDate(balance.report_date)}`]);
    rows.push(...reportProvenance(balance));
  }
  return rows;
}

/** Короткая строка для телефонного списка: «МСФО за 2025 год · опубл. 05.03.2026 · сверено». */
export function provenanceLine(rows: ProvenanceRow[]): string {
  const get = (k: string) => rows.find(([label]) => label === k)?.[1];
  return [get('12 месяцев') ?? get('Отчёт'), get('Опубликован') && `опубл. ${get('Опубликован')}`,
    get('Сверка')?.startsWith('сверено') ? 'сверено' : 'не сверено']
    .filter(Boolean).join(' · ');
}

/**
 * Окошко у числа. Без затемнения: страницу под ним можно листать; закрывается
 * нажатием мимо или Esc. Положение — под якорем, в пределах экрана.
 */
export function ProvenancePopover({ anchor, title, explain, rows, onOpenReport, onClose }: {
  anchor: HTMLElement;
  title: string;
  /** Пояснение из подсказки ячейки — то, что видно при наведении. */
  explain?: string | null;
  rows: ProvenanceRow[];
  onOpenReport?: () => void;
  onClose: () => void;
}) {
  const bubble = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; arrow: number } | null>(null);

  useLayoutEffect(() => {
    const place = () => {
      const b = anchor.getBoundingClientRect();
      const w = bubble.current?.offsetWidth ?? 320;
      const centre = b.left + b.width / 2;
      const left = Math.max(12, Math.min(window.innerWidth - w - 12, centre - w / 2));
      setPos({ top: b.bottom + window.scrollY + 8, left: left + window.scrollX, arrow: centre - left });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [anchor]);

  useEffect(() => {
    const close = (e: Event) => {
      const t = e.target as Node;
      if (anchor.contains(t) || bubble.current?.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [anchor, onClose]);

  return createPortal(
    <div
      ref={bubble}
      role="dialog"
      aria-label={title}
      className="it-bubble pv-bubble"
      style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden', top: 0, left: 0 }}
    >
      <span className="it-arrow" style={{ left: pos?.arrow ?? 0 }} aria-hidden />
      <div className="pv-title">{title}</div>
      {explain && <p className="pv-explain">{explain}</p>}
      {rows.length > 0 && (
        <dl className="pv-rows">
          {rows.map(([label, value]) => (
            <React.Fragment key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {onOpenReport && (
        <button type="button" className="pv-open" onClick={() => { onOpenReport(); onClose(); }}>
          Открыть отчёт →
        </button>
      )}
    </div>,
    document.body,
  );
}
