import { api } from './companies.api';

export type MassParseJobStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'cancelled';

export type MassParseItemStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'skipped'
  | 'error'
  | 'cancelled';

export interface MassParsePreview {
  reports_root: string;
  ticker_dirs: number;
  pdf_files: number;
  queued: number;
  skipped_company_has_reports: number;
  skipped_company_not_found: number;
  skipped_no_year: number;
  skipped_banks: number;
  companies_with_reports_in_db: number;
  llm_configured: boolean;
  llm_model: string;
}

export interface MassParseJob {
  id: number;
  status: MassParseJobStatus;
  reports_root: string;
  skip_companies_with_reports: boolean;
  force: boolean;
  accounting_standard: string;
  consolidated: boolean;
  total_items: number;
  done_ok: number;
  done_skipped: number;
  done_error: number;
  pending_count: number;
  processed_count: number;
  current_item_id: number | null;
  last_message: string | null;
  worker_alive: boolean;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface MassParseItem {
  id: number;
  position: number;
  ticker: string;
  company_id: number | null;
  fiscal_year: number | null;
  pdf_path: string;
  status: MassParseItemStatus;
  message: string | null;
  report_id: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface MassParseCreateRequest {
  reports_root?: string;
  skip_companies_with_reports?: boolean;
  force?: boolean;
  accounting_standard?: string;
  consolidated?: boolean;
  auto_start?: boolean;
}

function errDetail(error: unknown): string {
  const ax = error as { response?: { data?: { detail?: string } } };
  return ax?.response?.data?.detail || (error instanceof Error ? error.message : 'Ошибка запроса');
}

export const getMassParsePreview = async (
  params?: { reports_root?: string; skip_companies_with_reports?: boolean },
): Promise<MassParsePreview> => {
  try {
    const response = await api.get<MassParsePreview>('/mass-parse/preview', { params });
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const listMassParseJobs = async (): Promise<MassParseJob[]> => {
  const response = await api.get<MassParseJob[]>('/mass-parse/jobs');
  return response.data;
};

export const getMassParseJob = async (jobId: number): Promise<MassParseJob> => {
  const response = await api.get<MassParseJob>(`/mass-parse/jobs/${jobId}`);
  return response.data;
};

export const getMassParseItems = async (
  jobId: number,
  params?: { status?: string; limit?: number; offset?: number },
): Promise<MassParseItem[]> => {
  const response = await api.get<MassParseItem[]>(`/mass-parse/jobs/${jobId}/items`, { params });
  return response.data;
};

export const createMassParseJob = async (body: MassParseCreateRequest): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>('/mass-parse/jobs', body);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const startMassParseJob = async (jobId: number): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>(`/mass-parse/jobs/${jobId}/start`);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const pauseMassParseJob = async (jobId: number): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>(`/mass-parse/jobs/${jobId}/pause`);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const resumeMassParseJob = async (jobId: number): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>(`/mass-parse/jobs/${jobId}/resume`);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const cancelMassParseJob = async (jobId: number): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>(`/mass-parse/jobs/${jobId}/cancel`);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};

export const retryMassParseErrors = async (jobId: number): Promise<MassParseJob> => {
  try {
    const response = await api.post<MassParseJob>(`/mass-parse/jobs/${jobId}/retry-errors`);
    return response.data;
  } catch (error) {
    throw new Error(errDetail(error));
  }
};
