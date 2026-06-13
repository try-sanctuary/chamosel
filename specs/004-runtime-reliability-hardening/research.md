# Research: Runtime Reliability Hardening

## Decisions

- Use `/pool?fresh=1` as the doctor pool check because it exercises the live controller refresh path and updates stale state.
- Keep doctor output secret-safe by reporting booleans, paths, ports, and aggregate status only.
- Treat loaded persisted state as stale even if the saved health was healthy; after restart the controller must prove freshness again.
- Keep `/rotate/all` response backwards-compatible by retaining existing aggregate fields and adding batch metadata.
- Use `pool_degraded_min_healthy: auto` as all configured backends healthy. This makes degraded state conservative for live scraping pools.

## Alternatives Considered

- Full provider-specific diagnostics were deferred. The feature is runtime reliability, not provider integration.
- Controller auth for public API was not added here because the existing deployment default binds the API to loopback.
- DNS leak probing was left to `verify-leaks`/future leak features; doctor is a local stack health command.

