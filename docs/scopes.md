# BSGateway Scope Catalog

Phase 2b realigned the auth surface. Three gates now coexist:

- **`require_scope`** — narrow scope strings carried by opaque service
  keys (`bsv_sk_*`) / real-scope PATs. Used **only** for CLI/PAT-hit
  routes — the org-level effective-model registry.
- **`require_permission`** — permissive when OpenFGA is unconfigured
  (which it is on BSGateway), so an authenticated browser session JWT
  (`scope=[]`) passes. Used for frontend-hit reads/lists and
  tenant-member CRUD (rules, intents, presets, audit, tenant reads).
- **`require_admin`** — real enforced check on `app_metadata.role`
  (`owner`/`admin`; demo + service principals also pass). Used for
  genuine tenant administration (tenant create/update/delete, per-tenant
  model CRUD).

> **Why the split?** The frontend authenticates with a wrapped session
> JWT carrying `scope=[]`. A pure `require_scope` gate 403s every
> browser request — the app loads but is dead. So frontend-hit routes
> moved off `require_scope`; only CLI/PAT-only routes keep it.

The scope check is implemented by
[`bsvibe_authz.require_scope`](https://github.com/BSVibe/bsvibe-python/tree/main/packages/bsvibe-authz)
and re-exported as `bsgateway.api.deps.require_scope` (tagged with
`_bsvibe_scope` so `tests/test_authz_scope_matrix.py` can pin the
catalog). `require_permission` / `require_admin` are re-exported the same
way (tags `_bsvibe_permission` / `_bsvibe_admin`).

## `require_scope` catalog (CLI / PAT-only)

Scope grammar is `bsgateway:<resource>:<action>` — re-prefixed from the
legacy `gateway:` to match the bsXXX audience flip (bsvibe-authz 1.2.0
`SERVICE_AUDIENCES = {bsgateway, bsupervisor, bsage, bsnexus}`).

Match rules:
- exact match.
- prefix wildcard: `bsgateway:*` grants `bsgateway:models:write`,
  `bsgateway:models:read`, etc.

| Scope                     | Grants                                                          |
| ------------------------- | --------------------------------------------------------------- |
| `bsgateway:*`             | every `require_scope` BSGateway route                           |
| `bsgateway:models:read`   | `GET /admin/models`                                             |
| `bsgateway:models:write`  | `POST /admin/models`, `PATCH/DELETE /admin/models/{model_id}`   |

## `require_permission` routes (frontend-hit, permissive)

| Permission                  | Routes                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| `bsgateway.tenants.read`     | `GET /tenants`, `GET /tenants/{id}`                          |
| `bsgateway.routes.read`      | `GET` on rules                                               |
| `bsgateway.routes.create`    | `POST /tenants/{id}/rules`                                   |
| `bsgateway.routes.write`     | `PATCH/DELETE /tenants/{id}/rules/{rule_id}`                 |
| `bsgateway.routing.read`     | `GET` on intents, examples, presets                          |
| `bsgateway.routing.write`    | `POST/PATCH/DELETE` on intents, examples, reembed, preset apply |
| `bsgateway.audit.read`       | `GET /tenants/{id}/audit`                                    |

## `require_admin` routes (genuine tenant administration)

- `POST /tenants`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}`
- `POST/GET/PATCH/DELETE` on `/tenants/{id}/models[/{model_id}]`

## Adding a new route

1. Classify it: does a frontend page hit it with a session JWT?
   - **read/list, or tenant-member CRUD** → `require_permission("bsgateway.<res>.<act>")`
   - **genuine tenant administration** → `require_admin()`
   - **CLI/PAT-only** → `require_scope("bsgateway:<res>:<act>")`
2. Append a row to the matching `MATRIX`/`ADMIN_MATRIX` in
   `bsgateway/tests/test_authz_route_matrix.py` (permission/admin) or
   `bsgateway/tests/test_authz_scope_matrix.py` (scope).
3. Update this catalog.

## Audit / revoke SLA

Opaque-token introspection results are cached in-process for **60s** by
the `IntrospectionCache` singleton in
`bsgateway/api/deps.py::_get_introspection_cache`. After a scope change
or revoke on the auth side, the worst-case propagation window is 60s.
