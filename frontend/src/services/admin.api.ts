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
