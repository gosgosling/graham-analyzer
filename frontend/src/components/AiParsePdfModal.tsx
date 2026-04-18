import React, { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  comparePdfReport,
  getCompanyReports,
  getLlmStatus,
  parsePdfReport,
  refreshCompanyMultipliers,
} from '../services';
import type {
  ComparePdfResponse,
  ParsePdfResponse,
  ReportFieldDiff,
} from '../types';
import './AiParsePdfModal.css';

type AccountingStandard = 'IFRS' | 'RAS' | 'US_GAAP' | 'UK_GAAP' | 'OTHER';
type Mode = 'create' | 'compare' | 'batch';

interface AiParsePdfModalProps {
  companyId: number;
  companyName: string;
  ticker: string;
  onClose: () => void;
  /** Успешно создан черновик — вернёт id и данные. */
  onSuccess?: (response: ParsePdfResponse) => void;
  /** По умолчанию 'create'. 'compare' — только сравнить, в БД ничего не писать. */
  initialMode?: Mode;
}

const currentYear = new Date().getFullYear();

/**
 * Модалка загрузки PDF отчёта для AI-парсинга.
 *
 * Потоки:
 *  1. Проверка статуса LLM (если не сконфигурирован — показываем инструкцию).
 *  2. Форма: год + стандарт + PDF.
 *  3. После отправки показываем прогресс ("LLM анализирует...").
 *  4. После ответа — summary с предупреждениями и кнопкой «Проверить отчёт».
 */
