import type {
  EmbeddingSettings,
  Example,
  Intent,
  ReembedResponse,
  Rule,
  RuleCondition,
  TenantModel,
} from '../types/api';
import { intentsApi } from './intents';
import { rulesApi } from './rules';
import { tenantsApi } from './tenants';
import { api } from './client';

/**
 * RouteCard combines an Intent + Rule pair into a single conceptual unit
 * for the Notion Mail-style routing UI.
 *
 * - Non-default cards: have both intentId and ruleId, with the rule
 *   matching on `classified_intent == intentName`.
 * - Default cards: have only ruleId (intentId is null) and represent
 *   fallback rules with no intent pairing.
 */
export interface RouteCard {
  intentId: string | null;
  ruleId: string;
  description: string;
  targetModel: string;
  priority: number;
  isActive: boolean;
  isDefault: boolean;
  examples: Example[];
  createdAt: string;
}

export interface PresetSummary {
  name: string;
  description: string;
  intent_count: number;
  rule_count: number;
}

export interface PresetApplyResponse {
  preset_name: string;
  rules_created: number;
  intents_created: number;
  examples_created: number;
}

export interface CreateRouteInput {
  description: string;
  targetModel: string;
  examples?: string[];
}

/**
 * Slugify a description into a valid intent name.
 * Lowercase, alphanumeric + hyphens, trimmed.
 */
function slugify(text: string): string {
  const slug = text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
  return slug || `route-${Date.now()}`;
}

/**
 * Find the rule (if any) that pairs with a given intent name by matching
 * on a condition `{condition_type: "intent", field: "classified_intent",
 * operator: "eq", value: intentName}`.
 */
function findRuleForIntent(rules: Rule[], intentName: string): Rule | undefined {
  return rules.find((rule) =>
    (rule.conditions || []).some(
      (c: RuleCondition) =>
        c.condition_type === 'intent' &&
        c.field === 'classified_intent' &&
        c.operator === 'eq' &&
        c.value === intentName,
    ),
  );
}

function isIntentRule(rule: Rule): boolean {
  return (rule.conditions || []).some(
    (c: RuleCondition) =>
      c.condition_type === 'intent' && c.field === 'classified_intent',
  );
}

