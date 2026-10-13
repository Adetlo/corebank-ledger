# Security Policy

## Scope

CoreBank Ledger is an **educational reference implementation**. It must never
be used to process real financial transactions, real customer data or real
account identifiers. All data in this repository, its tests, examples and demo
scripts is synthetic.

Authentication and authorisation are intentionally **out of scope for v1**.
The API assumes it sits behind an authenticating gateway; see
[`docs/SECURITY.md`](docs/SECURITY.md) for the threat model, the controls that
*are* implemented, and how OAuth2/OIDC (for example Microsoft Entra ID) would
be integrated.

## Supported versions

Only the `main` branch receives fixes.

## Reporting a vulnerability

If you find a security issue in this project:

1. Please do **not** open a public issue with exploit details.
2. Use GitHub's private vulnerability reporting on the repository
   ("Security" tab, "Report a vulnerability") so the report stays confidential.
3. Include the affected component, a minimal reproduction and the impact you
   believe it has.

You can expect an acknowledgement within a reasonable time frame for a
volunteer-maintained project. Please allow time for a fix before public
disclosure. There is no bug bounty.

## Out of scope

* Findings that require real credentials or real banking infrastructure.
* Missing authentication (documented as out of scope for v1).
* Denial-of-service against a locally run demo stack.
