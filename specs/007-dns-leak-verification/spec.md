# Feature Specification: DNS Leak Verification

**Feature Branch**: `007-dns-leak-verification`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "007-dns-leak-verification: DNS leak checks, docs, tests, live validation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verify Backend DNS Resolvers (Priority: P1)

As an operator, I want to run a DNS leak check for every healthy backend in the pool, so that I can see which DNS resolvers are observed for each backend before trusting scraper traffic.

**Why this priority**: The project already verifies proxy exit IPs, but DNS resolver visibility is a separate leak class. Operators need this signal before live use.

**Independent Test**: Run the DNS verification command against mocked backend probe results and confirm the output reports per-backend DNS resolver IPs, resolver metadata, conclusions, and pass/fail status without exposing secrets.

**Acceptance Scenarios**:

1. **Given** a healthy backend and a DNS leak service result containing DNS resolver entries, **When** the operator runs DNS verification, **Then** the report lists the backend, observed connection IP, DNS resolver count, resolver details, and an OK result when no suspicious mismatch is detected.
2. **Given** a healthy backend and a DNS leak service result with resolver ASN metadata that differs from the backend connection ASN, **When** the operator runs DNS verification with the default policy, **Then** the report shows a warning but does not fail only because gluetun's default encrypted upstream resolver uses different network metadata.
3. **Given** a healthy backend and a DNS leak service result with resolver ASN metadata that differs from the backend connection ASN, **When** the operator runs DNS verification with strict ASN policy, **Then** the report marks that backend as suspicious and the command exits non-zero.
4. **Given** an unhealthy backend, **When** the operator runs DNS verification, **Then** that backend is skipped with an operator-visible reason and the overall result fails unless all configured backends are healthy and verifiable.

---

### User Story 2 - Consume DNS Results in Automation (Priority: P2)

As an operator, I want JSON output for DNS leak checks, so that I can save live validation artifacts and compare them with IP leak and stress reports.

**Why this priority**: Existing workflows already support `--json` for `verify-leaks`, `doctor`, and `stress`. DNS leak validation needs the same machine-readable behavior.

**Independent Test**: Run DNS verification with mocked results and `--json`; confirm the JSON shape includes a top-level result, per-backend resolver list, suspicious flags, errors, and no provider credentials or auth tokens.

**Acceptance Scenarios**:

1. **Given** multiple backend DNS results, **When** JSON output is requested, **Then** the report includes `ok`, `verified_count`, `total_count`, `instances`, and per-instance DNS resolver details.
2. **Given** a backend probe failure, **When** JSON output is requested, **Then** the failed backend includes a safe error string and no secret values.

---

### User Story 3 - Document Safe Live Validation (Priority: P3)

As an operator, I want README guidance and quick validation commands for DNS leak checks, so that I can run a cautious live test with Surfshark credentials and understand what the result means.

**Why this priority**: DNS leak output can be misread. Documentation must explain that resolver ASN/country mismatch is a suspicion signal, not proof of provider failure in every case.

**Independent Test**: Inspect README and quickstart docs to confirm they distinguish `verify-leaks`, `verify-dns`, `doctor`, and `stress`, and that live validation commands are conservative and secret-safe.

**Acceptance Scenarios**:

1. **Given** a live stack, **When** the operator follows the README, **Then** they can run `doctor`, `verify-leaks`, and `verify-dns` in a safe order without rotating tunnels.
2. **Given** DNS verification reports suspicious resolvers, **When** the operator reads the docs, **Then** they can see that this requires investigation and should not trigger automatic rotation by itself.
3. **Given** the operator wants provider-owned DNS instead of gluetun's default upstream resolver, **When** they configure provider DNS addresses, **Then** generated gluetun services receive explicit DNS upstream env vars while empty settings keep gluetun defaults.

### Edge Cases

