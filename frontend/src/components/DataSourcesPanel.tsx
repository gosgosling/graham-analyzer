import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/companies.api';

/**
 * Состояние внешних источников: работает ли T-Invest, ушли ли цены на резерв
 * Мосбиржи, у скольких компаний цена устарела, сколько логотипов в своём кэше.
 * Данные — `GET /admin/data-sources` (предохранители `utils/source_health.py`).
 */

interface SourceStatus {
  name: string;
  label: string;
  state: 'ok' | 'degraded' | 'down';
  failures_in_row: number;
  retry_at: string | null;
  last_ok: string | null;
  last_failure: string | null;
  last_error: string | null;
}

interface DataSources {
  sources: SourceStatus[];
  prices: {
    companies: number;
    by_source: Record<string, number>;
    stale: number;
    stale_examples: { ticker: string; quoted_at: string | null }[];
  };
  logos: { dir: string; files: number };
}

const STATE_LABEL: Record<SourceStatus['state'], string> = {
  ok: 'работает',
  degraded: 'были сбои',
  down: 'на паузе',
};

const SOURCE_LABEL: Record<string, string> = { tinvest: 'T-Invest', moex: 'Мосбиржа (резерв)' };

const clock = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow',
      })
    : '—';

const DataSourcesPanel: React.FC = () => {
  const { data, isLoading, isError, refetch, isFetching } = useQuery<DataSources>({
    queryKey: ['admin-data-sources'],
    queryFn: async () => (await api.get<DataSources>('/admin/data-sources')).data,
    refetchInterval: 60_000,
  });

  if (isLoading) return <p className="admin-note">Загрузка…</p>;
  if (isError || !data) return <p className="admin-note">Не удалось получить состояние источников.</p>;

  return (
    <div className="ds-panel">
      <table className="ds-table">
        <tbody>
          {data.sources.map((s) => (
            <tr key={s.name}>
              <td>{s.label}</td>
              <td><span className={`ds-state ds-state--${s.state}`}>{STATE_LABEL[s.state]}</span></td>
              <td className="ds-meta">
                {s.state === 'down' && <>следующая попытка {clock(s.retry_at)}; </>}
                {s.last_ok && <>последний ответ {clock(s.last_ok)}</>}
                {s.last_error && <div className="ds-error" title={s.last_error}>{s.last_error}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="admin-note">
        Цены: {Object.entries(data.prices.by_source)
          .map(([k, v]) => `${SOURCE_LABEL[k] ?? k} — ${v}`).join(', ')} из {data.prices.companies}.
        {' '}Старше трёх дней: {data.prices.stale}
        {data.prices.stale > 0 && <> ({data.prices.stale_examples.map((e) => e.ticker).join(', ')})</>}.
        {' '}Логотипов в своём кэше: {data.logos.files}.
        {' '}
        <button type="button" className="ds-refresh" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? 'обновляю…' : 'обновить'}
        </button>
      </p>
    </div>
  );
};

export default DataSourcesPanel;
