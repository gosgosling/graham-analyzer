import React from 'react';
import type { BankMetrics, FinancialReport } from '../types';
import { explainReportMultipliers, fmtMlnRub, marketCapMln } from '../utils/reportMultipliers';
import { formatPerShare } from '../utils/perShare';
import { resolveSharesForMultipliers } from '../utils/shareCounts';
import './ReportDetailModal.css';

/**
 * Просмотр отчёта: что посчиталось и из чего.
 *
 * Прежние две реализации (в списке компаний и в карточке) показывали таблицу
 * всех полей подряд — по ней нельзя было понять, почему P/E именно такой.
 * Здесь на первом экране стоят мультипликаторы с обеими частями дроби, а
 * исходные цифры отчёта убраны под раскрывающийся блок.
 *
 * Правка отчёта живёт в матрице: одна таблица вместо формы, дублирующей её
 * поля. Кнопка «Открыть в матрице» ведёт туда же.
 */
interface ReportDetailModalProps {
  report: FinancialReport;
  onClose: () => void;
  /** Переход к правке — в матрицу отчётов. */
  onEdit?: (report: FinancialReport) => void;
  onVerify?: (reportId: number) => void;
  verifyPending?: boolean;
  onDelete?: (reportId: number) => void;
  deletePending?: boolean;
}

const PERIOD_LABEL: Record<string, string> = {
  annual: 'Годовой',
  semi_annual: 'Полугодовой',
  quarterly: 'Квартальный',
};

function periodTitle(report: FinancialReport): string {
  const pt = String(report.period_type).toLowerCase();
  const base = PERIOD_LABEL[pt] ?? pt;
  const quarter = pt === 'quarterly' && report.fiscal_quarter ? ` · Q${report.fiscal_quarter}` : '';
  return `${report.fiscal_year} · ${base}${quarter}`;
}

/** Строка исходных данных: значение или явный прочерк. */
const Figure: React.FC<{ label: string; value: React.ReactNode; hint?: string }> = ({
  label,
  value,
  hint,
}) => (
  <div className="rdm-figure" title={hint}>
    <span className="rdm-figure-label">{label}</span>
    <span className="rdm-figure-value">{value}</span>
  </div>
);

