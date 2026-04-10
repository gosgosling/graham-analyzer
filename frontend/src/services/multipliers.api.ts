import { api } from './companies.api';
import { MultiplierRecord, CurrentMultipliers } from '../types';

export const getCompanyCurrentMultipliers = async (
    companyId: number,
    price?: number,
): Promise<CurrentMultipliers> => {
    const params = price !== undefined ? { price } : {};
    const response = await api.get<CurrentMultipliers>(
        `/companies/${companyId}/multipliers/current`,
        { params },
    );
    return response.data;
};

export const getCompanyMultipliersHistory = async (
    companyId: number,
    type?: 'report_based' | 'current' | 'daily',
    limit = 365,
): Promise<MultiplierRecord[]> => {
    const params: Record<string, string | number> = { limit };
    if (type) params['type'] = type;
    const response = await api.get<MultiplierRecord[]>(
        `/companies/${companyId}/multipliers/history`,
        { params },
    );
    return response.data;
};

export const refreshCompanyMultipliers = async (
    companyId: number,
    saveToCache = true,
): Promise<{ company_id: number; ticker: string; price: number | null; success: boolean }> => {
    const response = await api.post(
        `/companies/${companyId}/multipliers/refresh`,
        null,
        { params: { save_to_cache: saveToCache } },
    );
    return response.data;
};

export const getReportMultipliers = async (reportId: number): Promise<MultiplierRecord> => {
    const response = await api.get<MultiplierRecord>(`/reports/${reportId}/multipliers`);
    return response.data;
};
