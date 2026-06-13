# Contract: Doctor Repair

## Read-only doctor

`doctor` diagnoses the running stack and returns a `repair_decision`, but does not mutate backend state.

## Repair doctor

`doctor --repair` diagnoses first, then requests one safe repair only when the decision is repairable.

Required response fields:

```json
{
  "ok": false,
  "pool_status": "degraded",
  "repair_decision": {
    "action": "repair_requested",
    "reason": "verified_duplicate_proxy_ip",
    "targets": ["surfshark_4"],
    "message": "..."
  },
  "repair_result": {
    "attempted": true,
    "ok": true,
    "outcome": "success"
  }
}
```

Rules:
- `doctor --repair` performs at most one repair action.
- `public_ip_mismatch` with unique verified proxy IPs returns monitor-only and no repair.
- In-flight repair returns `repair_in_progress`.
- Backoff returns `wait_backoff`.
- Unhealthy/unreachable/unauthorized backends require manual inspection.
- The response must remain secret-safe.
