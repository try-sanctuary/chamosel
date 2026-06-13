# Contract: Stress Validation Workflow

## Scope

This contract describes the operator-facing stress validation workflow for leak checks and rotation behavior.

## Modes

### Leak-only Mode

Purpose: repeatedly verify that backend public IPs differ from the host public IP without rotating tunnels.

Required report fields:

- `mode`: `leak_only`
- `iterations_requested`
- `iterations_completed`
- `backend_count`
- `verified_backend_checks`
- `leak_failures`
- `availability_failures`
- `duplicate_ip_events`
- `total_seconds`

Expected behavior:

- Must not call rotation endpoints.
- Must fail if any backend public IP matches the host public IP.
- Must record controller or verification target availability failures.
- Must produce human-readable progress and a machine-readable final summary.

### Rotation Mode

Purpose: exercise rotation behavior and verify that cooldown/partial-success handling protects the pool under provider recovery delays.

Required report fields:

- All leak-only report fields when leak verification is enabled.
- `rotation_outcomes`
- `mass_rotation_attempts`
- `partial_success_count`
- `cooldown_skip_count`
- `forced_bypass_count`

Expected behavior:

- Must show per-iteration rotation outcomes.
- Must not repeatedly retry cooling-down backends in mass rotation.
- Must report partial success as a first-class result.
- Must keep leak verification and rotation verification separable.

## Operator Inputs

- Iteration count.
- Mode: leak-only or rotation.
- Optional target URL for public-IP verification.
- Optional timeout per verification.
- Optional output directory or report path.
- Optional force behavior for explicit rotation diagnostics.

## Safety Requirements

- Reports must not include provider credentials, control keys, private keys, `.env`, or `.env.local` contents.
- Live documentation must warn operators that frequent mass rotation can hit provider recovery limits.
- Conservative Surfshark-style validation should start with five backends.
