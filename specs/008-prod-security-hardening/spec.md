# Feature Specification: Production Security Hardening

**Feature Branch**: `008-prod-security-hardening`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Plan and implement production security hardening from audit P0/P1/P2: fail-closed control access, safe proxy and stats exposure, read-only diagnostics, serialized rotations, cooldown-safe forced rotation, protected secrets, hardened dashboard access, egress/DNS verification correctness, Docker runtime hardening, mutable image warnings, sanitized tool output, and config validation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prevent Accidental Public Control Or Proxy Exposure (Priority: P1)

As an operator preparing a production deployment, I need chamosel to refuse unsafe exposure of control, proxy, and stats surfaces unless I explicitly configure a protective boundary, so a configuration mistake cannot create an unauthenticated control plane or open proxy.

**Why this priority**: This directly addresses release-blocking exposure risks. A publicly reachable control API can rotate or repair the pool, and a publicly reachable proxy can be abused by unauthorized third parties.

**Independent Test**: Generate configuration with loopback bindings and confirm it succeeds, then generate configuration with non-loopback bindings and no protective settings and confirm it fails with clear remediation guidance.

**Acceptance Scenarios**:

1. **Given** default production configuration, **When** the operator generates runtime files, **Then** proxy, controller, and stats surfaces bind locally or require explicit protective configuration before non-loopback exposure is allowed.
2. **Given** the controller endpoint is configured for non-loopback access, **When** controller auth is missing or empty, **Then** generation or startup fails closed with an operator-safe error.
3. **Given** the proxy endpoint is configured for non-loopback access, **When** the operator has not explicitly acknowledged and constrained public proxy exposure, **Then** generation fails instead of creating an open proxy.
4. **Given** the stats endpoint is configured for non-loopback access, **When** no auth or allowlist protects it, **Then** generation fails or the stats endpoint is protected.

---

### User Story 2 - Make Diagnostics Read-Only And Rotations Safe (Priority: P1)

As an operator running health, DNS, leak, and pool checks, I need diagnostic reads to be non-mutating and rotations to be serialized per backend, so checks cannot unexpectedly rotate VPN sessions and concurrent actions cannot corrupt pool state.

**Why this priority**: Production reliability depends on predictable control semantics. A read path that triggers repair violates operator expectations, and overlapping rotations can create inconsistent backend state.

**Independent Test**: Run fresh pool, leak, and DNS checks against a degraded mocked pool and confirm no repair or rotation is scheduled; separately issue overlapping rotations for the same backend and confirm only one proceeds.

**Acceptance Scenarios**:

1. **Given** auto repair is enabled and the pool is degraded, **When** an operator runs a fresh read-only pool check, leak verification, DNS verification, or doctor without repair, **Then** no backend rotation is scheduled.
2. **Given** a backend rotation is already in progress, **When** a second rotate or repair request targets the same backend, **Then** the second request is rejected or skipped with an explicit in-progress outcome.
3. **Given** a named backend rotation is requested without an explicit force signal, **When** that backend is in cooldown, **Then** the request respects cooldown and does not bypass it.
4. **Given** an operator intentionally requests forced rotation, **When** the request is accepted, **Then** the forced bypass is visible in state, metrics, or response output.

---

### User Story 3 - Protect Secrets And Dashboard Sessions (Priority: P2)

As an operator managing live VPN credentials and controller tokens, I need generated secret files, dashboard authentication, and diagnostic output to avoid leaking sensitive data, so production troubleshooting does not expose credentials or bearer tokens.

**Why this priority**: Secret exposure can compromise the control plane and VPN provider credentials even when network bindings are otherwise correct.

**Independent Test**: Generate runtime files with configured secrets, inspect generated files and command output, and confirm secrets are either stored with restrictive permissions, referenced indirectly, or redacted from output.

**Acceptance Scenarios**:

1. **Given** chamosel generates or copies controller and gluetun auth secrets, **When** files are created or updated, **Then** secret-bearing files have restrictive permissions and unsafe existing permissions are reported.
2. **Given** runtime configuration is generated, **When** generated artifacts are inspected, **Then** local control secrets are not unnecessarily embedded as literal values in broad operational files.
3. **Given** dashboard authentication is enabled, **When** an operator logs in through the browser dashboard, **Then** the session handling prevents accidental token exposure through ordinary page scripts and rejects unsafe mutating requests.
4. **Given** Docker, Compose, doctor, or verification commands fail, **When** output is displayed or returned as JSON, **Then** local usernames, home paths, tokens, passwords, and provider secrets are redacted.

---

### User Story 4 - Strengthen Verification And Runtime Hardening (Priority: P2)

As an operator relying on chamosel to verify egress and DNS safety, I need verification to fail closed on incomplete data and production runtime settings to surface supply-chain or container-hardening gaps, so successful checks mean something before release.

**Why this priority**: Verification commands are part of the production go/no-go process. Passing with missing evidence or running mutable, over-privileged containers weakens that process.

**Independent Test**: Feed incomplete DNS verification payloads and mutable image configurations into the system and confirm they produce failed checks or production warnings instead of silent success.

**Acceptance Scenarios**:

1. **Given** DNS verification receives missing or non-public connection IP evidence, **When** the report is generated, **Then** the backend fails verification rather than passing with incomplete data.
2. **Given** strict DNS ASN verification is requested, **When** connection or resolver ASN data is unavailable, **Then** the result fails closed with a clear reason.
3. **Given** egress verification target configuration is unsafe or overly broad, **When** the controller starts or diagnostics run, **Then** the unsafe target is rejected or reported before use.
4. **Given** runtime images use mutable tags or containers run with avoidable privileges, **When** generation or doctor checks run, **Then** the operator receives actionable production hardening warnings.

