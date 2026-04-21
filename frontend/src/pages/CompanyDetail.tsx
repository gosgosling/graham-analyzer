import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  getCompanyById,
  getCompanyReports,
  createFinancialReport,
  updateFinancialReport,
  deleteFinancialReport,
  refreshCompanyMultipliers,
  verifyReport,
} from '../services';
import { FinancialReport, FinancialReportCreate } from '../types';
import MultipliersPanel from '../components/MultipliersPanel';
import ReportForm from '../components/ReportForm';
import VerificationBadge from '../components/VerificationBadge';
import AiParsePdfModal from '../components/AiParsePdfModal';
import { shadeHex, isLightBrandHex, isNeutralBrandForHero } from '../utils/brandColor';
import { getCompanyLogoCandidates } from '../utils/companyLogo';
import './CompanyDetail.css';

type ReportPeriodFilter = 'all' | 'annual' | 'quarterly' | 'semi_annual';

const CompanyDetail: React.FC = () => {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const [editingReport, setEditingReport] = useState<FinancialReport | null>(null);
  const [showAddReportForm, setShowAddReportForm] = useState(false);
  const [aiParseMode, setAiParseMode] = useState<'create' | 'compare' | 'batch' | null>(null);
  // Состояние раздела отчётов
  const [reportsExpanded, setReportsExpanded] = useState(true);
  const [reportPeriodFilter, setReportPeriodFilter] = useState<ReportPeriodFilter>('annual');
  const [reportStandardFilter, setReportStandardFilter] = useState<string>('all');
  const [showAllReports, setShowAllReports] = useState(false);

  const createReportMutation = useMutation({
    mutationFn: createFinancialReport,
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      await refreshCompanyMultipliers(Number(companyId), true);
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      setShowAddReportForm(false);
      alert('Отчёт успешно добавлен');
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      const msg =
        typeof d === 'string'
          ? d
          : Array.isArray(d)
            ? d.map((e: { msg?: string }) => e?.msg).filter(Boolean).join('; ')
            : 'Ошибка при создании отчёта';
      alert(msg);
    },
  });

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

  const verifyReportMutation = useMutation({
    mutationFn: (reportId: number) => verifyReport(reportId),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      setSelectedReport(updated);
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось подтвердить отчёт');
    },
  });

  // Удаление отчёта: инвалидируем кэш и триггерим пересчёт current-мультипликаторов
  // (чтобы панель LTM-показателей не показывала данные удалённого отчёта).
  const deleteReportMutation = useMutation({
    mutationFn: (reportId: number) => deleteFinancialReport(reportId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      try {
        await refreshCompanyMultipliers(Number(companyId), true);
      } catch {
        // не критично — кеш уже инвалидирован, при следующем переходе пересчитается
      }
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      setSelectedReport(null);
      setEditingReport(null);
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось удалить отчёт');
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

  // Уникальные стандарты учёта для фильтра — хук должен быть до любых return
  const availableStandards = useMemo(() => {
    if (!reports) return [];
    return Array.from(new Set(reports.map((r) => r.accounting_standard).filter(Boolean)));
  }, [reports]);

  const unverifiedCount = useMemo(
    () => (reports || []).filter((r) => r.verified_by_analyst === false).length,
    [reports],
  );

  // Отфильтрованные отчёты — хук должен быть до любых return
  const filteredReports = useMemo(() => {
    if (!reports) return [];
    return reports.filter((r) => {
      const pt = r.period_type.toLowerCase();
      if (reportPeriodFilter !== 'all' && pt !== reportPeriodFilter) return false;
      if (reportStandardFilter !== 'all' && r.accounting_standard !== reportStandardFilter) return false;
      return true;
    });
  }, [reports, reportPeriodFilter, reportStandardFilter]);

  const visibleReports = showAllReports ? filteredReports : filteredReports.slice(0, 5);

  /** Ч/б/серый бренд — оставляем стандартный фиолетовый градиент шапки */
  const useBrandInHero = useMemo(
    () =>
      Boolean(
        company?.brand_color && !isNeutralBrandForHero(company.brand_color),
      ),
    [company?.brand_color],
  );

  const brandLight = useMemo(
    () =>
      Boolean(
        useBrandInHero && company?.brand_color && isLightBrandHex(company.brand_color),
      ),
    [useBrandInHero, company?.brand_color],
  );

  const gradientEndColor = useMemo(() => {
    if (!useBrandInHero || !company?.brand_color) return null;
    return shadeHex(company.brand_color, brandLight ? 0.34 : 0.52);
  }, [useBrandInHero, company?.brand_color, brandLight]);

  const logoCandidates = useMemo(
    () => (company ? getCompanyLogoCandidates(company) : []),
    [company],
  );

  const [logoAttempt, setLogoAttempt] = useState(0);

  useEffect(() => {
    setLogoAttempt(0);
  }, [company?.id]);

  const logoSrc =
    logoCandidates.length > 0 && logoAttempt < logoCandidates.length
      ? logoCandidates[logoAttempt]
      : null;

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
      <div
        className={`company-hero${useBrandInHero ? ' company-hero--branded' : ''}${
          brandLight ? ' company-hero--light-brand' : ''
        }`}
        style={
          useBrandInHero && company.brand_color && gradientEndColor
            ? {
                background: `linear-gradient(135deg, ${company.brand_color} 0%, ${gradientEndColor} 100%)`,
              }
            : undefined
        }
      >
        <div className="company-hero-main">
          {logoSrc && (
            <img
              key={logoSrc}
              src={logoSrc}
              alt=""
              className="company-hero-logo"
              referrerPolicy="no-referrer"
              loading="eager"
              decoding="async"
              onError={() => setLogoAttempt((a) => a + 1)}
            />
          )}
          <div className="company-title-section">
            <h1 className="company-title">{company.name}</h1>
            <div className="company-meta">
              <span className="company-ticker">{company.ticker}</span>
              <span className="company-sector">{company.sector || 'Не указан'}</span>
              <span className="company-currency">💱 {company.currency}</span>
            </div>
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

      {/* Мультипликаторы — сразу под шапкой */}
      <MultipliersPanel company={company} />

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
        </div>

        {/* Правая колонка - Отчеты и новости */}
        <div className="content-column">
          {/* Финансовые отчеты */}
          <section className="info-card">
            {/* Заголовок: сворачивание по клику на название; справа — как в списке компаний + стрелка */}
            <div className="reports-card-header">
              <div
                className="reports-card-header-title"
                role="button"
                tabIndex={0}
                aria-expanded={reportsExpanded}
                onClick={() => setReportsExpanded((v) => !v)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setReportsExpanded((v) => !v);
                  }
                }}
              >
                <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
                  📋 Финансовые отчеты
                  {reports && reports.length > 0 && (
                    <span className="reports-count-badge">{reports.length}</span>
                  )}
                  {unverifiedCount > 0 && (
                    <span
                      title={`${unverifiedCount} отчётов требуют проверки аналитиком`}
                      style={{
                        background: '#fff7e6',
                        border: '1px solid #ffd591',
                        color: '#ad6800',
                        fontSize: 11,
                        fontWeight: 600,
                        padding: '2px 8px',
                        borderRadius: 12,
                      }}
                    >
                      🤖 {unverifiedCount} не проверено
                    </span>
                  )}
                </h2>
              </div>
              <div className="reports-card-header-actions">
                <AddReportMenu
                  disabled={createReportMutation.isPending}
                  onManualAdd={() => {
                    setShowAddReportForm(true);
                    setSelectedReport(null);
                    setEditingReport(null);
                    setReportsExpanded(true);
                  }}
                  onAiCreate={() => {
                    setAiParseMode('create');
                    setReportsExpanded(true);
                  }}
                  onAiBatch={() => {
                    setAiParseMode('batch');
                    setReportsExpanded(true);
                  }}
                  onAiCompare={() => {
                    setAiParseMode('compare');
                    setReportsExpanded(true);
                  }}
                />
                <button
                  type="button"
                  className="reports-toggle-arrow-btn"
                  aria-expanded={reportsExpanded}
                  aria-label={reportsExpanded ? 'Свернуть список отчётов' : 'Развернуть список отчётов'}
                  onClick={(e) => {
                    e.stopPropagation();
                    setReportsExpanded((v) => !v);
                  }}
                >
                  {reportsExpanded ? '▲' : '▼'}
                </button>
              </div>
            </div>

            {reportsExpanded && (
              <>
                {reportsLoading ? (
                  <div className="loading-small">Загрузка отчетов...</div>
                ) : reports && reports.length > 0 ? (
                  <>
                    {/* Фильтры */}
                    <div className="reports-filters">
                      <div className="reports-filter-row">
                        {(
                          [
                            { key: 'all',        label: 'Все' },
                            { key: 'annual',     label: 'Годовые' },
                            { key: 'quarterly',  label: 'Квартальные' },
                            { key: 'semi_annual',label: 'Полугодовые' },
                          ] as { key: ReportPeriodFilter; label: string }[]
                        ).map(({ key, label }) => (
                          <button
                            key={key}
                            className={`reports-filter-pill ${reportPeriodFilter === key ? 'active' : ''}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setReportPeriodFilter(key);
                              setShowAllReports(false);
                            }}
                          >
                            {label}
                          </button>
                        ))}
                        {availableStandards.length > 1 && (
                          <>
                            <span className="reports-filter-sep">|</span>
                            <button
                              className={`reports-filter-pill ${reportStandardFilter === 'all' ? 'active' : ''}`}
                              onClick={(e) => { e.stopPropagation(); setReportStandardFilter('all'); }}
                            >
                              Все стандарты
                            </button>
                            {availableStandards.map((s) => (
                              <button
                                key={s}
                                className={`reports-filter-pill ${reportStandardFilter === s ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); setReportStandardFilter(s); setShowAllReports(false); }}
                              >
                                {s}
                              </button>
                            ))}
                          </>
                        )}
                      </div>
                    </div>

                    {filteredReports.length === 0 ? (
                      <div className="placeholder-content" style={{ marginTop: 12 }}>
                        <p>Нет отчётов по выбранным фильтрам</p>
                      </div>
                    ) : (
                      <>
                        <div className="reports-compact-list">
                          {visibleReports.map((report) => {
                            const pt = report.period_type.toLowerCase();
                            const periodLabel = pt === 'annual'
                              ? 'Годовой'
                              : pt === 'semi_annual'
                              ? 'Полугодовой'
                              : `Q${report.fiscal_quarter}`;
                            const needsVerification = report.verified_by_analyst === false;
                            return (
                              <div
                                key={report.id}
                                className="report-compact-item"
                                style={
                                  needsVerification
                                    ? {
                                        background: '#fffbe6',
                                        borderLeft: '3px solid #ffa940',
                                      }
                                    : undefined
                                }
                              >
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
                                    <VerificationBadge
                                      autoExtracted={report.auto_extracted}
                                      verifiedByAnalyst={report.verified_by_analyst}
                                    />
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

                        {filteredReports.length > 5 && (
                          <button
                            className="reports-show-more"
                            onClick={(e) => { e.stopPropagation(); setShowAllReports((v) => !v); }}
                          >
                            {showAllReports
                              ? '▲ Свернуть'
                              : `▼ Показать все (${filteredReports.length})`}
                          </button>
                        )}
                      </>
                    )}
                  </>
                ) : (
                  <div className="reports-empty-state">
                    <p className="reports-empty-title">Финансовых отчётов пока нет</p>
                    <p className="reports-empty-hint">
                      Добавьте отчёт по этой компании — данные появятся в мультипликаторах и показателях.
                    </p>
                    <button
                      type="button"
                      className="btn-add-report-inline"
                      disabled={createReportMutation.isPending}
                      onClick={() => {
                        setShowAddReportForm(true);
                        setSelectedReport(null);
                        setEditingReport(null);
                      }}
                    >
                      + Добавить отчет
                    </button>
                  </div>
                )}
              </>
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
            setShowAddReportForm(false);
            setEditingReport(report);
            setSelectedReport(null);
          }}
          onVerify={(reportId) => verifyReportMutation.mutate(reportId)}
          verifyPending={verifyReportMutation.isPending}
          onDelete={(reportId) => {
            const r = selectedReport;
            const label = r ? `${r.fiscal_year} ${r.period_type}` : `#${reportId}`;
            const confirmMsg =
              `Удалить отчёт "${label}"?\n\n` +
              'Это действие необратимо. Вместе с отчётом будут удалены все ' +
              'привязанные к нему записи из истории мультипликаторов ' +
              '(type=report_based).\n\n' +
              'Текущие LTM-мультипликаторы (type=current) автоматически ' +
              'пересчитаются по оставшимся отчётам.';
            if (window.confirm(confirmMsg)) {
              deleteReportMutation.mutate(reportId);
            }
          }}
          deletePending={deleteReportMutation.isPending}
        />
      )}

      {/* Модалка AI-парсинга PDF (create или compare) */}
      {aiParseMode && company && (
        <AiParsePdfModal
          companyId={Number(companyId)}
          companyName={company.name}
          ticker={company.ticker}
          initialMode={aiParseMode}
          onClose={() => setAiParseMode(null)}
        />
      )}

      {/* Форма создания отчёта */}
      {showAddReportForm && company && !editingReport && (
        <ReportForm
          companyId={Number(companyId)}
          companyName={company.name}
          ticker={company.ticker}
          sector={company.sector}
          onSubmit={async (data) => {
            await createReportMutation.mutateAsync(data);
          }}
          onCancel={() => setShowAddReportForm(false)}
        />
      )}

      {/* Форма редактирования отчёта */}
      {editingReport && company && !showAddReportForm && (
        <ReportForm
          companyId={Number(companyId)}
          companyName={company.name}
          ticker={company.ticker}
          sector={company.sector}
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
  onVerify?: (reportId: number) => void;
  verifyPending?: boolean;
  onDelete?: (reportId: number) => void;
  deletePending?: boolean;
}

const ReportDetailModal: React.FC<ReportDetailModalProps> = ({
  report,
  onClose,
  onEdit,
  onVerify,
  verifyPending,
  onDelete,
  deletePending,
}) => {
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
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              📊 Финансовый отчет
              <VerificationBadge
                autoExtracted={report.auto_extracted}
                verifiedByAnalyst={report.verified_by_analyst}
              />
            </h2>
            <p className="report-detail-subtitle">
              {report.fiscal_year} · {periodLabel} · {report.accounting_standard}
              {report.consolidated ? ' · Консолидированный' : ''}
            </p>
          </div>
          <button onClick={onClose} className="btn-close">✕</button>
        </div>

        <div className="report-detail-content">
          {/* AI-блок: предупреждение и заметки модели */}
          {report.verified_by_analyst === false && (
            <div
              className="detail-section"
              style={{
                background: '#fff7e6',
                border: '1px solid #ffd591',
                borderRadius: 8,
                padding: 14,
              }}
            >
              <h3 style={{ color: '#ad6800', marginTop: 0 }}>
                {report.auto_extracted ? '🤖 Черновик AI-парсера' : '⚠ Требует проверки'}
              </h3>
              <p style={{ margin: '4px 0', color: '#874d00', fontSize: 13 }}>
                Отчёт ещё не подтверждён аналитиком.
                {report.extraction_model && (
                  <>
                    {' '}Создан моделью <code>{report.extraction_model}</code>.
                  </>
                )}{' '}
                Сверьте значения с PDF и нажмите «Подтвердить» в футере этого окна
                (или отредактируйте через «Редактировать» — сохранение формы тоже помечает отчёт как проверенный).
              </p>
              {report.extraction_notes && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 500, color: '#874d00' }}>
                    Заметки модели
                  </summary>
                  <pre
                    style={{
                      margin: '8px 0 0',
                      padding: 10,
                      background: 'white',
                      border: '1px solid #ffd591',
                      borderRadius: 4,
                      fontSize: 12,
                      color: '#2c3e50',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      maxHeight: 220,
                      overflowY: 'auto',
                    }}
                  >
                    {report.extraction_notes}
                  </pre>
                </details>
              )}
            </div>
          )}

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
            {onVerify && report.verified_by_analyst === false && (
              <button
                onClick={() => onVerify(report.id)}
                className="btn-edit-report"
                disabled={verifyPending}
                style={{
                  background: '#52c41a',
                  color: 'white',
                  border: 'none',
                }}
                title="Подтвердить, что отчёт проверен аналитиком"
              >
                {verifyPending ? 'Подтверждаем…' : '✓ Подтвердить'}
              </button>
            )}
            {onEdit && (
              <button onClick={() => onEdit(report)} className="btn-edit-report">
                ✏️ Редактировать
              </button>
            )}
            {onDelete && (
              <button
                onClick={() => onDelete(report.id)}
                className="btn-edit-report"
                disabled={deletePending}
                style={{
                  background: '#ff4d4f',
                  color: 'white',
                  border: 'none',
                }}
                title="Удалить отчёт и связанные записи в истории мультипликаторов"
              >
                {deletePending ? 'Удаляем…' : '🗑️ Удалить'}
              </button>
            )}
            <button onClick={onClose} className="btn-close-detail">Закрыть</button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Выпадающее меню «Добавить отчёт» ──────────────────────────────────────
