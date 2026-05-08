"""Top-level Typer app for ``bsgateway`` admin CLI.

Built on :func:`bsvibe_cli_base.cli_app` — the root callback resolves
profile / token / tenant / output and stashes a
:class:`bsvibe_cli_base.CliContext` on ``ctx.obj`` for sub-commands.

Sub-apps land in TASK-008..011:

* ``bsgateway models …``     — admin model registry CRUD
* ``bsgateway routes test``  — route resolution probe
* ``bsgateway rules …``      — routing rules CRUD
* ``bsgateway intents …``    — intent examples CRUD
* ``bsgateway presets …``    — preset apply
* ``bsgateway tenants …``    — tenant CRUD
* ``bsgateway audit …``      — audit log queries
* ``bsgateway usage …``      — usage / cost reports
* ``bsgateway feedback …``   — feedback submission
* ``bsgateway workers …``    — executor worker registry
* ``bsgateway execute …``    — async task dispatch
"""

from __future__ import annotations

from bsvibe_cli_base import cli_app

from bsgateway.cli.commands.intents import app as intents_app
from bsgateway.cli.commands.models import app as models_app
from bsgateway.cli.commands.presets import app as presets_app
from bsgateway.cli.commands.routes import app as routes_app
from bsgateway.cli.commands.rules import app as rules_app

app = cli_app(
    name="bsgateway",
    help=(
        "BSGateway admin CLI — manage tenant model registry, routing rules, "
        "audit, usage, and executor workers from the terminal."
    ),
)

app.add_typer(models_app, name="models")
app.add_typer(routes_app, name="routes")
app.add_typer(rules_app, name="rules")
app.add_typer(intents_app, name="intents")
app.add_typer(presets_app, name="presets")


__all__ = ["app"]
