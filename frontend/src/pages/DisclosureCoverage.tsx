import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  downloadDisclosurePeriods,
  enqueueDisclosureParse,
  getDisclosureCoverage,
  getDisclosureParseJob,
  getDisclosureSummary,
  getDisclosureSyncStatus,
  startDisclosureSync,
  type CoverageItem,
  type CoverageStatus,
} from '../services/disclosure.api';
import './DisclosureCoverage.css';

type Mode = 'missing' | 'expected' | 'all';

const STATUS_LABEL: Record<CoverageStatus, string> = {
  waiting: 'ждём',
  overdue: 'просрочено',
  available: 'есть на сайте',
  in_service: 'в сервисе',
  unknown: '—',
};

function periodLabel(it: CoverageItem): string {
  if (it.period_label) return it.period_label;
  return it.period_key;
}

const DisclosureCoverage: React.FC = () => {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>('missing');
  const [tickerFilter, setTickerFilter] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const [parseJobId, setParseJobId] = useState<number | null>(null);

  const summaryQ = useQuery({
    queryKey: ['disclosure-summary'],
    queryFn: getDisclosureSummary,
    refetchInterval: 5000,
  });

  const syncQ = useQuery({
    queryKey: ['disclosure-sync'],
    queryFn: getDisclosureSyncStatus,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : 10000),
  });

  const coverageQ = useQuery({
    queryKey: ['disclosure-coverage', mode, tickerFilter],
    queryFn: () =>
      getDisclosureCoverage({
        mode,
        ticker: tickerFilter.trim() || undefined,
        limit: 1000,
      }),
    refetchInterval: 8000,
  });

  const parseJobQ = useQuery({
    queryKey: ['disclosure-parse-job', parseJobId],
    queryFn: () => getDisclosureParseJob(parseJobId!),
    enabled: parseJobId != null,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : false),
  });

  const syncMut = useMutation({
    mutationFn: () => startDisclosureSync(),
    onSuccess: async () => {
      setActionError(null);
      await qc.invalidateQueries({ queryKey: ['disclosure-sync'] });
      await qc.invalidateQueries({ queryKey: ['disclosure-summary'] });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const downloadMut = useMutation({
    mutationFn: (ids: number[]) => downloadDisclosurePeriods(ids),
    onSuccess: async (res) => {
      setActionError(null);
      if (res.errors?.length) setActionError(res.errors.join('; '));
      await qc.invalidateQueries({ queryKey: ['disclosure-coverage'] });
      await qc.invalidateQueries({ queryKey: ['disclosure-summary'] });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const parseMut = useMutation({
    mutationFn: (ids: number[]) => enqueueDisclosureParse(ids),
    onSuccess: async (job) => {
      setActionError(null);
      setParseJobId(job.id);
      await qc.invalidateQueries({ queryKey: ['disclosure-coverage'] });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const items = coverageQ.data ?? [];
  const summary = summaryQ.data;
  const sync = syncQ.data ?? summary?.last_sync;

  const allSelected = useMemo(
    () => items.length > 0 && items.every((i) => selected.has(i.id)),
    [items, selected],
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(items.map((i) => i.id)));
  };

  const busy = syncMut.isPending || downloadMut.isPending || parseMut.isPending;
  const syncing = sync?.status === 'running' || sync?.worker_alive;

  return (
    <div className="disclosure-page">
      <h1>Мониторинг отчётности</h1>
      <p className="disclosure-lead">
        Календарь ожиданий и gap «есть на e-disclosure — нет в сервисе». Listing обновляется
        раз в неделю (и вручную). Скачивание и AI-парсинг — только по кнопке. Промежуточные:
        только самый свежий период на компанию.
      </p>

      <section className="disclosure-panel">
        {summary && (
          <div className="disclosure-stats">
            <div className="disclosure-stat">
              <span className="label">Всего строк</span>
              <span className="value">{summary.total}</span>
            </div>
            <div className="disclosure-stat">
              <span className="label">Ждём</span>
              <span className="value">{summary.waiting}</span>
            </div>
            <div className="disclosure-stat">
              <span className="label">Просрочено</span>
              <span className="value is-err">{summary.overdue}</span>
            </div>
            <div className="disclosure-stat">
              <span className="label">На сайте, нет у нас</span>
              <span className="value is-avail">{summary.available}</span>
            </div>
            <div className="disclosure-stat">
              <span className="label">В сервисе</span>
              <span className="value is-ok">{summary.in_service}</span>
            </div>
          </div>
        )}

        <div className="disclosure-actions">
          <button
            type="button"
            className="primary"
            disabled={busy || !!syncing}
            onClick={() => {
              if (
                window.confirm(
                  'Запустить полный listing e-disclosure? Это долго (~1 компания/мин).',
                )
              ) {
                syncMut.mutate();
              }
            }}
          >
            {syncing ? 'Синхронизация…' : 'Обновить listing сейчас'}
          </button>
          <button
            type="button"
            disabled={busy || selected.size === 0}
            onClick={() => downloadMut.mutate(Array.from(selected))}
          >
            Скачать выбранные ({selected.size})
          </button>
          <button
            type="button"
            disabled={busy || selected.size === 0}
            onClick={() => parseMut.mutate(Array.from(selected))}
          >
            В очередь парсинга ({selected.size})
          </button>
        </div>

        {sync && (
          <p
            className={
              sync.status === 'error' ? 'disclosure-error' : 'disclosure-message'
            }
          >
            Sync #{sync.id}: {sync.status}
            {sync.companies_total
              ? ` · ${sync.companies_done}/${sync.companies_total}`
              : ''}
            {sync.last_message ? ` · ${sync.last_message}` : ''}
          </p>
        )}

        {parseJobQ.data && (
          <p className="disclosure-message">
            Parse job #{parseJobQ.data.id}: {parseJobQ.data.status} · ok{' '}
            {parseJobQ.data.done_ok}/{parseJobQ.data.total_items}
            {parseJobQ.data.last_message ? ` · ${parseJobQ.data.last_message}` : ''}
          </p>
        )}

        {actionError && <div className="disclosure-error">{actionError}</div>}
      </section>

      <section className="disclosure-panel">
        <div className="disclosure-tabs">
          <button
            type="button"
            className={mode === 'missing' ? 'active' : ''}
            onClick={() => setMode('missing')}
          >
            Нет в сервисе
          </button>
          <button
            type="button"
            className={mode === 'expected' ? 'active' : ''}
            onClick={() => setMode('expected')}
          >
            Ожидаемые
          </button>
          <button
            type="button"
            className={mode === 'all' ? 'active' : ''}
            onClick={() => setMode('all')}
          >
            Все
          </button>
        </div>

        <div className="disclosure-filter">
          <input
            type="text"
            placeholder="Тикер"
            value={tickerFilter}
            onChange={(e) => setTickerFilter(e.target.value.toUpperCase())}
          />
          <span className="disclosure-message" style={{ margin: 0 }}>
            Строк: {items.length}
          </span>
        </div>

        <div className="disclosure-table-wrap">
          <table className="disclosure-table">
            <thead>
              <tr>
                <th>
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                </th>
                <th>Тикер</th>
                <th>Период</th>
                <th>Статус</th>
                <th>Размещён</th>
                <th>Диск</th>
                <th>БД</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(it.id)}
                      onChange={() => toggle(it.id)}
                    />
                  </td>
                  <td>{it.ticker}</td>
                  <td>
                    {periodLabel(it)}
                    {it.is_latest_interim ? ' · latest' : ''}
                  </td>
                  <td>
                    <span className={`disclosure-pill ${it.coverage_status}`}>
                      {STATUS_LABEL[it.coverage_status] || it.coverage_status}
                    </span>
                  </td>
                  <td>{it.published_at || '—'}</td>
                  <td>{it.on_disk ? '✓' : '—'}</td>
                  <td>{it.in_db ? (it.report_id ? `#${it.report_id}` : '✓') : '—'}</td>
                  <td>
                    <div className="disclosure-row-actions">
                      <button
                        type="button"
                        disabled={busy || !it.file_url}
                        onClick={() => downloadMut.mutate([it.id])}
                      >
                        Скачать
                      </button>
                      <button
                        type="button"
                        disabled={busy || !it.on_disk}
                        onClick={() => parseMut.mutate([it.id])}
                      >
                        Парсить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    {coverageQ.isLoading
                      ? 'Загрузка…'
                      : 'Пусто. Запустите sync listing или смените вкладку.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

export default DisclosureCoverage;