//
// Один компактный primary-CTA со стрелкой-переключателем выпадающего меню.
// Современный паттерн вместо 4 рядом стоящих кнопок — не растягивает шапку
// и логически группирует все способы создания отчёта.

interface AddReportMenuProps {
  disabled?: boolean;
  onManualAdd: () => void;
  onAiCreate: () => void;
  onAiBatch: () => void;
  onAiCompare: () => void;
}

const AddReportMenu: React.FC<AddReportMenuProps> = ({
  disabled,
  onManualAdd,
  onAiCreate,
  onAiBatch,
  onAiCompare,
}) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const firstItemRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    // Автофокус на первый пункт меню — удобно для клавиатуры.
    window.setTimeout(() => firstItemRef.current?.focus(), 0);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const run = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(false);
    fn();
  };

  return (
    <div className="add-report-menu" ref={rootRef}>
      <button
        type="button"
        className="add-report-menu-trigger"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((prev) => !prev);
        }}
      >
        <span className="add-report-menu-label">+ Добавить отчёт</span>
        <span className={`add-report-menu-caret ${open ? 'is-open' : ''}`} aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="add-report-menu-dropdown" role="menu">
          <div className="add-report-menu-section-label">Вручную</div>
          <button
            ref={firstItemRef}
            type="button"
            role="menuitem"
            className="add-report-menu-item"
            onClick={run(onManualAdd)}
          >
            <span className="add-report-menu-item-icon">✍️</span>
            <span className="add-report-menu-item-body">
              <span className="add-report-menu-item-title">Заполнить форму</span>
              <span className="add-report-menu-item-sub">
                Ручной ввод показателей по отчёту
              </span>
            </span>
          </button>

          <div className="add-report-menu-divider" />

          <div className="add-report-menu-section-label">AI-парсер (PDF)</div>
          <button
            type="button"
            role="menuitem"
            className="add-report-menu-item"
            onClick={run(onAiCreate)}
          >
            <span className="add-report-menu-item-icon">🤖</span>
            <span className="add-report-menu-item-body">
              <span className="add-report-menu-item-title">Загрузить один PDF</span>
              <span className="add-report-menu-item-sub">
                Модель извлечёт показатели и создаст черновик
              </span>
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="add-report-menu-item"
            onClick={run(onAiBatch)}
          >
            <span className="add-report-menu-item-icon">📁</span>
            <span className="add-report-menu-item-body">
              <span className="add-report-menu-item-title">Папка с PDF (пакет)</span>
              <span className="add-report-menu-item-sub">
                Все отчёты сразу; уже существующие годы пропускаются
              </span>
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="add-report-menu-item"
            onClick={run(onAiCompare)}
          >
            <span className="add-report-menu-item-icon">🔍</span>
            <span className="add-report-menu-item-body">
              <span className="add-report-menu-item-title">Сравнить PDF с базой</span>
              <span className="add-report-menu-item-sub">
                Проверить качество модели. В БД ничего не пишется.
              </span>
            </span>
          </button>
        </div>
      )}
    </div>
  );
};

export default CompanyDetail;
