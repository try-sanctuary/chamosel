# Tasks: Control Plane Hardening

**Input**: Design documents from `specs/001-control-plane-hardening/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required for this feature because it changes control-plane security,
template rendering, config parsing, controller API contracts, metrics semantics,
and generated artifacts.

**Organization**: Tasks are grouped by user story to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the minimal test harness and fixtures needed to validate the
feature without Docker or live VPN credentials.

- [X] T001 Create the `tests/` package with `tests/__init__.py`
- [X] T002 [P] Add generation test fixture helpers for temporary configs, `.env`, and generated files in `tests/test_generate.py`
- [X] T003 [P] Add controller import/reset helper scaffolding for environment-isolated controller tests in `tests/test_controller.py`
- [X] T004 [P] Add a YAML round-trip helper for generated Compose assertions in `tests/test_generate.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create stable implementation seams shared by all user stories.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Refactor `chamosel.py` file writes into small helpers for `.env`, `docker-compose.yml`, and `haproxy.cfg` so generation tests can isolate output paths
- [X] T006 Refactor `chamosel.py` key resolution into a function that returns the effective key and source without logging or exposing secret values
- [X] T007 Add controller status constants and outcome constants in `controller/controller.py`
- [X] T008 Add a `last_error` field and canonical `status` field to the per-instance state initialization in `controller/controller.py`
- [X] T009 Add state update methods for status, error category, and status-path clearing in `controller/controller.py`
- [X] T010 Add a shared response builder for rotation outcomes in `controller/controller.py`

**Checkpoint**: Shared seams exist; user story implementation can proceed.

---

## Phase 3: User Story 1 - Safe Default Startup (Priority: P1) MVP

**Goal**: Generated configuration uses one effective control key, binds operator
endpoints to localhost by default, fails on key conflicts, and preserves provider
environment values exactly.

**Independent Test**: Generate from sample configs and assert the key, bind, and
provider-value contracts without starting Docker.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T011 [P] [US1] Add a test that `global_settings.api_key` is written to generated `.env` and used by controller and gluetun output in `tests/test_generate.py`
- [X] T012 [P] [US1] Add a test that different `global_settings.api_key` and existing `.env` keys fail generation without printing either secret in `tests/test_generate.py`
- [X] T013 [P] [US1] Add a test that default controller and stats port bindings render as `127.0.0.1` in `docker-compose.yml` in `tests/test_generate.py`
- [X] T014 [P] [US1] Add a test that explicit remote bind config renders only when configured in `tests/test_generate.py`
- [X] T015 [P] [US1] Add a test with at least 10 provider environment values containing special characters that round-trip through generated Compose YAML in `tests/test_generate.py`

### Implementation for User Story 1

- [X] T016 [US1] Update `resolve_api_key` in `chamosel.py` to detect `.env` versus `global_settings.api_key` conflicts and exit before writing stack files
- [X] T017 [US1] Update `resolve_api_key` in `chamosel.py` to persist a config-supplied key to `.env` when no conflicting `.env` key exists
- [X] T018 [US1] Add `api_bind` and `stats_bind` defaults to `DEFAULTS` in `chamosel.py`
- [X] T019 [US1] Pass `api_bind` and `stats_bind` into the Compose template render call in `chamosel.py`
- [X] T020 [US1] Change controller and HAProxy stats port bindings in `templates/docker-compose.yml.j2` to use `{{ api_bind }}` and `{{ stats_bind }}` host binds
- [X] T021 [US1] Change gluetun provider environment rendering in `templates/docker-compose.yml.j2` to preserve exact key/value scalars through YAML parsing
- [X] T022 [US1] Update `env_for` in `chamosel.py` to return structured environment key/value data instead of fragile `KEY=value` strings
- [X] T023 [US1] Update `config.yml.example` with `api_bind: 127.0.0.1`, `stats_bind: 127.0.0.1`, and warning comments for remote exposure
- [X] T024 [US1] Update README quick start and notes in `README.md` to explain localhost operator binds, config key conflict behavior, and explicit remote exposure
- [X] T025 [US1] Run `python3 -m unittest tests.test_generate` and fix any US1 failures in `chamosel.py` and `templates/docker-compose.yml.j2`

**Checkpoint**: US1 can be validated independently by generation tests and
manual inspection of generated files.

---

