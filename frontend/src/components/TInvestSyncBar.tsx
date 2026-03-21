import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCompaniesSyncStatus, syncCompaniesFromTinkoff } from '../services/api';
import './TInvestSyncBar.css';

/**
 * Панель синхронизации компаний с T-Invest API + диагностика.
 * Используется на главной (MOEX) и на странице списка компаний.
 */
const TInvestSyncBar: React.FC = () => {
  const queryClient = useQueryClient();
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncTone, setSyncTone] = useState<'ok' | 'warn' | 'err'>('ok');

  const { data: status, isLoading: statusLoading, refetch: refetchStatus } = useQuery({
    queryKey: ['companiesSyncStatus'],
    queryFn: getCompaniesSyncStatus,
    staleTime: 30_000,
  });

  const syncMutation = useMutation({
    mutationFn: syncCompaniesFromTinkoff,
    onSuccess: (data) => {
      const s = data.statistics;
      setSyncTone(data.status === 'warning' ? 'warn' : 'ok');
      setSyncMessage(
        `${data.message}\nИз API получено: ${s.total}, создано: ${s.created}, обновлено: ${s.updated}, ошибок: ${s.errors}`,
      );
      queryClient.invalidateQueries({ queryKey: ['companiesSyncStatus'] });
      queryClient.invalidateQueries({ queryKey: ['companies'] });
      queryClient.invalidateQueries({ queryKey: ['company'] });
    },
    onError: (err: unknown) => {
      setSyncTone('err');
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      const d = ax.response?.data?.detail;
      setSyncMessage(
        typeof d === 'string' ? d : ax.message ?? 'Ошибка синхронизации',
      );
    },
  });

  return (
    <div className="tinvest-sync-bar">
      <div className="tinvest-sync-bar-row">
        <div className="tinvest-sync-info">
          <span className="tinvest-sync-title">T-Invest — компании в БД</span>
          {statusLoading && <span className="tinvest-sync-muted">загрузка статуса…</span>}
          {status && !statusLoading && (
            <ul className="tinvest-sync-stats">
              <li>
                Токен:{' '}
                <strong className={status.token_configured ? 'ok' : 'bad'}>
                  {status.token_configured ? 'настроен' : 'не настроен / заглушка'}
                </strong>
              </li>
              <li>Всего компаний: <strong>{status.companies_total}</strong></li>
              <li>
                С логотипом: <strong>{status.companies_with_brand_logo}</strong>, с цветом бренда:{' '}
                <strong>{status.companies_with_brand_color}</strong>
              </li>
            </ul>
          )}
        </div>
        <div className="tinvest-sync-actions">
          <button
            type="button"
            className="btn-tinvest-refresh"
            onClick={() => refetchStatus()}
            disabled={statusLoading}
          >
            Обновить статус
          </button>
          <button
            type="button"
            className="btn-tinvest-sync"
            onClick={() => {
              setSyncMessage(null);
              setSyncTone('ok');
              syncMutation.mutate();
            }}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Синхронизация…' : 'Синхронизировать с T-Invest'}
          </button>
        </div>
      </div>
      {syncMessage && (
        <pre
          className={`tinvest-sync-result ${syncTone === 'err' ? 'error' : ''} ${syncTone === 'warn' ? 'warn' : ''}`}
        >
          {syncMessage}
        </pre>
      )}
      <p className="tinvest-sync-hint">
        После успешной синхронизации откройте карточку компании — в шапке появятся логотип и фирменный цвет
        (если API их отдал). Первая синхронизация может занять несколько минут из‑за догрузки ShareBy по каждой
        бумаге.
      </p>
    </div>
  );
};

export default TInvestSyncBar;
