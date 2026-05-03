import React, { useCallback, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  deleteFinancialReport,
  getCompanyById,
  getCompanyReports,
  refreshCompanyMultipliers,
  updateFinancialReport,
  verifyReport,
  createFinancialReport,
} from '../services';
import type { FinancialReport, FinancialReportCreate } from '../types';
import { detectSectorDisplayKind } from '../utils/sectorDisplayKind';
import { financialReportToCreatePayload } from '../utils/financialReportPayload';
import ReportForm from '../components/ReportForm';
import AiParsePdfModal from '../components/AiParsePdfModal';
import './CompanyReportsMatrix.css';

type CellKind = 'text' | 'number' | 'int' | 'date' | 'bool' | 'select' | 'textarea' | 'readonly';

interface MatrixRowDef {
  key: keyof FinancialReportCreate | 'fcf_display';
  label: string;
  hint?: string;
  kind: CellKind;
  bankOnly?: boolean;
  nonBankOnly?: boolean;
  selectOptions?: { value: string; label: string }[];
}

const PERIOD_OPTIONS = [
  { value: 'quarterly', label: 'Квартальный' },
  { value: 'semi_annual', label: 'Полугодовой' },
  { value: 'annual', label: 'Годовой' },
];

const STANDARD_OPTIONS = [
  { value: 'IFRS', label: 'IFRS' },
  { value: 'RAS', label: 'РСБУ' },
  { value: 'US_GAAP', label: 'US GAAP' },
  { value: 'UK_GAAP', label: 'UK GAAP' },
  { value: 'OTHER', label: 'Иное' },
];

const SOURCE_OPTIONS = [
  { value: 'manual', label: 'Вручную' },
  { value: 'company_website', label: 'Сайт компании' },
  { value: 'api', label: 'API' },
  { value: 'regulator', label: 'Регулятор' },
  { value: 'other', label: 'Прочее' },
];

const MATRIX_ROWS: MatrixRowDef[] = [
  { key: 'period_type', label: 'Тип периода', kind: 'select', selectOptions: PERIOD_OPTIONS },
  { key: 'fiscal_year', label: 'Финансовый год', kind: 'int' },
  { key: 'fiscal_quarter', label: 'Квартал (1–4)', kind: 'int', hint: 'Только для квартальных; для годового оставьте пусто' },
  { key: 'accounting_standard', label: 'Стандарт', kind: 'select', selectOptions: STANDARD_OPTIONS },
  { key: 'consolidated', label: 'Консолидация', kind: 'bool' },
  { key: 'source', label: 'Источник данных', kind: 'select', selectOptions: SOURCE_OPTIONS },
  { key: 'report_date', label: 'Дата окончания периода', kind: 'date' },
  { key: 'filing_date', label: 'Дата публикации', kind: 'date' },
  { key: 'currency', label: 'Валюта отчёта', kind: 'select', selectOptions: [{ value: 'RUB', label: 'RUB' }, { value: 'USD', label: 'USD' }] },
  { key: 'exchange_rate', label: 'Курс к RUB', kind: 'number', hint: 'Обязателен для USD' },
  { key: 'price_per_share', label: 'Цена акции (на конец периода)', kind: 'number' },
  { key: 'price_at_filing', label: 'Цена на дату публикации', kind: 'number' },
  { key: 'shares_outstanding', label: 'Акций в обращении', kind: 'int' },
  { key: 'revenue', label: 'Выручка / OpIncome', kind: 'number', hint: 'млн валюты отчёта' },
  { key: 'net_income', label: 'Чистая прибыль', kind: 'number', hint: 'млн' },
  { key: 'net_income_reported', label: 'Прибыль отчётная', kind: 'number', hint: 'млн' },
  { key: 'total_assets', label: 'Активы всего', kind: 'number', hint: 'млн' },
  { key: 'current_assets', label: 'Оборотные активы', kind: 'number', hint: 'млн', bankOnly: false },
  { key: 'total_liabilities', label: 'Обязательства всего', kind: 'number', hint: 'млн' },
  { key: 'current_liabilities', label: 'Краткоср. обязательства', kind: 'number', hint: 'млн', bankOnly: false },
  { key: 'equity', label: 'Капитал', kind: 'number', hint: 'млн' },
  { key: 'dividends_per_share', label: 'Дивиденд на акцию', kind: 'number', hint: 'полные единицы валюты' },
  { key: 'dividends_paid', label: 'Дивиденды выплачивались', kind: 'bool' },
  { key: 'net_interest_income', label: 'NII (банк)', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'fee_commission_income', label: 'Комиссионные доходы', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'operating_expenses', label: 'Опер. расходы (до резервов)', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'provisions', label: 'Резервы под ОК', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'operating_cash_flow', label: 'Опер. денежный поток', kind: 'number', hint: 'млн', nonBankOnly: true },
  { key: 'capex', label: 'CAPEX', kind: 'number', hint: 'млн, положит.', nonBankOnly: true },
  { key: 'depreciation_amortization', label: 'Амортизация и износ (D&A)', kind: 'number', hint: 'млн', nonBankOnly: true },
  { key: 'fcf_display', label: 'FCF (расчётное)', kind: 'readonly', hint: 'OCF − CAPEX', nonBankOnly: true },
  { key: 'extraction_notes', label: 'Заметки / проверка', kind: 'textarea' },
];

