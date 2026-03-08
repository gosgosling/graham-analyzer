import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getCompanies, createFinancialReport, getCompanyReports, updateFinancialReport, refreshCompanyMultipliers } from '../services/api';
import { Company, FinancialReportCreate, FinancialReport } from '../types';
import ReportForm from '../components/ReportForm';
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

  const updateReportMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FinancialReportCreate }) =>
      updateFinancialReport(id, data),
    onSuccess: async (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
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

  const createReportMutation = useMutation({
    mutationFn: createFinancialReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
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
              companies.map((company: Company) => (
                <React.Fragment key={company.figi}>
                  <tr 
                    className="company-row"
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
                    <td className="name-cell">{company.name}</td>
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
              ))
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
            <div key={report.id} className="report-item">
              <div className="report-info">
                <span className="report-year">{report.fiscal_year}</span>
                <span className="report-period">{periodLabel}</span>
                <span className="report-date">{report.report_date}</span>
                <span className="report-currency">{report.currency}</span>
                {report.dividends_paid && (
                  <span className="report-dividend">💵</span>
                )}
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
}

// Тот же полный компонент, что и в CompanyDetail
const ReportDetailModal: React.FC<ReportDetailModalProps> = ({ report, onClose, onEdit }) => {
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
            <h2>📊 Финансовый отчет</h2>
            <p className="report-detail-subtitle">
              {report.fiscal_year} · {periodLabel} · {report.accounting_standard}
            </p>
          </div>
          <button onClick={onClose} className="btn-close">✕</button>
        </div>

        <div className="report-detail-content">
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

          {(report.revenue != null || report.net_income != null) && (
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
