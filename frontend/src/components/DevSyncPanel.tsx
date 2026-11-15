import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { applyDevSync, getDevSyncStatus, prepareDevSync } from '../services/admin.api';
import { formatApiErrorMessage } from '../utils/apiErrors';
import './DevSyncPanel.css';

const labels: Record<string, string> = {
  idle: 'Ожидает запуска', unavailable: 'Доступно в dev', preparing: 'Получение и проверка снимка',
  ready: 'Снимок готов', applying: 'Синхронизация', completed: 'Завершено', failed: 'Ошибка',
};

export default function DevSyncPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['dev-sync'], queryFn: getDevSyncStatus, refetchInterval: 3000 });
  const prepare = useMutation({ mutationFn: prepareDevSync,
    onSuccess: data => { setError(null); qc.setQueryData(['dev-sync'], data); },
    onError: e => setError(formatApiErrorMessage(e, 'Не удалось получить снимок')) });
  const apply = useMutation({ mutationFn: applyDevSync,
    onSuccess: data => { setError(null); qc.setQueryData(['dev-sync'], data); qc.invalidateQueries(); },
    onError: e => setError(formatApiErrorMessage(e, 'Не удалось синхронизировать dev')) });
  const data = query.data;
  useEffect(() => {
    if (data?.status === 'completed') {
      qc.invalidateQueries({ predicate: q => q.queryKey[0] !== 'dev-sync' });
    }
  }, [data?.status, data?.id, qc]);
  const busy = prepare.isPending || apply.isPending || data?.status === 'preparing' || data?.status === 'applying';
  const message = error || (query.error ? formatApiErrorMessage(query.error, 'Не удалось проверить синхронизацию') : null);

  return <section className="admin-card dev-sync">
    <h2>Синхронизация прод → dev</h2>
    <p>Забрать базу после заполнения отчётов на сайте. Прод служит источником и не изменяется.</p>
    {message && <p role="alert" className="dev-sync-error">{message}</p>}
    {data && <p role="status"><strong>{labels[data.status] || data.status}.</strong> {data.message}</p>}
    {data?.enabled && <>
      <p className="admin-note">Данные проекта в dev будут заменены снимком прода, включая очереди PostgreSQL. Перед записью создаётся бэкап. Локальные аккаунты, PDF и архивы аудитов сохраняются. Отметки аналитика копируются как есть.</p>
      <div className="dev-sync-actions">
        <button type="button" className="db-backup-btn" disabled={busy} onClick={() => prepare.mutate()}>
          {data.status === 'preparing' ? 'Получение снимка…' : 'Получить снимок прода и сравнить'}
        </button>
        {data.status === 'ready' && data.id && <button type="button" className="db-backup-btn" disabled={busy} onClick={() => apply.mutate(data.id!)}>
          Создать бэкап и синхронизировать dev
        </button>}
      </div>
      {data.downloaded_at && <p className="admin-note">Снимок от {new Date(data.downloaded_at).toLocaleString('ru-RU')}. Последующие изменения прода попадут в следующий снимок.</p>}
      {data.preview && <>
        <p>Отчёты: новых <b>{data.preview.added}</b>, изменённых <b>{data.preview.updated}</b>, удаляемых из dev <b>{data.preview.removed}</b>.</p>
        <p className="admin-note">Проверенных аналитиком: dev — {data.preview.verified_dev}, прод — {data.preview.verified_prod}.</p>
        {data.preview.removed > 0 && <p className="dev-sync-error">В dev есть отчёты, которых нет на проде. После применения они останутся только в бэкапе.</p>}
        <details><summary>Изменения по компаниям</summary>
          {data.preview.companies.length ? <div className="dev-sync-table"><table>
            <thead><tr><th>Компания</th><th>Новых</th><th>Изменённых</th><th>Удаляемых</th></tr></thead>
            <tbody>{data.preview.companies.map(c => <tr key={c.ticker}><th scope="row">{c.ticker}</th><td>{c.added}</td><td>{c.updated}</td><td>{c.removed}</td></tr>)}</tbody>
          </table></div> : <p>Отчёты совпадают.</p>}
        </details>
        <details><summary>Количество записей по таблицам</summary>
          <div className="dev-sync-table"><table><thead><tr><th>Таблица</th><th>Dev</th><th>Прод</th></tr></thead>
            <tbody>{data.preview.tables.map(t => <tr key={t.name}><th scope="row">{t.name}</th><td>{t.dev}</td><td>{t.prod}</td></tr>)}</tbody>
          </table></div>
        </details>
      </>}
      {data.backup && <p className="admin-note">Бэкап dev: <code>{data.backup.path}</code></p>}
      {data.result && <p>В dev: {data.result.companies} компаний, {data.result.reports} отчётов. Локальные аккаунты сохранены.</p>}
    </>}
  </section>;
}
