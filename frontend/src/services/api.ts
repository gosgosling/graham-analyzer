import axios from 'axios';
import { Security, Company, FinancialReport, FinancialReportCreate } from '../types';

const api = axios.create({
    baseURL: 'http://localhost:8000',
});

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

// ============ API для финансовых отчетов ============

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