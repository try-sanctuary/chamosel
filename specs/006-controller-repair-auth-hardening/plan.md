# Implementation Plan: Controller Repair and Auth Hardening

**Branch**: `006-controller-repair-auth-hardening` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-controller-repair-auth-hardening/spec.md`

## Summary

Add explicit diagnose-to-repair behavior for `doctor --repair` and harden the controller control plane with configurable authentication for dashboard, pool, metrics, and rotation/repair endpoints. The implementation keeps `doctor` read-only by default, limits repair to one safe action per invocation, treats `public_ip_mismatch` as monitor-only when verified proxy IPs are unique, and keeps post-rotation egress verification configurable.

## Technical Context

**Language/Version**: Python 3.10+ for CLI; Python 3.12-alpine image for controller

**Primary Dependencies**: CLI uses `pyyaml` and `jinja2`; controller remains stdlib-only

**Storage**: Existing controller JSON state file under `/data/state.json`; generated `.env` for local secrets

**Testing**: Python `unittest`, `py_compile`, `git diff --check`; optional live Docker validation

**Target Platform**: Docker Compose deployment on Linux/macOS host with gluetun and HAProxy containers

**Project Type**: CLI plus controller web service and generated Docker Compose stack

**Performance Goals**: Auth check adds no user-visible latency; `doctor --repair` performs at most one bounded repair action per run

**Constraints**: Controller remains stdlib-only; no secrets in logs/JSON/tables/docs; local development workflows must remain possible on loopback

**Scale/Scope**: Existing pool sizes tested in project, including 5-10 gluetun backends; one repair target per doctor invocation

## Constitution Check

- **Control Plane Security**: Pass. This feature adds configurable controller authentication and warnings/fail-safe behavior for non-loopback exposure. Secrets are supplied through config/env and never printed.
- **Health-Aware Rotation**: Pass. Repair uses existing graceful rotation/cooldown/recovery paths and never restarts containers directly.
- **Observability and State**: Pass. Doctor repair decisions, auth configuration status, and repair outcomes are visible in CLI JSON/human output and existing pool/metrics state.
- **Configuration Discipline**: Pass. Affected generated artifacts: `docker-compose.yml`, `.env`, `config.yml.example`, README. Template rendering tests verify env propagation.
- **Testable Operations**: Pass. Automated tests cover auth rejection/success, doctor read-only behavior, doctor repair decisions, mismatch monitor-only behavior, secret-safe output, and compose rendering.

## Project Structure

### Documentation (this feature)

```text
specs/006-controller-repair-auth-hardening/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── controller-auth.md
│   └── doctor-repair.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
chamosel.py                         # CLI config, doctor, status, auth-aware controller calls
controller/controller.py             # stdlib controller auth and repair endpoint behavior
templates/docker-compose.yml.j2      # generated controller auth env
config.yml.example                   # documented auth/repair config knobs
README.md                            # operator workflow docs
tests/test_controller.py             # controller auth/repair behavior
tests/test_generate.py               # generated config/env coverage
tests/test_verify_leaks.py           # CLI doctor/status/auth behavior
```

**Structure Decision**: Keep the existing single-project layout. No new runtime package or service is needed.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
