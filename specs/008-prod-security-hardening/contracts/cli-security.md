# Contract: CLI Security

## Generation

- Default generated bindings are local-only.
- Non-loopback controller exposure without auth fails.
- Non-loopback proxy exposure without explicit protective configuration fails.
- Non-loopback stats exposure without auth or protective configuration fails.
- Generated secret files use restrictive permissions.
- Secret conflicts are reported without printing secret values.

## Diagnostics

- `doctor` without repair is read-only.
- `doctor --repair` is explicitly mutating and reports the attempted repair target and outcome.
- `verify-leaks` and `verify-dns` are read-only.
- All JSON/table output redacts local usernames, home paths, tokens, passwords, private keys, and provider credentials.

## Verification

- DNS verification fails when required evidence is missing.
- Strict DNS ASN mode fails when connection ASN or resolver ASN evidence is unavailable.
- Egress verification target validation rejects unsafe targets before probing.
