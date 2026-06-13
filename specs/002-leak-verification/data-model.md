# Data Model: Leak Verification

## Leak Verification Run

Represents one operator-triggered verification attempt.

### Fields

- `target`: URL used for direct and backend public-IP checks.
- `timeout`: Maximum seconds allowed for each external/proxy check.
- `direct_ip`: Host public IP observed without proxy.
- `ok`: Overall pass/fail result.
- `verified_count`: Number of backend instances that passed verification.
- `total_count`: Number of backend instances considered by the run.
- `instances`: Ordered list of backend verification results.
- `error`: Top-level failure reason when the run cannot proceed.

### Validation Rules

- `target` must be a URL accepted by the verification workflow.
- `timeout` must be positive.
- `direct_ip` must be present and public before backend results can produce an
  overall PASS.
- `ok` is true only when every considered backend result is verified and no
  top-level error exists.

### State Transitions

```text
created -> host_ip_checked -> pool_loaded -> backends_checked -> pass
created -> fail
host_ip_checked -> fail
pool_loaded -> fail
backends_checked -> fail
```

## Backend Verification Result

Represents one backend's controller state and observed proxy behavior.

### Fields

- `name`: Backend instance name, such as `surfshark_0`.
- `controller_status`: Health/status reported by the controller.
- `controller_public_ip`: Public IP reported by controller pool state, if any.
- `proxy_ok`: Whether the backend proxy check succeeded.
- `proxy_ip`: Public IP observed through that backend proxy.
- `country`: Country metadata returned by the target, if available.
- `region`: Region metadata returned by the target, if available.
- `city`: City metadata returned by the target, if available.
- `asn`: ASN metadata returned by the target, if available.
- `asn_org`: ASN organization metadata returned by the target, if available.
- `leak_detected`: True when `proxy_ip` equals `direct_ip`.
- `error`: Backend-specific failure reason.

### Validation Rules

- `name` is required for every result.
- `controller_status` is required when pool state was loaded.
- A healthy backend must produce a public `proxy_ip`.
- `leak_detected` must be true when `proxy_ip` equals the run's `direct_ip`.
- Any unhealthy status, missing public proxy IP, proxy failure, or leak sets an
  error and causes overall run failure by default.

### State Transitions

```text
pending -> skipped
pending -> controller_unhealthy -> failed
pending -> proxy_checked -> verified
pending -> proxy_checked -> leak_detected
pending -> proxy_error -> failed
```

## Verification Target

External endpoint used to report apparent public IP and optional metadata.

### Fields

- `url`: Target URL.
- `ip_field`: Field containing the apparent public IP.
- `metadata_fields`: Optional fields used for operator display.

### Validation Rules

- The target response must contain a parseable public IP for successful checks.
- Missing optional metadata must not fail verification when the public IP is
  present.
- Malformed or non-public IP data fails the affected direct or backend check.