const AiParsePdfModal: React.FC<AiParsePdfModalProps> = ({
  companyId,
  companyName,
  ticker,
  onClose,
  onSuccess,
  initialMode = 'create',
}) => {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [file, setFile] = useState<File | null>(null);
  const [fiscalYear, setFiscalYear] = useState<number>(currentYear - 1);
  const [accountingStandard, setAccountingStandard] = useState<AccountingStandard>('IFRS');
  const [consolidated, setConsolidated] = useState(true);
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<ParsePdfResponse | null>(null);
  const [compareResult, setCompareResult] = useState<ComparePdfResponse | null>(null);

  const { data: llmStatus, isLoading: llmStatusLoading } = useQuery({
    queryKey: ['llm-status'],
    queryFn: getLlmStatus,
    staleTime: 60_000,
  });

  const parseMutation = useMutation({
    mutationFn: parsePdfReport,
    onSuccess: async (response) => {
      setResult(response);
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['reports', String(companyId)] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      await refreshCompanyMultipliers(companyId, true).catch(() => {});
      queryClient.invalidateQueries({ queryKey: ['multipliers', String(companyId)] });
      onSuccess?.(response);
    },
  });

  const compareMutation = useMutation({
    mutationFn: comparePdfReport,
    onSuccess: (response) => {
      setCompareResult(response);
    },
  });

  const activeMutation = mode === 'compare' ? compareMutation : parseMutation;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    if (mode === 'compare') {
      compareMutation.mutate({
        companyId,
        fiscalYear,
        file,
        periodType: 'annual',
        accountingStandard,
        consolidated,
      });
    } else {
      parseMutation.mutate({
        companyId,
        fiscalYear,
        file,
        periodType: 'annual',
        accountingStandard,
        consolidated,
        force,
      });
    }
  };

  const handleModeSwitch = (next: Mode) => {
    if (activeMutation.isPending) return;
    setMode(next);
    setResult(null);
    setCompareResult(null);
    parseMutation.reset();
    compareMutation.reset();
  };

  const errDetail = (activeMutation.error as any)?.response?.data?.detail;
  const errorMsg =
    typeof errDetail === 'string'
      ? errDetail
      : activeMutation.error
      ? (activeMutation.error as Error).message
      : null;

  return (
    <div className="ai-parse-overlay" onClick={onClose}>
      <div className="ai-parse-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ai-parse-header">
          <div>
            <h2>
              {mode === 'compare'
                ? '🔍 Сравнить AI-извлечение с отчётом в БД'
                : '🤖 Загрузить PDF отчёта для AI-парсинга'}
            </h2>
            <p className="ai-parse-subtitle">
              {companyName} · {ticker}
            </p>
          </div>
          <button onClick={onClose} className="ai-parse-close" aria-label="Закрыть">
            ✕
          </button>
        </div>

        <div className="ai-parse-mode-tabs">
          <button
            type="button"
            className={`ai-parse-tab ${mode === 'create' ? 'is-active' : ''}`}
            onClick={() => handleModeSwitch('create')}
            disabled={activeMutation.isPending}
            title="Извлечь данные и создать черновик отчёта в БД"
          >
            🤖 Извлечь и создать
          </button>
          <button
            type="button"
            className={`ai-parse-tab ${mode === 'compare' ? 'is-active' : ''}`}
            onClick={() => handleModeSwitch('compare')}
            disabled={activeMutation.isPending}
            title="Прогнать через модель и сравнить с уже существующим отчётом. В БД ничего не пишется."
          >
            🔍 Только сравнить
          </button>
          <button
            type="button"
            className={`ai-parse-tab ${mode === 'batch' ? 'is-active' : ''}`}
            onClick={() => handleModeSwitch('batch')}
            disabled={activeMutation.isPending}
            title="Указать папку с PDF отчётами и пакетно их обработать. Годы, которые уже есть в БД, пропускаются."
          >
            📁 Папка (пакет)
          </button>
        </div>

        {llmStatusLoading ? (
          <div className="ai-parse-loading">Проверяем настройку AI-сервиса…</div>
        ) : !llmStatus?.configured ? (
          <div className="ai-parse-body">
            <div className="ai-parse-error-block">
              <h3>⚠️ AI-парсер не настроен</h3>
              <p>
                Чтобы пользоваться автоматическим извлечением из PDF, задайте
                в корневом <code>.env</code> переменные <code>LLM_API_KEY</code> и{' '}
                <code>LLM_MODEL</code> и перезапустите backend.
              </p>
              <p>
                Текущая настройка: провайдер <b>{llmStatus?.provider}</b>, модель{' '}
                <b>{llmStatus?.model || '—'}</b>.
              </p>
            </div>
            <div className="ai-parse-footer">
              <button onClick={onClose} className="ai-parse-btn-secondary">
                Закрыть
              </button>
            </div>
          </div>
        ) : mode === 'batch' ? (
          <BatchParsePanel
            companyId={companyId}
            onClose={onClose}
            llmModel={`${llmStatus.provider}:${llmStatus.model}`}
          />
        ) : result ? (
          <ParseResultSummary
            response={result}
            onClose={onClose}
            onParseAnother={() => {
              setResult(null);
              setFile(null);
              parseMutation.reset();
            }}
          />
        ) : compareResult ? (
          <CompareResultSummary
            response={compareResult}
            onClose={onClose}
            onCompareAnother={() => {
              setCompareResult(null);
              setFile(null);
              compareMutation.reset();
            }}
          />
        ) : (
          <form onSubmit={handleSubmit} className="ai-parse-body">
            <div className="ai-parse-status-line">
              <span className="ai-parse-status-label">Модель:</span>
              <code className="ai-parse-model">
                {llmStatus.provider}:{llmStatus.model}
              </code>
            </div>

            <div className="ai-parse-field">
              <label htmlFor="ai-pdf-file">
                PDF-файл отчёта <span className="ai-parse-req">*</span>
              </label>
              <input
                id="ai-pdf-file"
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileChange}
                disabled={parseMutation.isPending}
                required
              />
              {file && (
                <div className="ai-parse-file-info">
                  {file.name} · {(file.size / 1024 / 1024).toFixed(2)} МБ
                </div>
              )}
            </div>

            <div className="ai-parse-grid">
              <div className="ai-parse-field">
                <label htmlFor="ai-fiscal-year">Отчётный год</label>
                <input
                  id="ai-fiscal-year"
                  type="number"
                  value={fiscalYear}
                  onChange={(e) => setFiscalYear(Number(e.target.value))}
                  min={1990}
                  max={currentYear + 1}
                  disabled={parseMutation.isPending}
                  required
                />
              </div>
              <div className="ai-parse-field">
                <label htmlFor="ai-standard">Стандарт учёта</label>
                <select
                  id="ai-standard"
                  value={accountingStandard}
                  onChange={(e) => setAccountingStandard(e.target.value as AccountingStandard)}
                  disabled={parseMutation.isPending}
                >
                  <option value="IFRS">МСФО (IFRS)</option>
                  <option value="RAS">РСБУ (RAS)</option>
                  <option value="US_GAAP">US GAAP</option>
                  <option value="UK_GAAP">UK GAAP</option>
                  <option value="OTHER">Другой</option>
                </select>
              </div>
            </div>

            <div className="ai-parse-checkboxes">
              <label className="ai-parse-checkbox">
                <input
                  type="checkbox"
                  checked={consolidated}
                  onChange={(e) => setConsolidated(e.target.checked)}
                  disabled={activeMutation.isPending}
                />
                Консолидированный отчёт
              </label>
              {mode === 'create' && (
                <label
                  className="ai-parse-checkbox"
                  title="Пересоздать, если отчёт за этот год уже есть"
                >
                  <input
                    type="checkbox"
                    checked={force}
                    onChange={(e) => setForce(e.target.checked)}
                    disabled={activeMutation.isPending}
                  />
                  Перезаписать, если уже существует
                </label>
              )}
            </div>

            {mode === 'compare' && (
              <div className="ai-parse-hint">
                В режиме сравнения в БД ничего не пишется — вы получите только таблицу
                расхождений между извлечением модели и уже имеющимся отчётом.
              </div>
            )}

            {activeMutation.isPending && (
              <div className="ai-parse-progress">
                <span className="ai-parse-spinner" />
                LLM анализирует PDF… Это может занять 15-60 секунд.
              </div>
            )}

            {errorMsg && !activeMutation.isPending && (
              <div className="ai-parse-error">⚠ {errorMsg}</div>
            )}

            <div className="ai-parse-footer">
              <button
                type="button"
                onClick={onClose}
                className="ai-parse-btn-secondary"
                disabled={activeMutation.isPending}
              >
                Отмена
              </button>
              <button
                type="submit"
                className="ai-parse-btn-primary"
                disabled={!file || activeMutation.isPending}
              >
                {activeMutation.isPending
                  ? 'Анализируем…'
                  : mode === 'compare'
                  ? '🔍 Сравнить'
                  : '🤖 Извлечь данные'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

interface ParseResultSummaryProps {
  response: ParsePdfResponse;
  onClose: () => void;
  onParseAnother: () => void;
}

const ParseResultSummary: React.FC<ParseResultSummaryProps> = ({
  response,
  onClose,
  onParseAnother,
}) => {
  const r = response.report;
  const warnings = response.warnings || [];

  const fmtMln = (n: number | null | undefined): string => {
    if (n === null || n === undefined) return '—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ' трлн';
    if (abs >= 1_000) return (n / 1_000).toFixed(2) + ' млрд';
    return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн';
  };

  return (
    <div className="ai-parse-body">
      <div className="ai-parse-success-block">
        <h3>✅ Черновик отчёта создан (id={r.id})</h3>
        <p className="ai-parse-success-hint">
          Отчёт помечен как <b>AI-черновик</b> и <b>не проверен</b>. Откройте его,
          сверьте значения с PDF и нажмите «Подтвердить».
        </p>
      </div>

      <div className="ai-parse-grid ai-parse-kv">
        <div>
          <span className="ai-parse-k">Период</span>
          <span className="ai-parse-v">
            {r.fiscal_year} · {r.accounting_standard}
          </span>
        </div>
        <div>
          <span className="ai-parse-k">Валюта</span>
          <span className="ai-parse-v">{r.currency}</span>
        </div>
        <div>
          <span className="ai-parse-k">Выручка</span>
          <span className="ai-parse-v">{fmtMln(r.revenue)}</span>
        </div>
        <div>
          <span className="ai-parse-k">Чистая прибыль</span>
          <span className="ai-parse-v">{fmtMln(r.net_income)}</span>
        </div>
        <div>
          <span className="ai-parse-k">Активы</span>
          <span className="ai-parse-v">{fmtMln(r.total_assets)}</span>
        </div>
        <div>
          <span className="ai-parse-k">Капитал</span>
          <span className="ai-parse-v">{fmtMln(r.equity)}</span>
        </div>
        <div>
          <span className="ai-parse-k">Обязательства</span>
          <span className="ai-parse-v">{fmtMln(r.total_liabilities)}</span>
        </div>
        <div>
          <span className="ai-parse-k">Страниц в PDF</span>
          <span className="ai-parse-v">
            {response.selected_pages} из {response.total_pages} (использовано)
          </span>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="ai-parse-warnings">
          <h4>⚠ Требуют проверки:</h4>
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {r.extraction_notes && (
        <details className="ai-parse-notes">
          <summary>Заметки модели</summary>
          <pre>{r.extraction_notes}</pre>
        </details>
      )}

      <div className="ai-parse-footer">
        <button onClick={onParseAnother} className="ai-parse-btn-secondary">
          Загрузить ещё PDF
        </button>
        <button onClick={onClose} className="ai-parse-btn-primary">
          Готово
        </button>
      </div>
    </div>
  );
};

// ─── Режим сравнения: таблица diff ─────────────────────────────────────────

interface CompareResultSummaryProps {
  response: ComparePdfResponse;
  onClose: () => void;
  onCompareAnother: () => void;
}

const _STATUS_META: Record<
  ReportFieldDiff['status'],
  { label: string; cls: string; icon: string }
> = {
  match: { label: 'совпало', cls: 'is-match', icon: '✓' },
  close: { label: '≈ близко', cls: 'is-close', icon: '≈' },
  mismatch: { label: 'расхождение', cls: 'is-mismatch', icon: '✗' },
  missing_ai: { label: 'модель не нашла', cls: 'is-missing-ai', icon: '·AI' },
  missing_existing: { label: 'нет в БД', cls: 'is-missing-existing', icon: '·DB' },
  both_missing: { label: 'оба пусто', cls: 'is-both-missing', icon: '—' },
};

function _formatDiffValue(
  value: ReportFieldDiff['existing_value'],
  kind: ReportFieldDiff['kind']
): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  const num = typeof value === 'number' ? value : Number(value);
  const isNum = Number.isFinite(num);

  if (kind === 'money_mln' && isNum) {
    const abs = Math.abs(num);
    if (abs >= 1_000_000) return (num / 1_000_000).toFixed(2) + ' трлн';
    if (abs >= 1_000) return (num / 1_000).toFixed(2) + ' млрд';
    return num.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн';
  }
  if (kind === 'int' && isNum) {
    return num.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
  }
  if (kind === 'float' && isNum) {
    return num.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  }
  return String(value);
}

const CompareResultSummary: React.FC<CompareResultSummaryProps> = ({
  response,
  onClose,
  onCompareAnother,
}) => {
  const s = response.summary;
  const totalBad = s.mismatched + s.missing_in_ai;
  const overallClass =
    totalBad === 0 && s.matched + s.close === s.total_fields
      ? 'is-ok'
      : totalBad > 2
      ? 'is-bad'
      : 'is-warn';

  return (
    <div className="ai-parse-body">
      <div className={`ai-compare-banner ${overallClass}`}>
        <h3>
          {overallClass === 'is-ok'
            ? '✅ Модель совпала с проверенным отчётом'
            : overallClass === 'is-warn'
            ? '⚠ Есть расхождения — проверьте ниже'
            : '❌ Значимые расхождения — модель ошиблась'}
        </h3>
        <p className="ai-compare-banner-sub">
          Сравнение с отчётом <b>#{response.existing_report_id}</b>
          {response.existing_report_verified ? ' (проверен аналитиком)' : ' (ещё не проверен)'} ·
          модель <code>{response.extraction_model}</code> ·
          страниц {response.selected_pages}/{response.total_pages}
        </p>
      </div>

      <div className="ai-compare-summary">
        <span className="ai-compare-stat is-match">
          ✓ совпало: <b>{s.matched}</b>
        </span>
        <span className="ai-compare-stat is-close">
          ≈ близко: <b>{s.close}</b>
        </span>
        <span className="ai-compare-stat is-mismatch">
          ✗ расхождение: <b>{s.mismatched}</b>
        </span>
        <span className="ai-compare-stat is-missing-ai">
          ·AI не нашла: <b>{s.missing_in_ai}</b>
        </span>
        <span className="ai-compare-stat is-missing-existing">
          ·DB не заполн.: <b>{s.missing_in_existing}</b>
        </span>
        {s.max_pct_diff !== null && (
          <span className="ai-compare-stat">
            max Δ: <b>{s.max_pct_diff >= 0 ? '+' : ''}{s.max_pct_diff.toFixed(2)}%</b>
          </span>
        )}
      </div>

      <div className="ai-compare-table-wrap">
        <table className="ai-compare-table">
          <thead>
            <tr>
              <th>Поле</th>
              <th>В БД (аналитик)</th>
              <th>Извлекла модель</th>
              <th>Δ %</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {response.diffs.map((d) => {
              const meta = _STATUS_META[d.status];
              return (
                <tr key={d.field} className={`ai-compare-row ${meta.cls}`}>
                  <td className="ai-compare-field">
                    {d.label}
                    {d.note && (
                      <span className="ai-compare-note" title={d.note}> · {d.note}</span>
                    )}
                  </td>
                  <td>{_formatDiffValue(d.existing_value, d.kind)}</td>
                  <td>{_formatDiffValue(d.extracted_value, d.kind)}</td>
                  <td className="ai-compare-pct">
                    {d.pct_diff === null
                      ? ''
                      : `${d.pct_diff >= 0 ? '+' : ''}${d.pct_diff.toFixed(2)}%`}
                  </td>
                  <td>
                    <span className={`ai-compare-badge ${meta.cls}`}>
                      {meta.icon} {meta.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="ai-compare-footnote">
        Существующий отчёт <b>не изменён</b>. В режиме сравнения мы ничего не пишем в БД —
        это «песочница» для оценки качества модели.
      </p>

      <div className="ai-parse-footer">
        <button onClick={onCompareAnother} className="ai-parse-btn-secondary">
          Сравнить ещё PDF
        </button>
        <button onClick={onClose} className="ai-parse-btn-primary">
          Готово
        </button>
      </div>
    </div>
  );
};

// ─── Batch-режим: папка с PDF ──────────────────────────────────────────────

type BatchItemStatus =
  | 'pending'            // в очереди — год не занят в БД
  | 'will_skip_existing' // уже есть в БД, пропустим (если не стоит force)
  | 'no_year'            // год не определился — нужен ручной ввод
  | 'running'            // сейчас обрабатывается LLM
  | 'done'               // успешно создан черновик
  | 'skipped'            // пропущен (дубль, уже был в БД)
  | 'error'              // ошибка
  | 'cancelled';         // отменён пользователем

interface BatchItem {
  key: string;
  file: File;
  fiscalYear: number | null;
  status: BatchItemStatus;
  message?: string;
  reportId?: number;
}

const CURRENT_YEAR = new Date().getFullYear();

/** Ищем в имени файла 4-значный год вида 19xx/20xx. Если несколько — берём первый правдоподобный. */
function extractYearFromFileName(name: string): number | null {
  const re = /(19|20)\d{2}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(name)) !== null) {
    const y = parseInt(match[0], 10);
    if (y >= 1990 && y <= CURRENT_YEAR + 1) return y;
  }
  return null;
}

interface BatchParsePanelProps {
  companyId: number;
  onClose: () => void;
  llmModel: string;
}

const BatchParsePanel: React.FC<BatchParsePanelProps> = ({
  companyId,
  onClose,
  llmModel,
}) => {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<BatchItem[]>([]);
  const [accountingStandard, setAccountingStandard] = useState<AccountingStandard>('IFRS');
  const [consolidated, setConsolidated] = useState(true);
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [running, setRunning] = useState(false);
  const cancelRef = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Существующие годы у компании — чтобы заранее отметить дубли.
  const { data: existingReports } = useQuery({
    queryKey: ['reports', String(companyId)],
    queryFn: () => getCompanyReports(companyId),
    staleTime: 30_000,
  });

  const existingYears = useMemo(() => {
    const set = new Set<number>();
    (existingReports ?? []).forEach((r) => {
      if (r.period_type === 'annual' && typeof r.fiscal_year === 'number') {
        set.add(r.fiscal_year);
      }
    });
    return set;
  }, [existingReports]);

  /** Определить начальный статус файла исходя из года и существующих отчётов. */
  const statusForYear = (year: number | null): BatchItemStatus => {
    if (year === null) return 'no_year';
    if (existingYears.has(year)) return 'will_skip_existing';
    return 'pending';
  };

  const handleFilesPicked = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const arr = Array.from(files).filter((f) => f.name.toLowerCase().endsWith('.pdf'));
    const next: BatchItem[] = arr.map((f, idx) => {
      const year = extractYearFromFileName(f.name);
      return {
        key: `${f.name}_${f.size}_${idx}_${Date.now()}`,
        file: f,
        fiscalYear: year,
        status: statusForYear(year),
      };
    });
    // Сортируем по году (сначала старые → новые), файлы без года — в хвост.
    next.sort((a, b) => {
      if (a.fiscalYear === null && b.fiscalYear === null) return 0;
      if (a.fiscalYear === null) return 1;
      if (b.fiscalYear === null) return -1;
      return a.fiscalYear - b.fiscalYear;
    });
    setItems(next);
  };

  /** Пересчитать статусы pending/will_skip_existing при смене чекбокса «перезаписать». */
  const recalcPendingAfterOverwriteToggle = (checked: boolean) => {
    setItems((prev) =>
      prev.map((it) => {
        if (it.status === 'will_skip_existing' && checked) return { ...it, status: 'pending' };
        if (it.status === 'pending' && !checked && it.fiscalYear !== null && existingYears.has(it.fiscalYear)) {
          return { ...it, status: 'will_skip_existing' };
        }
        return it;
      }),
    );
  };

  const updateItemYear = (key: string, year: number | null) => {
    setItems((prev) =>
      prev.map((it) =>
        it.key === key
          ? {
              ...it,
              fiscalYear: year,
              status:
                year === null
                  ? 'no_year'
                  : existingYears.has(year) && !overwriteExisting
                  ? 'will_skip_existing'
                  : 'pending',
              message: undefined,
            }
          : it,
      ),
    );
  };

  const removeItem = (key: string) => {
    setItems((prev) => prev.filter((it) => it.key !== key));
  };

  const resetAll = () => {
    if (running) return;
    setItems([]);
    if (inputRef.current) inputRef.current.value = '';
  };

  /** Последовательно обрабатываем все элементы, которые нужно отправить. */
  const runBatch = async () => {
    if (running) return;
    if (items.length === 0) return;
    // Перед запуском — все 'pending' реально отправляем; 'will_skip_existing'
    // остаются как skipped; 'no_year' / 'error' оставляем как есть.
    cancelRef.current = false;
    setRunning(true);

    // Материализуем текущий порядок работы.
    const snapshot = items.map((it) => it.key);

    let anySucceeded = false;

    for (const key of snapshot) {
      if (cancelRef.current) {
        setItems((prev) =>
          prev.map((it) =>
            it.status === 'pending' ? { ...it, status: 'cancelled' } : it,
          ),
        );
        break;
      }

      // Найдём актуальное состояние — пользователь мог за это время
      // переключить год или удалить элемент.
      const currentItem = await new Promise<BatchItem | undefined>((resolve) => {
        setItems((prev) => {
          resolve(prev.find((it) => it.key === key));
          return prev;
        });
      });
      if (!currentItem) continue;

      // Пропуски заранее.
      if (currentItem.status === 'will_skip_existing') {
        setItems((prev) =>
          prev.map((it) =>
            it.key === key
              ? {
                  ...it,
                  status: 'skipped',
                  message: `Отчёт за ${it.fiscalYear} уже есть в БД`,
                }
              : it,
          ),
        );
        continue;
      }
      if (currentItem.status !== 'pending') continue;
      if (currentItem.fiscalYear === null) continue;

      setItems((prev) =>
        prev.map((it) => (it.key === key ? { ...it, status: 'running', message: undefined } : it)),
      );

      try {
        const response = await parsePdfReport({
          companyId,
          fiscalYear: currentItem.fiscalYear,
          file: currentItem.file,
          periodType: 'annual',
          accountingStandard,
          consolidated,
          force: overwriteExisting,
        });
        anySucceeded = true;
        setItems((prev) =>
          prev.map((it) =>
            it.key === key
              ? {
                  ...it,
                  status: 'done',
                  reportId: response.report.id,
                  message: `Черновик #${response.report.id}${
                    response.warnings?.length ? ` · ${response.warnings.length} warn.` : ''
                  }`,
                }
              : it,
          ),
        );
      } catch (err: any) {
        const status = err?.response?.status;
        const detail: string =
          typeof err?.response?.data?.detail === 'string'
            ? err.response.data.detail
            : err?.message ?? 'Неизвестная ошибка';
        // 409 — дубликат: трактуем как «пропущено».
        if (status === 409) {
          setItems((prev) =>
            prev.map((it) =>
              it.key === key
                ? { ...it, status: 'skipped', message: detail }
                : it,
            ),
          );
        } else {
          setItems((prev) =>
            prev.map((it) =>
              it.key === key ? { ...it, status: 'error', message: detail } : it,
            ),
          );
        }
      }
    }

    setRunning(false);
    // Обновим зависимые кэши, если хоть что-то создалось.
    if (anySucceeded) {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.invalidateQueries({ queryKey: ['reports', String(companyId)] });
      queryClient.invalidateQueries({ queryKey: ['reports-unverified-counts'] });
      await refreshCompanyMultipliers(companyId, true).catch(() => {});
      queryClient.invalidateQueries({ queryKey: ['multipliers', String(companyId)] });
    }
  };

  const cancelBatch = () => {
    cancelRef.current = true;
  };

  // Счётчики
  const counts = useMemo(() => {
    const c = {
      total: items.length,
      toProcess: 0,
      willSkip: 0,
      noYear: 0,
      done: 0,
      skipped: 0,
      error: 0,
    };
    for (const it of items) {
      if (it.status === 'pending' || it.status === 'running') c.toProcess += 1;
      else if (it.status === 'will_skip_existing') c.willSkip += 1;
      else if (it.status === 'no_year') c.noYear += 1;
      else if (it.status === 'done') c.done += 1;
      else if (it.status === 'skipped') c.skipped += 1;
      else if (it.status === 'error') c.error += 1;
    }
    return c;
  }, [items]);

  const canStart =
    !running &&
    items.length > 0 &&
    counts.noYear === 0 &&
    counts.toProcess > 0;

  return (
    <div className="ai-parse-body">
      <div className="ai-parse-status-line">
        <span className="ai-parse-status-label">Модель:</span>
        <code className="ai-parse-model">{llmModel}</code>
      </div>

      <div className="ai-parse-hint">
        Укажите папку с PDF-отчётами компании. Мы попробуем угадать год по имени
        файла (<code>20XX</code>) и пакетно отправим каждый в LLM. Годы, которые
        уже есть в БД, будут <b>пропущены</b>.
      </div>

      <div className="ai-parse-field">
        <label htmlFor="ai-batch-dir">
          Папка с PDF-файлами <span className="ai-parse-req">*</span>
        </label>
        <input
          ref={inputRef}
          id="ai-batch-dir"
          type="file"
          accept=".pdf,application/pdf"
          multiple
          // webkitdirectory — нестандартный атрибут, прокидываем как any
          {...({ webkitdirectory: '', directory: '' } as any)}
          onChange={(e) => handleFilesPicked(e.target.files)}
          disabled={running}
        />
        <small className="ai-parse-file-info">
          Можно также выделить несколько PDF обычным файл-диалогом
          (Ctrl/Shift+клик).
        </small>
      </div>

      <div className="ai-parse-grid">
        <div className="ai-parse-field">
          <label htmlFor="ai-batch-standard">Стандарт учёта (для всех)</label>
          <select
            id="ai-batch-standard"
            value={accountingStandard}
            onChange={(e) => setAccountingStandard(e.target.value as AccountingStandard)}
            disabled={running}
          >
            <option value="IFRS">МСФО (IFRS)</option>
            <option value="RAS">РСБУ (RAS)</option>
            <option value="US_GAAP">US GAAP</option>
            <option value="UK_GAAP">UK GAAP</option>
            <option value="OTHER">Другой</option>
          </select>
        </div>
        <div className="ai-parse-field" style={{ alignSelf: 'end' }}>
          <div className="ai-parse-checkboxes">
            <label className="ai-parse-checkbox">
              <input
                type="checkbox"
                checked={consolidated}
                onChange={(e) => setConsolidated(e.target.checked)}
                disabled={running}
              />
              Консолидированные
            </label>
            <label
              className="ai-parse-checkbox"
              title="Если включено — даже уже существующие в БД годы будут пересозданы (с force=true)"
            >
              <input
                type="checkbox"
                checked={overwriteExisting}
                onChange={(e) => {
                  setOverwriteExisting(e.target.checked);
                  recalcPendingAfterOverwriteToggle(e.target.checked);
                }}
                disabled={running}
              />
              Перезаписать существующие
            </label>
          </div>
        </div>
      </div>

      {items.length > 0 && (
        <>
          <div className="ai-batch-summary">
            <span>Всего: <b>{counts.total}</b></span>
            <span className="ai-batch-stat is-pending">К отправке: <b>{counts.toProcess}</b></span>
            {counts.willSkip > 0 && (
              <span className="ai-batch-stat is-skipped">Уже в БД: <b>{counts.willSkip}</b></span>
            )}
            {counts.noYear > 0 && (
              <span className="ai-batch-stat is-error">Без года: <b>{counts.noYear}</b></span>
            )}
            {counts.done > 0 && (
              <span className="ai-batch-stat is-done">Создано: <b>{counts.done}</b></span>
            )}
            {counts.skipped > 0 && (
              <span className="ai-batch-stat is-skipped">Пропущено: <b>{counts.skipped}</b></span>
            )}
            {counts.error > 0 && (
              <span className="ai-batch-stat is-error">Ошибок: <b>{counts.error}</b></span>
            )}
          </div>

          <div className="ai-batch-table-wrap">
            <table className="ai-batch-table">
              <thead>
                <tr>
                  <th>Файл</th>
                  <th style={{ width: 110 }}>Год</th>
                  <th style={{ width: 170 }}>Статус</th>
                  <th>Примечание</th>
                  <th style={{ width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <BatchRow
                    key={it.key}
                    item={it}
                    disabled={running}
                    onYearChange={(y) => updateItemYear(it.key, y)}
                    onRemove={() => removeItem(it.key)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="ai-parse-footer">
        <button
          type="button"
          className="ai-parse-btn-secondary"
          onClick={onClose}
          disabled={running}
        >
          Закрыть
        </button>
        {items.length > 0 && !running && (
          <button
            type="button"
            className="ai-parse-btn-secondary"
            onClick={resetAll}
          >
            Очистить
          </button>
        )}
        {running ? (
          <button
            type="button"
            className="ai-parse-btn-secondary"
            onClick={cancelBatch}
          >
            ⏹ Остановить
          </button>
        ) : (
          <button
            type="button"
            className="ai-parse-btn-primary"
            onClick={runBatch}
            disabled={!canStart}
            title={
              counts.noYear > 0
                ? 'Укажите год для всех файлов'
                : counts.toProcess === 0
                ? 'Все файлы уже обработаны или пропущены'
                : 'Отправить в LLM'
            }
          >
            ▶ Запустить ({counts.toProcess})
          </button>
        )}
      </div>
    </div>
  );
};

interface BatchRowProps {
  item: BatchItem;
  disabled: boolean;
  onYearChange: (year: number | null) => void;
  onRemove: () => void;
}

const BATCH_STATUS_META: Record<BatchItemStatus, { label: string; cls: string }> = {
  pending: { label: 'в очереди', cls: 'is-pending' },
  will_skip_existing: { label: 'уже в БД · пропустим', cls: 'is-skipped' },
  no_year: { label: '⚠ укажите год', cls: 'is-error' },
  running: { label: '⟳ обработка…', cls: 'is-running' },
  done: { label: '✓ создан', cls: 'is-done' },
  skipped: { label: '⊘ пропущен', cls: 'is-skipped' },
  error: { label: '✗ ошибка', cls: 'is-error' },
  cancelled: { label: '— отменён', cls: 'is-skipped' },
};

const BatchRow: React.FC<BatchRowProps> = ({ item, disabled, onYearChange, onRemove }) => {
  const meta = BATCH_STATUS_META[item.status];
  const isRunning = item.status === 'running';
  const canEditYear = !disabled && !isRunning && item.status !== 'done' && item.status !== 'skipped';
  return (
    <tr className={`ai-batch-row ${meta.cls}`}>
      <td className="ai-batch-file" title={item.file.name}>
        {item.file.name}
        <span className="ai-batch-size">
          {' · '}
          {(item.file.size / 1024 / 1024).toFixed(2)} МБ
        </span>
      </td>
      <td>
        <input
          type="number"
          className="ai-batch-year-input"
          value={item.fiscalYear ?? ''}
          min={1990}
          max={CURRENT_YEAR + 1}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (raw === '') {
              onYearChange(null);
              return;
            }
            const n = parseInt(raw, 10);
            onYearChange(Number.isFinite(n) ? n : null);
          }}
          disabled={!canEditYear}
          placeholder="20XX"
        />
      </td>
      <td>
        <span className={`ai-batch-badge ${meta.cls}`}>{meta.label}</span>
      </td>
      <td className="ai-batch-note">{item.message ?? ''}</td>
      <td>
        {!disabled && item.status !== 'running' && (
          <button
            type="button"
            className="ai-batch-remove"
            onClick={onRemove}
            title="Убрать из списка"
          >
            ✕
          </button>
        )}
      </td>
    </tr>
  );
};

export default AiParsePdfModal;
