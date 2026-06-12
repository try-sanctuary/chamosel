# Contract: Generated Compose and HAProxy

## Docker Compose Port Bindings

Default generated bindings:

```yaml
ports:
  - "127.0.0.1:${api_port}:8800/tcp"
  - "127.0.0.1:${stats_port}:${stats_port}/tcp"
```

The scraper proxy port keeps existing proxy-facing behavior unless the
implementation adds an explicit bind option outside this feature's requirements.

## Service Environment

Generated gluetun service environment must provide:

- HTTP proxy enabled on the internal proxy port.
- Health server address on the internal health port.
- Control server address on the internal control port.
- Control-server auth role containing the effective control key.
- Provider-specific environment entries rendered with exact scalar preservation.

Generated controller service environment must provide:

- The same effective control key as `GLUETUN_API_KEY`.
- Instance list.
- Control port, listen port, auto-rotate interval, cooldown, poll interval, and
  state file path.

## HAProxy Stats

The generated HAProxy stats frontend must be reachable through the localhost
host binding by default. If a remote stats bind is explicitly configured,
generated or user-facing documentation must warn that operators need an external
protection boundary.

## Validation Expectations

- Generated Compose parses as valid YAML.
- At least 10 representative provider values with special characters parse back
  to the original values.
- Controller and gluetun generated environments reference the same key source.
- Default operator bind strings include localhost.
