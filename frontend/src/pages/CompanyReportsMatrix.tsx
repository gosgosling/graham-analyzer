import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  deleteFinancialReport,
  getCompanyById,
  getCompanyReports,
  refreshCompanyMultipliers,
  updateFinancialReport,
  verifyReport,
  createFinancialReport,
  getMoexPrice,
  getMoexShares,
} from '../services';
import type { FinancialReport, FinancialReportCreate } from '../types';
import { detectSectorDisplayKind } from '../utils/sectorDisplayKind';
import { financialReportToCreatePayload } from '../utils/financialReportPayload';
import { formatApiErrorMessage } from '../utils/apiErrors';
import { moexRubPriceToReportFieldValue } from '../utils/moexReportAssist';
import { computeFcf } from '../utils/fcf';
import { computeNetDebt } from '../utils/netDebt';
import ReportForm from '../components/ReportForm';
import AiParsePdfModal from '../components/AiParsePdfModal';
import './CompanyReportsMatrix.css';

type CellKind = 'text' | 'number' | 'int' | 'date' | 'bool' | 'select' | 'textarea' | 'readonly';

interface MatrixRowDef {
  key:
    | keyof FinancialReportCreate
    | 'fcf_display'
    | 'adjusted_net_display'
    | 'adjusted_fcf_display'
    | 'net_debt_display';
  label: string;
  hint?: string;
  kind: CellKind;
  bankOnly?: boolean;
  nonBankOnly?: boolean;
  selectOptions?: { value: string; label: string }[];
}

const PERIOD_OPTIONS = [
  { value: 'quarterly', label: 'Квартальный' },
  { value: 'semi_annual', label: 'Полугодовой' },
  { value: 'annual', label: 'Годовой' },
];

const STANDARD_OPTIONS = [
  { value: 'IFRS', label: 'IFRS' },
  { value: 'RAS', label: 'РСБУ' },
  { value: 'US_GAAP', label: 'US GAAP' },
  { value: 'UK_GAAP', label: 'UK GAAP' },
  { value: 'OTHER', label: 'Иное' },
];

const SOURCE_OPTIONS = [
  { value: 'manual', label: 'Вручную' },
  { value: 'company_website', label: 'Сайт компании' },
  { value: 'api', label: 'API' },
  { value: 'regulator', label: 'Регулятор' },
  { value: 'other', label: 'Прочее' },
];

