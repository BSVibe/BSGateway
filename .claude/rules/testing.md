---
description: Testing rules and coverage requirements for BSage
---

# Testing Rules

## CRITICAL: Tests Are Mandatory

**NEVER commit code without tests.**

**Minimum coverage: 80%**

### Unit Tests Required

Every module MUST have:
- Unit tests for core business logic
- Coverage >= 80%
- Mock all external dependencies

```python
# bsage/tests/test_skill_loader.py
import pytest
from pathlib import Path
from bsage.core.skill_loader import SkillLoader, SkillMeta

@pytest.mark.asyncio
async def test_load_skill_parses_yaml(tmp_path):
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "skill.yaml").write_text(
        "name: test-skill\nversion: 1.0.0\ncategory: process\n"
        "is_dangerous: false\ndescription: Test skill\n"
    )
    loader = SkillLoader(tmp_path)
    registry = await loader.load_all()
    assert "test-skill" in registry
    assert registry["test-skill"].category == "process"
```

### Mock External APIs

**ALWAYS mock**:
- LLM API (litellm) — `unittest.mock.patch("bsage.core.llm.litellm")`
- External APIs — `unittest.mock.AsyncMock`
- APScheduler — `unittest.mock.MagicMock`
- File system (Vault) — `tmp_path` fixture

**NEVER call real APIs in tests.**

```python
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.fixture
def mock_llm():
    with patch("bsage.core.llm.litellm") as mock:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Processed response"
        mock_response.choices[0].message.tool_calls = None
        mock.acompletion = AsyncMock(return_value=mock_response)
        yield mock

@pytest.fixture
def mock_context(tmp_path):
    context = MagicMock()
    context.logger = MagicMock()
    context.credentials = MagicMock()
    context.garden = AsyncMock()
    context.garden.write_seed = AsyncMock()
    context.garden.write_garden = AsyncMock()
    context.garden.write_action = AsyncMock()
    context.llm = AsyncMock()
    context.config = MagicMock()
    return context
```

### Test Organization

```
bsage/
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_skill_loader.py
│   ├── test_skill_runner.py
│   ├── test_skill_context.py
│   ├── test_agent_loop.py
│   ├── test_scheduler.py
│   ├── test_safe_mode.py
│   ├── test_credential_store.py
│   ├── test_garden_writer.py
│   └── test_vault.py

tests/                          # Root-level
└── fixtures/                   # Test data
    ├── sample_skill/
    │   ├── skill.yaml
    │   └── skill.py
    └── sample_vault/
        ├── seeds/
        └── garden/
```

### Code Quality Checks

**ALWAYS run before commit:**

```bash
# Lint check
ruff check bsage/

# Format check
ruff format --check bsage/
```

### Running Tests

Before every commit:

```bash
# Code quality (MUST pass)
ruff check bsage/

# Unit tests with coverage
pytest bsage/tests/ --cov=bsage --cov-fail-under=80

# All tests
pytest --cov=bsage --cov-fail-under=80
```

### CI/CD Gate

**Tests MUST pass in CI before merge.**

All PRs require:
- [ ] `ruff check` passing (no lint errors)
- [ ] Unit tests passing
- [ ] Coverage >= 80%
- [ ] No warnings or errors
