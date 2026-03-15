import type { UsageResponse } from '../types/api';
import { api } from './client';

export const usageApi = {
  get: (tenantId: string, period = 'day', from?: string, to?: string) => {
    const params = new URLSearchParams({ period });
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    return api.get<UsageResponse>(`/tenants/${tenantId}/usage?${params}`);
  },
};
