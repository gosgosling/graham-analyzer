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
import type { CompanyType, FinancialReport, FinancialReportCreate } from '../types';
import { detectSectorDisplayKind } from '../utils/sectorDisplayKind';
import { financialReportToCreatePayload, emptyFinancialReportPayload } from '../utils/financialReportPayload';
import { formatApiErrorMessage } from '../utils/apiErrors';
import { moexRubPriceToReportFieldValue } from '../utils/moexReportAssist';
import { computeFcf } from '../utils/fcf';
import { computeNetDebt } from '../utils/netDebt';
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
  /**
   * Каким типам компаний строка нужна. Отсутствие — всем.
   *
   * Раньше здесь были флаги bankOnly / lenderOnly / hybridOnly, и они
   * оказались слишком грубыми: биржа получила кредитный портфель и нормативы
   * Н1, которых у неё нет, и одновременно потеряла операционные расходы,
   * без которых не считается Cost-to-Income. Явный список читается прямо и
   * не ломается при добавлении шестого типа.
   */
  only?: CompanyType[];
  /** Кому строка не нужна, хотя нужна остальным. */
  hideFor?: CompanyType[];
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
  // У банка процентные расходы — себестоимость основной деятельности, а не
  // обслуживание долга, поэтому покрытие процентов ему не считается.
  { key: 'operating_profit', label: 'Операционная прибыль (EBIT)', kind: 'number', hint: 'млн', hideFor: ['lender', 'exchange']},
  { key: 'finance_costs', label: 'Финансовые расходы', kind: 'number', hint: 'млн, положит.', hideFor: ['lender', 'exchange']},
  { key: 'net_income_reported', label: 'Прибыль отчётная', kind: 'number', hint: 'млн' },
  { key: 'total_assets', label: 'Активы всего', kind: 'number', hint: 'млн' },
  { key: 'current_assets', label: 'Оборотные активы', kind: 'number', hint: 'млн', hideFor: ['lender', 'exchange']},
  { key: 'cash_and_equivalents', label: 'Наличность', kind: 'number', hint: 'ДС и эквиваленты, млн' },
  { key: 'debt', label: 'Долг', kind: 'number', hint: 'млн' },
  {
    key: 'net_debt_display',
    label: 'Чистый долг',
    kind: 'readonly',
    hint: 'Долг − наличность',
  },
  { key: 'total_liabilities', label: 'Обязательства всего', kind: 'number', hint: 'млн' },
  { key: 'current_liabilities', label: 'Краткоср. обязательства', kind: 'number', hint: 'млн', hideFor: ['lender', 'exchange']},
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
  { key: 'net_interest_income', label: 'NII (банк)', kind: 'number', hint: 'млн', only: ['lender']},
  { key: 'fee_commission_income', label: 'Комиссионные доходы', kind: 'number', hint: 'млн', only: ['lender', 'exchange']},
  { key: 'operating_expenses', label: 'Опер. расходы (до резервов)', kind: 'number', hint: 'млн', only: ['lender', 'exchange']},
  { key: 'provisions', label: 'Резервы под ОК', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'interest_income', label: 'Процентные доходы (валовые)', kind: 'number', hint: 'млн', only: ['lender', 'exchange']},
  { key: 'interest_expense', label: 'Процентные расходы', kind: 'number', hint: 'млн, положит.', only: ['lender', 'exchange']},
  { key: 'gross_loans', label: 'Кредиты до резерва', kind: 'number', hint: 'млн, примечание', only: ['lender', 'hybrid']},
  { key: 'loan_loss_allowance', label: 'Накопленный резерв (ECL)', kind: 'number', hint: 'млн, положит.', only: ['lender', 'hybrid']},
  { key: 'npl_loans', label: 'Обесцененные (Стадия 3 + POCI)', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'npl_overdue_90', label: '— в т.ч. просрочка 90+', kind: 'number', hint: 'млн, уже Стадии 3', only: ['lender', 'hybrid']},
  { key: 'customer_deposits', label: 'Средства клиентов', kind: 'number', hint: 'млн', only: ['lender', 'hybrid', 'exchange']},
  { key: 'loans_retail', label: '— кредиты физлицам', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'loans_corporate', label: '— кредиты юрлицам', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'deposits_retail', label: '— средства физлиц', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'deposits_corporate', label: '— средства юрлиц', kind: 'number', hint: 'млн', only: ['lender', 'hybrid']},
  { key: 'risk_weighted_assets', label: 'Активы под риском (RWA)', kind: 'number', hint: 'млн', only: ['lender']},
  { key: 'capital_adequacy_ratio', label: 'Достаточность общая Н1.0', kind: 'number', hint: '%', only: ['lender']},
  { key: 'capital_adequacy_core', label: 'Достаточность основного Н1.1', kind: 'number', hint: '%', only: ['lender']},
  { key: 'cf_customer_deposits', label: 'Δ средств клиентов (ОДДС)', kind: 'number', hint: 'млн, со знаком из отчёта', only: ['hybrid', 'exchange']},
  { key: 'cf_customer_loans', label: 'Δ кредитов клиентам (ОДДС)', kind: 'number', hint: 'млн, обычно отрицательное', only: ['hybrid', 'exchange']},
  { key: 'operating_cash_flow', label: 'Опер. денежный поток', kind: 'number', hint: 'млн', hideFor: ['lender']},
  { key: 'capex', label: 'CAPEX', kind: 'number', hint: 'млн, положит.', hideFor: ['lender']},
  { key: 'lease_principal', label: 'Тело аренды', kind: 'number', hint: 'млн, опц.', hideFor: ['lender']},
  { key: 'lease_interest', label: '% по аренде', kind: 'number', hint: 'млн, опц.', hideFor: ['lender']},
  { key: 'interest_paid', label: 'Проценты уплаченные', kind: 'number', hint: 'млн, financing', hideFor: ['lender']},
  { key: 'debt_principal', label: 'Тело долга (долг. ЦБ)', kind: 'number', hint: 'млн, не в FCF', hideFor: ['lender']},
  { key: 'depreciation_amortization', label: 'Амортизация и износ (D&A)', kind: 'number', hint: 'млн', hideFor: ['lender']},
  { key: 'fcf_display', label: 'FCF (расчётное)', kind: 'readonly', hint: 'OCF − CAPEX − аренда − %', hideFor: ['lender']},
  {
    key: 'adjusted_fcf_display',
    label: 'FCF (обыкнов.)',
    kind: 'readonly',
    hint: 'OCF − CAPEX − див. префов',
    hideFor: ['lender'],
  },
  { key: 'extraction_notes', label: 'Заметки / проверка', kind: 'textarea' },
];

