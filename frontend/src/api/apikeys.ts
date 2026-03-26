import type { ApiKeyCreated, ApiKeyCreate, ApiKeyInfo } from '../types/api';
import { api } from './client';

export const apiKeysApi = {
  list: (tenantId: string) =>
    api.get<ApiKeyInfo[]>(`/tenants/${tenantId}/api-keys`),
  create: (tenantId: string, data: ApiKeyCreate) =>
    api.post<ApiKeyCreated>(`/tenants/${tenantId}/api-keys`, data),
  revoke: (tenantId: string, keyId: string) =>
    api.delete<void>(`/tenants/${tenantId}/api-keys/${keyId}`),
};