function sliceIsoDate(v: unknown): string {
  if (v == null) return '';
  const s = typeof v === 'string' ? v : String(v);
  return s.slice(0, 10);
}

function periodShort(r: FinancialReport): string {
  const pt = String(r.period_type).toLowerCase();
  if (pt === 'annual') return `${r.fiscal_year} · год`;
  if (pt === 'semi_annual') return `${r.fiscal_year} · пг`;
  return `${r.fiscal_year} · Q${r.fiscal_quarter ?? '?'}`;
}

function parseNum(raw: string): number | null {
  const t = raw.replace(/\s/g, '').replace(',', '.').trim();
  if (t === '' || t === '-') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function parseIntMaybe(raw: string): number | null {
  const t = raw.replace(/\s/g, '').trim();
  if (t === '') return null;
  const n = parseInt(t, 10);
  return Number.isFinite(n) ? n : null;
}

function getDisplayValue(r: FinancialReport, row: MatrixRowDef): string {
  if (row.key === 'fcf_display') {
    if (r.fcf != null && r.fcf !== undefined) return String(r.fcf);
    const ocf = r.operating_cash_flow;
    const cx = r.capex;
    if (ocf != null && cx != null) return String(ocf - cx);
    return '';
  }
  const k = row.key as keyof FinancialReport;
  const v = r[k];
  if (v === null || v === undefined) return '';
  if (row.kind === 'bool') return v ? '1' : '';
  return String(v);
}

function applyParsedToPayload(
  payload: FinancialReportCreate,
  row: MatrixRowDef,
  raw: string,
): void {
  const k = row.key;
  if (k === 'fcf_display') return;

  const widened = payload as unknown as Record<string, unknown>;

  if (row.kind === 'bool') {
    widened[k as string] = raw === 'true' || raw === '1';
    return;
  }
  if (row.kind === 'int') {
    const n = parseIntMaybe(raw);
    widened[k as string] = n;
    return;
  }
  if (row.kind === 'number') {
    widened[k as string] = parseNum(raw);
    return;
  }
  if (row.kind === 'date') {
    const s = raw.trim().slice(0, 10);
    if (k === 'filing_date') {
      payload.filing_date = s === '' ? null : s;
    } else if (k === 'report_date') {
      payload.report_date = s;
    }
    return;
  }
  if (row.kind === 'select' || row.kind === 'text' || row.kind === 'textarea') {
    if (k === 'period_type') {
      const pt = raw as FinancialReportCreate['period_type'];
      payload.period_type = pt;
      if (pt === 'annual') {
        payload.fiscal_quarter = null;
      }
      return;
    }
    widened[k as string] = raw;
  }
}

const CompanyReportsMatrix: React.FC = () => {
  const { companyId: companyIdParam } = useParams<{ companyId: string }>();
  const companyId = Number(companyIdParam);
  const queryClient = useQueryClient();

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [aiModal, setAiModal] = useState<{
    mode: 'create' | 'compare' | 'batch';
    fiscalYear?: number;
    accountingStandard?: FinancialReportCreate['accounting_standard'];
  } | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const { data: company, error: companyError, isLoading: companyLoading } = useQuery({
    queryKey: ['company', companyIdParam],
    queryFn: () => getCompanyById(companyId),
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const { data: reports, isLoading: reportsLoading } = useQuery({
    queryKey: ['reports', companyIdParam],
    queryFn: () => getCompanyReports(companyId),
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const sectorKind = detectSectorDisplayKind(company?.sector);
  const isBank = sectorKind === 'bank';

  const visibleRows = useMemo(
    () =>
      MATRIX_ROWS.filter((row) => {
        if (row.bankOnly && !isBank) return false;
        if (row.nonBankOnly && isBank) return false;
        if (isBank && (row.key === 'current_assets' || row.key === 'current_liabilities')) return false;
        return true;
      }),
    [isBank],
  );

  const sortedReports = useMemo(() => {
    if (!reports?.length) return [];
    return [...reports].sort((a, b) => sliceIsoDate(b.report_date).localeCompare(sliceIsoDate(a.report_date)));
  }, [reports]);

  const invalidateAll = useCallback(async () => {
    queryClient.invalidateQueries({ queryKey: ['reports', companyIdParam] });
    queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
    queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
    queryClient.invalidateQueries({ queryKey: ['multipliers', companyIdParam] });
    queryClient.invalidateQueries({ queryKey: ['company', companyIdParam] });
    await refreshCompanyMultipliers(companyId, true).catch(() => {});
  }, [companyId, companyIdParam, queryClient]);

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FinancialReportCreate }) =>
      updateFinancialReport(id, data),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const verifyMutation = useMutation({
    mutationFn: (id: number) => verifyReport(id),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteFinancialReport(id),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const handleCellCommit = useCallback(
    async (report: FinancialReport, row: MatrixRowDef, raw: string) => {
      if (row.kind === 'readonly') return;
      const prev = getDisplayValue(report, row);
      if (prev === raw) return;

      const payload = financialReportToCreatePayload(report, companyId);
      try {
        applyParsedToPayload(payload, row, raw);
        if (payload.period_type === 'quarterly' && (payload.fiscal_quarter == null || payload.fiscal_quarter < 1)) {
          alert('Для квартального отчёта укажите квартал 1–4.');
          return;
        }
        if (payload.currency?.toUpperCase() !== 'RUB' && !payload.exchange_rate) {
          alert(`Для валюты ${payload.currency} укажите курс к RUB.`);
          return;
        }
      } catch {
        alert('Ошибка разбора значения');
        return;
      }

      const sk = `${report.id}:${String(row.key)}`;
      setSavingKey(sk);
      try {
        await updateMutation.mutateAsync({ id: report.id, data: payload });
      } catch (e: unknown) {
        const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        alert(typeof d === 'string' ? d : 'Не удалось сохранить ячейку');
      } finally {
        setSavingKey(null);
      }
    },
    [companyId, updateMutation],
  );

  const handleDeleteReport = useCallback(
    (r: FinancialReport) => {
      const label = `${r.fiscal_year} ${periodShort(r)}`;
      if (
        !window.confirm(
          `Удалить отчёт «${label}»?\n\nБудут удалены связанные записи report_based в истории мультипликаторов.`,
        )
      ) {
        return;
      }
      deleteMutation.mutate(r.id);
    },
    [deleteMutation],
  );

  if (!Number.isFinite(companyId) || companyId <= 0) {
    return (
      <div className="crm-page">
        <p className="crm-error">Некорректный идентификатор компании.</p>
      </div>
    );
  }

  if (companyLoading || companyError || !company) {
    return (
      <div className="crm-page">
        <div className="crm-loading">{companyLoading ? 'Загрузка…' : 'Компания не найдена'}</div>
      </div>
    );
  }

  const colCount = Math.max(1, sortedReports.length);

  return (
    <div className="crm-page">
      <header className="crm-header">
        <div className="crm-header-main">
          <Link to={`/company/${companyId}`} className="crm-back">
            ← К компании
          </Link>
          <h1 className="crm-title">
            Отчёты — {company.name}{' '}
            <span className="crm-ticker">{company.ticker}</span>
          </h1>
          <p className="crm-sub">
            Измените ячейку и нажмите Enter или уберите фокус. Колонки — от новых отчётов к старым.
          </p>
        </div>
        <div className="crm-toolbar">
          <button type="button" className="crm-btn crm-btn-primary" onClick={() => setShowCreateForm(true)}>
            + Отчёт вручную
          </button>
          <button
            type="button"
            className="crm-btn"
            onClick={() => setAiModal({ mode: 'create', fiscalYear: new Date().getFullYear() - 1 })}
          >
            🤖 AI: создать
          </button>
          <button type="button" className="crm-btn" onClick={() => setAiModal({ mode: 'compare' })}>
            🔍 AI: сравнить
          </button>
          <button type="button" className="crm-btn" onClick={() => setAiModal({ mode: 'batch' })}>
            📂 AI: пакет
          </button>
        </div>
      </header>

      <div className="crm-table-scroll">
        {reportsLoading ? (
          <div className="crm-loading">Загрузка отчётов…</div>
        ) : sortedReports.length === 0 ? (
          <div className="crm-empty">
            <p>Отчётов пока нет.</p>
            <button type="button" className="crm-btn crm-btn-primary" onClick={() => setShowCreateForm(true)}>
              Добавить первый отчёт
            </button>
          </div>
        ) : (
          <table className="crm-table">
            <thead>
              <tr>
                <th className="crm-th-label">Показатель</th>
                {sortedReports.map((r) => (
                  <th key={r.id} className="crm-th-col">
                    <div className="crm-col-head">
                      <div className="crm-col-period">{periodShort(r)}</div>
                      <div className="crm-col-meta">
                        {r.accounting_standard}
                        {r.report_type ? ` · ${r.report_type}` : ''}
                      </div>
                      <div className="crm-col-date">{sliceIsoDate(r.report_date)}</div>
                      <div className="crm-col-badges">
                        {r.auto_extracted && <span className="crm-badge ai">AI</span>}
                        {r.verified_by_analyst === false && (
                          <span className="crm-badge pending">не проверен</span>
                        )}
                      </div>
                      <div className="crm-col-actions">
                        {r.verified_by_analyst === false && (
                          <button
                            type="button"
                            className="crm-mini-btn"
                            disabled={verifyMutation.isPending}
                            title="Подтвердить проверку"
                            onClick={() => verifyMutation.mutate(r.id)}
                          >
                            ✓
                          </button>
                        )}
                        <button
                          type="button"
                          className="crm-mini-btn"
                          title="Загрузить PDF (AI), год подставлен"
                          onClick={() =>
                            setAiModal({
                              mode: 'create',
                              fiscalYear: r.fiscal_year,
                              accountingStandard: r.accounting_standard as FinancialReportCreate['accounting_standard'],
                            })
                          }
                        >
                          🤖
                        </button>
                        <button
                          type="button"
                          className="crm-mini-btn"
                          title="Сравнить с PDF (AI)"
                          onClick={() =>
                            setAiModal({
                              mode: 'compare',
                              fiscalYear: r.fiscal_year,
                              accountingStandard: r.accounting_standard as FinancialReportCreate['accounting_standard'],
                            })
                          }
                        >
                          🔍
                        </button>
                        <button
                          type="button"
                          className="crm-mini-btn danger"
                          disabled={deleteMutation.isPending}
                          title="Удалить отчёт"
                          onClick={() => handleDeleteReport(r)}
                        >
                          🗑
                        </button>
                      </div>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="crm-section-row">
                <td colSpan={colCount + 1}>Данные отчёта</td>
              </tr>
              {visibleRows.map((row) => (
                <tr key={String(row.key)}>
                  <td className="crm-row-label" title={row.hint}>
                    <span className="crm-row-label-text">{row.label}</span>
                  </td>
                  {sortedReports.map((r) => {
                    const sk = `${r.id}:${String(row.key)}`;
                    const busy = savingKey === sk;
                    return (
                      <td key={r.id} className="crm-cell">
                        <MatrixCellEditor
                          report={r}
                          row={row}
                          disabled={busy}
                          onCommit={(raw) => handleCellCommit(r, row, raw)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreateForm && (
        <ReportForm
          companyId={companyId}
          companyName={company.name}
          ticker={company.ticker}
          sector={company.sector}
          onSubmit={async (data) => {
            await createFinancialReport(data);
            setShowCreateForm(false);
            await invalidateAll();
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      )}

      {aiModal && (
        <AiParsePdfModal
          key={`${aiModal.mode}-${aiModal.fiscalYear ?? 'y'}-${aiModal.accountingStandard ?? 'std'}`}
          companyId={companyId}
          companyName={company.name}
          ticker={company.ticker}
          initialMode={aiModal.mode}
          initialFiscalYear={aiModal.fiscalYear}
          initialAccountingStandard={aiModal.accountingStandard}
          onClose={() => setAiModal(null)}
          onSuccess={async () => {
            await invalidateAll();
          }}
        />
      )}
    </div>
  );
};

interface MatrixCellEditorProps {
  report: FinancialReport;
  row: MatrixRowDef;
  disabled?: boolean;
  onCommit: (raw: string) => void;
}

const MatrixCellEditor: React.FC<MatrixCellEditorProps> = ({ report, row, disabled, onCommit }) => {
  const initial = getDisplayValue(report, row);
  const [val, setVal] = useState(initial);

  React.useEffect(() => {
    setVal(getDisplayValue(report, row));
  }, [report, row]);

  const commit = () => {
    if (!disabled) onCommit(val);
  };

  if (row.kind === 'readonly') {
    return <span className="crm-readonly">{initial === '' ? '—' : initial}</span>;
  }

  if (row.kind === 'bool') {
    const checked = val === 'true' || val === '1';
    return (
      <input
        type="checkbox"
        className="crm-checkbox"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => {
          const next = e.target.checked ? 'true' : 'false';
          setVal(next);
          onCommit(next);
        }}
      />
    );
  }

  if (row.kind === 'select' && row.selectOptions) {
    const selVal =
      val ||
      (report[row.key as keyof FinancialReport] != null
        ? String(report[row.key as keyof FinancialReport])
        : '');
    return (
      <select
        className="crm-select"
        disabled={disabled}
        value={selVal}
        onChange={(e) => {
          const next = e.target.value;
          setVal(next);
          onCommit(next);
        }}
      >
        <option value="">—</option>
        {row.selectOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }

  if (row.kind === 'textarea') {
    return (
      <textarea
        className="crm-textarea"
        disabled={disabled}
        rows={2}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onBlur={commit}
      />
    );
  }

  return (
    <input
      type={row.kind === 'date' ? 'date' : 'text'}
      className="crm-input"
      disabled={disabled}
      value={row.kind === 'date' ? val.slice(0, 10) : val}
      onChange={(e) => setVal(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );
};

export default CompanyReportsMatrix;
