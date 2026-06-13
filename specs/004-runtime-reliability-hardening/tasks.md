# Tasks: Runtime Reliability Hardening

- [X] T001 Add feature spec and design artifacts.
- [X] T002 Add controller config env vars for rotate/all batching and degraded healthy threshold.
- [X] T003 Mark loaded persisted controller state stale until live refresh.
- [X] T004 Normalize expired cooldowns after restart.
- [X] T005 Add pool summary with `pool_status`, `state_fresh`, and `degraded_reasons`.
- [X] T006 Add bounded batch execution and timeout accounting to `/rotate/all`.
- [X] T007 Add pool status/freshness metrics.
- [X] T008 Add dashboard and CLI status surfacing for pool status/freshness.
- [X] T009 Add `chamosel.py doctor` and `--json`.
- [X] T010 Render new global settings into generated compose.
- [X] T011 Update config example and README.
- [X] T012 Add unit tests for restart stale state, expired cooldown, duplicate IP degraded status, batched rotate/all, metrics, compose rendering, and doctor secret safety.
- [X] T013 Run py_compile and unit test suite.
- [X] T014 Add duplicate public IP self-healing repair scheduling with cooldown protection.
