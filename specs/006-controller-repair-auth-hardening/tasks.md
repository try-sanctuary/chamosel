# Tasks: Controller Repair and Auth Hardening

**Input**: Design documents from `specs/006-controller-repair-auth-hardening/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for controller auth, doctor repair, generated compose/config, and secret-safe output.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm feature context and project guardrails.

- [X] T001 Verify branch, clean tree, and current feature metadata in `.specify/feature.json`
- [X] T002 [P] Review controller auth and repair contracts in `specs/006-controller-repair-auth-hardening/contracts/`
- [X] T003 [P] Review existing auth/doctor/repair code paths in `chamosel.py` and `controller/controller.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared config/auth primitives that all stories use.

- [X] T004 Add controller auth defaults and config resolution in `chamosel.py`
- [X] T005 Add controller auth env rendering in `templates/docker-compose.yml.j2`
- [X] T006 Add controller auth helpers in `controller/controller.py`
- [X] T007 Add config/template tests for controller auth settings in `tests/test_generate.py`

---

## Phase 3: User Story 1 - Protected Operator Endpoints (Priority: P1)

**Goal**: Protected dashboard, pool, metrics, and rotation endpoints reject unauthenticated access when auth is enabled.

**Independent Test**: Enable auth in controller tests, call protected GET/POST routes without and with valid token, and verify expected reject/success behavior.

### Tests for User Story 1

- [X] T008 [P] [US1] Add controller auth rejection/success tests in `tests/test_controller.py`
- [X] T009 [P] [US1] Add CLI auth header and secret-safe output tests in `tests/test_verify_leaks.py`

### Implementation for User Story 1

- [X] T010 [US1] Enforce controller auth on dashboard, pool, metrics, and rotate routes in `controller/controller.py`
- [X] T011 [US1] Attach controller auth credentials to CLI controller calls in `chamosel.py`
- [X] T012 [US1] Add safe warnings/fail-fast behavior for auth disabled on non-loopback bind in `chamosel.py`

**Checkpoint**: Protected endpoint behavior is independently testable.

---

## Phase 4: User Story 2 - Doctor Can Repair Safe Conditions (Priority: P2)

**Goal**: `doctor --repair` diagnoses first and then requests one safe bounded repair action only when conditions are repairable.

**Independent Test**: Simulate duplicate verified proxy IP, duplicate public IP, mismatch-only, in-flight repair, and backoff states and verify doctor repair responses.

### Tests for User Story 2

- [X] T013 [P] [US2] Add controller repair endpoint tests in `tests/test_controller.py`
- [X] T014 [P] [US2] Add `doctor --repair` CLI tests in `tests/test_verify_leaks.py`

### Implementation for User Story 2

- [X] T015 [US2] Add bounded controller repair action route in `controller/controller.py`
- [X] T016 [US2] Add `doctor --repair` CLI flow and JSON/human output in `chamosel.py`
- [X] T017 [US2] Preserve monitor-only behavior for `public_ip_mismatch` in `chamosel.py`

**Checkpoint**: Doctor repair is explicit, bounded, and mismatch-safe.

---

## Phase 5: User Story 3 - Clear Safe Configuration Workflow (Priority: P3)

**Goal**: Operators can configure auth/repair safely from example config and README without exposing secrets.

**Independent Test**: Generate compose from example config and inspect docs/help output for auth/repair guidance without secrets.

### Tests for User Story 3

- [X] T018 [P] [US3] Extend README/help assertions in `tests/test_verify_leaks.py`
- [X] T019 [P] [US3] Extend generated compose assertions in `tests/test_generate.py`

### Implementation for User Story 3

- [X] T020 [US3] Update `config.yml.example` with controller auth and doctor repair settings
- [X] T021 [US3] Update `README.md` with controller auth and `doctor --repair` workflow
- [X] T022 [US3] Ensure generated `.env`/compose output remains secret-safe in `chamosel.py`

**Checkpoint**: Configuration and docs are safe and clear.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [X] T023 Run `.venv/bin/python -m py_compile chamosel.py controller/controller.py`
- [X] T024 Run `.venv/bin/python -m unittest discover -s tests -v`
- [X] T025 Run `git diff --check`
- [X] T026 Update this tasks file to mark all completed tasks

---

## Dependencies & Execution Order

- Phase 1 before all other work.
- Phase 2 blocks all user stories.
- US1 should land before US2 because doctor repair calls protected controller endpoints.
- US3 can run after Phase 2, but final docs should reflect US1 and US2 behavior.

## Parallel Opportunities

- T002 and T003 can run in parallel.
- T008 and T009 can run in parallel.
- T013 and T014 can run in parallel.
- T018 and T019 can run in parallel.

## Implementation Strategy

1. Build the shared auth/config foundation.
2. Deliver protected endpoints as MVP.
3. Add explicit bounded doctor repair.
4. Update docs/config and run validation.