export const routesApi = {
  /**
   * List all RouteCards for a tenant by joining intents + rules.
   * Sorted by priority ascending; default rules pushed to the bottom.
   */
  list: async (tenantId: string): Promise<RouteCard[]> => {
    const [intents, rules] = await Promise.all([
      intentsApi.list(tenantId).catch((): Intent[] => []),
      rulesApi.list(tenantId).catch((): Rule[] => []),
    ]);

    const cards: RouteCard[] = [];
    const usedRuleIds = new Set<string>();

    // Pair intents with their matching rules
    for (const intent of intents) {
      const rule = findRuleForIntent(rules, intent.name);
      if (!rule) continue;
      usedRuleIds.add(rule.id);

      let examples: Example[] = [];
      try {
        examples = await intentsApi.listExamples(tenantId, intent.id);
      } catch {
        examples = [];
      }

      cards.push({
        intentId: intent.id,
        ruleId: rule.id,
        description: intent.description || intent.name,
        targetModel: rule.target_model,
        priority: rule.priority,
        isActive: rule.is_active && intent.is_active,
        isDefault: rule.is_default,
        examples,
        createdAt: rule.created_at,
      });
    }

    // Include default + non-intent rules as standalone cards
    for (const rule of rules) {
      if (usedRuleIds.has(rule.id)) continue;
      if (isIntentRule(rule)) continue; // intent rule with no matching intent — skip
      cards.push({
        intentId: null,
        ruleId: rule.id,
        description: rule.is_default
          ? 'Default fallback'
          : rule.name,
        targetModel: rule.target_model,
        priority: rule.priority,
        isActive: rule.is_active,
        isDefault: rule.is_default,
        examples: [],
        createdAt: rule.created_at,
      });
    }

    // Sort by priority asc, defaults last
    cards.sort((a, b) => {
      if (a.isDefault !== b.isDefault) return a.isDefault ? 1 : -1;
      return a.priority - b.priority;
    });

    return cards;
  },

  /**
   * Create a new RouteCard: creates an intent and a paired rule.
   */
  create: async (
    tenantId: string,
    input: CreateRouteInput,
  ): Promise<RouteCard> => {
    const description = input.description.trim();
    if (!description) throw new Error('Description is required');
    if (!input.targetModel.trim()) throw new Error('Target model is required');

    const name = slugify(description);
    const examples = (input.examples || []).map((e) => e.trim()).filter(Boolean);

    const intent = await intentsApi.create(tenantId, {
      name,
      description,
      examples,
    });

    // Compute next priority (lowest free slot among non-default rules).
    const existingRules = await rulesApi.list(tenantId).catch((): Rule[] => []);
    const nonDefault = existingRules.filter((r) => !r.is_default);
    const maxPriority = nonDefault.reduce(
      (max, r) => Math.max(max, r.priority),
      -1,
    );
    const nextPriority = maxPriority + 1;

    let createdRule: Rule;
    try {
      createdRule = await rulesApi.create(tenantId, {
        name,
        priority: nextPriority,
        target_model: input.targetModel.trim(),
        is_default: false,
        conditions: [
          {
            condition_type: 'intent',
            field: 'classified_intent',
            operator: 'eq',
            value: name,
          },
        ],
      });
    } catch (err) {
      // Rollback intent creation on rule failure
      await intentsApi.delete(tenantId, intent.id).catch(() => undefined);
      throw err;
    }

    let createdExamples: Example[] = [];
    try {
      createdExamples = await intentsApi.listExamples(tenantId, intent.id);
    } catch {
      createdExamples = [];
    }

    return {
      intentId: intent.id,
      ruleId: createdRule.id,
      description,
      targetModel: createdRule.target_model,
      priority: createdRule.priority,
      isActive: createdRule.is_active && intent.is_active,
      isDefault: false,
      examples: createdExamples,
      createdAt: createdRule.created_at,
    };
  },

  /**
   * Delete a RouteCard: removes both the rule and its paired intent (if any).
   */
  delete: async (
    tenantId: string,
    intentId: string | null,
    ruleId: string,
  ): Promise<void> => {
    await rulesApi.delete(tenantId, ruleId);
    if (intentId) {
      await intentsApi.delete(tenantId, intentId).catch(() => undefined);
    }
  },

  updateModel: (tenantId: string, ruleId: string, model: string) =>
    rulesApi.update(tenantId, ruleId, { target_model: model }),

  toggleActive: (tenantId: string, ruleId: string, isActive: boolean) =>
    (rulesApi.update as (
      tid: string,
      id: string,
      data: Record<string, unknown>,
    ) => Promise<Rule>)(tenantId, ruleId, { is_active: isActive }),

  addExample: (tenantId: string, intentId: string, text: string) =>
    intentsApi.addExample(tenantId, intentId, text),

  removeExample: (tenantId: string, intentId: string, exampleId: string) =>
    intentsApi.deleteExample(tenantId, intentId, exampleId),

  listModels: (tenantId: string): Promise<TenantModel[]> =>
    tenantsApi.listModels(tenantId),

  listPresets: () => api.get<PresetSummary[]>('/presets'),

  applyPreset: (
    tenantId: string,
    presetName: string,
    modelMapping: Record<string, string>,
  ) =>
    api.post<PresetApplyResponse>(`/tenants/${tenantId}/presets/apply`, {
      preset_name: presetName,
      model_mapping: modelMapping,
    }),

  // ---- Per-tenant embedding settings ----

  getEmbeddingSettings: (tenantId: string) =>
    api.get<EmbeddingSettings | null>(`/tenants/${tenantId}/embedding-settings`),

  putEmbeddingSettings: (tenantId: string, settings: EmbeddingSettings) =>
    api.put<EmbeddingSettings>(`/tenants/${tenantId}/embedding-settings`, settings),

  deleteEmbeddingSettings: (tenantId: string) =>
    api.delete<void>(`/tenants/${tenantId}/embedding-settings`),

  reembed: (tenantId: string) =>
    api.post<ReembedResponse>(`/tenants/${tenantId}/intents/reembed`, {}),

  // ---- Default fallback rule ----
  //
  // The rule engine returns the default rule when no other rule matches.
  // We model "the default" as a single is_default=true rule with no conditions
  // and a fixed name (`__default__`). Setting it creates the rule if missing,
  // or updates the target_model in place.

  getDefaultRule: async (tenantId: string): Promise<Rule | null> => {
    const rules = await rulesApi.list(tenantId);
    return rules.find((r) => r.is_default) || null;
  },

  setDefaultModel: async (tenantId: string, targetModel: string): Promise<Rule> => {
    const existing = await routesApi.getDefaultRule(tenantId);
    if (existing) {
      return (rulesApi.update as (
        tid: string,
        id: string,
        data: Record<string, unknown>,
      ) => Promise<Rule>)(tenantId, existing.id, { target_model: targetModel });
    }
    // Pick a high priority number (lowest precedence) so it sits at the bottom
    const allRules = await rulesApi.list(tenantId);
    const maxPriority = allRules.reduce((m, r) => Math.max(m, r.priority), -1);
    return rulesApi.create(tenantId, {
      name: '__default__',
      priority: maxPriority + 1000, // sit far below intent rules
      is_default: true,
      target_model: targetModel,
      conditions: [],
    });
  },

  clearDefaultModel: async (tenantId: string): Promise<void> => {
    const existing = await routesApi.getDefaultRule(tenantId);
    if (existing) await rulesApi.delete(tenantId, existing.id);
  },

  // ---- Priority reordering ----

  reorderRoutes: async (
    tenantId: string,
    orderedRuleIds: string[],
  ): Promise<void> => {
    // Backend takes a {ruleId: priority} map. Re-number from 0 in the given order.
    const priorities: Record<string, number> = {};
    orderedRuleIds.forEach((id, index) => {
      priorities[id] = index;
    });
    await rulesApi.reorder(tenantId, priorities);
  },
};
