import type { Tenant, TenantCreate, TenantModel, TenantModelCreate } from '../types/api';
import { api } from './client';

export const tenantsApi = {
  list: (limit = 50, offset = 0) =>
    api.get<Tenant[]>(`/tenants?limit=${limit}&offset=${offset}`),
  get: (id: string) => api.get<Tenant>(`/tenants/${id}`),
  create: (data: TenantCreate) => api.post<Tenant>('/tenants', data),
  update: (id: string, data: Partial<TenantCreate>) =>
    api.patch<Tenant>(`/tenants/${id}`, data),
  deactivate: (id: string) => api.delete<void>(`/tenants/${id}`),

  // Models
  listModels: (tenantId: string) =>
    api.get<TenantModel[]>(`/tenants/${tenantId}/models`),
  getModel: (tenantId: string, modelId: string) =>
    api.get<TenantModel>(`/tenants/${tenantId}/models/${modelId}`),
  createModel: (tenantId: string, data: TenantModelCreate) =>
    api.post<TenantModel>(`/tenants/${tenantId}/models`, data),
  updateModel: (tenantId: string, modelId: string, data: Partial<TenantModelCreate>) =>
    api.patch<TenantModel>(`/tenants/${tenantId}/models/${modelId}`, data),
  deleteModel: (tenantId: string, modelId: string) =>
    api.delete<void>(`/tenants/${tenantId}/models/${modelId}`),
};
