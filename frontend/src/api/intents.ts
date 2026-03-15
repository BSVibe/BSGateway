import type { Intent, IntentCreate, Example } from '../types/api';
import { api } from './client';

export const intentsApi = {
  list: (tenantId: string) =>
    api.get<Intent[]>(`/tenants/${tenantId}/intents`),
  get: (tenantId: string, intentId: string) =>
    api.get<Intent>(`/tenants/${tenantId}/intents/${intentId}`),
  create: (tenantId: string, data: IntentCreate) =>
    api.post<Intent>(`/tenants/${tenantId}/intents`, data),
  update: (tenantId: string, intentId: string, data: Partial<IntentCreate>) =>
    api.patch<Intent>(`/tenants/${tenantId}/intents/${intentId}`, data),
  delete: (tenantId: string, intentId: string) =>
    api.delete<void>(`/tenants/${tenantId}/intents/${intentId}`),

  // Examples
  listExamples: (tenantId: string, intentId: string) =>
    api.get<Example[]>(`/tenants/${tenantId}/intents/${intentId}/examples`),
  addExample: (tenantId: string, intentId: string, text: string) =>
    api.post<Example>(`/tenants/${tenantId}/intents/${intentId}/examples`, { text }),
  deleteExample: (tenantId: string, intentId: string, exampleId: string) =>
    api.delete<void>(`/tenants/${tenantId}/intents/${intentId}/examples/${exampleId}`),
};
