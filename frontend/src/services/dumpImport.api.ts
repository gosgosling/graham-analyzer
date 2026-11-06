import { api, API_BASE_URL } from './companies.api';
export interface DumpCompany { ticker: string; name: string; company_id: number; kind: string; protected: boolean; excluded: boolean }
export interface DumpOverview { companies: DumpCompany[]; apply_allowed: boolean; policy_version: number; rules: string[]; worker_alive: boolean }
export interface DumpSummary { facts: number; metrics: number; periods: number; add: number; matches: number; differences: number; blocked: number; new_reports: number; missing_fields: number; protected: boolean; first_date: string | null; last_date: string | null }
export interface DumpJob { id: string; status: string; phase: 'audit' | 'apply'; created_at: string; updated_at: string; message: string; total: number; counts: Record<string, number>; totals: Record<string, number>; worker_alive: boolean; backup: Record<string, unknown> | null; retry_at: string | null }
export interface DumpItem { ticker: string; status: string; message: string; summary: DumpSummary | null }
export interface DumpCell { date: string; period_type: string; field: string; current: string | null; source: string; delta: string | null; action: string; reason: string; definition: string; provenance: string[] }
export interface AuditFinding { year: number; level: string; message?: string; detail?: string; code?: string }
export interface DumpAudit { ticker: string; company_id: number; summary: DumpSummary; warnings: string[]; source_version: string | null; source_origin: string; source_completeness: string; coverage: { field: string; codes: string[]; facts: number; present: boolean; usable_facts: number; mapped: boolean }[]; unmapped_metrics: string[]; not_projected: Record<string, number>; issues: unknown[]; audit_before: { findings: AuditFinding[] }; audit_projected: { findings: AuditFinding[] } }
const base = '/admin/dump-import';
export const dumpOverview = async (): Promise<DumpOverview> => (await api.get(`${base}/overview`)).data;
export const dumpJobs = async (): Promise<DumpJob[]> => (await api.get(`${base}/jobs`)).data;
export const dumpJob = async (id: string): Promise<DumpJob> => (await api.get(`${base}/jobs/${id}`)).data;
export const dumpItems = async (id: string): Promise<DumpItem[]> => (await api.get(`${base}/jobs/${id}/items`)).data;
export const dumpEvents = async (id: string): Promise<{ id: number; at: string; message: string }[]> => (await api.get(`${base}/jobs/${id}/events`)).data;
export const createDumpJob = async (tickers: string[], refresh: boolean): Promise<DumpJob> => (await api.post(`${base}/jobs`, { tickers, refresh })).data;
export const controlDumpJob = async (id: string, action: string): Promise<DumpJob> => (await api.post(`${base}/jobs/${id}/control/${action}`)).data;
export const dumpAudit = async (id: string, ticker: string): Promise<DumpAudit> => (await api.get(`${base}/jobs/${id}/companies/${ticker}`)).data;
export const dumpCells = async (id: string, ticker: string, action: string, offset: number): Promise<{ total: number; items: DumpCell[] }> => (await api.get(`${base}/jobs/${id}/companies/${ticker}/cells`, { params: { action, offset, limit: 100 } })).data;
export const dumpDownloadUrl = (id: string, ticker: string, kind: string): string => `${API_BASE_URL}${base}/jobs/${id}/companies/${ticker}/download/${kind}`;
