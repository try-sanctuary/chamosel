# Controller Reliability Contract

## GET /pool

Adds:

```json
{
  "pool_status": "healthy|degraded|down",
  "state_fresh": true,
  "degraded_reasons": [],
  "duplicate_repair": {
    "enabled": true,
    "in_flight": [],
    "scheduled_total": 0
  },
  "instances": [
    {"name": "surfshark_0", "state_fresh": true}
  ]
}
```

## POST /rotate/all

Retains aggregate response and adds:

```json
{
  "batch_count": 2,
  "batch_size": 2,
  "batch_delay_seconds": 2,
  "timed_out_count": 1
}
```

## GET /metrics

Adds:

```text
chamosel_pool_status{status="healthy"} 1
chamosel_pool_status{status="degraded"} 0
chamosel_pool_status{status="down"} 0
chamosel_pool_degraded_reason{reason="stale_state"} 1
chamosel_state_fresh 0
chamosel_duplicate_ip_repair_in_flight 1
chamosel_duplicate_ip_repair_scheduled_total 1
```