### Edge Cases

- Loopback-only local development must remain easy to start without forcing public-production settings.
- Private LAN bindings must not be treated as automatically safe without an explicit operator boundary.
- Existing deployments with intentionally public proxy access need a migration path that makes exposure deliberate and auditable.
- Diagnostic commands must remain useful when some backends are unhealthy, unauthorized, cooling down, or reconnecting.
- Rotation serialization must not deadlock the pool when a backend recovery times out.
- Secret permission checks must avoid printing secret values while still naming the affected file and remediation.
- Dashboard auth hardening must still support CLI clients that use explicit auth headers.
- DNS and egress verification failures must distinguish likely leak evidence, missing evidence, target failures, and backend proxy failures.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat public or non-loopback controller exposure without enabled, non-empty controller authentication as a release-blocking configuration error.
- **FR-002**: The system MUST keep proxy binding independent from controller binding and MUST NOT infer public proxy exposure from controller exposure settings.
- **FR-003**: The system MUST refuse or explicitly protect non-loopback proxy exposure unless the operator configures a deliberate protective boundary.
- **FR-004**: The system MUST refuse or explicitly protect non-loopback stats exposure unless the operator configures authentication or an equivalent protective boundary.
- **FR-005**: Diagnostic read operations MUST NOT schedule repair, rotation, cooldown bypass, or other mutating pool actions unless the operator explicitly requests repair.
- **FR-006**: Rotation and repair operations MUST be serialized per backend and MUST report an explicit in-progress outcome for overlapping requests.
- **FR-007**: Named backend rotation MUST respect cooldown by default and require explicit operator intent to bypass cooldown.
- **FR-008**: Forced cooldown bypasses MUST remain observable to operators through response data, status, metrics, or logs.
- **FR-009**: Secret-bearing generated files MUST be created or corrected with restrictive permissions, and unsafe existing permissions MUST be reported without exposing secret values.
- **FR-010**: Generated operational files MUST avoid unnecessary literal embedding of local control secrets when an indirect secret reference can provide the same behavior.
- **FR-011**: Dashboard authentication MUST avoid storing bearer tokens in ordinary script-readable state for mutating requests, or MUST add equivalent protections that prevent cross-site or script-assisted mutation.
- **FR-012**: Mutating controller requests authenticated by browser session state MUST include anti-forgery protection or require explicit auth headers.
- **FR-013**: Tool, doctor, and validation output MUST redact local paths, usernames, token values, passwords, private keys, and provider credentials.
- **FR-014**: DNS verification MUST fail closed when connection IP evidence is missing, malformed, private, or otherwise unverifiable.
- **FR-015**: Strict DNS ASN verification MUST fail closed when required ASN evidence is missing.
- **FR-016**: Egress verification target settings MUST be validated so unsafe schemes, private targets, metadata targets, or unexpected redirects cannot be silently used.
- **FR-017**: Production diagnostics MUST warn when runtime images are mutable tags instead of pinned immutable references.
- **FR-018**: Runtime generation or diagnostics MUST surface missing container hardening controls for services that do not require elevated privileges.
- **FR-SEC**: System MUST preserve controller/gluetun authentication and avoid exposing operator endpoints publicly unless the spec explicitly defines a protective boundary.
- **FR-OBS**: System MUST expose operator-visible health, rotation, and error state for any feature that affects the running pool.

### Key Entities

- **Exposure Policy**: Operator intent and constraints for controller, proxy, and stats host bindings, including whether non-loopback exposure is allowed and how it is protected.
- **Secret File**: A generated or operator-provided file containing control tokens, VPN credentials, or provider secrets; includes path, permission status, and remediation status without secret values.
- **Rotation Guard**: Per-backend state that records whether a rotation or repair is currently active and how cooldown or force decisions are handled.
- **Diagnostic Read**: A pool, doctor, leak, or DNS verification action that observes current state without mutating the pool unless explicitly upgraded to repair.
- **Verification Evidence**: The observable DNS, egress, and metadata facts used to decide whether a backend passes or fails verification.
- **Runtime Hardening Finding**: A warning or failure that identifies mutable images, unnecessary privileges, missing auth, or other production hardening gaps.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of tested unsafe non-loopback controller, proxy, and stats exposure configurations are rejected or protected before deployment artifacts are accepted.
- **SC-002**: 100% of read-only diagnostic commands complete without scheduling repair or rotation in automated tests, including degraded-pool cases.
- **SC-003**: 100% of overlapping same-backend rotation attempts return one active operation and one explicit in-progress or skipped outcome.
- **SC-004**: 100% of secret-safety tests confirm generated output contains no configured token, password, private key, or provider credential values.
- **SC-005**: DNS verification reports fail for 100% of test payloads missing required connection evidence or strict ASN evidence.
- **SC-006**: Production diagnostic output identifies mutable image references and missing runtime hardening controls with actionable remediation text.
- **SC-007**: Existing loopback-only local quick start remains startable without extra public-exposure configuration.

## Assumptions

- The feature targets production safety while preserving local loopback development as the lowest-friction default.
- Non-loopback proxy usage is valid only when the operator deliberately constrains who can reach it.
- Controller remains dependency-light and compatible with the existing deployment model.
- Existing CLI clients can continue to authenticate with explicit headers.
- Live VPN provider credentials are not required for automated tests; live validation can be documented separately when credentials are unavailable.
