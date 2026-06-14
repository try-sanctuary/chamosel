# Research: Control Plane Hardening

## Effective Control Key Source

**Decision**: Resolve one effective gluetun control key in this order: explicit
process environment, existing `.env`, configured `global_settings.api_key`, then
generated key. If both `.env` and `global_settings.api_key` exist and differ,
generation fails with a clear error before writing generated stack files.

**Rationale**: This preserves current env override behavior, keeps existing
generated deployments stable, supports config-supplied keys, and prevents a
split-brain stack where gluetun and the controller receive different keys.

**Alternatives considered**:
- Config always overwrites `.env`: simple, but risks silently invalidating an
  existing deployment.
- `.env` always wins and config is ignored: stable, but hides operator intent.
- Prompt interactively: poor for automation and `chamosel.py up`.

## Localhost-Safe Operator Bindings

**Decision**: Bind controller API and HAProxy stats host ports to `127.0.0.1` by
default. Remote exposure is explicit opt-in through configuration, documented as
requiring an external protection boundary such as firewall or reverse proxy.

**Rationale**: Default Docker port publishing is easy to expose on a VPS. Local
binds satisfy the spec's zero non-local default exposure criterion while
preserving local quickstart behavior.

**Alternatives considered**:
- Built-in controller authentication for all operator endpoints: useful later,
  but larger scope and does not protect HAProxy stats by itself.
- Keep public binds and warn in README: known unsafe default.

## Safe Provider Environment Rendering

**Decision**: Render service environment as a YAML mapping or otherwise quote
each key/value using structured serialization, preserving exact scalar values
with punctuation, whitespace, or comment-like characters.

**Rationale**: VPN credentials and provider options commonly contain characters
that break YAML plain scalars. Structured rendering gives deterministic output
and can be verified with YAML parsing.

**Alternatives considered**:
- Continue list-form `KEY=value` plain scalars: fragile with special characters.
- Escape manually: error-prone and harder to test than structured YAML output.

## Stale Status-Path Recovery

**Decision**: Treat a cached status path as tentative. If it fails with a route
or response-shape error, clear that instance's cached path and re-run supported
path detection before marking the instance unsupported or down. Authentication
failures remain fail-closed and operator-visible.

**Rationale**: gluetun status endpoints have changed across versions, and state
persists across controller restarts. Re-detection prevents stale state from
surviving upgrades or downgrades.

**Alternatives considered**:
- Never persist status path: simpler but adds extra detection calls every start.
- Persist and never re-detect: current behavior, brittle across version changes.

## Bounded Polling With Down Instances

**Decision**: Poll instances concurrently with a bounded worker count or one
thread per instance for the small expected pool size, preserving per-request
timeouts and writing one coherent state update per instance.

**Rationale**: Sequential polling can block behind multiple unreachable
instances. Bounded concurrency lets reachable instances refresh within the
configured interval target while keeping controller dependencies stdlib-only.

**Alternatives considered**:
- Lower timeout only: helps but still serializes failures.
- Async event loop: unnecessary dependency/style shift for a stdlib controller.

## Rotation Success Accounting

**Decision**: After a successful stop/start command sequence, wait up to 30
seconds for usable health. Count success only when the instance becomes usable
within that window; otherwise record a distinct recovery timeout outcome.

**Rationale**: Operators need counters to reflect usable proxy capacity, not just
command acknowledgement. The 30-second window was clarified in the spec and is
long enough for ordinary tunnel recovery without hanging request retry workflows
indefinitely.

**Alternatives considered**:
- Count success immediately: current optimistic behavior.
- Return pending and let polling update counters later: more complex state
  lifecycle and less clear synchronous feedback.
- Wait 60 seconds: safer for slow VPNs, but too slow for request retry loops.

## Testing Strategy

**Decision**: Add focused stdlib tests around pure helper seams and monkeypatch
network/control calls in controller tests. Generation tests validate rendered
YAML, `.env` behavior, and bind strings without requiring Docker or VPN
credentials. Optional quickstart steps cover `docker compose config` and live
runtime behavior where Docker/VPN access is available.

**Rationale**: The controller intentionally has no pip dependencies. Standard
library tests keep the project easy to run while covering the high-risk logic.

**Alternatives considered**:
- Add pytest: nicer ergonomics, but unnecessary for current scope.
- Only manual Docker tests: misses fast regression coverage.
