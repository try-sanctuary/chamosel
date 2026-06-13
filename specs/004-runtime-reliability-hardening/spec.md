# Feature Specification: Runtime Reliability Hardening

**Feature Branch**: `004-runtime-reliability-hardening`
**Created**: 2026-06-13
**Status**: Implemented
**Input**: Runtime reliability hardening for live chamosel operation: diagnostics, stale-state recovery, degraded pool semantics, duplicate-IP repair, and bounded mass rotation.

## User Scenarios & Testing

### User Story 1 - Diagnose A Live Stack (Priority: P1)

An operator can run one local command and understand whether Docker Compose, the controller, the pool, HAProxy stats, local secret file presence, and image freshness policy are in a usable state.

**Why this priority**: Live incidents need a fast, secret-safe diagnostic before deeper leak or rotation testing.

**Independent Test**: Run `python3 chamosel.py doctor --json` against mocked stack state and verify the result includes checks without secret values.

**Acceptance Scenarios**:

1. **Given** a running stack, **When** the operator runs `chamosel.py doctor`, **Then** the command reports PASS/FAIL, check details, and a repair decision.
2. **Given** a request for machine-readable diagnostics, **When** the operator runs `chamosel.py doctor --json`, **Then** the command returns one JSON object.
3. **Given** `.env.local` contains provider credentials, **When** diagnostics run, **Then** no credential value is printed.

---

### User Story 2 - Recover Predictably After Controller Restart (Priority: P1)

After a controller restart, loaded persisted state is clearly marked stale until live polling refreshes every instance.

**Why this priority**: Persisted IP/status data can be misleading immediately after restart.

**Independent Test**: Persist healthy state, reload `State`, verify `state_fresh: false`, refresh all instances, then verify `state_fresh: true`.

**Acceptance Scenarios**:

1. **Given** saved state on disk, **When** the controller starts, **Then** instances and `/pool` show `state_fresh: false`.
2. **Given** the first successful poll or `/pool?fresh=1`, **When** all instances have been refreshed, **Then** `/pool` shows `state_fresh: true`.
3. **Given** an expired persisted cooldown, **When** state reloads, **Then** cooldown is not shown as active.

---

### User Story 3 - Rotate All Without Hammering Providers (Priority: P2)

An operator can call `/rotate/all` and the controller rotates eligible backends in bounded batches while skipping cooling backends.

**Why this priority**: Large sequential rotations are slow and repeated provider recovery failures should back off.

**Independent Test**: Mock five backends, put one in cooldown, configure batch size two, and verify only four rotate with two batches and timeout accounting.

**Acceptance Scenarios**:

1. **Given** a pool with cooling and eligible backends, **When** `/rotate/all` runs, **Then** cooling backends are skipped and eligible backends rotate.
2. **Given** a backend times out during recovery, **When** `/rotate/all` continues, **Then** the response reports `timed_out_count` and later eligible backends still run.
3. **Given** default config, **When** compose is generated, **Then** controller gets batch size two and delay two seconds.

---

### User Story 4 - Repair Duplicate Public IPs (Priority: P2)

When duplicate public IPs are detected, the controller starts one conservative repair rotation for a duplicate backend instead of leaving the pool degraded forever. Failed repair attempts enter a retry backoff to avoid provider pressure loops.

**Why this priority**: Duplicate IPs reduce effective pool diversity even when every backend is technically healthy.

**Independent Test**: Create two healthy instances with the same public IP, run duplicate repair scheduling, and verify only one non-forced rotation is scheduled.

**Acceptance Scenarios**:

1. **Given** duplicate public IPs and an eligible duplicate backend, **When** a fresh pool refresh completes, **Then** the controller schedules one background repair rotation.
2. **Given** the duplicate backend is in cooldown, **When** duplicate repair is evaluated, **Then** no repair rotation is scheduled.
3. **Given** repair is in flight, **When** another refresh happens, **Then** duplicate repair is not scheduled again for the same instance.
4. **Given** repair fails, **When** duplicate repair is evaluated again immediately, **Then** retry backoff prevents another immediate rotation.

