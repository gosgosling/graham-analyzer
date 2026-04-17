import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  comparePdfReport,
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
type Mode = 'create' | 'compare';

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

export default AiParsePdfModal;
