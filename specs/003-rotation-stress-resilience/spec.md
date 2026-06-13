# Feature Specification: Rotation Stress Resilience

**Feature Branch**: `003-rotation-stress-resilience`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Improve rotation resilience after live stress testing: operators need mass rotation to handle provider recovery delays without repeatedly hammering failing backends, clearly distinguish successful IP change from healthy-but-unchanged and recovery/proxy failures, expose partial success and cooldown state, document safe Surfshark live defaults, and provide a repeatable stress verification workflow for leak checks and rotation behavior."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Protect Mass Rotation From Repeated Recovery Failures (Priority: P1)

As an operator running a live proxy pool, I need mass rotation to avoid repeatedly retrying backends that are already failing or slow to recover, so that one unstable tunnel does not keep slowing or destabilizing the whole pool.

**Why this priority**: Live stress testing showed that mass rotation can fail when a provider delays recovery for one backend. Preventing immediate repeated retries is the core operational safety improvement.

**Independent Test**: Can be tested by placing one backend into a recovery-failure state, requesting mass rotation more than once, and verifying that the backend is temporarily skipped while the remaining eligible backends continue to rotate.

**Acceptance Scenarios**:

1. **Given** a backend timed out during recovery, **When** the operator requests mass rotation again before its cooldown expires, **Then** that backend is skipped and the response clearly identifies it as cooling down.
2. **Given** a backend is cooling down and other backends are healthy, **When** mass rotation is requested, **Then** eligible backends are still processed and the operator receives a partial-success result rather than a generic failure.
3. **Given** a backend exits cooldown and is healthy again, **When** the operator requests rotation, **Then** the backend becomes eligible without requiring a manual reset.

---

### User Story 2 - Understand Rotation Outcomes Without Guesswork (Priority: P2)

As an operator diagnosing live provider behavior, I need rotation results to distinguish an IP change, a healthy unchanged IP, proxy failure, recovery timeout, skipped cooldown, and unhealthy backend, so that I know whether the pool is safe, degraded, or simply unchanged.

**Why this priority**: Current rotation results can make different provider behaviors look similar, which makes stress-test results harder to interpret.

**Independent Test**: Can be tested by simulating or observing each rotation outcome and verifying that pool state, metrics, logs, and operator-facing responses use distinct labels.

**Acceptance Scenarios**:

1. **Given** a backend returns to healthy service but keeps the same public IP, **When** rotation finishes, **Then** the outcome is reported as healthy but unchanged rather than as a generic recovery timeout.
2. **Given** a backend proxy cannot serve requests after rotation, **When** the operator reviews pool state, **Then** the outcome identifies proxy failure separately from provider recovery delay.
3. **Given** mass rotation has mixed results, **When** the operator checks current pool state, **Then** each backend has its own latest outcome, timestamp, and actionable status.

---

### User Story 3 - Run Repeatable Stress Validation (Priority: P3)

As an operator preparing changes for live use, I need a documented stress validation workflow for leak checks and rotation behavior, so that I can reproduce the same safety checks after configuration changes or provider updates.

**Why this priority**: Stress validation is useful only when the steps, expected outcomes, and safe defaults are repeatable.

**Independent Test**: Can be tested by following the documented workflow with a five-backend live configuration and confirming that the final report summarizes completed iterations, failures, leak findings, and rotation outcomes.

**Acceptance Scenarios**:

1. **Given** a five-backend live pool, **When** the operator runs the documented leak stress workflow for 100 iterations, **Then** the final report shows all completed iterations, per-backend verification counts, and any leak or availability failures.
2. **Given** the operator runs a rotation stress workflow, **When** one or more backends hit provider recovery limits, **Then** the final report shows skipped cooldowns and partial completion instead of repeatedly retrying the same backend.
3. **Given** the operator reads the project documentation, **When** choosing live Surfshark settings, **Then** they see a conservative default and guidance for when larger pools or frequent mass rotation may be risky.

### Edge Cases