## Phase 4: User Story 2 - Reliable Pool Health During Changes (Priority: P2)

**Goal**: Controller health detection recovers stale gluetun status-path cache
entries and polling remains timely when instances are down.

**Independent Test**: Simulate changed status routes and multiple unreachable
instances with mocked controller calls, then assert pool state and timing.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T026 [P] [US2] Add a test that a stale cached status path is cleared and supported status-path detection is retried in `tests/test_controller.py`
- [X] T027 [P] [US2] Add a test that unauthorized control responses set status `unauthorized` and do not keep retrying alternate paths in `tests/test_controller.py`
- [X] T028 [P] [US2] Add a test that unsupported control endpoints set status `unsupported_control` with an operator-visible error in `tests/test_controller.py`
- [X] T029 [P] [US2] Add a test that polling multiple slow/down instances still updates reachable instances within the bounded polling target in `tests/test_controller.py`
- [X] T030 [P] [US2] Add a test that `GET /pool?fresh=1` refreshes statuses with the same stale-cache recovery behavior in `tests/test_controller.py`

### Implementation for User Story 2

- [X] T031 [US2] Update `detect_status_path` in `controller/controller.py` to distinguish unauthorized, unsupported, unreachable, and stale cached path outcomes
- [X] T032 [US2] Update `is_healthy` in `controller/controller.py` to clear stale cached status paths and re-detect supported paths when route or response-shape failures occur
- [X] T033 [US2] Update `get_public_ip` and health refresh logic in `controller/controller.py` to preserve operator-visible `last_error` categories
- [X] T034 [US2] Replace sequential `poll_loop` instance refreshes with bounded concurrent refresh in `controller/controller.py`
- [X] T035 [US2] Update `Handler.do_GET` fresh pool refresh in `controller/controller.py` to reuse the same bounded refresh helper as the background poller
- [X] T036 [US2] Update `State.snapshot` in `controller/controller.py` so `/pool` includes `status` and `last_error` for each instance
- [X] T037 [US2] Update `render_dashboard` in `controller/controller.py` to display canonical status text rather than only healthy/down
- [X] T038 [US2] Run `python3 -m unittest tests.test_controller` and fix any US2 failures in `controller/controller.py`

**Checkpoint**: US2 can be validated independently through controller unit tests
without Docker or live VPN credentials.

---

## Phase 5: User Story 3 - Rotation Results Match Operator Reality (Priority: P3)

**Goal**: Rotation responses, counters, metrics, and pool state count success
only after usable health returns within 30 seconds.

**Independent Test**: Mock rotation command and health recovery paths for success,
timeout, command error, cooldown, and unknown instance outcomes.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T039 [P] [US3] Add a test that rotation success increments success counters only after health becomes usable within 30 seconds in `tests/test_controller.py`
- [X] T040 [P] [US3] Add a test that accepted stop/start commands followed by no usable health return `recovery_timeout` and increment error counters in `tests/test_controller.py`
- [X] T041 [P] [US3] Add a test that command exceptions return `command_error` and do not increment success counters in `tests/test_controller.py`
- [X] T042 [P] [US3] Add a test that unknown instance rotation returns `unknown_instance` without counter changes in `tests/test_controller.py`
- [X] T043 [P] [US3] Add a metrics contract test for success-only rotation counters and failure outcome labels in `tests/test_controller.py`

### Implementation for User Story 3

- [X] T044 [US3] Update `rotate_instance` in `controller/controller.py` to mark the instance `reconnecting` after accepted stop/start commands
- [X] T045 [US3] Add a bounded 30-second recovery wait helper in `controller/controller.py` that checks usable health without restarting containers
- [X] T046 [US3] Update `record_rotation` and related state in `controller/controller.py` to record `success`, `command_error`, `recovery_timeout`, `unauthorized`, and `unsupported_control` outcomes distinctly
- [X] T047 [US3] Update `rotate_one_random`, `/rotate`, `/rotate/<name>`, and `/rotate/all` responses in `controller/controller.py` to return the contract fields `ok`, `outcome`, `elapsed_seconds`, `old_ip`, `new_ip`, and `message`
- [X] T048 [US3] Update `render_metrics` in `controller/controller.py` so success counters count only recovered rotations and error metrics expose outcome labels
- [X] T049 [US3] Update `cmd_rotate` and `cmd_status` output in `chamosel.py` to keep existing readability while showing new outcome/status fields when present
- [X] T050 [US3] Run `python3 -m unittest tests.test_controller` and fix any US3 failures in `controller/controller.py` and `chamosel.py`