---

### User Story 5 - See Degraded Pool Semantics Everywhere (Priority: P2)

Operators can see whether the pool is `healthy`, `degraded`, or `down` from `/pool`, CLI status, Prometheus metrics, and the dashboard.

**Why this priority**: Healthy count alone hides duplicate IPs, stale state, and recent recovery failures.

**Independent Test**: Create duplicate healthy public IP state and verify `/pool` snapshot plus metrics show degraded reason.

**Acceptance Scenarios**:

1. **Given** duplicate public IPs among healthy instances, **When** `/pool` is rendered, **Then** `pool_status` is `degraded`.
2. **Given** stale state, recovery timeout, proxy failure, or too few healthy backends, **When** metrics are rendered, **Then** the active degraded reason is exposed.
3. **Given** a down pool, **When** status surfaces render, **Then** operators see `pool_status: down`.

## Edge Cases

- No configured instances returns `down` with stale/too-few-healthy reasons.
- Unauthorized or unsupported gluetun control endpoints still refresh state as operator-visible failure.
- Cached status endpoint 404/405 still triggers autodetect retry.
- Expired persisted failure cooldown is normalized to no active cooldown after restart.
- Diagnostics must not print `.env`, `.env.local`, provider credentials, or API key values.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide `chamosel.py doctor` and `chamosel.py doctor --json`.
- **FR-002**: Doctor MUST check compose visibility, controller `/health`, `/pool?fresh=1`, HAProxy stats port, healthy backend count, `.env.local` presence, and image freshness mode.
- **FR-003**: Doctor MUST NOT expose secret values.
- **FR-004**: Doctor MUST report a `repair_decision` when the pool is degraded.
- **FR-005**: Controller MUST mark loaded persisted instance state as stale until refreshed.
- **FR-006**: `/pool` MUST include `pool_status`, `state_fresh`, `degraded_reasons`, and per-instance `state_fresh`.
- **FR-007**: Expired persisted cooldown MUST NOT appear active after restart.
- **FR-008**: `/rotate/all` MUST rotate eligible backends in bounded batches with defaults batch size two and delay two seconds.
- **FR-009**: `/rotate/all` response MUST retain aggregate fields and add `batch_count` and `timed_out_count`.
- **FR-010**: Pool MUST be degraded for duplicate public IPs, stale state, recent recovery/proxy rotation failures, or fewer than the configured healthy threshold.
- **FR-011**: Controller MUST schedule one non-forced background repair rotation for duplicate public IPs when an eligible duplicate backend is not in cooldown or duplicate-repair retry backoff.
- **FR-012**: `/metrics`, dashboard, and `status` MUST expose pool status/state freshness.
- **FR-013**: Docs MUST explain doctor vs verify-leaks vs stress and recommended Surfshark live config.

### Key Entities

- **DoctorReport**: Top-level diagnostic result with `ok`, pool counts/status, and secret-safe check details.
- **PoolSnapshot**: Controller state returned by `/pool`, including aggregate status, freshness, and degraded reasons.
- **RotationBatchResult**: `/rotate/all` response with eligibility, skip, success/failure, timeout, cooldown, and batch counts.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Unit tests cover stale restart state, expired cooldown restart, duplicate IP degraded state, batched rotate/all, metrics, and doctor secret safety.
- **SC-002**: `/rotate/all` can skip cooling backends while rotating eligible backends in batches of two by default.
- **SC-003**: Operators can determine `healthy|degraded|down` from CLI, `/pool`, metrics, and dashboard without reading logs.
- **SC-004**: `doctor --json` emits no known API key or provider secret from config/env files.
- **SC-005**: Duplicate public IP repair schedules one rotation and respects cooldown.

## Assumptions

- Controller remains stdlib-only.
- Docker Compose remains the deployment mode.
- `pool_degraded_min_healthy: auto` means all configured backends are expected healthy, while zero healthy means down.
- Live validation should remain conservative for Surfshark and avoid unnecessary rotation pressure.
