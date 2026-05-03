import React, { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  getCompanies,
  createFinancialReport,
  getCompanyReports,
  updateFinancialReport,
  refreshCompanyMultipliers,
  getUnverifiedCountsByCompany,
  getReportCountsByCompany,
  verifyReport,
} from '../services';
import { Company, FinancialReportCreate, FinancialReport } from '../types';
import ReportForm from '../components/ReportForm';
import TInvestSyncBar from '../components/TInvestSyncBar';
import VerificationBadge from '../components/VerificationBadge';
import './SecuritiesList.css';
import './CompaniesList.css';

const CompaniesList: React.FC = () => {
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [expandedCompanies, setExpandedCompanies] = useState<number[]>([]);
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const [editingReport, setEditingReport] = useState<FinancialReport | null>(null);
  const [editingCompany, setEditingCompany] = useState<Company | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('');
  const [reportsFilter, setReportsFilter] = useState<'all' | 'with' | 'without'>('all');
  const [sortMode, setSortMode] = useState<
    'ticker' | 'name' | 'sector' | 'reports_desc' | 'reports_asc'
  >('ticker');

  const updateReportMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FinancialReportCreate }) =>
      updateFinancialReport(id, data),
    onSuccess: async (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      // Пересчёт мультипликаторов
      if (editingCompany?.id) {
        await refreshCompanyMultipliers(editingCompany.id, true).catch(() => {});
        queryClient.invalidateQueries({ queryKey: ['multipliers', String(editingCompany.id)] });
      }
      setEditingReport(null);
      setEditingCompany(null);
      setSelectedReport(null);
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail;
      alert(typeof detail === 'string' ? detail : 'Ошибка при обновлении отчёта');
    },
  });

  const { data: companies, isLoading, error } = useQuery({
    queryKey: ['companies'],
    queryFn: getCompanies
  });

  const { data: unverifiedCounts } = useQuery({
    queryKey: ['reports-unverified-counts'],
    queryFn: getUnverifiedCountsByCompany,
    staleTime: 30_000,
  });

  const { data: reportCounts } = useQuery({
    queryKey: ['reports-counts-by-company'],
    queryFn: getReportCountsByCompany,
    staleTime: 30_000,
  });

  const verifyReportMutation = useMutation({
    mutationFn: (reportId: number) => verifyReport(reportId),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      setSelectedReport(updated);
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось подтвердить отчёт');
    },
  });

  const createReportMutation = useMutation({
    mutationFn: createFinancialReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      setShowForm(false);
      setSelectedCompany(null);
      alert('Отчет успешно добавлен!');
    },
    onError: (error: any) => {
      console.error('Error creating report:', error);
      alert('Ошибка при создании отчета: ' + (error.response?.data?.detail || error.message));
    }
  });

  const toggleCompany = (companyId: number) => {
    setExpandedCompanies(prev => 
      prev.includes(companyId) 
        ? prev.filter(id => id !== companyId)
        : [...prev, companyId]
    );
  };

  const handleAddReport = (company: Company) => {
    setSelectedCompany(company);
    setShowForm(true);
  };

  const handleFormSubmit = async (reportData: FinancialReportCreate) => {
    await createReportMutation.mutateAsync(reportData);
  };

  const handleFormCancel = () => {
    setShowForm(false);
    setSelectedCompany(null);
  };

  const handleViewReport = (report: FinancialReport) => {
    setSelectedReport(report);
  };

  const handleCloseReport = () => {
    setSelectedReport(null);
  };

  const handleCompanyClick = (company: Company, event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest('.expand-button')) {
      return;
    }
    if (company.id) {
      navigate(`/company/${company.id}`);
    }
  };

  const sectorOptions = useMemo(() => {
    const set = new Set<string>();
    (companies ?? []).forEach((c) => {
      const sec = c.sector?.trim();
      if (sec) set.add(sec);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru'));
  }, [companies]);

  const visibleCompanies = useMemo(() => {
    if (!companies) return [];
    const q = search.trim().toLowerCase();
    const rows = companies.filter((c) => {
      if (q) {
        const hay = [c.name, c.ticker, c.isin, c.sector]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (sectorFilter && (c.sector?.trim() || '') !== sectorFilter) return false;
      const n = c.id && reportCounts ? reportCounts[c.id] ?? 0 : 0;
      if (reportsFilter === 'with' && n === 0) return false;
      if (reportsFilter === 'without' && n > 0) return false;
      return true;
    });
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const na = a.id && reportCounts ? reportCounts[a.id] ?? 0 : 0;
      const nb = b.id && reportCounts ? reportCounts[b.id] ?? 0 : 0;
      switch (sortMode) {
        case 'name':
          return (a.name || '').localeCompare(b.name || '', 'ru');
        case 'sector':
          return (a.sector || '').localeCompare(b.sector || '', 'ru');
        case 'reports_desc':
          return nb - na;
        case 'reports_asc':
          return na - nb;
        default:
          return (a.ticker || '').localeCompare(b.ticker || '', 'ru');
      }
    });
    return sorted;
  }, [companies, search, sectorFilter, reportsFilter, sortMode, reportCounts]);

  if (isLoading) {
    return (
      <div className="securities-container">
        <div className="loading">Загрузка данных компаний...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="securities-container">
        <div className="error">Ошибка: {error.message}</div>
      </div>
    );
  }

  return (
    <div className="securities-container">
      <h1 className="securities-title">Российские компании и компании Мосбиржи (T Invest API)</h1>
      <TInvestSyncBar />
      <div className="companies-toolbar">
        <input
          type="search"
          className="companies-search"
          placeholder="Поиск по названию, тикеру, ISIN или сектору…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Поиск компаний"
        />
        <div className="companies-toolbar-row">
          <div className="companies-filter-group">
            <span className="companies-filter-label">Отчёты:</span>
            <div className="companies-pills">
              {([
                ['all', 'Все'],
                ['with', 'С отчётами'],
                ['without', 'Без отчётов'],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`companies-pill${reportsFilter === key ? ' active' : ''}`}
                  onClick={() => setReportsFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="companies-filter-group companies-filter-selects">
            <label className="companies-select-wrap">
              <span>Сектор</span>
              <select
                value={sectorFilter}
                onChange={(e) => setSectorFilter(e.target.value)}
              >
                <option value="">Все сектора</option>
                {sectorOptions.map((sec) => (
                  <option key={sec} value={sec}>
                    {sec}
                  </option>
                ))}
              </select>
            </label>
            <label className="companies-select-wrap">
              <span>Сортировка</span>
              <select
                value={sortMode}
                onChange={(e) =>
                  setSortMode(e.target.value as typeof sortMode)
                }
              >
                <option value="ticker">Тикер (А→Я)</option>
                <option value="name">Название</option>
                <option value="sector">Сектор</option>
                <option value="reports_desc">Число отчётов (сначала больше)</option>
                <option value="reports_asc">Число отчётов (сначала меньше)</option>
              </select>
            </label>
          </div>
        </div>
        <p className="companies-toolbar-meta">
          Показано{' '}
          <strong>{visibleCompanies.length}</strong>
          {' '}из {companies?.length ?? 0} компаний
        </p>
      </div>
      <div className="table-wrapper">
        <table className="securities-table companies-expandable-table">
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              <th>Тикер</th>
              <th>Название</th>
              <th>ISIN</th>
              <th>Сектор</th>
              <th>Валюта</th>
              <th>Лот</th>
              <th>Доступно для API</th>
            </tr>
          </thead>
          <tbody>
            {companies && companies.length > 0 ? (
              visibleCompanies.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '20px' }}>
                    По заданным фильтрам компаний не найдено. Измените поиск или фильтры.
                  </td>
                </tr>
              ) : (
                visibleCompanies.map((company: Company) => {
                  const rc = company.id ? reportCounts?.[company.id] ?? 0 : 0;
                  return (
                <React.Fragment key={company.figi}>
                  <tr 
                    className={`company-row${company.id && rc === 0 ? ' company-row--no-reports' : ''}`}
                    onClick={(e) => handleCompanyClick(company, e)}
                    style={{ cursor: company.id ? 'pointer' : 'default' }}
                  >
                    <td className="expand-cell">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          company.id && toggleCompany(company.id);
                        }}
                        className="expand-button"
                        disabled={!company.id}
                        title="Показать/скрыть отчеты"
                      >
                        {company.id && expandedCompanies.includes(company.id) ? '▼' : '▶'}
                      </button>
                    </td>
                    <td className="ticker-cell">{company.ticker}</td>
                    <td className="name-cell">
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        {company.name}
                        {company.id && rc === 0 && (
                          <span
                            className="reports-none-pill"
                            title="В базе нет ни одного финансового отчёта"
                          >
                            📭 Нет отчётов
                          </span>
                        )}
                        {company.id && unverifiedCounts && unverifiedCounts[company.id] > 0 && (
                          <span
                            className="reports-unverified-pill"
                            title={`${unverifiedCounts[company.id]} отчётов требуют проверки`}
                          >
                            🤖 {unverifiedCounts[company.id]}
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="isin-cell">{company.isin || '-'}</td>
                    <td>{company.sector || '-'}</td>
                    <td className="currency-cell">{company.currency}</td>
                    <td className="lot-cell">{company.lot}</td>
                    <td className="status-cell">
                      <span className={`status-badge ${company.api_trade_available_flag ? 'active' : 'inactive'}`}>
                        {company.api_trade_available_flag ? 'Да' : 'Нет'}
                      </span>
                    </td>
                  </tr>
                  
                  {company.id && expandedCompanies.includes(company.id) && (
                    <tr className="expanded-row">
                      <td colSpan={8}>
                        <CompanyReportsSection
                          company={company}
                          onAddReport={handleAddReport}
                          onViewReport={handleViewReport}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
                  );
                })
              )
            ) : (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '20px' }}>
                  Нет данных. Проверьте настройку TINKOFF_TOKEN в .env файле.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      
      {showForm && selectedCompany && selectedCompany.id && (
        <ReportForm
          companyId={selectedCompany.id}
          companyName={selectedCompany.name}
          ticker={selectedCompany.ticker}
          onSubmit={handleFormSubmit}
          onCancel={handleFormCancel}
        />
      )}
      
      {selectedReport && !editingReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={handleCloseReport}
          onEdit={(report) => {
            // Найти компанию для этого отчёта
            const comp = companies?.find((c: Company) => c.id === report.company_id) ?? null;
            setEditingCompany(comp);
            setEditingReport(report);
            setSelectedReport(null);
          }}
          onVerify={(reportId) => verifyReportMutation.mutate(reportId)}
          verifyPending={verifyReportMutation.isPending}
        />
      )}

      {editingReport && editingCompany && editingCompany.id && (
        <ReportForm
          companyId={editingCompany.id}
          companyName={editingCompany.name}
          ticker={editingCompany.ticker}
          reportId={editingReport.id}
          initialValues={{
            ...editingReport,
            period_type: editingReport.period_type.toLowerCase() as any,
            accounting_standard: editingReport.accounting_standard as any,
            source: (editingReport.source ?? 'manual').toLowerCase() as any,
          }}
          onSubmit={async (data) => {
            await updateReportMutation.mutateAsync({ id: editingReport.id, data });
          }}
          onCancel={() => { setEditingReport(null); setEditingCompany(null); }}
        />
      )}
    </div>
  );
};

interface CompanyReportsSectionProps {
  company: Company;
  onAddReport: (company: Company) => void;
  onViewReport: (report: FinancialReport) => void;
}

const CompanyReportsSection: React.FC<CompanyReportsSectionProps> = ({ 
  company, 
  onAddReport,
  onViewReport 
}) => {
  const { data: reports, isLoading } = useQuery({
    queryKey: ['reports', company.id],
    queryFn: () => getCompanyReports(company.id!),
    enabled: !!company.id,
  });

  if (isLoading) {
    return <div className="reports-section-loading">Загрузка отчетов...</div>;
  }

  return (
    <div className="reports-section">
      <div className="reports-header">
        <h3>Финансовые отчеты</h3>
        <button 
          onClick={() => onAddReport(company)}
          className="btn-add-report-inline"
        >
          + Добавить отчет
        </button>
      </div>
      
      {reports && reports.length > 0 ? (
        <div className="reports-list">
          {reports.map((report) => {
            const pt = report.period_type.toLowerCase();
            const periodLabel =
              pt === 'annual'
                ? 'Годовой'
                : pt === 'semi_annual'
                ? 'Полугодовой'
                : `Q${report.fiscal_quarter}`;
            return (
            <div
              key={report.id}
              className={`report-item${report.verified_by_analyst === false ? ' report-item--needs-review' : ''}`}
            >
              <div className="report-info">
                <span className="report-year">{report.fiscal_year}</span>
                <span className="report-period">{periodLabel}</span>
                <span className="report-date">{report.report_date}</span>
                <span className="report-currency">{report.currency}</span>
                {report.dividends_paid && (
                  <span className="report-dividend">💵</span>
                )}
                <VerificationBadge
                  autoExtracted={report.auto_extracted}
                  verifiedByAnalyst={report.verified_by_analyst}
                  compact
                />
              </div>
              <button
                onClick={() => onViewReport(report)}
                className="btn-view-report"
              >
                Просмотр
              </button>
            </div>
            );
          })}
        </div>
      ) : (
        <div className="no-reports">
          <p>📊 Отчетов пока нет</p>
          <button 
            onClick={() => onAddReport(company)}
            className="btn-add-first-report"
          >
            Добавить первый отчет
          </button>
        </div>
      )}
    </div>
  );
};

interface ReportDetailModalProps {
  report: FinancialReport;
  onClose: () => void;
  onEdit?: (report: FinancialReport) => void;
  onVerify?: (reportId: number) => void;
  verifyPending?: boolean;
}

// Тот же полный компонент, что и в CompanyDetail
const ReportDetailModal: React.FC<ReportDetailModalProps> = ({
  report,
  onClose,
  onEdit,
  onVerify,
  verifyPending,
}) => {
  const cur = report.currency;
  const isUsd = cur === 'USD';

  const fmtMln = (n: number | null | undefined): string => {
    if (n === null || n === undefined) return '—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ` трлн ${cur}`;
    if (abs >= 1_000)     return (n / 1_000).toFixed(2) + ` млрд ${cur}`;
    return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ` млн ${cur}`;
  };

  const pt2 = report.period_type.toLowerCase();
  const periodLabel =
    pt2 === 'annual'
      ? 'Годовой'
      : pt2 === 'semi_annual'
      ? 'Полугодовой'
      : `Квартальный (Q${report.fiscal_quarter})`;

  return (
    <div className="report-detail-overlay" onClick={onClose}>
      <div className="report-detail-container" onClick={(e) => e.stopPropagation()}>
        <div className="report-detail-header">
          <div>
            <h2 className="report-detail-modal-title-row">
              📊 Финансовый отчет
              <VerificationBadge
                autoExtracted={report.auto_extracted}
                verifiedByAnalyst={report.verified_by_analyst}
              />
            </h2>
            <p className="report-detail-subtitle">
              {report.fiscal_year} · {periodLabel} · {report.accounting_standard}
            </p>
          </div>
          <button onClick={onClose} className="btn-close">✕</button>
        </div>

        <div className="report-detail-content">
          {report.verified_by_analyst === false && (
            <div className="detail-section detail-section--verification-banner">
              <h3>
                {report.auto_extracted ? '🤖 Черновик AI-парсера' : '⚠ Требует проверки'}
              </h3>
              <p>
                Отчёт ещё не подтверждён аналитиком.
                {report.extraction_model && (
                  <>
                    {' '}Создан моделью <code>{report.extraction_model}</code>.
                  </>
                )}
              </p>
              {report.extraction_notes && (
                <details className="report-detail-verification-details">
                  <summary>
                    Заметки модели
                  </summary>
                  <pre className="report-detail-verification-pre">
                    {report.extraction_notes}
                  </pre>
                </details>
              )}
            </div>
          )}
          <div className="detail-section">
            <h3>Атрибуты отчёта</h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="detail-label">Период:</span>
                <span className="detail-value">{report.fiscal_year} — {periodLabel}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Дата окончания периода:</span>
                <span className="detail-value">{report.report_date}</span>
              </div>
              {report.filing_date && (
                <div className="detail-item">
                  <span className="detail-label">Дата публикации:</span>
                  <span className="detail-value">{report.filing_date}</span>
                </div>
              )}
              <div className="detail-item">
                <span className="detail-label">Стандарт / Валюта:</span>
                <span className="detail-value">
                  {report.accounting_standard} / {cur}
                  {isUsd && report.exchange_rate ? ` (курс: ${report.exchange_rate} ₽)` : ''}
                </span>
              </div>
            </div>
          </div>

          {(report.price_per_share || report.price_at_filing || report.shares_outstanding) && (
            <div className="detail-section">
              <h3>Рыночные данные</h3>
              <div className="detail-grid">
                {report.price_per_share != null && (
                  <div className="detail-item">
                    <span className="detail-label">Цена на дату отчёта:</span>
                    <span className="detail-value">
                      {report.price_per_share.toLocaleString('ru-RU')} {cur}
                      {isUsd && report.price_per_share_rub && (
                        <span className="detail-hint"> = {report.price_per_share_rub.toLocaleString('ru-RU')} ₽</span>
                      )}
                    </span>
                  </div>
                )}
                {report.price_at_filing != null && (
                  <div className="detail-item">
                    <span className="detail-label">Цена на дату публикации:</span>
                    <span className="detail-value">{report.price_at_filing.toLocaleString('ru-RU')} {cur}</span>
                  </div>
                )}
                {report.shares_outstanding != null && (
                  <div className="detail-item">
                    <span className="detail-label">Акций в обращении:</span>
                    <span className="detail-value">{report.shares_outstanding.toLocaleString('ru-RU')} шт.</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {(report.revenue != null ||
            report.net_income != null ||
            report.net_income_reported != null) && (
            <div className="detail-section">
              <h3>Отчёт о прибылях и убытках <span className="section-units">(млн {cur})</span></h3>
              <div className="detail-grid">
                {report.revenue != null && (
                  <div className="detail-item">
                    <span className="detail-label">Выручка:</span>
                    <span className="detail-value">{fmtMln(report.revenue)}</span>
                  </div>
                )}
                {report.net_income != null && (
                  <div className="detail-item">
                    <span className="detail-label">Чистая прибыль:</span>
                    <span className="detail-value">{fmtMln(report.net_income)}</span>
                  </div>
                )}
                {report.net_income_reported != null && (
                  <div className="detail-item">
                    <span className="detail-label">Фактическая прибыль (отчётная):</span>
                    <span className="detail-value">{fmtMln(report.net_income_reported)}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {(report.total_assets != null || report.equity != null) && (
            <div className="detail-section">
              <h3>Балансовые показатели <span className="section-units">(млн {cur})</span></h3>
              <div className="detail-grid">
                {report.total_assets != null && (
                  <div className="detail-item"><span className="detail-label">Активы (всего):</span><span className="detail-value">{fmtMln(report.total_assets)}</span></div>
                )}
                {report.current_assets != null && (
                  <div className="detail-item"><span className="detail-label">Оборотные активы:</span><span className="detail-value">{fmtMln(report.current_assets)}</span></div>
                )}
                {report.total_liabilities != null && (
                  <div className="detail-item"><span className="detail-label">Обязательства (всего):</span><span className="detail-value">{fmtMln(report.total_liabilities)}</span></div>
                )}
                {report.current_liabilities != null && (
                  <div className="detail-item"><span className="detail-label">Краткосрочные обяз-ва:</span><span className="detail-value">{fmtMln(report.current_liabilities)}</span></div>
                )}
                {report.equity != null && (
                  <div className="detail-item"><span className="detail-label">Собственный капитал:</span><span className="detail-value">{fmtMln(report.equity)}</span></div>
                )}
              </div>
            </div>
          )}

          {/* Денежные потоки (ОДДС) */}
          {(report.operating_cash_flow != null || report.capex != null || report.depreciation_amortization != null) && (
            <div className="detail-section">
              <h3>Денежные потоки (ОДДС) <span className="section-units">(млн {cur})</span></h3>
              <div className="detail-grid">
                {report.operating_cash_flow != null && (
                  <div className="detail-item">
                    <span className="detail-label">Операционный поток (CFO):</span>
                    <span className="detail-value">{fmtMln(report.operating_cash_flow)}</span>
                  </div>
                )}
                {report.capex != null && (
                  <div className="detail-item">
                    <span className="detail-label">CAPEX:</span>
                    <span className="detail-value">{fmtMln(report.capex)}</span>
                  </div>
                )}
                {report.depreciation_amortization != null && (
                  <div className="detail-item">
                    <span className="detail-label">Амортизация и износ (D&amp;A):</span>
                    <span className="detail-value">{fmtMln(report.depreciation_amortization)}</span>
                  </div>
                )}
                {report.fcf != null && (
                  <div className="detail-item">
                    <span className="detail-label">FCF (CFO − CAPEX):</span>
                    <span className={`detail-value${report.fcf < 0 ? ' detail-loss' : ' detail-yes'}`}>
                      {fmtMln(report.fcf)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {report.dividends_paid && (
            <div className="detail-section">
              <h3>Дивиденды</h3>
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Выплачивались:</span>
                  <span className="detail-value detail-yes">✓ Да</span>
                </div>
                {report.dividends_per_share != null && (
                  <div className="detail-item">
                    <span className="detail-label">Дивиденд на акцию:</span>
                    <span className="detail-value">{report.dividends_per_share.toLocaleString('ru-RU')} {cur}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="report-detail-footer">
          <span className="report-detail-meta">
            Добавлен: {report.created_at ? new Date(report.created_at).toLocaleDateString('ru-RU') : '—'}
          </span>
          <div className="report-detail-footer-actions">
            {onVerify && report.verified_by_analyst === false && (
              <button
                onClick={() => onVerify(report.id)}
                className="btn-edit-report"
                disabled={verifyPending}
                style={{ background: '#52c41a', color: 'white', border: 'none' }}
                title="Подтвердить, что отчёт проверен"
              >
                {verifyPending ? 'Подтверждаем…' : '✓ Подтвердить'}
              </button>
            )}
            {onEdit && (
              <button onClick={() => onEdit(report)} className="btn-edit-report">
                ✏️ Редактировать
              </button>
            )}
            <button onClick={onClose} className="btn-close-detail">Закрыть</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CompaniesList;
