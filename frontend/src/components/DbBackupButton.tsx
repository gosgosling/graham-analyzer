import React from 'react';
import { useMutation } from '@tanstack/react-query';
import { message } from 'antd';
import { createPostgresBackup } from '../services/admin.api';
import './DbBackupButton.css';

const DbBackupButton: React.FC = () => {
  const backupMutation = useMutation({
    mutationFn: createPostgresBackup,
    onSuccess: (data) => {
      message.success(
        `Бэкап создан: ${data.filename} (${data.size_human})\n${data.path}`,
        6,
      );
    },
    onError: (err: unknown) => {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      const detail = ax.response?.data?.detail;
      message.error(
        typeof detail === 'string' ? detail : ax.message ?? 'Не удалось создать бэкап',
        8,
      );
    },
  });

  return (
    <button
      type="button"
      className="db-backup-btn"
      title="Сохранить дамп PostgreSQL в backups/postgres/"
      disabled={backupMutation.isPending}
      onClick={() => backupMutation.mutate()}
    >
      {backupMutation.isPending ? 'Бэкап…' : '💾 Создать бэкап'}
    </button>
  );
};

export default DbBackupButton;
