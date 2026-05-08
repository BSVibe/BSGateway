"""bsgateway admin CLI.

Entry point: ``bsgateway`` console script (declared in pyproject.toml
``[project.scripts]``) → :data:`bsgateway.cli.main.app`.

The Typer app is built via :func:`bsvibe_cli_base.cli_app` so every
sub-command inherits the global flag set (``--profile``, ``--output``,
``--tenant``, ``--token``, ``--url``, ``--dry-run``) and a resolved
:class:`bsvibe_cli_base.CliContext` on ``ctx.obj``.

Sub-apps (models, rules, intents, presets, tenants, audit, usage,
feedback, workers, execute) are mounted in TASK-008..011.
"""

from bsgateway.cli.main import app

__all__ = ["app"]
