# Contract: CLI and Configuration

## Commands

### `python3 chamosel.py generate [-c CONFIG]`

**Preconditions**:
- `CONFIG` exists and defines at least one provider.

**Required behavior**:
- Resolve one effective gluetun control key.
- Generate `docker-compose.yml`, `haproxy.cfg`, and `.env` where needed.
- Fail before writing inconsistent stack output if `global_settings.api_key` and
  existing `.env` define different non-empty control keys.
- Preserve existing workflows and exit non-zero with an operator-readable error
  on validation failure.

**Observable results**:
- `docker-compose.yml` gives gluetun and controller the same effective key.
- Controller API and HAProxy stats host bindings default to `127.0.0.1`.
- Provider environment values round-trip exactly through generated YAML.

### `python3 chamosel.py up [-c CONFIG]`

**Required behavior**:
- Runs the same generation validation as `generate` before starting services.
- Does not start a stack when generation fails due to key conflict or invalid
  generated config.

### `python3 chamosel.py status [-c CONFIG]`

**Required behavior**:
- Continues to report pool state from the controller.
- If new status categories are available, status output may show them while
  preserving name, health, rotation count, and public IP readability.

### `python3 chamosel.py rotate [name|all] [-c CONFIG]`

**Required behavior**:
- Continues to request rotation from the controller.
- Displays distinct success, cooldown, unknown-instance, command-error, and
  recovery-timeout outcomes returned by the controller.

## Configuration Fields

### Existing

- `global_settings.proxy_port`
- `global_settings.stats_port`
- `global_settings.api_port`
- `global_settings.api_key`
- `vpn_providers.*.env`

### Added or clarified

- `global_settings.api_bind` or equivalent: optional controller host bind;
  defaults to `127.0.0.1`.
- `global_settings.stats_bind` or equivalent: optional HAProxy stats host bind;
  defaults to `127.0.0.1`.
- Explicit remote binds must be documented as operator opt-in.

## Error Contract

Key conflict errors must include:
- The two conflicting sources, not the secret values.
- A clear instruction to remove or align one source.
- No generated secret content.
