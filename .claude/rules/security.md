---
description: Security rules for BSage
---

# Security Rules

## CRITICAL: Credential, Data, and Safety Security

### 1. Environment Variables

**NEVER commit secrets to git.**

**ALWAYS use .env files (gitignored):**

```python
# Correct
from bsage.core.config import settings
# settings.llm_api_key is auto-loaded from .env via pydantic-settings

# Wrong
API_KEY = "sk-ant-..."  # NEVER hardcode credentials!
```

**Provide .env.example (committed, no real secrets):**

```bash
# .env.example (committed)
LLM_MODEL=anthropic/claude-sonnet-4-20250514
LLM_API_KEY=
LLM_API_BASE=
VAULT_PATH=./vault
SKILLS_DIR=./skills
SAFE_MODE=true

# .env (gitignored, actual secrets)
LLM_API_KEY=sk-ant-real-key-here
```

### 2. Service Credentials

**NEVER log or expose authentication tokens.**

```python
# Correct
logger.info("credential_loaded", service=name)

# Wrong
logger.info(f"Authenticated with token: {token}")  # NO!
```

**Service credentials stored in `.credentials/` directory (gitignored) via CredentialStore.
SkillRunner auto-injects resolved credentials into `context.credentials` dict:**

```python
# Correct - credentials auto-injected as dict by SkillRunner
creds = context.credentials  # dict[str, Any]

# Wrong - store tokens in plain text
with open("tokens.txt", "w") as f:
    f.write(f"{service}:{token}")  # NEVER!
```

### 3. API Keys in Logs

**NEVER log API keys or secrets.**

```python
# Correct
logger.info("llm_call", model=settings.llm_model)

# Wrong
logger.info(f"Using API key: {settings.llm_api_key}")  # NO!
```

### 4. Safe Mode

**BSage safety model:**

**Layer 1: Installation gate** — only installed Plugins/Skills can run; anything not installed cannot execute.

**Layer 2: SafeModeGuard**
```python
# Dangerous plugins require user approval before execution
if danger_fn(plugin_name):
    approved = await interface.request_approval(plugin_meta)
    if not approved:
        raise SafeModeError(f"User rejected execution of '{plugin_meta.name}'")
```

`is_dangerous` is **auto-detected** by `DangerAnalyzer` via AST static analysis — never declared manually.
Markdown Skills are structurally always safe (no external calls possible).

**NEVER bypass SafeModeGuard. NEVER skip the danger check.**

### 5. Vault Data Boundary

**Data must never leave the 2nd Brain (Vault).**

```python
# Correct — read/write only within the Vault
note_path = settings.vault_path / "garden" / "ideas" / f"{slug}.md"
if not note_path.resolve().is_relative_to(settings.vault_path.resolve()):
    raise ValueError("Path traversal detected — cannot access outside Vault")

# Wrong — sends Vault data to an external service
requests.post("https://external.api/data", json=vault_data)  # NEVER!
```

**Exception: intentional sync through Output Plugins only (git-output, s3-output, etc.)**

### 6. Input Validation

**Validate all external inputs:**

```python
# Plugin/Skill name validation
import re

def validate_plugin_name(name: str) -> str:
    if not re.match(r'^[a-z][a-z0-9-]*$', name):
        raise ValueError(f"Invalid name: {name}. Use lowercase alphanumeric with hyphens.")
    return name
```

### 7. Temporary File Cleanup

**ALWAYS clean up temporary files after processing.**

```python
# Correct
try:
    await skill_runner.run(skill_meta, context)
finally:
    if not keep_tmp:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# Wrong - leave temp files
pass  # tmp files remain
```

### 8. Secure Defaults

**Principle of least privilege:**

- Safe mode ON by default (`SAFE_MODE=true`)
- Only installed Plugins/Skills can execute
- API keys scoped to minimum permissions
- No `shell=True` in subprocess calls
- Plugins access the outside world only through the `context` object

### 9. Error Messages

**NEVER expose credentials in error messages:**

```python
# Correct (user-facing)
raise CredentialNotFoundError("No credentials for 'google-calendar'")

# Correct (logs)
logger.error("credential_load_failed", service=name, exc_info=True)

# Wrong
raise Exception(f"Auth failed with token {token}")  # Exposes secrets!
```

## Verification Checklist

Before every commit:
- [ ] No hardcoded credentials (API keys, tokens)
- [ ] .env.example provided
- [ ] No secrets in logs
- [ ] .credentials/ in .gitignore
- [ ] SafeModeGuard not bypassed
- [ ] Vault path traversal prevented
- [ ] Temp file cleanup implemented
- [ ] No `shell=True` in subprocess calls
- [ ] DangerAnalyzer correctly classifies all Plugins (not manually overridden)
