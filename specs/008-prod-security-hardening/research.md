# Research: Production Security Hardening

## Decision: Treat non-loopback exposure as explicit production intent

**Rationale**: Public controller and proxy exposure are the highest-impact audit findings. Defaults should serve local development, while production exposure must require clear operator intent and a protective boundary.

**Alternatives considered**:
- Keep current defaults and document firewall requirements: rejected because documentation cannot prevent accidental open proxy or control-plane exposure.
- Force all endpoints to loopback permanently: rejected because some deployments legitimately bind to private interfaces or reverse proxies.

## Decision: Make fresh diagnostic reads non-mutating

**Rationale**: Operators expect pool, doctor, leak, and DNS checks to observe state unless they explicitly request repair. Read-triggered repair makes validation nondeterministic and can rotate provider sessions during audits.

**Alternatives considered**:
- Keep auto-repair on all fresh reads: rejected because it violates read-only command contracts.
- Disable auto-repair globally: rejected because background repair remains useful when explicitly enabled.

## Decision: Serialize rotations per backend, not globally

**Rationale**: The unsafe concurrency is overlapping rotations for the same backend. Per-backend locks preserve pool-level parallelism for `rotate/all` batches while preventing interleaved stop/start/recovery operations.

**Alternatives considered**:
- Global rotation lock: simpler but unnecessarily blocks independent backends.
- Best-effort detection without locks: rejected because ThreadingHTTPServer can still interleave calls.

## Decision: Keep controller stdlib-only

**Rationale**: The constitution and existing deployment rely on a dependency-free controller. Auth/session hardening, CSRF checks, egress target validation, and rotation locks can be implemented with stdlib modules.

**Alternatives considered**:
- Add a web framework/session library: rejected for this release because it expands runtime surface area and image complexity.

## Decision: Fail closed on incomplete DNS verification evidence

**Rationale**: Security validation is used for release confidence. Missing connection IP or ASN evidence must not be interpreted as success when strict mode is requested.

**Alternatives considered**:
- Report warnings while passing: rejected because it weakens go/no-go semantics.

## Decision: Warn on mutable images before requiring digest pins

**Rationale**: Digest pinning is desirable for production, but forcing it immediately could break current live deployments. The first hardening step should make risk visible through doctor/generate output and docs, with support for digest references already compatible with Docker.

**Alternatives considered**:
- Reject all mutable tags immediately: rejected as too disruptive for existing users.
