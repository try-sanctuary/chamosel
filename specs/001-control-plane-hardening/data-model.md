# Data Model: Control Plane Hardening

## Control Key

**Purpose**: One effective shared secret used by the controller to authenticate
to every managed gluetun control server.

**Fields**:
- `source`: `environment`, `env_file`, `config`, or `generated`
- `value`: secret string; never logged or exposed in API, dashboard, metrics, or docs
- `conflict`: optional pair of source labels when two configured keys disagree

**Validation rules**:
- Empty strings are ignored.
- If `env_file` and `config` both exist and differ, generation fails.
- The selected key is persisted to `.env` unless it came only from the process
  environment and the operator intentionally keeps it external.

**Relationships**:
- Used by generated gluetun service auth role.
- Used by generated controller environment.

## Operator Endpoint

**Purpose**: A host-reachable endpoint used for pool control, state, metrics,
dashboard, or HAProxy stats.

**Fields**:
- `name`: `proxy`, `controller`, or `stats`
- `host_bind`: host interface or address
- `host_port`: operator-configured host port
- `container_port`: fixed internal service port
- `remote_exposure`: boolean explicit opt-in

**Validation rules**:
- `controller` and `stats` default to `127.0.0.1`.
- Remote exposure requires an explicit config value and documentation warning.
- `proxy` remains request-facing and may bind according to existing proxy
  behavior.

## Provider Environment Entry

**Purpose**: A provider-specific environment key/value passed to gluetun.

**Fields**:
- `key`: environment variable name
- `value`: scalar value preserved exactly from config

**Validation rules**:
- Values containing `#`, quotes, colons, commas, spaces, braces, or empty strings
  must survive render and parse without change.
- Keys remain strings and are not logged with secret values.

## Backend Instance

**Purpose**: One managed VPN-backed proxy backend.

**Fields**:
- `name`: container/DNS name
- `healthy`: boolean usable-health flag
- `status`: canonical operator status: `healthy`, `reconnecting`, `unreachable`,
  `unauthorized`, or `unsupported_control`
- `public_ip`: current known exit IP or null
- `ip_history`: most recent known exit IPs
- `status_path`: cached working gluetun status path or null
- `last_seen`: last completed health refresh timestamp
- `last_error`: last operator-visible failure category

**State transitions**:
- `unknown -> healthy`: supported status path reports running and public IP
  lookup succeeds or remains previously known.
- `healthy -> reconnecting`: rotation command accepted and usable health is not
  yet restored.
- `reconnecting -> healthy`: usable health restored within 30 seconds.
- `reconnecting -> unreachable|unauthorized|unsupported_control`: recovery
  window expires or a definitive failure is detected.
- `healthy|unknown -> unauthorized`: control server rejects configured key.
- `healthy|unknown -> unsupported_control`: supported status paths cannot be
  detected after retry.

## Rotation Outcome

**Purpose**: Operator-visible result of a rotation attempt.

**Fields**:
- `instance`: backend name or requested name
- `ok`: boolean true only for fully recovered rotations
- `outcome`: `success`, `cooldown`, `unknown_instance`, `command_error`,
  `recovery_timeout`, `unauthorized`, or `unsupported_control`
- `old_ip`: previous public IP if known
- `new_ip`: post-recovery public IP if known
- `elapsed_seconds`: time spent attempting command and recovery
- `message`: short operator-facing explanation

**Validation rules**:
- Success counters increment only for `outcome=success`.
- Error counters increment for command, authorization, unsupported-control, and
  recovery-timeout outcomes.
- Unknown instance and cooldown outcomes do not increment success counters.

## Pool Snapshot

**Purpose**: Current operator-visible state served through `/pool`, dashboard,
and metrics.

**Fields**:
- `count`: number of configured backends
- `healthy`: count of usable backends
- `rotations_total`: count of fully successful rotations
- `rotation_errors_total`: count of failed rotation attempts
- `instances`: list of backend instance snapshots

**Validation rules**:
- Snapshot updates for reachable instances must not be blocked by unrelated down
  instances beyond two polling intervals in the 10-instance/50%-down target.
- Persisted state must not include control key values.
