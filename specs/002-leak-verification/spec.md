# Feature Specification: Leak Verification

**Feature Branch**: `002-leak-verification`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Implement DNS/IP leak verification and safer runtime checks for chamosel from leak-verification-prompt.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verify Pool Exit IPs (Priority: P1)

An operator can run a leak verification workflow and immediately see whether every checked backend is routing requests through a VPN exit IP instead of exposing the host/server IP.

**Why this priority**: This is the core safety promise. Operators need a clear pass/fail result before trusting the proxy pool for scraping or other outbound traffic.

**Independent Test**: Can be tested by running the verification workflow against a mocked or live pool where backend exit IPs differ from the host IP and confirming the result reports success for all checked backends.

**Acceptance Scenarios**:

1. **Given** the host IP is known and all healthy backends return different public proxy IPs, **When** the operator runs leak verification, **Then** the workflow reports PASS and shows every backend as verified.
2. **Given** a healthy backend returns the same public IP as the host, **When** the operator runs leak verification, **Then** the workflow reports FAIL and identifies that backend as leaking the host IP.
3. **Given** the host IP cannot be determined, **When** the operator runs leak verification, **Then** the workflow reports FAIL and exits without claiming backend verification success.

---

### User Story 2 - Inspect Per-Backend Results (Priority: P2)

An operator can inspect a per-backend result table or structured output that shows controller status, controller-reported public IP, probe-observed proxy IP, location/network metadata when available, and a clear result for each backend.

**Why this priority**: A single global PASS/FAIL is not enough to debug partial pool failures. Operators need to know which backend failed and why.

**Independent Test**: Can be tested by supplying mixed backend results and confirming that each backend has its own status, proxy result, leak flag, and failure reason.

**Acceptance Scenarios**:

1. **Given** multiple healthy backends, **When** leak verification completes, **Then** the operator sees one result row or object per backend.
2. **Given** one backend cannot proxy the verification request, **When** leak verification completes, **Then** the overall result is FAIL and that backend includes a specific error reason.
3. **Given** structured output is requested, **When** leak verification completes, **Then** the output contains the direct host IP, target, overall status, and an instances list with stable fields for automation.

---

### User Story 3 - Understand Verification Boundaries (Priority: P3)

An operator can read project documentation that explains what the leak verification proves, what it does not prove, and how client DNS behavior can still bypass proxy safety if clients are configured incorrectly.

**Why this priority**: Leak checks can create false confidence if the tool does not explain DNS, client bypass, and browser/WebRTC limitations.

**Independent Test**: Can be tested by reviewing the documentation and confirming it clearly distinguishes verified pool behavior from client-side/browser/network behaviors outside chamosel's control.

**Acceptance Scenarios**:

1. **Given** an operator reads the leak verification documentation, **When** they configure an HTTP proxy client, **Then** they understand hostnames should be sent through the proxy path.
2. **Given** an operator reads SOCKS guidance, **When** they configure a SOCKS client, **Then** they understand remote DNS resolution is required to avoid local DNS leaks.
3. **Given** an operator relies on a browser or non-proxy traffic, **When** they read the limitations, **Then** they understand those paths require separate hardening and are not proven by this workflow.

### Edge Cases

- Host IP lookup is unreachable, returns malformed data, or returns a non-public address.
- Controller is unreachable, unauthorized, or returns malformed pool data.
- A backend is marked healthy by the controller but cannot proxy the verification target.
- A backend is marked unhealthy, still reconnecting, or missing a public IP.
- Two or more backends return the same VPN exit IP while still differing from the host IP.
- The verification target is blocked, rate-limited, slow, or returns partial metadata.
- Operator requests structured output during a failure and still needs machine-readable failure reasons.
- The workflow must not reveal API keys, WireGuard keys, provider credentials, generated secret files, or environment contents.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide an operator-triggered leak verification workflow for the current chamosel deployment.
- **FR-002**: The workflow MUST determine the direct host public IP before evaluating backend proxy results.
- **FR-003**: The workflow MUST retrieve fresh controller pool state before selecting backend instances to verify.
- **FR-004**: The workflow MUST verify each configured healthy backend independently rather than relying on aggregate load-balanced proxy behavior.
- **FR-005**: The workflow MUST compare each backend's observed proxy IP with the direct host IP.
- **FR-006**: The workflow MUST fail when any checked backend exposes the same IP as the direct host.
- **FR-007**: The workflow MUST fail when any checked backend cannot return a public proxy IP.
- **FR-008**: The workflow MUST fail when the controller is unreachable or cannot provide usable pool state.
- **FR-009**: The workflow MUST treat unhealthy backends as failures by default unless the operator explicitly chooses a mode that excludes them.
- **FR-010**: The workflow MUST show a human-readable per-backend summary with instance name, controller health, controller-reported IP, observed proxy IP, available location/network metadata, and result.
- **FR-011**: The workflow MUST offer structured output suitable for automation, including direct host IP, verification target, overall status, and per-backend result objects.
- **FR-012**: The workflow MUST return a non-success process result whenever the overall leak verification fails.
- **FR-013**: The system MUST document what the workflow verifies and what it cannot guarantee, including browser/WebRTC, local DNS resolution by clients, and traffic that bypasses chamosel.
- **FR-014**: The workflow MUST avoid printing secrets, provider credentials, generated environment contents, API keys, or WireGuard keys in normal output, structured output, errors, and tests.
- **FR-SEC**: System MUST preserve controller/gluetun authentication and avoid exposing operator endpoints publicly unless the spec explicitly defines a protective boundary.
- **FR-OBS**: System MUST expose operator-visible health, rotation, and error state for any feature that affects the running pool.

### Key Entities *(include if feature involves data)*

- **Leak Verification Run**: One operator-triggered check, including target, direct host IP, overall pass/fail result, checked backend count, and failure reasons.
- **Backend Verification Result**: Per-instance result containing instance identity, controller health, controller public IP, observed proxy IP, metadata returned by the verification target, leak status, and error state.
- **Verification Target**: External endpoint used to report the apparent public IP and optional location/network metadata for host and backend requests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can determine PASS or FAIL for a running pool in one command without manually curling each backend.
- **SC-002**: 100% of checked backend failures include an operator-visible reason identifying the affected instance.
- **SC-003**: The workflow returns a non-success process result for 100% of detected host-IP leak cases.
- **SC-004**: Structured output includes the required top-level and per-backend fields in 100% of success and failure cases.
- **SC-005**: Automated tests cover host IP parsing, host-IP leak detection, all-clear success, structured output shape, controller unreachable failure, and secret-safe probe command behavior.
- **SC-006**: Documentation allows an operator to distinguish verified backend exit-IP safety from DNS/client/browser limitations without reading source code.

## Assumptions

- Operators run leak verification from a machine that can reach the chamosel controller and deployment environment.
- The default verification target returns JSON containing a public IP and may optionally return country, region, city, ASN, and ASN organization metadata.
- Duplicate VPN exit IPs across different backends are allowed unless one equals the direct host IP.
- v1 verifies backend proxy path behavior and documentation boundaries; it does not claim to prove every possible external client, browser, WebRTC, or non-proxy traffic path.
- Tests for this feature should be deterministic and must not require live VPN credentials, Docker availability, or external network access.
