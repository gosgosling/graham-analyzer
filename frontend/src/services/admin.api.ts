import { api } from './companies.api';

export interface PostgresBackupResponse {
    status: string;
    filename: string;
    path: string;
    size_bytes: number;
    size_human: string;
    message: string;
}

export const createPostgresBackup = async (): Promise<PostgresBackupResponse> => {
    const response = await api.post<PostgresBackupResponse>('/admin/backup/postgres');
    return response.data;
};

export interface DevSyncStatus {
    enabled: boolean;
    id?: string;
    status: 'idle' | 'unavailable' | 'preparing' | 'ready' | 'applying' | 'completed' | 'failed';
    message?: string;
    downloaded_at?: string;
    backup?: PostgresBackupResponse;
    preview?: {
        added: number; updated: number; removed: number;
        verified_dev: number; verified_prod: number;
        companies: { ticker: string; added: number; updated: number; removed: number }[];
        tables: { name: string; dev: number; prod: number }[];
    };
    result?: { reports: number; companies: number; verified: number; accounts_preserved: boolean };
}

export const getDevSyncStatus = async (): Promise<DevSyncStatus> => (await api.get('/admin/dev-sync/status')).data;
export const prepareDevSync = async (): Promise<DevSyncStatus> => (await api.post('/admin/dev-sync/prepare')).data;
export const applyDevSync = async (snapshotId: string): Promise<DevSyncStatus> =>
    (await api.post('/admin/dev-sync/apply', { snapshot_id: snapshotId })).data;
