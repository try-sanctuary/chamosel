# Research: Rotation Stress Resilience

## Decision: Treat provider recovery failure as a backend cooldown trigger

**Rationale**: Live stress testing showed that repeated mass rotation can keep selecting a backend that is slow to recover or does not receive a changed IP. A cooldown window gives the provider and backend time to stabilize while preserving service from the rest of the pool.

**Alternatives considered**:

- Immediate retry on every mass rotation: rejected because it repeats the stress pattern that caused instability.
- Permanently disable the backend after one failure: rejected because provider delays may be temporary and should recover without manual intervention.
- Only rely on the existing rotate cooldown: rejected because existing cooldown is based on successful rotation timing and does not clearly represent failure recovery state.

## Decision: Split rotation outcomes into operator-actionable labels

**Rationale**: A healthy tunnel with the same public IP, a proxy failure, an auth failure, and a recovery timeout require different operator responses. Distinct labels make `/pool`, `/metrics`, logs, and stress reports useful without reading raw traces.

**Alternatives considered**:

- Keep `success` and `recovery_timeout` only: rejected because it hides important provider behavior and makes stress results misleading.
- Use free-form messages only: rejected because operators and metrics need stable values.
- Treat unchanged IP as success: rejected because the operator requested a fresh exit IP, so unchanged IP is not the same success mode.

## Decision: Mass rotation should return partial success instead of all-or-nothing

**Rationale**: In a multi-backend pool, one cooling-down or failing backend should not hide successful rotations on other backends. A partial summary also makes stress testing measurable.

**Alternatives considered**:

- Abort mass rotation on first failure: rejected because it reduces pool availability and hides later backend state.
- Always force every backend: rejected because this can repeatedly hammer failing provider sessions.
- Report only a list of per-instance results: rejected because operators need aggregate counts for fast triage.

## Decision: Preserve explicit force behavior, but make it visible

**Rationale**: Operators may intentionally override cooldown for a named backend during manual diagnosis. The system should allow that choice while showing that a force bypass happened.

**Alternatives considered**:

- Remove force entirely: rejected because current API semantics include forced named rotation and operators need manual recovery tools.
- Force by default for `rotate/all`: rejected because it conflicts with stress-test findings and would keep retrying failing backends.
- Add hidden force behavior: rejected because it undermines observability and post-incident diagnosis.

## Decision: Use existing state file for cooldown and outcome persistence

**Rationale**: The controller already persists per-backend IP history, counters, status path, and outcomes. Extending this state keeps implementation localized and maintains restart continuity.

**Alternatives considered**:

- Store cooldown only in memory: rejected because restart would erase operator-relevant recovery state without explanation.
- Add a separate persistence file: rejected because it increases config drift and operational surface without a clear benefit.
- Require an external database: rejected as unnecessary for a single-controller Docker Compose deployment.

## Decision: Provide a project stress workflow with leak-only and rotation modes

**Rationale**: Leak-only stress validation passed 100 iterations with five live backends, while rotation stress exposed provider recovery behavior. Keeping those workflows separate lets operators validate safety without causing unnecessary rotation pressure.

**Alternatives considered**:

- Document only ad hoc shell loops: rejected because results are hard to compare and easy to run inconsistently.
- Combine leak and rotation stress into one mandatory workflow: rejected because leak checks should remain low-impact and repeatable.
- Make live stress mandatory for all contributors: rejected because it requires credentials and Docker access that may be unavailable in CI.

## Decision: Document conservative Surfshark defaults without encoding provider-specific limits as guarantees

**Rationale**: Surfshark-style live testing behaved well with five backends for leak verification, while frequent mass rotation showed provider recovery limits. Documentation should recommend a safe starting point while making clear that provider behavior can change.

**Alternatives considered**:

- Claim a hard provider limit: rejected because the provider's published terms are broad and operational limits may be dynamic.
- Default to ten live backends: rejected because stress testing showed weaker rotation stability at higher pressure.
- Avoid provider guidance: rejected because operators need practical starting values for safe live use.
