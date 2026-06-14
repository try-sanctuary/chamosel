# Verified Egress Country Policy

Status: deferred / not critical

## Problem

`SERVER_COUNTRIES` constrains gluetun server selection by provider metadata, but it does not guarantee that external websites will classify the actual proxy egress IP in the same country.

Observed case:

- Container env had `SERVER_COUNTRIES=United States`.
- gluetun logs showed United States server selection and US public IPs.
- A UI-observed IP, `82.26.162.14`, was manually checked on CloudFilt and classified as `United Kingdom / Chatham`.
- Direct re-check of `surfshark_2` later showed matching proxy and gluetun IP `185.141.119.47`, classified by gluetun as `United States / Michigan / Detroit`.

This means the UK result may have been a stale UI value, a different backend selected through HAProxy, a temporary egress mismatch, or a GeoIP disagreement. The broader reliability gap remains valid: chamosel currently verifies egress IP, but it does not enforce an allowed country policy for the verified egress location.

## Goal

Add an optional policy that validates actual proxy egress country against an operator-defined allowlist.

Example:

```yaml
global_settings:
  allowed_egress_countries:
    - United States
```

When enabled, chamosel should treat the verified proxy egress country as the source of truth for country policy, not `SERVER_COUNTRIES`.

## Proposed Behavior

- `/pool?fresh=1` verifies each healthy backend through its own proxy.
- The controller stores `verified_proxy_ip`, `country`, `city`, and source metadata.
- If `country` is not in `allowed_egress_countries`, the backend is marked degraded.
- Pool gets degraded reason `unexpected_egress_country`.
- Dashboard shows the unexpected country/city clearly.
- `doctor --repair` and auto repair may rotate one affected backend, respecting cooldown and backoff.
- `public_ip_mismatch` remains monitor-only unless the verified country policy fails or another fail-level reason exists.

## Config

Potential config additions:

```yaml
global_settings:
  allowed_egress_countries: [] # empty means disabled
  egress_geo_source: ifconfig.co
```

Potential future extension:

```yaml
global_settings:
  egress_geo_sources:
    - ifconfig.co
    - ipinfo
    - custom
  egress_geo_consensus: any # any|majority|strict
```

## API Additions

Per-instance `/pool` fields:

- `country`
- `city`
- `geo_source`
- `expected_country`
- `unexpected_egress_country: true|false`
- `unexpected_egress_country_error`

Pool-level additions:

- `degraded_reasons` includes `unexpected_egress_country`
- `pool_status` becomes `degraded` if any healthy backend violates the country policy

## Repair Semantics

Repair should target only backends that are actually repairable:

- duplicate verified proxy IP
- proxy/egress verification failure
- unexpected verified egress country

Repair should not rotate only because of:

- `public_ip_mismatch` when verified proxy IP is unique and country is allowed
- stale state before first fresh poll
- missing country when egress verification is disabled

## Open Questions

- Should country matching use display names only (`United States`) or also ISO codes (`US`)?
- Should `SERVER_COUNTRIES` be automatically reused as `allowed_egress_countries`, or should the policy require an explicit allowlist?
- Should `ifconfig.co` remain the default geo source, given occasional HTTP 403 responses?
- Should chamosel support a fallback source for country when ifconfig fails but IP verification succeeds?

## Test Plan

- Unit: allowed country passes.
- Unit: unexpected country marks backend and pool degraded.
- Unit: public IP mismatch with allowed verified country does not trigger country repair.
- Unit: unexpected country selects exactly one repair candidate.
- Unit: country policy disabled preserves current behavior.
- Unit: stale country from previous controller process is not used for policy decisions.
- CLI: `doctor --repair` reports `unexpected_egress_country` as repairable.
- Dashboard: country/city remain visible and unexpected country is obvious.
- Live validation: configure `allowed_egress_countries: ["United States"]`, rotate a backend, confirm only non-US verified exits are degraded/repaired.
