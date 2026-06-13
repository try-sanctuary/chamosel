# Data Model: Controller Repair and Auth Hardening

## Controller Auth Configuration

- `enabled`: whether controller endpoints require operator authentication
- `token_source`: where the operator token is supplied from
- `bind_safety`: whether the controller bind address is loopback or exposed
- `protected_endpoints`: dashboard, pool, metrics, rotation, and repair routes

Validation rules:
- If authentication is enabled, a non-empty token must exist.
- If authentication is disabled and the bind address is non-loopback, generation or doctor must warn/fail safely.
- Secrets must not appear in generated docs, CLI output, metrics, dashboard, or logs.

## Repair Decision

- `action`: `none`, `monitor`, `repair_requested`, `repair_in_progress`, `wait_backoff`, `blocked`, or `manual`
- `reason`: operator-readable reason code
- `targets`: zero or one repair target for one invocation
- `message`: human-readable summary
- `backoff_remaining`: retry backoff state when applicable

Validation rules:
- `doctor` without repair mode must not mutate backend state.
- `doctor --repair` may request at most one repair target.
- `public_ip_mismatch` alone is monitor-only when verified proxy IPs are unique.

## Repair Action

- `target_instance`: backend selected for repair
- `trigger_reason`: duplicate verified proxy IP or fallback duplicate public IP
- `outcome`: existing rotation outcome or blocked state
- `cooldown`: active cooldown/backoff information

State transitions:
- `eligible duplicate` -> `repair_requested` -> existing rotation outcome
- `duplicate with active repair` -> `repair_in_progress`
- `duplicate with retry backoff` -> `wait_backoff`
- `mismatch-only` -> `monitor`
- `unhealthy/unauthorized/unreachable` -> `manual` or `blocked`
