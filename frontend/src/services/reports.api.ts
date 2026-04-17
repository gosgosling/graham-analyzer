import { api } from './companies.api';
import {
    ComparePdfResponse,
    FinancialReport,
    FinancialReportCreate,
    LlmStatus,
    ParsePdfResponse,
} from '../types';

export const createFinancialReport = async (
    reportData: FinancialReportCreate
): Promise<FinancialReport> => {
    try {
        const response = await api.post<FinancialReport>('/reports/', reportData);
        return response.data;
    } catch (error) {
        console.error('Error creating financial report:', error);
        throw error;
    }
};

export const getFinancialReports = async (): Promise<FinancialReport[]> => {
    try {
        const response = await api.get<FinancialReport[]>('/reports/');
        return response.data;
    } catch (error) {
        console.error('Error fetching financial reports:', error);
        throw error;
    }
};

export const getCompanyReports = async (companyId: number): Promise<FinancialReport[]> => {
    try {
        const response = await api.get<FinancialReport[]>(`/reports/company/${companyId}`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching reports for company ${companyId}:`, error);
        throw error;
    }
};

export const getLatestCompanyReport = async (companyId: number): Promise<FinancialReport> => {
    try {
        const response = await api.get<FinancialReport>(`/reports/company/${companyId}/latest`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching latest report for company ${companyId}:`, error);
        throw error;
    }
};

export const updateFinancialReport = async (
    reportId: number,
    reportData: FinancialReportCreate
): Promise<FinancialReport> => {
    try {
        const response = await api.put<FinancialReport>(`/reports/${reportId}`, reportData);
        return response.data;
    } catch (error) {
        console.error(`Error updating report ${reportId}:`, error);
        throw error;
    }
};

export const deleteFinancialReport = async (reportId: number): Promise<void> => {
    try {
        await api.delete(`/reports/${reportId}`);
    } catch (error) {
        console.error(`Error deleting report ${reportId}:`, error);
        throw error;
    }
};

// ─── Верификация отчётов аналитиком ─────────────────────────────────────────

/** Пометить отчёт как проверенный аналитиком. */
export const verifyReport = async (reportId: number): Promise<FinancialReport> => {
    const response = await api.post<FinancialReport>(`/reports/${reportId}/verify`);
    return response.data;
};

/** Снять отметку «проверен» — отчёт снова требует проверки. */
export const unverifyReport = async (reportId: number): Promise<FinancialReport> => {
    const response = await api.post<FinancialReport>(`/reports/${reportId}/unverify`);
    return response.data;
};

/** Список непроверенных отчётов (пагинация через skip/limit). */
export const getUnverifiedReports = async (
    params: { skip?: number; limit?: number; companyId?: number } = {}
): Promise<FinancialReport[]> => {
    const response = await api.get<FinancialReport[]>('/reports/unverified/list', {
        params: {
            skip: params.skip,
            limit: params.limit,
            company_id: params.companyId,
        },
    });
    return response.data;
};

/** Счётчики непроверенных отчётов по компаниям: { company_id: count }. */
export const getUnverifiedCountsByCompany = async (): Promise<Record<number, number>> => {
    const response = await api.get<Record<string, number>>('/reports/unverified/counts');
    const result: Record<number, number> = {};
    for (const [key, value] of Object.entries(response.data || {})) {
        result[Number(key)] = value;
    }
    return result;
};

// ─── AI-парсинг PDF ─────────────────────────────────────────────────────────

/** Статус настройки LLM на бэкенде — показывать ли UI загрузки PDF. */
export const getLlmStatus = async (): Promise<LlmStatus> => {
    const response = await api.get<LlmStatus>('/reports/ai/status');
    return response.data;
};

export interface ParsePdfRequest {
    companyId: number;
    fiscalYear: number;
    file: File;
    periodType?: 'annual' | 'quarterly' | 'semi_annual';
    fiscalQuarter?: number | null;
    accountingStandard?: 'IFRS' | 'RAS' | 'US_GAAP' | 'UK_GAAP' | 'OTHER';
    consolidated?: boolean;
    force?: boolean;
}

/**
 * Загрузить PDF и получить черновик отчёта (auto_extracted=true,
 * verified_by_analyst=false).
 *
 * Таймаут поднят до 5 минут — LLM может долго парсить большой PDF.
 */
export const parsePdfReport = async (req: ParsePdfRequest): Promise<ParsePdfResponse> => {
    const form = new FormData();
    form.append('company_id', String(req.companyId));
    form.append('fiscal_year', String(req.fiscalYear));
    form.append('period_type', req.periodType ?? 'annual');
    if (req.fiscalQuarter != null) {
        form.append('fiscal_quarter', String(req.fiscalQuarter));
    }
    form.append('accounting_standard', req.accountingStandard ?? 'IFRS');
    form.append('consolidated', String(req.consolidated ?? true));
    form.append('force', String(req.force ?? false));
    form.append('file', req.file);

    const response = await api.post<ParsePdfResponse>('/reports/parse-pdf', form, {
        timeout: 300_000,
    });
    return response.data;
};

export interface ComparePdfRequest {
    companyId: number;
    fiscalYear: number;
    file: File;
    periodType?: 'annual' | 'quarterly' | 'semi_annual';
    fiscalQuarter?: number | null;
    accountingStandard?: 'IFRS' | 'RAS' | 'US_GAAP' | 'UK_GAAP' | 'OTHER';
    consolidated?: boolean;
}

/**
 * Прогнать PDF через модель и СРАВНИТЬ с уже имеющимся в БД отчётом.
 * Ничего не пишется — возвращается только diff по полям.
 */
export const comparePdfReport = async (
    req: ComparePdfRequest
): Promise<ComparePdfResponse> => {
    const form = new FormData();
    form.append('company_id', String(req.companyId));
    form.append('fiscal_year', String(req.fiscalYear));
    form.append('period_type', req.periodType ?? 'annual');
    if (req.fiscalQuarter != null) {
        form.append('fiscal_quarter', String(req.fiscalQuarter));
    }
    form.append('accounting_standard', req.accountingStandard ?? 'IFRS');
    form.append('consolidated', String(req.consolidated ?? true));
    form.append('file', req.file);

    const response = await api.post<ComparePdfResponse>('/reports/compare-pdf', form, {
        timeout: 300_000,
    });
    return response.data;
};
