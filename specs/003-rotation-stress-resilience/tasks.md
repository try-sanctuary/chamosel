# Tasks: Rotation Stress Resilience

**Input**: Design documents from `specs/003-rotation-stress-resilience/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required by the implementation plan and constitution for controller API behavior, persisted state, metrics, CLI stress workflow, and secret-safe output.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the exact baseline and reusable test scaffolding before changing runtime behavior.

- [X] T001 Review existing rotation, pool, metrics, and leak-verification test coverage in tests/test_controller.py and tests/test_verify_leaks.py
- [X] T002 [P] Add reusable controller test helpers for simulated rotation outcomes and frozen time in tests/test_controller.py
- [X] T003 [P] Add reusable CLI stress workflow test helpers for mocked verify/rotate calls in tests/test_verify_leaks.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared controller state, labels, and safety guarantees needed by all user stories.

**Critical**: No user story work can begin until this phase is complete.

- [X] T004 Define stable rotation outcome constants and aggregate mass-rotation outcome constants in controller/controller.py
- [X] T005 Extend per-instance state defaults, load, save, and snapshot fields for latest rotation attempt and cooldown metadata in controller/controller.py
- [X] T006 [P] Add state default and state persistence regression tests for new rotation/cooldown fields in tests/test_controller.py
- [X] T007 Implement cooldown helper methods for start, expiry, remaining time, and forced bypass accounting in controller/controller.py
- [X] T008 [P] Add secret-safety regression tests for new rotation/cooldown/stress outputs in tests/test_controller.py and tests/test_verify_leaks.py

**Checkpoint**: Foundation ready. User story implementation can start.

---

## Phase 3: User Story 1 - Protect Mass Rotation From Repeated Recovery Failures (Priority: P1) MVP

**Goal**: Mass rotation skips backends in failure cooldown, continues rotating eligible backends, and returns a partial-success summary.

**Independent Test**: Simulate one backend entering recovery timeout, request mass rotation twice, and verify the second request skips the cooling backend while eligible backends continue.

### Tests for User Story 1

- [X] T009 [P] [US1] Add failing unit test for recovery_timeout starting a backend cooldown in tests/test_controller.py
- [X] T010 [P] [US1] Add failing unit test for POST /rotate/all skipping cooling backends while rotating eligible backends in tests/test_controller.py
- [X] T011 [P] [US1] Add failing unit test for named forced rotation bypassing cooldown and reporting the bypass in tests/test_controller.py

### Implementation for User Story 1

- [X] T012 [US1] Record failure cooldown when recovery_timeout or proxy_failure occurs during rotate_instance in controller/controller.py
- [X] T013 [US1] Implement cooldown-aware eligible backend selection for rotate_one_random and automatic rotation in controller/controller.py
- [X] T014 [US1] Replace inline POST /rotate/all list handling with a rotate_all aggregate function in controller/controller.py
- [X] T015 [US1] Add aggregate counts for eligible, skipped, success, unchanged, failure, and cooldown results to rotate_all responses in controller/controller.py
- [X] T016 [US1] Add cooldown remaining, cooldown reason, and forced bypass fields to rotation responses in controller/controller.py
- [X] T017 [US1] Run the US1 controller tests in tests/test_controller.py and confirm cooldown skipping and partial success pass

**Checkpoint**: User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - Understand Rotation Outcomes Without Guesswork (Priority: P2)

**Goal**: Operators can distinguish changed IP, healthy unchanged IP, recovery timeout, proxy failure, cooldown skip, unhealthy, unauthorized, and unsupported-control outcomes through responses, pool state, metrics, dashboard, and CLI status.

**Independent Test**: Simulate each outcome and verify stable labels appear in controller responses, `/pool`, `/metrics`, dashboard HTML, and CLI status output without secrets.

### Tests for User Story 2

- [X] T018 [P] [US2] Add failing unit test for healthy_ip_unchanged outcome when backend recovers with the same public IP in tests/test_controller.py
- [X] T019 [P] [US2] Add failing unit test for proxy_failure outcome when backend health recovers but proxied verification fails in tests/test_controller.py
- [X] T020 [P] [US2] Add failing metrics tests for latest outcome labels and active cooldown gauges in tests/test_controller.py
- [X] T021 [P] [US2] Add failing CLI status output test for latest outcome and cooldown display in tests/test_verify_leaks.py

### Implementation for User Story 2

- [X] T022 [US2] Update wait_for_recovery result handling to distinguish changed IP, unchanged IP, recovery timeout, and proxy verification failure in controller/controller.py
- [X] T023 [US2] Record healthy_ip_unchanged as a degraded rotation outcome without incrementing changed-IP rotation counters in controller/controller.py
- [X] T024 [US2] Add operator-safe latest outcome, message, old IP, new IP, and attempt timestamp recording in controller/controller.py
- [X] T025 [US2] Expose cooldown and latest rotation fields in STATE.snapshot and GET /pool responses in controller/controller.py
- [X] T026 [US2] Expose per-outcome counters, latest outcome labels, active cooldown state, and cooldown remaining seconds in render_metrics in controller/controller.py
- [X] T027 [US2] Show latest outcome and cooldown state in render_dashboard in controller/controller.py
- [X] T028 [US2] Show latest outcome and cooldown state in cmd_status output in chamosel.py
- [X] T029 [US2] Run US2 tests in tests/test_controller.py and tests/test_verify_leaks.py and confirm outcome observability passes

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - Run Repeatable Stress Validation (Priority: P3)

**Goal**: Operators can run repeatable leak-only and rotation stress workflows with final reports, safe defaults, and documentation.

**Independent Test**: Run mocked CLI stress tests for leak-only and rotation modes, then follow the quickstart with a five-backend live pool when credentials are available.

### Tests for User Story 3

- [X] T030 [P] [US3] Add failing CLI parser test for chamosel.py stress --iterations, --mode, --target, --timeout, and --out-dir in tests/test_verify_leaks.py
- [X] T031 [P] [US3] Add failing leak-only stress test proving no rotation endpoint is called and report fields are populated in tests/test_verify_leaks.py
- [X] T032 [P] [US3] Add failing rotation stress test proving rotate/all outcomes, partial success count, and cooldown skip count are summarized in tests/test_verify_leaks.py

### Implementation for User Story 3

- [X] T033 [US3] Add stress report data construction and summary rendering helpers in chamosel.py
- [X] T034 [US3] Implement leak-only stress loop using existing verify_leaks behavior in chamosel.py
- [X] T035 [US3] Implement rotation stress loop using controller rotate/all responses and optional leak verification in chamosel.py
- [X] T036 [US3] Add stress action and options to build_parser and main dispatch in chamosel.py
- [X] T037 [US3] Document conservative Surfshark live defaults and stress commands in README.md
- [X] T038 [US3] Update validation expectations if command names or report fields changed in specs/003-rotation-stress-resilience/quickstart.md
- [X] T039 [US3] Run US3 CLI tests in tests/test_verify_leaks.py and confirm leak-only and rotation stress summaries pass

**Checkpoint**: All user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, docs consistency, and safety review across all stories.

- [X] T040 [P] Review controller contract alignment against specs/003-rotation-stress-resilience/contracts/controller-rotation.md and update controller/controller.py if gaps remain
- [X] T041 [P] Review stress contract alignment against specs/003-rotation-stress-resilience/contracts/stress-validation.md and update chamosel.py if gaps remain
- [X] T042 Run syntax validation with `.venv/bin/python -m py_compile chamosel.py controller/controller.py` for chamosel.py and controller/controller.py
- [X] T043 Run the full test suite with `.venv/bin/python -m unittest discover -s tests -v` for tests/
- [X] T044 Run whitespace validation with `git diff --check` for the repository
- [X] T045 Run secret-output scan for provider credentials, GLUETUN_API_KEY, and WIREGUARD_PRIVATE_KEY references in README.md, chamosel.py, controller/controller.py, and tests/
- [X] T046 If live credentials are available, run the quickstart live leak-only stress validation and record pass/fail notes in specs/003-rotation-stress-resilience/quickstart.md
- [X] T047 If live credentials are available, run the quickstart live rotation stress validation and record provider recovery/cooldown notes in specs/003-rotation-stress-resilience/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies; can start immediately.
- **Phase 2 Foundational**: Depends on Setup completion and blocks all user stories.
- **Phase 3 US1**: Depends on Foundational; delivers MVP.
- **Phase 4 US2**: Depends on Foundational and can be developed after or alongside US1, but final metrics/pool semantics should respect US1 cooldown fields.
- **Phase 5 US3**: Depends on Foundational and benefits from US1/US2 outcomes for rotation-mode stress reporting.
- **Phase 6 Polish**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational; no dependency on US2 or US3.
- **US2 (P2)**: Can start after Foundational; integrates most cleanly after US1 field names are settled.
- **US3 (P3)**: Can start after Foundational for leak-only mode; rotation mode depends on US1 aggregate outcomes and US2 stable labels.

### Within Each User Story

- Tests must be written first and fail before implementation.
- Controller state changes must precede response, metrics, and dashboard changes.
- CLI report helpers must precede parser dispatch and README examples.
- Story validation must run before moving to the next priority unless intentionally working in parallel.

## Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T006 and T008 can run in parallel after T004 and T005 are understood.
- T009, T010, and T011 can run in parallel because they are separate US1 test cases.
- T018, T019, T020, and T021 can run in parallel because they target separate observability tests.
- T030, T031, and T032 can run in parallel because they target separate CLI stress cases.
- T040 and T041 can run in parallel during polish.

## Parallel Example: User Story 1

```text
Task: "T009 [P] [US1] Add failing unit test for recovery_timeout starting a backend cooldown in tests/test_controller.py"
Task: "T010 [P] [US1] Add failing unit test for POST /rotate/all skipping cooling backends while rotating eligible backends in tests/test_controller.py"
Task: "T011 [P] [US1] Add failing unit test for named forced rotation bypassing cooldown and reporting the bypass in tests/test_controller.py"
```

## Parallel Example: User Story 2

```text
Task: "T018 [P] [US2] Add failing unit test for healthy_ip_unchanged outcome when backend recovers with the same public IP in tests/test_controller.py"
Task: "T020 [P] [US2] Add failing metrics tests for latest outcome labels and active cooldown gauges in tests/test_controller.py"
Task: "T021 [P] [US2] Add failing CLI status output test for latest outcome and cooldown display in tests/test_verify_leaks.py"
```

## Parallel Example: User Story 3

```text
Task: "T030 [P] [US3] Add failing CLI parser test for chamosel.py stress --iterations, --mode, --target, --timeout, and --out-dir in tests/test_verify_leaks.py"
Task: "T031 [P] [US3] Add failing leak-only stress test proving no rotation endpoint is called and report fields are populated in tests/test_verify_leaks.py"
Task: "T032 [P] [US3] Add failing rotation stress test proving rotate/all outcomes, partial success count, and cooldown skip count are summarized in tests/test_verify_leaks.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundational state and safety work.
3. Complete Phase 3 US1 cooldown and partial `rotate/all`.
4. Stop and validate US1 independently with tests in tests/test_controller.py.
5. Demo with simulated recovery timeout and second mass rotation skip.

### Incremental Delivery

1. Add US1 to protect mass rotation from repeated failure pressure.
2. Add US2 to make every rotation outcome visible and measurable.
3. Add US3 to provide repeatable operator stress workflows and documentation.
4. Run full validation and optional live validation only after automated checks pass.

### Parallel Team Strategy

1. One developer completes controller state foundation.
2. One developer writes US1/US2 controller tests.
3. One developer writes US3 CLI stress tests and docs.
4. Merge by priority order: US1, then US2, then US3.

## Notes

- Every checklist item uses the required `- [X] T###` format.
- `[P]` tasks touch separable tests or review artifacts and can be worked independently.
- Live validation tasks are conditional on credentials and Docker availability; record skipped live checks with a reason.
