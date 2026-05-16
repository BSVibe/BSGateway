# BSGateway Authorization Catalog

Tier 5 (bsvibe-authz 1.4.0) unified the BSGateway REST authorization
surface. The legacy `require_scope` COLON-grammar gate was removed.
Two gates now coexist:

- **`require_permission`** — the uniform per-resource gate. Permission
  strings use the 3-part DOT grammar `bsgateway.<resource>.<action>`.
  The minimum tenant role for each permission lives in the OpenFGA model
  (generated from `bsvibe-authz/schema/permission_matrix.yaml`), **not**
  in route code. `require_permission` is permissive when OpenFGA is
  unconfigured (which it is on BSGateway today), so an authenticated
  browser session JWT (`scope=[]`) passes. Used for every control-plane
  read/list and tenant-member CRUD route.
- **`require_admin`** — real enforced check on `app_metadata.role`
  (`owner`/`admin`; demo + service principals also pass). Used for
  genuine tenant administration (tenant create/update/delete, per-tenant
  model CRUD).

> **Why no `require_scope`?** The frontend authenticates with a wrapped
> session JWT carrying `scope=[]`; a pure `require_scope` gate 403s every
> browser request. Tier 5 retired BSGateway's `require_scope` usage and
> its `bsgateway.api.deps.require_scope` wrapper entirely — every REST
> route now uses `require_permission` or `require_admin`. (The
> library-level `bsvibe_authz.require_scope` is removed in a later
> Tier 5 phase.)

`require_permission` / `require_admin` are re-exported from
`bsgateway.api.deps` (tags `_bsvibe_permission` / `_bsvibe_admin`) so
`tests/test_authz_route_matrix.py` can pin the route → permission matrix.

## `require_permission` routes

Permission grammar is `bsgateway.<resource>.<action>` (3-part DOT). Every
string below is a row in `bsvibe-authz/schema/permission_matrix.yaml`.

| Permission                   | Routes                                                          |
| ----------------------------- | --------------------------------------------------------------- |
| `bsgateway.tenants.read`      | `GET /tenants`, `GET /tenants/{id}`                             |
| `bsgateway.routes.read`       | `GET` on rules                                                  |
| `bsgateway.routes.create`     | `POST /tenants/{id}/rules`                                      |
| `bsgateway.routes.write`      | `PATCH/DELETE /tenants/{id}/rules/{rule_id}`                    |
| `bsgateway.routing.read`      | `GET` on intents, examples                                      |
| `bsgateway.routing.write`     | `POST/PATCH/DELETE` on intents, examples, reembed               |
| `bsgateway.presets.read`      | `GET /presets`                                                  |
| `bsgateway.presets.write`     | `POST /tenants/{id}/presets/apply`                              |
| `bsgateway.models.read`       | `GET /admin/models`                                             |
| `bsgateway.models.write`      | `POST /admin/models`, `PATCH/DELETE /admin/models/{model_id}`   |
| `bsgateway.audit.read`        | `GET /tenants/{id}/audit`                                       |
| `bsgateway.workers.read`      | `GET /workers`, `GET /workers/install-token`                    |
| `bsgateway.workers.write`     | `POST/DELETE /workers/install-token`, `DELETE /workers/{id}`    |
| `bsgateway.usage.read`        | `GET /tenants/{id}/usage`, `GET /tenants/{id}/usage/sparklines` |
| `bsgateway.feedback.read`     | `GET /tenants/{id}/feedback`                                    |
| `bsgateway.feedback.write`    | `POST /tenants/{id}/feedback`                                   |

## `require_admin` routes (genuine tenant administration)

- `POST /tenants`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}`
- `POST/GET/PATCH/DELETE` on `/tenants/{id}/models[/{model_id}]`

## Ungated-by-permission routes (data plane)

The gateway's core dispatch routes are deliberately gated **only** by
tenant-scoped authentication (`get_auth_context`), not by a per-resource
`require_permission` check. Any authenticated tenant member may use them:

- `POST /chat/completions` — OpenAI-compatible completion dispatch.
- `POST /execute`, `GET /tasks/{id}`, `GET /tasks` — async executor
  dispatch (the async sibling of chat completions).

The `bsgateway.execute.write` permission row exists in the matrix for a
future control-plane execute admin surface; it is **not** applied to the
data-plane dispatch routes above.

The worker-token-authed registration loop (`POST /workers/register`,
`/heartbeat`, `/poll`, `/result`) authenticates with the worker's own
`X-Worker-Token` / `X-Install-Token` header — not a user JWT — and is
therefore outside the user-permission catalog.

## Adding a new route

1. Classify it:
   - **read/list, or tenant-member CRUD** → `require_permission("bsgateway.<res>.<act>")`
   - **genuine tenant administration** → `require_admin()`
   - **core data-plane dispatch** → `get_auth_context` only (document it here)
2. Ensure the permission string is a row in
   `bsvibe-authz/schema/permission_matrix.yaml`.
3. Append a row to the matching `MATRIX`/`ADMIN_MATRIX` in
   `bsgateway/tests/test_authz_route_matrix.py`.
4. Update this catalog.

## Audit / revoke SLA

PAT-JWT introspection results are cached in-process for **60s** by the
`IntrospectionCache` singleton in
`bsgateway/api/deps.py::_get_introspection_cache`. After a revoke on the
auth side, the worst-case propagation window is 60s.
</content>
</invoke>