- A backend recovers successfully but receives the same public IP as before.
- A backend is healthy according to pool state but cannot serve proxied verification traffic.
- Several backends enter cooldown at the same time and a mass rotation request has no eligible targets.
- A single-backend pool enters cooldown and the operator attempts mass rotation.
- The operator forces rotation of a backend that is cooling down.
- Pool state is restarted while cooldown or latest outcome information exists.
- Rotation verification target is temporarily unavailable or rate-limited.
- Provider behavior changes and causes slower recovery than the configured timeout.
- The feature must not change provider credentials, generated secrets, public endpoint exposure, or authentication boundaries.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST track a cooldown state for each backend after recovery timeout or repeated rotation failure.
- **FR-002**: System MUST skip cooling-down backends during mass rotation unless the operator explicitly requests a force behavior.
- **FR-003**: System MUST allow healthy, eligible backends to continue rotating when other backends are cooling down or failing.
- **FR-004**: System MUST distinguish at least these latest rotation outcomes per backend: IP changed, healthy but IP unchanged, recovery timeout, proxy failure, skipped due to cooldown, unhealthy before rotation, and unauthorized or unsupported control access.
- **FR-005**: System MUST expose partial-success results for mass rotation, including counts and per-backend outcomes.
- **FR-006**: System MUST expose cooldown start time, expiry time, reason, and latest outcome in operator-visible pool state.
- **FR-007**: System MUST include rotation outcome labels in operator-visible metrics or equivalent operational summaries.
- **FR-008**: System MUST avoid logging or returning provider credentials, control keys, private network keys, or generated secret values in any new stress, rotation, cooldown, or outcome output.
- **FR-009**: System MUST preserve existing control-plane authentication and must not publish any operator endpoint beyond the existing intended host boundary.
- **FR-010**: System MUST provide documented safe live defaults for Surfshark-style provider behavior, including a conservative starting pool size and caution around frequent mass rotation.
- **FR-011**: System MUST provide a repeatable stress validation workflow that records iteration count, backend verification count, failed checks, duplicate public-IP findings, rotation outcomes, and total duration.
- **FR-012**: System MUST make stress validation usable for leak-only validation and for rotation validation as separate operator choices.
- **FR-013**: System MUST define how forced rotation behaves for cooling-down backends and how that behavior is represented in results.
- **FR-014**: System MUST keep cooldown and latest outcome behavior understandable after controller restart, either by preserving necessary state or clearly reporting when state was reset.

### Key Entities

- **Backend Rotation State**: Represents the latest known operational rotation condition for one backend, including current health, current public IP, latest outcome, timestamps, and failure reason.
- **Cooldown Window**: Represents a temporary period during which a backend is skipped by mass rotation after a provider or proxy recovery problem.
- **Mass Rotation Result**: Represents one operator-requested rotation operation across multiple backends, including eligible count, skipped count, success count, failure count, and per-backend details.
- **Stress Validation Report**: Represents the result of a repeatable validation run, including iteration totals, duration, leak findings, backend failures, and rotation outcome distribution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a five-backend live pool, a backend that times out during recovery is skipped on the next mass rotation attempt within its cooldown window 100% of the time unless forced by the operator.
- **SC-002**: In mixed-result mass rotation, eligible healthy backends continue to be processed and the operator receives a per-backend partial-success summary in 100% of attempts.
- **SC-003**: Operators can identify whether each backend changed IP, stayed healthy with the same IP, timed out, failed proxy verification, or was skipped within one pool/status review.
- **SC-004**: A leak-only stress workflow can complete 100 iterations against a five-backend live pool and produce a summary containing iteration count, backend verification count, failures, duplicate IP findings, and total duration.
- **SC-005**: Documentation enables an operator to choose conservative live defaults and understand how to disable or avoid risky mass-rotation stress patterns without reading source code.
- **SC-006**: New rotation and stress outputs expose zero provider credentials, control keys, private network keys, or generated secret values during automated and live validation.

## Assumptions

- The operator is running a local or trusted control plane and already has valid provider credentials configured outside committed files.
- The conservative live default for Surfshark-style testing is five backends unless the operator intentionally increases the pool size.
- Cooldown should apply to automated or mass rotation by default, while explicit force behavior remains an operator decision.
- Existing leak verification remains the baseline safety check before and after rotation stress testing.
- Provider recovery limits are external behavior and cannot be guaranteed by chamosel; the feature should make those limits visible and reduce repeated pressure on unstable backends.
