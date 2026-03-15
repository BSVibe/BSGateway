import type { AuditLog } from '../types/api';
import { api } from './client';

export const auditApi = {
  list: (tenantId: string, limit = 50, offset = 0) =>
    api.get<AuditLog[]>(`/tenants/${tenantId}/audit?limit=${limit}&offset=${offset}`),
};
