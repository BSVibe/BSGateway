---
description: Architecture rules and critical design decisions for BSage
---

# Architecture Rules

## CRITICAL: Core Architectural Decisions

These decisions are final. Do NOT deviate without explicit approval.

### 1. Python-Only, uv for Package Management

**All code MUST be Python 3.11+.**

**NEVER use requirements.txt. Use pyproject.toml + uv only:**

```toml
# pyproject.toml
[project]
dependencies = [
    "pydantic-settings>=2.0.0",
    "structlog>=23.0.0",
    "pyyaml>=6.0",
    "litellm>=1.0.0",
    "apscheduler>=3.10.0",
    "click>=8.0.0",
]
```

Why: Single source of truth, uv is faster and more reliable.

### 2. Type Hints Required

**ALL public functions MUST have type hints.**

```python
# Correct
async def load_skill(skill_dir: Path) -> SkillMeta:
    pass

# Wrong
async def load_skill(skill_dir):  # NO!
    pass
```

### 3. pydantic-settings for Configuration

**ALWAYS use pydantic-settings for environment variable management.**

```python
# Correct
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    llm_model: str = "anthropic/claude-sonnet-4-20250514"  # litellm provider/model format
    llm_api_key: str = ""
    llm_api_base: str | None = None       # e.g. http://localhost:11434 for Ollama
    vault_path: Path = Path("./vault")
    skills_dir: Path = Path("./skills")
    safe_mode: bool = True

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()  # Auto-validates at startup

# Wrong
import os
api_key = os.getenv('LLM_API_KEY')  # No validation, no type safety
```

### 4. structlog for Logging

**ALWAYS use structlog for structured JSON logging.**

```python
# Correct
import structlog
logger = structlog.get_logger(__name__)

logger.info("skill_executed",
            skill_name="garden-writer",
            duration_s=1.2,
            notes_written=3)

# Wrong
import logging
logging.info("Skill executed")  # Unstructured, hard to parse
```

### 5. Async Throughout

**ALL I/O operations MUST be async.**

```python
# Correct
async def run_skill(skill_meta: SkillMeta, context: SkillContext) -> dict:
    result = await execute_skill(skill_meta, context)
    await garden_writer.write_action(skill_meta.name, result)
    return result

# Wrong
def run_skill(skill_meta):  # Blocks event loop!
    pass
```

### 6. Metadata Definitions in Files

**ALL Plugin/Skill metadata MUST be declared in their respective files, NOT hardcoded in Python source.**

- Plugins: metadata via `@plugin` decorator in `plugins/name/plugin.py`
- Skills: metadata via YAML frontmatter in `skills/name.md`; Markdown body is the system prompt

```python
# Correct
meta = plugin_loader.get("telegram-input")  # loaded from plugin.py @plugin decorator

# Wrong
plugin_config = {"name": "telegram-input", "category": "input"}  # Hardcoded
```

### 7. Dataclasses for Internal Data

**Use dataclasses for structured internal data, NOT dict.**

```python
# Correct
from dataclasses import dataclass, field

@dataclass
class PluginMeta:
    name: str
    version: str
    category: str
    description: str
    trigger: dict | None = None

# Wrong
plugin = {"name": "...", "category": "..."}  # No type safety
```

### 8. PYTHONPATH Configuration

**NEVER use sys.path.insert() for imports.**

```python
# Wrong - sys.path manipulation (NO!)
import sys
sys.path.insert(0, "/workspace")

# Correct - PYTHONPATH is set in devcontainer / editable install handles it
from bsage.core.config import settings
```

### 9. Output Path via Environment

**ALWAYS configure Vault/output/tmp paths via environment variables.**

```python
# Correct - configurable
settings.vault_path / "garden" / "ideas" / f"{slug}.md"

# Wrong - hardcoded path
Path("/Users/me/obsidian/vault") / filename
```

### 10. Temporary Files in TMP_DIR

**ALL temporary files go in `TMP_DIR`.**

```python
# Correct
tmp_dir = settings.tmp_dir / skill_name
tmp_dir.mkdir(parents=True, exist_ok=True)

# Wrong
Path("/tmp") / skill_name  # Ignores configured tmp path
```

## Verification Checklist

Before implementing ANY module:
- [ ] Python 3.11+ with type hints on all public functions
- [ ] pyproject.toml + uv (no requirements.txt)
- [ ] pydantic-settings for config (no raw os.getenv)
- [ ] structlog for logging (not print or logging.info)
- [ ] async for all I/O operations
- [ ] Plugin/Skill metadata declared in their respective files (not hardcoded)
- [ ] Dataclasses for internal data structures
- [ ] No sys.path.insert()
- [ ] Vault/output/tmp paths from settings

### Git Commit Rules

**NEVER include Co-Authored-By in commit messages.**

Commit message format:
```
type(scope): short description

- bullet points for details
- no Co-Authored-By line
```

Example:
```bash
git commit -m "feat(core): add SkillLoader with yaml parsing

- Scan skills/ directory for skill.yaml files
- Parse metadata into SkillMeta dataclass
- Register skills in memory registry"
```
