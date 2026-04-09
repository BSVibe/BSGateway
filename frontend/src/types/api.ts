export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TenantCreate {
  name: string;
  slug: string;
  settings?: Record<string, unknown>;
}

export interface TenantModel {
  id: string;
  tenant_id: string;
  model_name: string;
  provider: string;
  litellm_model: string;
  api_base: string | null;
  is_active: boolean;
  extra_params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TenantModelCreate {
  model_name: string;
  litellm_model: string;
  api_key?: string;
  api_base?: string;
  extra_params?: Record<string, unknown>;
}

export interface RuleCondition {
  id: string;
  condition_type: string;
  field: string;
  operator: string;
  value: unknown;
  negate: boolean;
}

export interface Rule {
  id: string;
  tenant_id: string;
  name: string;
  priority: number;
  is_active: boolean;
  is_default: boolean;
  target_model: string;
  conditions: RuleCondition[];
  created_at: string;
  updated_at: string;
}

export interface RuleCreate {
  name: string;
  priority: number;
  is_default?: boolean;
  target_model: string;
  conditions?: ConditionCreate[];
}

export interface ConditionCreate {
  condition_type: string;
  field: string;
  operator: string;
  value: unknown;
  negate?: boolean;
}

export interface RuleTestRequest {
  messages: Array<{ role: string; content: string }>;
  model?: string;
}

export interface RuleTestResponse {
  matched_rule: { id: string; name: string; priority: number } | null;
  target_model: string | null;
  evaluation_trace: Record<string, unknown>[];
  context: Record<string, unknown>;
}

export interface Intent {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  threshold: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface IntentCreate {
  name: string;
  description?: string;
  threshold?: number;
  examples?: string[];
}

export interface Example {
  id: string;
  intent_id: string;
  text: string;
  created_at: string;
}

export interface EmbeddingSettings {
  model: string;
  api_base: string | null;
  timeout: number;
  max_input_length: number;
}

export interface ReembedResponse {
  refreshed: number;
  failed: number;
  model: string;
}

export interface ApiKeyCreated {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  raw_key: string;
  scopes: string[];
  created_at: string;
}

export interface ApiKeyInfo {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreate {
  name: string;
  scopes?: string[];
  expires_in_days?: number;
}

export interface AuditLog {
  id: string;
  tenant_id: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ModelUsage {
  requests: number;
  tokens: number;
}

export interface DailyUsage {
  date: string;
  requests: number;
  tokens: number;
}

export interface UsageResponse {
  total_requests: number;
  total_tokens: number;
  by_model: Record<string, ModelUsage>;
  by_rule: Record<string, number>;
  daily_breakdown: DailyUsage[];
}
