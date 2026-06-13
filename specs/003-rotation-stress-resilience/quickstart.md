# Quickstart: Rotation Stress Resilience

## Prerequisites

- Valid local VPN provider credentials configured outside committed files.
- Docker is available and authenticated if image pulls are needed.
- A generated stack is available from the project configuration.
- For Surfshark-style live testing, start conservatively with five configured backends.

## Automated Validation

Run syntax and unit validation:

```sh
.venv/bin/python -m py_compile chamosel.py controller/controller.py
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected outcome:

- All syntax checks pass.
- Unit tests cover cooldown, partial mass rotation, outcome labels, metrics, pool state, stress workflow summaries, and secret-safe output.
- No whitespace errors are reported.

## Live Leak-Only Stress Validation

Start the pool with a conservative five-backend configuration:

```sh
.venv/bin/python chamosel.py up
.venv/bin/python chamosel.py verify-leaks
```

Run the leak-only stress workflow for 100 iterations:

```sh
.venv/bin/python chamosel.py stress --iterations 100 --mode leak-only
```

Expected outcome:

- The workflow completes 100 iterations unless the controller, backend, or verification target fails.
- Each iteration verifies every healthy backend.
- The final report shows iteration count, backend checks, leak failures, availability failures, duplicate IP events, and total duration.
- No rotation endpoints are called in leak-only mode.

## Live Rotation Stress Validation

Run rotation validation separately from leak-only validation:

```sh
.venv/bin/python chamosel.py stress --iterations 10 --mode rotation
```

Expected outcome:

- Mass rotation reports per-backend outcomes.
- Backends that enter recovery-failure cooldown are skipped on subsequent mass rotations until cooldown expires.
- Eligible backends continue to rotate and the aggregate result reports partial success when outcomes are mixed.
- The final report includes rotation outcome counts and cooldown skip counts.

## Manual Operator Checks

Inspect pool state:

```sh
.venv/bin/python chamosel.py status
curl -s http://127.0.0.1:8800/pool?fresh=1 | jq
```

Expected outcome:

- Each backend shows current health, public IP, latest rotation outcome, and cooldown state when applicable.
- No secret values appear in JSON or CLI output.

Inspect metrics:

```sh
curl -s http://127.0.0.1:8800/metrics
```

Expected outcome:

- Metrics expose total rotations, per-outcome counters, per-instance latest outcome labels, and cooldown state.

## Failure Scenario

Create or simulate a backend that times out during recovery, then request mass rotation twice.

Expected outcome:

- First request records a recovery or proxy failure and starts cooldown.
- Second request skips that backend and continues with eligible backends.
- The response clearly reports skipped cooldown and partial completion.

## Implementation Live Notes

- 2026-06-13: Rebuilt the local controller with `chamosel.py up --no-pull` against the existing five-backend Surfshark WireGuard stack.
- 2026-06-13: Ran `chamosel.py stress --iterations 1 --mode leak-only --timeout 30`; result PASS with 5 backend checks, 0 leak failures, 0 availability failures, and 0 duplicate IP events.
- 2026-06-13: Ran `chamosel.py stress --iterations 1 --mode rotation --no-verify --timeout 30`; result PASS with partial success, 2 successful rotations, and 3 `recovery_timeout` outcomes over about 299 seconds.
- Current live config appears to use `rotate_cooldown: 0`, so recovery timeouts were recorded as latest outcomes but did not produce an active cooldown window in the status output. Use a positive `rotate_cooldown` value to exercise cooldown skipping in live rotation stress.
- Full 100-iteration leak stress and 10-iteration rotation stress were not repeated during implementation to avoid unnecessary provider load; use the commands above when explicitly validating a release candidate.