**Checkpoint**: US3 can be validated independently through controller rotation
and metrics tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, generated artifact checks, and documentation
alignment across all user stories.

- [X] T051 [P] Update `specs/001-control-plane-hardening/quickstart.md` if implementation names or validation commands differ from the plan
- [X] T052 [P] Update `specs/001-control-plane-hardening/contracts/controller-api.md` if final response field names differ from the implemented contract
- [X] T053 Run `python3 -m py_compile chamosel.py controller/controller.py`
- [X] T054 Run `python3 -m unittest discover -s tests`
- [X] T055 Generate from a temporary safe config with special-character provider values and inspect `docker-compose.yml`, `haproxy.cfg`, and `.env`
- [X] T056 Run `docker compose -f docker-compose.yml config` when Docker Compose is available, or record that Docker validation was not run
- [X] T057 Verify `git status --short` shows no generated `docker-compose.yml`, `haproxy.cfg`, `.env`, or cache files staged for commit

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user stories.
- **US1 Safe Default Startup (Phase 3)**: Depends on Foundational; MVP scope.
- **US2 Reliable Pool Health (Phase 4)**: Depends on Foundational; can proceed after or in parallel with US1 once shared helpers exist.
- **US3 Rotation Results (Phase 5)**: Depends on Foundational and benefits from US2 status helpers; implement after US2 for least rework.
- **Polish (Phase 6)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Independent after Foundational.
- **US2 (P2)**: Independent after Foundational, but shares controller status fields with US3.
- **US3 (P3)**: Depends on controller status/outcome fields from Foundational and is simpler after US2.

### Within Each User Story

- Write tests first and confirm they fail.
- Implement the smallest code path that satisfies that story.
- Run that story's targeted test command before moving to the next story.
- Preserve generated secret redaction and stdlib-only controller constraints.

## Parallel Opportunities

- T002, T003, and T004 can run in parallel.
- US1 tests T011-T015 can run in parallel after T005-T006.
- US2 tests T026-T030 can run in parallel after T007-T009.
- US3 tests T039-T043 can run in parallel after T010.
- T051 and T052 can run in parallel during polish.

## Parallel Example: User Story 1

```bash
# Write generation contract tests together:
Task: "T011 Add config-supplied key propagation test in tests/test_generate.py"
Task: "T013 Add localhost bind default test in tests/test_generate.py"
Task: "T015 Add provider value round-trip test in tests/test_generate.py"
```

## Parallel Example: User Story 2

```bash
# Write controller health behavior tests together:
Task: "T026 Add stale status-path re-detection test in tests/test_controller.py"
Task: "T027 Add unauthorized status test in tests/test_controller.py"
Task: "T029 Add bounded polling test in tests/test_controller.py"
```

## Parallel Example: User Story 3

```bash
# Write rotation outcome tests together:
Task: "T039 Add recovered rotation success test in tests/test_controller.py"
Task: "T040 Add recovery timeout test in tests/test_controller.py"
Task: "T043 Add rotation metrics contract test in tests/test_controller.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 tasks T011-T025.
3. Validate with `python3 -m unittest tests.test_generate`.
4. Stop and inspect generated config behavior before touching controller runtime logic.

### Incremental Delivery

1. US1: Safe generation and secret/bind behavior.
2. US2: Reliable health detection and bounded polling.
3. US3: Rotation recovery accounting and metrics semantics.
4. Polish: docs, quickstart, syntax checks, full unit test suite, optional Docker Compose validation.

### Parallel Team Strategy

After Foundational:

- Developer A: US1 generation and template hardening.
- Developer B: US2 health state and polling behavior.
- Developer C: US3 rotation outcome tests can start once shared outcome constants exist, then implementation follows US2 status helpers.

## Notes

- `[P]` tasks touch different files or isolated test cases and can run in parallel.
- `[US1]`, `[US2]`, and `[US3]` labels map tasks to user stories in `spec.md`.
- Generated files `docker-compose.yml`, `haproxy.cfg`, `.env`, and cache files remain ignored by Git.
- Keep controller runtime dependencies stdlib-only.
