# BSGateway Scope Catalog

Phase 1 token cutover replaces role-based gating with **scope strings**
carried by bsvibe-authz tokens. Bootstrap tokens (`bsv_admin_*`) carry the
wildcard `*` and pass every check; opaque service keys (`bsv_sk_*`) issued
through bsvibe-authz introspection carry the narrow scopes below.

The scope check is implemented by
[`bsvibe_authz.require_scope`](https://github.com/BSVibe/bsvibe-python/tree/main/packages/bsvibe-authz)
and re-exported as `bsgateway.api.deps.require_scope` (tagged with
`_bsvibe_scope` so `tests/test_authz_scope_matrix.py` can pin the catalog).

Match rules:
- `*` grants any scope.
- exact match.
- prefix wildcard: `gateway:*` grants `gateway:models:write`,
  `gateway:routing:read`, etc.

## Catalog

| Scope                     | Grants                                                              |
| ------------------------- | ------------------------------------------------------------------- |
| `*`                       | bootstrap super-admin — every endpoint                              |
| `gateway:*`               | every BSGateway admin endpoint (any resource, any action)           |
| `gateway:tenants:read`    | `GET /tenants`, `GET /tenants/{id}`                                 |
| `gateway:tenants:write`   | `POST /tenants`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}`      |
| `gateway:models:read`     | `GET /tenants/{id}/models`, `GET /tenants/{id}/models/{model_id}`   |
| `gateway:models:write`    | `POST/PATCH/DELETE` on `/tenants/{id}/models[/{model_id}]`          |
| `gateway:routing:read`    | `GET` on rules, intents, examples, presets                          |
| `gateway:routing:write`   | `POST/PATCH/DELETE` on rules, intents, examples, preset apply, reembed |
| `gateway:audit:read`      | `GET /tenants/{id}/audit`                                           |

## Adding a new admin route

1. Add `_scope: None = Depends(require_scope("gateway:<resource>:<action>"))`
   to the route signature.
2. Append a row to `MATRIX` in `bsgateway/tests/test_authz_scope_matrix.py`.
3. Update this catalog table.

## Why scopes (not roles or OpenFGA tuples)?

- **Roles** (`admin` / `member`) couldn't express "this CI service can
  read models but not rotate them" without proliferating role names.
- **OpenFGA tuples** (`require_permission(...)`) handle resource-level
  ACLs (per-tenant, per-rule) but require a relationship graph for every
  scriptable token — overkill for a service key minted by an operator.
- **Scopes** strike the middle: a token claim string, easy to mint, easy
  to audit, and they coexist with `require_permission` on the same route
  (both must pass).

## Audit / revoke SLA

Opaque-token introspection results are cached in-process for **60s** by
the `IntrospectionCache` singleton in
`bsgateway/api/deps.py::_get_introspection_cache`. After a scope change
or revoke on the auth side, the worst-case propagation window is 60s.
