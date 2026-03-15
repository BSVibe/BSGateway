import type { Rule, RuleCreate, RuleTestRequest, RuleTestResponse } from '../types/api';
import { api } from './client';

export const rulesApi = {
  list: (tenantId: string) =>
    api.get<Rule[]>(`/tenants/${tenantId}/rules`),
  get: (tenantId: string, ruleId: string) =>
    api.get<Rule>(`/tenants/${tenantId}/rules/${ruleId}`),
  create: (tenantId: string, data: RuleCreate) =>
    api.post<Rule>(`/tenants/${tenantId}/rules`, data),
  update: (tenantId: string, ruleId: string, data: Partial<RuleCreate>) =>
    api.patch<Rule>(`/tenants/${tenantId}/rules/${ruleId}`, data),
  delete: (tenantId: string, ruleId: string) =>
    api.delete<void>(`/tenants/${tenantId}/rules/${ruleId}`),
  reorder: (tenantId: string, priorities: Record<string, number>) =>
    api.post<void>(`/tenants/${tenantId}/rules/reorder`, { priorities }),
  test: (tenantId: string, data: RuleTestRequest) =>
    api.post<RuleTestResponse>(`/tenants/${tenantId}/rules/test`, data),
};
