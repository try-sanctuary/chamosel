# Tasks: Production Security Hardening

**Input**: Design documents from `/specs/008-prod-security-hardening/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for control-plane, template-rendering, config-parsing, API contract, DNS verification, and generated artifact changes.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm current feature context and baseline validation.

- [X] T001 Verify feature branch and active feature metadata in `.specify/feature.json`
- [X] T002 [P] Review existing security-related tests in `tests/test_generate.py`, `tests/test_controller.py`, and `tests/test_verify_leaks.py`
- [X] T003 [P] Review current generated templates in `templates/docker-compose.yml.j2` and `templates/haproxy.cfg.j2`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared validation and redaction helpers required by all stories.

- [X] T004 Add shared safe-output redaction and secret-file permission helpers in `chamosel.py`
- [X] T005 Add config validation helpers for bind addresses, provider IDs, env keys, HAProxy balance, and image references in `chamosel.py`
- [X] T006 [P] Add controller constants and helpers for rotation-in-progress, read-only refresh mode, and egress target validation in `controller/controller.py`

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Prevent Accidental Public Control Or Proxy Exposure (Priority: P1) MVP

**Goal**: Unsafe controller, proxy, and stats exposure is rejected or protected before deployment artifacts are accepted.

**Independent Test**: Generate loopback config successfully; generate unsafe non-loopback controller/proxy/stats configs and confirm failure with no secret output.

### Tests for User Story 1

- [X] T007 [P] [US1] Add generation tests for independent `proxy_bind` default and non-loopback proxy refusal in `tests/test_generate.py`
- [X] T008 [P] [US1] Add generation tests for non-loopback stats refusal without stats auth/protection in `tests/test_generate.py`
- [X] T009 [P] [US1] Add generation tests for controller auth fail-closed behavior and config validation errors in `tests/test_generate.py`

### Implementation for User Story 1

- [X] T010 [US1] Make `proxy_bind` default independent from `api_bind` in `chamosel.py`
- [X] T011 [US1] Implement exposure policy validation for controller, proxy, and stats in `chamosel.py`
- [X] T012 [US1] Add stats/proxy protective config rendering in `templates/haproxy.cfg.j2` and `templates/docker-compose.yml.j2`
- [X] T013 [US1] Update `config.yml.example` and `README.md` with explicit production exposure settings

**Checkpoint**: User Story 1 is independently testable and closes the P0 exposure risks.

---

## Phase 4: User Story 2 - Make Diagnostics Read-Only And Rotations Safe (Priority: P1)

**Goal**: Diagnostics do not mutate pool state, and same-backend rotations cannot overlap.

**Independent Test**: Fresh diagnostic paths do not schedule repair; overlapping same-backend rotations produce one active operation and one explicit in-progress result.

### Tests for User Story 2

- [X] T014 [P] [US2] Add controller tests proving `/pool?fresh=1` can refresh without scheduling repair in `tests/test_controller.py`
- [X] T015 [P] [US2] Add CLI tests proving `verify-leaks`, `verify-dns`, and doctor use non-mutating fresh reads in `tests/test_verify_leaks.py`
- [X] T016 [P] [US2] Add controller tests for per-instance rotation in-flight rejection and cooldown-respecting named rotation in `tests/test_controller.py`

### Implementation for User Story 2

- [X] T017 [US2] Add read-only refresh control to controller pool refresh paths in `controller/controller.py`
- [X] T018 [US2] Update CLI pool fetch, doctor, leak verification, and DNS verification to request non-mutating fresh state in `chamosel.py`
- [X] T019 [US2] Add per-instance rotation locks and explicit in-progress outcomes in `controller/controller.py`
- [X] T020 [US2] Change named backend rotation default to respect cooldown unless force is explicitly requested in `controller/controller.py`

**Checkpoint**: User Story 2 is independently testable and closes read-triggered mutation plus rotation race risks.

---

## Phase 5: User Story 3 - Protect Secrets And Dashboard Sessions (Priority: P2)

**Goal**: Secrets are permission-protected and redacted, and browser dashboard auth cannot silently mutate via ambient token state.

**Independent Test**: Generated secret files have restrictive permissions; generated output and failures redact secrets; dashboard mutating requests require anti-forgery or explicit auth headers.

### Tests for User Story 3

- [X] T021 [P] [US3] Add tests for generated `.env` permissions and unsafe `.env.local` warnings in `tests/test_generate.py`
- [X] T022 [P] [US3] Add tests confirming generated compose avoids literal local control secrets in `tests/test_generate.py`
- [X] T023 [P] [US3] Add controller auth/session and mutating-request protection tests in `tests/test_controller.py`
- [X] T024 [P] [US3] Add redaction tests for tool, doctor, and verification output in `tests/test_verify_leaks.py`

### Implementation for User Story 3

- [X] T025 [US3] Write generated secret files with restrictive permissions and warn on broad existing secret-file permissions in `chamosel.py`
- [X] T026 [US3] Remove unnecessary literal gluetun API key embedding from generated compose flow in `chamosel.py` and `templates/docker-compose.yml.j2`
- [X] T027 [US3] Harden dashboard login/session handling and mutating POST protection in `controller/controller.py`
- [X] T028 [US3] Apply centralized redaction to compose, doctor, and verification error output in `chamosel.py`

**Checkpoint**: User Story 3 is independently testable and closes secret/session exposure risks.

---

## Phase 6: User Story 4 - Strengthen Verification And Runtime Hardening (Priority: P2)

**Goal**: Verification fails closed on incomplete evidence and runtime hardening gaps are visible before production.

**Independent Test**: DNS verification fails on missing evidence; unsafe egress targets are rejected; doctor reports mutable image and runtime hardening warnings.

### Tests for User Story 4

- [X] T029 [P] [US4] Add DNS fail-closed tests for missing connection IP and strict ASN evidence in `tests/test_verify_leaks.py`
- [X] T030 [P] [US4] Add egress target validation tests in `tests/test_controller.py` and `tests/test_generate.py`
- [X] T031 [P] [US4] Add doctor/runtime-hardening warning tests for mutable images and missing container hardening in `tests/test_verify_leaks.py`

### Implementation for User Story 4

- [X] T032 [US4] Make DNS verification fail closed on missing connection IP and strict ASN evidence in `chamosel.py`
- [X] T033 [US4] Validate egress verification targets and disable ambient proxy use for gluetun control calls in `controller/controller.py`
- [X] T034 [US4] Add container hardening settings to compatible services in `controller/Dockerfile` and `templates/docker-compose.yml.j2`
- [X] T035 [US4] Add mutable image and runtime-hardening warnings to doctor/generation output in `chamosel.py`

**Checkpoint**: User Story 4 is independently testable and strengthens release validation confidence.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, compatibility, and full validation.

- [X] T036 [P] Update `README.md` with production security hardening migration notes, public proxy warnings, stats auth, read-only diagnostics, and secret-file permissions
- [X] T037 [P] Update `specs/008-prod-security-hardening/quickstart.md` with final validation commands and expected outcomes
- [X] T038 Run `.venv/bin/python -m py_compile chamosel.py controller/controller.py`
- [X] T039 Run `.venv/bin/python -m unittest discover -s tests -v`
- [X] T040 Run `git diff --check`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (P1)**: Depends on Foundational and is MVP.
- **User Story 2 (P1)**: Depends on Foundational; can run after or alongside US1 if file conflicts are coordinated.
- **User Story 3 (P2)**: Depends on Foundational and should follow US1/US2 for fewer auth/config conflicts.
- **User Story 4 (P2)**: Depends on Foundational and can run after US2.
- **Polish**: Depends on selected user stories being complete.

### Parallel Opportunities

- T002 and T003 can run in parallel.
- T007, T008, and T009 can run in parallel.
- T014, T015, and T016 can run in parallel.
- T021, T022, T023, and T024 can run in parallel.
- T029, T030, and T031 can run in parallel.
- T036 and T037 can run in parallel.

## Implementation Strategy

### MVP First

1. Complete T001-T006.
2. Complete US1 T007-T013.
3. Run relevant generation tests to confirm no accidental public controller/proxy/stats exposure.

### Full Production Hardening

1. Complete MVP.
2. Complete US2 to make diagnostics and rotations safe.
3. Complete US3 to protect secrets and dashboard sessions.
4. Complete US4 to harden verification and runtime diagnostics.
5. Complete final validation T036-T040.

## Notes

- Tests for each story should be added before implementation changes.
- Any live validation not run must be recorded with the reason.
