# Research: Controller Repair and Auth Hardening

## Decision: Controller auth is separate from gluetun auth

**Rationale**: The existing `GLUETUN_API_KEY` protects controller-to-gluetun calls, not operator-to-controller calls. Reusing the same key would couple two trust boundaries and make rotation/dashboard access harder to reason about.

**Alternatives considered**:
- Reuse `GLUETUN_API_KEY`: rejected because it widens the blast radius of a gluetun control secret.
- Add only reverse-proxy guidance: rejected because generated controller endpoints still need a first-party protection option.

## Decision: Use one configured controller token for protected endpoints

**Rationale**: chamosel is an operator tool, not a multi-user admin product. A single bearer-style token keeps the controller stdlib-only and is enough to protect dashboard, pool, metrics, and rotation actions when bound beyond loopback.

**Alternatives considered**:
- Basic auth username/password: useful later, but two secrets add config burden without adding meaningful local value.
- Full user/session auth: rejected as out of scope for an operator-side controller.

## Decision: `doctor` remains read-only unless `--repair` is passed

**Rationale**: Operators expect a doctor command to suggest repair, but command safety requires a clear action boundary. Read-only default preserves current behavior and makes automation safe.

**Alternatives considered**:
- Auto-repair on every doctor run: rejected because it would surprise existing scripts.
- Separate `repair` command only: rejected because user explicitly wants doctor to diagnose in order to repair.

## Decision: Repair targets duplicate egress conditions, not mismatch-only state

**Rationale**: A `public_ip_mismatch` with unique verified proxy IPs can be temporary and acceptable. Rotating for mismatch alone may create unnecessary provider pressure.

**Alternatives considered**:
- Rotate every mismatch: rejected because verified proxy IP is the stronger source of truth for HTTP egress.
- Ignore mismatch entirely: rejected because operators still need visibility.

## Decision: Repair remains bounded to one target per invocation

**Rationale**: One repair per command keeps provider load controlled and makes outcomes easy to inspect.

**Alternatives considered**:
- Repair all degraded backends: rejected because it can amplify provider cooldown/recovery failures.
