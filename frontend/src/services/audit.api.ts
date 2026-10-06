import { api } from './companies.api';
import type { AuditFailure } from '../utils/auditText';

export type { AuditFailure } from '../utils/auditText';

/** Только для администратора: сервер закрывает /admin и на чтение. */
export const fetchAuditFailures = async (): Promise<AuditFailure[]> =>
  (await api.get<AuditFailure[]>('/admin/audit')).data;
