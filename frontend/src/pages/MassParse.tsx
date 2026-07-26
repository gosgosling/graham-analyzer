import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelMassParseJob,
  createMassParseJob,
  getMassParseItems,
  getMassParseJob,
  getMassParsePreview,
  listMassParseJobs,
  pauseMassParseJob,
  resumeMassParseJob,
  retryMassParseErrors,
  type MassParseItemStatus,
  type MassParseJob,
} from '../services/massParse.api';
import './MassParse.css';

const STATUS_FILTERS: Array<{ key: string; label: string }> = [
  { key: '', label: 'Все' },
  { key: 'running', label: 'В работе' },
  { key: 'pending', label: 'Ожидают' },
  { key: 'success', label: 'OK' },
  { key: 'error', label: 'Ошибки' },
  { key: 'skipped', label: 'Пропуск' },
];

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending: 'ожидает',
    running: 'парсинг',
    paused: 'пауза',
    completed: 'готово',
    cancelled: 'отменён',
    success: 'ok',
    error: 'ошибка',
    skipped: 'пропуск',
  };
  return map[s] || s;
}

const MassParse: React.FC = () => {
  const queryClient = useQueryClient();
  const [reportsRoot, setReportsRoot] = useState('');
  const [skipWithReports, setSkipWithReports] = useState(true);
  const [force, setForce] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [itemFilter, setItemFilter] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  const previewQuery = useQuery({
    queryKey: ['mass-parse-preview', reportsRoot, skipWithReports],
    queryFn: () =>
      getMassParsePreview({
        reports_root: reportsRoot || undefined,
        skip_companies_with_reports: skipWithReports,
      }),
    staleTime: 15_000,
  });

  const jobsQuery = useQuery({
    queryKey: ['mass-parse-jobs'],
    queryFn: listMassParseJobs,
    refetchInterval: 5000,
  });

  const activeJobId = selectedJobId ?? jobsQuery.data?.[0]?.id ?? null;

  const jobQuery = useQuery({
    queryKey: ['mass-parse-job', activeJobId],
    queryFn: () => getMassParseJob(activeJobId!),
    enabled: activeJobId != null,
    refetchInterval: (q) => {
      const st = q.state.data?.status;
      return st === 'running' ? 2000 : 8000;
    },
  });

  const itemsQuery = useQuery({
    queryKey: ['mass-parse-items', activeJobId, itemFilter],
    queryFn: () =>
      getMassParseItems(activeJobId!, {
        status: itemFilter || undefined,
        limit: 500,
      }),
    enabled: activeJobId != null,
    refetchInterval: () => (jobQuery.data?.status === 'running' ? 2500 : 10000),
  });

  useEffect(() => {
    if (selectedJobId == null && jobsQuery.data?.[0]?.id) {
      setSelectedJobId(jobsQuery.data[0].id);
    }
  }, [jobsQuery.data, selectedJobId]);

  const invalidateJob = async (job: MassParseJob) => {
    setSelectedJobId(job.id);
    await queryClient.invalidateQueries({ queryKey: ['mass-parse-jobs'] });
    await queryClient.invalidateQueries({ queryKey: ['mass-parse-job', job.id] });
    await queryClient.invalidateQueries({ queryKey: ['mass-parse-items', job.id] });
  };

  const createMut = useMutation({
    mutationFn: () =>
      createMassParseJob({
        reports_root: reportsRoot || undefined,
        skip_companies_with_reports: skipWithReports,
        force,
        auto_start: true,
      }),
    onSuccess: async (job) => {
      setActionError(null);
      await invalidateJob(job);
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const pauseMut = useMutation({
    mutationFn: () => pauseMassParseJob(activeJobId!),
    onSuccess: invalidateJob,
    onError: (e: Error) => setActionError(e.message),
  });

  const resumeMut = useMutation({
    mutationFn: () => resumeMassParseJob(activeJobId!),
    onSuccess: invalidateJob,
    onError: (e: Error) => setActionError(e.message),
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelMassParseJob(activeJobId!),
    onSuccess: invalidateJob,
    onError: (e: Error) => setActionError(e.message),
  });

  const retryMut = useMutation({
    mutationFn: () => retryMassParseErrors(activeJobId!),
    onSuccess: invalidateJob,
    onError: (e: Error) => setActionError(e.message),
  });

  const job = jobQuery.data;
  const preview = previewQuery.data;

  const progressPct = useMemo(() => {
    if (!job || !job.total_items) return 0;
    return Math.min(100, Math.round((job.processed_count / job.total_items) * 100));
  }, [job]);

  const busy =
    createMut.isPending ||
    pauseMut.isPending ||
    resumeMut.isPending ||
    cancelMut.isPending ||
    retryMut.isPending;

  return (
    <div className="mass-parse-page">
      <h1>Массовый AI-парсинг</h1>
      <p className="mass-parse-lead">
        Каталоги тикеров на диске → очередь PDF. Компании, у которых уже есть отчёты,
        пропускаются. Ошибка по одному файлу не останавливает очередь; Pause → фикс → Resume
        продолжает с того же места.
      </p>

      <section className="mass-parse-panel">
        <h2>Сканирование диска</h2>
        <div className="mass-parse-row">
          <input
            type="text"
            placeholder={preview?.reports_root || '/home/devops/Reports'}
            value={reportsRoot}
            onChange={(e) => setReportsRoot(e.target.value)}
          />
          <button
            type="button"
            className="mass-parse-btn"
            onClick={() => previewQuery.refetch()}
            disabled={previewQuery.isFetching}
          >
            Обновить превью
          </button>
        </div>
        <div className="mass-parse-row">
          <label>
            <input
              type="checkbox"
              checked={skipWithReports}
              onChange={(e) => setSkipWithReports(e.target.checked)}
            />
            Пропускать компании, у которых уже есть отчёты
          </label>
          <label>
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            Перезаписывать дубликаты годов (force)
          </label>
        </div>

        {previewQuery.isError && (
          <div className="mass-parse-error">
            {(previewQuery.error as Error)?.message || 'Не удалось просканировать каталог'}
          </div>
        )}

        {preview && (
          <>
            <div className="mass-parse-stats">
              <div className="mass-parse-stat">
                <span className="label">В очереди</span>
                <span className="value">{preview.queued}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">PDF всего</span>
                <span className="value">{preview.pdf_files}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">Тикеров на диске</span>
                <span className="value">{preview.ticker_dirs}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">С отчётами в БД</span>
                <span className="value is-skip">{preview.companies_with_reports_in_db}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">Пропуск (есть отчёты)</span>
                <span className="value is-skip">{preview.skipped_company_has_reports}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">Пропуск (банки)</span>
                <span className="value is-skip">{preview.skipped_banks}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">Нет компании</span>
                <span className="value is-err">{preview.skipped_company_not_found}</span>
              </div>
              <div className="mass-parse-stat">
                <span className="label">Без года в имени</span>
                <span className="value is-skip">{preview.skipped_no_year}</span>
              </div>
            </div>
            <p className="mass-parse-message">
              Корень: <code>{preview.reports_root}</code>
              {preview.llm_configured
                ? ` · LLM: ${preview.llm_model}`
                : ' · LLM не настроен'}
            </p>
          </>
        )}

        <div className="mass-parse-actions">
          <button
            type="button"
            className="primary"
            disabled={busy || !preview?.queued || !preview.llm_configured}
            onClick={() => {
              if (
                !window.confirm(
                  `Создать и запустить очередь из ${preview?.queued ?? 0} PDF?\n` +
                    `Компании с отчётами будут пропущены (${preview?.companies_with_reports_in_db ?? 0}).`,
                )
              ) {
                return;
              }
              createMut.mutate();
            }}
          >
            {createMut.isPending ? 'Создаём…' : 'Создать и запустить'}
          </button>
        </div>
      </section>

      {actionError && <div className="mass-parse-error">{actionError}</div>}

      <section className="mass-parse-panel">
        <h2>Задания</h2>
        <div className="mass-parse-jobs-list">
          {(jobsQuery.data ?? []).length === 0 && (
            <p className="mass-parse-message">Пока нет заданий.</p>
          )}
          {(jobsQuery.data ?? []).map((j) => (
            <button
              key={j.id}
              type="button"
              className={`mass-parse-job-link${activeJobId === j.id ? ' active' : ''}`}
              onClick={() => setSelectedJobId(j.id)}
            >
              <span>
                #{j.id} · {statusLabel(j.status)}
                {j.worker_alive ? ' · worker' : ''}
              </span>
              <span>
                {j.processed_count}/{j.total_items} · err {j.done_error}
              </span>
            </button>
          ))}
        </div>
      </section>

      {job && (
        <section className="mass-parse-panel">
          <h2>
            Мониторинг #{job.id}{' '}
            <span className={`mass-parse-status-pill ${job.status}`}>
              {statusLabel(job.status)}
            </span>
          </h2>

          <div className="mass-parse-stats">
            <div className="mass-parse-stat">
              <span className="label">Всего</span>
              <span className="value">{job.total_items}</span>
            </div>
            <div className="mass-parse-stat">
              <span className="label">OK</span>
              <span className="value is-ok">{job.done_ok}</span>
            </div>
            <div className="mass-parse-stat">
              <span className="label">Пропуск</span>
              <span className="value is-skip">{job.done_skipped}</span>
            </div>
            <div className="mass-parse-stat">
              <span className="label">Ошибки</span>
              <span className="value is-err">{job.done_error}</span>
            </div>
            <div className="mass-parse-stat">
              <span className="label">Осталось</span>
              <span className="value">{job.pending_count}</span>
            </div>
            <div className="mass-parse-stat">
              <span className="label">Прогресс</span>
              <span className="value">{progressPct}%</span>
            </div>
          </div>

          <div className="mass-parse-progress">
            <div className="mass-parse-progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
          <p className="mass-parse-message">{job.last_message}</p>
          {!job.worker_alive && job.status === 'running' && (
            <p className="mass-parse-error">
              Статус running, но воркер не жив (возможен рестарт API). Нажмите Resume.
            </p>
          )}

          <div className="mass-parse-actions">
            <button
              type="button"
              disabled={busy || job.status !== 'running'}
              onClick={() => pauseMut.mutate()}
            >
              Pause
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || (job.status !== 'paused' && job.status !== 'pending')}
              onClick={() => resumeMut.mutate()}
            >
              Resume
            </button>
            <button
              type="button"
              className="danger"
              disabled={busy || job.status === 'completed' || job.status === 'cancelled'}
              onClick={() => {
                if (window.confirm('Отменить оставшиеся pending-элементы?')) {
                  cancelMut.mutate();
                }
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || job.done_error === 0 || job.status === 'running'}
              onClick={() => retryMut.mutate()}
            >
              Retry errors
            </button>
          </div>
        </section>
      )}

      {activeJobId != null && (
        <section className="mass-parse-panel">
          <h2>Элементы очереди</h2>
          <div className="mass-parse-filters">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key || 'all'}
                type="button"
                className={itemFilter === f.key ? 'active' : ''}
                onClick={() => setItemFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="mass-parse-table-wrap">
            <table className="mass-parse-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Тикер</th>
                  <th>Год</th>
                  <th>Статус</th>
                  <th>Сообщение</th>
                  <th>Файл</th>
                </tr>
              </thead>
              <tbody>
                {(itemsQuery.data ?? []).map((it) => (
                  <tr key={it.id} className={it.status === 'running' ? 'is-running' : ''}>
                    <td>{it.position + 1}</td>
                    <td>{it.ticker}</td>
                    <td>{it.fiscal_year ?? '—'}</td>
                    <td>
                      <span className={`mass-parse-status-pill ${it.status as MassParseItemStatus}`}>
                        {statusLabel(it.status)}
                      </span>
                    </td>
                    <td>{it.message ?? (it.report_id ? `report #${it.report_id}` : '')}</td>
                    <td className="mass-parse-path" title={it.pdf_path}>
                      {it.pdf_path.split('/').pop()}
                    </td>
                  </tr>
                ))}
                {(itemsQuery.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6}>Нет элементов для фильтра</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
};

export default MassParse;
