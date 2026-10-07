# Security Considerations

## Position

CoreBank Ledger is an educational reference implementation that processes
**synthetic data only**. It must never be connected to real customer or
financial data. With that said, it is written with the habits a real ledger
service needs, and this document is explicit about what is and is not covered.

## Authentication and authorisation: out of scope for v1

The API has no login, tokens or roles. Faking authentication "for appearance"
would teach the wrong lesson, so instead:

* The service is designed to sit **behind an authenticating gateway / reverse
  proxy** that terminates TLS and validates identity.
* The optional `X-Actor` header is recorded on audit events as *informational*
  provenance only. It is not trusted for authorisation.

### Intended future integration (OAuth2 / OIDC)

1. Register the API as a resource in an identity provider such as
   **Microsoft Entra ID**, Auth0 or Keycloak.
2. Clients obtain JWT access tokens (client credentials for systems,
   authorization code + PKCE for people).
3. A FastAPI dependency validates the token (issuer, audience, signature via
   JWKS, expiry) and maps scopes/roles to permissions, e.g.
   `ledger.accounts.write`, `ledger.journal.post`, `ledger.reconciliation.read`.
4. The validated subject replaces `X-Actor` on audit events.
5. Service-to-service calls use mTLS or workload identity in addition to tokens.

## Controls implemented in v1

| Area                   | Control                                                                                     |
|------------------------|---------------------------------------------------------------------------------------------|
| Input validation       | pydantic v2 with `extra="forbid"`; amounts must be decimal strings; enumerations enforced; length limits on every string; metadata capped at 20 keys |
| Request size           | ASGI middleware rejects bodies over `MAX_REQUEST_BYTES` (default 256 KiB) with 413, including chunked bodies |
| SQL injection          | All data access through SQLAlchemy Core/ORM with bound parameters; no string-built SQL from user input |
| Secrets                | `DATABASE_URL` is a `SecretStr`; `Settings.safe_summary()` masks credentials; `.env` is git-ignored; no secrets in the image |
| Logging                | Structured JSON; request/response bodies are never logged; SQL echo is off; internal exception details never reach clients (`INTERNAL_ERROR`) |
| Error handling         | Stable codes; database outages map to `503` without leaking DSNs                            |
| Correlation            | `X-Correlation-ID` validated against `^[A-Za-z0-9._:-]{1,64}$`; otherwise replaced          |
| Financial integrity    | Balancing, immutability, atomicity, idempotency, reversal-only corrections (see `LEDGER_INVARIANTS.md`) |
| Database hardening     | Check constraints, unique constraints, triggers blocking tampering with posted rows         |
| Container              | Multi-stage build, slim base, non-root user, no build tools in the runtime image, health check |
| Dependencies           | Locked with `uv.lock`; `pip-audit` and `bandit` run in CI                                    |
| Account numbers        | Synthetic `SYN-` prefix, random (non-sequential) body, Luhn check digit; no real scheme     |

## Threat considerations

| Threat                                     | Mitigation / status                                                            |
|--------------------------------------------|--------------------------------------------------------------------------------|
| Replay of a transfer request               | Persistent idempotency keyed per operation; conflicts on payload change        |
| Double spend via concurrent requests       | Row locks on accounts in sorted order; available-funds check under lock        |
| Tampering with history                     | Immutability in domain, application and database triggers; audit trail        |
| Unbalanced ledger via direct DB access     | Deferred constraint trigger rejects at commit                                  |
| Oversized / malformed payloads             | Size limit, strict schemas, JSON decode errors → 422                           |
| Enumeration of accounts                    | UUID ids, random account numbers; **list endpoints are unauthenticated in v1** |
| Information leakage in errors/logs         | Generic 500/503 bodies; masked DSN; bodies not logged                          |
| Dependency vulnerabilities                 | `pip-audit --strict` in CI                                                     |
| Denial of service                          | Not addressed beyond request-size limits; rate limiting belongs at the gateway |
| Privilege escalation                       | Not applicable until authentication exists; all endpoints are equally exposed  |

## Operational recommendations for a real deployment

* TLS everywhere; run behind a gateway with authentication, rate limiting and
  WAF rules.
* Separate database roles: migrations (DDL) vs runtime (DML only, no
  `TRUNCATE`/`DROP`), and no superuser for the application.
* Encrypt the database at rest; restrict network access to the API host.
* Ship logs and audit events to a tamper-evident store.
* Add an idempotency-record retention job and monitor `ledger-check`.
