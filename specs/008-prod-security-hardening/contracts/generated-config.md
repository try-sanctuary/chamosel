# Contract: Generated Configuration

## Docker Compose

- Proxy, controller, and stats host bindings reflect their independent configured bind addresses.
- Controller receives auth and runtime settings through environment references rather than unnecessary literal secret embedding.
- Services that do not require elevated networking privileges run with reduced privileges where compatible.
- Gluetun retains required VPN capabilities and device access.

## HAProxy

- Stats UI is loopback-only by default or protected when intentionally exposed.
- Proxy frontend remains unauthenticated only when exposure is constrained by host binding or allowlist policy.
- HAProxy configuration validates allowed balance algorithms before rendering.

## Secret Files

- `.env` and configured secret files are never committed.
- Generated or updated secret files are permission-restricted.
- Permission warnings identify file paths and modes only, not contents.
