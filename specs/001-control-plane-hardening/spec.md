# Feature Specification: Control Plane Hardening

**Feature Branch**: `001-control-plane-hardening`

**Created**: 2026-06-12

**Status**: Draft

**Input**: User description: "Fix security, configuration, health detection, polling,
and rotation accounting risks found in the chamosel analysis: config-supplied
control keys must reach both VPN backends and controller, operator endpoints must
not be publicly exposed by default, stats must be protected, provider values must
survive generated configuration safely, cached backend status paths must recover
after version changes, pool polling must remain timely when instances are down,
and successful rotation accounting must reflect actual recovery."

## Clarifications

### Session 2026-06-12

- Q: What should the default exposure policy be for controller API and HAProxy stats? → A: Bind controller API and HAProxy stats to localhost by default; remote access requires explicit opt-in.
- Q: What should happen when `config.yml` and an existing generated environment file contain different control keys? → A: Fail generation until the operator resolves the conflicting keys.
- Q: How long should rotation wait for usable health before counting success? → A: Wait up to 30 seconds for usable health before counting success.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Safe Default Startup (Priority: P1)

As an operator preparing chamosel for a local machine or VPS, I want generated
configuration to keep control endpoints private and authenticated by default, so
that starting the pool does not accidentally expose rotation controls, dashboard
state, stats, or secrets to the network.

**Why this priority**: Accidental public control-plane exposure is the highest
risk because it can allow outsiders to observe or manipulate the proxy pool.

**Independent Test**: Generate configuration from a sample config that includes a
predefined control key and operator ports, then inspect the generated output to
confirm the controller and VPN backends use the same key and operator-facing
ports are bound or protected according to the safe default policy.

**Acceptance Scenarios**:

1. **Given** an operator provides a control key in configuration, **When** they
   generate the stack, **Then** both the controller and managed VPN backends use
   that same key without requiring an additional manual environment file edit.
2. **Given** an operator starts from the example configuration, **When** the stack
   is generated, **Then** controller and stats access are bound to localhost by
   default unless the operator explicitly opts into a documented remote exposure
   boundary.
3. **Given** an operator uses provider credentials or values containing special
   characters, **When** configuration is generated, **Then** the generated stack
   preserves those values exactly and remains valid.

---

### User Story 2 - Reliable Pool Health During Changes (Priority: P2)

As an operator running a mixed or upgraded VPN pool, I want chamosel to recover
from backend control-path changes and unhealthy instances without long blind
spots, so that pool status and rotation decisions remain trustworthy.

**Why this priority**: The pool can become misleading when backend versions
change, instances are down, or health checks serialize behind slow failures.

**Independent Test**: Simulate a pool where one backend changes its control
status route and multiple backends are unreachable, then verify the pool report
settles to accurate health and error state within the expected polling window.

**Acceptance Scenarios**:

1. **Given** a previously working backend status path no longer responds,
   **When** chamosel checks that instance, **Then** it re-detects a supported
   status path before declaring the instance permanently unusable.
2. **Given** several instances are unreachable, **When** the poller refreshes the
   pool snapshot, **Then** reachable instances are still refreshed promptly and
   down instances are reported with operator-visible failure state.
3. **Given** an instance is unauthorized or has an unsupported control endpoint,
   **When** the operator views pool state, **Then** the state distinguishes that
   failure from a healthy-but-reconnecting tunnel.

---

### User Story 3 - Rotation Results Match Operator Reality (Priority: P3)

As an operator or scraper client responding to bans, I want rotation responses
and counters to indicate whether a backend actually recovered, so that I do not
mistake a command acknowledgement for a usable fresh exit path.

**Why this priority**: Operators use rotation responses and metrics to decide
whether traffic can resume; optimistic success counts can hide a degraded pool.

**Independent Test**: Trigger rotation for a healthy backend, a backend that
accepts the restart command but fails to recover, and an unknown backend, then
verify the reported result, counters, and pool state match each outcome.

**Acceptance Scenarios**:

1. **Given** a backend accepts rotation and returns to healthy service, **When**
   rotation reaches usable health within 30 seconds, **Then** the operator sees
   a successful recovery result and success counters increase once.
2. **Given** a backend accepts the rotation command but does not recover within
   30 seconds, **When** rotation completes, **Then** the operator sees a
   non-success result and failure counters or warnings reflect the outcome.
3. **Given** an unknown backend name is requested, **When** rotation is attempted,
   **Then** no success counter increases and the operator receives a clear
   unknown-instance result.

---

### Edge Cases

- A control key is provided in configuration while an existing generated
  environment file contains a different key; generation must stop until the
  operator chooses one effective key.
- The operator intentionally wants non-local controller or stats access.
- Provider credentials contain `#`, quotes, colons, commas, spaces, braces, or
  other characters that often affect generated configuration formats.
