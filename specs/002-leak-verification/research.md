# Research: Leak Verification

## Decision: Use the existing CLI as the verification entry point

**Rationale**: Operators already use `chamosel.py` for lifecycle and controller
actions. A `verify-leaks` subcommand keeps the diagnostic next to `status` and
`rotate`, can reuse existing config/controller URL helpers, and avoids adding a
new service.

**Alternatives considered**: Adding a controller endpoint was rejected because
the check is an operator diagnostic that needs to compare host-direct traffic
with backend-proxied traffic. Adding a separate script was rejected because it
would duplicate config and controller handling.

## Decision: Determine direct host IP before backend checks

**Rationale**: The feature's primary failure mode is exposing the host/server
public IP. The workflow must know that IP before it can classify backend proxy
results as leaking or safe.

**Alternatives considered**: Trusting controller-reported backend IPs alone was
rejected because it does not prove the host IP differs from observed proxy
traffic. Making host IP optional was rejected because it would prevent a clear
PASS/FAIL result.

## Decision: Probe each backend independently instead of using HAProxy

**Rationale**: HAProxy intentionally hides backend selection behind one pool
endpoint. Leak verification must attribute failures to exact instances, so each
backend needs its own direct proxy probe path.

**Alternatives considered**: Repeated requests through HAProxy were rejected
because they cannot reliably prove every backend was exercised or identify the
failing backend. Adding temporary HAProxy routing rules was rejected because it
would change generated runtime behavior for a diagnostic command.

## Decision: Run backend proxy probes from inside the Docker network

**Rationale**: The backend container names are resolvable inside the Compose
network, and the controller container is already in that network. Running a
small stdlib probe inside the controller container avoids exposing backend proxy
ports on the host.

**Alternatives considered**: Publishing every backend proxy to the host was
rejected as a control-plane exposure risk. Adding probe code to the controller
API was rejected for v1 because the diagnostic can be implemented from the CLI
without expanding the controller surface.

## Decision: Fail unhealthy backends by default

**Rationale**: Operators asked whether the pool is safe to use. A pool with
unhealthy or unreachable backends is not fully verified, even when healthy
backends are safe. Default failure avoids false confidence.

**Alternatives considered**: Silently skipping unhealthy backends was rejected
because it can report PASS for a partially broken pool. A future explicit
skip-unhealthy mode can be considered, but the default remains fail-closed.

## Decision: Provide both human-readable and structured output

**Rationale**: Operators need a concise table for manual use, while automation
needs stable fields, boolean status, and per-backend error details.

**Alternatives considered**: Human-only output was rejected because CI or
monitoring cannot parse it reliably. JSON-only output was rejected because it is
less ergonomic during live debugging.

## Decision: Keep runtime dependencies unchanged

**Rationale**: The project already has a small Python CLI and a stdlib-only
controller. Python stdlib can perform HTTP requests, JSON parsing, subprocess
calls, and public IP validation.

**Alternatives considered**: Adding `requests`, Docker SDK, or proxy helper
libraries was rejected because the feature does not need them and they would
increase installation and packaging surface.

## Decision: Document DNS/client/browser limits explicitly

**Rationale**: Exit-IP verification does not prove every caller's DNS behavior,
browser WebRTC behavior, or non-proxy traffic path. The README must explain
what is verified and what remains the operator/client responsibility.

**Alternatives considered**: Claiming full DNS leak protection was rejected as
misleading. Blocking the feature until full browser/client leak testing exists
was rejected because backend exit-IP verification is still valuable and
testable.
