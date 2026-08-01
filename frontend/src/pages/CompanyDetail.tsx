import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  getCompanyById,
  getCompanyReports,
  createFinancialReport,
  updateFinancialReport,
  deleteFinancialReport,
  refreshCompanyMultipliers,
  verifyReport,
  updateCompanyPreferredShare,
  updateCompanyDescription,
} from '../services';
import { FinancialReport, FinancialReportCreate } from '../types';
import MultipliersPanel from '../components/MultipliersPanel';
import BankMetricsPanel from '../components/BankMetricsPanel';
import VerificationBadge from '../components/VerificationBadge';
import ReportDetailModal from '../components/ReportDetailModal';
import AiParsePdfModal from '../components/AiParsePdfModal';
import { formatPerShare } from '../utils/perShare';
import { formatMln } from '../utils/format';
import { shadeHex, isLightBrandHex, isNeutralBrandForHero } from '../utils/brandColor';
import { computeNetDebt } from '../utils/netDebt';
import { resolveSharesForMultipliers, explainSharesCapBasis } from '../utils/shareCounts';
import SharesCapHover from '../components/SharesCapHover';
import { getCompanyLogoCandidates } from '../utils/companyLogo';
import { isMisclassifiedAsPreferred } from '../utils/companyShareClass';
import './CompanyDetail.css';

type ReportPeriodFilter = 'all' | 'annual' | 'quarterly' | 'semi_annual';

