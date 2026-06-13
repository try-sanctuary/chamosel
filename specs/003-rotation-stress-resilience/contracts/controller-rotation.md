# Contract: Controller Rotation Resilience

## Scope

This contract describes operator-visible behavior for rotation endpoints, pool state, and metrics after adding rotation stress resilience.

## Stable Rotation Outcomes

Rotation responses and metrics must use stable labels:

- `success`: backend recovered with a changed public IP.
- `healthy_ip_unchanged`: backend recovered and stayed healthy, but public IP did not change.
- `recovery_timeout`: backend did not reach recovered state before timeout.
- `proxy_failure`: backend recovered enough for control/health state but proxied verification failed.
- `cooldown`: backend was skipped because cooldown is active.
- `unhealthy`: backend was not healthy enough to rotate before the attempt.
- `unauthorized`: gluetun control access returned unauthorized.
- `unsupported_control`: no supported gluetun control endpoint is available.
- `control_unreachable`: controller cannot reach gluetun control server.
- `command_error`: stop/start command failed.
- `unknown_instance`: requested backend does not exist.

## POST /rotate

Rotates one eligible backend.

### Response Requirements

- Must skip backends in active cooldown.
- Must prefer eligible backends over cooling-down backends.
- Must return a single rotation response object.
- Must return `cooldown` if no backend is eligible.

## POST /rotate/{name}

Rotates one named backend.

### Response Requirements

- Must support explicit force behavior for named diagnosis.
- If force bypasses cooldown, response must indicate cooldown was bypassed.
- Must not hide changed-IP, unchanged-IP, proxy, timeout, auth, or unsupported-control outcomes.

## POST /rotate/all

Rotates all eligible backends.

### Response Shape

```json
{
  "ok": false,
  "outcome": "partial_success",
  "eligible_count": 4,
  "skipped_count": 1,
  "success_count": 3,
  "unchanged_count": 0,
  "failure_count": 1,
  "cooldown_count": 2,
  "results": [
    {
      "instance": "surfshark_0",
      "ok": true,
      "outcome": "success",
      "old_ip": "198.51.100.10",
      "new_ip": "203.0.113.20",
      "elapsed_seconds": 12.4,
      "message": "rotation recovered with a changed public IP"
    },
    {
      "instance": "surfshark_3",
      "ok": false,
      "outcome": "cooldown",
      "cooldown_remaining_seconds": 74,
      "message": "cooldown active after recovery_timeout"
    }
  ]
}
```

### Response Requirements

- Must not force cooling-down backends by default.
- Must process eligible backends even when some are skipped.
- Must provide aggregate counts that match `results`.
- Must report partial success when results are mixed.

## GET /pool and GET /pool?fresh=1

Pool state must include per-backend rotation observability:

- `last_rotation_outcome`
- `last_rotation_message`
- `last_rotation_attempted`
- `cooldown_until`
- `cooldown_remaining_seconds`
- `cooldown_reason`
- existing health, status, public IP, history, and counters

## GET /metrics

Metrics must expose:

- Total changed-IP rotations.
- Total rotation errors/degraded outcomes.
- Per-outcome counters.
- Per-instance latest outcome labels.
- Per-instance active cooldown state.
- Per-instance cooldown remaining seconds or equivalent numeric signal.

## Dashboard

The dashboard must surface latest outcome and cooldown state enough for an operator to diagnose mixed rotation results without calling raw JSON endpoints.

## Security Requirements

- Responses, metrics, logs, and dashboard HTML must not include provider credentials, control API keys, WireGuard private keys, `.env`, `.env.local`, or generated secret values.
- No new public endpoint exposure is introduced by this contract.
