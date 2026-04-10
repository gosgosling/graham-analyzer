import { api } from './companies.api';
import { Bond } from '../types';

export const getBonds = async (): Promise<Bond[]> => {
    const response = await api.get<Bond[]>('/bonds/');
    return response.data;
};

export const getBondByFigi = async (figi: string): Promise<Bond> => {
    const response = await api.get<Bond>(`/bonds/${figi}`);
    return response.data;
};
