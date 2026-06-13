# Tasks: DNS Leak Verification

**Input**: Design documents from `specs/007-dns-leak-verification/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for DNS verification success/failure, JSON shape, parser/help output, docs, and secret-safe output.

**Organization**: Tasks are grouped by user story to keep the first usable DNS check independently testable.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm feature context and existing verification patterns.

- [X] T001 Verify branch, clean tree, and `.specify/feature.json` point at `specs/007-dns-leak-verification`
- [X] T002 [P] Review existing proxy leak verification flow in `chamosel.py`
- [X] T003 [P] Review existing CLI/report tests in `tests/test_verify_leaks.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared DNS probe primitives used by all user stories.

- [X] T004 Add DNS leak constants and probe script builder in `chamosel.py`
- [X] T005 Add DNS leak payload normalization helpers in `chamosel.py`
- [X] T006 Add low-level DNS probe and normalization tests in `tests/test_verify_leaks.py`

---

## Phase 3: User Story 1 - Verify Backend DNS Resolvers (Priority: P1)

**Goal**: Operators can run one command to verify DNS resolvers for healthy backends.

**Independent Test**: Mock pool state and backend DNS probe results, run DNS verification, and confirm passing and suspicious results are reported correctly.

### Tests for User Story 1

- [X] T007 [P] [US1] Add successful DNS verification test in `tests/test_verify_leaks.py`
- [X] T008 [P] [US1] Add suspicious resolver mismatch test in `tests/test_verify_leaks.py`
- [X] T009 [P] [US1] Add unhealthy backend and probe failure tests in `tests/test_verify_leaks.py`

### Implementation for User Story 1

- [X] T010 [US1] Implement `verify_dns_leaks` in `chamosel.py`
- [X] T011 [US1] Implement human DNS report rendering in `chamosel.py`
- [X] T012 [US1] Add `verify-dns` command dispatch and exit behavior in `chamosel.py`

**Checkpoint**: `verify-dns` is independently usable and tested.

---

## Phase 4: User Story 2 - Consume DNS Results in Automation (Priority: P2)

**Goal**: Operators can consume DNS verification through stable JSON output.

**Independent Test**: Run the command with mocked results and `--json`, then assert stable top-level and per-instance fields.

### Tests for User Story 2

- [X] T013 [P] [US2] Add JSON shape and secret-safety tests in `tests/test_verify_leaks.py`
- [X] T014 [P] [US2] Add CLI help/parser tests for `verify-dns` options in `tests/test_verify_leaks.py`

### Implementation for User Story 2

- [X] T015 [US2] Implement `cmd_verify_dns` JSON output in `chamosel.py`
- [X] T016 [US2] Ensure controller auth headers are reused for pool reads in DNS verification in `chamosel.py`

**Checkpoint**: JSON output is stable and automation-safe.

---

## Phase 5: User Story 3 - Document Safe Live Validation (Priority: P3)

**Goal**: README documents safe DNS leak validation and how to interpret suspicious results.

**Independent Test**: Inspect README assertions for command examples, ordering, and no secret values.

### Tests for User Story 3

- [X] T017 [P] [US3] Add README documentation assertions in `tests/test_verify_leaks.py`

### Implementation for User Story 3

- [X] T018 [US3] Update `README.md` command table, validation order, and interpretation notes
- [X] T019 [US3] Update `specs/007-dns-leak-verification/quickstart.md` if implementation details changed

**Checkpoint**: Operators have a safe live validation path.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [X] T020 Run `.venv/bin/python -m py_compile chamosel.py controller/controller.py`
- [X] T021 Run `.venv/bin/python -m unittest discover -s tests -v`
- [X] T022 Run `git diff --check`
- [X] T023 Mark all completed tasks in this file

---

## Dependencies & Execution Order

- Phase 1 before all other work.
- Phase 2 blocks all user stories.
- US1 is the MVP and should complete before US2 and US3.
- US2 depends on US1 report structure.
- US3 depends on final CLI behavior.

## Parallel Opportunities

- T002 and T003 can run in parallel.
- T007, T008, and T009 can be written in parallel after T004-T006.
- T013 and T014 can be written in parallel after US1.

## Implementation Strategy

1. Add shared DNS probe and normalization helpers.
2. Deliver the `verify-dns` MVP with table output.
3. Add JSON automation behavior.
4. Update documentation and run validation.
