import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  getCompanyById,
  getCompanyReports,
  createFinancialReport,
  deleteFinancialReport,
  refreshCompanyMultipliers,
  verifyReport,
  updateCompanyPreferredShare,
  updateCompanyDescription,
} from '../services';
import { FinancialReport } from '../types';
import MultipliersPanel from '../components/MultipliersPanel';
import PriceChart from '../components/PriceChart';
import ValuationTab from '../components/ValuationTab';
import ConservativeCriteria from '../components/ConservativeCriteria';
import StatementsSheet from '../components/StatementsSheet';
import {
  AsideNotes,
  AsideToc,
  AsideValuation,
  marginLabel,
  rubLabel,
  useCompanyVerdict,
} from '../components/CompanyVerdict';
import BankMetricsPanel from '../components/BankMetricsPanel';
import HoldingPanel from '../components/HoldingPanel';
import VerificationBadge from '../components/VerificationBadge';
import ReportDetailModal from '../components/ReportDetailModal';
import AiParsePdfModal from '../components/AiParsePdfModal';
import { formatPerShare } from '../utils/perShare';
import { resolveSharesForMultipliers, explainSharesCapBasis } from '../utils/shareCounts';
import { fetchPriceHistory, type PriceHistoryOut } from '../services/prices.api';
import { fetchPassport, type PassportOut } from '../services/screen.api';
import { getCompanyCurrentMultipliers } from '../services';
import { useAdmin } from '../hooks/useAdmin';
import SharesCapHover from '../components/SharesCapHover';
import { getCompanyLogoCandidates } from '../utils/companyLogo';
import { isMisclassifiedAsPreferred } from '../utils/companyShareClass';
import './CompanyDetail.css';

type ReportPeriodFilter = 'all' | 'annual' | 'quarterly' | 'semi_annual';

/**
 * Разделы карточки. На большом экране они идут подряд, одной страницей: лист
 * читается сверху вниз — цена и оценка, ряд по годам, как посчитано, по каким
 * критериям, из каких отчётов. На телефоне длинную страницу листать неудобно,
 * и те же разделы становятся вкладками под шапкой.
 */
type CardSection = 'overview' | 'years' | 'valuation' | 'criteria' | 'statements' | 'reports' | 'about';

const SECTIONS: { key: Exclude<CardSection, 'overview'>; label: string; tab: string }[] = [
  { key: 'years', label: 'Показатели по годам', tab: 'По годам' },
  { key: 'valuation', label: 'Как получилась оценка', tab: 'Оценка' },
  { key: 'criteria', label: 'Консервативные критерии', tab: 'Критерии' },
  { key: 'statements', label: 'Отчётность', tab: 'Отчётность' },
  { key: 'reports', label: 'Файлы отчётов', tab: 'Файлы' },
  { key: 'about', label: 'О компании', tab: 'О компании' },
];

const STANDARD_LABEL: Record<string, string> = {
  IFRS: 'МСФО',
  RAS: 'РСБУ',
  US_GAAP: 'US GAAP',
  UK_GAAP: 'UK GAAP',
};

/** «2025 год», «1-е полугодие 2026» — для метки в шапке. */
function periodShort(report: FinancialReport): string {
  const pt = report.period_type.toLowerCase();
  if (pt === 'annual') return `${report.fiscal_year} год`;
  if (pt === 'semi_annual') return `1-е полугодие ${report.fiscal_year}`;
  return `${report.fiscal_quarter} кв. ${report.fiscal_year}`;
}

/** «за 2025 год», «за 1-е полугодие 2026», «за 3 кв. 2025». */
function periodPhrase(report: FinancialReport): string {
  const pt = report.period_type.toLowerCase();
  if (pt === 'annual') return `за ${report.fiscal_year} год`;
  if (pt === 'semi_annual') return `за 1-е полугодие ${report.fiscal_year}`;
  return `за ${report.fiscal_quarter} кв. ${report.fiscal_year}`;
}

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Миллионы рублей → «3,14 трлн ₽». */
function capLabel(mln: number): string {
  const abs = Math.abs(mln);
  if (abs >= 1_000_000) return `${ru(mln / 1_000_000, 2)} трлн ₽`;
  if (abs >= 1_000) return `${ru(mln / 1_000, 1)} млрд ₽`;
  return `${ru(mln, 0)} млн ₽`;
}