const MATRIX_ROWS: MatrixRowDef[] = [
  { key: 'period_type', label: 'Тип периода', kind: 'select', selectOptions: PERIOD_OPTIONS },
  { key: 'fiscal_year', label: 'Финансовый год', kind: 'int' },
  { key: 'fiscal_quarter', label: 'Квартал (1–4)', kind: 'int', hint: 'Только для квартальных; для годового оставьте пусто' },
  { key: 'accounting_standard', label: 'Стандарт', kind: 'select', selectOptions: STANDARD_OPTIONS },
  { key: 'consolidated', label: 'Консолидация', kind: 'bool' },
  { key: 'source', label: 'Источник данных', kind: 'select', selectOptions: SOURCE_OPTIONS },
  { key: 'report_date', label: 'Дата окончания периода', kind: 'date' },
  { key: 'filing_date', label: 'Дата публикации', kind: 'date' },
  { key: 'currency', label: 'Валюта отчёта', kind: 'select', selectOptions: [{ value: 'RUB', label: 'RUB' }, { value: 'USD', label: 'USD' }] },
  { key: 'exchange_rate', label: 'Курс к RUB', kind: 'number', hint: 'Обязателен для USD' },
  { key: 'price_per_share', label: 'Цена акции (на конец периода)', kind: 'number' },
  { key: 'price_at_filing', label: 'Цена на дату публикации', kind: 'number' },
  { key: 'shares_issued', label: 'Размещено (общее)', kind: 'int' },
  { key: 'shares_outstanding', label: 'Акции в обращении', kind: 'int' },
  { key: 'shares_weighted_avg', label: 'Средневзвешенное', kind: 'int' },
  { key: 'treasury_shares', label: 'Казначейские', kind: 'int' },
  { key: 'revenue', label: 'Выручка / OpIncome', kind: 'number', hint: 'млн валюты отчёта' },
  { key: 'net_income', label: 'Чистая прибыль', kind: 'number', hint: 'млн' },
  {
    key: 'adjusted_net_display',
    label: 'Чистая прибыль (обыкнов.)',
    kind: 'readonly',
    hint: 'NI − див. по префам',
  },
  { key: 'net_income_reported', label: 'Прибыль отчётная', kind: 'number', hint: 'млн' },
  { key: 'total_assets', label: 'Активы всего', kind: 'number', hint: 'млн' },
  { key: 'current_assets', label: 'Оборотные активы', kind: 'number', hint: 'млн', bankOnly: false },
  { key: 'cash_and_equivalents', label: 'Наличность', kind: 'number', hint: 'ДС и эквиваленты, млн' },
  { key: 'debt', label: 'Долг', kind: 'number', hint: 'млн' },
  {
    key: 'net_debt_display',
    label: 'Чистый долг',
    kind: 'readonly',
    hint: 'Долг − наличность',
  },
  { key: 'total_liabilities', label: 'Обязательства всего', kind: 'number', hint: 'млн' },
  { key: 'current_liabilities', label: 'Краткоср. обязательства', kind: 'number', hint: 'млн', bankOnly: false },
  { key: 'equity', label: 'Капитал', kind: 'number', hint: 'млн' },
  { key: 'dividends_per_share', label: 'Дивиденд на акцию', kind: 'number', hint: 'полные единицы валюты' },
  { key: 'dividends_paid', label: 'Дивиденды выплачивались', kind: 'bool' },
  {
    key: 'has_preferred_shares',
    label: 'Есть привилегированные акции',
    kind: 'bool',
    hint: 'корректировка прибыли и FCF на обыкновенные',
  },
  {
    key: 'preferred_share_dividends',
    label: 'Дивиденды по префам',
    kind: 'number',
    hint: 'млн валюты отчёта',
  },
  { key: 'net_interest_income', label: 'NII (банк)', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'fee_commission_income', label: 'Комиссионные доходы', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'operating_expenses', label: 'Опер. расходы (до резервов)', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'provisions', label: 'Резервы под ОК', kind: 'number', hint: 'млн', bankOnly: true },
  { key: 'operating_cash_flow', label: 'Опер. денежный поток', kind: 'number', hint: 'млн', nonBankOnly: true },
  { key: 'capex', label: 'CAPEX', kind: 'number', hint: 'млн, положит.', nonBankOnly: true },
  { key: 'lease_principal', label: 'Тело аренды', kind: 'number', hint: 'млн, опц.', nonBankOnly: true },
  { key: 'lease_interest', label: '% по аренде', kind: 'number', hint: 'млн, опц.', nonBankOnly: true },
  { key: 'debt_principal', label: 'Тело долга (долг. ЦБ)', kind: 'number', hint: 'млн, опц.', nonBankOnly: true },
  { key: 'depreciation_amortization', label: 'Амортизация и износ (D&A)', kind: 'number', hint: 'млн', nonBankOnly: true },
  { key: 'fcf_display', label: 'FCF (расчётное)', kind: 'readonly', hint: 'OCF − CAPEX − аренда − долг', nonBankOnly: true },
  {
    key: 'adjusted_fcf_display',
    label: 'FCF (обыкнов.)',
    kind: 'readonly',
    hint: 'OCF − CAPEX − див. префов',
    nonBankOnly: true,
  },
  { key: 'extraction_notes', label: 'Заметки / проверка', kind: 'textarea' },
];

/** Колонка-черновик нового отчёта в таблице (до POST не имеет id в БД). */
const MATRIX_DRAFT_ID = -1;

function initialDraftPayload(company_id: number): FinancialReportCreate {
  const y = new Date().getFullYear();
  return {
    company_id,
    period_type: 'annual',
    fiscal_year: y,
    fiscal_quarter: null,
    accounting_standard: 'IFRS',
    consolidated: true,
    source: 'manual',
    report_date: `${y}-12-31`,
    filing_date: null,
    price_per_share: null,
    price_at_filing: null,
    shares_issued: null,
    shares_outstanding: null,
    shares_weighted_avg: null,
    treasury_shares: null,
    revenue: null,
    net_income: null,
    net_income_reported: null,
    total_assets: null,
    current_assets: null,
    cash_and_equivalents: null,
    debt: null,
    total_liabilities: null,
    current_liabilities: null,
    equity: null,
    dividends_per_share: null,
    dividends_paid: false,
    has_preferred_shares: false,
    preferred_share_dividends: null,
    net_interest_income: null,
    fee_commission_income: null,
    operating_expenses: null,
    provisions: null,
    operating_cash_flow: null,
    capex: null,
    lease_principal: null,
    lease_interest: null,
    debt_principal: null,
    depreciation_amortization: null,
    currency: 'RUB',
    exchange_rate: null,
    auto_extracted: false,
    verified_by_analyst: true,
    extraction_notes: null,
    extraction_model: null,
    source_pdf_path: null,
  };
}

