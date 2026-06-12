# Quickstart Validation: Control Plane Hardening

This guide validates the feature without requiring real VPN credentials first,
then lists optional live checks for a Docker/VPN-capable environment.

## Prerequisites

- Python 3.10+
- `pyyaml` and `jinja2`
- Docker Compose plugin for optional generated-config validation
- Real VPN credentials only for optional live checks

## 1. Syntax Checks

```bash
python3 -m py_compile chamosel.py controller/controller.py
```

Expected: command exits `0`.

## 2. Generate With Config-Supplied Control Key

Create a temporary config based on `config.yml.example` with:

- `global_settings.api_key` set to a known test value
- provider environment values containing at least these characters:
  `#`, quotes, colon, comma, spaces, braces

Run:

```bash
python3 chamosel.py -c /path/to/test-config.yml generate
```

Expected:

- Generation exits `0`.
- The generated gluetun auth role and controller `GLUETUN_API_KEY` reference the
  same effective key.
- `.env` is present when required and does not contain a conflicting key.
- Provider values parse back exactly from `docker-compose.yml`.

## 3. Key Conflict Fails Fast

Prepare `.env` with one test key and `config.yml` with a different
`global_settings.api_key`.

Run:

```bash
python3 chamosel.py generate
```

Expected:

- Generation exits non-zero.
- Error mentions conflicting key sources.
- Error does not print either secret value.
- No inconsistent stack is written after the failure.

## 4. Localhost Operator Bind Defaults

Run generation from the example config.

Expected generated bindings:

- Controller API: `127.0.0.1:<api_port>:8800/tcp`
- HAProxy stats: `127.0.0.1:<stats_port>:<stats_port>/tcp`

Remote binds are only present when explicitly configured.

## 5. Generated Config Validation

If Docker Compose is available:

```bash
docker compose -f docker-compose.yml config
```

Expected: generated config validates successfully.

## 6. Controller Behavior Tests

Run the focused test suite once implemented:

```bash
python3 -m unittest discover -s tests
```

Expected coverage:

- status-path cache is cleared and re-detected when stale
- unauthorized and unsupported control states are distinguishable
- slow/down instances do not block reachable instance refresh beyond target
- rotation success increments only after usable health within 30 seconds
- recovery timeout increments error outcome, not success counters

## 7. Optional Live Runtime Check

With real VPN credentials:

```bash
python3 chamosel.py up
python3 chamosel.py status
curl http://127.0.0.1:8800/pool
curl -X POST http://127.0.0.1:8800/rotate
```

Expected:

- Local dashboard and API work through localhost.
- Remote access to controller/stats is unavailable unless explicitly opted in.
- Rotation response reports `success` only after usable health returns.
- `/metrics` counters match the observed rotation outcome.
