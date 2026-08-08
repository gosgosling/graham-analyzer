import axios from 'axios';

// Тот же базовый адрес, что и у остальных модулей API.
const api = axios.create({ baseURL: 'http://localhost:8000' });
import type { HoldingNav, HoldingStake } from '../types';

/**
 * Оценка холдинга: доли, NAV и дисконт.
 *
 * Доли ведёт аналитик руками — доля владения в отчётности не раскрывается
 * в пригодном для расчёта виде, а непубличные активы требуют оценки.
 */

export interface HoldingStakeInput {
  name: string;
  share_pct: number;
  subsidiary_company_id?: number | null;
  manual_valuation?: number | null;
  valuation_note?: string | null;
}

export const getHoldingNav = async (companyId: number): Promise<HoldingNav> => {
  const response = await api.get<HoldingNav>(`/companies/${companyId}/holding/nav`);
  return response.data;
};

export const getHoldingStakes = async (companyId: number): Promise<HoldingStake[]> => {
  const response = await api.get<HoldingStake[]>(`/companies/${companyId}/holding/stakes`);
  return response.data;
};

export const addHoldingStake = async (
  companyId: number,
  payload: HoldingStakeInput,
): Promise<HoldingStake> => {
  const response = await api.post<HoldingStake>(`/companies/${companyId}/holding/stakes`, payload);
  return response.data;
};

export const updateHoldingStake = async (
  companyId: number,
  stakeId: number,
  payload: HoldingStakeInput,
): Promise<HoldingStake> => {
  const response = await api.put<HoldingStake>(
    `/companies/${companyId}/holding/stakes/${stakeId}`,
    payload,
  );
  return response.data;
};

export const deleteHoldingStake = async (companyId: number, stakeId: number): Promise<void> => {
  await api.delete(`/companies/${companyId}/holding/stakes/${stakeId}`);
};

export const setCorporateDebt = async (
  companyId: number,
  value: number | null,
): Promise<HoldingNav> => {
  const response = await api.patch<HoldingNav>(`/companies/${companyId}/holding/corporate-debt`, {
    corporate_center_net_debt: value,
  });
  return response.data;
};
