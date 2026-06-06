import axios from 'axios';
import { Security, Company, CompaniesSyncStatus, CompaniesSyncResponse } from '../types';

const api = axios.create({
    baseURL: 'http://localhost:8000',
});

export { api };

export const getSecurities = async (): Promise<Security[]> => {
    try {
        const response = await api.get<Security[]>('/securities/');
        return response.data;
    } catch (error) {
        console.error('Error fetching securities:', error);
        throw error;
    }
};

export const getCompanies = async (): Promise<Company[]> => {
    try {
        const response = await api.get<Company[]>('/companies/');
        return response.data;
    } catch (error) {
        console.error('Error fetching companies:', error);
        throw error;
    }
};

export const getCompanyById = async (companyId: number): Promise<Company> => {
    try {
        const response = await api.get<Company>(`/companies/${companyId}`);
        return response.data;
    } catch (error) {
        console.error(`Error fetching company ${companyId}:`, error);
        throw error;
    }
};

export const getCompaniesSyncStatus = async (): Promise<CompaniesSyncStatus> => {
    const response = await api.get<CompaniesSyncStatus>('/companies/sync/status');
    return response.data;
};

export const syncCompaniesFromTinkoff = async (): Promise<CompaniesSyncResponse> => {
    const response = await api.post<CompaniesSyncResponse>('/companies/sync');
    return response.data;
};

/**
 * Переключить флажок «инструмент — привилегированные акции» вручную в
 * карточке компании. Имеет приоритет над авто-детектом при последующей
 * синхронизации из T-Invest API.
 */
export const updateCompanyPreferredShare = async (
    companyId: number,
    isPreferredShare: boolean,
): Promise<Company> => {
    const response = await api.patch<Company>(
        `/companies/${companyId}/preferred-share`,
        { is_preferred_share: isPreferredShare },
    );
    return response.data;
};
