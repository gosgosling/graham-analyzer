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

/**
 * Пропущенные отчёты — по собственным данным сервиса.
 *
 * В отличие от `getDisclosureCoverage`, который сверяется с центром
 * раскрытия через скрапер, здесь нет ни одного внешнего запроса: ожидание
 * периода выводится из истории самой компании, срок — из её медианной
 * задержки публикации. Поэтому раздел работает, даже когда e-disclosure
 * отдаёт 403.
 */
export interface ExpectedPeriod {
  company_id: number;
  ticker: string;
  name: string | null;
  period_type: string;
  fiscal_year: number;
  fiscal_quarter: number | null;
  period_key: string;
  period_label: string;
  period_end: string;
  deadline: string;
  status: 'filed' | 'window_open' | 'overdue';
  days_overdue: number | null;
  report_id: number | null;
}

export interface ExpectationsResponse {
  total: number;
  filed: number;
  window_open: number;
  overdue: number;
  companies_with_gaps: number;
  items: ExpectedPeriod[];
}

export const getExpectations = async (
  status: 'overdue' | 'window_open' | 'filed' | 'all' = 'overdue',
  limit = 200,
): Promise<ExpectationsResponse> => {
  try {
    const { data } = await api.get('/disclosure/expectations', {
      params: { status, limit },
    });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};

/**
 * Календарь ожидаемых публикаций.
 *
 * Прогноз, а не расписание: точной даты будущей публикации не существует,
 * поэтому каждая строка несёт пометку собственной точности.
 */
export interface UpcomingReport {
  company_id: number;
  ticker: string;
  name: string | null;
  logo_url: string | null;
  period_type: string;
  fiscal_year: number;
  fiscal_quarter: number | null;
  period_key: string;
  period_label: string;
  period_end: string;
  expected_date: string;
  confidence: 'narrow' | 'wide' | 'rough';
  lag_days: number;
  lag_spread: number | null;
  samples: number;
}

export interface CalendarResponse {
  today: string;
  horizon_days: number;
  total: number;
  days: { day: string; items: UpcomingReport[] }[];
}

export const getReportCalendar = async (days = 140): Promise<CalendarResponse> => {
  try {
    const { data } = await api.get('/disclosure/calendar', { params: { days } });
    return data;
  } catch (e) {
    throw new Error(errDetail(e));
  }
};