const CompanyDetail: React.FC = () => {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const [aiParseMode, setAiParseMode] = useState<'create' | 'compare' | 'batch' | null>(null);
  // Состояние раздела отчётов
  const [reportsExpanded, setReportsExpanded] = useState(true);
  const [reportPeriodFilter, setReportPeriodFilter] = useState<ReportPeriodFilter>('annual');
  const [reportStandardFilter, setReportStandardFilter] = useState<string>('all');
  const [showAllReports, setShowAllReports] = useState(false);
  const [editingDescription, setEditingDescription] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState('');

  const createReportMutation = useMutation({
    mutationFn: createFinancialReport,
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      await refreshCompanyMultipliers(Number(companyId), true);
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
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
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      // Пересчитываем мультипликаторы на сервере
      await refreshCompanyMultipliers(Number(companyId), true);
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
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
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      setSelectedReport(updated);
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось подтвердить отчёт');
    },
  });

  // Сброс ошибочного флага is_preferred_share (если в БД остался после старого UI).
  const preferredShareMutation = useMutation({
    mutationFn: ({ id, value }: { id: number; value: boolean }) =>
      updateCompanyPreferredShare(id, value),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['company', companyId] });
      await queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
      await queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
      await queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось обновить тип акций');
    },
  });

  const descriptionMutation = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string | null }) =>
      updateCompanyDescription(id, text),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['company', companyId] });
      setEditingDescription(false);
    },
    onError: (err: any) => {
      const d = err?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Не удалось сохранить описание');
    },
  });

  // Удаление отчёта: инвалидируем кэш и триггерим пересчёт current-мультипликаторов
  // (чтобы панель LTM-показателей не показывала данные удалённого отчёта).
  const deleteReportMutation = useMutation({
    mutationFn: (reportId: number) => deleteFinancialReport(reportId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['reports', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      try {
        await refreshCompanyMultipliers(Number(companyId), true);
      } catch {
        // не критично — кеш уже инвалидирован, при следующем переходе пересчитается
      }
      queryClient.invalidateQueries({ queryKey: ['multipliers', companyId] });
      setSelectedReport(null);
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

  // Сброс ошибочного «префы» (старая кнопка-индикатор: клик по «Обыкн.» включал префы у SIBN и т.п.)
  const misclassifiedFixRef = useRef<number | null>(null);
  useEffect(() => {
    misclassifiedFixRef.current = null;
  }, [companyId]);
  useEffect(() => {
    if (!company?.id) return;
    if (!isMisclassifiedAsPreferred(company)) return;
    if (misclassifiedFixRef.current === company.id) return;
    misclassifiedFixRef.current = company.id;
    preferredShareMutation.mutate({ id: company.id, value: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- однократный сброс по company.id
  }, [company?.id, company?.is_preferred_share, company?.ticker, company?.name]);

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

  const firstReports = filteredReports.slice(0, 5);
  const extraReports = filteredReports.slice(5);

  const renderReportRow = (report: FinancialReport) => {
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
        className={`report-compact-item${needsVerification ? ' report-compact-item--needs-review' : ''}`}
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
  };

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
  const latestSharesForCap = latestReport ? resolveSharesForMultipliers(latestReport) : null;
  const latestCapExplanation = latestReport
    ? explainSharesCapBasis(latestReport, latestSharesForCap)
    : null;
  const marketCapMln = latestReport?.price_per_share_rub && latestSharesForCap
    ? (latestReport.price_per_share_rub * latestSharesForCap) / 1_000_000
    : null;

  /** Значения отчёта хранятся в млн ₽; показываем в млн/млрд/трлн. */
  const fmtMln = (n: number | null | undefined): string => formatMln(n);

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
                  {formatPerShare(latestReport.price_per_share_rub)} ₽
                </span>
                {latestReport.currency === 'USD' && latestReport.price_per_share && (
                  <span className="stat-hint">({formatPerShare(latestReport.price_per_share)} USD)</span>
                )}
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
            {marketCapMln && (
              <div className="quick-stat">
                <span className="stat-label">Капитализация</span>
                <span className="stat-value">
                  <SharesCapHover explanation={latestCapExplanation}>
                    {fmtMln(marketCapMln)}
                  </SharesCapHover>
                </span>
                <span className="stat-date">на {latestReport.report_date}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Мультипликаторы — сразу под шапкой */}
      <MultipliersPanel company={company} reports={reports} />

      {/* Банковский блок: риск, качество портфеля, фондирование, капитал.
          Показывается только у банков — определяется типом отчёта, который
          бэкенд проставляет по сектору компании. */}
      {reports && reports.some((r) => r.report_type === 'bank') && (
        <BankMetricsPanel reports={reports} />
      )}

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

          {/* Описание бизнеса */}
          <section className="info-card company-description-card">
            <div className="company-description-header">
              <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none' }}>
                🏢 О компании
              </h2>
              <div className="company-description-actions">
                {company.business_description_source && !editingDescription && (
                  <span
                    className={`company-description-source company-description-source--${company.business_description_source}`}
                    title={
                      company.business_description_updated_at
                        ? `Обновлено: ${new Date(company.business_description_updated_at).toLocaleString('ru-RU')}`
                        : undefined
                    }
                  >
                    {company.business_description_source === 'manual' ? '✏️ Вручную' : '🤖 Из отчёта'}
                  </span>
                )}
                {!editingDescription ? (
                  <button
                    type="button"
                    className="company-description-btn company-description-btn--secondary"
                    onClick={() => {
                      setDescriptionDraft(company.business_description || '');
                      setEditingDescription(true);
                    }}
                  >
                    {company.business_description ? 'Редактировать' : 'Добавить'}
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      className="company-description-btn company-description-btn--secondary"
                      onClick={() => setEditingDescription(false)}
                      disabled={descriptionMutation.isPending}
                    >
                      Отмена
                    </button>
                    <button
                      type="button"
                      className="company-description-btn company-description-btn--primary"
                      disabled={descriptionMutation.isPending}
                      onClick={() => {
                        if (!company.id) return;
                        const trimmed = descriptionDraft.trim();
                        descriptionMutation.mutate({
                          id: company.id,
                          text: trimmed || null,
                        });
                      }}
                    >
                      {descriptionMutation.isPending ? 'Сохранение…' : 'Сохранить'}
                    </button>
                  </>
                )}
              </div>
            </div>
            {editingDescription ? (
              <textarea
                className="company-description-editor"
                value={descriptionDraft}
                onChange={(e) => setDescriptionDraft(e.target.value)}
                placeholder="Опишите деятельность компании: основные направления бизнеса, география, ключевые продукты…"
                rows={8}
              />
            ) : company.business_description ? (
              <div className="company-description-text">{company.business_description}</div>
            ) : (
              <div className="placeholder-content company-description-empty">
                <p>Описание пока не заполнено.</p>
                <p className="placeholder-hint">
                  Добавьте вручную или загрузите отчёт через AI-парсер — описание подтянется
                  из раздела примечаний «1. Информация о компании».
                </p>
              </div>
            )}
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
              <Link
                className="reports-card-header-title reports-card-header-title--nav-matrix"
                to={`/company/${companyId}/reports-matrix`}
                title="Открыть таблицу всех полей по периодам"
              >
                <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
                  📋 Финансовые отчеты
                  {reports && reports.length > 0 && (
                    <span className="reports-count-badge">{reports.length}</span>
                  )}
                  {unverifiedCount > 0 && (
                    <span
                      className="reports-unverified-pill"
                      title={`${unverifiedCount} отчётов требуют проверки аналитиком`}
                    >
                      🤖 {unverifiedCount} не проверено
                    </span>
                  )}
                </h2>
              </Link>
              <div className="reports-card-header-actions">
                <AddReportMenu
                  disabled={createReportMutation.isPending}
                  onManualAdd={() => navigate(`/company/${companyId}/reports-matrix`)}
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
                  <span
                    className={`reports-toggle-arrow-icon${reportsExpanded ? ' is-open' : ''}`}
                    aria-hidden
                  >
                    ▼
                  </span>
                </button>
              </div>
            </div>

            <div
              className={`reports-collapsible${reportsExpanded ? ' is-open' : ' is-closed'}`}
              aria-hidden={!reportsExpanded}
            >
              <div className="reports-collapsible-inner">
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
                          {firstReports.map(renderReportRow)}
                        </div>

                        {extraReports.length > 0 && (
                          <div
                            className={`reports-extra-collapsible${showAllReports ? ' is-open' : ' is-closed'}`}
                            aria-hidden={!showAllReports}
                          >
                            <div className="reports-extra-collapsible-inner reports-compact-list">
                              {extraReports.map(renderReportRow)}
                            </div>
                          </div>
                        )}

                        {filteredReports.length > 5 && (
                          <button
                            className="reports-show-more"
                            onClick={(e) => { e.stopPropagation(); setShowAllReports((v) => !v); }}
                            aria-expanded={showAllReports}
                          >
                            <span
                              className={`reports-show-more-icon${showAllReports ? ' is-open' : ''}`}
                              aria-hidden
                            >
                              ▼
                            </span>
                            {showAllReports
                              ? 'Свернуть'
                              : `Показать все (${filteredReports.length})`}
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
                      onClick={() => navigate(`/company/${companyId}/reports-matrix`)}
                    >
                      + Добавить отчет
                    </button>
                  </div>
                )}
              </div>
            </div>
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
      {selectedReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={() => setSelectedReport(null)}
          onEdit={() => navigate(`/company/${companyId}/reports-matrix`)}
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

    </div>
  );
};

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
