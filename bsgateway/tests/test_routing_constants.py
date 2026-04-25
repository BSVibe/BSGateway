"""Audit M13: every magic number in routing logic must live in one place.

The pre-fix codebase scattered three numeric constants across hot paths:

* ``0.7`` / ``0.3`` blend weights (classifier vs. nexus complexity hint)
  — ``routing/hook.py``
* ``1.3`` words-to-tokens estimation multiplier — ``routing/collector.py``,
  ``routing/classifiers/static.py``, ``rules/models.py``
* ``2000`` log-text truncation cap — ``chat/service.py``

These are operational knobs (an operator might want to tune blend bias,
the tokens-per-word ratio, or truncation length without grepping for
literals). The fix: surface them as importable named constants in
``bsgateway/routing/constants.py`` and route every call site through it.
"""

from __future__ import annotations

import math


def test_blend_weights_module_exists_and_sums_to_one() -> None:
    from bsgateway.routing import constants

    assert hasattr(constants, "CLASSIFIER_BLEND_WEIGHT")
    assert hasattr(constants, "COMPLEXITY_HINT_BLEND_WEIGHT")
    # Must form a proper convex combination so the blended score never
    # leaves the [0, 100] domain.
    total = constants.CLASSIFIER_BLEND_WEIGHT + constants.COMPLEXITY_HINT_BLEND_WEIGHT
    assert math.isclose(total, 1.0), (
        f"blend weights must sum to 1.0; got {total}. Otherwise the blended "
        f"score escapes the [0, 100] tier-mapping domain."
    )


def test_blend_weights_match_legacy_70_30() -> None:
    """Lock in the 70%-classifier / 30%-hint default tested across e2e suites.

    Changing these values changes the routing decision surface; bump
    intentionally, not by accident.
    """
    from bsgateway.routing import constants

    assert constants.CLASSIFIER_BLEND_WEIGHT == 0.7
    assert constants.COMPLEXITY_HINT_BLEND_WEIGHT == 0.3


def test_token_estimation_multiplier_exposed() -> None:
    """``words * WORDS_TO_TOKENS_RATIO`` is the cross-codebase token estimate.

    Three call sites used the literal ``1.3``; one named constant means
    "tune this once, propagate everywhere".
    """
    from bsgateway.routing import constants

    assert hasattr(constants, "WORDS_TO_TOKENS_RATIO")
    assert constants.WORDS_TO_TOKENS_RATIO == 1.3


def test_log_text_truncation_exposed() -> None:
    """``LOG_TEXT_MAX_CHARS`` controls how much user_text/system_prompt
    is persisted into routing_logs."""
    from bsgateway.routing import constants

    assert hasattr(constants, "LOG_TEXT_MAX_CHARS")
    # Must be a positive int so slice expressions never raise.
    assert isinstance(constants.LOG_TEXT_MAX_CHARS, int)
    assert constants.LOG_TEXT_MAX_CHARS > 0
    assert constants.LOG_TEXT_MAX_CHARS == 2000


def test_hook_uses_named_blend_weights() -> None:
    """``BSGatewayRouter._auto_route`` must reference the named constants
    rather than open-coding ``0.7`` / ``0.3``.

    Pinning this prevents the value from drifting back into the literal
    over time.
    """
    import inspect

    from bsgateway.routing import hook

    src = inspect.getsource(hook)
    assert "CLASSIFIER_BLEND_WEIGHT" in src, (
        "hook.py must import and use CLASSIFIER_BLEND_WEIGHT from constants"
    )
    assert "COMPLEXITY_HINT_BLEND_WEIGHT" in src, (
        "hook.py must import and use COMPLEXITY_HINT_BLEND_WEIGHT from constants"
    )


def test_collector_uses_named_token_ratio() -> None:
    import inspect

    from bsgateway.routing import collector

    src = inspect.getsource(collector)
    assert "WORDS_TO_TOKENS_RATIO" in src, (
        "collector.py must use WORDS_TO_TOKENS_RATIO from constants"
    )


def test_chat_service_uses_named_truncation() -> None:
    import inspect

    from bsgateway.chat import service

    src = inspect.getsource(service)
    assert "LOG_TEXT_MAX_CHARS" in src, "chat/service.py must use LOG_TEXT_MAX_CHARS from constants"
