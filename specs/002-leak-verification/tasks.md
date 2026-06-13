# Tasks: Leak Verification

**Input**: Design documents from `specs/002-leak-verification/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/verify-leaks.md, quickstart.md

**Tests**: Required by the feature specification. Unit tests must not require Docker, live VPN credentials, or external network access.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish test locations and confirm the CLI implementation surface.

- [X] T001 Inspect existing argparse, controller API helper, compose helper, and test loading patterns in chamosel.py and tests/test_generate.py
- [X] T002 Create leak verification test scaffolding in tests/test_verify_leaks.py using importlib loading consistent with tests/test_generate.py
- [X] T003 Add shared mocked pool/result fixtures for healthy, leaking, unhealthy, malformed, and controller-unreachable cases in tests/test_verify_leaks.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add reusable verification primitives required by all user stories.

**Critical**: No user story work should begin until this phase is complete.

- [X] T004 Add stdlib-only public IP extraction and validation helpers in chamosel.py using ipaddress and JSON response data
- [X] T005 Add timeout and target validation helpers in chamosel.py for the verify-leaks command arguments
- [X] T006 Add a backend probe command builder in chamosel.py that constructs docker compose exec -T controller probe calls without embedding secrets
- [X] T007 Add a probe response normalization helper in chamosel.py that maps target JSON metadata to Backend Verification Result fields
- [X] T008 Add unit tests for public IP parsing, malformed JSON, missing IP, and non-public IP handling in tests/test_verify_leaks.py
- [X] T009 Add unit tests proving backend probe command construction does not include GLUETUN_API_KEY, WireGuard keys, or provider env values in tests/test_verify_leaks.py

**Checkpoint**: Verification primitives are test-covered and ready for story implementation.

---

## Phase 3: User Story 1 - Verify Pool Exit IPs (Priority: P1) (MVP)

**Goal**: Operators can run leak verification and get PASS/FAIL based on direct host IP versus each backend proxy IP.

**Independent Test**: Mock direct IP, controller pool state, and backend probe results; verify success when all proxy IPs differ from host IP and failure when any proxy IP equals host IP.

### Tests for User Story 1

- [X] T010 [US1] Add success test where direct host IP differs from every backend proxy IP in tests/test_verify_leaks.py
- [X] T011 [US1] Add leak failure test where one backend proxy IP equals direct host IP in tests/test_verify_leaks.py
- [X] T012 [US1] Add direct host IP unavailable failure test in tests/test_verify_leaks.py
- [X] T013 [US1] Add controller unreachable failure test in tests/test_verify_leaks.py
- [X] T014 [US1] Add unhealthy backend fails-by-default test in tests/test_verify_leaks.py

### Implementation for User Story 1

- [X] T015 [US1] Add verify_leaks(cfg, target, timeout) orchestration in chamosel.py to fetch direct host IP, call /pool?fresh=1, probe healthy backends, and compute overall ok
- [X] T016 [US1] Add cmd_verify_leaks(cfg, json_output, timeout, target) in chamosel.py with non-zero SystemExit behavior when verification fails
- [X] T017 [US1] Register verify-leaks argparse subcommand with --json, --timeout, and --target flags in chamosel.py
- [X] T018 [US1] Ensure controller unreachable, malformed pool data, direct IP failure, unhealthy backend, missing proxy IP, and host-IP leak failures each produce operator-safe error strings in chamosel.py

**Checkpoint**: User Story 1 is independently functional and provides the MVP PASS/FAIL leak check.

---

## Phase 4: User Story 2 - Inspect Per-Backend Results (Priority: P2)

**Goal**: Operators can inspect per-backend human and JSON results with stable fields and useful failure reasons.

**Independent Test**: Mock mixed backend results and verify each backend has status, controller IP, proxy IP, metadata, leak flag, and error state in human and JSON output.

### Tests for User Story 2

- [X] T019 [US2] Add JSON output shape test with direct_ip, target, ok, verified_count, total_count, error, and instances fields in tests/test_verify_leaks.py
- [X] T020 [US2] Add per-instance metadata mapping test for country, region, city, asn, and asn_org in tests/test_verify_leaks.py
- [X] T021 [US2] Add human output table test covering direct host IP, Verified summary, Leak result, and backend rows in tests/test_verify_leaks.py
- [X] T022 [US2] Add mixed backend failure reason test proving each failed backend includes its own error in tests/test_verify_leaks.py

### Implementation for User Story 2

- [X] T023 [US2] Add stable leak verification result dictionaries in chamosel.py matching contracts/verify-leaks.md
- [X] T024 [US2] Add JSON renderer for leak verification results in chamosel.py that preserves the contract shape for success and failure
- [X] T025 [US2] Add human table renderer in chamosel.py with instance, status, controller IP, proxy IP, country, ASN, and result columns
- [X] T026 [US2] Wire cmd_verify_leaks output selection so --json prints one JSON object and default mode prints the human table in chamosel.py

**Checkpoint**: User Stories 1 and 2 both work independently; automation and human debugging have stable output.

---

## Phase 5: User Story 3 - Understand Verification Boundaries (Priority: P3)

**Goal**: Operators understand what the command verifies and what remains outside its guarantee.

**Independent Test**: Review README and CLI help to confirm usage, examples, DNS/client/browser limitations, and secret-safe guidance are documented.

### Tests for User Story 3

- [X] T027 [US3] Add CLI help test proving verify-leaks, --json, --timeout, and --target are documented without secrets in tests/test_verify_leaks.py
- [X] T028 [US3] Add README documentation presence test or checklist note covering Leak Verification examples and limitations in tests/test_verify_leaks.py or quickstart.md

### Implementation for User Story 3

- [X] T029 [US3] Add README Leak Verification section with python3 chamosel.py verify-leaks and --json examples in README.md
- [X] T030 [US3] Document verified guarantees in README.md: host IP differs from proxy exit IPs, each backend reaches target through VPN, and controller/backend health agrees
- [X] T031 [US3] Document limitations in README.md: browser WebRTC, local DNS resolution by clients, SOCKS clients requiring remote DNS behavior such as socks5h://, and traffic bypassing chamosel

**Checkpoint**: Operators can use the feature without over-trusting what it proves.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, safety review, and cleanup across all stories.

- [X] T032 Run python3 -m py_compile chamosel.py controller/controller.py and fix any syntax errors
- [X] T033 Run python3 -m unittest discover -s tests -v and fix any failing tests
- [X] T034 Run git diff --check and fix any whitespace issues
- [X] T035 [P] Review chamosel.py output/error paths to confirm they do not print .env, .env.local, GLUETUN_API_KEY, WireGuard private keys, VPN credentials, or generated compose secret values
- [X] T036 [P] Review README.md and specs/002-leak-verification/quickstart.md for consistency with implemented flags, default target, timeout wording, and validation commands
- [X] T037 Live validation passed with local Docker/VPN stack: python3 chamosel.py verify-leaks and python3 chamosel.py verify-leaks --json both verified 10/10 backends with leak_detected=false

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion and delivers the MVP.
- **User Story 2 (Phase 4)**: Depends on Foundational completion and can be developed after or alongside US1 once shared result structures are clear.
- **User Story 3 (Phase 5)**: Depends on the CLI flag/output contract and can be completed after US1/US2 behavior is stable.
- **Polish (Phase 6)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1 Verify Pool Exit IPs**: No dependency on other stories after Foundational.
- **US2 Inspect Per-Backend Results**: Uses the run/result data generated by US1 but remains independently testable with mocked results.
- **US3 Understand Verification Boundaries**: Depends on final command flags and behavior from US1/US2 for accurate documentation.

### Within Each User Story

- Write tests first and confirm they fail before implementation.
- Implement the smallest code path that satisfies the story.
- Run targeted tests for the story before moving to the next priority.
- Keep output secret-safe at every failure and render path.

## Parallel Opportunities

- T035 and T036 can run in parallel during polish because they review different files and concerns.
- Most test-writing tasks intentionally are not marked [P] because they edit the same file, tests/test_verify_leaks.py.

## Parallel Example: Polish

```bash
Task: "T035 Review chamosel.py output/error paths to confirm they do not print secrets"
Task: "T036 Review README.md and specs/002-leak-verification/quickstart.md for consistency"
```

## Sequential Example: User Story 1

```bash
Task: "T010 [US1] Add success test where direct host IP differs from every backend proxy IP in tests/test_verify_leaks.py"
Task: "T011 [US1] Add leak failure test where one backend proxy IP equals direct host IP in tests/test_verify_leaks.py"
Task: "T015 [US1] Add verify_leaks(cfg, target, timeout) orchestration in chamosel.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Write and satisfy US1 tests T010 through T014.
3. Implement T015 through T018.
4. Run targeted leak verification tests.
5. Stop and validate PASS/FAIL behavior before expanding output polish.

### Incremental Delivery

1. Add US1 for the core safety check.
2. Add US2 for stable human/JSON diagnostics.
3. Add US3 documentation and boundary guidance.
4. Complete polish validation and optional live check.

### Validation Commands

```bash
python3 -m py_compile chamosel.py controller/controller.py
python3 -m unittest discover -s tests -v
git diff --check
```

## Notes

- [P] tasks touch distinct concerns or can be drafted independently, but tasks in the same file still need merge discipline.
- Every user story task includes an exact file path.
- Do not add non-stdlib runtime dependencies.
- Do not print secrets in tests, command output, or subprocess error messages.
