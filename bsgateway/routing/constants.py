"""Named numeric constants for the routing pipeline (audit M13).

The pre-fix codebase scattered three magic numbers across hot paths.
Centralising them here makes them:

* discoverable — `git grep WORDS_TO_TOKENS_RATIO` returns every call site
* tunable — operators can change the constant in one place to re-evaluate
  routing behaviour without combing through call sites
* test-pinnable — assertions live alongside the value so accidental
  drift is caught at CI time

Promote any of these to environment-driven settings only when there is
a real per-deploy reason; otherwise keep them as in-code constants.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Auto-routing blend weights
# ---------------------------------------------------------------------------
# When BSNexus passes ``X-BSNexus-Complexity-Hint`` the router blends the
# header-supplied score with the local classifier output:
#
#     blended = (CLASSIFIER * classifier_score) + (HINT * complexity_hint)
#
# Both weights MUST sum to 1.0 so the result stays in the [0, 100] tier
# domain. The 70/30 split biases toward the local classifier (which sees
# the actual prompt text) while still letting upstream callers nudge the
# decision when they have task-level context the classifier can't.
CLASSIFIER_BLEND_WEIGHT: Final[float] = 0.7
COMPLEXITY_HINT_BLEND_WEIGHT: Final[float] = 0.3

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
# OpenAI's rule-of-thumb: ~1.3 tokens per whitespace-delimited word for
# English. Used in:
#  - bsgateway.routing.collector (feature extraction for routing_logs)
#  - bsgateway.routing.classifiers.static (complexity scoring)
#  - bsgateway.rules.models (EvaluationContext token estimate)
#
# CJK paths add a separate per-character term in ``rules.models.estimate_tokens``;
# this multiplier still scales the combined sum.
WORDS_TO_TOKENS_RATIO: Final[float] = 1.3

# ---------------------------------------------------------------------------
# Routing-log truncation
# ---------------------------------------------------------------------------
# routing_logs.user_text / system_prompt persist the prompt text for ML
# training. Cap to keep row size and ML training memory bounded. 2000
# chars ≈ a 500-token request, which covers 99%+ of decision contexts
# without forcing the DB to spill TOAST pages on every read.
LOG_TEXT_MAX_CHARS: Final[int] = 2000