const ReportDetailModal: React.FC<ReportDetailModalProps> = ({
  report,
  onClose,
  onEdit,
  onVerify,
  verifyPending = false,
  onDelete,
  deletePending = false,
}) => {
  const metrics = explainReportMultipliers(report);
  const cap = marketCapMln(report);
  const shares = resolveSharesForMultipliers(report);
  const bank = report.bank_metrics as BankMetrics | null | undefined;
  const unverified = report.verified_by_analyst === false;

  return (
    <div className="rdm-overlay" onClick={onClose}>
      <div className="rdm-window" onClick={(e) => e.stopPropagation()}>
        <header className="rdm-header">
          <div>
            <h2 className="rdm-title">{periodTitle(report)}</h2>
            <div className="rdm-subtitle">
              {report.accounting_standard}
              {report.consolidated ? ' · консолидированный' : ' · неконсолидированный'}
              {report.currency !== 'RUB' ? ` · ${report.currency}` : ''}
              {report.report_type === 'bank' ? ' · банк' : ''}
            </div>
          </div>
          <button type="button" className="rdm-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </header>

        {unverified && (
          <div className="rdm-banner">
            {report.auto_extracted ? 'Черновик AI-парсера' : 'Требует проверки'} — значения не
            подтверждены аналитиком.
            {report.extraction_model ? ` Модель: ${report.extraction_model}.` : ''}
            {report.extraction_notes && (
              <details className="rdm-notes">
                <summary>Заметки извлечения</summary>
                <pre>{report.extraction_notes}</pre>
              </details>
            )}
          </div>
        )}

        <div className="rdm-body">
          <section className="rdm-section">
            <h3 className="rdm-section-title">Из чего складываются мультипликаторы</h3>
            <div className="rdm-metrics">
              {metrics.map((m) => (
                <div key={m.key} className={`rdm-metric${m.value === null ? ' is-empty' : ''}`}>
                  <div className="rdm-metric-head">
                    <span className="rdm-metric-label">{m.label}</span>
                    <span className="rdm-metric-value">
                      {m.value === null
                        ? '—'
                        : `${m.value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}${m.unit}`}
                    </span>
                  </div>
                  <div className="rdm-metric-formula">{m.formula}</div>
                  <div className="rdm-metric-sub">{m.missing ?? m.substitution}</div>
                </div>
              ))}
            </div>
            <p className="rdm-note">
              Капитализация на дату отчёта: {fmtMlnRub(cap)}
              {shares !== null && (
                <> — цена {formatPerShare(report.price_per_share)} × {shares.toLocaleString('ru-RU')} акций</>
              )}
            </p>
          </section>

          {bank && (
            <section className="rdm-section">
              <h3 className="rdm-section-title">Банковские показатели</h3>
              <div className="rdm-figures">
                <Figure label="Стоимость риска" value={bank.cost_of_risk !== null ? `${bank.cost_of_risk}%` : '—'} />
                <Figure label="Доля проблемных" value={bank.npl_ratio !== null ? `${bank.npl_ratio}%` : '—'} />
                <Figure label="Покрытие резервом" value={bank.npl_coverage !== null ? `${bank.npl_coverage}%` : '—'} />
                <Figure label="Кредиты / депозиты" value={bank.loans_to_deposits !== null ? `${bank.loans_to_deposits}%` : '—'} />
                <Figure label="Н1.1" value={bank.capital_adequacy_core !== null ? `${bank.capital_adequacy_core}%` : '—'} />
                <Figure label="ROA" value={bank.roa !== null ? `${bank.roa}%` : '—'} />
              </div>
            </section>
          )}

          <details className="rdm-raw">
            <summary>Исходные цифры отчёта</summary>
            <div className="rdm-figures">
              <Figure label="Выручка" value={fmtMlnRub(report.revenue_rub ?? report.revenue ?? null)} />
              <Figure label="Чистая прибыль" value={fmtMlnRub(report.net_income_rub ?? report.net_income ?? null)} />
              {report.net_income_reported != null && (
                <Figure
                  label="Прибыль отчётная"
                  value={fmtMlnRub(report.net_income_reported_rub ?? report.net_income_reported)}
                  hint="Если отличается от net_income — прибыль нормализована"
                />
              )}
              <Figure label="Активы" value={fmtMlnRub(report.total_assets_rub ?? report.total_assets ?? null)} />
              <Figure label="Капитал" value={fmtMlnRub(report.equity_rub ?? report.equity ?? null)} />
              <Figure label="Обязательства" value={fmtMlnRub(report.total_liabilities_rub ?? report.total_liabilities ?? null)} />
              <Figure label="Цена акции" value={formatPerShare(report.price_per_share)} />
              <Figure label="Акции для расчёта" value={shares !== null ? shares.toLocaleString('ru-RU') : '—'} />
              <Figure
                label="Дивиденд на акцию"
                value={report.dividends_paid ? formatPerShare(report.dividends_per_share) : 'не платили'}
              />
              {report.dividend_payout != null && (
                <Figure label="Payout" value={`${report.dividend_payout}%`} hint="Доля прибыли, ушедшая на дивиденды" />
              )}
              <Figure label="Дата окончания периода" value={String(report.report_date).slice(0, 10)} />
              {report.filing_date && (
                <Figure label="Дата публикации" value={String(report.filing_date).slice(0, 10)} />
              )}
            </div>
          </details>
        </div>

        <footer className="rdm-footer">
          {onVerify && unverified && (
            <button
              type="button"
              className="rdm-btn rdm-btn-primary"
              disabled={verifyPending}
              onClick={() => onVerify(report.id)}
            >
              {verifyPending ? 'Подтверждаю…' : '✓ Подтвердить'}
            </button>
          )}
          {onEdit && (
            <button type="button" className="rdm-btn" onClick={() => onEdit(report)}>
              Открыть в матрице
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              className="rdm-btn rdm-btn-danger"
              disabled={deletePending}
              onClick={() => onDelete(report.id)}
            >
              {deletePending ? 'Удаляю…' : 'Удалить'}
            </button>
          )}
          <button type="button" className="rdm-btn" onClick={onClose}>
            Закрыть
          </button>
        </footer>
      </div>
    </div>
  );
};

export default ReportDetailModal;