function validateDraftForCreate(p: FinancialReportCreate): string | null {
  if (!p.report_date?.trim()) return 'Укажите дату окончания периода.';
  if (
    p.period_type === 'quarterly' &&
    (p.fiscal_quarter == null || p.fiscal_quarter < 1 || p.fiscal_quarter > 4)
  ) {
    return 'Для квартального отчёта укажите квартал 1–4.';
  }
  if (p.currency?.toUpperCase() !== 'RUB' && (!p.exchange_rate || p.exchange_rate <= 0)) {
    return `Для валюты ${p.currency} укажите положительный курс к RUB.`;
  }
  return null;
}

function extractMoexError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof d === 'string' ? d : 'Запрос к MOEX не удался';
}

function sliceIsoDate(v: unknown): string {
  if (v == null) return '';
  const s = typeof v === 'string' ? v : String(v);
  return s.slice(0, 10);
}

function periodShort(r: FinancialReport): string {
  const pt = String(r.period_type).toLowerCase();
  if (pt === 'annual') return `${r.fiscal_year} · год`;
  if (pt === 'semi_annual') return `${r.fiscal_year} · пг`;
  return `${r.fiscal_year} · Q${r.fiscal_quarter ?? '?'}`;
}

function parseNum(raw: string): number | null {
  const t = raw.replace(/\s/g, '').replace(',', '.').trim();
  if (t === '' || t === '-') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function parseIntMaybe(raw: string): number | null {
  const t = raw.replace(/\s/g, '').trim();
  if (t === '') return null;
  const n = parseInt(t, 10);
  return Number.isFinite(n) ? n : null;
}

function preferredDividendsMln(r: Pick<FinancialReport, 'has_preferred_shares' | 'preferred_share_dividends'>): number {
  if (!r.has_preferred_shares) return 0;
  return r.preferred_share_dividends ?? 0;
}

function getDisplayValue(r: FinancialReport, row: MatrixRowDef): string {
  if (row.key === 'fcf_display') {
    if (r.fcf != null && r.fcf !== undefined) return String(r.fcf);
    const f = computeFcf(
      r.operating_cash_flow,
      r.capex,
      r.lease_principal,
      r.lease_interest,
      r.debt_principal,
    );
    return f != null ? String(f) : '';
  }
  if (row.key === 'adjusted_net_display') {
    if (r.adjusted_net_income != null && r.adjusted_net_income !== undefined) return String(r.adjusted_net_income);
    if (r.net_income == null || r.net_income === undefined) return '';
    return String(r.net_income - preferredDividendsMln(r));
  }
  if (row.key === 'adjusted_fcf_display') {
    if (r.adjusted_fcf != null && r.adjusted_fcf !== undefined) return String(r.adjusted_fcf);
    const base = computeFcf(
      r.operating_cash_flow,
      r.capex,
      r.lease_principal,
      r.lease_interest,
      r.debt_principal,
    );
    if (base == null) return '';
    return String(base - preferredDividendsMln(r));
  }
  if (row.key === 'net_debt_display') {
    if (r.net_debt != null && r.net_debt !== undefined) return String(r.net_debt);
    const nd = computeNetDebt(r.debt, r.cash_and_equivalents);
    return nd != null ? String(nd) : '';
  }
  const k = row.key as keyof FinancialReport;
  const v = r[k];
  if (v === null || v === undefined) return '';
  if (row.kind === 'bool') return v ? '1' : '';
  return String(v);
}

function applyParsedToPayload(
  payload: FinancialReportCreate,
  row: MatrixRowDef,
  raw: string,
): void {
  const k = row.key;
  if (k === 'fcf_display' || k === 'adjusted_net_display' || k === 'adjusted_fcf_display' || k === 'net_debt_display') return;

  const widened = payload as unknown as Record<string, unknown>;

  if (row.kind === 'bool') {
    widened[k as string] = raw === 'true' || raw === '1';
    return;
  }
  if (row.kind === 'int') {
    const n = parseIntMaybe(raw);
    widened[k as string] = n;
    return;
  }
  if (row.kind === 'number') {
    widened[k as string] = parseNum(raw);
    return;
  }
  if (row.kind === 'date') {
    const s = raw.trim().slice(0, 10);
    if (k === 'filing_date') {
      payload.filing_date = s === '' ? null : s;
    } else if (k === 'report_date') {
      payload.report_date = s;
    }
    return;
  }
  if (row.kind === 'select' || row.kind === 'text' || row.kind === 'textarea') {
    if (k === 'period_type') {
      const pt = raw as FinancialReportCreate['period_type'];
      payload.period_type = pt;
      if (pt === 'annual') {
        payload.fiscal_quarter = null;
      }
      return;
    }
    widened[k as string] = raw;
  }
}

const CompanyReportsMatrix: React.FC = () => {
  const { companyId: companyIdParam } = useParams<{ companyId: string }>();
  const companyId = Number(companyIdParam);
  const queryClient = useQueryClient();

  const [showCreateForm, setShowCreateForm] = useState(false);
  /** Черновик нового отчёта — отображается первой колонкой матрицы без модалки. */
  const [draftPayload, setDraftPayload] = useState<FinancialReportCreate | null>(null);
  const draftRef = useRef<FinancialReportCreate | null>(null);
  const [aiModal, setAiModal] = useState<{
    mode: 'create' | 'compare' | 'batch';
    fiscalYear?: number;
    accountingStandard?: FinancialReportCreate['accounting_standard'];
  } | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  useEffect(() => {
    draftRef.current = draftPayload;
  }, [draftPayload]);

  const { data: company, error: companyError, isLoading: companyLoading } = useQuery({
    queryKey: ['company', companyIdParam],
    queryFn: () => getCompanyById(companyId),
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const { data: reports, isLoading: reportsLoading } = useQuery({
    queryKey: ['reports', companyIdParam],
    queryFn: () => getCompanyReports(companyId),
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const sectorKind = detectSectorDisplayKind(company?.sector);
  const isBank = sectorKind === 'bank';

  const isPreferred = company?.is_preferred_share ?? false;

  const visibleRows = useMemo(
    () =>
      MATRIX_ROWS.filter((row) => {
        if (row.bankOnly && !isBank) return false;
        if (row.nonBankOnly && isBank) return false;
        if (isBank && (row.key === 'current_assets' || row.key === 'current_liabilities')) return false;
        // На префовом тикере «обычные» корректировки на префы бессмысленны:
        // dividends_per_share уже хранит дивиденд по префам, разделения нет.
        if (isPreferred && (row.key === 'has_preferred_shares' || row.key === 'preferred_share_dividends')) {
          return false;
        }
        if (isPreferred && (row.key === 'adjusted_net_display' || row.key === 'adjusted_fcf_display')) {
          return false;
        }
        return true;
      }),
    [isBank, isPreferred],
  );

  const sortedReports = useMemo(() => {
    if (!reports?.length) return [];
    return [...reports].sort((a, b) => sliceIsoDate(b.report_date).localeCompare(sliceIsoDate(a.report_date)));
  }, [reports]);

  const draftPseudoReport = useMemo((): FinancialReport | null => {
    if (!draftPayload) return null;
    return { ...draftPayload, id: MATRIX_DRAFT_ID } as FinancialReport;
  }, [draftPayload]);

  const displayReports = useMemo(() => {
    if (!draftPseudoReport) return sortedReports;
    return [draftPseudoReport, ...sortedReports];
  }, [draftPseudoReport, sortedReports]);

  const startMatrixDraft = useCallback(() => {
    if (draftPayload !== null) {
      window.alert('Уже открыта колонка черновика — сохраните её (💾) или отмените (✕).');
      return;
    }
    setDraftPayload(initialDraftPayload(companyId));
  }, [companyId, draftPayload]);

  const cancelMatrixDraft = useCallback(() => {
    setDraftPayload(null);
  }, []);
  const invalidateAll = useCallback(async () => {
    queryClient.invalidateQueries({ queryKey: ['reports', companyIdParam] });
    queryClient.invalidateQueries({ queryKey: ['reports-counts-by-company'] });
    queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
    queryClient.invalidateQueries({ queryKey: ['multipliers', companyIdParam] });
    queryClient.invalidateQueries({ queryKey: ['company', companyIdParam] });
    await refreshCompanyMultipliers(companyId, true).catch(() => {});
  }, [companyId, companyIdParam, queryClient]);

  const applyMoexPriceFromPayload = useCallback(
    async (
      reportId: number,
      field: 'price_per_share' | 'price_at_filing',
      basePayload: FinancialReportCreate,
    ) => {
      const tk = company?.ticker;
      if (!tk) return;

      if (reportId === MATRIX_DRAFT_ID) {
        setSavingKey(`${MATRIX_DRAFT_ID}:moex`);
        try {
          const prev = draftRef.current;
          if (!prev) return;
          const dateIso = field === 'price_per_share' ? prev.report_date : prev.filing_date;
          if (!dateIso) {
            alert(
              field === 'price_per_share'
                ? 'Укажите дату окончания периода'
                : 'Укажите дату публикации',
            );
            return;
          }
          const rubResult = await getMoexPrice(tk, sliceIsoDate(dateIso));
          const converted = moexRubPriceToReportFieldValue(
            rubResult.price,
            prev.currency,
            prev.exchange_rate,
          );
          if (converted === null) {
            alert(
              `MOEX: ${rubResult.price.toLocaleString('ru-RU')} ₽ — укажите курс ${prev.currency}/RUB для конвертации.`,
            );
            return;
          }
          setDraftPayload({ ...prev, [field]: converted });
        } catch (e) {
          alert(extractMoexError(e));
        } finally {
          setSavingKey(null);
        }
        return;
      }

      const dateIso = field === 'price_per_share' ? basePayload.report_date : basePayload.filing_date;
      if (!dateIso) return;
      setSavingKey(`${reportId}:moex`);
      try {
        const rubResult = await getMoexPrice(tk, sliceIsoDate(dateIso));
        const converted = moexRubPriceToReportFieldValue(
          rubResult.price,
          basePayload.currency,
          basePayload.exchange_rate,
        );
        if (converted === null) {
          alert(
            `MOEX: ${rubResult.price.toLocaleString('ru-RU')} ₽ — укажите курс ${basePayload.currency}/RUB для конвертации.`,
          );
          return;
        }
        await updateFinancialReport(reportId, { ...basePayload, [field]: converted });
        await invalidateAll();
      } catch (e) {
        alert(extractMoexError(e));
      } finally {
        setSavingKey(null);
      }
    },
    [company?.ticker, invalidateAll],
  );

  const applyMoexSharesSave = useCallback(
    async (report: FinancialReport) => {
      const tk = company?.ticker;
      if (!tk) {
        alert('Нет тикера компании — загрузка MOEX недоступна.');
        return;
      }

      if (report.id === MATRIX_DRAFT_ID) {
        setSavingKey(`${MATRIX_DRAFT_ID}:moex`);
        try {
          const prev = draftRef.current;
          if (!prev) return;
          const result = await getMoexShares(tk);
          setDraftPayload({ ...prev, shares_issued: result.issuesize });
        } catch (e) {
          alert(extractMoexError(e));
        } finally {
          setSavingKey(null);
        }
        return;
      }

      const payload = financialReportToCreatePayload(report, companyId);
      setSavingKey(`${report.id}:moex`);
      try {
        const result = await getMoexShares(tk);
        await updateFinancialReport(report.id, {
          ...payload,
          shares_issued: result.issuesize,
        });
        await invalidateAll();
      } catch (e) {
        alert(extractMoexError(e));
      } finally {
        setSavingKey(null);
      }
    },
    [company?.ticker, companyId, invalidateAll],
  );

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FinancialReportCreate }) =>
      updateFinancialReport(id, data),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const verifyMutation = useMutation({
    mutationFn: (id: number) => verifyReport(id),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteFinancialReport(id),
    onSuccess: async () => {
      await invalidateAll();
    },
  });

  const submitDraft = useCallback(async () => {
    const payload = draftRef.current;
    if (!payload) return;
    const err = validateDraftForCreate(payload);
    if (err) {
      alert(err);
      return;
    }
    setSavingKey('draft:submit');
    try {
      await createFinancialReport(payload);
      setDraftPayload(null);
      await invalidateAll();
    } catch (e: unknown) {
      alert(formatApiErrorMessage(e, 'Не удалось создать отчёт'));
    } finally {
      setSavingKey(null);
    }
  }, [invalidateAll]);

  const handleDraftCellCommit = useCallback((row: MatrixRowDef, raw: string) => {
    setDraftPayload((prev) => {
      if (!prev) return prev;
      const pseudo = { ...prev, id: MATRIX_DRAFT_ID } as FinancialReport;
      const prevDisp = getDisplayValue(pseudo, row);
      if (prevDisp === raw) return prev;
      const next = { ...prev };
      try {
        applyParsedToPayload(next, row, raw);
      } catch {
        alert('Ошибка разбора значения');
        return prev;
      }
      if (next.period_type === 'quarterly' && (next.fiscal_quarter == null || next.fiscal_quarter < 1)) {
        alert('Для квартального отчёта укажите квартал 1–4.');
        return prev;
      }
      if (next.currency?.toUpperCase() !== 'RUB' && !next.exchange_rate) {
        alert(`Для валюты ${next.currency} укажите курс к RUB.`);
        return prev;
      }
      return next;
    });
  }, []);

  const handleCellCommit = useCallback(
    async (report: FinancialReport, row: MatrixRowDef, raw: string) => {
      if (row.kind === 'readonly') return;
      const prev = getDisplayValue(report, row);
      if (prev === raw) return;

      const payload = financialReportToCreatePayload(report, companyId);
      try {
        applyParsedToPayload(payload, row, raw);
        if (payload.period_type === 'quarterly' && (payload.fiscal_quarter == null || payload.fiscal_quarter < 1)) {
          alert('Для квартального отчёта укажите квартал 1–4.');
          return;
        }
        if (payload.currency?.toUpperCase() !== 'RUB' && !payload.exchange_rate) {
          alert(`Для валюты ${payload.currency} укажите курс к RUB.`);
          return;
        }
      } catch {
        alert('Ошибка разбора значения');
        return;
      }

      const sk = `${report.id}:${String(row.key)}`;
      setSavingKey(sk);
      try {
        await updateMutation.mutateAsync({ id: report.id, data: payload });
        if (row.key === 'report_date') {
          const wasEmpty = report.price_per_share == null || report.price_per_share === undefined;
          if (wasEmpty && payload.report_date) {
            void applyMoexPriceFromPayload(report.id, 'price_per_share', payload);
          }
        }
        if (row.key === 'filing_date') {
          const wasEmpty = report.price_at_filing == null || report.price_at_filing === undefined;
          if (wasEmpty && payload.filing_date) {
            void applyMoexPriceFromPayload(report.id, 'price_at_filing', payload);
          }
        }
      } catch (e: unknown) {
        const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        alert(typeof d === 'string' ? d : 'Не удалось сохранить ячейку');
      } finally {
        setSavingKey(null);
      }
    },
    [companyId, updateMutation, applyMoexPriceFromPayload],
  );

  const handleMatrixCellCommit = useCallback(
    (report: FinancialReport, row: MatrixRowDef, raw: string) => {
      if (report.id === MATRIX_DRAFT_ID) {
        handleDraftCellCommit(row, raw);
        return;
      }
      void handleCellCommit(report, row, raw);
    },
    [handleDraftCellCommit, handleCellCommit],
  );

  const handleDeleteReport = useCallback(
    (r: FinancialReport) => {
      if (r.id === MATRIX_DRAFT_ID) return;
      const label = `${r.fiscal_year} ${periodShort(r)}`;
      if (
        !window.confirm(
          `Удалить отчёт «${label}»?\n\nБудут удалены связанные записи report_based в истории мультипликаторов.`,
        )
      ) {
        return;
      }
      deleteMutation.mutate(r.id);
    },
    [deleteMutation],
  );

  if (!Number.isFinite(companyId) || companyId <= 0) {
    return (
      <div className="crm-page">
        <p className="crm-error">Некорректный идентификатор компании.</p>
      </div>
    );
  }

  if (companyLoading || companyError || !company) {
    return (
      <div className="crm-page">
        <div className="crm-loading">{companyLoading ? 'Загрузка…' : 'Компания не найдена'}</div>
      </div>
    );
  }

  const colCount = Math.max(1, displayReports.length);

  return (
    <div className="crm-page">
      <header className="crm-header">
        <div className="crm-header-main">
          <Link to={`/company/${companyId}`} className="crm-back">
            ← К компании
          </Link>
          <h1 className="crm-title">
            Отчёты — {company.name}{' '}
            <span className="crm-ticker">{company.ticker}</span>
          </h1>
          <p className="crm-sub">
            Измените ячейку и нажмите Enter или уберите фокус. Колонки — от новых отчётов к старым. У полей цен и
            акций — кнопка MOEX; если сохранили дату без цены, подстановка с биржи выполняется автоматически при
            наличии тикера.
          </p>
        </div>
        <div className="crm-toolbar">
          <button
            type="button"
            className="crm-btn crm-btn-primary"
            onClick={() => setShowCreateForm(true)}
          >
            + Отчёт вручную (окно)
          </button>
          <button
            type="button"
            className="crm-btn crm-btn-primary"
            onClick={() => {
              setShowCreateForm(false);
              startMatrixDraft();
            }}
          >
            + Отчёт в таблице
          </button>
          <button
            type="button"
            className="crm-btn"
            onClick={() => setAiModal({ mode: 'create', fiscalYear: new Date().getFullYear() - 1 })}
          >
            🤖 AI: создать
          </button>
          <button type="button" className="crm-btn" onClick={() => setAiModal({ mode: 'compare' })}>
            🔍 AI: сравнить
          </button>
          <button type="button" className="crm-btn" onClick={() => setAiModal({ mode: 'batch' })}>
            📂 AI: пакет
          </button>
        </div>
      </header>

      <div className="crm-table-scroll">
        {reportsLoading && !draftPseudoReport ? (
          <div className="crm-loading">Загрузка отчётов…</div>
        ) : sortedReports.length === 0 && !draftPseudoReport ? (
          <div className="crm-empty">
            <p>Отчётов пока нет.</p>
            <div className="crm-empty-actions">
              <button type="button" className="crm-btn crm-btn-primary" onClick={() => setShowCreateForm(true)}>
                Добавить (окно)
              </button>
              <button
                type="button"
                className="crm-btn crm-btn-primary"
                onClick={() => {
                  setShowCreateForm(false);
                  startMatrixDraft();
                }}
              >
                Добавить в таблице
              </button>
            </div>
          </div>
        ) : (
          <table className="crm-table">
            <thead>
              <tr>
                <th className="crm-th-label">Показатель</th>
                {displayReports.map((r) =>
                  r.id === MATRIX_DRAFT_ID ? (
                    <th key={r.id} className="crm-th-col crm-th-draft">
                      <div className="crm-col-head">
                        <div className="crm-col-period">Новый отчёт</div>
                        <div className="crm-col-meta">{periodShort(r)}</div>
                        <div className="crm-col-meta">
                          {r.accounting_standard}
                          {r.report_type ? ` · ${r.report_type}` : ''}
                        </div>
                        <div className="crm-col-date">{sliceIsoDate(r.report_date)}</div>
                        <div className="crm-col-badges">
                          <span className="crm-badge pending">черновик</span>
                        </div>
                        <div className="crm-col-actions">
                          <button
                            type="button"
                            className="crm-mini-btn"
                            disabled={savingKey === 'draft:submit'}
                            title="Сохранить новый отчёт"
                            onClick={() => void submitDraft()}
                          >
                            💾
                          </button>
                          <button
                            type="button"
                            className="crm-mini-btn"
                            disabled={savingKey === 'draft:submit'}
                            title="Отменить черновик"
                            onClick={cancelMatrixDraft}
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    </th>
                  ) : (
                    <th key={r.id} className="crm-th-col">
                      <div className="crm-col-head">
                        <div className="crm-col-period">{periodShort(r)}</div>
                        <div className="crm-col-meta">
                          {r.accounting_standard}
                          {r.report_type ? ` · ${r.report_type}` : ''}
                        </div>
                        <div className="crm-col-date">{sliceIsoDate(r.report_date)}</div>
                        <div className="crm-col-badges">
                          {r.auto_extracted && <span className="crm-badge ai">AI</span>}
                          {r.verified_by_analyst === false && (
                            <span className="crm-badge pending">не проверен</span>
                          )}
                        </div>
                        <div className="crm-col-actions">
                          {r.verified_by_analyst === false && (
                            <button
                              type="button"
                              className="crm-mini-btn"
                              disabled={verifyMutation.isPending}
                              title="Подтвердить проверку"
                              onClick={() => verifyMutation.mutate(r.id)}
                            >
                              ✓
                            </button>
                          )}
                          <button
                            type="button"
                            className="crm-mini-btn"
                            title="Загрузить PDF (AI), год подставлен"
                            onClick={() =>
                              setAiModal({
                                mode: 'create',
                                fiscalYear: r.fiscal_year,
                                accountingStandard: r.accounting_standard as FinancialReportCreate['accounting_standard'],
                              })
                            }
                          >
                            🤖
                          </button>
                          <button
                            type="button"
                            className="crm-mini-btn"
                            title="Сравнить с PDF (AI)"
                            onClick={() =>
                              setAiModal({
                                mode: 'compare',
                                fiscalYear: r.fiscal_year,
                                accountingStandard: r.accounting_standard as FinancialReportCreate['accounting_standard'],
                              })
                            }
                          >
                            🔍
                          </button>
                          <button
                            type="button"
                            className="crm-mini-btn danger"
                            disabled={deleteMutation.isPending}
                            title="Удалить отчёт"
                            onClick={() => handleDeleteReport(r)}
                          >
                            🗑
                          </button>
                        </div>
                      </div>
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              <tr className="crm-section-row">
                <td colSpan={colCount + 1}>Данные отчёта</td>
              </tr>
              {visibleRows.map((row) => (
                <tr key={String(row.key)}>
                  <td className="crm-row-label" title={row.hint}>
                    <span className="crm-row-label-text">{row.label}</span>
                  </td>
                  {displayReports.map((r) => {
                    const draftSubmitting = savingKey === 'draft:submit';
                    const sk = `${r.id}:${String(row.key)}`;
                    const busy = savingKey === sk || (r.id === MATRIX_DRAFT_ID && draftSubmitting);
                    const moexBusy = savingKey === `${r.id}:moex`;
                    return (
                      <td key={r.id} className="crm-cell">
                        <MatrixCellEditor
                          report={r}
                          row={row}
                          disabled={busy}
                          moexReportBusy={moexBusy}
                          ticker={company.ticker}
                          onCommit={(raw) => handleMatrixCellCommit(r, row, raw)}
                          onMoexPrice={(field) =>
                            void applyMoexPriceFromPayload(
                              r.id,
                              field,
                              financialReportToCreatePayload(r, companyId),
                            )
                          }
                          onMoexShares={() => void applyMoexSharesSave(r)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreateForm && (
        <ReportForm
          companyId={companyId}
          companyName={company.name}
          ticker={company.ticker}
          sector={company.sector}
          isPreferredShare={company.is_preferred_share}
          onSubmit={async (data) => {
            await createFinancialReport(data);
            setShowCreateForm(false);
            await invalidateAll();
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      )}

      {aiModal && (
        <AiParsePdfModal
          key={`${aiModal.mode}-${aiModal.fiscalYear ?? 'y'}-${aiModal.accountingStandard ?? 'std'}`}
          companyId={companyId}
          companyName={company.name}
          ticker={company.ticker}
          initialMode={aiModal.mode}
          initialFiscalYear={aiModal.fiscalYear}
          initialAccountingStandard={aiModal.accountingStandard}
          onClose={() => setAiModal(null)}
          onSuccess={async () => {
            await invalidateAll();
          }}
        />
      )}
    </div>
  );
};

interface MatrixCellEditorProps {
  report: FinancialReport;
  row: MatrixRowDef;
  disabled?: boolean;
  moexReportBusy?: boolean;
  ticker?: string | null;
  onCommit: (raw: string) => void;
  onMoexPrice?: (field: 'price_per_share' | 'price_at_filing') => void;
  onMoexShares?: () => void;
}

const MatrixCellEditor: React.FC<MatrixCellEditorProps> = ({
  report,
  row,
  disabled,
  moexReportBusy,
  ticker,
  onCommit,
  onMoexPrice,
  onMoexShares,
}) => {
  const initial = getDisplayValue(report, row);
  const [val, setVal] = useState(initial);

  React.useEffect(() => {
    setVal(getDisplayValue(report, row));
  }, [report, row]);

  const commit = () => {
    if (!disabled) onCommit(val);
  };

  if (row.kind === 'readonly') {
    return <span className="crm-readonly">{initial === '' ? '—' : initial}</span>;
  }

  if (row.kind === 'bool') {
    const checked = val === 'true' || val === '1';
    return (
      <input
        type="checkbox"
        className="crm-checkbox"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => {
          const next = e.target.checked ? 'true' : 'false';
          setVal(next);
          onCommit(next);
        }}
      />
    );
  }

  if (row.kind === 'select' && row.selectOptions) {
    const selVal =
      val ||
      (report[row.key as keyof FinancialReport] != null
        ? String(report[row.key as keyof FinancialReport])
        : '');
    return (
      <select
        className="crm-select"
        disabled={disabled}
        value={selVal}
        onChange={(e) => {
          const next = e.target.value;
          setVal(next);
          onCommit(next);
        }}
      >
        <option value="">—</option>
        {row.selectOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }

  if (row.kind === 'textarea') {
    return (
      <textarea
        className="crm-textarea"
        disabled={disabled}
        rows={2}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onBlur={commit}
      />
    );
  }

  const inputEl = (
    <input
      type={row.kind === 'date' ? 'date' : 'text'}
      className="crm-input"
      disabled={disabled}
      value={row.kind === 'date' ? val.slice(0, 10) : val}
      onChange={(e) => setVal(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );

  const moexBtnDisabled = !!disabled || !!moexReportBusy;

  if (ticker && row.key === 'price_per_share' && onMoexPrice) {
    return (
      <div className="crm-cell-moex-row">
        {inputEl}
        <button
          type="button"
          className="crm-moex-mini"
          title="Цена с MOEX на дату окончания периода"
          disabled={moexBtnDisabled}
          onClick={() => onMoexPrice('price_per_share')}
        >
          MOEX
        </button>
      </div>
    );
  }

  if (ticker && row.key === 'price_at_filing' && onMoexPrice) {
    return (
      <div className="crm-cell-moex-row">
        {inputEl}
        <button
          type="button"
          className="crm-moex-mini"
          title="Цена с MOEX на дату публикации"
          disabled={moexBtnDisabled}
          onClick={() => onMoexPrice('price_at_filing')}
        >
          MOEX
        </button>
      </div>
    );
  }

  if (ticker && row.key === 'shares_issued' && onMoexShares) {
    return (
      <div className="crm-cell-moex-row">
        {inputEl}
        <button
          type="button"
          className="crm-moex-mini"
          title="Акции из реестра MOEX"
          disabled={moexBtnDisabled}
          onClick={() => onMoexShares()}
        >
          MOEX
        </button>
      </div>
    );
  }

  return inputEl;
};

export default CompanyReportsMatrix;
