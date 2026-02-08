import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getCompanies, createFinancialReport, getCompanyReports } from '../services/api';
import { Company, FinancialReportCreate, FinancialReport } from '../types';
import ReportForm from '../components/ReportForm';
import './SecuritiesList.css';
import './CompaniesList.css';

const CompaniesList: React.FC = () => {
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [expandedCompanies, setExpandedCompanies] = useState<number[]>([]);
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

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
          onSubmit={handleFormSubmit}
          onCancel={handleFormCancel}
        />
      )}
      
      {selectedReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={handleCloseReport}
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
          {reports.map((report) => (
            <div key={report.id} className="report-item">
              <div className="report-info">
                <span className="report-date">📅 {report.report_date}</span>
                <span className="report-currency">💰 {report.currency}</span>
                {report.dividends_paid && (
                  <span className="report-dividend">💵 Дивиденды</span>
                )}
              </div>
              <button 
                onClick={() => onViewReport(report)}
                className="btn-view-report"
              >
                Посмотреть
              </button>
            </div>
          ))}
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
}

const ReportDetailModal: React.FC<ReportDetailModalProps> = ({ report, onClose }) => {
  return (
    <div className="report-detail-overlay" onClick={onClose}>
      <div className="report-detail-container" onClick={(e) => e.stopPropagation()}>
        <div className="report-detail-header">
          <h2>📊 Финансовый отчет</h2>
          <button onClick={onClose} className="btn-close">✕</button>
        </div>
        
        <div className="report-detail-content">
          <div className="detail-section">
            <h3>Основная информация</h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="detail-label">Дата отчета:</span>
                <span className="detail-value">{report.report_date}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Валюта:</span>
                <span className="detail-value">{report.currency}</span>
              </div>
              {report.exchange_rate && (
                <div className="detail-item">
                  <span className="detail-label">Курс USD/RUB:</span>
                  <span className="detail-value">{report.exchange_rate.toFixed(4)}</span>
                </div>
              )}
            </div>
          </div>

          {(report.price_per_share || report.shares_outstanding) && (
            <div className="detail-section">
              <h3>Рыночные данные</h3>
              <div className="detail-grid">
                {report.price_per_share && (
                  <div className="detail-item">
                    <span className="detail-label">Цена акции:</span>
                    <span className="detail-value">{report.price_per_share.toLocaleString()} {report.currency}</span>
                  </div>
                )}
                {report.shares_outstanding && (
                  <div className="detail-item">
                    <span className="detail-label">Количество акций:</span>
                    <span className="detail-value">{report.shares_outstanding.toLocaleString()}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {(report.revenue || report.net_income) && (
            <div className="detail-section">
              <h3>Отчет о прибылях и убытках</h3>
              <div className="detail-grid">
                {report.revenue && (
                  <div className="detail-item">
                    <span className="detail-label">Выручка:</span>
                    <span className="detail-value">{report.revenue.toLocaleString()} {report.currency}</span>
                  </div>
                )}
                {report.net_income && (
                  <div className="detail-item">
                    <span className="detail-label">Чистая прибыль:</span>
                    <span className="detail-value">{report.net_income.toLocaleString()} {report.currency}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        
        <div className="report-detail-footer">
          <button onClick={onClose} className="btn-close-detail">
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
};

export default CompaniesList;
