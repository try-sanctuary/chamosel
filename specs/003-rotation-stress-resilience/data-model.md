# Data Model: Rotation Stress Resilience

## Backend Rotation State

Represents the latest operator-relevant rotation condition for one backend.

### Fields

- `name`: Backend instance name.
- `healthy`: Whether the backend is currently considered healthy.
- `status`: Current backend health/control status.
- `public_ip`: Last known public IP for the backend.
- `ip_history`: Most recent public IPs for this backend.
- `rotations`: Count of changed-IP rotation successes.
- `rotation_errors`: Count of failed or degraded rotation outcomes.
- `last_rotated`: Timestamp for the most recent changed-IP success.
- `last_rotation_attempted`: Timestamp for the most recent rotation attempt.
- `last_rotation_outcome`: Stable label for the most recent outcome.
- `last_rotation_message`: Operator-safe summary of the most recent outcome.
- `last_rotation_old_ip`: Public IP observed before the latest rotation attempt, when available.
- `last_rotation_new_ip`: Public IP observed after the latest rotation attempt, when available.
- `cooldown_until`: Timestamp when failure cooldown expires, or empty when not cooling down.
- `cooldown_reason`: Outcome that caused the cooldown, or empty when not cooling down.
- `rotation_errors_by_outcome`: Counts grouped by stable outcome label.

### Validation Rules

- Outcome labels must be stable strings suitable for JSON responses and metrics labels.
- Secret values must never be stored in rotation message fields.
- `cooldown_until` must be absent or greater than the time the cooldown was created.
- `last_rotation_new_ip` may equal `last_rotation_old_ip` only for the healthy-but-unchanged outcome.

### State Transitions

- `eligible` -> `reconnecting`: rotation command accepted and stop/start transition begins.
- `reconnecting` -> `ip_changed`: backend becomes healthy with a changed public IP.
- `reconnecting` -> `healthy_ip_unchanged`: backend becomes healthy but public IP remains unchanged.
- `reconnecting` -> `recovery_timeout`: backend does not reach an acceptable recovered state before timeout.
- `reconnecting` -> `proxy_failure`: backend health/control status recovers but proxied verification fails.
- `eligible` -> `skipped_cooldown`: mass rotation skips a backend with an active cooldown.
- `cooling_down` -> `eligible`: cooldown expires and backend is no longer skipped by mass rotation.

## Cooldown Window

Represents a temporary skip period after provider recovery or proxy verification problems.

### Fields

- `instance`: Backend instance name.
- `started_at`: Timestamp when cooldown began.
- `expires_at`: Timestamp when cooldown ends.
- `reason`: Outcome that triggered cooldown.
- `attempt_count`: Number of recent attempts associated with the cooldown reason.
- `forced_bypass_count`: Number of times an operator explicitly bypassed cooldown.

### Validation Rules

- Cooldown must apply to mass rotation and automatic rotation.
- Named forced rotation may bypass cooldown, but the result must reveal that a bypass occurred.
- Expired cooldowns must not keep a backend out of eligible rotation.

## Mass Rotation Result

Represents the result of a rotate-all operation.

### Fields

- `ok`: True when all eligible backend operations completed without failed outcomes; false when any backend failed or no backend was eligible.
- `outcome`: Aggregate outcome, such as all changed, partial success, all skipped cooldown, or failed.
- `eligible_count`: Backends selected for rotation.
- `skipped_count`: Backends skipped before rotation.
- `success_count`: Backends that changed IP successfully.
- `unchanged_count`: Backends that recovered but kept the same IP.
- `failure_count`: Backends with failed outcomes.
- `cooldown_count`: Backends currently cooling down after the request.
- `results`: Per-backend rotation responses.

### Validation Rules

- Aggregate counts must match the per-backend result list.
- Skipped cooldown results must not increment changed-IP success counters.
- Partial success must preserve every per-backend outcome.

## Stress Validation Report

Represents the final report from a repeatable stress workflow.

### Fields

- `mode`: Leak-only or rotation validation mode.
- `iterations_requested`: Number of requested iterations.
- `iterations_completed`: Number of completed iterations.
- `backend_count`: Number of backends observed in the pool.
- `verified_backend_checks`: Total backend verification checks completed.
- `leak_failures`: Count of host/backend public-IP matches or unsafe public-IP findings.
- `availability_failures`: Count of backend/controller/target availability failures.
- `duplicate_ip_events`: Count of repeated public-IP findings across backends when tracked.
- `rotation_outcomes`: Counts grouped by rotation outcome.
- `started_at`: Report start timestamp.
- `finished_at`: Report finish timestamp.
- `total_seconds`: Total elapsed duration.
- `artifact_paths`: Optional paths to report files.

### Validation Rules

- Reports must be useful without secrets or provider credentials.
- Leak-only mode must not rotate backends.
- Rotation mode must show skipped cooldowns and partial completion.
