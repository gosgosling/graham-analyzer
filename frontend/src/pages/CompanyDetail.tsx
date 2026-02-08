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
      <div className="company-detail-wrapper">
        <div className="company-detail-container">
          <div className="loading">⏳ Загрузка данных компании...</div>
        </div>
      </div>
    );
  }

  if (companyError || !company) {
    return (
      <div className="company-detail-wrapper">
        <div className="company-detail-container">
          <div className="error">
            ❌ Ошибка: Компания не найдена
            <br /><br />
            <button onClick={() => navigate('/companies')} className="btn-back">
              ← Вернуться к списку
            </button>
          </div>
        </div>
      </div>
    );
  }

  const latestReport = reports && reports.length > 0 ? reports[0] : null;
  const marketCap = latestReport?.price_per_share && latestReport?.shares_outstanding
    ? latestReport.price_per_share * latestReport.shares_outstanding
    : null;

  return (
    <div className="company-detail-wrapper">
      <div className="company-detail-container">
        <div className="detail-header">
          <button onClick={() => navigate('/companies')} className="btn-back">
            ← Назад к списку компаний
          </button>
        </div>

        {/* Hero Section */}
        <div className="company-hero">
          <div className="company-title-section">
            <h1 className="company-title">{company.name}</h1>
            <div className="company-meta">
              <span className="company-ticker">📊 {company.ticker}</span>
              <span className="company-sector">🏢 {company.sector || 'Сектор не указан'}</span>
              <span className="company-currency">💱 {company.currency.toUpperCase()}</span>
            </div>
          </div>
          
          {latestReport ? (
            <div className="company-quick-stats">
              {latestReport.price_per_share && (
                <div className="quick-stat">
                  <span className="stat-label">Цена акции</span>
                  <span className="stat-value">
                    {latestReport.price_per_share.toLocaleString('ru-RU', { 
                      minimumFractionDigits: 2, 
                      maximumFractionDigits: 2 
                    })} {latestReport.currency}
                  </span>
                  <span className="stat-date">📅 на {latestReport.report_date}</span>
                </div>
              )}
              {marketCap && (
                <div className="quick-stat">
                  <span className="stat-label">Капитализация</span>
                  <span className="stat-value">
                    {(marketCap / 1_000_000_000).toFixed(2)} млрд {latestReport.currency}
                  </span>
                  <span className="stat-date">📅 на {latestReport.report_date}</span>
                </div>
              )}
              {latestReport.revenue && (
                <div className="quick-stat">
                  <span className="stat-label">Выручка</span>
                  <span className="stat-value">
                    {(latestReport.revenue / 1_000_000_000).toFixed(2)} млрд
                  </span>
                  <span className="stat-date">📅 за период до {latestReport.report_date}</span>
                </div>
              )}
              {latestReport.net_income && (
                <div className="quick-stat">
                  <span className="stat-label">Чистая прибыль</span>
                  <span className="stat-value">
                    {(latestReport.net_income / 1_000_000_000).toFixed(2)} млрд
                  </span>
                  <span className="stat-date">📅 за период до {latestReport.report_date}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="company-quick-stats">
              <div className="placeholder-content">
                <div className="placeholder-icon">📊</div>
                <p>Финансовые показатели появятся после добавления первого отчета</p>
              </div>
            </div>
          )}
        </div>

        {/* Content Grid */}
        <div className="company-content-grid">
          {/* Sidebar */}
          <div className="content-sidebar">
            {/* Basic Info */}
            <section className="info-card">
              <h2 className="card-title">📋 Основная информация</h2>
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
                <div className="info-item">
                  <span className="info-label">Валюта:</span>
                  <span className="info-value">{company.currency.toUpperCase()}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Размер лота:</span>
                  <span className="info-value">{company.lot}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">API Trading:</span>
                  <span className="info-value">
                    {company.api_trade_available_flag ? '✅ Доступно' : '❌ Недоступно'}
                  </span>
                </div>
              </div>
            </section>

            {/* Multipliers */}
            <section className="info-card">
              <h2 className="card-title">📈 Мультипликаторы</h2>
              <ul className="multipliers-list">
                <li>
                  <span>P/E:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
                <li>
                  <span>P/B:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
                <li>
                  <span>ROE:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
                <li>
                  <span>Debt/Equity:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
                <li>
                  <span>Current Ratio:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
                <li>
                  <span>Dividend Yield:</span>
                  <span className="placeholder-value">Скоро</span>
                </li>
              </ul>
              <div className="placeholder-content" style={{ marginTop: '15px' }}>
                <p>Мультипликаторы будут рассчитаны автоматически после добавления финансовых отчетов</p>
              </div>
            </section>
          </div>

          {/* Main Content */}
          <div className="content-main">
            {/* Business Description */}
            <section className="info-card">
              <h2 className="card-title">🏢 О компании</h2>
              <div className="placeholder-content">
                <div className="placeholder-icon">📝</div>
                <p className="business-description">
                  Здесь будет размещено подробное описание бизнеса компании <strong>{company.name}</strong>, 
                  включая историю создания, основные направления деятельности, ключевые продукты и услуги, 
                  конкурентные преимущества и стратегию развития.
                </p>
              </div>
            </section>

            {/* Price Chart */}
            <section className="info-card">
              <h2 className="card-title">📊 График цены акций</h2>
              <div className="chart-placeholder">
                <span>График цены акций за последний год</span>
              </div>
            </section>

            {/* Financial Reports */}
            <section className="info-card">
              <div className="reports-header">
                <h2 className="card-title" style={{ margin: 0, border: 'none', padding: 0 }}>
                  📄 Финансовые отчеты
                </h2>
                <button className="btn-add-report" onClick={() => alert('Функция добавления отчета')}>
                  + Добавить отчет
                </button>
              </div>
              
              {reportsLoading ? (
                <div className="loading-small">⏳ Загрузка отчетов...</div>
              ) : reports && reports.length > 0 ? (
                <div className="reports-compact-list">
                  {reports.map((report) => (
                    <div 
                      key={report.id} 
                      className="report-compact-item"
                      onClick={() => alert(`Просмотр отчета ${report.id}`)}
                    >
                      <div className="report-compact-info">
                        <span className="report-compact-date">📅 {report.report_date}</span>
                        <div className="report-compact-meta">
                          <span className="report-compact-currency">
                            💰 {report.currency.toUpperCase()}
                          </span>
                          {report.dividends_paid && (
                            <span className="report-compact-dividend">💵 Дивиденды</span>
                          )}
                          {report.revenue && (
                            <span style={{ 
                              fontSize: '12px', 
                              color: '#3498db',
                              backgroundColor: '#e3f2fd',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              fontWeight: 600,
                              border: '1px solid #3498db'
                            }}>
                              📊 Выручка: {(report.revenue / 1_000_000_000).toFixed(2)} млрд
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="placeholder-content">
                  <div className="placeholder-icon">📊</div>
                  <p>
                    Финансовых отчетов пока нет.<br />
                    Добавьте первый отчет, чтобы начать анализ компании по методу Бенджамина Грэма.
                  </p>
                </div>
              )}
            </section>

            {/* Multipliers Chart */}
            <section className="info-card">
              <h2 className="card-title">📉 Динамика мультипликаторов</h2>
              <div className="chart-placeholder">
                <span>График изменения P/E, P/B, ROE и других показателей</span>
              </div>
            </section>

            {/* Graham Analysis */}
            <section className="info-card">
              <h2 className="card-title">🎯 Анализ по методу Бенджамина Грэма</h2>
              <div className="analysis-section">
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Размер компании (выручка &gt; $100 млн)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Финансовая устойчивость (Current Ratio &gt; 2)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Стабильность прибыли (прибыль за 10 лет)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Дивидендная история (дивиденды 20+ лет)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Умеренное P/E (P/E &lt; 15)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Умеренное P/B (P/B &lt; 1.5)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
                <div className="analysis-criteria">
                  <span className="criteria-name">✓ Низкий долг (Debt/Equity &lt; 1)</span>
                  <span className="criteria-status pending">Ожидание данных</span>
                </div>
              </div>
              <div className="placeholder-content" style={{ marginTop: '20px' }}>
                <p>
                  Автоматический анализ будет доступен после добавления достаточного количества 
                  финансовых отчетов. Система оценит компанию по всем критериям защитного инвестора.
                </p>
              </div>
            </section>

            {/* News */}
            <section className="info-card">
              <h2 className="card-title">📰 Новости компании</h2>
              <div className="placeholder-content">
                <div className="placeholder-icon">📰</div>
                <p>
                  Здесь будут отображаться последние новости, связанные с компанией {company.name}, 
                  включая финансовые отчеты, дивидендные выплаты, изменения в руководстве и другие 
                  важные события.
                </p>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CompanyDetail;