/** «2026-09-30» → «30.09.2026». */
const dotDate = (iso: string) => iso.split('-').reverse().join('.');

const CompanyDetail: React.FC = () => {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedReport, setSelectedReport] = useState<FinancialReport | null>(null);
  const [aiParseMode, setAiParseMode] = useState<'create' | 'compare' | 'batch' | null>(null);
  // Состояние раздела отчётов
  const [reportsExpanded, setReportsExpanded] = useState(false);
  const [reportPeriodFilter, setReportPeriodFilter] = useState<ReportPeriodFilter>('annual');
  const [reportStandardFilter, setReportStandardFilter] = useState<string>('all');
  const [showAllReports, setShowAllReports] = useState(false);
  const [mobileSection, setMobileSection] = useState<CardSection>('overview');
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

  // Цена в шапке — из той же истории, что и график, и с тем же ключом кэша:
  // раньше шапка брала цену из последнего отчёта, график — с биржи, а
  // мультипликаторы — из T-Invest, и на одной странице стояли три цены.
  const { data: priceHistory } = useQuery<PriceHistoryOut>({
    queryKey: ['price-history', Number(companyId)],
    queryFn: () => fetchPriceHistory(Number(companyId)),
    staleTime: 30 * 60 * 1000,
    enabled: !!companyId,
  });

  // Отраслевой профиль — по-русски и тот же, по которому считаются пороги.
  const { data: passport } = useQuery<PassportOut>({
    queryKey: ['screen-passport', Number(companyId)],
    queryFn: () => fetchPassport(Number(companyId)),
    staleTime: 5 * 60 * 1000,
    enabled: !!companyId,
  });

  // Всё, что карточка говорит о компании: фраза, запас, критерии.
  const verdict = useCompanyVerdict(Number(companyId));
  // Правка отчётов, описания и типа компании — только администратору.
  const { isAdmin } = useAdmin();

  // P/E, P/B и дивиденды в шапке — те же, что в листе по годам (строка LTM).
  const { data: currentMultipliers } = useQuery({
    queryKey: ['multipliers-current', Number(companyId)],
    queryFn: () => getCompanyCurrentMultipliers(Number(companyId)),
    staleTime: 5 * 60 * 1000,
    enabled: !!companyId,
    retry: false,
  });

  // «Обратить внимание» уходит под график, когда с ним боковая колонка
  // вылезает ниже графика больше чем на четверть: иначе рядом с графиком
  // остаётся пустое поле, а колонка тянется в одиночку.
  const [notesBelow, setNotesBelow] = useState(false);
  const overviewMainRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const notesRef = useRef<HTMLElement | null>(null);
  const notesHeightInAside = useRef(0);
  useEffect(() => {
    const main = overviewMainRef.current;
    const aside = asideRef.current;
    if (!main || !aside || typeof ResizeObserver === 'undefined') return undefined;
    const OVERFLOW = 1.25;
    const GAP = 16;
    const decide = () => {
      // В одну колонку (планшет, телефон) колонка и так стоит под графиком.
      if (window.innerWidth <= 1100) {
        setNotesBelow(false);
        return;
      }
      const chart = main.querySelector('.pc') as HTMLElement | null;
      const chartHeight = chart?.offsetHeight ?? 0;
      if (chartHeight === 0) return;
      const asideHeight = aside.offsetHeight;
      if (!notesBelow) {
        if (asideHeight > chartHeight * OVERFLOW) {
          notesHeightInAside.current = notesRef.current?.offsetHeight ?? 0;
          setNotesBelow(true);
        }
      } else if (asideHeight + GAP + notesHeightInAside.current <= chartHeight * OVERFLOW) {
        setNotesBelow(false);
      }
    };
    const observer = new ResizeObserver(decide);
    observer.observe(main);
    observer.observe(aside);
    decide();
    return () => observer.disconnect();
  }, [notesBelow, companyId, verdict.loading, company?.id]);

  // Сброс ошибочного «префы» (старая кнопка-индикатор: клик по «Обыкн.» включал префы у SIBN и т.п.)
  const misclassifiedFixRef = useRef<number | null>(null);
  useEffect(() => {
    misclassifiedFixRef.current = null;
  }, [companyId]);
  useEffect(() => {
    if (!company?.id || !isAdmin) return;
    if (!isMisclassifiedAsPreferred(company)) return;
    if (misclassifiedFixRef.current === company.id) return;
    misclassifiedFixRef.current = company.id;
    preferredShareMutation.mutate({ id: company.id, value: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- однократный сброс по company.id
  }, [company?.id, company?.is_preferred_share, company?.ticker, company?.name, isAdmin]);

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
            <span className="report-compact-standard">
              {STANDARD_LABEL[report.accounting_standard] ?? report.accounting_standard}
            </span>
            {report.currency !== 'RUB' && (
              <span className="report-compact-currency">{report.currency}</span>
            )}
            {report.dividends_paid && (
              <span className="report-compact-dividend">дивиденды</span>
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

  // Капитализация — по той же цене, что в шапке, и по акциям последнего
  // отчёта (в обращении, как во всех расчётах проекта).
  const latestReport = reports && reports.length > 0 ? reports[0] : null;
  const latestSharesForCap = latestReport ? resolveSharesForMultipliers(latestReport) : null;
  const latestCapExplanation = latestReport
    ? explainSharesCapBasis(latestReport, latestSharesForCap)
    : null;

  const points = priceHistory?.points ?? [];
  const lastPoint = points.length > 0 ? points[points.length - 1] : null;
  const prevPoint = points.length > 1 ? points[points.length - 2] : null;
  const price = lastPoint?.price ?? latestReport?.price_per_share_rub ?? null;
  const priceDate = lastPoint?.date ?? latestReport?.report_date ?? null;
  const dayChange = lastPoint && prevPoint && prevPoint.price > 0
    ? { abs: lastPoint.price - prevPoint.price, rel: lastPoint.price / prevPoint.price - 1 }
    : null;
  const marketCapMln = price && latestSharesForCap
    ? (price * latestSharesForCap) / 1_000_000
    : null;

  // Какие данные стоят за карточкой: вся история отчётов, а не один отчёт.
  const reportYears = (reports ?? []).map((r) => r.fiscal_year).filter(Boolean);
  const coverage = latestReport && reportYears.length > 0
    ? `отчёты ${Math.min(...reportYears)}–${Math.max(...reportYears)}, последний — `
      + `${STANDARD_LABEL[latestReport.accounting_standard] ?? latestReport.accounting_standard} `
      + periodPhrase(latestReport)
    : null;
  const coverageChip = latestReport
    ? `${STANDARD_LABEL[latestReport.accounting_standard] ?? latestReport.accounting_standard} · ${periodShort(latestReport)}`
    : null;

  // Разовые статьи последнего года: мультипликаторы считаются без них, оценка —
  // от прибыли как в отчёте. Расхождение больше десятой — повод сказать.
  const latestAnnual = (reports ?? []).find((r) => r.period_type.toLowerCase() === 'annual') ?? null;
  const oneOffs = latestAnnual
    && latestAnnual.net_income != null
    && latestAnnual.net_income_reported != null
    && Math.abs(latestAnnual.net_income - latestAnnual.net_income_reported)
      > 0.1 * Math.max(Math.abs(latestAnnual.net_income), Math.abs(latestAnnual.net_income_reported))
    ? { year: latestAnnual.fiscal_year, reported: latestAnnual.net_income_reported, normalized: latestAnnual.net_income }
    : null;

  const pe = currentMultipliers?.pe_ratio ?? null;
  const pb = currentMultipliers?.pb_ratio ?? null;
  const dy = currentMultipliers?.dividend_yield ?? null;
  const qualityTone = verdict.quality === 'strong' ? 'good' : verdict.quality === 'weak' ? 'bad' : 'neutral';
  const tabbed = (key: CardSection) => `cd-tabbed${mobileSection === key ? ' is-current' : ''}`;

  return (
    <div className="company-detail-container cd-page">
      <section className="cd-card cd-head">
        <div className="cd-head-top">
          <div className="cd-identity">
            <button onClick={() => navigate('/companies')} className="cd-back" type="button">
              ← Все компании
            </button>
            <div className="cd-name-row">
              {logoSrc && (
                <img
                  key={logoSrc}
                  src={logoSrc}
                  alt=""
                  className="cd-logo"
                  referrerPolicy="no-referrer"
                  loading="eager"
                  decoding="async"
                  onError={() => setLogoAttempt((a) => a + 1)}
                />
              )}
              <div className="cd-name-block">
                <h1 className="cd-name">{company.name}</h1>
                {/* Тикер, отрасль, свежий отчёт — строкой текста, без плашек. */}
                <div className="cd-meta">
                  <span className="cd-meta-ticker">{company.ticker}</span>
                  {passport?.profile?.label && <> · {passport.profile.label.toLowerCase()}</>}
                  {coverageChip && <> · <span title={coverage ?? undefined}>{coverageChip}</span></>}
                </div>
              </div>
            </div>
            {!verdict.loading && (
              <p className="cd-verdict">
                <strong>{verdict.headline}.</strong> {verdict.lede}
              </p>
            )}
          </div>

          {price !== null && (
            <div className="cd-quote">
              {/* Округление то же, что в оценке ниже: 5 350,5 в шапке и 5 351
                  под ней читались бы как две разные цены. */}
              <span className="cd-price">
                {Math.abs(price) >= 100 ? ru(price) : formatPerShare(price)} ₽
              </span>
              {dayChange && (
                <span className={`cd-change ${dayChange.abs >= 0 ? 'is-up' : 'is-down'}`}>
                  {dayChange.abs >= 0 ? '+' : '−'}{Math.abs(dayChange.abs) >= 100 ? ru(Math.abs(dayChange.abs)) : formatPerShare(Math.abs(dayChange.abs))} ₽
                  {' · '}
                  {dayChange.rel >= 0 ? '+' : '−'}{ru(Math.abs(dayChange.rel) * 100, 2)}% за день
                </span>
              )}
              <span className="cd-quote-meta">
                {marketCapMln !== null && (
                  <>
                    капитализация{' '}
                    <SharesCapHover explanation={latestCapExplanation}>
                      {capLabel(marketCapMln)}
                    </SharesCapHover>
                    {' · '}
                  </>
                )}
                {priceDate && <>цена на {dotDate(priceDate)}</>}
              </span>
            </div>
          )}
        </div>

        <div className={`cd-stats ${tabbed('overview')}`}>
          <a className="cd-stat" href="#valuation">
            <span className="cd-stat-label">Опорная</span>
            <span className="cd-stat-value cd-stat-value--ref">{verdict.available ? rubLabel(verdict.reference) : '—'}</span>
            <span className="cd-stat-sub">расчёт, не прогноз</span>
          </a>
          <a className="cd-stat" href="#valuation">
            <span className="cd-stat-label">Запас прочности</span>
            <span className={`cd-stat-value cd-tone--${verdict.marginTone}`}>{marginLabel(verdict.margin)}</span>
            <span className="cd-stat-sub">
              {verdict.margin === null ? 'нет оценки' : verdict.margin < 0 ? 'цена выше опорной' : 'цена ниже опорной'}
            </span>
          </a>
          <a className="cd-stat" href="#years" title="Цена / прибыль без разовых статей за последние 12 месяцев">
            <span className="cd-stat-label">P/E</span>
            <span className="cd-stat-value">{pe !== null ? ru(pe, 1) : '—'}</span>
            <span className="cd-stat-sub">без разовых</span>
          </a>
          <a className="cd-stat" href="#years">
            <span className="cd-stat-label">P/B</span>
            <span className="cd-stat-value">{pb !== null ? ru(pb, 2) : '—'}</span>
            <span className="cd-stat-sub">по балансу</span>
          </a>
          <a className="cd-stat" href="#years">
            <span className="cd-stat-label">Дивиденды</span>
            <span className="cd-stat-value">{dy !== null ? `${ru(dy, 1)}%` : '—'}</span>
            <span className="cd-stat-sub">за 12 мес.</span>
          </a>
          <a className="cd-stat" href="#criteria">
            <span className="cd-stat-label">Критерии</span>
            <span className={`cd-stat-value cd-tone--${qualityTone}`}>
              {verdict.total > 0 ? `${verdict.passed} из ${verdict.total}` : '—'}
            </span>
            <span className="cd-stat-sub">консервативные</span>
          </a>
        </div>
      </section>

      <nav className="cd-mobile-tabs" role="tablist" aria-label="Разделы карточки">
        {[{ key: 'overview' as CardSection, tab: 'Обзор' }, ...SECTIONS].map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={mobileSection === s.key}
            className={`cd-mobile-tab${mobileSection === s.key ? ' is-on' : ''}`}
            onClick={() => setMobileSection(s.key)}
          >
            {s.tab}
          </button>
        ))}
      </nav>

      <div className={`cd-overview ${tabbed('overview')}`}>
        <div className="cd-overview-main" ref={overviewMainRef}>
          {/* Нефть на графике — у энергетики: нефтяники, газовики, переработка. */}
          <PriceChart companyId={company.id!} oil={company.sector === 'energy'} />
          {notesBelow && <AsideNotes verdict={verdict} oneOffs={oneOffs} wide />}
        </div>
        <aside className="ca" ref={asideRef}>
          <AsideValuation verdict={verdict} />
          {!notesBelow && <AsideNotes ref={notesRef} verdict={verdict} oneOffs={oneOffs} />}
          <AsideToc
            sections={SECTIONS.map((s) => ({
              id: s.key,
              label: s.label,
              note: s.key === 'valuation' && verdict.available && verdict.reference !== null
                ? rubLabel(verdict.reference)
                : s.key === 'criteria' && verdict.total > 0
                  ? `${verdict.passed} из ${verdict.total}`
                  : s.key === 'reports' && reports
                    ? String(reports.length)
                    : undefined,
            }))}
          />
          {/* Сравнение с крупнейшими компаниями той же отрасли — гл. 18. */}
          <Link className="ca-compare" to={`/compare?with=${company.id}`}>Сравнить с отраслью →</Link>
        </aside>
      </div>

      <section id="years" className={`cd-card ${tabbed('years')}`}>
        <div className="cd-section-head">
          <h2 className="cd-section-title">Показатели по годам</h2>
          <span className="cd-section-sub">МСФО · годовые отчёты и последние 12 месяцев</span>
        </div>
        <MultipliersPanel company={company} reports={reports} />
      </section>

      {/* Холдинг: стоимость складывается из долей, а не из консолидированной
          отчётности — там результаты дочек, а не доля акционера. */}
      {company.company_type === 'holding' && (
        <div className={tabbed('years')}>
          <HoldingPanel company={company} reports={reports} />
        </div>
      )}

      {/* Блок финансового бизнеса: риск, качество портфеля, фондирование,
          капитал. У кредитора это вся компания (определяется типом отчёта),
          у гибрида — сегмент внутри обычной. */}
      {reports &&
        (reports.some((r) => r.report_type === 'bank') ||
          company.company_type === 'hybrid' ||
          company.company_type === 'exchange') && (
          <div className={tabbed('years')}>
            <BankMetricsPanel
              companyId={company.id!}
              reports={reports}
              companyType={company.company_type}
            />
          </div>
        )}

      <section id="valuation" className={`cd-card ${tabbed('valuation')}`}>
        <ValuationTab companyId={company.id!} />
      </section>

      <section id="criteria" className={`cd-card ${tabbed('criteria')}`}>
        <ConservativeCriteria companyId={company.id!} />
      </section>

      {/* Отчётность как в отчётах — без поправок проекта, по периодам. */}
      <section id="statements" className={`cd-card ${tabbed('statements')}`}>
        <div className="cd-section-head">
          <h2 className="cd-section-title">Отчётность</h2>
          <span className="cd-section-sub">как в отчётах компании, без поправок</span>
        </div>
        {reports ? <StatementsSheet reports={reports} company={company} /> : null}
      </section>

      {/* Отчёты: гостю — список и просмотр, администратору — ещё добавление,
          AI-парсер, проверка и удаление. */}
      <section id="reports" className={`cd-card cd-card--flush ${tabbed('reports')}`}>
          {/* Финансовые отчеты */}
          <section className="info-card">
            {/* Заголовок: сворачивание по клику на название; справа — как в списке компаний + стрелка */}
            <div className="reports-card-header">
              {isAdmin ? (
                <Link
                className="reports-card-header-title reports-card-header-title--nav-matrix"
                to={`/company/${companyId}/reports-matrix`}
                title="Открыть таблицу всех полей по периодам"
              >
                <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
                  Финансовые отчёты
                  {reports && reports.length > 0 && (
                    <span className="reports-count-badge">{reports.length}</span>
                  )}
                  {unverifiedCount > 0 && (
                    <span
                      className="reports-unverified-pill"
                      title={`${unverifiedCount} отчётов требуют проверки аналитиком`}
                    >
                      {unverifiedCount} не проверено
                    </span>
                  )}
                </h2>
                </Link>
              ) : (
                <div className="reports-card-header-title">
                <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
                  Финансовые отчёты
                  {reports && reports.length > 0 && (
                    <span className="reports-count-badge">{reports.length}</span>
                  )}
                  {unverifiedCount > 0 && (
                    <span
                      className="reports-unverified-pill"
                      title={`${unverifiedCount} отчётов требуют проверки аналитиком`}
                    >
                      {unverifiedCount} не проверено
                    </span>
                  )}
                </h2>
                </div>
              )}
              <div className="reports-card-header-actions">
                {isAdmin && <AddReportMenu
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
                />}
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

      </section>

      <section id="about" className={`cd-card cd-card--flush ${tabbed('about')}`}>
      <div className="company-content-grid">
        <div className="content-column">
          {/* Описание бизнеса */}
          <section className="info-card company-description-card">
            <div className="company-description-header">
              <h2 className="card-title" style={{ margin: 0, paddingBottom: 0, borderBottom: 'none' }}>
                О компании
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
                    {company.business_description_source === 'manual' ? 'вручную' : 'из отчёта'}
                  </span>
                )}
                {!isAdmin ? null : !editingDescription ? (
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
                <p>Описания пока нет.</p>
              </div>
            )}
          </section>

        </div>
        <div className="content-column">
          <section className="info-card">
            <h2 className="card-title">Биржевые данные</h2>
            <div className="info-grid">
              <div className="info-item">
                <span className="info-label">FIGI</span>
                <span className="info-value">{company.figi}</span>
              </div>
              <div className="info-item">
                <span className="info-label">ISIN</span>
                <span className="info-value">{company.isin || '—'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Тикер</span>
                <span className="info-value">{company.ticker}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Валюта</span>
                <span className="info-value">{company.currency?.toUpperCase()}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Размер лота</span>
                <span className="info-value">{company.lot}</span>
              </div>
              <div className="info-item">
                <span className="info-label">Торговля через API</span>
                <span className={`info-badge ${company.api_trade_available_flag ? 'active' : 'inactive'}`}>
                  {company.api_trade_available_flag ? 'доступна' : 'недоступна'}
                </span>
              </div>
            </div>
          </section>

        </div>
      </div>
      </section>

      {/* Модальное окно просмотра отчёта */}
      {selectedReport && (
        <ReportDetailModal
          report={selectedReport}
          onClose={() => setSelectedReport(null)}
          onEdit={isAdmin ? () => navigate(`/company/${companyId}/reports-matrix`) : undefined}
          onVerify={isAdmin ? (reportId) => verifyReportMutation.mutate(reportId) : undefined}
          verifyPending={verifyReportMutation.isPending}
          onDelete={!isAdmin ? undefined : (reportId) => {
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
      {isAdmin && aiParseMode && company && (
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
