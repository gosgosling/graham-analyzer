import { api } from './companies.api';

export type CoverageStatus =
  | 'waiting'
  | 'overdue'
  | 'available'
  | 'in_service'
  | 'unknown';

export interface DisclosureSyncRun {
  id: number;
  status: string;
  companies_total: number;
  companies_done: number;
  periods_found: number;
  last_message: string | null;
  worker_alive: boolean;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface CoverageItem {
  id: number;
  company_id: number;
  ticker: string;
  period_type: string;
  fiscal_year: number;
  fiscal_quarter: number | null;
  period_key: string;
  period_label: string | null;
  doc_type: string | null;
  published_at: string | null;
  on_edisclosure: boolean;
  in_db: boolean;
  on_disk: boolean;
  is_latest_interim: boolean;
  expectation: string;
  coverage_status: CoverageStatus;
  file_url: string | null;
  pdf_path: string | null;
  report_id: number | null;
}

export interface CoverageSummary {
  total: number;
  waiting: number;
  overdue: number;
  available: number;
  in_service: number;
  unknown: number;
  last_sync: DisclosureSyncRun | null;
}

export interface DisclosureParseJob {
  id: number;
  status: string;
  total_items: number;
  done_ok: number;
  done_error: number;
  done_skipped: number;
  last_message: string | null;
  worker_alive: boolean;
}

function errDetail(error: unknown): string {
  const ax = error as { response?: { data?: { detail?: string } } };
  return ax?.response?.data?.detail || (error instanceof Error ? error.message : 'Ошибка');
}

export const getDisclosureSummary = async (): Promise<CoverageSummary> => {
  const { data } = await api.get<CoverageSummary>('/disclosure/summary');
  return data;
};

export const getDisclosureCoverage = async (params: {
  mode?: 'missing' | 'expected' | 'all';
  status?: string;
  ticker?: string;
  period_type?: string;
  limit?: number;
}): Promise<CoverageItem[]> => {
  const { data } = await api.get<CoverageItem[]>('/disclosure/coverage', { params });
  return data;
};

export const startDisclosureSync = async (tickers?: string[]): Promise<DisclosureSyncRun> => {
  try {
    const { data } = await api.post<DisclosureSyncRun>('/disclosure/sync', { tickers });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};

export const getDisclosureSyncStatus = async (): Promise<DisclosureSyncRun | null> => {
  const { data } = await api.get<DisclosureSyncRun | null>('/disclosure/sync/status');
  return data;
};

export const downloadDisclosurePeriods = async (
  periodIds: number[],
): Promise<{ downloaded: number; paths: Record<string, string>; errors: string[] }> => {
  try {
    const { data } = await api.post('/disclosure/download', { period_ids: periodIds });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};

export const enqueueDisclosureParse = async (
  periodIds: number[],
): Promise<DisclosureParseJob> => {
  try {
    const { data } = await api.post<DisclosureParseJob>('/disclosure/enqueue-parse', {
      period_ids: periodIds,
    });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};

export const getDisclosureParseJob = async (jobId: number): Promise<DisclosureParseJob> => {
  const { data } = await api.get<DisclosureParseJob>(`/disclosure/parse-jobs/${jobId}`);
  return data;
};

export const refreshDisclosureFlags = async (): Promise<{ updated: number }> => {
  const { data } = await api.post<{ updated: number }>('/disclosure/refresh-flags');
  return data;
};

export const importDisclosureListing = async (
  items: Record<string, unknown>[],
  applyCoverageFilter = true,
): Promise<{ imported: number; tickers: string[]; skipped_tickers: string[] }> => {
  try {
    const { data } = await api.post('/disclosure/import-listing', {
      items,
      apply_coverage_filter: applyCoverageFilter,
    });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};
