# Feature Specification: Proxy Client Network

**Feature Branch**: `009-proxy-client-network`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Allow operators to attach only the HAProxy request proxy to an optional shared Docker client network so another container can resolve and use the chamosel proxy by name, while keeping controller and gluetun backends on the internal network. The shared network should be configurable by name, support external existing networks, and expose a stable proxy alias such as chamosel-proxy. This should reduce the need to publish the proxy on host interfaces and avoid expanding controller access."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use Proxy From Another Container By Name (Priority: P1)

An operator runs a separate application container that needs to send requests through chamosel without relying on a host-published proxy port. The operator configures a shared client network and a stable proxy name so the application can use the proxy endpoint by name.

**Why this priority**: This is the core value of the feature. It enables container-to-container proxy access while reducing host-interface exposure.

**Independent Test**: Can be fully tested by configuring a client network, starting the pool, attaching a separate client container to the same network, and verifying that the client can resolve the configured proxy alias and make requests through it.

**Acceptance Scenarios**:

1. **Given** a configured shared client network and proxy alias, **When** the operator starts chamosel, **Then** the request proxy is reachable from another container on that shared network by the configured alias and proxy port.
2. **Given** the request proxy is reachable from the shared client network, **When** the operator checks the controller and backend service exposure from that client network, **Then** only the request proxy is intentionally exposed through the shared client path.

---

### User Story 2 - Keep Internal Control Plane Isolated (Priority: P2)

An operator wants the proxy service available to selected client containers but does not want controller or VPN backend control surfaces reachable through the shared client network.

**Why this priority**: The feature changes network exposure. Preserving control-plane isolation prevents a convenience feature from broadening the attack surface.

**Independent Test**: Can be tested by enabling the client network and confirming that the proxy service participates in that network while controller and backend services remain on the internal pool network only.

**Acceptance Scenarios**:

1. **Given** a shared client network is configured, **When** chamosel generates and starts the pool, **Then** the request proxy joins both the internal pool network and the shared client network.
2. **Given** the same configuration, **When** generated service exposure is reviewed, **Then** controller and VPN backend services do not join the shared client network.

---

### User Story 3 - Use Existing Operator-Managed Network (Priority: P3)

An operator already has a controlled shared network for application containers and wants chamosel to attach the proxy to that network instead of creating a new client network.

**Why this priority**: Existing-network support avoids forcing operators to restructure deployments and supports controlled production environments.

**Independent Test**: Can be tested by configuring an existing client network, starting chamosel, and confirming the proxy attaches to that network without creating an unexpected replacement network.

**Acceptance Scenarios**:

1. **Given** an operator-managed client network already exists, **When** the operator marks the client network as externally managed, **Then** chamosel uses that network for the proxy client path.
2. **Given** an operator configures a non-existing externally managed client network, **When** the pool is started, **Then** startup fails visibly instead of silently creating or using the wrong network.

### Edge Cases

- If no shared client network is configured, chamosel must behave as it does today with only the internal pool network.
- If the configured client network name is empty or invalid, configuration validation must fail before startup.
- If the proxy alias is empty, chamosel must use a documented safe default alias.
- If the proxy alias conflicts with another service name on the shared client network, startup or client resolution should fail visibly rather than exposing controller or backend services.
- If the proxy host bind is loopback-only, containers on the shared client network must still be able to use the proxy through the network alias.
- If controller auth is disabled, the shared client network must not create a new path to the controller.
- If one or more gluetun instances are unhealthy or reconnecting, the shared client network must not bypass existing HAProxy health behavior.
- The feature changes generated deployment network structure and request proxy exposure; it must not change provider secrets, gluetun control credentials, or controller authentication requirements.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow operators to configure an optional shared client network for request-proxy access from other containers.
- **FR-002**: System MUST leave the shared client network disabled by default.
- **FR-003**: System MUST attach only the request proxy service to the shared client network when the feature is enabled.
- **FR-004**: System MUST keep controller and VPN backend services on the internal pool network only unless a future feature explicitly expands their exposure.
- **FR-005**: System MUST support using an operator-managed existing client network.
- **FR-006**: System MUST support creating a managed client network when the operator does not mark it as externally managed.
- **FR-007**: System MUST provide a stable proxy network alias for client containers and default that alias to `chamosel-proxy` when the operator does not choose one.
- **FR-008**: System MUST validate client network names and aliases before startup and fail with an operator-visible error when values are unsafe or empty.
- **FR-009**: System MUST document how a separate client container should connect to the shared client network and use the proxy alias.
- **FR-010**: System MUST preserve existing host bind and allowlist protections; enabling a shared client network must not implicitly publish the proxy on broader host interfaces.
- **FR-011**: System MUST preserve HAProxy backend health behavior for all traffic entering from the shared client network.
- **FR-SEC**: System MUST preserve controller/gluetun authentication and avoid exposing operator endpoints publicly unless the spec explicitly defines a protective boundary.
- **FR-OBS**: System MUST expose enough generated configuration and startup feedback for operators to confirm whether the shared client network is disabled, managed, or external.

### Key Entities *(include if feature involves data)*

- **Proxy Client Network Configuration**: Operator intent for the optional shared client network, including enabled/disabled state, network name, whether the network is externally managed, and proxy alias.
- **Internal Pool Network**: Existing private network that connects proxy, controller, and VPN backends for internal orchestration.
- **Request Proxy Service**: The only service intentionally exposed to the shared client network for application traffic.
- **Client Container**: An operator-managed container outside the chamosel pool that needs to resolve and use the request proxy by name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can configure a shared client network and verify proxy name resolution from a separate client container in one startup cycle.
- **SC-002**: With the shared client network enabled, 100% of generated deployments keep controller and VPN backend services off the shared client network.
- **SC-003**: With the shared client network disabled, generated deployments remain equivalent to current default network behavior.
- **SC-004**: At least 95% of invalid client network configurations fail before startup with a clear operator-visible validation message.
- **SC-005**: Operators can keep the host proxy bind on loopback while still allowing selected containers on the shared client network to use the proxy.

## Assumptions

- Operators who enable the shared client network control which external containers are attached to that network.
- The shared client network is intended only for request traffic through the proxy, not for controller API, dashboard, metrics, gluetun control, or direct backend access.
- A single shared client network and one proxy alias are sufficient for the first version.
- The default alias `chamosel-proxy` is acceptable unless the operator overrides it.
- Existing host bind, proxy allowlist, controller auth, HAProxy health, and rotation behavior remain authoritative.
