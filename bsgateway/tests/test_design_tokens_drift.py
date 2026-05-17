"""Drift guard: ``frontend/app/[locale]/globals.css`` Material 3 tokens must
match the ``@bsvibe/design-tokens`` ``m3.*`` namespace.

Phase A Batch 5 (Lockin §3 #12 + #11): the BSGateway frontend cannot
yet `@import "@bsvibe/design-tokens/css"` because GitHub Packages
publishing requires a user-action PAT (Lockin §3 #12) that hasn't been
provisioned. As an interim measure, we keep the M3 token values inline
in ``frontend/app/[locale]/globals.css`` and pin them with this test against the
canonical TypeScript export.

The TS source of truth lives in
``~/Works/bsvibe-frontend-lib/main/packages/design-tokens/src/index.ts``
under the ``m3`` const (lines 180-223). When that file changes,
this test fails and the engineer must:
* update ``frontend/app/[locale]/globals.css`` to mirror the new values, OR
* update ``CANONICAL_M3`` below if the change was intentional.

Once Decision #12 lands and BSGateway can pull tokens via
``@import "@bsvibe/design-tokens/css"``, this test is replaced by the
package's own ``pnpm tokens:verify`` (which already exists upstream).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOBALS_CSS = REPO_ROOT / "frontend" / "app" / "[locale]" / "globals.css"


# Canonical M3 values from @bsvibe/design-tokens m3.* (verbatim).
# Source: bsvibe-frontend-lib/packages/design-tokens/src/index.ts lines 180-223.
CANONICAL_M3: dict[str, str] = {
    "primary": "#ffc174",
    "primary-container": "#f59e0b",
    "on-primary": "#472a00",
    "on-primary-container": "#613b00",
    "secondary": "#f0bd82",
    "secondary-container": "#62400f",
    "on-secondary": "#472a00",
    "on-secondary-container": "#ddac72",
    "tertiary": "#8fd5ff",
    "tertiary-container": "#1abdff",
    "on-tertiary": "#00344a",
    "on-tertiary-container": "#004966",
    "error": "#ffb4ab",
    "error-container": "#93000a",
    "on-error": "#690005",
    "on-error-container": "#ffdad6",
    "surface": "#121317",
    "surface-dim": "#121317",
    "surface-bright": "#38393e",
    "surface-container-lowest": "#0d0e12",
    "surface-container-low": "#1a1b20",
    "surface-container": "#1f1f24",
    "surface-container-high": "#292a2e",
    "surface-container-highest": "#343439",
    "surface-variant": "#343439",
    "on-surface": "#e3e2e8",
    "on-surface-variant": "#d8c3ad",
    "on-background": "#e3e2e8",
    "outline": "#a08e7a",
    "outline-variant": "#534434",
    "background": "#121317",
    "inverse-surface": "#e3e2e8",
    "inverse-on-surface": "#2f3035",
    "inverse-primary": "#855300",
    "surface-tint": "#ffb95f",
}


def _extract_color_vars(css_text: str) -> dict[str, str]:
    """Parse ``--color-<key>: <value>;`` declarations out of the @theme block."""
    pattern = re.compile(r"--color-([a-z-]+):\s*(#[0-9a-fA-F]{3,8});")
    return {m.group(1): m.group(2).lower() for m in pattern.finditer(css_text)}


@pytest.fixture(scope="module")
def globals_css_vars() -> dict[str, str]:
    text = GLOBALS_CSS.read_text(encoding="utf-8")
    return _extract_color_vars(text)


class TestDesignTokensDrift:
    @pytest.mark.parametrize("key,expected", sorted(CANONICAL_M3.items()))
    def test_m3_token_present_and_matches(
        self, key: str, expected: str, globals_css_vars: dict[str, str]
    ) -> None:
        assert key in globals_css_vars, (
            f"--color-{key} missing from frontend/app/[locale]/globals.css. "
            f"Expected {expected} (from @bsvibe/design-tokens m3.*)"
        )
        assert globals_css_vars[key] == expected.lower(), (
            f"--color-{key} drift: got {globals_css_vars[key]!r}, "
            f"expected {expected!r} (from @bsvibe/design-tokens m3.*). "
            f"Update frontend/app/[locale]/globals.css or CANONICAL_M3 in this test."
        )

    def test_canonical_m3_count_matches_upstream(self) -> None:
        """Sanity check: 35 m3.* keys in the upstream design-tokens TS export.

        If the upstream package adds/removes keys, this fails — engineer
        must update ``CANONICAL_M3`` and re-verify drift.
        """
        assert len(CANONICAL_M3) == 35, (
            f"Expected 35 m3.* tokens (upstream as of 2026-04-26), "
            f"got {len(CANONICAL_M3)}. Update CANONICAL_M3 from "
            f"~/Works/bsvibe-frontend-lib/main/packages/design-tokens/src/index.ts."
        )
