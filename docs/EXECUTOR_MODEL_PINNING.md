# Pinning an LLM model to an agent CLI executor

When a worker registers, BSGateway auto-creates one routable model per
detected capability (`claude_code` / `codex` / `opencode`) with
`litellm_model = executor/<type>`. Routing to that base model runs the
agent CLI with **its local default LLM model**.

To pin a specific LLM model, register an additional model that points at
the same worker + executor type but carries an `ai_model` param. The
`ai_model` string flows down to the worker and becomes a CLI flag
(`claude --model`, `codex exec --model`) or the opencode message-body
`providerID`/`modelID` pair.

## Recipe

Register pinned variants via the `bsgateway_models_register` MCP tool (or
`POST /api/v1/models/`). Everything in `config` other than
`litellm_model` / `api_base` lands in the model's `extra_params`:

```jsonc
// codex pinned to gpt-5-codex
{
  "name": "codex-opus",
  "provider": "executor",
  "config": {
    "litellm_model": "executor/codex",
    "worker_id": "<the worker uuid>",
    "executor_type": "codex",
    "ai_model": "openai/gpt-5-codex"
  }
}
```

```jsonc
// claude_code pinned to Opus
{
  "name": "claude-opus",
  "provider": "executor",
  "config": {
    "litellm_model": "executor/claude_code",
    "worker_id": "<the worker uuid>",
    "executor_type": "claude_code",
    "ai_model": "claude-opus-4-7"
  }
}
```

Register as many variants as you need (e.g. `codex-opus` + `codex-sonnet`),
each with a distinct `name` and a different `ai_model`. Routing rules
target whichever `name` you want.

## `ai_model` format

- **claude_code / codex** — passed verbatim as `--model <ai_model>`. Use
  whatever the CLI accepts (`sonnet`, `opus`, a full model id).
- **opencode** — **must** be `provider/model`. opencode's API
  (`SessionPromptData.model`) requires a structured
  `{providerID, modelID}` pair, so `anthropic/claude-opus-4-7` is split
  into `providerID=anthropic`, `modelID=claude-opus-4-7`. A bare string
  with no `/` cannot be expressed and is dropped — opencode then uses
  its own configured default. Always use the slash form for opencode.

Omitting `ai_model` (e.g. the auto-created base model) ⇒ the CLI uses its
local default — fully back-compatible.