- The external DNS leak service is unreachable or returns malformed JSON.
- A backend is unhealthy, unauthorized, still reconnecting, or missing from `/pool?fresh=1`.
- The DNS leak service reports no DNS resolvers.
- DNS resolver entries lack ASN or country metadata.
- DNS resolver ASN differs from the backend connection ASN.
- DNS resolver ASN differs because gluetun is using its default Cloudflare DNS-over-TLS upstream.
- Operator wants Surfshark/provider DNS addresses instead of gluetun default upstreams.
- Duplicate repair rotates a backend away from a duplicated verified proxy IP, but gluetun's public IP remains unchanged or mismatched.
- Controller auth is enabled and CLI commands must authenticate without printing the token.
- Live validation must not rotate tunnels or mutate controller state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an operator command to run DNS leak verification for healthy backends.
- **FR-002**: System MUST use the existing backend proxy path for each DNS leak probe so the observed DNS resolvers correspond to that backend path.
- **FR-003**: System MUST report per-backend observed connection IP, DNS resolver list, resolver count, conclusion text if present, suspicious status, and error state.
- **FR-004**: System MUST return non-zero when any healthy backend cannot be DNS-verified or has a fail-level DNS risk such as a non-global resolver address.
- **FR-005**: System MUST skip unhealthy backends with an explicit operator-visible reason.
- **FR-006**: System MUST support JSON output for DNS leak verification.
- **FR-007**: System MUST keep provider credentials, gluetun API keys, and controller auth tokens out of JSON, tables, errors, logs, and documentation examples.
- **FR-008**: System MUST document a cautious live validation sequence that includes DNS leak verification without forcing rotation.
- **FR-009**: System MUST keep DNS leak verification read-only; it MUST NOT trigger repair or rotation automatically.
- **FR-010**: System MUST include automated tests for successful DNS verification, suspicious resolver detection, probe failure handling, JSON shape, parser/help output, and documentation guidance.
- **FR-011**: System MUST provide a strict ASN mode that returns non-zero when resolver ASN differs from backend connection ASN.
- **FR-012**: System MUST keep gluetun DNS upstream overrides opt-in; empty config MUST leave gluetun defaults unchanged.
- **FR-013**: System MUST support explicit gluetun DNS upstream env generation for named encrypted upstream resolvers and provider plain DNS addresses.
- **FR-014**: Duplicate-IP repair MUST treat a fresh verified proxy IP that differs from the duplicate IP as successful recovery, even when gluetun public IP remains unchanged or mismatched.
- **FR-SEC**: System MUST preserve controller/gluetun authentication and avoid exposing operator endpoints publicly unless the spec explicitly defines a protective boundary.
- **FR-OBS**: System MUST expose operator-visible health, rotation, and error state for any feature that affects the running pool.

### Key Entities

- **DNS Verification Report**: The top-level operator result containing overall status, target service metadata, backend counts, and per-backend DNS verification results.
- **Backend DNS Result**: Per-instance DNS verification state including backend name, controller status, connection IP, DNS resolver entries, suspicious flags, and safe errors.
- **DNS Resolver Entry**: A resolver observed by the DNS leak test, including IP and optional country/ASN metadata.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can run one command to receive DNS leak status for all healthy backends in a running pool.
- **SC-002**: JSON DNS verification output contains all required top-level and per-backend fields in automated tests.
- **SC-003**: Automated tests cover at least one passing DNS result, one suspicious resolver result, one probe failure, and one unhealthy backend.
- **SC-004**: Documentation includes a live validation sequence that runs `doctor`, `verify-leaks`, and DNS verification without exposing secrets.
- **SC-005**: DNS leak verification produces no committed generated artifacts and does not mutate running VPN tunnels.

## Assumptions

- DNS leak verification is a CLI/operator feature, not a controller background poll.
- The default live DNS leak service can be replaced later if the service becomes unavailable.
- Resolver ASN mismatch is treated as a warning by default because gluetun's default Cloudflare DNS-over-TLS upstream can intentionally differ from the backend connection ASN.
- Operators can opt into strict ASN validation when their policy requires resolver ASN to match the backend connection ASN.
- Provider DNS addresses are operator supplied from provider documentation or generated VPN configs; chamosel does not hardcode Surfshark DNS IPs.
- Verified proxy IP is the diversity truth for duplicate repair when it is fresh and error-free.
- This feature does not add automatic repair for DNS leaks.
- Existing controller authentication behavior from feature 006 applies to any controller calls made by DNS verification.
