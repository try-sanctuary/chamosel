# Implementation Plan: Rotation Stress Resilience

**Branch**: `003-rotation-stress-resilience` | **Date**: 2026-06-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-rotation-stress-resilience/spec.md`

## Summary

Improve live rotation behavior after stress testing showed that `rotate/all` can repeatedly pressure a slow provider backend. The implementation will add backend-level rotation cooldown state for recovery failures, distinguish changed-IP success from healthy-but-unchanged and proxy/recovery failures, expose partial-success mass-rotation summaries through the controller, document conservative Surfshark live defaults, and add a repeatable stress validation workflow for leak-only and rotation scenarios.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: Controller remains Python stdlib-only; CLI continues using `pyyaml` and `jinja2`; Docker Compose and gluetun remain runtime dependencies.

**Storage**: Existing controller JSON state file (`STATE_FILE`, default `/data/state.json`) for persisted per-backend rotation state, cooldown windows, counters, and latest outcomes.

**Testing**: Python `unittest`, `py_compile`, `git diff --check`, and documented live validation commands using Docker Compose when credentials are available.

**Target Platform**: Docker Compose deployment on Linux hosts and Docker Desktop/macOS development.

**Project Type**: Python CLI plus controller web service inside Docker Compose.

**Performance Goals**: Mass rotation should return a complete per-backend summary without repeatedly retrying backends already in cooldown; leak-only stress validation should support 100 iterations with a five-backend live pool.

**Constraints**: Preserve gluetun status-transition rotation, avoid container restarts as a primary mechanism, keep controller runtime stdlib-only, avoid leaking credentials in outputs/logs, and keep controller/stats exposure on the existing intended host boundary.

**Scale/Scope**: Existing pool sizes from one backend through at least ten configured backends, with a conservative documented live default of five Surfshark WireGuard backends.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control Plane Security**: PASS. The feature does not add public endpoints or change auth boundaries. Existing controller endpoints remain bound by generated compose settings. New outputs must not include `GLUETUN_API_KEY`, WireGuard private keys, provider credentials, `.env`, or `.env.local` contents.
- **Health-Aware Rotation**: PASS. Rotation continues to use gluetun status transitions and HAProxy health checks. The feature adds clearer forced rotation behavior, cooldown after recovery failures, and mass-rotation partial-success handling.
- **Observability and State**: PASS. `/pool`, `/metrics`, logs, and dashboard-visible state will expose latest outcome and cooldown details. State that helps operators decide when a backend is eligible must persist in the existing state file or be explicitly reported as reset after restart.
- **Configuration Discipline**: PASS. No generated Docker Compose, HAProxy, provider env, or secret format changes are required. README examples must describe safe live defaults without adding real credentials.
- **Testable Operations**: PASS. Automated tests will cover cooldown skipping, forced rotation, outcome labels, partial mass rotation, metrics/pool state, and secret-safe outputs. Quickstart documents live stress validation for leak-only and rotation workflows.

## Project Structure

### Documentation (this feature)

```text
specs/003-rotation-stress-resilience/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── controller-rotation.md
│   └── stress-validation.md
└── tasks.md
```

### Source Code (repository root)

```text
chamosel.py                    # CLI commands, stress validation workflow, docs-visible command help
controller/
└── controller.py              # rotation outcomes, cooldown state, pool/metrics/dashboard responses
tests/
├── test_controller.py         # controller rotation, cooldown, metrics, state tests
├── test_generate.py           # config/template regression tests if generated env changes are touched
└── test_verify_leaks.py       # leak/stress workflow CLI tests
README.md                     # operator guidance and safe live defaults
```

**Structure Decision**: Keep the existing single-project layout. Add behavior to the controller and CLI where those responsibilities already live; add tests beside the existing unittest modules. No new package boundary is needed.

## Phase 0: Research

Research decisions are documented in [research.md](research.md). All technical clarifications are resolved; there are no remaining `NEEDS CLARIFICATION` markers.

## Phase 1: Design & Contracts

Design artifacts:

- [data-model.md](data-model.md)
- [contracts/controller-rotation.md](contracts/controller-rotation.md)
- [contracts/stress-validation.md](contracts/stress-validation.md)
- [quickstart.md](quickstart.md)

## Post-Design Constitution Check

- **Control Plane Security**: PASS. Contracts require secret redaction and no new public exposure.
- **Health-Aware Rotation**: PASS. Data model includes cooldown windows, force behavior, and healthy-but-unchanged outcomes without changing the graceful rotation mechanism.
- **Observability and State**: PASS. Data model and contracts define `/pool`, `/metrics`, dashboard, logs, and persisted state expectations.
- **Configuration Discipline**: PASS. No generated Docker or HAProxy structure changes are planned. README changes are documentation-only for live defaults and stress workflow.
- **Testable Operations**: PASS. Quickstart and contracts define unit, CLI, and live validation expectations for happy path and recovery-timeout/cooldown failure path.

## Complexity Tracking

No constitution violations or justified complexity exceptions.