- A backend upgrades or downgrades and the previously cached status path becomes
  invalid.
- Multiple instances are down or slow at the same time.
- A rotation command succeeds at the control-command layer but the tunnel never
  returns to usable health.
- A pool has a single instance, so rotation and cooldown behavior directly affect
  all scraper traffic.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST use one effective control key for both controller-to-
  backend requests and backend control-server authentication, regardless of
  whether the key was generated automatically or supplied by the operator.
- **FR-002**: System MUST make the effective control key discoverable to generated
  services without requiring the operator to duplicate it manually in a second
  file.
- **FR-002A**: System MUST stop generation with a clear operator-facing error
  when configuration and an existing generated environment file define different
  control keys.
- **FR-003**: System MUST bind controller operations, dashboard state, metrics,
  and stats to localhost in the default generated configuration.
- **FR-004**: System MUST provide an explicit operator choice for exposing
  controller or stats access beyond the local host, including clear warning text
  in generated or user-facing documentation.
- **FR-005**: System MUST protect or constrain stats access so that a default VPS
  deployment does not publish unauthenticated operational data.
- **FR-006**: System MUST preserve provider environment values exactly when
  generating deployment configuration, including values containing whitespace,
  punctuation, or comment-like characters.
- **FR-007**: System MUST recover from stale cached backend status paths by
  attempting supported path re-detection when a cached path no longer works.
- **FR-008**: System MUST keep health polling bounded so one or more slow or down
  instances do not prevent timely updates for healthy instances.
- **FR-009**: System MUST expose operator-visible health, authorization,
  unreachable, reconnecting, and unsupported-control states when those states can
  be distinguished.
- **FR-010**: System MUST only count a rotation as fully successful when the
  selected instance reaches usable health within 30 seconds after the rotation
  attempt.
- **FR-011**: System MUST record and expose failed, partial, or timed-out rotation
  outcomes separately from fully successful rotations.
- **FR-012**: System MUST keep existing operator workflows for generation,
  startup, status inspection, and rotation available after these hardening
  changes.
- **FR-SEC**: System MUST preserve controller/backend authentication and avoid
  exposing operator endpoints publicly unless the spec explicitly defines a
  protective boundary.
- **FR-OBS**: System MUST expose operator-visible health, rotation, and error
  state for any feature that affects the running pool.

### Key Entities *(include if feature involves data)*

- **Control Key**: The shared secret used by chamosel's controller to authenticate
  to managed backend control servers. It may be generated or operator-supplied,
  but there is only one effective key per generated stack.
- **Operator Endpoint**: Any local or network-accessible endpoint used to rotate
  the pool, inspect pool state, scrape metrics, view the dashboard, or view stats.
- **Backend Instance**: A managed VPN-backed proxy participant with health,
  public exit identity, control status path, and rotation state.
- **Rotation Outcome**: The result of a rotation attempt, including command
  acceptance, recovery status, elapsed wait, old/new exit identity when known,
  and success or failure classification.
- **Pool Snapshot**: The current operator-visible view of all backend instances,
  including health, public identity, recent history, counters, and failure state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of generated stacks using a configured control key, the
  controller and every managed backend agree on the same effective key without
  manual post-generation edits.
- **SC-001A**: In 100% of key-conflict cases, generation stops before writing a
  stack that could give different effective keys to controller and backends.
- **SC-002**: A default generated deployment exposes zero operator-control or
  stats endpoints to non-local network interfaces unless the operator explicitly
  opts in.
- **SC-003**: At least 10 representative provider values containing punctuation
  and whitespace are preserved exactly through generation and validation.
- **SC-004**: When half of a 10-instance pool is unreachable, reachable instances
  still refresh within two configured polling intervals.
- **SC-005**: After a backend control-path change, supported backends recover
  status detection during the next live health refresh.
- **SC-006**: Rotation metrics and responses classify successful recovery,
  command failure, recovery timeout, and unknown instance outcomes distinctly in
  operator-visible state.
- **SC-006A**: A backend that has not reached usable health within 30 seconds of
  rotation is not counted as a successful rotation.
- **SC-007**: Existing quick-start generation and local-only operation remain
  usable with no additional manual secret-copying steps.

## Assumptions

- Safe defaults bind operator endpoints to localhost; remote access is an
  explicit opt-in scenario.
- Operators who need remote dashboard, metrics, or stats access can place those
  endpoints behind their own authenticated reverse proxy or firewall.
- The feature covers configuration generation, controller behavior, operator
  state, and documentation for the listed risks; it does not add a new scraper
  client feature.
- The default bounded recovery wait for rotation success is 30 seconds.
- Live VPN credentials may not be available in every development environment, so
  validation can combine automated generation checks with documented manual
  runtime checks.
