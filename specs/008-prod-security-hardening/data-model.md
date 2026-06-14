# Data Model: Production Security Hardening

## Exposure Policy

- **Fields**: endpoint (`controller`, `proxy`, `stats`), bind address, public exposure flag, auth enabled flag, allowlist, acknowledgement flag, remediation message.
- **Validation**:
  - Loopback bind is safe by default.
  - Non-loopback controller bind requires enabled, non-empty controller auth.
  - Non-loopback proxy bind requires explicit public proxy acknowledgement and a protective boundary.
  - Non-loopback stats bind requires stats auth or a protective boundary.

## Secret File

- **Fields**: path, expected permission mode, actual permission mode, contains generated secrets, remediation status.
- **Validation**:
  - Generated secret files are created with restrictive permissions.
  - Existing secret files with broader permissions are reported without exposing content.
  - Secret values never appear in logs, JSON, tables, or generated documentation.

## Rotation Guard

- **Fields**: instance name, in-flight flag, started timestamp, operation type, forced flag, cooldown state, outcome.
- **Validation**:
  - Only one active rotation/repair operation can target an instance.
  - Overlapping requests return an explicit in-progress outcome.
  - Forced cooldown bypass is recorded and visible.

## Diagnostic Read

- **Fields**: command/source, freshness requested, repair allowed flag, observed degraded reasons, repair decision, mutation count.
- **Validation**:
  - Read-only diagnostics have `repair_allowed=false`.
  - Read-only diagnostics never schedule repair or rotation.
  - Explicit repair commands remain mutating and observable.

## Verification Evidence

- **Fields**: backend name, connection IP, connection ASN, resolver IPs, resolver ASNs, egress target, target validation status, verification outcome, error reason.
- **Validation**:
  - Missing or non-public connection IP fails DNS verification.
  - Strict ASN mode fails when required ASN evidence is missing or mismatched.
  - Unsafe egress targets fail validation before use.

## Runtime Hardening Finding

- **Fields**: service name, category, severity, current state, recommended action.
- **Validation**:
  - Mutable image references generate production warnings.
  - Avoidable root/capability/writeable-root settings generate warnings or are corrected where compatible.
