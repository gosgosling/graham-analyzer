import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { getCompanyById, getCompanyReports, updateFinancialReport, refreshCompanyMultipliers } from '../services/api';
import { FinancialReport, FinancialReportCreate } from '../types';
import MultipliersPanel from '../components/MultipliersPanel';
import ReportForm from '../components/ReportForm';
import './CompanyDetail.css';

const CompanyDetail: React.FC = () => {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const [editingReport, setEditingReport] = useState<FinancialReport | null>(null);

  const updateReportMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FinancialReportCreate }) =>
      updateFinancialReport(id, data),
    onSuccess: async (_, variables) => {
      // Инвалидируем кэш отчётов и мультипликаторов
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      // Пересчитываем мультипликаторы на сервере
      await refreshCompanyMultipliers(Number(companyId), true);
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      setEditingReport(null);
      setSelectedReport(null);
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : 'Ошибка при обновлении отчёта';
      alert(msg);
    },
  });

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

  // Вычисляем базовую статистику (используем рублёвые значения)
  // Финансовые показатели хранятся в МИЛЛИОНАХ ₽ — при отображении делим на 1000 для млрд
  const latestReport = reports && reports.length > 0 ? reports[0] : null;
  const marketCapMln = latestReport?.price_per_share_rub && latestReport?.shares_outstanding
    ? (latestReport.price_per_share_rub * latestReport.shares_outstanding) / 1_000_000
    : null;

  /** Форматирует значение в млн ₽ → показывает в млн/млрд/трлн */
  const fmtMln = (n: number | null | undefined): string => {
    if (n === null || n === undefined) return '—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ' трлн ₽';
    if (abs >= 1_000)     return (n / 1_000).toFixed(2) + ' млрд ₽';
    return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн ₽';
  };

  return (
    <div className="company-detail-container">
      {/* Хедер с кнопкой назад */}
      <div className="detail-header">
        <button onClick={() => navigate('/companies')} className="btn-back">
          ← Назад к списку
        </button>
      </div>

      {/* Основная информация о компании */}
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
            {latestReport.price_per_share_rub && (
              <div className="quick-stat">
                <span className="stat-label">Цена акции</span>
                <span className="stat-value">
                  {latestReport.price_per_share_rub.toLocaleString()} ₽
                </span>
                {latestReport.currency === 'USD' && latestReport.price_per_share && (
                  <span className="stat-hint">({latestReport.price_per_share.toLocaleString()} USD)</span>
                )}
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
            {marketCapMln && (
              <div className="quick-stat">
                <span className="stat-label">Капитализация</span>
                <span className="stat-value">{fmtMln(marketCapMln)}</span>
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Основная сетка с информацией */}
      <div className="company-content-grid">
        {/* Левая колонка - Основная информация */}
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
              <div className="info-item">
                <span className="info-label">Валюта:</span>
                <span className="info-value">{company.currency}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Размер лота:</span>
                <span className="info-value">{company.lot}</span>
              </div>
              <div className="info-item">
                <span className="info-label">API торговля:</span>
                <span className={`info-badge ${company.api_trade_available_flag ? 'active' : 'inactive'}`}>
                  {company.api_trade_available_flag ? '✓ Доступна' : '✗ Недоступна'}
                </span>
              </div>
            </div>
          </section>

          {/* Описание бизнеса - заглушка */}
          <section className="info-card">
            <h2 className="card-title">🏢 О компании</h2>
            <div className="placeholder-content">
              <p>Подробное описание бизнеса компании будет добавлено позже.</p>
              <p className="placeholder-hint">
                Здесь будет информация о деятельности компании, основных направлениях бизнеса, 
                истории развития и ключевых достижениях.
              </p>
            </div>
          </section>

          {/* График цены - заглушка */}
          <section className="info-card">
            <h2 className="card-title">📈 График цены акций</h2>
            <div className="placeholder-chart">
              <div className="chart-placeholder">
                <span className="placeholder-icon">📊</span>
                <p>График цены акций</p>
                <p className="placeholder-hint">Интеграция с биржевыми данными в разработке</p>
              </div>
            </div>
          </section>

          {/* Мультипликаторы */}
          <MultipliersPanel company={company} />
        </div>

        {/* Правая колонка - Отчеты и новости */}
        <div className="content-column">
          {/* Финансовые отчеты */}
          <section className="info-card">
            <h2 className="card-title">📋 Финансовые отчеты</h2>
            {reportsLoading ? (
              <div className="loading-small">Загрузка отчетов...</div>
            ) : reports && reports.length > 0 ? (
              <div className="reports-compact-list">
                {reports.map((report) => {
                  const pt = report.period_type.toLowerCase();
                  const periodLabel = pt === 'annual'
                    ? 'Годовой'
                    : pt === 'semi_annual'
                    ? 'Полугодовой'
                    : `Q${report.fiscal_quarter}`;
                  return (
                    <div key={report.id} className="report-compact-item">
                      <div className="report-compact-info">
                        <span className="report-compact-year">{report.fiscal_year}</span>
                        <span className="report-compact-period">{periodLabel}</span>
                        <span className="report-compact-date">{report.report_date}</span>
                        <div className="report-compact-meta">
                          <span className="report-compact-standard">{report.accounting_standard}</span>
                          <span className="report-compact-currency">{report.currency}</span>
                          {report.dividends_paid && (
                            <span className="report-compact-dividend">💵</span>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => setSelectedReport(report)}
                        className="btn-compact-view"
                      >
                        Просмотр
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="placeholder-content">
                <p>Финансовых отчетов пока нет</p>
                <p className="placeholder-hint">
                  Добавьте отчеты вручную через список компаний или загрузите из внешних источников
                </p>
              </div>
            )}
          </section>

          {/* Последние финансовые показатели */}
          {latestReport && (
            <section className="info-card">
              <h2 className="card-title">💰 Последние показатели</h2>
              <div className="financial-metrics">
                {latestReport.revenue_rub && (
                  <div className="metric-item">
                    <span className="metric-label">Выручка</span>
                    <span className="metric-value">{fmtMln(latestReport.revenue_rub)}</span>
                    {latestReport.currency === 'USD' && latestReport.revenue && (
                      <span className="metric-hint">
                        ({fmtMln(latestReport.revenue)} в USD)
                      </span>
                    )}
                  </div>
                )}
                {latestReport.net_income_rub && (
                  <div className="metric-item">
                    <span className="metric-label">Чистая прибыль</span>
                    <span className="metric-value">{fmtMln(latestReport.net_income_rub)}</span>
                    {latestReport.currency === 'USD' && latestReport.net_income && (
                      <span className="metric-hint">
                        ({fmtMln(latestReport.net_income)} в USD)
                      </span>
                    )}
                  </div>
                )}
                {latestReport.total_assets_rub && (
                  <div className="metric-item">
                    <span className="metric-label">Активы</span>
                    <span className="metric-value">{fmtMln(latestReport.total_assets_rub)}</span>
                    {latestReport.currency === 'USD' && latestReport.total_assets && (
                      <span className="metric-hint">
                        ({fmtMln(latestReport.total_assets)} в USD)
                      </span>
                    )}
                  </div>
                )}
                {latestReport.equity_rub && (
                  <div className="metric-item">
                    <span className="metric-label">Капитал</span>
                    <span className="metric-value">{fmtMln(latestReport.equity_rub)}</span>
                    {latestReport.currency === 'USD' && latestReport.equity && (
                      <span className="metric-hint">
                        ({fmtMln(latestReport.equity)} в USD)
                      </span>
                    )}
                  </div>
                )}
              </div>
              <p className="report-date-info">По данным отчета от {latestReport.report_date}</p>
            </section>
          )}

          {/* Новости - заглушка */}
          <section className="info-card">
            <h2 className="card-title">📰 Новости</h2>
            <div className="placeholder-content">
              <p>Новости компании появятся здесь</p>
              <p className="placeholder-hint">
                Планируется интеграция с источниками новостей для отображения актуальной информации
              </p>
            </div>
          </section>

          {/* Анализ по Грэму - заглушка */}
          <section className="info-card">
            <h2 className="card-title">🎯 Анализ по методу Грэма</h2>
            <div className="placeholder-content">
              <p>Автоматический анализ будет доступен после накопления данных</p>
              <p className="placeholder-hint">
                Система проанализирует финансовые показатели компании и даст рекомендацию: 
                недооценена, стабильна или переоценена
              </p>
            </div>
          </section>
        </div>
      </div>

      {/* Модальное окно просмотра отчёта */}
      {selectedReport && !editingReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={() => setSelectedReport(null)}
          onEdit={(report) => {
            setEditingReport(report);
            setSelectedReport(null);
          }}
        />
      )}

      {/* Форма редактирования отчёта */}
      {editingReport && company && (
        <ReportForm
          companyId={Number(companyId)}
          companyName={company.name}
          ticker={company.ticker}
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
          onCancel={() => setEditingReport(null)}
        />
      )}
    </div>
  );
};

interface ReportDetailModalProps {
  report: FinancialReport;
  onClose: () => void;
  onEdit?: (report: FinancialReport) => void;
}

const ReportDetailModal: React.FC<ReportDetailModalProps> = ({ report, onClose, onEdit }) => {
  const cur = report.currency;
  const isUsd = cur === 'USD';

  const fmtMln = (n: number | null | undefined, showCur = true): string => {
    if (n === null || n === undefined) return '—';
    const abs = Math.abs(n);
    const suffix = showCur ? ` млн ${cur}` : '';
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ` трлн ${cur}`;
    if (abs >= 1_000)     return (n / 1_000).toFixed(2) + ` млрд ${cur}`;
    return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + suffix;
  };

  const pt = report.period_type.toLowerCase();
  const periodLabel =
    pt === 'annual'
      ? 'Годовой'
      : pt === 'semi_annual'
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
              {report.consolidated ? ' · Консолидированный' : ''}
            </p>
          </div>
          <button onClick={onClose} className="btn-close">✕</button>
        </div>

        <div className="report-detail-content">
          {/* Период и даты */}
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
                <span className="detail-label">Стандарт:</span>
                <span className="detail-value">{report.accounting_standard}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Валюта:</span>
                <span className="detail-value">{cur}{isUsd && report.exchange_rate ? ` (курс: ${report.exchange_rate} ₽)` : ''}</span>
              </div>
            </div>
          </div>

          {/* Рыночные данные */}
          {(report.price_per_share || report.price_at_filing || report.shares_outstanding) && (
            <div className="detail-section">
              <h3>Рыночные данные</h3>
              <div className="detail-grid">
                {report.price_per_share && (
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
                {report.price_at_filing && (
                  <div className="detail-item">
                    <span className="detail-label">Цена на дату публикации:</span>
                    <span className="detail-value">
                      {report.price_at_filing.toLocaleString('ru-RU')} {cur}
                    </span>
                  </div>
                )}
                {report.shares_outstanding && (
                  <div className="detail-item">
                    <span className="detail-label">Акций в обращении:</span>
                    <span className="detail-value">{report.shares_outstanding.toLocaleString('ru-RU')} шт.</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Отчёт о прибылях и убытках */}
          {(report.revenue || report.net_income) && (
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

          {/* Баланс */}
          {(report.total_assets || report.equity || report.total_liabilities) && (
            <div className="detail-section">
              <h3>Балансовые показатели <span className="section-units">(млн {cur})</span></h3>
              <div className="detail-grid">
                {report.total_assets != null && (
                  <div className="detail-item">
                    <span className="detail-label">Активы (всего):</span>
                    <span className="detail-value">{fmtMln(report.total_assets)}</span>
                  </div>
                )}
                {report.current_assets != null && (
                  <div className="detail-item">
                    <span className="detail-label">Оборотные активы:</span>
                    <span className="detail-value">{fmtMln(report.current_assets)}</span>
                  </div>
                )}
                {report.total_liabilities != null && (
                  <div className="detail-item">
                    <span className="detail-label">Обязательства (всего):</span>
                    <span className="detail-value">{fmtMln(report.total_liabilities)}</span>
                  </div>
                )}
                {report.current_liabilities != null && (
                  <div className="detail-item">
                    <span className="detail-label">Краткосрочные обязательства:</span>
                    <span className="detail-value">{fmtMln(report.current_liabilities)}</span>
                  </div>
                )}
                {report.equity != null && (
                  <div className="detail-item">
                    <span className="detail-label">Собственный капитал:</span>
                    <span className="detail-value">{fmtMln(report.equity)}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Дивиденды */}
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
                    <span className="detail-value">
                      {report.dividends_per_share.toLocaleString('ru-RU')} {cur}
                    </span>
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

export default CompanyDetail;
