# Implementation Plan: Production Security Hardening

**Branch**: `008-prod-security-hardening` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-prod-security-hardening/spec.md`

## Summary

Harden chamosel for production by making unsafe exposure fail closed, separating proxy exposure from controller exposure, keeping diagnostics read-only, serializing rotations per backend, protecting generated secrets, tightening dashboard/session handling, making DNS/egress verification fail closed, and surfacing runtime hardening warnings. The implementation keeps the current Python CLI, stdlib-only controller, Docker Compose deployment, HAProxy proxy layer, and unittest-based verification.

## Technical Context

**Language/Version**: Python 3.10+ for CLI; controller runs on Python 3.12 Alpine and remains stdlib-only.

**Primary Dependencies**: CLI uses `pyyaml` and `jinja2`; controller uses Python stdlib only; HAProxy and gluetun remain Docker runtime services.

**Storage**: Generated files (`docker-compose.yml`, `haproxy.cfg`, `.env`) and controller state file at `/data/state.json`.

**Testing**: `.venv/bin/python -m unittest discover -s tests -v`; `.venv/bin/python -m py_compile chamosel.py controller/controller.py`; `git diff --check`.

**Target Platform**: Docker Compose deployment on Linux/macOS hosts, including Oracle Linux 8.10 production target.

**Project Type**: Python CLI plus stdlib-only controller service with generated Docker Compose and HAProxy config.

**Performance Goals**: Security checks and validation must not materially slow ordinary `generate`/`up`; rotation serialization must only block overlapping requests for the same backend, not the whole pool.

**Constraints**: No secret values in logs, metrics, JSON, README examples, generated docs, or test output. Controller remains dependency-free. Local loopback development remains startable without production exposure acknowledgements.

**Scale/Scope**: Primary live pool size remains 1-10 backends; rotation locking and diagnostics should work for larger pools without global serialization.

## Constitution Check

- **Control Plane Security**: Pass. The feature closes unsafe non-loopback controller/proxy/stats exposure, tightens controller/browser auth, validates egress targets, and protects generated secrets.
- **Health-Aware Rotation**: Pass. The feature preserves gluetun status transitions and HAProxy health checks while adding per-backend in-flight guards, cooldown-safe named rotation, and explicit forced bypass observability.
- **Observability and State**: Pass. New exposure, repair, rotation-in-progress, secret-permission, image, and runtime-hardening findings are visible through generation errors, doctor output, API responses, logs, or tests.
- **Configuration Discipline**: Pass. Affects `config.yml.example`, `docker-compose.yml.j2`, `haproxy.cfg.j2`, `.env` writing, controller env, README, and tests. Validation prevents unsafe drift.
- **Testable Operations**: Pass. Automated tests cover exposure rejection, non-mutating diagnostics, rotation locks, cooldown semantics, secret redaction/permissions, DNS fail-closed behavior, generated templates, and doctor warnings.

## Project Structure

### Documentation (this feature)

```text
specs/008-prod-security-hardening/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── controller-security.md
│   ├── cli-security.md
│   └── generated-config.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
chamosel.py                    # CLI validation, secret file handling, doctor, verification behavior
controller/controller.py       # auth/session handling, read-only refresh, rotation locks, egress validation
controller/Dockerfile          # controller runtime hardening
templates/docker-compose.yml.j2 # generated binds, env references, container hardening
templates/haproxy.cfg.j2       # proxy/stats ACL/auth rendering
config.yml.example             # safe defaults and explicit production exposure settings
README.md                      # production security guidance and migration notes
tests/test_generate.py         # generation, bind, secret, template tests
tests/test_controller.py       # auth, read-only refresh, rotation locking tests
tests/test_verify_leaks.py     # DNS/egress verification fail-closed tests
```

**Structure Decision**: Keep changes in the existing single-project layout. Security behavior crosses CLI generation, controller runtime, templates, and docs; no new package or service is required.

## Complexity Tracking

No constitution violations.
