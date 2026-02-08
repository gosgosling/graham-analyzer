import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanyById, getCompanyReports } from '../services/api';
import { FinancialReport } from '../types';
import './CompanyDetail.css';

const CompanyDetail: React.FC = () => {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);

  const { data: company, isLoading: companyLoading, error: companyError } = useQuery({
    queryKey: ['company', companyId],
    queryFn: () => getCompanyById(Number(companyId)),
    enabled: !!companyId,
  });

  const { data: reports, isLoading: reportsLoading } = useQuery({
    queryKey: ['reports', companyId],
    queryFn: () => getCompanyReports(Number(companyId)),
    enabled: !!companyId,
  });

  if (companyLoading) {
    return (
      <div className="company-detail-container">
        <div className="loading">Загрузка данных компании...</div>
      </div>
    );
  }

  if (companyError || !company) {
    return (
      <div className="company-detail-container">
        <div className="error">Ошибка: Компания не найдена</div>
        <button onClick={() => navigate('/companies')} className="btn-back">
          ← Вернуться к списку
        </button>
      </div>
    );
  }

  const latestReport = reports && reports.length > 0 ? reports[0] : null;
  const marketCap = latestReport?.price_per_share && latestReport?.shares_outstanding
    ? latestReport.price_per_share * latestReport.shares_outstanding
    : null;

  return (
    <div className="company-detail-container">
      <div className="detail-header">
        <button onClick={() => navigate('/companies')} className="btn-back">
          ← Назад к списку
        </button>
      </div>

      <div className="company-hero">
        <div className="company-title-section">
          <h1 className="company-title">{company.name}</h1>
          <div className="company-meta">
            <span className="company-ticker">{company.ticker}</span>
            <span className="company-sector">{company.sector || 'Не указан'}</span>
            <span className="company-currency">💱 {company.currency}</span>
          </div>
        </div>
        
        {latestReport && (
          <div className="company-quick-stats">
            {latestReport.price_per_share && (
              <div className="quick-stat">
                <span className="stat-label">Цена акции</span>
                <span className="stat-value">
                  {latestReport.price_per_share.toLocaleString()} {latestReport.currency}
                </span>
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
            {marketCap && (
              <div className="quick-stat">
                <span className="stat-label">Капитализация</span>
                <span className="stat-value">
                  {(marketCap / 1_000_000_000).toFixed(2)} млрд {latestReport.currency}
                </span>
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="company-content-grid">
        <div className="content-column">
          <section className="info-card">
            <h2 className="card-title">📊 Основная информация</h2>
            <div className="info-grid">
              <div className="info-item">
                <span className="info-label">FIGI:</span>
                <span className="info-value">{company.figi}</span>
              </div>
              <div className="info-item">
                <span className="info-label">ISIN:</span>
                <span className="info-value">{company.isin || 'Не указан'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Тикер:</span>
                <span className="info-value">{company.ticker}</span>
              </div>
            </div>
          </section>
        </div>

        <div className="content-column">
          <section className="info-card">
            <h2 className="card-title">📋 Финансовые отчеты</h2>
            {reportsLoading ? (
              <div className="loading-small">Загрузка отчетов...</div>
            ) : reports && reports.length > 0 ? (
              <div className="reports-compact-list">
                {reports.map((report) => (
                  <div key={report.id} className="report-compact-item">
                    <div className="report-compact-info">
                      <span className="report-compact-date">📅 {report.report_date}</span>
                      <div className="report-compact-meta">
                        <span className="report-compact-currency">{report.currency}</span>
                        {report.dividends_paid && (
                          <span className="report-compact-dividend">💵 Дивиденды</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="placeholder-content">
                <p>Финансовых отчетов пока нет</p>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};

export default CompanyDetail;
