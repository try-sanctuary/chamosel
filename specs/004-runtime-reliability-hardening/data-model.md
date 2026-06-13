# Data Model: Runtime Reliability Hardening

## InstanceState

- `state_fresh`: boolean, false after controller restart until live refresh.
- Existing rotation/cooldown fields remain persisted.
- Expired cooldown is normalized in snapshots and cooldown info.

## PoolSnapshot

- `pool_status`: `healthy`, `degraded`, or `down`.
- `state_fresh`: true when every configured instance has been refreshed since start.
- `degraded_reasons`: list of reason identifiers.
- `instances`: per-instance state including `state_fresh`.

## RotationAllResult

- Existing fields: `ok`, `outcome`, `eligible_count`, `skipped_count`, `success_count`, `unchanged_count`, `failure_count`, `cooldown_count`, `results`.
- New fields: `batch_count`, `batch_size`, `batch_delay_seconds`, `timed_out_count`.

## DoctorReport

- `ok`: boolean aggregate.
- `configured_instances`, `healthy_backends`, `backend_count`, `pool_status`.
- `checks`: compose, controller, pool, stats port, env file presence, image freshness mode.

## DuplicateRepairState

- `enabled`: whether automatic duplicate-IP repair is enabled.
- `in_flight`: backend names currently being repair-rotated.
- `retry_cooldown_seconds`: retry delay after failed duplicate repair.
- `backoff_remaining`: per-backend duplicate repair backoff remaining seconds.
- `scheduled_total`: total duplicate-IP repair rotations scheduled since controller start.
