# Implementation Plan: Leak Verification

**Branch**: `002-leak-verification` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-leak-verification/spec.md`

## Summary

Add an operator-facing leak verification workflow to chamosel that determines
the direct host public IP, refreshes controller pool state, probes each backend
through its own proxy path, and reports PASS/FAIL when backend exit IPs are
safe or appear to expose the host IP. The implementation will extend the
existing Python CLI, use stdlib networking/subprocess helpers for verification,
avoid new runtime dependencies, document DNS/client limitations, and cover the
workflow with mocked unit tests that do not require Docker or live VPN
credentials.

## Technical Context

**Language/Version**: Python 3.10+ for `chamosel.py`; controller remains Python stdlib-only

**Primary Dependencies**: Existing CLI dependencies `pyyaml` and `jinja2`; Python stdlib for HTTP, JSON, subprocess, IP parsing, and tests; Docker Compose as an optional live runtime dependency

**Storage**: No new persisted storage; reads existing `config.yml`, generated `.env`, generated `docker-compose.yml`, and controller `/pool?fresh=1` state at runtime

**Testing**: Python `unittest` with mocked HTTP/subprocess calls; `python3 -m py_compile chamosel.py controller/controller.py`; `python3 -m unittest discover -s tests -v`; `git diff --check`

**Target Platform**: Local or server Docker host running chamosel with Docker Compose plugin and gluetun backend containers

**Project Type**: Single-project Python CLI plus Dockerized stdlib controller

**Performance Goals**: Verify a 10-backend pool within the configured timeout per backend and provide partial failure reasons without hanging indefinitely

**Constraints**: No new runtime dependencies; do not print `.env`, `.env.local`, API keys, WireGuard keys, provider secrets, or generated compose secrets; preserve existing `generate`, `up`, `down`, `status`, and `rotate` behavior

**Scale/Scope**: Small to medium gluetun pools; explicit validation target covers 1 to 10 backend instances and supports operator-selected verification target/timeout

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control Plane Security**: PASS. The workflow calls existing local controller
  API paths and backend proxies without changing public exposure. Secret-bearing
  files and environment values are never printed. Controller/gluetun auth remains
  unchanged.
- **Health-Aware Rotation**: PASS. The feature does not rotate tunnels or restart
  containers. It consumes current health state and reports unhealthy or
  unreachable instances rather than altering them.
- **Observability and State**: PASS. The command provides operator-visible
  per-backend result rows and structured output. No persisted state changes are
  required because each run is an on-demand diagnostic snapshot.
- **Configuration Discipline**: PASS. No generated Docker Compose, HAProxy, or
  provider environment structure changes are required. Documentation changes are
  limited to README usage and leak-boundary guidance.
- **Testable Operations**: PASS. Tests will mock direct IP lookup, controller
  pool responses, and backend probe subprocess calls; quickstart documents live
  validation when Docker/VPN credentials are available.

## Project Structure

### Documentation (this feature)

```text
specs/002-leak-verification/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── verify-leaks.md
└── tasks.md              # Created by /speckit-tasks, not by /speckit-plan
```

### Source Code (repository root)

```text
chamosel.py                 # CLI command, leak verification orchestration, formatting
README.md                   # Operator leak verification docs and limitations
tests/
└── test_generate.py         # CLI/generation tests; add leak verification unit tests here or split if useful
controller/
└── controller.py            # Read-only dependency via /pool?fresh=1; no planned change
templates/
├── docker-compose.yml.j2    # No planned change
└── haproxy.cfg.j2           # No planned change
```

**Structure Decision**: Keep the existing single-project layout. Implement the
operator workflow in `chamosel.py` because it is a CLI concern and can reuse
existing config/controller helpers. Keep controller and generated templates
unchanged unless implementation reveals a necessary contract gap.

## Complexity Tracking

No constitution violations are planned.

## Phase 0: Research Summary

See [research.md](./research.md). All planning unknowns are resolved there:
direct host IP source, per-backend probing approach, unhealthy backend policy,
JSON/human output shape, DNS guidance boundary, timeout/error handling, and
stdlib-only testing strategy.

## Phase 1: Design Summary

See [data-model.md](./data-model.md) for the verification run and per-backend
result model. See [contracts/verify-leaks.md](./contracts/verify-leaks.md) for
CLI flags, exit behavior, human output, and JSON output. See
[quickstart.md](./quickstart.md) for automated and optional live validation.

## Post-Design Constitution Check

- **Control Plane Security**: PASS. Contract requires secret-safe output and
  preserves existing controller/gluetun auth boundaries.
- **Health-Aware Rotation**: PASS. Design remains read-only and does not change
  rotation or HAProxy health behavior.
- **Observability and State**: PASS. Per-run result model and output contract
  provide enough diagnostic state without persisted storage.
- **Configuration Discipline**: PASS. No generated artifact changes are planned;
  README documents how to run the new command and what it does not prove.
- **Testable Operations**: PASS. Quickstart and contracts define mocked unit
  checks plus optional live Docker/VPN validation.
