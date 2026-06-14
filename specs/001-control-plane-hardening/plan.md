# Implementation Plan: Control Plane Hardening

**Branch**: `001-control-plane-hardening` | **Date**: 2026-06-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-control-plane-hardening/spec.md`

## Summary

Harden chamosel's operator control plane and runtime accounting without changing
the core product shape: one generated Docker Compose stack, gluetun backends
behind HAProxy, and a stdlib controller. The implementation will make one
effective gluetun control key flow consistently into both gluetun and the
controller, fail fast on key conflicts, bind controller and stats ports to
localhost by default, safely render provider environment values, recover stale
gluetun status-path cache entries, bound health polling when instances are down,
and count rotation success only after 30 seconds of usable-health recovery.

## Technical Context

**Language/Version**: Python 3.10+ for CLI and controller; PHP example client remains unchanged unless docs need updates

**Primary Dependencies**: CLI uses `pyyaml` and `jinja2`; controller remains Python stdlib-only; Docker Compose and HAProxy remain deployment/runtime dependencies

**Storage**: `.env` for generated control key; generated `docker-compose.yml` and `haproxy.cfg`; controller state JSON at `/data/state.json`

**Testing**: Python `unittest`/stdlib tests for controller behavior; Python generation tests for YAML/template output; `python3 -m py_compile`; optional `docker compose config` and live runtime validation

**Target Platform**: Linux server or local Docker host with Docker Compose plugin; generated operator endpoints default to localhost host binding

**Project Type**: Single-project Python CLI plus Dockerized stdlib web controller and generated deployment templates

**Performance Goals**: Polling refreshes reachable instances within two configured polling intervals when half of a 10-instance pool is down; rotation waits up to 30 seconds for usable health before success accounting

**Constraints**: Controller must remain stdlib-only; generated secrets must not be logged or committed; default operator API/stats exposure must be local-only; existing `generate`, `up`, `status`, and `rotate` workflows must remain available

**Scale/Scope**: Small to medium VPN backend pools; explicit success target covers 10 instances with 50% unreachable

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control Plane Security**: PASS. Default plan binds controller and HAProxy
  stats host ports to `127.0.0.1`, propagates one effective control key, fails
  on conflicting config/env-file keys, and keeps remote exposure explicit.
- **Health-Aware Rotation**: PASS. Rotation remains gluetun control-server
  stop/start with HAProxy health checks, but success accounting waits for usable
  health within 30 seconds.
- **Observability and State**: PASS. Plan adds operator-visible instance status
  details, distinct rotation outcomes, and metrics/API/dashboard state aligned
  with the new outcome model.
- **Configuration Discipline**: PASS. Affected generated artifacts are
  `docker-compose.yml`, `haproxy.cfg`, `.env`, README examples, and generated
  service environment. Validation includes exact preservation of special
  provider values and generated config parsing.
- **Testable Operations**: PASS. Verification covers key propagation, key
  conflict failure, localhost binds, environment quoting, stale status-path
  re-detection, bounded polling, and 30-second rotation outcome classification.

## Project Structure

### Documentation (this feature)

```text
specs/001-control-plane-hardening/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-and-config.md
│   ├── controller-api.md
│   ├── generated-compose.md
│   └── metrics.md
└── tasks.md
```

### Source Code (repository root)

```text
chamosel.py                 # CLI, config loading, key resolution, template rendering
controller/
├── controller.py            # stdlib controller, polling, rotation, API, metrics, dashboard
└── Dockerfile
templates/
├── docker-compose.yml.j2    # generated services, port bindings, environment rendering
└── haproxy.cfg.j2           # generated proxy and stats frontend
tests/
├── test_generate.py         # generation, key, YAML, bind contract tests
└── test_controller.py       # controller state, health, polling, rotation outcome tests
README.md                   # operator docs and safe exposure notes
config.yml.example          # safe defaults and explicit opt-in settings
examples/client.php         # request-facing example, unchanged unless response contract docs need update
```

**Structure Decision**: Keep the existing single-project layout and add a small
`tests/` directory. Do not introduce a framework, service split, or non-stdlib
controller dependency.

## Complexity Tracking

No constitution violations are planned.

## Phase 0: Research Summary

See [research.md](./research.md). All planning unknowns are resolved there:
effective key precedence, localhost-safe port binding, safe environment
rendering, stale status-path recovery, bounded polling, rotation outcome
accounting, and stdlib-only testing strategy.

## Phase 1: Design Summary

See [data-model.md](./data-model.md) for the operational entities and state
transitions. See [contracts/](./contracts/) for CLI/config, generated Compose,
controller API, and metrics contracts. See [quickstart.md](./quickstart.md) for
end-to-end validation scenarios.

## Post-Design Constitution Check

- **Control Plane Security**: PASS. Contracts require localhost binds by default
  and fail-fast conflicting keys; quickstart validates both.
- **Health-Aware Rotation**: PASS. Data model defines rotation outcome states and
  30-second recovery success criteria without container restarts.
- **Observability and State**: PASS. API and metrics contracts expose distinct
  health and rotation outcomes.
- **Configuration Discipline**: PASS. Generated Compose contract covers exact
  provider value preservation, `.env` key propagation, and bind defaults.
- **Testable Operations**: PASS. Quickstart and contracts define both automated
  and optional live validation commands.