/** Колонка-черновик нового отчёта в таблице (до POST не имеет id в БД). */
const MATRIX_DRAFT_ID = -1;

function initialDraftPayload(company_id: number): FinancialReportCreate {
  const y = new Date().getFullYear();
  // Годовой отчёт за текущий год — остальное берётся из общего конструктора.
  return emptyFinancialReportPayload(company_id, {
    fiscal_year: y,
    report_date: `${y}-12-31`,
  });
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

/** Тип периода → дата окончания и номер квартала. */
const PERIOD_PRESETS = [
  { value: 'annual', label: 'Год', monthDay: '12-31', quarter: null },
  { value: 'quarterly-1', label: '3 мес (Q1)', monthDay: '03-31', quarter: 1 },
  { value: 'semi_annual', label: '6 мес (пг)', monthDay: '06-30', quarter: null },
  { value: 'quarterly-3', label: '9 мес (Q3)', monthDay: '09-30', quarter: 3 },
] as const;

type PeriodPreset = (typeof PERIOD_PRESETS)[number]['value'];

/**
 * Пустой отчёт за выбранный период — «черновик» одним действием.
 *
 * Раньше на это уходило четыре шага: открыть окно, выставить год, выставить
 * дату окончания, сохранить. Год и дата однозначно связаны, поэтому дату
 * подставляем сами: 31.12 для года, 30.06 для полугодия и так далее.
 * Показатели остаются пустыми и заполняются прямо в таблице.
 */
function draftForPeriod(
  companyId: number,
  year: number,
  preset: PeriodPreset,
): FinancialReportCreate {
  const spec = PERIOD_PRESETS.find((p) => p.value === preset) ?? PERIOD_PRESETS[0];
  const periodType = spec.value.startsWith('quarterly')
    ? 'quarterly'
    : (spec.value as 'annual' | 'semi_annual');

  return emptyFinancialReportPayload(companyId, {
    period_type: periodType,
    fiscal_year: year,
    fiscal_quarter: spec.quarter,
    report_date: `${year}-${spec.monthDay}`,
    // Пустой отчёт — это заготовка, а не сверенные данные: пока в нём нет
    // цифр, он не должен считаться подтверждённым аналитиком.
    verified_by_analyst: false,
  });
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
      r.interest_paid,
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
      r.interest_paid,
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

  const [quickPeriod, setQuickPeriod] = useState<PeriodPreset>('annual');
  // Двадцать лет назад: Грэму нужна средняя прибыль за 7–10 лет, а самые
  // ранние отчёты в базе — 2006 года, и они тоже должны быть доступны.
  const quickYears = useMemo(() => {
    const now = new Date().getFullYear();
    return Array.from({ length: 21 }, (_, i) => now - i);
  }, []);
  const [creatingYear, setCreatingYear] = useState<number | null>(null);
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
  // Набор строк определяет тип компании, а не сектор: в «financial» у T-Invest
  // лежат и банки, и холдинги. У гибрида (Яндекс, МОЕХ) финансовый сегмент
  // существует внутри обычной компании — банковские поля ему тоже нужны,
  // но вместе с обычными: FCF и оборотные активы у ядра никуда не делись.
  const kind: CompanyType = (company?.company_type as CompanyType) ?? 'industrial';
  const isLender = kind === 'lender';
  // Финсегмент внутри обычной компании: у гибрида встроенный банк, у биржи —
  // средства участников торгов. Обоим нужна очистка потока от чужих денег.
  const hasClientMoney = kind === 'hybrid' || kind === 'exchange';

  const isPreferred = company?.is_preferred_share ?? false;

  const visibleRows = useMemo(
    () =>
      MATRIX_ROWS.filter((row) => {
        if (row.only && !row.only.includes(kind)) return false;
        if (row.hideFor?.includes(kind)) return false;
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
    [kind, isPreferred],
  ).map((row) => {
    // У биржи чужие деньги не выдаются в кредит, а размещаются в банках и
    // бумагах. Подпись «кредиты клиентам» здесь сбивает с толку: строка
    // отвечает на вопрос «куда эти деньги вложены», а не «кому одолжены».
    if (kind === 'exchange' && row.key === 'cf_customer_loans') {
      return {
        ...row,
        label: 'Δ размещения клиентских средств (ОДДС)',
        hint: 'млн, со знаком: рост размещений — отток',
      };
    }
    if (kind === 'exchange' && row.key === 'cf_customer_deposits') {
      return {
        ...row,
        label: 'Δ обязательств перед клиентами (ОДДС)',
        hint: 'млн, без зеркальных позиций клиринга',
      };
    }
    // У гибрида и биржи эти строки описывают не всю компанию, а её финансовую
    // часть — подпись должна это говорить, иначе «средства клиентов» рядом с
    // выручкой от такси читаются как одно целое.
    return hasClientMoney && row.only && !row.only.includes('industrial')
      ? { ...row, label: `${row.label} · финсегмент`, hint: `${row.hint ?? ''}`.trim() }
      : row;
  });

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

  /**
   * Пустой отчёт за выбранный год — одним действием.
   *
   * Раньше это были четыре шага через модальное окно; год и дата окончания
   * связаны однозначно, поэтому спрашиваем только год, остальное подставляем.
   */
  /** Периоды, которые уже есть: год+тип. Повтор упрётся в constraint БД. */
  const existingPeriodKeys = useMemo(() => {
    const set = new Set<string>();
    for (const r of reports ?? []) {
      const pt = String(r.period_type).toLowerCase();
      set.add(`${r.fiscal_year}:${pt}:${r.fiscal_quarter ?? ''}`);
    }
    return set;
  }, [reports]);

  const quickCreate = useCallback(
    async (year: number) => {
      setCreatingYear(year);
      try {
        await createFinancialReport(draftForPeriod(companyId, year, quickPeriod));
        await invalidateAll();
      } catch (e) {
        window.alert(formatApiErrorMessage(e, 'Не удалось создать отчёт'));
      } finally {
        setCreatingYear(null);
      }
    },
    [companyId, quickPeriod, invalidateAll],
  );

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
          <div className="crm-quick-add">
            <select
              className="crm-quick-period"
              value={quickPeriod}
              onChange={(e) => setQuickPeriod(e.target.value as PeriodPreset)}
              title="Тип периода для новых отчётов"
            >
              {PERIOD_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <select
              className="crm-quick-year"
              value=""
              disabled={creatingYear !== null}
              onChange={(e) => {
                const year = Number(e.target.value);
                if (year) void quickCreate(year);
                e.target.value = '';
              }}
            >
              <option value="">
                {creatingYear !== null ? `Создаю ${creatingYear}…` : '+ Отчёт за год…'}
              </option>
              {quickYears.map((y) => {
                const spec = PERIOD_PRESETS.find((p) => p.value === quickPeriod)!;
                const pt = spec.value.startsWith('quarterly') ? 'quarterly' : spec.value;
                const exists = existingPeriodKeys.has(`${y}:${pt}:${spec.quarter ?? ''}`);
                return (
                  <option key={y} value={y} disabled={exists}>
                    {y}{exists ? ' — уже есть' : ''}
                  </option>
                );
              })}
            </select>
          </div>
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
              <button
                type="button"
                className="crm-btn crm-btn-primary"
                onClick={startMatrixDraft}
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
