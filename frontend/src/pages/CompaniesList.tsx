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
import TInvestSyncBar from '../components/TInvestSyncBar';
import VerificationBadge from '../components/VerificationBadge';
import ReportDetailModal from '../components/ReportDetailModal';
import { formatPerShare } from '../utils/perShare';
import { formatMln } from '../utils/format';
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

  // Ввод и правка отчётов живут только в матрице: одна таблица вместо
  // модального окна, которое дублировало её поля и тормозило на больших формах.
  const handleAddReport = (company: Company) => {
    navigate(`/company/${company.id}/reports-matrix`);
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
      
      {selectedReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={handleCloseReport}
          onEdit={(report) => {
            // Правка отчётов живёт в матрице — там же, где ввод.
            navigate(`/company/${report.company_id}/reports-matrix`);
          }}
          onVerify={(reportId) => verifyReportMutation.mutate(reportId)}
          verifyPending={verifyReportMutation.isPending}
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

export default CompaniesList;
