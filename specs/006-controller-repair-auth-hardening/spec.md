# Feature Specification: Controller Repair and Auth Hardening

**Feature Branch**: `006-controller-repair-auth-hardening`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Doctor should diagnose in order to repair; public_ip_mismatch is temporarily acceptable; /pool?fresh=1 remains enough as the fresh verification trigger; post-rotation egress verification stays configurable; controller API/dashboard authentication is needed; DNS leak verification will be a later feature; live-test report artifacts are not needed."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Protected Operator Endpoints (Priority: P1)

As an operator running chamosel on a server, I want the controller API, dashboard, and metrics endpoints to reject unauthenticated access when controller authentication is enabled, so that external users cannot rotate tunnels or inspect operational state.

**Why this priority**: The controller can change VPN state and expose pool health. Control-plane protection is required before more repair automation is safe.

**Independent Test**: Enable controller authentication, request dashboard, pool, metrics, and rotation endpoints without credentials, then repeat with credentials and confirm only authenticated requests succeed.

**Acceptance Scenarios**:

1. **Given** controller authentication is enabled, **When** an unauthenticated request reaches `/rotate`, `/pool`, `/metrics`, or dashboard, **Then** the request is rejected without exposing operational details.
2. **Given** controller authentication is enabled, **When** a request provides valid credentials, **Then** the protected endpoint behaves as it did before authentication was enabled.
3. **Given** controller authentication is disabled for a local-only development setup, **When** the operator uses existing local commands, **Then** current loopback-only workflows continue to work.

---

### User Story 2 - Doctor Can Repair Safe Conditions (Priority: P2)

As an operator, I want `doctor` to support an explicit repair mode after diagnosis, so that a known safe degraded condition can be repaired from one command without manually deciding which backend to rotate.

**Why this priority**: Operators already treat “doctor” as diagnose-to-heal. Repair must be explicit and bounded so it does not make provider recovery problems worse.

**Independent Test**: Put the pool in a duplicate verified proxy IP or duplicate public IP state, run `doctor --repair`, and confirm the response reports a bounded repair decision without rotating mismatch-only backends.

**Acceptance Scenarios**:

1. **Given** the pool has a duplicate verified proxy IP and a backend is eligible for repair, **When** the operator runs `doctor --repair`, **Then** one repair action is requested and the response identifies the target and outcome.
2. **Given** the pool has only `public_ip_mismatch` while verified proxy IPs are unique, **When** the operator runs `doctor --repair`, **Then** no rotation is requested and the response says the condition is monitor-only.
3. **Given** repair is blocked by cooldown, retry backoff, unhealthy backend, or recovery timeout, **When** the operator runs `doctor --repair`, **Then** the response reports the blocking reason and does not start an unsafe repair loop.

---

### User Story 3 - Clear Safe Configuration Workflow (Priority: P3)

As an operator, I want generated config, compose output, README guidance, and command output to make controller authentication and doctor repair behavior explicit, so that I can safely deploy chamosel on a VPS without guessing which secrets or endpoints are protected.

**Why this priority**: Auth and repair settings affect operational safety. Operators need clear defaults and docs before using them live.

**Independent Test**: Generate the stack from example config, inspect the generated controller settings, and run help/status commands to confirm secrets are not printed and the safe workflow is documented.

**Acceptance Scenarios**:

1. **Given** example configuration, **When** the stack is generated, **Then** controller auth and repair settings are rendered consistently without printing secrets.
2. **Given** the operator reads the README, **When** they follow the documented workflow, **Then** they can choose local-only unauthenticated mode or authenticated remote-safe mode knowingly.
3. **Given** post-rotation egress verification is configured, **When** a rotation completes, **Then** the configured behavior remains visible and testable.

### Edge Cases

- Auth is enabled but no usable secret is configured.
- Auth is disabled while the controller bind address is not loopback.
- A CLI command calls a protected controller endpoint without credentials.
- `doctor --repair` sees a mismatch-only pool state where verified proxy IPs are unique.
- `doctor --repair` sees duplicate IP repair already in flight or in retry backoff.
- One or more backends are unhealthy, unauthorized, unreachable, reconnecting, or in cooldown.
- A repair attempt starts but recovery times out or proxy verification fails.
- Output must remain secret-safe in JSON, human tables, logs, dashboard, and README examples.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support configurable authentication for controller endpoints that expose dashboard, pool state, metrics, or rotation/repair actions.
- **FR-002**: The system MUST reject unauthenticated protected controller requests when authentication is enabled.
- **FR-003**: Valid authenticated requests MUST preserve existing endpoint behavior.
- **FR-004**: CLI commands that call protected controller endpoints MUST be able to authenticate without exposing secrets in command output.
- **FR-005**: The system MUST warn or fail safely when controller authentication is disabled for a non-loopback bind address.
- **FR-006**: `doctor` MUST remain read-only unless an explicit repair mode is requested.
- **FR-007**: `doctor --repair` MUST request at most one bounded repair action per invocation.
- **FR-008**: `doctor --repair` MUST repair duplicate verified proxy IPs first, then fallback duplicate public IPs when verified IPs are unavailable or expired.
- **FR-009**: `doctor --repair` MUST NOT rotate solely for `public_ip_mismatch` when verified proxy IPs are unique and leak state is otherwise acceptable.
- **FR-010**: Repair decisions MUST report `none`, `monitor`, `repair_requested`, `repair_in_progress`, `wait_backoff`, `blocked`, or `manual` with a human-readable reason.
- **FR-011**: Post-rotation egress verification behavior MUST remain configurable and visible in generated configuration and docs.
- **FR-012**: Generated config and compose output MUST pass controller auth and repair settings consistently to the running controller.
- **FR-013**: JSON and human output MUST remain secret-safe.
- **FR-SEC**: System MUST preserve controller/gluetun authentication and avoid exposing operator endpoints publicly unless the spec explicitly defines a protective boundary.
- **FR-OBS**: System MUST expose operator-visible health, rotation, repair, and auth-related state for any feature that affects the running pool.

### Key Entities *(include if feature involves data)*

- **Controller Auth Configuration**: Operator choice for whether controller endpoints require authentication, how the secret is supplied, and which bind addresses are considered safe.
- **Repair Decision**: The result of diagnosis that says whether repair is safe, blocked, monitor-only, already in progress, or manual.
- **Repair Action**: A bounded request to rotate one eligible backend because the pool has a repairable duplicate IP condition.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of protected controller endpoints reject unauthenticated requests when controller authentication is enabled.
- **SC-002**: Existing local unauthenticated workflows continue to pass automated tests when controller authentication is explicitly disabled.
- **SC-003**: `doctor --repair` performs no more than one repair action per invocation in all tested degraded pool states.
- **SC-004**: Mismatch-only pool states are reported as monitor-only and trigger zero repair rotations in automated tests.
- **SC-005**: Automated tests verify secret-safe output for doctor, auth failure, and generated compose/config flows.
- **SC-006**: Operators can identify from README and generated example config how to enable auth, run read-only doctor, and run doctor repair in under five minutes.

## Assumptions

- DNS leak verification is intentionally out of scope for this feature and will be handled separately.
- Live validation report artifacts are not needed and should not be generated by default.
- Local development may keep controller authentication disabled only when controller and stats endpoints remain loopback-bound.
- Existing gluetun control-server API key behavior remains separate from controller operator authentication.
- `/pool?fresh=1` remains the single fresh verification trigger; a separate egress verification endpoint is not needed.
